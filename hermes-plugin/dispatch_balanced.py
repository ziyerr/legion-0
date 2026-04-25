"""dispatch_balanced.py — 能力 3：智能调度（负载均衡 + DAG 拓扑延派）

P1.4 核心入口实现。tools.py 仅 dispatch 到本模块的 ``run`` 函数。

5 步推理链（详见 ARCHITECTURE.md §4.4 / §5.3 / RECON-REFERENCE §6）：
  1. 入参校验 + 拉项目上下文（PRD 摘要 + tech_plan + ADR）
  2. Discover 在线军团（filter status=commanding；alive 优先）
  3. 拓扑划分 ready / deferred（depends_on 为空 → ready；非空 → deferred）
  4. 负载均衡分配 ready tasks（suggested_legion 优先；
     tech_stack_link 启发式打分；单军团并发 ≤2）
  5. 双通道派单（legion_api.send_to_commander → inbox + tmux 通知）

关键约束（硬纪律）：
- CTO 拥有调度决策权，军团必须接（可 appeal 不可拒）— 派单不需军团确认
- 单军团并发 ≤2（派前查 + 排队，超载进 deferred）
- DAG 依赖未就绪的任务延派
- payload 三段必齐：PRD 摘要（≤500 字）+ 技术方案（≤1000 字）+ GWT 验收
- mailbox 协议向后兼容（用 legion_api.mailbox_protocol_serialize，不自构造）
- 双通道双发：inbox.json + tmux send-keys 一行通知
- EngineerProfile hardcoded 复用 design_tech_plan.HARDCODED_LEGION_PROFILES
- 单 task 派失败 → warning + deferred；不阻塞整批
- _DispatchBalancedError 继承 WrappedToolError（防 B-1 重犯）

参考：
- .planning/phase1/specs/REQUIREMENTS.md §1.4 R-FN-3.1 ~ 3.9
- .planning/phase1/specs/ARCHITECTURE.md §4.4 / §5.3
- .planning/phase1/specs/PHASE-PLAN.md §5
- .planning/phase1/recon/PRD-CAPABILITIES.md 能力 3
- .planning/phase1/recon/RECON-REFERENCE.md §6（ProdMind 双通道参照）
- legion_api.py（API 完整签名 — discover / send / mailbox_protocol_serialize）
- design_tech_plan.HARDCODED_LEGION_PROFILES（8 军团技能/项目偏好）
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from . import adr_storage, design_tech_plan, error_classifier, legion_api, pm_db_api


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 单军团并发上限（PRD §五·能力 3 + R-FN-3.3）
MAX_CONCURRENT_TASKS_PER_LEGION: int = 2

# size → priority 映射（mailbox 协议 priority 字段）
# XL=high（最近 deadline 紧）/ L,M=normal / S=low
SIZE_TO_PRIORITY: Dict[str, str] = {
    "XL": "high",
    "L": "normal",
    "M": "normal",
    "S": "low",
}

# payload 三段字符限制（避免 inbox 过大；详见 ARCHITECTURE §4.4）
PRD_SUMMARY_CHAR_LIMIT: int = 500
TECH_PLAN_CHAR_LIMIT: int = 1000

# payload 概要回显（assignment.payload_summary 用，便于审计）
PAYLOAD_SUMMARY_CHAR_LIMIT: int = 200


# ---------------------------------------------------------------------------
# 异常类（继承 WrappedToolError，防 B-1：retry 用 .level 短路）
# ---------------------------------------------------------------------------


class _DispatchBalancedError(error_classifier.WrappedToolError):
    """本模块专用异常，继承 WrappedToolError 让 retry_with_backoff 走 .level 短路。

    防 B-1（reviewer-p1-2 / 2026-04-25）：原 design_tech_plan 继承 Exception →
    retry 用 classify() 关键词匹配返回 LEVEL_UNKNOWN → 立即抛不重试 →
    R-NFR-19 / ADR-006 技术级重试 3 次实质失效。本模块照 design_tech_plan /
    breakdown_tasks 修复方案，继承 WrappedToolError 让 retry 走 level 短路。
    """

    def __init__(
        self,
        message: str,
        level: str = error_classifier.LEVEL_UNKNOWN,
    ) -> None:
        super().__init__(message, level=level)


# ---------------------------------------------------------------------------
# Public entry — tools.py 调用此函数
# ---------------------------------------------------------------------------


def run(args: Dict[str, Any], **kwargs) -> str:
    """dispatch_to_legion_balanced 主入口（5 步推理链）。

    返回 JSON 字符串（与其他 AICTO 工具风格一致），所有错误用 4 级分类。
    """
    started_at = time.monotonic()
    warnings: List[str] = []

    # ---- 入参校验（intent 级失败立即返）----
    tasks = args.get("tasks")
    project_id = args.get("project_id")

    if not tasks or not isinstance(tasks, list):
        return _fail(
            "tasks must be a non-empty list",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )
    if not project_id or not isinstance(project_id, str):
        return _fail(
            "project_id is required (string)",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 1：拉项目上下文（best-effort，缺数据走 warnings）----
    ctx = _step1_load_project_context(project_id, warnings)

    # ---- Step 2：Discover 在线军团 ----
    try:
        commanders = legion_api.discover_online_commanders()
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        if level in (
            error_classifier.LEVEL_PERMISSION,
            error_classifier.LEVEL_UNKNOWN,
        ):
            error_classifier.escalate_to_owner(
                level,
                e,
                {"phase": "step2_discover", "project_id": project_id},
            )
        return _fail(
            f"step2_discover_online_commanders: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    if not commanders:
        return _fail(
            "no online legion available (directory.json empty / "
            "no commander with status='commanding'). "
            "请先用 legion.sh 拉起军团或检查 ~/.claude/legion/directory.json",
            level=error_classifier.LEVEL_TECH,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 3：拓扑划分 ready / deferred ----
    ready_tasks, deferred_initial, split_warnings = _step3_split_ready_deferred(tasks)
    warnings.extend(split_warnings)

    # ---- Step 4 + 5：负载均衡 + 双通道派单 ----
    assignments, deferred_post, dispatch_warnings = _step4_5_dispatch_with_balance(
        ready_tasks=ready_tasks,
        commanders=commanders,
        ctx=ctx,
    )
    warnings.extend(dispatch_warnings)

    # ---- 返回 ----
    elapsed = time.monotonic() - started_at
    return _success(
        {
            "assignments": assignments,
            "deferred": deferred_initial + deferred_post,
            "warnings": warnings or None,
            "elapsed_seconds": round(elapsed, 2),
            "project_id": project_id,
            "online_legion_count": len(commanders),
            "ready_count": len(ready_tasks),
        }
    )


# ---------------------------------------------------------------------------
# Step 1: 拉项目上下文（PRD 摘要 + tech_plan + ADR）
# ---------------------------------------------------------------------------


def _step1_load_project_context(
    project_id: str,
    warnings: List[str],
) -> Dict[str, Any]:
    """读 Project + 最新 PRD + ADR 历史（best-effort）。

    任一子步失败：记 warning 后继续（payload 缺数据时降级提示，不阻塞）。
    """
    ctx: Dict[str, Any] = {
        "project_id": project_id,
        "project_name": project_id,  # 兜底
        "prd_id": None,
        "prd_title": "未命名 PRD",
        "prd_content": "",
        "tech_stack": [],
        "adr_ids": [],
        "feishu_doc_url": None,  # Phase 1 暂不接（design_tech_plan 输出含此 URL，
                                  # 但 dispatch 拿不到 plan obj — 需等 Phase 2 改 schema）
    }

    # 1a. Project name
    try:
        raw = pm_db_api.read_pm_project({"project_id": project_id})
        payload = json.loads(raw)
        if "error" not in payload:
            project = payload.get("project") or {}
            ctx["project_name"] = project.get("name") or project_id
        else:
            warnings.append(f"step1.read_pm_project: {payload['error']}")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"step1.read_pm_project exception: {e}")

    # 1b. PRD context（取项目最新 PRD）
    try:
        raw = pm_db_api.get_pm_context_for_tech_plan({"project_id": project_id})
        payload = json.loads(raw)
        if "error" not in payload:
            ctx["prd_id"] = payload.get("prd_id")
            prd = payload.get("prd") or {}
            ctx["prd_title"] = prd.get("title") or "未命名 PRD"
            ctx["prd_content"] = prd.get("content") or ""
        else:
            warnings.append(
                f"step1.get_pm_context_for_tech_plan: {payload['error']}"
            )
    except Exception as e:  # noqa: BLE001
        warnings.append(f"step1.get_pm_context_for_tech_plan exception: {e}")

    # 1c. ADR list（拉 tech_stack 还原）
    try:
        adrs = adr_storage.list_adrs(project_id) or []
        ctx["adr_ids"] = [a.get("id") for a in adrs if a.get("id")]
        ctx["tech_stack"] = [
            {
                "component": _parse_adr_component(a.get("title") or ""),
                "choice": a.get("decision") or "",
                "adr_display_number": a.get("display_number"),
            }
            for a in adrs
        ]
        if not adrs:
            warnings.append(
                f"step1.list_adrs: no ADRs for project_id={project_id} "
                f"(payload 技术方案段将降级)"
            )
    except Exception as e:  # noqa: BLE001
        warnings.append(f"step1.list_adrs exception: {e}")

    return ctx


def _parse_adr_component(title: str) -> str:
    """从 design_tech_plan 写的 ADR title '选择 X 作为 Y' 反解 component=Y。

    与 breakdown_tasks._parse_adr_title 等价（保持一致）；解析失败返回原 title。
    """
    if not title:
        return "?"
    if title.startswith("选择 ") and " 作为 " in title:
        body = title[len("选择 "):]
        try:
            _choice, component = body.split(" 作为 ", 1)
            return component.strip() or title
        except ValueError:
            pass
    return title


# ---------------------------------------------------------------------------
# Step 3: 拓扑划分 ready / deferred
# ---------------------------------------------------------------------------


def _step3_split_ready_deferred(
    tasks: List[Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """把 tasks 划分为 ready（depends_on 为空）和 deferred（depends_on 非空）。

    Phase 1 简化（与 PRD-CAPABILITIES 能力 3 验收对齐）：dispatch 是一次性快照，
    不跨调用追踪 task done 状态 — depends_on 非空 → 当前轮 deferred；
    breakdown_tasks 已保证 dependency_graph 是 DAG，下游调用方完成后下次再 dispatch。

    R-FN-3.4：DAG 依赖未就绪的任务延派。
    """
    ready: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for idx, t in enumerate(tasks):
        if not isinstance(t, dict):
            warnings.append(
                f"task #{idx} not a dict (got {type(t).__name__}), skipped"
            )
            continue

        tid = t.get("id")
        if not tid:
            warnings.append(
                f"task #{idx} missing id, skipped (上游 breakdown_tasks 应已兜底 uuid)"
            )
            continue

        deps = t.get("depends_on")
        if isinstance(deps, list) and deps:
            # 依赖未就绪 → 延派
            deferred.append(
                {
                    "task_id": tid,
                    "title": t.get("title") or "",
                    "reason": (
                        f"depends_on 未就绪（共 {len(deps)} 个前置任务尚未完成）："
                        f"{deps[:5]}"
                        + ("..." if len(deps) > 5 else "")
                    ),
                    "depends_on": deps,
                }
            )
        else:
            ready.append(t)

    return ready, deferred, warnings


# ---------------------------------------------------------------------------
# Step 4 + 5: 负载均衡 + 双通道派单
# ---------------------------------------------------------------------------


def _step4_5_dispatch_with_balance(
    *,
    ready_tasks: List[Dict[str, Any]],
    commanders: List[legion_api.Commander],
    ctx: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """对每个 ready task 选军团 + 双通道派单。

    单军团并发 ≤2（派前查 + 排队），超载或派失败 → 加 deferred。

    Returns:
        (assignments, deferred, warnings)
    """
    assignments: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # EngineerProfile lookup（commander_name → profile dict）
    profiles_by_name: Dict[str, Dict[str, Any]] = {
        p["commander_name"]: p
        for p in design_tech_plan.HARDCODED_LEGION_PROFILES
    }

    # load_map：每 dispatch 一次 += 1（Phase 1 启发式 — 初始为 0）
    # Phase 2 可改为读 inbox.json 未读消息数（更准确，但需多次磁盘 IO）
    load_map: Dict[str, int] = {c.commander_id: 0 for c in commanders}

    for task in ready_tasks:
        chosen = _pick_best_legion(
            task=task,
            commanders=commanders,
            load_map=load_map,
            profiles_by_name=profiles_by_name,
        )
        if not chosen:
            deferred.append(
                {
                    "task_id": task.get("id"),
                    "title": task.get("title") or "",
                    "reason": (
                        "all matching legions full "
                        f"(单军团并发上限 ≤{MAX_CONCURRENT_TASKS_PER_LEGION} 已被填满)"
                    ),
                    "suggested_legion": task.get("suggested_legion"),
                }
            )
            continue

        # 构造 payload 三段 + cto_context
        payload = _build_payload(task=task, ctx=ctx)
        cto_context = _build_cto_context(task=task, ctx=ctx)
        priority = SIZE_TO_PRIORITY.get(task.get("size") or "M", "normal")
        summary = _build_summary(task=task, ctx=ctx)

        # 双通道派单（legion_api.send_to_commander 内部已实现 inbox + tmux）
        try:
            send_result = legion_api.send_to_commander(
                commander_id=chosen.commander_id,
                payload=payload,
                msg_type="task",
                summary=summary,
                cto_context=cto_context,
                priority=priority,
            )
        except legion_api.LegionError as e:
            # 业务级派单失败 — 记 warning + 加 deferred，不阻塞下一个 task
            warnings.append(
                f"send_to_commander failed: legion={chosen.commander_id} "
                f"task={task.get('id')} err={e}"
            )
            deferred.append(
                {
                    "task_id": task.get("id"),
                    "title": task.get("title") or "",
                    "reason": f"send to {chosen.commander_id} failed: {e}",
                }
            )
            continue
        except Exception as e:  # noqa: BLE001
            level = error_classifier.classify(e)
            warnings.append(
                f"send_to_commander unexpected[{level}]: legion={chosen.commander_id} "
                f"task={task.get('id')} err={e}"
            )
            deferred.append(
                {
                    "task_id": task.get("id"),
                    "title": task.get("title") or "",
                    "reason": f"send to {chosen.commander_id} error[{level}]: {e}",
                }
            )
            continue

        # 派单成功 → load + 1 + 记录 assignment
        load_map[chosen.commander_id] = load_map.get(chosen.commander_id, 0) + 1
        assignments.append(
            {
                "task_id": task.get("id"),
                "title": task.get("title") or "",
                "legion_id": chosen.commander_id,
                "msg_id": send_result.get("message_id"),
                "inbox_path": send_result.get("inbox_path"),
                "tmux_session": send_result.get("tmux_session"),
                "tmux_notified": send_result.get("tmux_notified", False),
                "priority": priority,
                "payload_summary": _summarize_payload(payload),
            }
        )

    return assignments, deferred, warnings


# ---------------------------------------------------------------------------
# 军团匹配算法
# ---------------------------------------------------------------------------


def _pick_best_legion(
    *,
    task: Dict[str, Any],
    commanders: List[legion_api.Commander],
    load_map: Dict[str, int],
    profiles_by_name: Dict[str, Dict[str, Any]],
) -> Optional[legion_api.Commander]:
    """选择最匹配的在线军团。

    优先级：
      1. task.suggested_legion 在线 + load < MAX → 直选（breakdown_tasks 已含 hint）
      2. 全军团按 tech_stack_link 启发式打分排序：
         - score 高 → load 低 → tmux_alive=True 优先 → started_at 旧 优先
      3. 候选全无（load 全满 或 完全没匹配）→ None（上游加 deferred）

    返回值：选中的 Commander 或 None。
    """
    suggested = task.get("suggested_legion")
    tech_links_lower = [
        s.lower() for s in (task.get("tech_stack_link") or []) if isinstance(s, str)
    ]

    # ---- 1. suggested_legion 优先 ----
    if suggested:
        for c in commanders:
            if c.commander_id != suggested:
                continue
            if load_map.get(c.commander_id, 0) < MAX_CONCURRENT_TASKS_PER_LEGION:
                return c
            # suggested 满载 → 走 step 2 找替补
            break

    # ---- 2. 全军团启发式打分 ----
    # tuple 排序键：(-score, load, alive_rank, started_rank)
    # 都升序 → score 大 → load 小 → alive=True → started 旧（更早开服）优先
    candidates: List[Tuple[int, int, int, str, legion_api.Commander]] = []
    for c in commanders:
        if load_map.get(c.commander_id, 0) >= MAX_CONCURRENT_TASKS_PER_LEGION:
            continue

        prof = profiles_by_name.get(c.commander_id) or {}
        tags_lower = [
            t.lower()
            for t in prof.get("tech_stack_tags", [])
            if isinstance(t, str)
        ]
        score = _match_score(tech_links_lower, tags_lower)
        # score 中加入 suggested_legion 命中加成（即使 suggested 满载，备选打分时仍考虑）
        if suggested and c.commander_id == suggested:
            score += 10  # 强 hint

        alive_rank = 0 if c.tmux_alive else 1  # 0 优先
        candidates.append(
            (
                -score,
                load_map.get(c.commander_id, 0),
                alive_rank,
                c.started_at or "",
                c,
            )
        )

    if not candidates:
        return None

    # 排序：score 大优先 / load 小优先 / alive 优先 / started 旧优先
    candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    return candidates[0][4]


def _match_score(tech_links: List[str], tags: List[str]) -> int:
    """tech_stack_link × tech_stack_tags 子串匹配打分。

    简单粗暴：双向子串命中（tag in link / link in tag）各 +1。
    Phase 2 可换 embedding cosine similarity（更准确但要 LLM tokenize）。
    """
    if not tech_links or not tags:
        return 0
    score = 0
    for link in tech_links:
        for tag in tags:
            if link == tag:
                score += 2
                continue
            if link in tag or tag in link:
                score += 1
    return score


# ---------------------------------------------------------------------------
# Payload 构造（三段：PRD 摘要 + 技术方案 + GWT）
# ---------------------------------------------------------------------------


def _build_payload(*, task: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    """构造派单正文（明文 markdown，写入 inbox payload 字段）。

    R-FN-3.5：必含三段。
    任一段缺失：保留 segment 标题 + "（数据缺失）"提示，下游军团能识别。
    """
    lines: List[str] = []

    # ---- 头部 ----
    title = task.get("title") or "（未命名任务）"
    size = task.get("size") or "M"
    priority = SIZE_TO_PRIORITY.get(size, "normal")
    lines.append(f"# AICTO 派单 · {title}")
    lines.append("")
    lines.append(
        f"> 项目：**{ctx.get('project_name')}** | "
        f"size={size} | priority={priority} | task_id=`{task.get('id')}`"
    )
    lines.append("")

    # ---- 一、PRD 摘要 ----
    lines.append("## 一、PRD 摘要")
    lines.append("")
    prd_clip = ctx.get("prd_content") or ""
    if not prd_clip.strip():
        lines.append(
            "（PRD 摘要数据缺失 — 程小远拉 dev.db 失败，请军团需要时直接联系 PM）"
        )
    else:
        if len(prd_clip) > PRD_SUMMARY_CHAR_LIMIT:
            prd_clip = (
                prd_clip[:PRD_SUMMARY_CHAR_LIMIT]
                + "\n...（PRD 全文超长已截断；如需完整请查 dev.db PRD 表）"
            )
        prd_title = ctx.get("prd_title") or "未命名 PRD"
        lines.append(f"**{prd_title}**")
        lines.append("")
        lines.append(prd_clip)
    lines.append("")

    # ---- 二、技术方案（来自 ADR） ----
    lines.append("## 二、技术方案（CTO ADR 决策）")
    lines.append("")
    tech_stack = ctx.get("tech_stack") or []
    if not tech_stack:
        lines.append(
            "（暂无 ADR — 程小远建议先调 design_tech_plan 落决策；"
            "本次任务请自行评估技术栈或与 CTO 沟通）"
        )
    else:
        plan_lines: List[str] = []
        plan_lines.append("| 组件 | 选择 | ADR |")
        plan_lines.append("|------|------|-----|")
        for item in tech_stack:
            comp = (item.get("component") or "?").replace("|", "/")
            choice = (item.get("choice") or "?").replace("|", "/")
            adr_disp = item.get("adr_display_number") or "—"
            plan_lines.append(f"| {comp} | {choice} | {adr_disp} |")
        plan_text = "\n".join(plan_lines)
        if len(plan_text) > TECH_PLAN_CHAR_LIMIT:
            plan_text = (
                plan_text[:TECH_PLAN_CHAR_LIMIT]
                + "\n（技术方案超长已截断 — 完整 ADR 列表见 cto_context.adr_links）"
            )
        lines.append(plan_text)
    lines.append("")

    # ---- 三、验收标准（GWT） ----
    lines.append("## 三、验收标准（Given/When/Then）")
    lines.append("")
    gwt = task.get("acceptance_gwt")
    if not isinstance(gwt, dict):
        lines.append("（GWT 数据缺失 — 上游 breakdown_tasks 应已兜底；本次按 <待补> 处理）")
        lines.append("- **Given**: <待补>")
        lines.append("- **When**: <待补>")
        lines.append("- **Then**: <待补>")
    else:
        lines.append(f"- **Given**: {gwt.get('given') or '<待补>'}")
        lines.append(f"- **When**: {gwt.get('when') or '<待补>'}")
        lines.append(f"- **Then**: {gwt.get('then') or '<待补>'}")
    lines.append("")

    # ---- 任务描述（可选附加） ----
    desc = task.get("description") or ""
    if isinstance(desc, str) and desc.strip():
        lines.append("## 任务描述")
        lines.append("")
        lines.append(desc.strip())
        lines.append("")

    # ---- 元信息（dispatch 调度信息） ----
    lines.append("## 调度元信息")
    lines.append("")
    lines.append(f"- task_id: `{task.get('id')}`")
    lines.append(f"- size: {size} | priority: {priority}")
    lines.append(
        f"- tech_stack_link: {task.get('tech_stack_link') or '[]'}"
    )
    lines.append(
        f"- suggested_legion: {task.get('suggested_legion') or '（未指定）'}"
    )
    lines.append(
        "- 决策权：CTO 拥有调度决策权；如有重大异议可走 appeal 通道（review_code 阶段）"
    )

    return "\n".join(lines)


def _build_cto_context(
    *, task: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """ARCHITECTURE §5.3 cto_context 字段 — 派单时附加上下文。

    保留字段（不动 mailbox 协议老 schema）：
      tech_plan_id / adr_links / feishu_doc_url
    扩展字段（dispatch 自加，便于追溯）：
      project_id / task_id / tech_stack_link / size / suggested_legion
    """
    return {
        "project_id": ctx.get("project_id"),
        # Phase 1 简化：tech_plan_id == project_id（与 breakdown_tasks 对齐 —
        # design_tech_plan 输出未含独立 plan_id，恢复用 ADR 重组）
        "tech_plan_id": ctx.get("project_id"),
        "adr_links": list(ctx.get("adr_ids") or []),
        "feishu_doc_url": ctx.get("feishu_doc_url"),
        "task_id": task.get("id"),
        "tech_stack_link": list(task.get("tech_stack_link") or []),
        "size": task.get("size"),
        "suggested_legion": task.get("suggested_legion"),
    }


def _build_summary(*, task: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    """构造 mailbox.summary 字段（≤一行）。"""
    title = task.get("title") or task.get("id") or "未命名任务"
    project = ctx.get("project_name") or "?"
    return f"AICTO 派发[{project}]: {title}"


def _summarize_payload(payload: str) -> str:
    """把 payload markdown 浓缩为一行（assignment.payload_summary 用）。"""
    if not payload:
        return ""
    flat = " ".join(line.strip() for line in payload.splitlines() if line.strip())
    if len(flat) > PAYLOAD_SUMMARY_CHAR_LIMIT:
        return flat[:PAYLOAD_SUMMARY_CHAR_LIMIT] + "..."
    return flat


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
    "MAX_CONCURRENT_TASKS_PER_LEGION",
    "SIZE_TO_PRIORITY",
    "PRD_SUMMARY_CHAR_LIMIT",
    "TECH_PLAN_CHAR_LIMIT",
]
