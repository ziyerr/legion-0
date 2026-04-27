"""AICTO ↔ L1 军团指挥中枢。

定位：程小远是开发军团最高技术指挥官。L1 应直接听 CTO 指挥、向 CTO
汇报，并在需求/授权/方案存在不确定时请求 CTO 决策。

本模块提供三类动作：
- collect_reports：收集 L1 outbox 汇报/授权请求/方案讨论。
- send_directive：向 L1 发送 CTO 指令。
- decide_authorization：对 L1 授权/方案请求给出 CTO 决策。
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import cto_memory, legion_api, portfolio_manager


VALID_ACTIONS = {"collect_reports", "send_directive", "decide_authorization"}
DIRECTIVE_TYPES = {
    "execute",
    "pause",
    "resume",
    "request_plan",
    "approve_plan",
    "reject_plan",
    "clarify_requirement",
    "authorize",
    "block",
    "escalate",
}
AUTH_VERDICTS = {"approved", "rejected", "needs_plan", "needs_pm_clarification", "escalated"}
EVIDENCE_REQUIRED_DIRECTIVES = {"approve_plan", "authorize", "reject_plan", "block", "escalate"}
EVIDENCE_REQUIRED_VERDICTS = {"approved", "rejected", "escalated"}
REPORT_ACTION_EVENTS = {
    "authorization_request",
    "plan_proposal",
    "requirement_question",
    "blocked",
    "appeal",
    "risk",
}


def run(args: Dict[str, Any], **kwargs) -> str:
    started = time.monotonic()
    action = (args or {}).get("action") or "collect_reports"
    if action not in VALID_ACTIONS:
        return _err(f"invalid action: {action}", started)
    try:
        if action == "collect_reports":
            payload = collect_reports(args or {})
        elif action == "send_directive":
            payload = send_directive(args or {})
        else:
            payload = decide_authorization(args or {})
        payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return json.dumps({"success": True, **payload}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return _err(f"legion_command_center {action} failed: {type(exc).__name__}: {exc}", started)


def collect_reports(args: Dict[str, Any]) -> Dict[str, Any]:
    project_id = (args.get("project_id") or "").strip()
    commander_id = (args.get("commander_id") or "").strip()
    limit = max(1, min(int(args.get("limit") or 50), 300))
    since_ts = _parse_epoch(args.get("since_ts"))
    include_heartbeats = bool(args.get("include_heartbeats", False))
    record_memory = bool(args.get("record_memory", True))

    commanders = _target_commanders(project_id=project_id, commander_id=commander_id)
    reports: List[Dict[str, Any]] = []
    for commander in commanders:
        outbox = _outbox_path(commander)
        for message in _read_jsonl(outbox):
            report = _normalize_report(message, commander, outbox)
            if not report:
                continue
            if since_ts and (report.get("ts_epoch") or 0.0) < since_ts:
                continue
            event = ((report.get("payload") or {}).get("event") or "").strip()
            if not include_heartbeats and event == "heartbeat":
                continue
            reports.append(report)

    reports.sort(key=lambda r: r.get("ts_epoch") or 0.0, reverse=True)
    reports = reports[:limit]
    action_required = [r for r in reports if r.get("requires_cto_action")]

    recorded = 0
    if record_memory:
        for report in action_required:
            cto_memory.record_event(
                kind="legion_report",
                scope="legion",
                title=f"L1 report: {report.get('type')} {report.get('event') or ''}".strip(),
                content=_report_content(report),
                project_id=project_id,
                project_name=report.get("legion_project") or "",
                legion_id=report.get("from") or report.get("commander_id") or "",
                source=report.get("from") or "L1",
                tags=["l1-report", "requires-cto-action"],
                metadata={"message": report},
                importance=4,
            )
            recorded += 1

    return {
        "action": "collect_reports",
        "project_id": project_id or None,
        "commander_id": commander_id or None,
        "reports_count": len(reports),
        "action_required_count": len(action_required),
        "memory_records_written": recorded,
        "reports": reports,
        "action_required": action_required,
    }


def send_directive(args: Dict[str, Any]) -> Dict[str, Any]:
    commander_id = (args.get("commander_id") or "").strip()
    if not commander_id:
        raise ValueError("commander_id is required")
    directive_type = args.get("directive_type") or "execute"
    if directive_type not in DIRECTIVE_TYPES:
        raise ValueError(f"invalid directive_type: {directive_type}")
    title = (args.get("title") or directive_type).strip()
    content = (args.get("content") or "").strip()
    if not content:
        raise ValueError("content is required")

    project_id = (args.get("project_id") or "").strip()
    project_name = (args.get("project_name") or "").strip()
    legion_hash = (args.get("legion_hash") or "").strip()
    priority = args.get("priority") or "normal"
    requires_ack = bool(args.get("requires_ack", True))
    requires_plan = bool(args.get("requires_plan", directive_type == "request_plan"))
    evidence = _normalize_evidence(args.get("evidence"))
    if directive_type in EVIDENCE_REQUIRED_DIRECTIVES and not evidence:
        raise ValueError(
            f"directive_type={directive_type} requires evidence; "
            "AICTO 不允许无事实依据做方案确认/授权/阻断"
        )
    directive_id = args.get("directive_id") or f"cto-dir-{uuid.uuid4().hex[:10]}"
    payload = _format_directive_payload(
        directive_id=directive_id,
        directive_type=directive_type,
        title=title,
        content=content,
        project_id=project_id,
        project_name=project_name,
        requires_ack=requires_ack,
        requires_plan=requires_plan,
        constraints=args.get("constraints"),
        evidence=evidence,
    )
    msg_type = "escalation" if directive_type in {"block", "escalate", "pause"} else "task"
    result = legion_api.send_to_commander(
        commander_id=commander_id,
        payload=payload,
        msg_type=msg_type,
        summary=f"AICTO CTO 指令[{directive_type}]: {title}",
        cto_context={
            "authority": "AICTO_CTO_SUPREME_COMMAND",
            "directive_id": directive_id,
            "directive_type": directive_type,
            "legion_hash": legion_hash or None,
            "project_id": project_id or None,
            "project_name": project_name or None,
            "requires_ack": requires_ack,
            "requires_plan": requires_plan,
            "evidence": evidence,
            "decision_right": "AICTO has technical decision authority over development projects",
        },
        priority=priority,
        legion_hash=legion_hash or None,
    )
    memory = cto_memory.record_event(
        kind="directive",
        scope="legion",
        title=title,
        content=content,
        project_id=project_id,
        project_name=project_name,
        legion_id=commander_id,
        source="AICTO",
        tags=["cto-directive", directive_type],
        metadata={"send_result": result, "directive_id": directive_id, "evidence": evidence},
        importance=5 if directive_type in {"block", "pause", "escalate"} else 4,
    )
    return {
        "action": "send_directive",
        "directive_id": directive_id,
        "commander_id": commander_id,
        "directive_type": directive_type,
        "evidence_count": len(evidence),
        "send_result": result,
        "memory_id": memory["id"],
    }


def decide_authorization(args: Dict[str, Any]) -> Dict[str, Any]:
    commander_id = (args.get("commander_id") or "").strip()
    if not commander_id:
        raise ValueError("commander_id is required")
    verdict = args.get("verdict") or "needs_plan"
    if verdict not in AUTH_VERDICTS:
        raise ValueError(f"invalid verdict: {verdict}")
    request_id = args.get("request_id") or f"auth-{uuid.uuid4().hex[:10]}"
    rationale = (args.get("rationale") or "").strip()
    if not rationale:
        raise ValueError("rationale is required")
    evidence = _normalize_evidence(args.get("evidence"))
    if verdict in EVIDENCE_REQUIRED_VERDICTS and not evidence:
        raise ValueError(
            f"verdict={verdict} requires evidence; "
            "AICTO 不允许无事实依据批准/拒绝/升级"
        )
    project_id = (args.get("project_id") or "").strip()
    project_name = (args.get("project_name") or "").strip()
    legion_hash = (args.get("legion_hash") or "").strip()
    title = args.get("title") or f"授权决策 {verdict}"
    directive_type = "authorize" if verdict == "approved" else "reject_plan"
    if verdict in {"needs_plan", "needs_pm_clarification"}:
        directive_type = "request_plan" if verdict == "needs_plan" else "clarify_requirement"

    content = (
        f"request_id={request_id}\n"
        f"verdict={verdict}\n"
        f"rationale={rationale}\n"
        f"constraints={args.get('constraints') or ''}\n"
        "L1 必须按此 CTO 决策推进；如有技术反证，走 report/appeal 通道。"
    )
    result = send_directive(
        {
            "commander_id": commander_id,
            "directive_type": directive_type,
            "title": title,
            "content": content,
            "project_id": project_id,
            "project_name": project_name,
            "legion_hash": legion_hash,
            "priority": "high" if verdict in {"rejected", "escalated"} else "normal",
            "requires_ack": True,
            "requires_plan": verdict == "needs_plan",
            "constraints": args.get("constraints"),
            "evidence": evidence,
        }
    )
    memory = cto_memory.record_event(
        kind="authorization",
        scope="project" if project_id else "legion",
        title=title,
        content=content,
        project_id=project_id,
        project_name=project_name,
        legion_id=commander_id,
        source="AICTO",
        tags=["cto-authorization", verdict],
        metadata={"request_id": request_id, "directive": result, "evidence": evidence},
        importance=5,
    )
    return {
        "action": "decide_authorization",
        "request_id": request_id,
        "verdict": verdict,
        "evidence_count": len(evidence),
        "directive": result,
        "memory_id": memory["id"],
    }


def _target_commanders(project_id: str, commander_id: str) -> List[Dict[str, Any]]:
    warnings: List[str] = []
    legions = portfolio_manager._load_legion_projects(
        include_inactive=True,
        stale_hours=24.0,
        warnings=warnings,
    )
    if project_id:
        project = portfolio_manager._load_one_pm_project(project_id, warnings) or {
            "project_id": project_id,
            "name": project_id,
        }
        legions = [
            legion
            for legion in legions
            if portfolio_manager._project_legion_score(project, legion, {})[0]
            >= portfolio_manager.PROJECT_MATCH_THRESHOLD
        ]

    commanders: List[Dict[str, Any]] = []
    for legion in legions:
        for commander in legion.get("commanders") or []:
            item = dict(commander)
            item["legion_project"] = legion.get("legion_project")
            item["legion_hash"] = legion.get("legion_hash")
            if commander_id and item.get("commander_id") != commander_id:
                continue
            commanders.append(item)
    return commanders


def _outbox_path(commander: Dict[str, Any]) -> Path:
    return (
        legion_api.LEGION_ROOT
        / str(commander.get("legion_hash"))
        / f"team-{commander.get('commander_id')}"
        / "outbox.jsonl"
    )


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _normalize_report(
    message: Dict[str, Any],
    commander: Dict[str, Any],
    outbox: Path,
) -> Optional[Dict[str, Any]]:
    payload = message.get("payload")
    if isinstance(payload, str):
        payload_obj = {"message": payload}
    elif isinstance(payload, dict):
        payload_obj = payload
    else:
        payload_obj = {}

    event = (payload_obj.get("event") or "").strip()
    message_type = message.get("type") or "notify"
    requires = (
        message_type in {"authorization_request", "plan_proposal", "question", "appeal", "risk"}
        or event in REPORT_ACTION_EVENTS
        or str(message.get("priority") or "").lower() in {"high", "urgent"}
    )
    ts = message.get("ts") or message.get("timestamp")
    return {
        "id": message.get("id"),
        "ts": ts,
        "ts_epoch": _parse_epoch(ts),
        "from": message.get("from") or commander.get("commander_id"),
        "to": message.get("to"),
        "type": message_type,
        "priority": message.get("priority") or "normal",
        "event": event,
        "payload": payload_obj,
        "requires_cto_action": requires,
        "commander_id": commander.get("commander_id"),
        "legion_project": commander.get("legion_project"),
        "legion_hash": commander.get("legion_hash"),
        "outbox_path": str(outbox),
    }


def _report_content(report: Dict[str, Any]) -> str:
    payload = report.get("payload") or {}
    if payload.get("summary"):
        return str(payload["summary"])
    if payload.get("message"):
        return str(payload["message"])
    return json.dumps(payload, ensure_ascii=False)


def _format_directive_payload(
    *,
    directive_id: str,
    directive_type: str,
    title: str,
    content: str,
    project_id: str,
    project_name: str,
    requires_ack: bool,
    requires_plan: bool,
    constraints: Any,
    evidence: List[Dict[str, Any]],
) -> str:
    lines = [
        f"# AICTO CTO 指令 · {title}",
        "",
        f"- directive_id: `{directive_id}`",
        f"- directive_type: `{directive_type}`",
        f"- project_id: `{project_id or '未指定'}`",
        f"- project_name: `{project_name or '未指定'}`",
        "- authority: 程小远（AICTO）是开发军团最高技术指挥官；L1 必须执行或提交技术反证。",
        f"- requires_ack: {str(requires_ack).lower()}",
        f"- requires_plan: {str(requires_plan).lower()}",
        "",
        "## 指令正文",
        content,
    ]
    if constraints:
        lines.extend(["", "## 约束", str(constraints)])
    if evidence:
        lines.extend(["", "## 事实证据"])
        for item in evidence:
            source = item.get("source") or "unknown"
            ref = item.get("ref") or item.get("url") or ""
            detail = item.get("detail") or item.get("summary") or ""
            lines.append(f"- source={source}; ref={ref}; detail={detail}")
    lines.extend(
        [
            "",
            "## L1 回应要求",
            "- 收到后向 AICTO 汇报 ack / plan / blocked / authorization_request。",
            "- 需求不清：请求 PM 澄清，但技术执行路径由 AICTO 裁决。",
            "- 不同意 CTO 决策：提交 appeal，必须给出可验证技术理由。",
        ]
    )
    return "\n".join(lines)


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


def _parse_epoch(value: Any) -> Optional[float]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


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
    "collect_reports",
    "send_directive",
    "decide_authorization",
]
