"""breakdown_tasks.py — 能力 2：技术方案 → 任务 DAG + Given/When/Then

P1.3 核心入口实现。tools.py 仅 dispatch 到本模块的 ``run`` 函数。

4 步推理链（详见 ARCHITECTURE.md / RECON-HISTORY 8.2）：
  1. Resolve tech_plan：tech_plan_id（从 ADR 还原）或 tech_plan obj（直接用）
     - 检测 feasibility=red / blocking_downstream → 早返 intent error（拒绝触发）
  2. LLM 生成 tasks（含 size / GWT / depends_on / suggested_legion / tech_stack_link）
  3. 校验 + 修正：
     - size > XL 自动再调 LLM 拆（最多 2 轮）
     - GWT 缺字段：兜底标 "<待补>" + warning（不阻塞）
     - id 缺：自动 uuid4
     - depends_on 引用了不存在的 task：剔除 + warning（不阻塞）
  4. 拓扑排序 + 检环：
     - 有环 → return error（intent 级，要求 LLM 上游别再生成）
     - 无环 → 返回 topological_order

关键约束（硬纪律）：
- 单任务 size ≤ XL（≥3 天必须再拆）
- 拓扑必须 DAG（环 → 拒绝）
- 每任务必须含完整 GWT 三段（兜底而非阻塞）
- tasks[].id 用 uuid4
- _BreakdownTasksError 继承 WrappedToolError（防 B-1 重犯）
- 不写 ADR（与 design_tech_plan 不同 — breakdown_tasks 只读不写决策）
- 不引入新 Python 依赖（拓扑排序自实现）

参考：
- .planning/phase1/specs/REQUIREMENTS.md §1.3 (R-FN-2.1 ~ 2.6)
- .planning/phase1/specs/ARCHITECTURE.md §10 扩展点 EngineerProfile
- .planning/phase1/specs/PHASE-PLAN.md §4 (P1.3)
- .planning/phase1/recon/PRD-CAPABILITIES.md 能力 2
- .planning/phase1/recon/RECON-HISTORY.md §8.2
- design_tech_plan.py（复用 _invoke_llm / _extract_content / _parse_llm_json /
  HARDCODED_LEGION_PROFILES / WrappedToolError 模式）
"""
from __future__ import annotations

import json
import pathlib
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from . import adr_storage, design_tech_plan, error_classifier


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROMPT_PATH: pathlib.Path = (
    pathlib.Path(__file__).parent / "templates" / "breakdown-tasks-prompt.md"
)
RESPLIT_PROMPT_PATH: pathlib.Path = (
    pathlib.Path(__file__).parent / "templates" / "breakdown-tasks-resplit-prompt.md"
)

# size → 推荐人天（与 PRD §五·能力 2 单任务 ≤ XL = 3 天对齐）
SIZE_TO_DAYS: Dict[str, float] = {"S": 0.5, "M": 1.0, "L": 2.0, "XL": 3.0}
ALLOWED_SIZES: Set[str] = {"S", "M", "L", "XL"}
MAX_DAYS_HARD_CAP: float = 3.0  # XL 的天数上限；> 此值必须再拆

# size > XL 时自动调 LLM 再拆，最多 2 轮（避免无限循环 + 控制 LLM 成本）
MAX_RESPLIT_ROUNDS: int = 2


# ---------------------------------------------------------------------------
# 异常类（继承 WrappedToolError，防 B-1：retry 用 .level 短路）
# ---------------------------------------------------------------------------


class _BreakdownTasksError(error_classifier.WrappedToolError):
    """本模块专用异常，继承 WrappedToolError 让 retry_with_backoff 走 .level 短路。

    防 B-1（reviewer-p1-2 / 2026-04-25）：原 design_tech_plan 继承 Exception →
    retry 用 classify() 关键词匹配返回 LEVEL_UNKNOWN → 立即抛不重试 → R-NFR-19 /
    ADR-006 技术级重试 3 次实质失效。本模块照 design_tech_plan 修复方案，
    继承 WrappedToolError 让 retry 走 level 短路 → 技术级正常 3 次重试。
    """

    def __init__(self, message: str, level: str = error_classifier.LEVEL_UNKNOWN):
        super().__init__(message, level=level)


# ---------------------------------------------------------------------------
# Public entry — tools.py 调用此函数
# ---------------------------------------------------------------------------


def run(args: Dict[str, Any], **kwargs) -> str:
    """breakdown_tasks 主入口（4 步推理链）。

    返回 JSON 字符串（与其他 AICTO 工具风格一致），所有错误用 4 级分类。
    """
    started_at = time.monotonic()
    warnings: List[str] = []

    # ---- 入参校验（intent 级失败立即返）----
    tech_plan_id = args.get("tech_plan_id")
    tech_plan_obj = args.get("tech_plan")

    if not tech_plan_id and not tech_plan_obj:
        return _fail(
            "must provide one of: tech_plan_id / tech_plan",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 1：Resolve tech_plan（含 red / blocking 拒绝触发）----
    try:
        tech_plan, project_id = _step1_resolve_tech_plan(
            tech_plan_id=tech_plan_id,
            tech_plan_obj=tech_plan_obj,
        )
    except _BreakdownTasksError as e:
        return _fail(
            str(e), level=e.level, elapsed=time.monotonic() - started_at
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        if level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                level,
                e,
                {
                    "phase": "step1_resolve_tech_plan",
                    "tech_plan_id": tech_plan_id,
                    "has_tech_plan_obj": bool(tech_plan_obj),
                },
            )
        return _fail(
            f"step1_resolve_tech_plan: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    # ---- 拒绝触发条件（feasibility=red / blocking_downstream）----
    feasibility = tech_plan.get("feasibility")
    if feasibility == "red":
        return _fail(
            "tech_plan feasibility=red, breakdown blocked. "
            "red 必须先变绿才能拆任务（参考 tech_plan.improvement_path）",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )
    if tech_plan.get("blocking_downstream") is True:
        return _fail(
            "tech_plan has unresolved missing_info (blocking_downstream=true), "
            "breakdown blocked. PM 需先补全 missing_info 后再触发",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    project_name = tech_plan.get("project_name") or "未命名项目"
    summary = tech_plan.get("summary") or ""
    tech_stack: List[Dict[str, Any]] = tech_plan.get("tech_stack") or []
    estimate: Dict[str, Any] = tech_plan.get("estimate") or {}
    risks: List[Dict[str, Any]] = tech_plan.get("risks") or []
    legion_info = design_tech_plan.HARDCODED_LEGION_PROFILES

    if not tech_stack:
        return _fail(
            "tech_plan.tech_stack is empty — nothing to break down. "
            "请先调 design_tech_plan 生成有效 tech_stack",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # 拉历史 ADR（best-effort，失败不阻塞）
    adr_history: List[Dict[str, Any]] = []
    if project_id:
        try:
            adr_history = adr_storage.list_adrs(project_id) or []
        except Exception as e:  # noqa: BLE001
            print(f"[breakdown_tasks] adr_history read failed: {e}")
            adr_history = []

    # ---- Step 2：LLM 生成 tasks ----
    try:
        tasks_raw = _step2_llm_breakdown(
            project_name=project_name,
            summary=summary,
            feasibility=feasibility or "yellow",
            tech_stack=tech_stack,
            estimate=estimate,
            risks=risks,
            legion_info=legion_info,
            adr_history=adr_history,
        )
    except _BreakdownTasksError as e:
        return _fail(
            str(e), level=e.level, elapsed=time.monotonic() - started_at
        )
    except error_classifier.WrappedToolError as e:
        # retry_with_backoff 用尽 → 升级
        error_classifier.escalate_to_owner(
            e.level,
            e,
            {
                "phase": "step2_llm_breakdown",
                "tech_plan_id": tech_plan_id,
                "project_id": project_id,
            },
        )
        return _fail(
            f"step2_llm_breakdown exhausted: {e}",
            level=e.level,
            elapsed=time.monotonic() - started_at,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        error_classifier.escalate_to_owner(
            level,
            e,
            {"phase": "step2_llm_breakdown", "project_id": project_id},
        )
        return _fail(
            f"step2_llm_breakdown: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 3：校验 + 修正 ----
    # 3a. size > XL 自动再拆（最多 MAX_RESPLIT_ROUNDS 轮）
    tasks_after_resplit, resplit_warnings = _resplit_oversized_tasks(
        tasks_raw,
        project_name=project_name,
        summary=summary,
        feasibility=feasibility or "yellow",
        tech_stack=tech_stack,
        estimate=estimate,
        risks=risks,
        legion_info=legion_info,
        adr_history=adr_history,
    )
    warnings.extend(resplit_warnings)

    # 3b. 字段兜底（id / GWT / size 等）
    tasks_normalized, norm_warnings = _normalize_tasks(tasks_after_resplit)
    warnings.extend(norm_warnings)

    # 3c. depends_on 引用真实 id 校验（剔除非法 + warning）
    tasks_clean, dep_warnings = _clean_dependency_references(tasks_normalized)
    warnings.extend(dep_warnings)

    # ---- Step 4：拓扑排序 + 检环 ----
    try:
        topo_order, edges = _topological_sort(tasks_clean)
    except _BreakdownTasksError as e:
        return _fail(
            str(e), level=e.level, elapsed=time.monotonic() - started_at
        )

    # ---- 返回 ----
    elapsed = time.monotonic() - started_at
    return _success(
        {
            "tasks": tasks_clean,
            "dependency_graph": {
                "edges": edges,
                "is_dag": True,
                "topological_order": topo_order,
            },
            "tech_plan_id": tech_plan_id,
            "project_id": project_id,
            "project_name": project_name,
            "warnings": warnings or None,
            "elapsed_seconds": round(elapsed, 2),
        }
    )


# ---------------------------------------------------------------------------
# Step 1: Resolve tech_plan
# ---------------------------------------------------------------------------


def _step1_resolve_tech_plan(
    *,
    tech_plan_id: Optional[str],
    tech_plan_obj: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """二选一加载 tech_plan。

    优先级：tech_plan_obj > tech_plan_id（obj 完整无歧义；id 需从 ADR 还原）

    返回 (tech_plan_dict, project_id)。
    """
    # 直传 obj — 直接用
    if tech_plan_obj:
        if not isinstance(tech_plan_obj, dict):
            raise _BreakdownTasksError(
                f"tech_plan must be a dict, got {type(tech_plan_obj).__name__}",
                level=error_classifier.LEVEL_INTENT,
            )
        # tech_plan_obj 里如果带 project_id 就用，没有就 None
        proj_id = tech_plan_obj.get("project_id")
        # 至少要有 tech_stack（其他字段都有兜底）
        if not tech_plan_obj.get("tech_stack"):
            raise _BreakdownTasksError(
                "tech_plan.tech_stack is missing or empty — nothing to break down",
                level=error_classifier.LEVEL_INTENT,
            )
        return tech_plan_obj, proj_id

    # 用 tech_plan_id 从 ADR 还原 tech_plan
    # tech_plan_id 在 P1.2 实现里其实是 project_id（design_tech_plan 输出的
    # adr_ids 没有单独的 plan_id，而是用 project_id 去拉所有 ADR 重组 tech_stack）
    # 详见 RECON-HISTORY 8.2 与 design_tech_plan.run 输出契约
    if not tech_plan_id:
        raise _BreakdownTasksError(
            "no tech_plan source provided",
            level=error_classifier.LEVEL_INTENT,
        )

    try:
        adrs = adr_storage.list_adrs(tech_plan_id) or []
    except Exception as e:  # noqa: BLE001
        # 读 ADR 失败：可能是 db 损坏 / 路径问题 — 走分类
        level = error_classifier.classify(e)
        raise _BreakdownTasksError(
            f"failed to load ADRs for tech_plan_id={tech_plan_id}: {e}",
            level=level,
        )

    if not adrs:
        raise _BreakdownTasksError(
            f"no ADRs found for tech_plan_id={tech_plan_id}. "
            f"tech_plan_id 应等于 design_tech_plan 输出的 project_id（含已写入的 ADR）。"
            f"如果是直接给 tech_plan dict，请改传 tech_plan 参数",
            level=error_classifier.LEVEL_INTENT,
        )

    # 把 ADR 还原成 tech_stack 项
    tech_stack: List[Dict[str, Any]] = []
    for adr in adrs:
        title = adr.get("title") or ""
        # design_tech_plan 写 ADR 的 title 形如：「选择 X 作为 Y」
        component, choice = _parse_adr_title(title)
        tech_stack.append(
            {
                "component": component,
                "choice": choice or adr.get("decision") or "",
                "reason": adr.get("rationale") or "",
                "alternatives_considered": adr.get("alternatives_considered") or [],
                "adr_id": adr.get("id"),
                "adr_display_number": adr.get("display_number"),
            }
        )

    plan = {
        "feasibility": "yellow",  # 没存 → 默认保守 yellow（不阻塞 breakdown）
        "summary": f"从 ADR 还原（共 {len(adrs)} 条决策）",
        "tech_stack": tech_stack,
        "estimate": {},
        "risks": [],
        "missing_info": [],
        "blocking_downstream": False,
        "project_id": tech_plan_id,
        "project_name": _resolve_project_name_safe(tech_plan_id),
    }
    return plan, tech_plan_id


def _parse_adr_title(title: str) -> Tuple[str, str]:
    """从 design_tech_plan 写的 ADR title 反解 (component, choice)。

    格式：'选择 {choice} 作为 {component}'。
    解析失败返回 ('unknown', title)。
    """
    if not title:
        return ("unknown", "")
    # 正则替代：保持 stdlib only
    if title.startswith("选择 ") and " 作为 " in title:
        body = title[len("选择 "):]
        try:
            choice, component = body.split(" 作为 ", 1)
            return (component.strip(), choice.strip())
        except ValueError:
            pass
    return ("unknown", title)


def _resolve_project_name_safe(project_id: str) -> str:
    """通过 pm_db_api 拿 Project.name；失败兜底为 project_id。"""
    try:
        from . import pm_db_api  # 延迟 import 避免循环

        raw = pm_db_api.read_pm_project({"project_id": project_id})
        payload = json.loads(raw)
        if "error" in payload:
            return project_id
        return (payload.get("project") or {}).get("name") or project_id
    except Exception:  # noqa: BLE001
        return project_id


# ---------------------------------------------------------------------------
# Step 2: LLM 生成 tasks
# ---------------------------------------------------------------------------


def _load_prompt_template() -> str:
    if not PROMPT_PATH.exists():
        raise _BreakdownTasksError(
            f"prompt template missing: {PROMPT_PATH}",
            level=error_classifier.LEVEL_UNKNOWN,
        )
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_resplit_prompt_template() -> str:
    if not RESPLIT_PROMPT_PATH.exists():
        raise _BreakdownTasksError(
            f"resplit prompt template missing: {RESPLIT_PROMPT_PATH}",
            level=error_classifier.LEVEL_UNKNOWN,
        )
    return RESPLIT_PROMPT_PATH.read_text(encoding="utf-8")


def _summarize_tech_stack(tech_stack: List[Dict[str, Any]]) -> str:
    if not tech_stack:
        return "（空）"
    lines: List[str] = []
    for i, item in enumerate(tech_stack, 1):
        comp = item.get("component", "?")
        choice = item.get("choice", "?")
        reason = (item.get("reason") or "").replace("\n", " ")
        if len(reason) > 200:
            reason = reason[:200] + "..."
        lines.append(f"  {i}. component={comp} | choice={choice} | reason={reason}")
    return "\n".join(lines)


def _summarize_risks(risks: List[Dict[str, Any]]) -> str:
    if not risks:
        return "（无）"
    lines: List[str] = []
    for r in risks[:10]:
        title = r.get("title") or "?"
        sev = r.get("severity") or "?"
        mit = (r.get("mitigation") or "").replace("\n", " ")
        if len(mit) > 120:
            mit = mit[:120] + "..."
        lines.append(f"  - [{sev}] {title} | 缓解：{mit}")
    return "\n".join(lines)


def _summarize_legion(legion_info: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"  - {l['commander_name']}: 擅长 {','.join(l['tech_stack_tags'][:5])} "
        f"| 项目偏好 {','.join(l['project_affinity'][:3])}"
        for l in legion_info
    )


def _summarize_adrs(adr_history: List[Dict[str, Any]]) -> str:
    if not adr_history:
        return "（无）"
    lines = []
    for adr in adr_history[:15]:
        lines.append(
            f"  - {adr.get('display_number') or adr.get('number')}: "
            f"{adr.get('title')} | status={adr.get('status')}"
        )
    return "\n".join(lines)


def _build_messages(
    *,
    project_name: str,
    summary: str,
    feasibility: str,
    tech_stack: List[Dict[str, Any]],
    estimate: Dict[str, Any],
    risks: List[Dict[str, Any]],
    legion_info: List[Dict[str, Any]],
    adr_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    template = _load_prompt_template()
    rendered = (
        template.replace("{{PROJECT_NAME}}", project_name or "")
        .replace("{{TECH_PLAN_SUMMARY}}", summary or "（未提供 summary）")
        .replace("{{FEASIBILITY}}", feasibility)
        .replace("{{TECH_STACK}}", _summarize_tech_stack(tech_stack))
        .replace(
            "{{ESTIMATE}}",
            json.dumps(estimate, ensure_ascii=False) if estimate else "（未提供）",
        )
        .replace("{{RISKS}}", _summarize_risks(risks))
        .replace("{{LEGION_INFO}}", _summarize_legion(legion_info))
        .replace("{{ADR_HISTORY}}", _summarize_adrs(adr_history))
    )
    return [
        {
            "role": "system",
            "content": (
                "你是程小远，云智 OPC 团队的 AI CTO。严格按用户消息中的契约输出 JSON。"
                "不要任何 markdown 围栏。不要任何解释性前后缀。"
            ),
        },
        {"role": "user", "content": rendered},
    ]


def _build_resplit_messages(
    *,
    last_tasks: List[Dict[str, Any]],
    oversized: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    template = _load_resplit_prompt_template()
    # 标记超标任务
    last_tasks_marked: List[Dict[str, Any]] = []
    oversized_ids = {t.get("id") for t in oversized}
    for t in last_tasks:
        marked = dict(t)
        if t.get("id") in oversized_ids:
            marked["__warning__"] = "⚠️ size 超标，必须再拆"
        last_tasks_marked.append(marked)

    oversized_summary = "\n".join(
        f"  - id={t.get('id')} | size={t.get('size')} | "
        f"estimate_days={t.get('estimate_days')} | title={t.get('title')}"
        for t in oversized
    )
    rendered = template.replace(
        "{{LAST_TASKS_JSON}}",
        json.dumps(last_tasks_marked, ensure_ascii=False, indent=2),
    ).replace("{{OVERSIZED_TASKS}}", oversized_summary)

    return [
        {
            "role": "system",
            "content": (
                "你是程小远。本轮职责单一：把 size 超标的任务拆成 ≤ XL 的子任务。"
                "严格输出 JSON，不要 markdown 围栏。"
            ),
        },
        {"role": "user", "content": rendered},
    ]


def _step2_llm_breakdown(
    *,
    project_name: str,
    summary: str,
    feasibility: str,
    tech_stack: List[Dict[str, Any]],
    estimate: Dict[str, Any],
    risks: List[Dict[str, Any]],
    legion_info: List[Dict[str, Any]],
    adr_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """发给 LLM → 解 JSON → 返回 tasks list（带 retry 包裹）。"""
    messages = _build_messages(
        project_name=project_name,
        summary=summary,
        feasibility=feasibility,
        tech_stack=tech_stack,
        estimate=estimate,
        risks=risks,
        legion_info=legion_info,
        adr_history=adr_history,
    )

    def _do_call() -> List[Dict[str, Any]]:
        response = design_tech_plan._invoke_llm(messages)
        content = design_tech_plan._extract_content(response)
        parsed = design_tech_plan._parse_llm_json(content)
        return _coerce_tasks_payload(parsed)

    return error_classifier.retry_with_backoff(
        _do_call, max_retries=3, base_delay=2.0
    )


def _coerce_tasks_payload(parsed: Any) -> List[Dict[str, Any]]:
    """LLM 输出可能是 {"tasks": [...]} 或裸 [...]，统一抽出 tasks list。"""
    if isinstance(parsed, dict):
        tasks = parsed.get("tasks")
        if isinstance(tasks, list):
            return tasks
        # 兜底：第一个值是 list 也接受
        for v in parsed.values():
            if isinstance(v, list):
                return v
        raise _BreakdownTasksError(
            f"LLM JSON missing 'tasks' key; got keys={list(parsed.keys())}",
            level=error_classifier.LEVEL_TECH,  # 让 retry 触发
        )
    if isinstance(parsed, list):
        return parsed
    raise _BreakdownTasksError(
        f"LLM JSON not a dict or list; type={type(parsed).__name__}",
        level=error_classifier.LEVEL_TECH,
    )


# ---------------------------------------------------------------------------
# Step 3a: size > XL 再拆（最多 MAX_RESPLIT_ROUNDS 轮）
# ---------------------------------------------------------------------------


def _resplit_oversized_tasks(
    tasks: List[Dict[str, Any]],
    *,
    project_name: str,
    summary: str,
    feasibility: str,
    tech_stack: List[Dict[str, Any]],
    estimate: Dict[str, Any],
    risks: List[Dict[str, Any]],
    legion_info: List[Dict[str, Any]],
    adr_history: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """检测 size 超标的任务并调 LLM 再拆，最多 MAX_RESPLIT_ROUNDS 轮。

    超标判定：
      - size 字段值不在 ALLOWED_SIZES 之内（如 "XXL"）
      - 或 estimate_days > MAX_DAYS_HARD_CAP

    Returns:
        (refined_tasks, warnings)
    """
    warnings: List[str] = []
    current = tasks

    for round_num in range(1, MAX_RESPLIT_ROUNDS + 1):
        oversized = _find_oversized(current)
        if not oversized:
            return current, warnings

        warnings.append(
            f"resplit round #{round_num}: {len(oversized)} 个任务 size 超标 "
            f"(>{MAX_DAYS_HARD_CAP} 天 / size ∉ {{S,M,L,XL}})，已调 LLM 再拆"
        )

        try:
            new_tasks = _invoke_resplit(current, oversized)
        except _BreakdownTasksError as e:
            warnings.append(
                f"resplit round #{round_num} failed: {e}. 保留上一轮输出 + 强制降级"
            )
            return _force_clamp_oversized(current, warnings), warnings
        except error_classifier.WrappedToolError as e:
            warnings.append(
                f"resplit round #{round_num} retry exhausted: {e}. 强制降级"
            )
            return _force_clamp_oversized(current, warnings), warnings
        except Exception as e:  # noqa: BLE001
            warnings.append(
                f"resplit round #{round_num} unexpected: {e}. 强制降级"
            )
            return _force_clamp_oversized(current, warnings), warnings

        current = new_tasks

    # 用尽轮数仍有超标 → 强制 clamp（标记为 XL 并加 warning，避免阻塞）
    leftover = _find_oversized(current)
    if leftover:
        warnings.append(
            f"resplit 用尽 {MAX_RESPLIT_ROUNDS} 轮后仍有 {len(leftover)} 个超标任务，"
            f"强制 clamp size=XL（PM 需手动复核）"
        )
        return _force_clamp_oversized(current, warnings), warnings
    return current, warnings


def _find_oversized(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """找出 size 不合规的任务。"""
    oversized: List[Dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        size = t.get("size")
        days = t.get("estimate_days")
        # size 非法
        if size is not None and size not in ALLOWED_SIZES:
            oversized.append(t)
            continue
        # estimate_days 超 XL
        if isinstance(days, (int, float)) and days > MAX_DAYS_HARD_CAP:
            oversized.append(t)
            continue
    return oversized


def _force_clamp_oversized(
    tasks: List[Dict[str, Any]], warnings: List[str]
) -> List[Dict[str, Any]]:
    """LLM 拆失败兜底：把超标任务硬 clamp 到 XL（保住下游 dispatch 不挂）。"""
    out: List[Dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            out.append(t)
            continue
        size = t.get("size")
        days = t.get("estimate_days")
        clamped = dict(t)
        if size not in ALLOWED_SIZES:
            clamped["size"] = "XL"
        if isinstance(days, (int, float)) and days > MAX_DAYS_HARD_CAP:
            clamped["estimate_days"] = MAX_DAYS_HARD_CAP
        out.append(clamped)
    return out


def _invoke_resplit(
    last_tasks: List[Dict[str, Any]],
    oversized: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """调 LLM 让它把超标任务拆开（带 retry 包裹）。"""
    messages = _build_resplit_messages(last_tasks=last_tasks, oversized=oversized)

    def _do_call() -> List[Dict[str, Any]]:
        response = design_tech_plan._invoke_llm(messages)
        content = design_tech_plan._extract_content(response)
        parsed = design_tech_plan._parse_llm_json(content)
        return _coerce_tasks_payload(parsed)

    return error_classifier.retry_with_backoff(
        _do_call, max_retries=2, base_delay=2.0
    )


# ---------------------------------------------------------------------------
# Step 3b: 字段兜底（id / size / estimate_days / GWT / suggested_legion）
# ---------------------------------------------------------------------------


def _normalize_tasks(
    tasks: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """字段补救：id / size / estimate_days / GWT 三段 / suggested_legion / tech_stack_link。

    缺失字段不抛错，记 warning 后用合理默认补上。
    非 dict 元素直接剔除（同时 warning）。
    """
    warnings: List[str] = []
    valid_legions = {p["commander_name"] for p in design_tech_plan.HARDCODED_LEGION_PROFILES}
    out: List[Dict[str, Any]] = []
    used_ids: Set[str] = set()

    for idx, raw in enumerate(tasks):
        if not isinstance(raw, dict):
            warnings.append(
                f"task #{idx} not a dict (got {type(raw).__name__}), skipped"
            )
            continue

        t = dict(raw)  # 不要破坏原 dict（resplit 可能复用）

        # id 兜底（缺 / 重复 → 重新生成）
        tid = t.get("id")
        if not isinstance(tid, str) or not tid.strip() or tid in used_ids:
            new_id = _new_task_id()
            if tid in used_ids:
                warnings.append(
                    f"task #{idx} id duplicate ({tid!r}) → 替换为 {new_id}"
                )
            t["id"] = new_id
        used_ids.add(t["id"])

        # size 兜底
        size = t.get("size")
        if size not in ALLOWED_SIZES:
            # 之前的 force_clamp 兜底应该已经处理过；这里再保险
            warnings.append(
                f"task {t['id']} size={size!r} 非法（应 ∈ {sorted(ALLOWED_SIZES)}），"
                f"兜底为 'M'"
            )
            t["size"] = "M"

        # estimate_days 兜底（与 size 对齐）
        days = t.get("estimate_days")
        if not isinstance(days, (int, float)) or days <= 0:
            t["estimate_days"] = SIZE_TO_DAYS[t["size"]]
            warnings.append(
                f"task {t['id']} estimate_days 缺失/非法，兜底为 {t['estimate_days']}（按 size={t['size']}）"
            )
        elif days > MAX_DAYS_HARD_CAP:
            # 已经 clamp 过；保险再 clamp 一次
            t["estimate_days"] = MAX_DAYS_HARD_CAP

        # depends_on 兜底（必须是 list）
        deps = t.get("depends_on")
        if deps is None:
            t["depends_on"] = []
        elif not isinstance(deps, list):
            warnings.append(
                f"task {t['id']} depends_on 非 list（{type(deps).__name__}），兜底为 []"
            )
            t["depends_on"] = []
        else:
            # 过滤非 str 项
            t["depends_on"] = [d for d in deps if isinstance(d, str) and d.strip()]

        # acceptance_gwt 三段兜底
        gwt = t.get("acceptance_gwt")
        if not isinstance(gwt, dict):
            t["acceptance_gwt"] = {
                "given": "<待补>",
                "when": "<待补>",
                "then": "<待补>",
            }
            warnings.append(
                f"task {t['id']} acceptance_gwt 缺失或非 dict，三段全兜底为 '<待补>'"
            )
        else:
            new_gwt = {}
            for k in ("given", "when", "then"):
                v = gwt.get(k)
                if not isinstance(v, str) or not v.strip():
                    new_gwt[k] = "<待补>"
                    warnings.append(
                        f"task {t['id']} acceptance_gwt.{k} 缺失，兜底为 '<待补>'"
                    )
                else:
                    new_gwt[k] = v.strip()
            t["acceptance_gwt"] = new_gwt

        # suggested_legion 兜底（必须 ∈ 8 军团）
        legion = t.get("suggested_legion")
        if legion not in valid_legions:
            # tech_stack_link 启发式匹配
            picked = _pick_legion_by_tech_stack_link(t.get("tech_stack_link") or [])
            t["suggested_legion"] = picked
            warnings.append(
                f"task {t['id']} suggested_legion={legion!r} 非法/缺失，"
                f"按 tech_stack_link 启发式分配为 {picked}"
            )

        # tech_stack_link 兜底
        link = t.get("tech_stack_link")
        if not isinstance(link, list) or not link:
            t["tech_stack_link"] = ["unknown"]
            warnings.append(
                f"task {t['id']} tech_stack_link 缺失或非 list，兜底为 ['unknown']"
            )
        else:
            t["tech_stack_link"] = [s for s in link if isinstance(s, str) and s.strip()]
            if not t["tech_stack_link"]:
                t["tech_stack_link"] = ["unknown"]

        # title / description 兜底（避免下游 dispatch 见空）
        if not isinstance(t.get("title"), str) or not t["title"].strip():
            t["title"] = f"未命名任务 {t['id'][:8]}"
            warnings.append(f"task {t['id']} title 缺失，兜底为占位")
        if not isinstance(t.get("description"), str):
            t["description"] = ""

        out.append(t)

    return out, warnings


def _new_task_id() -> str:
    """生成 task id（uuid4 + task- 前缀，便于人工识别）。"""
    return f"task-{uuid.uuid4()}"


def _pick_legion_by_tech_stack_link(link: List[str]) -> str:
    """按 tech_stack_link 关键词启发式匹配军团；命中失败返回 L1-麒麟军团（默认 backend）。"""
    text = " ".join(link).lower()
    # 简单关键词映射
    if any(k in text for k in ("frontend", "ui", "react", "next", "tailwind", "前端")):
        return "L1-凤凰军团"
    if any(k in text for k in ("ai", "llm", "embedding", "ml", "pytorch", "model")):
        return "L1-昆仑军团"
    if any(k in text for k in ("devops", "docker", "k8s", "ci", "cd", "monitor")):
        return "L1-青龙军团"
    if any(k in text for k in ("mobile", "ios", "android", "flutter", "rn")):
        return "L1-星辰军团"
    if any(k in text for k in ("data", "spark", "hadoop", "clickhouse", "minio", "大数据")):
        return "L1-鲲鹏军团"
    if any(k in text for k in ("urgent", "poc", "原型", "rapid")):
        return "L1-暴风军团"
    # database / observability / mq / cache / search / backend / 其他 → 麒麟（默认）
    return "L1-麒麟军团"


# ---------------------------------------------------------------------------
# Step 3c: depends_on 引用真实 id 校验
# ---------------------------------------------------------------------------


def _clean_dependency_references(
    tasks: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """剔除 depends_on 中引用了不存在的 task id 的项；同时禁止自引用。"""
    warnings: List[str] = []
    valid_ids: Set[str] = {t["id"] for t in tasks}
    out: List[Dict[str, Any]] = []
    for t in tasks:
        deps = t.get("depends_on") or []
        cleaned: List[str] = []
        for dep in deps:
            if dep == t["id"]:
                warnings.append(
                    f"task {t['id']} 自引用 depends_on={dep}，已剔除"
                )
                continue
            if dep not in valid_ids:
                warnings.append(
                    f"task {t['id']} depends_on={dep} 引用了不存在的 task id，已剔除"
                )
                continue
            cleaned.append(dep)
        nt = dict(t)
        nt["depends_on"] = cleaned
        out.append(nt)
    return out, warnings


# ---------------------------------------------------------------------------
# Step 4: 拓扑排序 + 检环（Kahn 算法，无新依赖）
# ---------------------------------------------------------------------------


def _topological_sort(
    tasks: List[Dict[str, Any]],
) -> Tuple[List[str], List[Dict[str, str]]]:
    """Kahn 算法拓扑排序；有环抛 _BreakdownTasksError(intent)。

    Returns:
        (topological_order: list[task_id], edges: list[{"from", "to"}])
        edges 表示 from → to（依赖关系：to depends on from，from 必须先完成）。
    """
    if not tasks:
        return [], []

    # 构建邻接表 + 入度表
    # depends_on: t.depends_on = [pre_id, ...]，意为 t 依赖 pre_id（pre 先完成）
    # edge: from=pre → to=t（拓扑顺序 pre 在前）
    incoming: Dict[str, int] = {t["id"]: 0 for t in tasks}
    outgoing: Dict[str, List[str]] = {t["id"]: [] for t in tasks}
    edges: List[Dict[str, str]] = []

    for t in tasks:
        tid = t["id"]
        for pre in t.get("depends_on") or []:
            if pre not in incoming:
                # 非法引用应已在 step 3c 剔除；保险跳过
                continue
            outgoing[pre].append(tid)
            incoming[tid] += 1
            edges.append({"from": pre, "to": tid})

    # Kahn 算法：起始入度为 0 的节点
    # 用稳定顺序（按 tasks 顺序）便于 deterministic 输出
    order: List[str] = []
    queue: List[str] = [t["id"] for t in tasks if incoming[t["id"]] == 0]

    visited: Set[str] = set()
    while queue:
        # FIFO（保稳定）
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        order.append(node)
        # 邻接节点入度 -1
        for nxt in outgoing[node]:
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(tasks):
        # 有环 — 找出环中的节点（入度 > 0 的剩余节点）
        cycle_nodes = [tid for tid, deg in incoming.items() if deg > 0]
        raise _BreakdownTasksError(
            f"dependency cycle detected: {len(cycle_nodes)} tasks in cycle "
            f"(node ids head: {cycle_nodes[:10]}). DAG 无环是硬纪律 — "
            f"通常意味着 LLM 拆任务时给出了循环依赖，请重新 design_tech_plan 或人工修正",
            level=error_classifier.LEVEL_INTENT,
        )

    return order, edges


# ---------------------------------------------------------------------------
# 公共辅助
# ---------------------------------------------------------------------------


def _success(payload: Dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _fail(message: str, *, level: str, elapsed: float) -> str:
    return json.dumps(
        {
            "error": message,
            "level": level,
            "elapsed_seconds": round(elapsed, 2),
        },
        ensure_ascii=False,
    )


__all__ = [
    "run",
    "SIZE_TO_DAYS",
    "ALLOWED_SIZES",
    "MAX_DAYS_HARD_CAP",
    "MAX_RESPLIT_ROUNDS",
]
