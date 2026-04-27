"""aipm_cto_collaboration.py — AIPM ↔ AICTO 独立项目协作协议。

AIPM/ProdMind 与 AICTO 是两个独立项目：
- AIPM 负责收集用户需求、产品设计、PRD、用户确认、最终用户汇报。
- AICTO 负责需求技术入口门禁、实现方案、军团指挥、组织测试验收、向 AIPM 交付验收包。

本模块只实现 AICTO 侧的协作协议和飞书通知，不直接修改 AIPM/ProdMind 的 PRD 数据。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import cto_memory, feishu_api


PM_CHAT_ENV = "AICTO_PM_FEISHU_CHAT_ID"
MODEL_VERSION = "aipm-cto-collaboration/v1"

VALID_ACTIONS = {
    "workflow_contract",
    "request_requirement_clarification",
    "deliver_acceptance_to_aipm",
}

WORKFLOW_CONTRACT = {
    "independent_projects": True,
    "projects": {
        "AIPM/ProdMind": {
            "path": "/Users/feijun/Documents/prodmind",
            "owns": ["用户需求收集", "需求辨识", "产品设计", "PRD", "用户确认", "最终用户汇报"],
            "must_not_delegate_to_aicto": ["替用户做产品确认", "让 AICTO 直接改 PRD"],
        },
        "AICTO": {
            "path": "/Users/feijun/Documents/AICTO",
            "owns": ["需求技术门禁", "技术方案", "军团指挥", "开发推进", "测试组织", "技术验收", "验收包交付 AIPM"],
            "must_not_delegate_to_aipm": ["技术方案裁决", "军团调度", "测试事实判断"],
        },
    },
    "stages": [
        {
            "stage": "1_user_requirement_collection",
            "owner": "AIPM",
            "output": "原子 PRD 元数据 + 用户原始诉求 + 飞书确认记录",
            "handoff_event": "AIPM_REQUIREMENT_READY",
        },
        {
            "stage": "2_joint_requirement_clarification",
            "owner": "AICTO + AIPM",
            "output": "AICTO 给出缺口/冲突；AIPM 负责向用户确认并更新 PRD",
            "handoff_event": "AICTO_CLARIFICATION_REQUEST / AIPM_REQUIREMENT_READY",
        },
        {
            "stage": "3_technical_planning",
            "owner": "AICTO",
            "output": "技术方案、ADR、风险、任务 DAG",
            "handoff_event": "AICTO_TECH_PLAN_READY",
        },
        {
            "stage": "4_legion_delivery",
            "owner": "AICTO",
            "output": "L1/L2 执行、代码、测试、验收证据",
            "handoff_event": "AICTO_ACCEPTANCE_DELIVERY",
        },
        {
            "stage": "5_product_acceptance_and_user_report",
            "owner": "AIPM",
            "output": "产品验收结论 + 面向用户的汇报",
            "handoff_event": "AIPM_USER_REPORT_DONE",
        },
    ],
    "hard_gates": [
        "需求不明细、与用户诉求相悖、或没有用户确认记录时，AICTO 必须阻断并请求 AIPM 澄清。",
        "AIPM 未更新 PRD 前，AICTO 不进入技术方案、拆任务或派军团。",
        "AICTO 未组织测试验收并提供证据前，不得向 AIPM 声称交付通过。",
        "AIPM 未完成产品验收前，不得向用户汇报已完成。",
    ],
}

ACCEPTANCE_REQUIRED_EVIDENCE = [
    "legion delivery/report",
    "test/build output",
    "review/acceptance result",
]


def run(args: Dict[str, Any], **kwargs) -> str:
    started = time.monotonic()
    action = (args or {}).get("action") or "workflow_contract"
    if action not in VALID_ACTIONS:
        return _err(f"invalid action: {action}", started)
    try:
        if action == "workflow_contract":
            payload = workflow_contract(args or {})
        elif action == "request_requirement_clarification":
            payload = request_requirement_clarification(args or {})
        else:
            payload = deliver_acceptance_to_aipm(args or {})
        payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return json.dumps({"success": True, **payload}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return _err(f"aipm_cto_collaboration {action} failed: {type(exc).__name__}: {exc}", started)


def workflow_contract(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "action": "workflow_contract",
        "model_version": MODEL_VERSION,
        "contract": WORKFLOW_CONTRACT,
    }


def request_requirement_clarification(args: Dict[str, Any]) -> Dict[str, Any]:
    """AICTO 发现需求不明细/冲突时，主动请求 AIPM 澄清。"""
    message = _build_clarification_message(args)
    notification = _notify_aipm(
        message=message,
        target_chat_id=args.get("target_chat_id"),
        dry_run=bool(args.get("dry_run", False)),
    )
    memory = _maybe_record_memory(
        should_record=args.get("record_memory", True),
        kind="requirement_insight",
        title=f"AICTO requested AIPM clarification: {args.get('requirement_id') or args.get('prd_id') or 'unknown'}",
        content=message,
        args=args,
        tags=["aipm-cto-collaboration", "requirement-clarification"],
    )
    requires_user_confirmation = bool(args.get("requires_user_confirmation"))
    return {
        "action": "request_requirement_clarification",
        "model_version": MODEL_VERSION,
        "next_owner": "AIPM",
        "aicto_state": (
            "blocked_waiting_aipm_user_confirmation"
            if requires_user_confirmation
            else "blocked_waiting_aipm_prd_update"
        ),
        "blocking_downstream": True,
        "requires_user_confirmation": requires_user_confirmation,
        "message": message,
        "notification": notification,
        "memory": memory,
        "contract": WORKFLOW_CONTRACT,
    }


def deliver_acceptance_to_aipm(args: Dict[str, Any]) -> Dict[str, Any]:
    """AICTO 组织开发/测试验收通过后，把验收包交付给 AIPM。"""
    evidence = _normalize_evidence(args.get("evidence"))
    missing_evidence = _missing_acceptance_evidence(evidence)
    if missing_evidence:
        return {
            "action": "deliver_acceptance_to_aipm",
            "model_version": MODEL_VERSION,
            "handoff_status": "blocked_missing_acceptance_evidence",
            "blocking_downstream": True,
            "missing_evidence": missing_evidence,
            "required_evidence": ACCEPTANCE_REQUIRED_EVIDENCE,
            "next_owner": "AICTO",
            "message": "AICTO 不能向 AIPM 交付验收：缺少开发/测试/评审事实证据。",
        }

    message = _build_acceptance_delivery_message(args, evidence)
    notification = _notify_aipm(
        message=message,
        target_chat_id=args.get("target_chat_id"),
        dry_run=bool(args.get("dry_run", False)),
    )
    memory = _maybe_record_memory(
        should_record=args.get("record_memory", True),
        kind="handoff",
        title=f"AICTO delivered acceptance to AIPM: {args.get('project_name') or args.get('project_id') or 'unknown'}",
        content=message,
        args=args,
        tags=["aipm-cto-collaboration", "acceptance-delivery"],
    )
    return {
        "action": "deliver_acceptance_to_aipm",
        "model_version": MODEL_VERSION,
        "handoff_status": "delivered_to_aipm",
        "blocking_downstream": False,
        "next_owner": "AIPM",
        "aipm_required_actions": [
            "AIPM 按 PRD 验收口径做产品验收。",
            "AIPM 如发现产品口径偏差，回退给 AICTO 并附具体验收失败证据。",
            "AIPM 产品验收通过后，在飞书中向用户汇报结果、范围、证据和未做事项。",
        ],
        "evidence": evidence,
        "message": message,
        "notification": notification,
        "memory": memory,
    }


def _build_clarification_message(args: Dict[str, Any]) -> str:
    missing = _string_list(args.get("missing_info") or args.get("missing_required_sections"))
    conflicts = _string_list(args.get("conflict_notes") or args.get("conflict_or_unconfirmed_sections"))
    protocol = args.get("aipm_clarification_protocol") or {}
    user_questions = protocol.get("user_confirmation_questions") or WORKFLOW_CONTRACT["hard_gates"]
    lines = [
        "【AICTO → AIPM｜需求澄清请求】",
        f"项目：{args.get('project_name') or args.get('project_id') or '未指定'}",
        f"PRD：{args.get('prd_id') or '未指定'}",
        f"需求：{args.get('requirement_id') or args.get('title') or '未指定'}",
        "",
        "AICTO 判断：当前需求不能进入技术方案/军团派发。",
    ]
    if missing:
        lines.append("缺失/不明细：")
        lines.extend(f"- {item}" for item in missing)
    if conflicts:
        lines.append("用户对齐风险：")
        lines.extend(f"- {item}" for item in conflicts)
    lines.extend(
        [
            "",
            "AIPM 必须执行：",
            "1. 回到用户原始诉求，确认需求场景。",
            "2. 如设计方向/思路/边界未和用户探讨，必须在飞书中向用户确认并留下记录。",
            "3. 更新原子 PRD 元数据：用户原始诉求、AIPM 设计思路、用户一致性判断、飞书用户确认记录、5W1H、增删查改显算传。",
            "4. 更新后重新交给 AICTO；AICTO 门禁通过后才继续技术方案。",
            "",
            "建议向用户确认的问题：",
        ]
    )
    lines.extend(f"- {item}" for item in user_questions[:6])
    return "\n".join(lines)


def _build_acceptance_delivery_message(
    args: Dict[str, Any],
    evidence: List[Dict[str, Any]],
) -> str:
    lines = [
        "【AICTO → AIPM｜开发验收交付】",
        f"项目：{args.get('project_name') or args.get('project_id') or '未指定'}",
        f"PRD：{args.get('prd_id') or '未指定'}",
        f"版本/范围：{args.get('scope') or '未指定'}",
        "",
        "AICTO 结论：军团开发、测试、技术验收已通过，现交付 AIPM 做产品验收。",
        "",
        "验收摘要：",
        args.get("summary") or "（未提供摘要）",
        "",
        "事实证据：",
    ]
    for item in evidence:
        lines.append(f"- [{item['source']}] {item['ref']} — {item['detail']}")
    lines.extend(
        [
            "",
            "AIPM 下一步：",
            "1. 按 PRD/用户确认记录做产品验收。",
            "2. 验收通过后向用户汇报：已完成范围、验收证据、未做事项、后续建议。",
            "3. 验收不通过则带具体失败证据退回 AICTO。",
        ]
    )
    return "\n".join(lines)


def _notify_aipm(
    *,
    message: str,
    target_chat_id: Optional[str],
    dry_run: bool,
) -> Dict[str, Any]:
    chat_id = (target_chat_id or os.environ.get(PM_CHAT_ENV, "")).strip()
    if dry_run:
        return {
            "sent_via_feishu": False,
            "dry_run": True,
            "target_chat_id": chat_id or None,
            "error": None,
        }
    if not chat_id:
        return {
            "sent_via_feishu": False,
            "dry_run": False,
            "target_chat_id": None,
            "error": f"{PM_CHAT_ENV} empty",
        }
    try:
        feishu_api.send_text_to_chat(chat_id, message)
        return {
            "sent_via_feishu": True,
            "dry_run": False,
            "target_chat_id": chat_id,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "sent_via_feishu": False,
            "dry_run": False,
            "target_chat_id": chat_id,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _maybe_record_memory(
    *,
    should_record: bool,
    kind: str,
    title: str,
    content: str,
    args: Dict[str, Any],
    tags: List[str],
) -> Dict[str, Any]:
    if not should_record:
        return {"recorded": False, "reason": "record_memory=false"}
    try:
        entry = cto_memory.record_event(
            kind=kind,
            scope="project" if args.get("project_id") else "interaction",
            title=title,
            content=content,
            project_id=args.get("project_id") or "",
            project_name=args.get("project_name") or "",
            source="AICTO",
            tags=tags,
            metadata={
                "model_version": MODEL_VERSION,
                "prd_id": args.get("prd_id"),
                "requirement_id": args.get("requirement_id"),
                "recorded_at": _now_iso(),
            },
            importance=5,
        )
        return {"recorded": True, "memory_id": entry["id"]}
    except Exception as exc:  # noqa: BLE001
        return {"recorded": False, "error": f"{type(exc).__name__}: {exc}"}


def _normalize_evidence(value: Any) -> List[Dict[str, str]]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    evidence: List[Dict[str, str]] = []
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
            evidence.append(
                {"source": source or "unspecified", "ref": ref, "detail": detail}
            )
    return evidence


def _missing_acceptance_evidence(evidence: List[Dict[str, str]]) -> List[str]:
    if not evidence:
        return ACCEPTANCE_REQUIRED_EVIDENCE
    labels = [
        " ".join([item.get("source", ""), item.get("ref", ""), item.get("detail", "")]).lower()
        for item in evidence
    ]
    checks = {
        "legion delivery/report": ["legion", "l1", "l2", "delivery", "report", "军团"],
        "test/build output": ["test", "build", "pytest", "unittest", "测试", "构建"],
        "review/acceptance result": ["review", "acceptance", "验收", "评审"],
    }
    missing: List[str] = []
    for requirement, words in checks.items():
        if not any(any(word in label for word in words) for label in labels):
            missing.append(requirement)
    return missing


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item]
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
    "workflow_contract",
    "request_requirement_clarification",
    "deliver_acceptance_to_aipm",
]
