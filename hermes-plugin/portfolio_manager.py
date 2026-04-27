"""AICTO 多项目军团组合管理。

本模块解决 Phase 1 调度的核心缺口：AICTO 不能只知道"有在线军团"，
还必须知道"哪个项目归哪个军团管、哪个项目缺军团、哪些军团积压/离线"。

边界：
- 只读 ProdMind Project/PRD/Feature/UserStory/CTO 表。
- 只读 ~/.claude/legion/directory.json 与各 registry/inbox。
- 不启动/停止军团，不改 Hermes profile，不写 PM 表。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import legion_api, pm_db_api


DEFAULT_STALE_HOURS = 24.0
PROJECT_MATCH_THRESHOLD = 55
MAX_PROJECTS_DEFAULT = 50

INACTIVE_PROJECT_STATUSES = {"archived", "completed", "done", "cancelled"}
ACTIVE_COMMANDER_STATUSES = {"commanding", "running", "active"}

ALIASES_PATH = Path.home() / ".hermes/profiles/aicto/plugins/aicto/state/project_legion_aliases.json"


def run(args: Dict[str, Any], **kwargs) -> str:
    """Hermes tool entry：返回 AICTO 管辖的 PM 项目 × Legion 组合状态。"""
    started = time.monotonic()
    try:
        payload = build_portfolio(args or {})
        payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
        return json.dumps({"success": True, **payload}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "error": f"legion_portfolio_status failed: {type(exc).__name__}: {exc}",
                "elapsed_seconds": round(time.monotonic() - started, 2),
            },
            ensure_ascii=False,
        )


def build_portfolio(args: Dict[str, Any]) -> Dict[str, Any]:
    """构建多项目军团组合态。

    Args:
        include_inactive_projects: 是否包含 archived/completed/done 项目。
        include_inactive_legions: 是否包含无 active commander 的历史 legion。
        project_id / project_name: 可选过滤单项目。
        stale_hours: inbox 未读消息超过该小时数视为 stale。
    """
    include_inactive_projects = bool(args.get("include_inactive_projects", False))
    include_inactive_legions = bool(args.get("include_inactive_legions", False))
    project_id_filter = (args.get("project_id") or "").strip()
    project_name_filter = (args.get("project_name") or "").strip()
    stale_hours = _float_arg(args.get("stale_hours"), DEFAULT_STALE_HOURS)
    max_projects = int(args.get("max_projects") or MAX_PROJECTS_DEFAULT)

    warnings: List[str] = []
    aliases = _load_aliases(warnings)
    projects = _load_pm_projects(
        include_inactive=include_inactive_projects,
        warnings=warnings,
    )
    legions = _load_legion_projects(
        include_inactive=include_inactive_legions,
        stale_hours=stale_hours,
        warnings=warnings,
    )

    if project_id_filter:
        projects = [p for p in projects if p.get("project_id") == project_id_filter]
    if project_name_filter:
        needle = _normalize(project_name_filter)
        projects = [p for p in projects if needle in _normalize(p.get("name") or "")]
    projects = projects[:max_projects]

    matched_legion_hashes: set[str] = set()
    portfolio_projects: List[Dict[str, Any]] = []
    for project in projects:
        matches = _match_legions_for_project(project, legions, aliases)
        matched_legion_hashes.update(m["legion_hash"] for m in matches)
        health, alerts, actions = _assess_project_health(project, matches)
        portfolio_projects.append(
            {
                **project,
                "health": health,
                "alerts": alerts,
                "recommended_actions": actions,
                "legions": matches,
            }
        )

    unmatched_legions = [
        _compact_legion(l)
        for l in legions
        if l.get("legion_hash") not in matched_legion_hashes
    ]

    summary = _build_summary(portfolio_projects, legions, unmatched_legions)
    return {
        "generated_at": _now_iso(),
        "stale_hours": stale_hours,
        "summary": summary,
        "projects": portfolio_projects,
        "unmatched_legions": unmatched_legions,
        "warnings": warnings or None,
    }


def rank_commanders_for_project(
    *,
    project_id: str,
    project_name: str = "",
    commanders: List[legion_api.Commander],
    allow_cross_project_borrow: bool = False,
) -> Tuple[List[legion_api.Commander], Dict[str, Dict[str, Any]], List[str]]:
    """按项目归属过滤/排序 commander。

    默认策略是**不跨项目借兵**：如果没有匹配项目的 commander，返回空列表。
    调用方只有显式传 allow_cross_project_borrow=True 才会退回全量 commander。
    """
    warnings: List[str] = []
    aliases = _load_aliases(warnings)
    project = _load_one_pm_project(project_id, warnings) or {
        "project_id": project_id,
        "name": project_name or project_id,
    }
    if project_name and not project.get("name"):
        project["name"] = project_name

    scored: List[Tuple[int, str, legion_api.Commander]] = []
    affinity: Dict[str, Dict[str, Any]] = {}
    for commander in commanders:
        legion_view = {
            "legion_hash": commander.legion_hash,
            "legion_project": commander.legion_project,
            "path": "",
            "commander_ids": [commander.commander_id],
        }
        score, reason = _project_legion_score(project, legion_view, aliases)
        affinity[commander.commander_id] = {
            "project_match_score": score,
            "project_match_reason": reason,
            "legion_project": commander.legion_project,
            "legion_hash": commander.legion_hash,
            "cross_project_borrowed": score < PROJECT_MATCH_THRESHOLD,
        }
        if score >= PROJECT_MATCH_THRESHOLD:
            scored.append((-score, commander.commander_id, commander))

    if scored:
        scored.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in scored], affinity, warnings

    msg = (
        f"no project-bound legion for project_id={project_id} "
        f"name={project.get('name')!r}; "
        "默认禁止跨项目借兵，避免把任务派给其他项目军团"
    )
    if allow_cross_project_borrow:
        warnings.append(msg + "；已因 allow_cross_project_borrow=true 退回全量 commander")
        return commanders, affinity, warnings

    warnings.append(msg)
    return [], affinity, warnings


def affinity_for_commander(
    commander_id: str,
    affinity: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return affinity.get(
        commander_id,
        {
            "project_match_score": 0,
            "project_match_reason": "not_scored",
            "cross_project_borrowed": True,
        },
    )


def _load_pm_projects(
    *,
    include_inactive: bool,
    warnings: List[str],
) -> List[Dict[str, Any]]:
    try:
        conn = pm_db_api._readonly_connect()
    except sqlite3.Error as exc:
        warnings.append(f"pm_db connect failed: {exc}")
        return []

    try:
        rows = conn.execute(
            'SELECT "id", "name", "status", "stage", "mode", "updatedAt", "createdAt" '
            'FROM "Project" ORDER BY "updatedAt" DESC'
        ).fetchall()
        projects: List[Dict[str, Any]] = []
        for row in rows:
            status = (row["status"] or "").lower()
            if not include_inactive and status in INACTIVE_PROJECT_STATUSES:
                continue
            project_id = row["id"]
            projects.append(
                {
                    "project_id": project_id,
                    "name": row["name"],
                    "status": row["status"],
                    "stage": row["stage"],
                    "mode": row["mode"],
                    "updated_at": row["updatedAt"],
                    "created_at": row["createdAt"],
                    "pm_context": _pm_context_counts(conn, project_id),
                    "cto_state": _cto_state_counts(conn, project_id),
                }
            )
        return projects
    except sqlite3.Error as exc:
        warnings.append(f"load projects failed: {exc}")
        return []
    finally:
        conn.close()


def _load_one_pm_project(project_id: str, warnings: List[str]) -> Optional[Dict[str, Any]]:
    if not project_id:
        return None
    try:
        conn = pm_db_api._readonly_connect()
        try:
            row = conn.execute(
                'SELECT "id", "name", "status", "stage", "mode", "updatedAt", "createdAt" '
                'FROM "Project" WHERE "id" = ?',
                (project_id,),
            ).fetchone()
            if row is None:
                warnings.append(f"project not found in PM db: {project_id}")
                return None
            return {
                "project_id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "stage": row["stage"],
                "mode": row["mode"],
                "updated_at": row["updatedAt"],
                "created_at": row["createdAt"],
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        warnings.append(f"load project failed: {exc}")
        return None


def _pm_context_counts(conn: sqlite3.Connection, project_id: str) -> Dict[str, int]:
    return {
        "prd_count": _count_where(conn, "PRD", '"projectId" = ?', (project_id,)),
        "feature_count": _count_where(conn, "Feature", '"projectId" = ?', (project_id,)),
        "user_story_count": _count_where(conn, "UserStory", '"projectId" = ?', (project_id,)),
        "open_question_count": _count_open_questions(conn, project_id),
    }


def _cto_state_counts(conn: sqlite3.Connection, project_id: str) -> Dict[str, int]:
    return {
        "adr_count": _count_where(conn, "ADR", '"project_id" = ?', (project_id,)),
        "open_risk_count": _count_where(
            conn, "TechRisk", '"project_id" = ? AND "status" = ?', (project_id, "open")
        ),
        "open_debt_count": _count_where(
            conn, "TechDebt", '"project_id" = ? AND "status" = ?', (project_id, "open")
        ),
        "blocking_review_count": _count_where(
            conn,
            "CodeReview",
            '"project_id" = ? AND "blocker_count" > 0 AND "appeal_status" IN (?, ?)',
            (project_id, "none", "pending"),
        ),
    }


def _count_where(
    conn: sqlite3.Connection,
    table: str,
    where_sql: str,
    params: Tuple[Any, ...],
) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        row = conn.execute(
            f'SELECT COUNT(*) AS c FROM "{table}" WHERE {where_sql}',
            params,
        ).fetchone()
        return int(row["c"] if row else 0)
    except sqlite3.Error:
        return 0


def _count_open_questions(conn: sqlite3.Connection, project_id: str) -> int:
    if not _table_exists(conn, "PRDOpenQuestion") or not _table_exists(conn, "PRD"):
        return 0
    try:
        row = conn.execute(
            'SELECT COUNT(*) AS c FROM "PRDOpenQuestion" q '
            'JOIN "PRD" p ON p."id" = q."prdId" '
            'WHERE p."projectId" = ? AND (q."status" IS NULL OR q."status" = ?)',
            (project_id, "open"),
        ).fetchone()
        return int(row["c"] if row else 0)
    except sqlite3.Error:
        return 0


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _load_legion_projects(
    *,
    include_inactive: bool,
    stale_hours: float,
    warnings: List[str],
) -> List[Dict[str, Any]]:
    try:
        directory = json.loads(legion_api.LEGION_DIRECTORY.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"load legion directory failed: {exc}")
        return []

    live = legion_api._live_tmux_sessions()
    if live is None:
        warnings.append("tmux list-sessions unavailable; tmux_alive uses registry fallback")
        live = set()

    legions: List[Dict[str, Any]] = []
    for item in directory.get("legions", []):
        legion_hash = item.get("hash") or ""
        if not legion_hash:
            continue
        registry = _read_registry(legion_hash, warnings)
        commanders = _collect_commanders(legion_hash, item, registry, live, stale_hours)
        active_commanders = [
            c for c in commanders if c.get("status") in ACTIVE_COMMANDER_STATUSES
        ]
        online_commanders = [c for c in active_commanders if c.get("tmux_alive")]
        if not include_inactive and not active_commanders:
            continue

        pending_ai_cto_tasks = sum(c["inbox"]["pending_ai_cto_tasks"] for c in commanders)
        stale_pending_tasks = sum(c["inbox"]["stale_pending_tasks"] for c in commanders)
        legions.append(
            {
                "legion_hash": legion_hash,
                "legion_project": item.get("project") or "",
                "path": item.get("path") or "",
                "last_active": item.get("last_active"),
                "commander_count": len(commanders),
                "active_commander_count": len(active_commanders),
                "online_commander_count": len(online_commanders),
                "pending_ai_cto_tasks": pending_ai_cto_tasks,
                "stale_pending_tasks": stale_pending_tasks,
                "commanders": commanders,
            }
        )
    legions.sort(
        key=lambda l: (
            l.get("online_commander_count", 0),
            l.get("active_commander_count", 0),
            l.get("last_active") or "",
        ),
        reverse=True,
    )
    return legions


def _read_registry(legion_hash: str, warnings: List[str]) -> Dict[str, Any]:
    path = legion_api.LEGION_ROOT / legion_hash / "registry.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"teams": []}
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"read registry failed: {legion_hash}: {exc}")
        return {"teams": []}


def _collect_commanders(
    legion_hash: str,
    directory_item: Dict[str, Any],
    registry: Dict[str, Any],
    live_sessions: set[str],
    stale_hours: float,
) -> List[Dict[str, Any]]:
    commanders: List[Dict[str, Any]] = []
    for team in registry.get("teams", []):
        if team.get("role") != "commander":
            continue
        commander_id = team.get("id") or ""
        if not commander_id:
            continue
        session_name = f"{legion_api.TMUX_SESSION_PREFIX}{legion_hash}-{commander_id}"
        inbox_path = legion_api._inbox_path_for(legion_hash, commander_id)
        commanders.append(
            {
                "commander_id": commander_id,
                "status": team.get("status"),
                "task": team.get("task"),
                "started_at": team.get("started"),
                "tmux_session": session_name,
                "tmux_alive": session_name in live_sessions,
                "inbox_path": str(inbox_path),
                "inbox": _read_inbox_stats(inbox_path, stale_hours),
                "legion_project": directory_item.get("project") or "",
                "legion_hash": legion_hash,
            }
        )
    return commanders


def _read_inbox_stats(inbox_path: Path, stale_hours: float) -> Dict[str, Any]:
    stats = {
        "message_count": 0,
        "pending_ai_cto_tasks": 0,
        "stale_pending_tasks": 0,
        "pending_project_ids": [],
        "last_message_at": None,
    }
    try:
        messages = json.loads(inbox_path.read_text(encoding="utf-8"))
    except Exception:
        return stats
    if not isinstance(messages, list):
        return stats

    project_ids: set[str] = set()
    stale_before = time.time() - stale_hours * 3600
    latest_ts = 0.0
    for message in messages:
        if not isinstance(message, dict):
            continue
        stats["message_count"] += 1
        ts = _parse_ts(message.get("timestamp"))
        latest_ts = max(latest_ts, ts or 0.0)
        if message.get("from") != legion_api.SENDER_ID:
            continue
        if message.get("read") is True:
            continue
        stats["pending_ai_cto_tasks"] += 1
        cto_context = message.get("cto_context") or {}
        project_id = cto_context.get("project_id")
        if isinstance(project_id, str) and project_id:
            project_ids.add(project_id)
        if ts and ts < stale_before:
            stats["stale_pending_tasks"] += 1

    stats["pending_project_ids"] = sorted(project_ids)
    if latest_ts:
        stats["last_message_at"] = _iso_from_epoch(latest_ts)
    return stats


def _match_legions_for_project(
    project: Dict[str, Any],
    legions: List[Dict[str, Any]],
    aliases: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for legion in legions:
        score, reason = _project_legion_score(project, legion, aliases)
        if score < PROJECT_MATCH_THRESHOLD:
            continue
        compact = _compact_legion(legion)
        compact["project_match_score"] = score
        compact["project_match_reason"] = reason
        matches.append(compact)
    matches.sort(
        key=lambda item: (
            -int(item.get("project_match_score") or 0),
            -int(item.get("online_commander_count") or 0),
            item.get("legion_project") or "",
        )
    )
    return matches


def _project_legion_score(
    project: Dict[str, Any],
    legion: Dict[str, Any],
    aliases: Dict[str, List[str]],
) -> Tuple[int, str]:
    project_id = project.get("project_id") or project.get("id") or ""
    project_name = project.get("name") or project_id
    project_norm = _normalize(project_name)

    legion_names = [
        legion.get("legion_project") or "",
        Path(legion.get("path") or "").name,
        legion.get("legion_hash") or "",
    ]
    for commander_id in legion.get("commander_ids") or []:
        legion_names.append(str(commander_id))
    for commander in legion.get("commanders") or []:
        legion_names.append(str(commander.get("commander_id") or ""))

    alias_values = aliases.get(project_id, []) + aliases.get(project_name, [])
    alias_norms = [_normalize(v) for v in alias_values if v]
    legion_norms = [_normalize(v) for v in legion_names if v]

    for alias in alias_norms:
        if alias and alias in legion_norms:
            return 100, "manual_alias_exact"
        for lname in legion_norms:
            if alias and (alias in lname or lname in alias):
                return 95, "manual_alias_contains"

    for lname in legion_norms:
        if not lname or not project_norm:
            continue
        if lname == project_norm:
            return 100, "name_exact"
        if len(lname) >= 3 and (lname in project_norm or project_norm in lname):
            return 85, "name_contains"

    project_tokens = _tokens(project_name)
    best_overlap = 0.0
    for name in legion_names:
        legion_tokens = _tokens(name)
        if not project_tokens or not legion_tokens:
            continue
        overlap = len(project_tokens & legion_tokens) / max(len(project_tokens), 1)
        best_overlap = max(best_overlap, overlap)
    if best_overlap:
        score = int(best_overlap * 70)
        return score, "token_overlap"

    return 0, "no_match"


def _compact_legion(legion: Dict[str, Any]) -> Dict[str, Any]:
    commanders = legion.get("commanders") or []
    return {
        "legion_hash": legion.get("legion_hash"),
        "legion_project": legion.get("legion_project"),
        "path": legion.get("path"),
        "last_active": legion.get("last_active"),
        "commander_count": legion.get("commander_count", len(commanders)),
        "active_commander_count": legion.get("active_commander_count", 0),
        "online_commander_count": legion.get("online_commander_count", 0),
        "pending_ai_cto_tasks": legion.get("pending_ai_cto_tasks", 0),
        "stale_pending_tasks": legion.get("stale_pending_tasks", 0),
        "commanders": [
            {
                "commander_id": c.get("commander_id"),
                "status": c.get("status"),
                "tmux_alive": c.get("tmux_alive"),
                "tmux_session": c.get("tmux_session"),
                "pending_ai_cto_tasks": (c.get("inbox") or {}).get("pending_ai_cto_tasks", 0),
                "stale_pending_tasks": (c.get("inbox") or {}).get("stale_pending_tasks", 0),
            }
            for c in commanders
        ],
    }


def _assess_project_health(
    project: Dict[str, Any],
    legions: List[Dict[str, Any]],
) -> Tuple[str, List[str], List[str]]:
    alerts: List[str] = []
    actions: List[str] = []
    health = "green"

    pm_ctx = project.get("pm_context") or {}
    cto_state = project.get("cto_state") or {}
    project_status = (project.get("status") or "").lower()
    needs_legion = project_status in {"development", "active", "in_progress"} or (
        pm_ctx.get("prd_count", 0) > 0 and project_status not in INACTIVE_PROJECT_STATUSES
    )

    if needs_legion and not legions:
        health = "red"
        alerts.append("active_project_without_bound_legion")
        actions.append("先用 kickoff_project 或 legion.sh 为该项目建立专属 L1，再派开发任务")

    online = sum(l.get("online_commander_count", 0) for l in legions)
    active = sum(l.get("active_commander_count", 0) for l in legions)
    stale = sum(l.get("stale_pending_tasks", 0) for l in legions)
    pending = sum(l.get("pending_ai_cto_tasks", 0) for l in legions)

    if legions and active and not online:
        health = "red"
        alerts.append("project_legion_offline")
        actions.append("恢复该项目军团 tmux 会话后再继续派单")
    elif legions and not active:
        health = _max_health(health, "yellow")
        alerts.append("project_has_only_inactive_legions")
        actions.append("复用前需重新激活军团或新建军团")

    if stale:
        health = "red"
        alerts.append(f"stale_ai_cto_tasks={stale}")
        actions.append("检查对应 commander inbox，要求 L1 ack/执行/申诉")
    elif pending:
        health = _max_health(health, "yellow")
        alerts.append(f"pending_ai_cto_tasks={pending}")

    if cto_state.get("blocking_review_count", 0):
        health = "red"
        alerts.append(f"blocking_reviews={cto_state['blocking_review_count']}")
        actions.append("优先处理 BLOCKING code review，不允许继续合并")

    if pm_ctx.get("open_question_count", 0):
        health = _max_health(health, "yellow")
        alerts.append(f"pm_open_questions={pm_ctx['open_question_count']}")
        actions.append("让 PM 补齐开放问题后再拆重型开发任务")

    if needs_legion and cto_state.get("adr_count", 0) == 0:
        health = _max_health(health, "yellow")
        alerts.append("no_cto_adr")
        actions.append("先跑 design_tech_plan 落 ADR，再派 L2 执行")

    return health, alerts, actions


def _build_summary(
    projects: List[Dict[str, Any]],
    legions: List[Dict[str, Any]],
    unmatched_legions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "project_count": len(projects),
        "legion_count": len(legions),
        "green_projects": sum(1 for p in projects if p.get("health") == "green"),
        "yellow_projects": sum(1 for p in projects if p.get("health") == "yellow"),
        "red_projects": sum(1 for p in projects if p.get("health") == "red"),
        "projects_without_legion": sum(1 for p in projects if not p.get("legions")),
        "online_commanders": sum(l.get("online_commander_count", 0) for l in legions),
        "active_commanders": sum(l.get("active_commander_count", 0) for l in legions),
        "pending_ai_cto_tasks": sum(l.get("pending_ai_cto_tasks", 0) for l in legions),
        "stale_pending_tasks": sum(l.get("stale_pending_tasks", 0) for l in legions),
        "unmatched_legions": len(unmatched_legions),
    }


def _load_aliases(warnings: List[str]) -> Dict[str, List[str]]:
    path = Path(os.environ.get("AICTO_PROJECT_LEGION_ALIASES", str(ALIASES_PATH)))
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"alias file unreadable: {path}: {exc}")
        return {}
    items = raw.get("projects", raw) if isinstance(raw, dict) else {}
    aliases: Dict[str, List[str]] = {}
    if not isinstance(items, dict):
        return aliases
    for key, value in items.items():
        if isinstance(value, str):
            aliases[str(key)] = [value]
        elif isinstance(value, list):
            aliases[str(key)] = [str(v) for v in value if v]
    return aliases


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value or "").lower()


def _tokens(value: str) -> set[str]:
    ascii_tokens = re.findall(r"[0-9A-Za-z]+", value or "")
    cjk_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", value or "")
    return {t.lower() for t in ascii_tokens + cjk_tokens if t}


def _float_arg(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _max_health(current: str, candidate: str) -> str:
    order = {"green": 0, "yellow": 1, "red": 2}
    return candidate if order[candidate] > order[current] else current


def _parse_ts(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "run",
    "build_portfolio",
    "rank_commanders_for_project",
    "affinity_for_commander",
    "PROJECT_MATCH_THRESHOLD",
    "DEFAULT_STALE_HOURS",
]
