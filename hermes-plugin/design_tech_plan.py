"""design_tech_plan.py — 能力 1：PRD → 技术方案（KR4 ≤ 5 分钟 SLA）

P1.2 核心入口实现。tools.py 仅 dispatch 到本模块的 ``run`` 函数。

6 步推理链（详见 ARCHITECTURE.md §1 / RECON-HISTORY 8.4）：
  1. 拉 PM 上下文（prd_id / prd_markdown / prd_doc_token 三选一）
  2. 需求元数据硬门禁（5W1H + 增删查改显算传；缺失则不进 LLM）
  3. 检查 ADR 历史（保持决策连贯性）
  4. 查 EngineerProfile（Phase 1 hardcoded 8 军团）
  5. LLM 推理生成 6 字段 JSON（含 red verdict 改进路径强约束）
  6. 每个 tech_stack 选项写一条 ADR
  7. 渲染飞书技术方案文档（不阻塞主流程）

关键约束（硬纪律）：
- KR4 SLA ≤ 5 分钟（埋点 elapsed_seconds + kr4_compliant）
- 需求入口必须通过原子 PRD 元数据门禁；任何维度不涉及必须显式写「无」
- red verdict 必含 improvement_path
- missing_info 非空 → blocking_downstream=true
- 飞书 / ADR 写入失败不阻塞返回（降级为 null + 告知 markdown 自取）
- 全程 retry_with_backoff 包裹 LLM 调用
- 错误用 error_classifier 4 级分类，不自定义新级别

参考：
- .planning/phase1/specs/REQUIREMENTS.md §1.2 (R-FN-1.1 ~ 1.8)
- .planning/phase1/specs/ARCHITECTURE.md §1 / §4
- .planning/phase1/specs/PHASE-PLAN.md §3
- .planning/phase1/recon/PRD-CAPABILITIES.md 能力 1
- .planning/phase1/recon/RECON-HISTORY.md §8.4
- .dispatch/inbox/pm-clarification-20250425-1505.md R-OPEN-1/2/4/6
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from . import (
    adr_storage,
    aipm_cto_collaboration,
    error_classifier,
    feishu_api,
    pm_db_api,
    requirement_metadata_gate,
)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

KR4_SLA_SECONDS: float = 300.0
"""KR4 验收阈值：design_tech_plan 必须 ≤ 5 分钟（PRD §九）。"""

PROMPT_PATH: pathlib.Path = (
    pathlib.Path(__file__).parent / "templates" / "tech-plan-prompt.md"
)
"""LLM prompt 模板（markdown 格式，避免硬编码到 .py）。"""

# Phase 1 hardcoded EngineerProfile（R-OPEN-6 PM 决策）
# 字段：commander_name / project_affinity / tech_stack_tags
# PM 答复明细：当前活跃军团 8 队 — 麒麟、凤凰、赤龙、昆仑、青龙、星辰、鲲鹏、暴风
# Phase 2 落表 + 动态更新（详见 .dispatch/inbox/pm-clarification-20250425-1505.md）
HARDCODED_LEGION_PROFILES: List[Dict[str, Any]] = [
    {
        "commander_name": "L1-麒麟军团",
        "project_affinity": ["AICTO", "ProdMind", "Hermes plugin"],
        "tech_stack_tags": ["python", "fastapi", "sqlite", "hermes", "feishu-api"],
    },
    {
        "commander_name": "L1-凤凰军团",
        "project_affinity": ["前端", "管理后台"],
        "tech_stack_tags": ["typescript", "react", "next.js", "tailwind"],
    },
    {
        "commander_name": "L1-赤龙军团",
        "project_affinity": ["后端服务", "数据中台"],
        "tech_stack_tags": ["python", "go", "postgresql", "kafka"],
    },
    {
        "commander_name": "L1-昆仑军团",
        "project_affinity": ["AI/ML", "数据科学"],
        "tech_stack_tags": ["python", "pytorch", "llm", "embedding"],
    },
    {
        "commander_name": "L1-青龙军团",
        "project_affinity": ["DevOps", "基础设施"],
        "tech_stack_tags": ["docker", "k8s", "ci/cd", "monitoring"],
    },
    {
        "commander_name": "L1-星辰军团",
        "project_affinity": ["移动端", "跨平台"],
        "tech_stack_tags": ["flutter", "react-native", "ios", "android"],
    },
    {
        "commander_name": "L1-鲲鹏军团",
        "project_affinity": ["大数据", "存储"],
        "tech_stack_tags": ["spark", "hadoop", "clickhouse", "minio"],
    },
    {
        "commander_name": "L1-暴风军团",
        "project_affinity": ["Quick-strike", "POC", "原型"],
        "tech_stack_tags": ["any", "rapid-prototype"],
    },
]


# ---------------------------------------------------------------------------
# Public entry — tools.py 调用此函数
# ---------------------------------------------------------------------------


def run(args: Dict[str, Any], **kwargs) -> str:
    """design_tech_plan 主入口（6 步推理链）。

    返回 JSON 字符串（与其他 AICTO 工具风格一致），所有错误用 4 级分类。
    """
    started_at = time.monotonic()

    # ---- 入参校验（intent 级失败立即返）----
    prd_id = args.get("prd_id")
    prd_markdown = args.get("prd_markdown")
    prd_doc_token = args.get("prd_doc_token")
    focus = args.get("focus")
    constraints = args.get("constraints")

    if not (prd_id or prd_markdown or prd_doc_token):
        return _fail(
            "must provide one of: prd_id / prd_markdown / prd_doc_token",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 1：拉 PM 上下文 ----
    try:
        ctx = _step1_load_prd_context(
            prd_id=prd_id,
            prd_markdown=prd_markdown,
            prd_doc_token=prd_doc_token,
        )
    except _DesignTechPlanError as e:
        return _fail(
            str(e), level=e.level, elapsed=time.monotonic() - started_at
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        if level in (
            error_classifier.LEVEL_PERMISSION,
            error_classifier.LEVEL_UNKNOWN,
        ):
            error_classifier.escalate_to_owner(
                level, e, {"phase": "step1_load_prd_context", "args": _summarize_args(args)}
            )
        return _fail(
            f"step1_load_prd_context: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    project_id: Optional[str] = ctx.get("project_id")
    project_name: str = ctx.get("project_name") or "未命名项目"
    prd_title: str = ctx.get("prd_title") or "未命名 PRD"
    prd_content: str = ctx.get("prd_content") or ""

    # ---- Step 2：需求元数据硬门禁 ----
    requirement_gate = requirement_metadata_gate.evaluate_prd(
        prd_markdown=prd_content,
        requirement_metadata=args.get("requirement_metadata"),
    )
    if not requirement_gate.get("passes"):
        return _requirement_gate_block_response(
            requirement_gate=requirement_gate,
            args=args,
            ctx=ctx,
            project_id=project_id,
            project_name=project_name,
            prd_title=prd_title,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 3：检查 ADR 历史 ----
    try:
        adr_history: List[Dict[str, Any]] = (
            adr_storage.list_adrs(project_id) if project_id else []
        )
    except Exception as e:  # noqa: BLE001
        # ADR 读失败不阻塞主流程（降级为空历史 + 日志）
        print(f"[design_tech_plan] step2 ADR history read failed: {e}")
        adr_history = []

    # ---- Step 4：EngineerProfile（Phase 1 hardcoded） ----
    legion_info = HARDCODED_LEGION_PROFILES

    # ---- Step 5：LLM 推理生成 6 字段 JSON ----
    try:
        plan_json = _step4_llm_design(
            prd_title=prd_title,
            prd_content=prd_content,
            adr_history=adr_history,
            user_stories=ctx.get("user_stories", []),
            features=ctx.get("features", []),
            decisions=ctx.get("decisions", []),
            open_questions=ctx.get("open_questions", []),
            legion_info=legion_info,
            focus=focus,
            constraints=constraints,
        )
    except _DesignTechPlanError as e:
        return _fail(
            str(e), level=e.level, elapsed=time.monotonic() - started_at
        )
    except error_classifier.WrappedToolError as e:
        # retry_with_backoff 用尽 → 升级
        error_classifier.escalate_to_owner(
            e.level,
            e,
            {
                "phase": "step4_llm_design",
                "prd_id": prd_id,
                "prd_doc_token": prd_doc_token,
                "project_id": project_id,
            },
        )
        return _fail(
            f"step4_llm_design exhausted: {e}",
            level=e.level,
            elapsed=time.monotonic() - started_at,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        error_classifier.escalate_to_owner(
            level,
            e,
            {"phase": "step4_llm_design", "project_id": project_id},
        )
        return _fail(
            f"step4_llm_design: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    # 业务后处理 — 不修改 LLM 决策，只做硬约束兜底
    plan_json = _enforce_hard_rules(plan_json)
    feasibility: str = plan_json.get("feasibility", "yellow")
    improvement_path: Optional[str] = plan_json.get("improvement_path")
    tech_stack: List[Dict[str, Any]] = plan_json.get("tech_stack") or []
    estimate: Dict[str, Any] = plan_json.get("estimate") or {}
    risks: List[Dict[str, Any]] = plan_json.get("risks") or []
    missing_info: List[str] = plan_json.get("missing_info") or []
    summary: str = plan_json.get("summary") or ""

    blocking_downstream: bool = (feasibility == "red") or bool(missing_info)

    # ---- Step 6：每个 tech_stack 选项写一条 ADR ----
    adr_ids: List[str] = []
    adr_write_errors: List[str] = []
    if project_id:
        for item in tech_stack:
            try:
                title = f"选择 {item.get('choice', '?')} 作为 {item.get('component', '?')}"
                adr_row = adr_storage.create_adr(
                    project_id=project_id,
                    title=title,
                    decision=item.get("choice", ""),
                    rationale=item.get("reason", ""),
                    alternatives_considered=item.get("alternatives_considered") or [],
                    decided_by="AICTO (程小远)",
                )
                adr_id = adr_row.get("id") if adr_row else None
                if adr_id:
                    item["adr_id"] = adr_id
                    item["adr_display_number"] = adr_row.get("display_number")
                    adr_ids.append(adr_id)
            except Exception as e:  # noqa: BLE001
                # ADR 写入失败不阻塞主流程（仅 log + 累计错误）
                msg = f"adr write failed for {item.get('component')}: {e}"
                print(f"[design_tech_plan] {msg}")
                adr_write_errors.append(msg)
    else:
        # 无 project_id（如直传 prd_markdown 没法溯源到 PM project）→ 跳过 ADR 写入
        adr_write_errors.append(
            "no project_id resolved; ADR writes skipped (use prd_id "
            "or prd_doc_token with project metadata to enable ADR persistence)"
        )

    # ---- Step 7：渲染飞书技术方案文档（不阻塞主流程） ----
    feishu_doc_url: Optional[str] = None
    feishu_doc_id: Optional[str] = None
    feishu_error: Optional[str] = None
    markdown_doc: str = _build_tech_plan_markdown(
        project_name=project_name,
        prd_title=prd_title,
        feasibility=feasibility,
        improvement_path=improvement_path,
        summary=summary,
        tech_stack=tech_stack,
        estimate=estimate,
        risks=risks,
        missing_info=missing_info,
        adr_history=adr_history,
        focus=focus,
        constraints=constraints,
    )
    try:
        doc_title = f"{project_name} 技术方案 — {prd_title}"
        result = feishu_api.create_docx(doc_title, markdown_doc)
        feishu_doc_id = result.get("document_id")
        feishu_doc_url = result.get("url")
        # _grant_doc_tenant_read 已在 create_docx 内自动调用
    except Exception as e:  # noqa: BLE001
        feishu_error = f"{type(e).__name__}: {e}"
        print(f"[design_tech_plan] step6 feishu doc create failed: {feishu_error}")

    # ---- 返回 ----
    elapsed = time.monotonic() - started_at
    return _success(
        {
            "feasibility": feasibility,
            "improvement_path": improvement_path,
            "summary": summary,
            "tech_stack": tech_stack,
            "estimate": estimate,
            "risks": risks,
            "missing_info": missing_info,
            "blocking_downstream": blocking_downstream,
            "requirement_gate": _summarize_requirement_gate(requirement_gate),
            "feishu_doc_url": feishu_doc_url,
            "feishu_doc_id": feishu_doc_id,
            "feishu_error": feishu_error,
            "markdown_doc": markdown_doc if feishu_doc_url is None else None,
            "adr_ids": adr_ids,
            "adr_write_errors": adr_write_errors or None,
            "project_id": project_id,
            "prd_id": ctx.get("prd_id_resolved"),
            "elapsed_seconds": round(elapsed, 2),
            "kr4_compliant": elapsed <= KR4_SLA_SECONDS,
        }
    )


# ---------------------------------------------------------------------------
# Step 1: 拉 PM 上下文
# ---------------------------------------------------------------------------


class _DesignTechPlanError(error_classifier.WrappedToolError):
    """本模块专用异常，继承 WrappedToolError 让 retry_with_backoff 走 .level 短路。

    修复 B-1（reviewer-p1-2 / 2026-04-25）：原本继承 Exception → retry 用 classify()
    关键词匹配返回 LEVEL_UNKNOWN → 立即抛不重试 → R-NFR-19 / ADR-006 技术级重试 3 次
    实质失效。改继承 WrappedToolError 后 retry 走 level 短路 → 技术级正常 3 次重试。
    """

    def __init__(self, message: str, level: str = error_classifier.LEVEL_UNKNOWN):
        super().__init__(message, level=level)


def _step1_load_prd_context(
    *,
    prd_id: Optional[str],
    prd_markdown: Optional[str],
    prd_doc_token: Optional[str],
) -> Dict[str, Any]:
    """三选一加载 PRD 上下文。

    优先级（PM R-OPEN-4 已决）：prd_id > prd_markdown > prd_doc_token

    返回 dict 包含：
      project_id (Optional[str])
      project_name (Optional[str])
      prd_title (str)
      prd_content (str)
      prd_id_resolved (Optional[str])
      user_stories (list)
      features (list)
      decisions (list)
      open_questions (list)
    """
    if prd_id:
        return _load_from_dev_db(prd_id)
    if prd_markdown:
        return _load_from_markdown(prd_markdown)
    if prd_doc_token:
        return _load_from_feishu(prd_doc_token)
    raise _DesignTechPlanError(
        "no PRD source provided", level=error_classifier.LEVEL_INTENT
    )


def _load_from_dev_db(prd_id: str) -> Dict[str, Any]:
    """主链路：用 prd_id 从 ProdMind dev.db 拉完整上下文。

    复用 pm_db_api.get_pm_context_for_tech_plan（一次连接 5 张表）。
    """
    raw = pm_db_api.get_pm_context_for_tech_plan({"prd_id": prd_id})
    payload = json.loads(raw)
    if "error" in payload:
        raise _DesignTechPlanError(
            f"dev.db get_pm_context failed: {payload['error']}",
            level=error_classifier.LEVEL_INTENT,
        )

    prd = payload.get("prd") or {}
    # Project 名称（额外读一次）
    project_id = payload.get("project_id")
    project_name = _resolve_project_name(project_id)

    return {
        "project_id": project_id,
        "project_name": project_name,
        "prd_title": prd.get("title") or "未命名 PRD",
        "prd_content": prd.get("content") or "",
        "prd_id_resolved": payload.get("prd_id"),
        "user_stories": payload.get("user_stories", []),
        "features": payload.get("features", []),
        "decisions": payload.get("decisions", []),
        "open_questions": payload.get("open_questions", []),
    }


def _load_from_markdown(prd_markdown: str) -> Dict[str, Any]:
    """直接传 PRD 文本（用于 Dogfood / 快速验证）。

    无 project_id → 跳过 ADR 写入（adr_write_errors 会标注）。
    """
    if not prd_markdown.strip():
        raise _DesignTechPlanError(
            "prd_markdown is empty", level=error_classifier.LEVEL_INTENT
        )
    title = _guess_title_from_markdown(prd_markdown)
    return {
        "project_id": None,
        "project_name": "ad-hoc PRD",
        "prd_title": title,
        "prd_content": prd_markdown,
        "prd_id_resolved": None,
        "user_stories": [],
        "features": [],
        "decisions": [],
        "open_questions": [],
    }


def _load_from_feishu(prd_doc_token: str) -> Dict[str, Any]:
    """从飞书 docx 拉 PRD（PM 直接丢飞书链接的兜底通道）。

    无法可靠提取 project_id（飞书 doc 无元数据指向 dev.db）→ ADR 写入会跳过。
    Phase 2 可考虑通过飞书 doc URL 反查 ProdMind ProjectDocument 表。
    """
    try:
        content = feishu_api.read_docx_content(prd_doc_token)
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        raise _DesignTechPlanError(
            f"feishu read_docx_content failed: {e}", level=level
        )
    if not content.strip():
        raise _DesignTechPlanError(
            f"feishu docx empty or unreadable: {prd_doc_token}",
            level=error_classifier.LEVEL_INTENT,
        )
    title = _guess_title_from_markdown(content)

    # 兜底：尝试通过 doc_token 反查 ProdMind dev.db 的 ProjectDocument 表
    project_id, project_name = _try_resolve_project_from_feishu_doc(prd_doc_token)

    return {
        "project_id": project_id,
        "project_name": project_name or "外部飞书 PRD",
        "prd_title": title,
        "prd_content": content,
        "prd_id_resolved": None,
        "user_stories": [],
        "features": [],
        "decisions": [],
        "open_questions": [],
    }


def _try_resolve_project_from_feishu_doc(
    doc_token_or_url: str,
) -> Tuple[Optional[str], Optional[str]]:
    """尝试通过飞书 doc_token 反查 ProdMind ProjectDocument 表。

    无法解析时返回 (None, None) — 不抛错（这只是 best-effort 增强，主流程已可用）。
    """
    import sqlite3 as _sqlite

    # 提取纯 doc_id
    try:
        from .feishu_api import _extract_doc_id  # type: ignore

        doc_id = _extract_doc_id(doc_token_or_url)
    except Exception:  # noqa: BLE001
        doc_id = doc_token_or_url

    try:
        # mode=ro 只读访问
        uri = f"file:{pm_db_api.PRODMIND_DB_PATH}?mode=ro"
        conn = _sqlite.connect(uri, uri=True)
        conn.row_factory = _sqlite.Row
        try:
            # ProjectDocument 表可能字段名不同，try a few common ones
            row = conn.execute(
                'SELECT projectId FROM "ProjectDocument" '
                'WHERE feishuDocToken = ? OR feishuDocId = ? LIMIT 1',
                (doc_id, doc_id),
            ).fetchone()
            if row is None:
                return None, None
            project_id = row["projectId"]
            prow = conn.execute(
                'SELECT name FROM "Project" WHERE id = ?', (project_id,)
            ).fetchone()
            project_name = prow["name"] if prow else None
            return project_id, project_name
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        # ProjectDocument 表不存在或字段不同 — 静默降级
        return None, None


def _resolve_project_name(project_id: Optional[str]) -> Optional[str]:
    """通过 pm_db_api 拿 Project.name（best-effort）。"""
    if not project_id:
        return None
    try:
        raw = pm_db_api.read_pm_project({"project_id": project_id})
        payload = json.loads(raw)
        if "error" in payload:
            return None
        return (payload.get("project") or {}).get("name")
    except Exception:  # noqa: BLE001
        return None


def _guess_title_from_markdown(md: str) -> str:
    """取 markdown 第一个 h1，其次第一行非空。"""
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s.lstrip("# ").strip() or "PRD"
    for line in md.splitlines():
        s = line.strip()
        if s:
            return s[:80]
    return "PRD"


# ---------------------------------------------------------------------------
# Step 4: LLM 推理
# ---------------------------------------------------------------------------


def _load_prompt_template() -> str:
    if not PROMPT_PATH.exists():
        raise _DesignTechPlanError(
            f"prompt template missing: {PROMPT_PATH}",
            level=error_classifier.LEVEL_UNKNOWN,
        )
    return PROMPT_PATH.read_text(encoding="utf-8")


def _summarize_records(records: List[Dict[str, Any]], keys: List[str], limit: int = 8) -> str:
    """把一组 dict 汇总为短行 list（供 prompt 注入）。"""
    if not records:
        return "（无）"
    lines: List[str] = []
    for r in records[:limit]:
        parts = []
        for k in keys:
            v = r.get(k)
            if v is None or v == "":
                continue
            if isinstance(v, str) and len(v) > 120:
                v = v[:120] + "..."
            parts.append(f"{k}={v}")
        if parts:
            lines.append("  - " + " | ".join(parts))
    if len(records) > limit:
        lines.append(f"  - …（共 {len(records)} 条，仅显示前 {limit}）")
    return "\n".join(lines) if lines else "（无）"


def _summarize_adrs(adr_history: List[Dict[str, Any]]) -> str:
    if not adr_history:
        return "（无历史 ADR — 这是项目首份技术方案）"
    lines = ["（按编号升序）"]
    for adr in adr_history[:20]:
        lines.append(
            f"  - {adr.get('display_number') or adr.get('number')}: "
            f"{adr.get('title')} | status={adr.get('status')} | "
            f"decision={(adr.get('decision') or '')[:80]}"
        )
    if len(adr_history) > 20:
        lines.append(f"  - …（共 {len(adr_history)} 条，仅显示前 20）")
    return "\n".join(lines)


def _summarize_legion(legion_info: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"  - {l['commander_name']}: 擅长 {','.join(l['tech_stack_tags'][:5])} "
        f"| 项目偏好 {','.join(l['project_affinity'][:3])}"
        for l in legion_info
    )


def _build_messages(
    *,
    prd_title: str,
    prd_content: str,
    adr_history: List[Dict[str, Any]],
    user_stories: List[Dict[str, Any]],
    features: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    open_questions: List[Dict[str, Any]],
    legion_info: List[Dict[str, Any]],
    focus: Optional[str],
    constraints: Optional[str],
) -> List[Dict[str, Any]]:
    """构造发给 LLM 的 messages 列表。"""
    template = _load_prompt_template()

    # PRD 内容超长截断（Opus 1M 上下文，留出余量给系统/思考；这里取 80K char ≈ 25K token）
    prd_clip = prd_content
    if len(prd_clip) > 80000:
        prd_clip = prd_clip[:80000] + "\n\n…（PRD 过长已截断，仅含前 80K 字符）"

    rendered = (
        template.replace("{{PRD_TITLE}}", prd_title or "")
        .replace("{{PRD_CONTENT}}", prd_clip or "")
        .replace("{{ADR_HISTORY}}", _summarize_adrs(adr_history))
        .replace(
            "{{USER_STORIES_SUMMARY}}",
            _summarize_records(
                user_stories, ["asA", "iWant", "soThat", "priority"], limit=10
            ),
        )
        .replace(
            "{{FEATURES_SUMMARY}}",
            _summarize_records(
                features, ["title", "riceScore", "description"], limit=10
            ),
        )
        .replace(
            "{{PRD_DECISIONS_SUMMARY}}",
            _summarize_records(
                decisions, ["title", "decision", "decidedBy"], limit=10
            ),
        )
        .replace(
            "{{PRD_OPEN_QUESTIONS_SUMMARY}}",
            _summarize_records(
                open_questions, ["question", "status", "priority"], limit=10
            ),
        )
        .replace("{{FOCUS}}", focus or "（未指定）")
        .replace("{{CONSTRAINTS}}", constraints or "（未指定）")
        .replace("{{LEGION_INFO}}", _summarize_legion(legion_info))
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


def _step4_llm_design(
    *,
    prd_title: str,
    prd_content: str,
    adr_history: List[Dict[str, Any]],
    user_stories: List[Dict[str, Any]],
    features: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    open_questions: List[Dict[str, Any]],
    legion_info: List[Dict[str, Any]],
    focus: Optional[str],
    constraints: Optional[str],
) -> Dict[str, Any]:
    """发给 LLM → 解 JSON → 返回 dict（带 retry 包裹）。"""
    messages = _build_messages(
        prd_title=prd_title,
        prd_content=prd_content,
        adr_history=adr_history,
        user_stories=user_stories,
        features=features,
        decisions=decisions,
        open_questions=open_questions,
        legion_info=legion_info,
        focus=focus,
        constraints=constraints,
    )

    def _do_call() -> Dict[str, Any]:
        response = _invoke_llm(messages)
        content = _extract_content(response)
        return _parse_llm_json(content)

    return error_classifier.retry_with_backoff(
        _do_call, max_retries=3, base_delay=2.0
    )


def _invoke_llm(messages: List[Dict[str, Any]]) -> Any:
    """调 LLM。优先用 Hermes auxiliary call_llm；否则降级 OpenAI direct。

    两条路径都目标 aigcapi.top + claude-opus-4-6（profile config 已配）。
    """
    # 优先：Hermes 内置 call_llm（自动读 profile config，处理 fallback）
    try:
        from agent.auxiliary_client import call_llm  # type: ignore

        return call_llm(
            task="design_tech_plan",
            messages=messages,
            temperature=0.3,
            max_tokens=8000,
            timeout=180.0,
        )
    except ImportError:
        # plugin 在 hermes-agent venv 之外加载（极少见），降级用 OpenAI direct
        return _invoke_llm_via_openai(messages)


def _invoke_llm_via_openai(messages: List[Dict[str, Any]]) -> Any:
    """OpenAI client 直连 aigcapi.top（fallback path）。"""
    from openai import OpenAI

    api_key = os.environ.get("AIGC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise _DesignTechPlanError(
            "no LLM API key in env (AIGC_API_KEY / OPENAI_API_KEY)",
            level=error_classifier.LEVEL_PERMISSION,
        )
    base_url = os.environ.get("AIGC_API_BASE", "https://aigcapi.top/v1")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0)
    return client.chat.completions.create(
        model=os.environ.get("AICTO_LLM_MODEL", "claude-opus-4-6"),
        messages=messages,
        temperature=0.3,
        max_tokens=8000,
    )


def _extract_content(response: Any) -> str:
    """从 OpenAI/Hermes response 抽出 text content。"""
    try:
        # Hermes 提供的辅助函数（如可用）
        from agent.auxiliary_client import extract_content_or_reasoning  # type: ignore

        text = extract_content_or_reasoning(response) or ""
        if text:
            return text
    except ImportError:
        pass
    # 直接走 OpenAI 协议
    try:
        return (response.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        raise _DesignTechPlanError(
            f"unable to extract LLM content: {e}",
            level=error_classifier.LEVEL_UNKNOWN,
        )


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """解 LLM 返回的 JSON。容错：去 markdown 围栏，截首尾大括号。"""
    if not text or not text.strip():
        raise _DesignTechPlanError(
            "LLM returned empty content",
            level=error_classifier.LEVEL_TECH,  # 让 retry 触发
        )

    s = text.strip()
    # 去 ```json 围栏
    if s.startswith("```"):
        # 找第一个换行后的内容到下一个 ``` 之间
        first_nl = s.find("\n")
        last_fence = s.rfind("```")
        if first_nl != -1 and last_fence > first_nl:
            s = s[first_nl + 1 : last_fence].strip()

    # 提第一个 { 到最后一个 } 之间（防 LLM 加额外说明）
    lb = s.find("{")
    rb = s.rfind("}")
    if lb != -1 and rb > lb:
        s = s[lb : rb + 1]

    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise _DesignTechPlanError(
            f"LLM returned invalid JSON: {e}; raw_head={text[:200]!r}",
            level=error_classifier.LEVEL_TECH,  # 让 retry 触发（LLM 偶发抽风）
        )


# ---------------------------------------------------------------------------
# Hard-rule enforcement (post-LLM)
# ---------------------------------------------------------------------------


def _enforce_hard_rules(plan: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 输出兜底 — 仅做最低限度的硬约束补救，不改变决策内容。

    1. feasibility 缺失或非法 → yellow（保守）
    2. red 但 improvement_path 缺失 → 写占位（避免输出违反契约，但记录到 missing_info）
    3. estimate 缺失或错乱 → 用占位 1/3/7 + missing_info 加一条
    4. tech_stack 项缺 alternatives_considered → 加 [{"option":"未列出","rejected_reason":"..."}]
    """
    if not isinstance(plan, dict):
        return {
            "feasibility": "yellow",
            "improvement_path": None,
            "tech_stack": [],
            "estimate": {"optimistic": 1, "likely": 3, "pessimistic": 7, "unit": "days"},
            "risks": [],
            "missing_info": ["LLM 输出非 dict，已兜底为占位"],
            "summary": "",
        }

    fe = plan.get("feasibility")
    if fe not in ("green", "yellow", "red"):
        plan["feasibility"] = "yellow"
        plan.setdefault("missing_info", []).append(
            f"LLM feasibility 非法值 {fe!r}，兜底为 yellow"
        )

    if plan.get("feasibility") == "red" and not plan.get("improvement_path"):
        plan["improvement_path"] = (
            "（LLM 未填 improvement_path — 程小远兜底：请 PM 提供更明确的 PRD 范围 / "
            "或调整时间预算 / 或砍掉 P2 功能后重新提交）"
        )
        plan.setdefault("missing_info", []).append(
            "feasibility=red 但 LLM 未给 improvement_path（已兜底）"
        )

    est = plan.get("estimate")
    if not isinstance(est, dict):
        est = {}
    o = est.get("optimistic")
    l = est.get("likely")
    p = est.get("pessimistic")
    if not (isinstance(o, (int, float)) and isinstance(l, (int, float)) and isinstance(p, (int, float))):
        plan["estimate"] = {"optimistic": 1, "likely": 3, "pessimistic": 7, "unit": "days"}
        plan.setdefault("missing_info", []).append(
            "LLM estimate 不完整，兜底为 1/3/7 天"
        )
    elif not (o <= l <= p):
        # 强制递增
        sorted_vals = sorted([o, l, p])
        plan["estimate"] = {
            "optimistic": sorted_vals[0],
            "likely": sorted_vals[1],
            "pessimistic": sorted_vals[2],
            "unit": est.get("unit", "days"),
        }
    else:
        est.setdefault("unit", "days")
        plan["estimate"] = est

    # tech_stack 兜底
    ts = plan.get("tech_stack")
    if not isinstance(ts, list):
        ts = []
    fixed_ts: List[Dict[str, Any]] = []
    for item in ts:
        if not isinstance(item, dict):
            continue
        if not item.get("alternatives_considered"):
            item["alternatives_considered"] = [
                {"option": "未列出", "rejected_reason": "LLM 未提供备选方案"}
            ]
        fixed_ts.append(item)
    plan["tech_stack"] = fixed_ts

    # risks 兜底
    if not isinstance(plan.get("risks"), list):
        plan["risks"] = []

    # missing_info 兜底
    if not isinstance(plan.get("missing_info"), list):
        plan["missing_info"] = []

    return plan


# ---------------------------------------------------------------------------
# Step 7: 飞书技术方案 markdown 渲染
# ---------------------------------------------------------------------------


def _build_tech_plan_markdown(
    *,
    project_name: str,
    prd_title: str,
    feasibility: str,
    improvement_path: Optional[str],
    summary: str,
    tech_stack: List[Dict[str, Any]],
    estimate: Dict[str, Any],
    risks: List[Dict[str, Any]],
    missing_info: List[str],
    adr_history: List[Dict[str, Any]],
    focus: Optional[str],
    constraints: Optional[str],
) -> str:
    """生成飞书 doc 的 markdown 内容。

    使用标准 markdown（飞书 markdown_to_descendants 已支持表格 / heading / list / code）。
    """
    lines: List[str] = []
    feasibility_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(feasibility, "⚪")

    lines.append(f"# {project_name} — 技术方案")
    lines.append("")
    lines.append(f"> PRD: **{prd_title}**")
    lines.append(f"> 程小远（AICTO）出品 · {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 一句话总结
    if summary:
        lines.append(f"## 一句话总结")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # Feasibility
    lines.append(f"## 可行性判断")
    lines.append("")
    lines.append(f"**{feasibility_emoji} {feasibility.upper()}**")
    lines.append("")
    if feasibility == "red" and improvement_path:
        lines.append(f"### 改进路径（red 必填）")
        lines.append("")
        lines.append(improvement_path)
        lines.append("")

    # Estimate
    lines.append(f"## 工期估计（三档）")
    lines.append("")
    lines.append("| 档位 | 天数 |")
    lines.append("|------|------|")
    lines.append(f"| 乐观 | {estimate.get('optimistic')} |")
    lines.append(f"| 常态 | {estimate.get('likely')} |")
    lines.append(f"| 悲观 | {estimate.get('pessimistic')} |")
    lines.append(f"| 单位 | {estimate.get('unit', 'days')} |")
    lines.append("")

    # Tech stack
    lines.append(f"## 技术栈选型")
    lines.append("")
    if tech_stack:
        lines.append("| 组件 | 选择 | 理由 | ADR |")
        lines.append("|------|------|------|-----|")
        for item in tech_stack:
            adr_disp = item.get("adr_display_number") or item.get("adr_id") or "—"
            reason = (item.get("reason") or "").replace("\n", " ").replace("|", "/")
            choice = (item.get("choice") or "").replace("|", "/")
            comp = (item.get("component") or "").replace("|", "/")
            lines.append(f"| {comp} | {choice} | {reason} | {adr_disp} |")
        lines.append("")

        # 备选方案
        lines.append(f"### 备选方案（已考虑并拒绝）")
        lines.append("")
        for item in tech_stack:
            alts = item.get("alternatives_considered") or []
            if not alts:
                continue
            lines.append(f"#### {item.get('component')} — {item.get('choice')}")
            lines.append("")
            for a in alts:
                lines.append(
                    f"- ❌ **{a.get('option')}** — {a.get('rejected_reason', '（未填理由）')}"
                )
            lines.append("")
    else:
        lines.append("（LLM 未输出 tech_stack — 通常意味着 PRD 信息不足以做选型）")
        lines.append("")

    # Risks
    lines.append(f"## 风险登记")
    lines.append("")
    if risks:
        lines.append("| 标题 | 严重度 | 概率 | 缓解 |")
        lines.append("|------|--------|------|------|")
        for r in risks:
            title = (r.get("title") or "").replace("|", "/")
            mit = (r.get("mitigation") or "").replace("\n", " ").replace("|", "/")
            sev = r.get("severity") or "?"
            prob = r.get("probability") or "?"
            lines.append(f"| {title} | {sev} | {prob} | {mit} |")
        lines.append("")
    else:
        lines.append("（无识别风险 — 程小远会在评审阶段抽查）")
        lines.append("")

    # Missing info（阻塞下游标记）
    lines.append(f"## ⚠️ Missing Info（反向推回 PM）")
    lines.append("")
    if missing_info:
        lines.append("> 以下事项 PRD 未明示，**阻塞 breakdown_tasks**。请 PM 补全后重发。")
        lines.append("")
        for m in missing_info:
            lines.append(f"- {m}")
        lines.append("")
    else:
        lines.append("（PRD 信息完整 — 可直接进入 breakdown_tasks 阶段）")
        lines.append("")

    # 历史 ADR 引用
    if adr_history:
        lines.append(f"## 历史 ADR 引用")
        lines.append("")
        for adr in adr_history[:10]:
            lines.append(
                f"- {adr.get('display_number') or ('ADR-' + str(adr.get('number')))}: "
                f"{adr.get('title')} (status={adr.get('status')})"
            )
        lines.append("")

    # 元信息
    lines.append(f"## 元信息")
    lines.append("")
    lines.append(f"- focus: {focus or '（未指定）'}")
    lines.append(f"- constraints: {constraints or '（未指定）'}")
    lines.append(f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(
        "- 决策者: 程小远（AICTO Phase 1 · KR4 SLA ≤5 分钟 · ADR 自动写入）"
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 公共辅助
# ---------------------------------------------------------------------------


def _summarize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """日志/上下文用 — 截断敏感长字段。"""
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "...（截断）"
        else:
            out[k] = v
    return out


def _summarize_requirement_gate(gate: Dict[str, Any]) -> Dict[str, Any]:
    """压缩门禁结果，避免把每个字段值重复塞进技术方案主返回。"""
    return {
        "gate": gate.get("gate"),
        "gate_status": gate.get("gate_status"),
        "passes": gate.get("passes"),
        "blocking_downstream": gate.get("blocking_downstream"),
        "metadata_contract": gate.get("metadata_contract"),
        "missing_required_sections": gate.get("missing_required_sections") or [],
        "blank_or_unknown_sections": gate.get("blank_or_unknown_sections") or [],
        "explicit_none_sections": gate.get("explicit_none_sections") or [],
        "clarification_request": gate.get("clarification_request") or [],
    }


def _requirement_gate_block_response(
    *,
    requirement_gate: Dict[str, Any],
    args: Dict[str, Any],
    ctx: Dict[str, Any],
    project_id: Optional[str],
    project_name: str,
    prd_title: str,
    elapsed: float,
) -> str:
    """需求门禁未通过时返回结构化阻塞结果，不进入 LLM/ADR/飞书。"""
    clarification_request = requirement_gate.get("clarification_request") or []
    missing_info = [
        "需求元数据门禁未通过：AICTO 只接受原子级 PRD 元数据；"
        "5W1H 与「增删查改显算传」必须全量出现，不涉及也写「无」。",
        *clarification_request,
    ]
    aipm_clarification = aipm_cto_collaboration.request_requirement_clarification(
        {
            "project_id": project_id,
            "project_name": project_name,
            "prd_id": ctx.get("prd_id_resolved"),
            "requirement_id": _extract_requirement_id(requirement_gate),
            "title": prd_title,
            "missing_info": missing_info,
            "conflict_or_unconfirmed_sections": requirement_gate.get(
                "conflict_or_unconfirmed_sections"
            )
            or [],
            "requires_user_confirmation": requirement_gate.get(
                "requires_user_feishu_confirmation"
            ),
            "aipm_clarification_protocol": requirement_gate.get(
                "aipm_clarification_protocol"
            )
            or {},
            "target_chat_id": args.get("aipm_target_chat_id"),
            "dry_run": bool(args.get("dry_run_aipm_clarification", False)),
            "record_memory": args.get("record_memory", True),
        }
    )
    markdown_doc = "\n".join(
        [
            f"# {project_name} — 需求元数据未通过",
            "",
            f"> PRD: **{prd_title}**",
            f"> 程小远（AICTO）拒绝进入技术方案阶段 · {time.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 阻塞原因",
            "",
            "当前输入不是可执行的原子 PRD 元数据。AICTO 不会基于残缺需求生成技术方案。",
            "",
            "## 需要补充",
            "",
            *[f"- {item}" for item in missing_info],
            "",
            "## 标准模板",
            "",
            requirement_gate.get("best_practice_template") or "",
        ]
    )
    return _success(
        {
            "feasibility": "yellow",
            "improvement_path": "请 AIPM/需求方按 requirement_gate.best_practice_template 补齐后重新提交。",
            "summary": "需求元数据不完整，已阻断技术方案生成。",
            "tech_stack": [],
            "estimate": {},
            "risks": [
                {
                    "title": "残缺 PRD 导致技术方案幻觉",
                    "severity": "high",
                    "probability": "high",
                    "mitigation": "先补齐用户对齐、5W1H 与增删查改显算传；必要时由 AIPM 在飞书向用户确认，再进入 design_tech_plan。",
                }
            ],
            "missing_info": missing_info,
            "blocking_downstream": True,
            "requirement_gate": requirement_gate,
            "aipm_clarification": aipm_clarification,
            "feishu_doc_url": None,
            "feishu_doc_id": None,
            "feishu_error": None,
            "markdown_doc": markdown_doc,
            "adr_ids": [],
            "adr_write_errors": [
                "requirement metadata gate failed; ADR writes skipped"
            ],
            "project_id": project_id,
            "prd_id": ctx.get("prd_id_resolved"),
            "elapsed_seconds": round(elapsed, 2),
            "kr4_compliant": elapsed <= KR4_SLA_SECONDS,
        }
    )


def _extract_requirement_id(requirement_gate: Dict[str, Any]) -> Optional[str]:
    try:
        value = (
            (requirement_gate.get("sections") or {})
            .get("requirement_id", {})
            .get("value")
        )
        return str(value) if value else None
    except Exception:  # noqa: BLE001
        return None


def _success(payload: Dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _fail(message: str, *, level: str, elapsed: float) -> str:
    return json.dumps(
        {
            "error": message,
            "level": level,
            "elapsed_seconds": round(elapsed, 2),
            "kr4_compliant": elapsed <= KR4_SLA_SECONDS,
        },
        ensure_ascii=False,
    )


__all__ = ["run", "KR4_SLA_SECONDS", "HARDCODED_LEGION_PROFILES"]
