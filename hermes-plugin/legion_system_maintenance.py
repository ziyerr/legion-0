"""AICTO 军团系统维护与长期数据治理。

CTO 不只管理项目交付，也要维护军团系统本身：发现重复 commander、长期
events/outbox/memory 无法处理、L1 不 ACK、blocked 任务堆积等系统性短板。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import cto_memory, legion_command_center
from . import legion_api


VALID_ACTIONS = {
    "scan",
    "follow_up_active",
    "record_summary",
    "ack_status",
    "escalate_overdue_acks",
}
ACTIVE_STATUSES = {"commanding", "running", "active", "planned"}
ATTENTION_TASK_STATUSES = {"running", "blocked", "failed", "planned"}
DONE_TASK_STATUSES = {"completed", "done", "cancelled"}


def run(args: Dict[str, Any], **kwargs) -> str:
    started = time.monotonic()
    action = (args or {}).get("action") or "scan"
    if action not in VALID_ACTIONS:
        return _err(f"invalid action: {action}", started)
    try:
        if action == "scan":
            payload = scan(args or {})
        elif action == "follow_up_active":
            payload = follow_up_active(args or {})
        elif action == "record_summary":
            payload = record_summary(args or {})
        elif action == "ack_status":
            payload = ack_status(args or {})
        else:
            payload = escalate_overdue_acks(args or {})
        payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return json.dumps({"success": True, **payload}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return _err(f"legion_system_maintenance {action} failed: {type(exc).__name__}: {exc}", started)


def scan(args: Dict[str, Any]) -> Dict[str, Any]:
    max_projects = int(args.get("max_projects") or 80)
    include_idle = bool(args.get("include_idle", False))
    root = legion_api.LEGION_ROOT
    live = _live_tmux_sessions()
    directory = _read_json(root / "directory.json") or {"legions": []}
    projects: List[Dict[str, Any]] = []
    commander_locations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    totals = Counter()

    for legion in (directory.get("legions") or [])[:max_projects]:
        legion_hash = legion.get("hash") or ""
        if not legion_hash:
            continue
        project = _scan_one_legion(root, legion, live)
        for commander in project["commanders"]:
            commander_locations[commander["id"]].append(
                {
                    "legion_hash": legion_hash,
                    "project": project["project"],
                    "status": commander.get("status"),
                    "online": commander.get("online"),
                }
            )
        if include_idle or project["online_commander_count"] or project["attention_task_count"] or project["outbox_count"]:
            projects.append(project)
        totals["projects"] += 1
        totals["online_commanders"] += project["online_commander_count"]
        totals["active_commanders"] += project["active_commander_count"]
        totals["attention_tasks"] += project["attention_task_count"]
        totals["outbox_messages"] += project["outbox_count"]
        totals["inbox_messages"] += project["inbox_count"]
        totals["memory_records"] += project["memory_records"]

    duplicate_commanders = [
        {"commander_id": cid, "locations": locations}
        for cid, locations in sorted(commander_locations.items())
        if len(locations) > 1
    ]
    findings = _findings(projects, duplicate_commanders)
    projects.sort(
        key=lambda item: (
            item["online_commander_count"],
            item["attention_task_count"],
            item["outbox_count"],
            item.get("last_active") or "",
        ),
        reverse=True,
    )
    return {
        "action": "scan",
        "generated_at": _now_iso(),
        "summary": {
            **dict(totals),
            "duplicate_commander_count": len(duplicate_commanders),
            "finding_count": len(findings),
        },
        "findings": findings,
        "duplicate_commanders": duplicate_commanders[:50],
        "projects": projects,
    }


def follow_up_active(args: Dict[str, Any]) -> Dict[str, Any]:
    dry_run = bool(args.get("dry_run", True))
    max_targets = int(args.get("max_targets") or 5)
    project_filter = (args.get("project") or "").strip().lower()
    scanned = scan({"include_idle": False, "max_projects": args.get("max_projects") or 80})
    targets = _follow_up_targets(scanned["projects"], project_filter)[:max_targets]
    sent: List[Dict[str, Any]] = []

    for target in targets:
        directive = _follow_up_directive(target)
        if dry_run:
            sent.append({"dry_run": True, **target, "directive": directive})
            continue
        result = json.loads(legion_command_center.run(directive))
        sent.append({"dry_run": False, **target, "result": result})

    memory = cto_memory.record_event(
        kind="legion_report",
        scope="system",
        title="AICTO legion maintenance follow-up",
        content=json.dumps(
            {
                "dry_run": dry_run,
                "target_count": len(targets),
                "targets": targets,
            },
            ensure_ascii=False,
        ),
        source="AICTO",
        tags=["legion-maintenance", "follow-up", "dry-run" if dry_run else "sent"],
        metadata={"scan_summary": scanned["summary"], "sent": sent},
        importance=5 if not dry_run else 3,
    )
    return {
        "action": "follow_up_active",
        "dry_run": dry_run,
        "target_count": len(targets),
        "targets": sent,
        "memory_id": memory["id"],
    }


def record_summary(args: Dict[str, Any]) -> Dict[str, Any]:
    scanned = scan(args or {})
    memory = cto_memory.record_event(
        kind="lesson",
        scope="system",
        title="Legion long-term data maintenance summary",
        content=json.dumps(
            {
                "summary": scanned["summary"],
                "findings": scanned["findings"],
                "top_projects": [
                    {
                        "project": p["project"],
                        "legion_hash": p["legion_hash"],
                        "attention_tasks": p["attention_task_count"],
                        "outbox_count": p["outbox_count"],
                        "memory_records": p["memory_records"],
                    }
                    for p in scanned["projects"][:20]
                ],
            },
            ensure_ascii=False,
        ),
        source="AICTO",
        tags=["legion-maintenance", "long-term-data", "summary"],
        metadata={"scan": scanned},
        importance=5,
    )
    return {
        "action": "record_summary",
        "memory_id": memory["id"],
        "summary": scanned["summary"],
        "finding_count": len(scanned["findings"]),
    }


def ack_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """扫描 CTO 指令是否收到 L1 ACK/AICTO-REPORT。"""
    ack_timeout_minutes = float(args.get("ack_timeout_minutes") or 15)
    lookback_hours = float(args.get("lookback_hours") or 48)
    project_filter = (args.get("project") or "").strip().lower()
    commander_filter = (args.get("commander_id") or "").strip()
    directives = _directive_memories(lookback_hours)
    statuses = []
    for directive in directives:
        if commander_filter and directive.get("legion_id") != commander_filter:
            continue
        if project_filter and project_filter not in (directive.get("project_name") or directive.get("title") or "").lower():
            continue
        statuses.append(_directive_ack_status(directive, ack_timeout_minutes))

    summary = Counter(status["ack_status"] for status in statuses)
    return {
        "action": "ack_status",
        "ack_timeout_minutes": ack_timeout_minutes,
        "lookback_hours": lookback_hours,
        "summary": dict(summary),
        "directives": statuses,
    }


def escalate_overdue_acks(args: Dict[str, Any]) -> Dict[str, Any]:
    """对超时未 ACK 的 CTO 指令发送升级提醒。

    默认 dry_run=true，避免重复骚扰；真实发送时使用 directive_type=escalate，必须携带
    原始指令和超时扫描作为 evidence。
    """
    dry_run = bool(args.get("dry_run", True))
    max_targets = int(args.get("max_targets") or 5)
    status_payload = ack_status(args or {})
    overdue = [
        item for item in status_payload["directives"]
        if item.get("ack_status") == "overdue"
    ][:max_targets]
    results = []
    for item in overdue:
        directive = _ack_escalation_directive(item)
        if dry_run:
            results.append({"dry_run": True, "target": item, "directive": directive})
            continue
        result = json.loads(legion_command_center.run(directive))
        results.append({"dry_run": False, "target": item, "result": result})

    memory = cto_memory.record_event(
        kind="risk",
        scope="system",
        title="AICTO overdue ACK escalation",
        content=json.dumps(
            {
                "dry_run": dry_run,
                "overdue_count": len(overdue),
                "summary": status_payload["summary"],
            },
            ensure_ascii=False,
        ),
        source="AICTO",
        tags=["legion-maintenance", "ack-timeout", "dry-run" if dry_run else "escalated"],
        metadata={"ack_status": status_payload, "results": results},
        importance=5 if overdue else 3,
    )
    return {
        "action": "escalate_overdue_acks",
        "dry_run": dry_run,
        "overdue_count": len(overdue),
        "results": results,
        "memory_id": memory["id"],
    }


def _scan_one_legion(root: Path, legion: Dict[str, Any], live: set[str]) -> Dict[str, Any]:
    legion_hash = legion.get("hash") or ""
    base = root / legion_hash
    commanders = _classic_commanders(base, legion_hash, live) + _mixed_commanders(base, legion_hash, live)
    tasks = _mixed_tasks(base)
    outbox_count = _count_jsonl(base.glob("team-*/outbox.jsonl"))
    inbox_count = _count_jsonl(base.glob("team-*/inbox.jsonl"))
    mixed_inbox_count = _count_jsonl((base / "mixed" / "inbox").glob("*.jsonl"))
    memory_records = _memory_count(base / "mixed" / "memory" / "memory.db")
    attention_tasks = [task for task in tasks if task.get("status") in ATTENTION_TASK_STATUSES]
    active_commanders = [c for c in commanders if c.get("status") in ACTIVE_STATUSES]
    online_commanders = [c for c in commanders if c.get("online")]
    return {
        "legion_hash": legion_hash,
        "project": legion.get("project") or "",
        "path": legion.get("path") or "",
        "last_active": legion.get("last_active"),
        "commanders": commanders,
        "active_commander_count": len(active_commanders),
        "online_commander_count": len(online_commanders),
        "tasks": tasks[:80],
        "attention_tasks": attention_tasks[:30],
        "attention_task_count": len(attention_tasks),
        "outbox_count": outbox_count,
        "inbox_count": inbox_count + mixed_inbox_count,
        "memory_records": memory_records,
    }


def _directive_memories(lookback_hours: float) -> List[Dict[str, Any]]:
    payload = cto_memory.query_memory(
        {
            "kind": "directive",
            "tag": "cto-directive",
            "limit": 200,
        }
    )
    cutoff = time.time() - max(0.1, lookback_hours) * 3600
    directives = []
    for entry in payload.get("memories") or []:
        ts_epoch = _parse_epoch(entry.get("ts")) or 0.0
        if ts_epoch and ts_epoch < cutoff:
            continue
        directives.append(entry)
    directives.sort(key=lambda item: _parse_epoch(item.get("ts")) or 0.0, reverse=True)
    return directives


def _directive_ack_status(directive: Dict[str, Any], ack_timeout_minutes: float) -> Dict[str, Any]:
    metadata = directive.get("metadata") or {}
    send_result = metadata.get("send_result") or {}
    directive_id = metadata.get("directive_id") or ""
    message_id = send_result.get("message_id") or ""
    commander_id = directive.get("legion_id") or ""
    legion_hash = send_result.get("legion_hash") or _legion_hash_from_path(send_result.get("inbox_path"))
    sent_ts = _parse_epoch(directive.get("ts")) or 0.0
    responses = _find_ack_responses(
        legion_hash=legion_hash,
        commander_id=commander_id,
        directive_id=directive_id,
        message_id=message_id,
        sent_ts=sent_ts,
    )
    elapsed_minutes = (time.time() - sent_ts) / 60 if sent_ts else None
    if responses:
        status = "acked"
    elif elapsed_minutes is not None and elapsed_minutes > ack_timeout_minutes:
        status = "overdue"
    else:
        status = "pending"
    return {
        "memory_id": directive.get("id"),
        "directive_id": directive_id,
        "message_id": message_id,
        "title": directive.get("title"),
        "project_name": directive.get("project_name"),
        "commander_id": commander_id,
        "legion_hash": legion_hash,
        "sent_ts": directive.get("ts"),
        "elapsed_minutes": round(elapsed_minutes, 2) if elapsed_minutes is not None else None,
        "ack_timeout_minutes": ack_timeout_minutes,
        "ack_status": status,
        "responses": responses[:5],
        "send_result": send_result,
    }


def _find_ack_responses(
    *,
    legion_hash: str,
    commander_id: str,
    directive_id: str,
    message_id: str,
    sent_ts: float,
) -> List[Dict[str, Any]]:
    if not legion_hash or not commander_id:
        return []
    paths = [
        legion_api.LEGION_ROOT / legion_hash / f"team-{commander_id}" / "outbox.jsonl",
        legion_api.LEGION_ROOT / legion_hash / "mixed" / "inbox" / f"{commander_id.lower()}.jsonl",
    ]
    responses: List[Dict[str, Any]] = []
    for path in paths:
        for record in _read_jsonl(path):
            if record.get("from") == "AICTO-CTO":
                continue
            record_ts = _parse_epoch(record.get("ts") or record.get("timestamp")) or 0.0
            if sent_ts and record_ts and record_ts < sent_ts:
                continue
            if _is_ack_record(record, directive_id=directive_id, message_id=message_id):
                responses.append(
                    {
                        "path": str(path),
                        "id": record.get("id"),
                        "ts": record.get("ts") or record.get("timestamp"),
                        "from": record.get("from"),
                        "to": record.get("to"),
                        "type": record.get("type"),
                        "report_type": record.get("report_type") or ((record.get("payload") or {}).get("report_type") if isinstance(record.get("payload"), dict) else None),
                        "summary": _record_summary(record),
                    }
                )
    responses.sort(key=lambda item: _parse_epoch(item.get("ts")) or 0.0, reverse=True)
    return responses


def _is_ack_record(record: Dict[str, Any], *, directive_id: str, message_id: str) -> bool:
    if directive_id and record.get("directive_id") == directive_id:
        return True
    if message_id and record.get("in_reply_to") == message_id:
        return True
    payload = record.get("payload")
    text_parts = [
        record.get("content"),
        record.get("summary"),
        json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload,
    ]
    text = "\n".join(str(part or "") for part in text_parts)
    if directive_id and directive_id in text:
        return True
    if message_id and message_id in text:
        return True
    return "AICTO-REPORT" in text or "ack" in text.lower()


def _ack_escalation_directive(item: Dict[str, Any]) -> Dict[str, Any]:
    content = (
        "ACK 超时升级：AICTO 已发送 CTO 指令但未收到结构化 ACK/AICTO-REPORT。"
        f"directive_id={item.get('directive_id')}；message_id={item.get('message_id')}；"
        f"elapsed_minutes={item.get('elapsed_minutes')}。"
        "L1 必须立即回复 AICTO-REPORT，包含当前任务状态、阻塞、L2 分工、验证证据和长期数据处理建议；"
        "如果不应处理该指令，必须提交 technical appeal 并说明事实原因。"
    )
    return {
        "action": "send_directive",
        "commander_id": item["commander_id"],
        "legion_hash": item["legion_hash"],
        "directive_type": "escalate",
        "title": f"ACK 超时升级 · {item.get('project_name') or item.get('title')}",
        "content": content,
        "project_name": item.get("project_name") or "",
        "priority": "high",
        "requires_ack": True,
        "requires_plan": True,
        "constraints": "回复必须引用原 directive_id/message_id；不得只发 heartbeat。",
        "evidence": [
            {
                "source": "cto_memory",
                "ref": item.get("memory_id") or "",
                "detail": f"original directive_id={item.get('directive_id')} sent_ts={item.get('sent_ts')}",
            },
            {
                "source": "legion_system_maintenance.ack_status",
                "ref": item.get("message_id") or "",
                "detail": f"ack_status=overdue elapsed_minutes={item.get('elapsed_minutes')}",
            },
        ],
    }


def _classic_commanders(base: Path, legion_hash: str, live: set[str]) -> List[Dict[str, Any]]:
    registry = _read_json(base / "registry.json") or {}
    commanders: List[Dict[str, Any]] = []
    for team in registry.get("teams") or []:
        if not isinstance(team, dict):
            continue
        commander_id = team.get("id") or ""
        if not commander_id:
            continue
        session = f"legion-{legion_hash}-{commander_id}"
        commanders.append(
            {
                "id": commander_id,
                "provider": "classic",
                "role": team.get("role"),
                "status": team.get("status"),
                "task": team.get("task"),
                "session": session,
                "online": session in live,
            }
        )
    return commanders


def _mixed_commanders(base: Path, legion_hash: str, live: set[str]) -> List[Dict[str, Any]]:
    registry = _read_json(base / "mixed" / "mixed-registry.json") or {}
    items = registry.get("commanders") or []
    if isinstance(items, dict):
        items = items.values()
    commanders: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        session = item.get("session") or f"legion-mixed-{legion_hash}-{item.get('id')}"
        commanders.append(
            {
                "id": item.get("id"),
                "provider": item.get("provider") or "mixed",
                "role": item.get("role"),
                "status": item.get("status"),
                "branch": item.get("branch"),
                "parent": item.get("parent"),
                "session": session,
                "online": session in live,
            }
        )
    return commanders


def _mixed_tasks(base: Path) -> List[Dict[str, Any]]:
    registry = _read_json(base / "mixed" / "mixed-registry.json") or {}
    tasks = registry.get("tasks") or []
    if isinstance(tasks, dict):
        iterable = tasks.values()
    else:
        iterable = tasks
    normalized: List[Dict[str, Any]] = []
    for task in iterable:
        if not isinstance(task, dict):
            continue
        normalized.append(
            {
                "id": task.get("id"),
                "status": task.get("status"),
                "role": task.get("role"),
                "provider": task.get("provider"),
                "branch": task.get("branch"),
                "commander": task.get("commander"),
                "origin_commander": task.get("origin_commander"),
                "updated": task.get("updated"),
                "summary": task.get("result_summary") or _short(task.get("task")),
                "result_file": task.get("result_file"),
            }
        )
    normalized.sort(key=lambda t: t.get("updated") or "", reverse=True)
    return normalized


def _follow_up_targets(projects: List[Dict[str, Any]], project_filter: str) -> List[Dict[str, Any]]:
    targets: Dict[tuple[str, str], Dict[str, Any]] = {}
    for project in projects:
        if project_filter and project_filter not in (project.get("project") or "").lower():
            continue
        attention = project.get("attention_tasks") or []
        l1_candidates = [
            commander for commander in project.get("commanders") or []
            if commander.get("role") == "commander" and commander.get("online")
        ]
        for task in attention:
            commander_id = task.get("origin_commander") or ""
            if not commander_id and l1_candidates:
                commander_id = l1_candidates[0].get("id") or ""
            if not commander_id:
                continue
            key = (project["legion_hash"], commander_id)
            targets.setdefault(
                key,
                {
                    "project": project.get("project"),
                    "legion_hash": project["legion_hash"],
                    "commander_id": commander_id,
                    "tasks": [],
                    "evidence": [],
                },
            )
            targets[key]["tasks"].append(task)
            targets[key]["evidence"].append(
                {
                    "source": "legion-maintenance-scan",
                    "ref": f"{project['legion_hash']}:{task.get('id')}",
                    "detail": f"task status={task.get('status')} commander={task.get('commander')}",
                }
            )
        if not attention and l1_candidates:
            commander_id = l1_candidates[0].get("id") or ""
            targets.setdefault(
                (project["legion_hash"], commander_id),
                {
                    "project": project.get("project"),
                    "legion_hash": project["legion_hash"],
                    "commander_id": commander_id,
                    "tasks": [],
                    "evidence": [
                        {
                            "source": "legion-maintenance-scan",
                            "ref": project["legion_hash"],
                            "detail": "commander online but no structured active mixed task; request idle/active clarification",
                        }
                    ],
                },
            )
    return list(targets.values())


def _follow_up_directive(target: Dict[str, Any]) -> Dict[str, Any]:
    task_ids = [task.get("id") for task in target.get("tasks") or [] if task.get("id")]
    content = (
        "AICTO 正在维护军团系统并跟进开发任务。请回复 AICTO-REPORT："
        f"project={target.get('project')}；tasks={','.join(task_ids) or 'none-detected'}。"
        "必须说明当前状态、下一步、阻塞、验证证据、L2 分工、是否需要 CTO 授权，"
        "以及 events/outbox/memory 中哪些长期数据需要总结/抽取/归档。"
    )
    return {
        "action": "send_directive",
        "commander_id": target["commander_id"],
        "legion_hash": target["legion_hash"],
        "directive_type": "request_plan",
        "title": f"AICTO 军团维护跟进 · {target.get('project')}",
        "content": content,
        "project_name": target.get("project"),
        "priority": "high",
        "requires_ack": True,
        "requires_plan": True,
        "constraints": "回复必须引用任务 id、文件路径、验证命令、outbox/mixed event/memory；不得空泛确认。",
        "evidence": target.get("evidence") or [],
    }


def _findings(projects: List[Dict[str, Any]], duplicates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for duplicate in duplicates[:30]:
        findings.append(
            {
                "severity": "high",
                "type": "duplicate_commander_id",
                "summary": f"commander_id={duplicate['commander_id']} appears in multiple legions; send requires legion_hash disambiguation",
                "evidence": duplicate["locations"],
            }
        )
    for project in projects:
        if project["attention_task_count"]:
            findings.append(
                {
                    "severity": "medium",
                    "type": "attention_tasks",
                    "summary": f"{project['project']} has {project['attention_task_count']} running/blocked/failed/planned mixed tasks",
                    "evidence": project["attention_tasks"][:5],
                }
            )
        if project["outbox_count"] > 200 and project["memory_records"] < 10:
            findings.append(
                {
                    "severity": "medium",
                    "type": "long_data_not_summarized",
                    "summary": f"{project['project']} has {project['outbox_count']} outbox messages but only {project['memory_records']} mixed memories",
                    "evidence": {"legion_hash": project["legion_hash"]},
                }
            )
    return findings


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as file:
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
    except Exception:
        return []
    return records


def _live_tmux_sessions() -> set[str]:
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return set()
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line}


def _count_jsonl(paths: Iterable[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += sum(1 for line in path.open("r", encoding="utf-8", errors="ignore") if line.strip())
        except Exception:
            continue
    return total


def _memory_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        conn = sqlite3.connect(path)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return 0


def _short(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


def _record_summary(record: Dict[str, Any]) -> str:
    payload = record.get("payload")
    if isinstance(payload, dict):
        for key in ("summary", "message", "content"):
            if payload.get(key):
                return _short(payload.get(key), 240)
        return _short(json.dumps(payload, ensure_ascii=False), 240)
    for key in ("summary", "content", "payload"):
        if record.get(key):
            return _short(record.get(key), 240)
    return _short(record, 240)


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
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def _legion_hash_from_path(path: Any) -> str:
    if not path:
        return ""
    parts = Path(str(path)).parts
    try:
        idx = parts.index("legion")
    except ValueError:
        return ""
    if len(parts) > idx + 1:
        return parts[idx + 1]
    return ""


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


__all__ = ["run", "scan", "follow_up_active", "record_summary"]
