"""AICTO 独立长期记忆。

这是程小远自己的 CTO 记忆，不绑定 Hermes state.db，也不写 PM 表。
存储格式是可迁移 JSONL：复制这个文件即可跨机器/跨 runtime 迁移，后续升级通过
schema_version 做兼容。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = "aicto-cto-memory/v1"
DEFAULT_MEMORY_PATH = (
    Path.home() / ".hermes/profiles/aicto/plugins/aicto/state/cto_memory.jsonl"
)
VALID_SCOPES = {"system", "project", "legion", "interaction"}
VALID_KINDS = {
    "organization_contract",
    "requirement_insight",
    "tech_decision",
    "authorization",
    "directive",
    "legion_report",
    "risk",
    "lesson",
    "handoff",
}


def record(args: Dict[str, Any], **kwargs) -> str:
    try:
        entry = append_memory(args or {})
        return json.dumps({"success": True, "memory": entry}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"cto_memory_record failed: {exc}"}, ensure_ascii=False)


def query(args: Dict[str, Any], **kwargs) -> str:
    try:
        payload = query_memory(args or {})
        return json.dumps({"success": True, **payload}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"cto_memory_query failed: {exc}"}, ensure_ascii=False)


def append_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    scope = args.get("scope") or _infer_scope(args)
    kind = args.get("kind") or "lesson"
    if scope not in VALID_SCOPES:
        raise ValueError(f"invalid scope: {scope}")
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind}")

    content = (args.get("content") or "").strip()
    title = (args.get("title") or "").strip()
    if not content and not title:
        raise ValueError("title/content 至少提供一个")

    entry = {
        "id": args.get("id") or f"mem-{uuid.uuid4().hex[:12]}",
        "schema_version": SCHEMA_VERSION,
        "ts": args.get("ts") or _now_iso(),
        "scope": scope,
        "kind": kind,
        "project_id": args.get("project_id") or None,
        "project_name": args.get("project_name") or None,
        "legion_id": args.get("legion_id") or args.get("commander_id") or None,
        "source": args.get("source") or "AICTO",
        "title": title,
        "content": content,
        "tags": _string_list(args.get("tags")),
        "confidence": _confidence(args.get("confidence")),
        "importance": _importance(args.get("importance")),
        "links": _string_list(args.get("links")),
        "metadata": args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
    }
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def record_event(
    *,
    kind: str,
    title: str,
    content: str,
    scope: str = "interaction",
    project_id: str = "",
    project_name: str = "",
    legion_id: str = "",
    source: str = "AICTO",
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    importance: int = 3,
) -> Dict[str, Any]:
    return append_memory(
        {
            "kind": kind,
            "scope": scope,
            "title": title,
            "content": content,
            "project_id": project_id,
            "project_name": project_name,
            "legion_id": legion_id,
            "source": source,
            "tags": tags or [],
            "metadata": metadata or {},
            "importance": importance,
        }
    )


def query_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 20)
    limit = max(1, min(limit, 200))
    scope = args.get("scope")
    kind = args.get("kind")
    project_id = args.get("project_id")
    legion_id = args.get("legion_id") or args.get("commander_id")
    tag = args.get("tag")
    text = (args.get("text") or "").strip().lower()
    since_ts = _parse_epoch(args.get("since_ts"))

    entries = []
    for entry in _iter_entries():
        if scope and entry.get("scope") != scope:
            continue
        if kind and entry.get("kind") != kind:
            continue
        if project_id and entry.get("project_id") != project_id:
            continue
        if legion_id and entry.get("legion_id") != legion_id:
            continue
        if tag and tag not in (entry.get("tags") or []):
            continue
        if since_ts:
            entry_ts = _parse_epoch(entry.get("ts")) or 0.0
            if entry_ts < since_ts:
                continue
        if text:
            blob = " ".join(
                str(entry.get(k) or "") for k in ("title", "content", "project_name", "legion_id")
            ).lower()
            if text not in blob:
                continue
        entries.append(entry)

    entries.sort(
        key=lambda e: (_parse_epoch(e.get("ts")) or 0.0, int(e.get("importance") or 0)),
        reverse=True,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "memory_path": str(_memory_path()),
        "count": len(entries[:limit]),
        "total_matched": len(entries),
        "memories": entries[:limit],
    }


def _iter_entries() -> Iterable[Dict[str, Any]]:
    path = _memory_path()
    if not path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _memory_path() -> Path:
    return Path(os.environ.get("AICTO_MEMORY_PATH", str(DEFAULT_MEMORY_PATH))).expanduser()


def _infer_scope(args: Dict[str, Any]) -> str:
    if args.get("legion_id") or args.get("commander_id"):
        return "legion"
    if args.get("project_id") or args.get("project_name"):
        return "project"
    return "system"


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []


def _confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, parsed))


def _importance(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, parsed))


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_MEMORY_PATH",
    "record",
    "query",
    "append_memory",
    "query_memory",
    "record_event",
]
