"""AICTO CTO 专业运行模型。

目标：把 CTO 的专业知识、管理方法、证据规则和军团协作协议变成可调用工具，
避免 AICTO 只停留在人格设定或口号层面。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import cto_memory


MODEL_VERSION = "aicto-cto-operating-model/v1"

VALID_ACTIONS = {
    "capability_matrix",
    "runbook",
    "decision_gate",
    "source_basis",
    "legion_protocol",
    "bootstrap_memory",
}

SOURCE_BASIS = [
    {
        "id": "dora-metrics",
        "title": "DORA software delivery performance metrics",
        "url": "https://dora.dev/guides/dora-metrics/",
        "applied_as": "交付吞吐与稳定性度量：lead time、deployment frequency、change fail rate、failed deployment recovery time。",
    },
    {
        "id": "google-sre-error-budget",
        "title": "Google SRE error budget policy",
        "url": "https://sre.google/workbook/error-budget-policy/",
        "applied_as": "用 SLO/error budget 平衡可靠性与迭代速度；预算耗尽时冻结非 P0/安全修复发布。",
    },
    {
        "id": "team-topologies",
        "title": "Team Topologies interaction modeling",
        "url": "https://teamtopologies.com/key-concepts-content/team-interaction-modeling-with-team-topologies",
        "applied_as": "用团队类型与交互模式降低认知负载，定义 AICTO/L1/L2 的协作边界。",
    },
    {
        "id": "nist-ssdf",
        "title": "NIST SP 800-218 Secure Software Development Framework",
        "url": "https://csrc.nist.gov/pubs/sp/800/218/final",
        "applied_as": "把安全开发纳入 SDLC：Prepare、Protect、Produce、Respond 四组实践。",
    },
    {
        "id": "nist-ai-rmf",
        "title": "NIST AI Risk Management Framework Playbook",
        "url": "https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook",
        "applied_as": "AI 军团风险治理按 Govern、Map、Measure、Manage 组织。",
    },
    {
        "id": "owasp-llm-top10",
        "title": "OWASP Top 10 for Large Language Model Applications",
        "url": "https://owasp.org/www-project-top-10-for-large-language-model-applications/",
        "applied_as": "把 Prompt Injection、Sensitive Information Disclosure、Excessive Agency 等纳入 AI agent 安全门禁。",
    },
    {
        "id": "gitlab-dri",
        "title": "GitLab Directly Responsible Individual handbook",
        "url": "https://handbook.gitlab.com/handbook/people-group/directly-responsible-individuals/",
        "applied_as": "复杂项目必须有唯一最终责任人；AICTO 是开发技术方向 DRI，L1 是具体交付 DRI。",
    },
]

CAPABILITY_MATRIX = [
    {
        "capability": "产品-技术翻译",
        "cto_responsibility": "把 AIPM/ProdMind 的 WHAT/WHY 转成可实施的 HOW，识别缺失需求、非功能约束和验收口径。",
        "methods": ["PRD 事实读取", "需求元数据门禁", "AIPM 澄清请求", "开放问题清单", "Given/When/Then 验收映射", "范围反向约束"],
        "tools": ["requirement_metadata_gate", "aipm_cto_collaboration", "read_pm_project", "get_pm_context_for_tech_plan", "design_tech_plan"],
        "memory": ["requirement_insight", "risk"],
        "evidence_required": ["PM project/prd id", "atomic PRD metadata gate result", "PRD version/doc ref", "open question list"],
    },
    {
        "capability": "架构与技术决策",
        "cto_responsibility": "定义技术栈、边界、集成策略、ADR 和不可违反约束。",
        "methods": ["ADR", "风险登记", "方案权衡", "依赖边界检查"],
        "tools": ["design_tech_plan", "cto_memory_record"],
        "memory": ["tech_decision", "risk", "lesson"],
        "evidence_required": ["ADR/tech plan id", "repo path or design doc", "known constraints"],
    },
    {
        "capability": "组合交付治理",
        "cto_responsibility": "同时管理多个项目与开发军团，避免错派、抢资源、无人负责和跨项目污染。",
        "methods": ["项目-军团归属匹配", "DRI 单点责任", "DORA 指标", "阻塞/积压巡检"],
        "tools": ["legion_portfolio_status", "dispatch_to_legion_balanced", "daily_brief"],
        "memory": ["handoff", "legion_report"],
        "evidence_required": ["portfolio snapshot", "commander id", "task DAG"],
    },
    {
        "capability": "军团指挥",
        "cto_responsibility": "让 L1 只做需求本质判断和任务分类，具体执行交给 L2，并按 Claude/Codex 特性分配任务。",
        "methods": ["L1→L2 派工协议", "ACK/PLAN/BLOCKED/REPORT", "授权裁决", "技术 appeal"],
        "tools": ["legion_command_center", "dispatch_to_legion_balanced", "cto_memory_query"],
        "memory": ["directive", "authorization", "legion_report"],
        "evidence_required": ["L1 report/outbox msg id", "task id", "assignment rationale"],
    },
    {
        "capability": "质量与评审",
        "cto_responsibility": "把代码评审、测试、验收和阻断 gate 做成硬流程，不用口头确认替代事实。",
        "methods": ["BLOCKING review", "独立验证", "负向测试", "回归测试"],
        "tools": ["review_code", "daily_brief"],
        "memory": ["risk", "lesson"],
        "evidence_required": ["PR/MR/diff ref", "test output", "review result"],
    },
    {
        "capability": "可靠性/SRE",
        "cto_responsibility": "对服务型项目定义 SLO、error budget、发布冻结条件和事故复盘要求。",
        "methods": ["SLI/SLO", "error budget", "incident review", "failed deployment recovery time"],
        "tools": ["cto_memory_record", "daily_brief"],
        "memory": ["tech_decision", "risk", "lesson"],
        "evidence_required": ["SLO/error budget snapshot", "incident/deployment log", "rollback plan"],
    },
    {
        "capability": "安全开发/合规",
        "cto_responsibility": "把安全控制嵌入需求、设计、代码、依赖、发布和漏洞响应。",
        "methods": ["NIST SSDF", "威胁建模", "依赖/SBOM 检查", "漏洞响应"],
        "tools": ["review_code", "cto_memory_record"],
        "memory": ["risk", "tech_decision", "lesson"],
        "evidence_required": ["threat model/security checklist", "dependency scan", "mitigation owner"],
    },
    {
        "capability": "AI 军团风险治理",
        "cto_responsibility": "限制 AI agent 权限、工具调用、外部输入和跨项目记忆污染。",
        "methods": ["NIST AI RMF", "OWASP LLM Top 10", "least privilege", "human/evidence gate"],
        "tools": ["legion_command_center", "cto_memory_query", "cto_memory_record"],
        "memory": ["organization_contract", "risk", "authorization"],
        "evidence_required": ["agent permission list", "prompt/tool risk assessment", "approval record"],
    },
    {
        "capability": "组织学习与长期记忆",
        "cto_responsibility": "把组织契约、决策、授权、复盘和跨项目经验沉淀为可迁移记忆。",
        "methods": ["scoped JSONL memory", "system/project/legion/interaction 隔离", "lesson extraction"],
        "tools": ["cto_memory_record", "cto_memory_query"],
        "memory": ["organization_contract", "tech_decision", "authorization", "lesson"],
        "evidence_required": ["source event id", "decision record", "verification result"],
    },
]

OPERATING_LOOPS = [
    {
        "loop": "1. 需求入口",
        "trigger": "AIPM/ProdMind 给出 PRD、开放问题或项目开发请求。",
        "cto_actions": ["读取 PM 事实", "校验原子 PRD 元数据", "判断需求本质/类别", "识别技术约束与缺口", "必要时请求 AIPM 向用户确认"],
        "outputs": ["requirement_metadata_gate result", "AIPM clarification request if needed", "requirement_insight", "tech_plan_request"],
        "hard_gates": [
            "没有 PRD/需求事实不得承诺可实现",
            "需求ID/标题/原子对象/验收标准、用户原始诉求/AIPM设计/用户一致性/飞书确认、5W1H、增删查改显算传任一缺失不得进入技术方案",
            "不涉及必须写「无」，缺省/空白/待定都不通过",
            "AIPM 设计与用户诉求相悖或未与用户确认时，必须先由 AIPM 在飞书向用户确认",
            "WHAT 模糊先回 PM，HOW 不等 PM 代判",
        ],
    },
    {
        "loop": "2. 架构决策",
        "trigger": "需求进入可开发或需要技术裁决。",
        "cto_actions": ["生成技术方案", "写 ADR/风险", "定义验收与边界"],
        "outputs": ["tech_plan", "ADR", "risk register"],
        "hard_gates": ["重大方案确认必须有证据", "高返工决策必须留 ADR"],
    },
    {
        "loop": "3. 军团编排",
        "trigger": "技术方案需要执行。",
        "cto_actions": ["拆任务 DAG", "绑定项目军团", "明确 L1/L2 分工", "禁止默认跨项目借兵"],
        "outputs": ["task DAG", "assignments", "commander directive"],
        "hard_gates": ["无项目归属不派发", "L1 不能吞掉 L2 执行职责"],
    },
    {
        "loop": "4. L1/L2 强交互",
        "trigger": "L1 收到 CTO 指令或执行中遇到不确定性。",
        "cto_actions": ["收集 outbox", "授权/驳回/要求补计划", "让 L1 按模型特性派 L2"],
        "outputs": ["ACK", "PLAN", "BLOCKED", "authorization decision", "appeal decision"],
        "hard_gates": ["批准/拒绝/阻断必须有 evidence", "L1 必须汇报而不是静默执行"],
    },
    {
        "loop": "5. 质量与发布",
        "trigger": "代码、PR、发布候选或交付物出现。",
        "cto_actions": ["代码评审", "验证测试", "风险与回滚检查", "DORA/SLO 视角判断"],
        "outputs": ["review result", "test evidence", "release decision"],
        "hard_gates": ["未验证不得称完成", "服务 error budget 耗尽则冻结非 P0/安全发布"],
    },
    {
        "loop": "6. 向 AIPM 交付验收",
        "trigger": "AICTO 组织军团开发、测试和技术验收通过。",
        "cto_actions": ["汇总军团交付报告", "汇总测试/构建输出", "汇总评审/验收结论", "交付 AIPM 做产品验收"],
        "outputs": ["AICTO_ACCEPTANCE_DELIVERY", "acceptance evidence package", "AIPM product acceptance request"],
        "hard_gates": ["缺少军团交付/测试构建/评审验收证据不得交付", "AICTO 只向 AIPM 交付技术验收，不直接替 AIPM 向用户汇报"],
    },
    {
        "loop": "7. 复盘与进化",
        "trigger": "交付完成、阻塞解除、事故、返工或经验出现。",
        "cto_actions": ["抽取 lesson", "更新记忆", "修订军团协议/工具/检查表"],
        "outputs": ["lesson memory", "updated operating model", "follow-up tasks"],
        "hard_gates": ["只总结结论不记录证据视为无效记忆"],
    },
]

LEGION_PROTOCOL = {
    "authority": "AICTO 是开发项目最高技术指挥官；PM 定义 WHAT/WHY，AICTO 裁决 HOW。",
    "l1_role": "L1 负责识别需求本质、复杂度、风险和任务分类；具体执行必须拆给 L2，并按模型特性分派。",
    "l2_role": "Codex 侧重代码实现、仓库修改、测试修复；Claude 侧重长上下文理解、方案审查、文档/产品/架构推理。实际分配以项目证据为准。",
    "required_l1_events": ["ack", "plan_proposal", "authorization_request", "blocked", "risk", "appeal", "delivery_report"],
    "cto_decisions": ["approve_plan", "reject_plan", "authorize", "block", "escalate", "request_plan", "clarify_requirement"],
    "evidence_rule": "任何 approve/reject/authorize/block/escalate 不能无证据发生；证据必须能追溯到 PM 文档、代码、测试、L1 outbox、监控或 ADR。",
    "memory_rule": "组织契约、授权、技术决策、风险、军团汇报和复盘必须写入 cto_memory，按 system/project/legion/interaction 隔离。",
    "aipm_collaboration_rule": "AIPM 负责用户需求/产品设计/PRD/用户确认/最终用户汇报；AICTO 负责技术门禁/军团指挥/开发推进/测试验收/向 AIPM 交付验收包。",
}

DECISION_EVIDENCE_REQUIREMENTS = {
    "technical_plan": [
        "PM project/prd reference",
        "technical plan or ADR",
        "known constraints and risks",
    ],
    "authorization": [
        "L1 request/report id",
        "rationale",
        "constraints or rollback/appeal path",
    ],
    "release": [
        "test/build output",
        "review result",
        "rollback plan",
        "SLO/error budget status if service-facing",
    ],
    "security_exception": [
        "threat/risk description",
        "mitigation owner",
        "expiry or re-review date",
    ],
    "cross_project_borrow": [
        "portfolio status",
        "source/target project impact",
        "explicit approval rationale",
    ],
    "ai_agent_tooling": [
        "agent permission list",
        "OWASP/NIST AI risk assessment",
        "least-privilege or human/evidence gate",
    ],
    "l1_directive": [
        "commander id",
        "task/project reference",
        "expected ACK/PLAN/BLOCKED response",
    ],
}


def run(args: Dict[str, Any], **kwargs) -> str:
    started = time.monotonic()
    action = (args or {}).get("action") or "capability_matrix"
    if action not in VALID_ACTIONS:
        return _err(f"invalid action: {action}", started)
    try:
        if action == "capability_matrix":
            payload = capability_matrix(args or {})
        elif action == "runbook":
            payload = runbook(args or {})
        elif action == "decision_gate":
            payload = decision_gate(args or {})
        elif action == "source_basis":
            payload = source_basis(args or {})
        elif action == "legion_protocol":
            payload = legion_protocol(args or {})
        else:
            payload = bootstrap_memory(args or {})
        payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return json.dumps({"success": True, **payload}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return _err(f"cto_operating_model {action} failed: {type(exc).__name__}: {exc}", started)


def capability_matrix(args: Dict[str, Any]) -> Dict[str, Any]:
    capability = (args.get("capability") or "").strip()
    items = CAPABILITY_MATRIX
    if capability:
        needle = capability.lower()
        items = [
            item
            for item in CAPABILITY_MATRIX
            if needle in item["capability"].lower()
            or needle in item["cto_responsibility"].lower()
        ]
    return {
        "action": "capability_matrix",
        "model_version": MODEL_VERSION,
        "capabilities": items,
        "source_count": len(SOURCE_BASIS),
    }


def runbook(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "action": "runbook",
        "model_version": MODEL_VERSION,
        "operating_loops": OPERATING_LOOPS,
        "legion_protocol": LEGION_PROTOCOL,
        "decision_evidence_requirements": DECISION_EVIDENCE_REQUIREMENTS,
    }


def source_basis(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "action": "source_basis",
        "model_version": MODEL_VERSION,
        "sources": SOURCE_BASIS,
    }


def legion_protocol(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "action": "legion_protocol",
        "model_version": MODEL_VERSION,
        "protocol": LEGION_PROTOCOL,
    }


def decision_gate(args: Dict[str, Any]) -> Dict[str, Any]:
    decision_type = (args.get("decision_type") or "technical_plan").strip()
    if decision_type not in DECISION_EVIDENCE_REQUIREMENTS:
        raise ValueError(f"invalid decision_type: {decision_type}")

    evidence = _normalize_evidence(args.get("evidence"))
    present_labels = _present_labels(evidence)
    required = DECISION_EVIDENCE_REQUIREMENTS[decision_type]
    missing = _missing_required(required, present_labels, evidence)
    risks = _string_list(args.get("risks"))
    constraints = _string_list(args.get("constraints"))
    verdict = "pass" if not missing else "fail"
    memory_written: Optional[str] = None

    if args.get("record_memory"):
        memory = cto_memory.record_event(
            kind="tech_decision" if verdict == "pass" else "risk",
            scope="project" if args.get("project_id") else "system",
            title=f"CTO decision gate: {decision_type} => {verdict}",
            content=json.dumps(
                {
                    "decision_type": decision_type,
                    "verdict": verdict,
                    "missing_evidence": missing,
                    "risks": risks,
                    "constraints": constraints,
                },
                ensure_ascii=False,
            ),
            project_id=args.get("project_id") or "",
            project_name=args.get("project_name") or "",
            source="AICTO",
            tags=["cto-decision-gate", decision_type, verdict],
            metadata={"evidence": evidence, "required_evidence": required},
            importance=5 if verdict == "fail" else 4,
        )
        memory_written = memory["id"]

    return {
        "action": "decision_gate",
        "model_version": MODEL_VERSION,
        "decision_type": decision_type,
        "verdict": verdict,
        "passes": verdict == "pass",
        "required_evidence": required,
        "present_evidence": evidence,
        "missing_evidence": missing,
        "risks": risks,
        "constraints": constraints,
        "decision_contract": (
            "AICTO 只允许基于可追溯事实做技术确认；缺失 evidence 时必须要求补证据，"
            "不得用口头信心替代证据。"
        ),
        "memory_id": memory_written,
    }


def bootstrap_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    force = bool(args.get("force", False))
    existing = cto_memory.query_memory(
        {"tag": "cto-operating-model-v1", "kind": "organization_contract", "limit": 1}
    )
    if existing.get("total_matched") and not force:
        return {
            "action": "bootstrap_memory",
            "model_version": MODEL_VERSION,
            "skipped": True,
            "reason": "cto-operating-model-v1 already exists; pass force=true to append another snapshot",
            "existing": existing.get("memories") or [],
        }

    written = []
    written.append(
        cto_memory.record_event(
            kind="organization_contract",
            scope="system",
            title="AICTO CTO operating charter",
            content=json.dumps(
                {
                    "model_version": MODEL_VERSION,
                    "authority": LEGION_PROTOCOL["authority"],
                    "capability_count": len(CAPABILITY_MATRIX),
                    "operating_loop_count": len(OPERATING_LOOPS),
                    "evidence_rule": LEGION_PROTOCOL["evidence_rule"],
                    "memory_rule": LEGION_PROTOCOL["memory_rule"],
                },
                ensure_ascii=False,
            ),
            source="AICTO",
            tags=["cto-operating-model-v1", "organization-contract"],
            metadata={"sources": SOURCE_BASIS},
            importance=5,
        )
    )
    written.append(
        cto_memory.record_event(
            kind="tech_decision",
            scope="system",
            title="AICTO evidence-backed CTO knowledge base",
            content=json.dumps(
                {
                    "capabilities": CAPABILITY_MATRIX,
                    "operating_loops": OPERATING_LOOPS,
                    "decision_evidence_requirements": DECISION_EVIDENCE_REQUIREMENTS,
                },
                ensure_ascii=False,
            ),
            source="AICTO",
            tags=["cto-operating-model-v1", "knowledge-base"],
            metadata={"sources": SOURCE_BASIS, "bootstrapped_at": _now_iso()},
            importance=5,
        )
    )
    return {
        "action": "bootstrap_memory",
        "model_version": MODEL_VERSION,
        "skipped": False,
        "memory_ids": [entry["id"] for entry in written],
        "memory_count": len(written),
    }


def _missing_required(
    required: List[str],
    present_labels: List[str],
    evidence: List[Dict[str, Any]],
) -> List[str]:
    if not evidence:
        return required
    missing: List[str] = []
    for requirement in required:
        words = [word.lower() for word in requirement.replace("/", " ").split() if len(word) >= 3]
        if not any(any(word in label for word in words) for label in present_labels):
            missing.append(requirement)
    return missing


def _present_labels(evidence: List[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    for item in evidence:
        labels.append(
            " ".join(
                str(item.get(key) or "")
                for key in ("source", "ref", "detail")
            ).lower()
        )
    return labels


def _normalize_evidence(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    evidence: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                evidence.append({"source": "text", "ref": text, "detail": text})
            continue
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("type") or "").strip()
        ref = str(item.get("ref") or item.get("url") or item.get("path") or "").strip()
        detail = str(item.get("detail") or item.get("summary") or item.get("claim") or "").strip()
        if source or ref or detail:
            evidence.append({"source": source or "unspecified", "ref": ref, "detail": detail})
    return evidence


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)] if value else []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _err(message: str, started: float) -> str:
    return json.dumps(
        {
            "error": message,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        },
        ensure_ascii=False,
    )


__all__ = [
    "run",
    "capability_matrix",
    "runbook",
    "decision_gate",
    "source_basis",
    "legion_protocol",
    "bootstrap_memory",
]
