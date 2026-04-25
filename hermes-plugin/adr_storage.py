"""AICTO 自有表 CRUD — 5 张 CTO 表的 SQL 读写封装.

负责管理 CTO 在 ProdMind dev.db 内**新增**的 5 张表：

    ADR              — 架构决策记录
    TechRisk         — 技术风险登记
    TechDebt         — 技术债务清单
    CodeReview       — 代码评审记录
    EngineerProfile  — 工程师 / 军团能力画像

边界纪律（ADR-002 LOCKED）：
    - 共享 ProdMind dev.db (`/Users/feijun/Documents/prodmind/dev.db`)
    - CTO 写自有 5 张表 → `_cto_own_connect()`（不带 mode=ro）
    - CTO 读 PM 表请走 `pm_db_api._readonly_connect()`，**禁止**通过本模块读 PM 表
    - `_ensure_cto_tables()` 仅 CREATE TABLE IF NOT EXISTS，**不**对 PM 表做任何 CREATE/ALTER
    - 老 schema 已存在但缺字段 → 不 ALTER（避免破坏现有数据），需要新字段时另发 ADR + 迁移脚本

参考：
    .planning/phase1/specs/ARCHITECTURE.md §4.3 / §5.4
    .planning/phase1/specs/REQUIREMENTS.md §2.1
    .planning/phase1/decisions/ADR-002-adr-storage-location.md
    docs/PRODUCT-SPEC-v0.2-merged.md §6
    .planning/phase1/recon/RECON-REFERENCE.md §7.2 / §7.3
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRODMIND_DB_PATH = "/Users/feijun/Documents/prodmind/dev.db"

# 受控枚举（与 spec / 任务约束保持一致）
TECH_RISK_SEVERITIES = {"high", "med", "low"}
TECH_RISK_STATUSES = {"open", "mitigated", "accepted", "closed"}

TECH_DEBT_PRIORITIES = {"high", "med", "low"}
TECH_DEBT_STATUSES = {"open", "scheduled", "paid_down", "accepted"}

CODE_REVIEW_APPEAL_STATUSES = {
    "none",
    "pending",
    "retracted",
    "maintained",
    "escalated",
}


# ---------------------------------------------------------------------------
# Connection / utility helpers
# ---------------------------------------------------------------------------

def _cto_own_connect() -> sqlite3.Connection:
    """打开 CTO 写连接（共享 ProdMind dev.db，无 mode=ro）。

    **仅用于** 5 张 CTO 自有表的读写：
        ADR / TechRisk / TechDebt / CodeReview / EngineerProfile

    严禁用此连接 INSERT / UPDATE / DELETE 任何 PM 表（Project / PRD /
    UserStory / Feature / Activity ...）。读 PM 表请改用
    `pm_db_api._readonly_connect()`（mode=ro，物理挡写）。

    返回 row_factory=Row 的连接（可用 dict-like 访问），并打开 foreign_keys。
    """
    conn = sqlite3.connect(PRODMIND_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now_iso() -> str:
    """UTC ISO 时间串（与 ProdMind 风格一致：毫秒精度 + 'Z' 后缀）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _new_id() -> str:
    """UUID v4 字符串。"""
    return str(uuid.uuid4())


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def format_adr_number(number: int) -> str:
    """显示用 ADR 编号格式（"ADR-0001"）。"""
    return f"ADR-{int(number):04d}"


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_CTO_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS "ADR" (
    "id"                       TEXT PRIMARY KEY,
    "project_id"               TEXT NOT NULL,
    "number"                   INTEGER NOT NULL,
    "title"                    TEXT NOT NULL,
    "status"                   TEXT NOT NULL DEFAULT 'accepted',
    "decision"                 TEXT NOT NULL,
    "rationale"                TEXT NOT NULL DEFAULT '',
    "alternatives_considered"  TEXT,
    "decided_by"               TEXT NOT NULL DEFAULT 'AICTO',
    "supersedes"               TEXT,
    "superseded_by"            TEXT,
    "created_at"               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at"               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_ADR_project_id" ON "ADR"("project_id");
CREATE UNIQUE INDEX IF NOT EXISTS "uq_ADR_project_number"
    ON "ADR"("project_id", "number");

CREATE TABLE IF NOT EXISTS "TechRisk" (
    "id"                    TEXT PRIMARY KEY,
    "project_id"            TEXT NOT NULL,
    "severity"              TEXT NOT NULL,
    "probability"           REAL,
    "impact"                TEXT,
    "description"           TEXT NOT NULL DEFAULT '',
    "mitigation"            TEXT,
    "early_warning_signal"  TEXT,
    "status"                TEXT NOT NULL DEFAULT 'open',
    "created_at"            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at"            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_TechRisk_project_id" ON "TechRisk"("project_id");
CREATE INDEX IF NOT EXISTS "idx_TechRisk_status" ON "TechRisk"("status");

CREATE TABLE IF NOT EXISTS "TechDebt" (
    "id"                    TEXT PRIMARY KEY,
    "project_id"            TEXT NOT NULL,
    "type"                  TEXT NOT NULL,
    "description"           TEXT NOT NULL DEFAULT '',
    "introduced_in_commit"  TEXT,
    "paydown_estimate"      TEXT,
    "priority"              TEXT NOT NULL DEFAULT 'med',
    "status"                TEXT NOT NULL DEFAULT 'open',
    "created_at"            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at"            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_TechDebt_project_id" ON "TechDebt"("project_id");
CREATE INDEX IF NOT EXISTS "idx_TechDebt_status" ON "TechDebt"("status");

CREATE TABLE IF NOT EXISTS "CodeReview" (
    "id"                TEXT PRIMARY KEY,
    "project_id"        TEXT NOT NULL,
    "pr_url"            TEXT,
    "commit_sha"        TEXT,
    "checklist_json"    TEXT,
    "blocker_count"     INTEGER NOT NULL DEFAULT 0,
    "suggestion_count"  INTEGER NOT NULL DEFAULT 0,
    "appeal_status"     TEXT NOT NULL DEFAULT 'none',
    "reviewer"          TEXT NOT NULL DEFAULT 'AICTO',
    "reviewed_at"       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at"        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_CodeReview_project_id" ON "CodeReview"("project_id");
CREATE INDEX IF NOT EXISTS "idx_CodeReview_pr_url" ON "CodeReview"("pr_url");
CREATE INDEX IF NOT EXISTS "idx_CodeReview_appeal_status"
    ON "CodeReview"("appeal_status");

CREATE TABLE IF NOT EXISTS "EngineerProfile" (
    "id"                       TEXT PRIMARY KEY,
    "commander_id"             TEXT NOT NULL UNIQUE,
    "skills_json"              TEXT,
    "strengths"                TEXT,
    "weaknesses"               TEXT,
    "past_tasks_count"         INTEGER NOT NULL DEFAULT 0,
    "dispatch_recommendation"  TEXT,
    "created_at"               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at"               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_EngineerProfile_commander_id"
    ON "EngineerProfile"("commander_id");
"""


def _ensure_cto_tables() -> None:
    """启动时建 5 张 CTO 自有表（CREATE TABLE IF NOT EXISTS，幂等）。

    **仅触碰** ADR / TechRisk / TechDebt / CodeReview / EngineerProfile。
    本函数严禁包含针对 PM 表（Project / PRD / UserStory / Feature ...）的
    CREATE / ALTER / INSERT / UPDATE / DELETE 语句。

    现有 schema 缺字段时 **不做** ALTER（避免破坏数据）；如需扩字段，应
    走 ADR-002b 改写 + 迁移脚本流程。
    """
    conn = _cto_own_connect()
    try:
        conn.executescript(_CTO_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ADR
# ---------------------------------------------------------------------------

def _next_adr_number(conn: sqlite3.Connection, project_id: str) -> int:
    """per-project 的 ADR.number 单调递增（从 1 起）。

    DB 层 max(number)+1，初始为 1。配合 (project_id, number) 唯一索引兜底
    并发冲突；如冲突调用方应重试一次（Phase 1 单进程串行写入，目前不会触发）。
    """
    row = conn.execute(
        'SELECT MAX("number") AS m FROM "ADR" WHERE "project_id" = ?',
        (project_id,),
    ).fetchone()
    last = row["m"] if row and row["m"] is not None else 0
    return int(last) + 1


def create_adr(
    project_id: str,
    title: str,
    decision: str,
    rationale: str = "",
    alternatives_considered: Optional[List[Dict[str, Any]]] = None,
    decided_by: str = "AICTO",
    supersedes: Optional[str] = None,
    status: str = "accepted",
    number: Optional[int] = None,
) -> Dict[str, Any]:
    """写入一条 ADR；返回 {id, number, display_number, ...}。

    Args:
        project_id:   关联的 ProdMind Project.id（必填）
        title:        ADR 标题
        decision:     决策内容
        rationale:    决策理由（长文本）
        alternatives_considered: 备选方案 list[dict]，存为 JSON 字符串
        decided_by:   决策者（默认 "AICTO"）
        supersedes:   旧 ADR id（如有，写入并将旧 ADR 标记 superseded_by）
        status:       proposed | accepted | deprecated | superseded
        number:       显式指定编号（可选）；不传则 DB 层 max+1（推荐）

    Returns:
        新创建 ADR 的 dict 视图（含 display_number = "ADR-0001"）
    """
    if not project_id:
        raise ValueError("project_id is required")
    if not title:
        raise ValueError("title is required")
    if not decision:
        raise ValueError("decision is required")

    alternatives_json = (
        json.dumps(alternatives_considered, ensure_ascii=False)
        if alternatives_considered is not None
        else None
    )

    conn = _cto_own_connect()
    try:
        adr_number = number if number is not None else _next_adr_number(conn, project_id)
        adr_id = _new_id()
        now = _now_iso()
        conn.execute(
            'INSERT INTO "ADR" '
            '("id", "project_id", "number", "title", "status", "decision", '
            '"rationale", "alternatives_considered", "decided_by", "supersedes", '
            '"created_at", "updated_at") '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                adr_id,
                project_id,
                adr_number,
                title,
                status,
                decision,
                rationale,
                alternatives_json,
                decided_by,
                supersedes,
                now,
                now,
            ),
        )
        if supersedes:
            conn.execute(
                'UPDATE "ADR" SET "superseded_by" = ?, "status" = ?, "updated_at" = ? '
                'WHERE "id" = ?',
                (adr_id, "superseded", now, supersedes),
            )
        conn.commit()
        return _hydrate_adr_row(get_adr(adr_id, _conn=conn))
    finally:
        conn.close()


def _hydrate_adr_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """ADR 行后处理：解 alternatives_considered JSON + 加 display_number."""
    if row is None:
        return None
    raw = row.get("alternatives_considered")
    if raw:
        try:
            row["alternatives_considered"] = json.loads(raw)
        except (TypeError, ValueError):
            # 损坏或老格式：原样返回，避免静默吃错
            row["alternatives_considered"] = raw
    row["display_number"] = format_adr_number(row["number"])
    return row


def get_adr(
    adr_id: str, _conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """按 id 拉一条 ADR；找不到返回 None。"""
    if not adr_id:
        return None
    conn = _conn or _cto_own_connect()
    try:
        row = conn.execute(
            'SELECT * FROM "ADR" WHERE "id" = ?', (adr_id,)
        ).fetchone()
        result = _row_to_dict(row)
        return _hydrate_adr_row(result) if _conn is None else result
    finally:
        if _conn is None:
            conn.close()


def list_adrs(project_id: str) -> List[Dict[str, Any]]:
    """按 number 升序列项目下的所有 ADR；alternatives_considered 已 JSON 解析。"""
    if not project_id:
        return []
    conn = _cto_own_connect()
    try:
        rows = conn.execute(
            'SELECT * FROM "ADR" WHERE "project_id" = ? ORDER BY "number" ASC',
            (project_id,),
        ).fetchall()
        return [_hydrate_adr_row(dict(r)) for r in rows]
    finally:
        conn.close()


def supersede_adr(old_adr_id: str, new_adr_id: str) -> Dict[str, Any]:
    """把旧 ADR 标记为 superseded、并 link 到新 ADR.id；返回更新后的两行。"""
    if not old_adr_id or not new_adr_id:
        raise ValueError("old_adr_id / new_adr_id are required")
    if old_adr_id == new_adr_id:
        raise ValueError("old_adr_id and new_adr_id must differ")

    conn = _cto_own_connect()
    try:
        now = _now_iso()
        # 校验两个 ADR 都存在
        old_row = conn.execute(
            'SELECT "id" FROM "ADR" WHERE "id" = ?', (old_adr_id,)
        ).fetchone()
        new_row = conn.execute(
            'SELECT "id" FROM "ADR" WHERE "id" = ?', (new_adr_id,)
        ).fetchone()
        if old_row is None:
            raise ValueError(f"old ADR not found: {old_adr_id}")
        if new_row is None:
            raise ValueError(f"new ADR not found: {new_adr_id}")

        conn.execute(
            'UPDATE "ADR" SET "superseded_by" = ?, "status" = ?, "updated_at" = ? '
            'WHERE "id" = ?',
            (new_adr_id, "superseded", now, old_adr_id),
        )
        conn.execute(
            'UPDATE "ADR" SET "supersedes" = ?, "updated_at" = ? WHERE "id" = ?',
            (old_adr_id, now, new_adr_id),
        )
        conn.commit()
        return {
            "old": _hydrate_adr_row(_row_to_dict(
                conn.execute('SELECT * FROM "ADR" WHERE "id" = ?', (old_adr_id,)).fetchone()
            )),
            "new": _hydrate_adr_row(_row_to_dict(
                conn.execute('SELECT * FROM "ADR" WHERE "id" = ?', (new_adr_id,)).fetchone()
            )),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TechRisk
# ---------------------------------------------------------------------------

def create_risk(
    project_id: str,
    severity: str,
    description: str,
    probability: Optional[float] = None,
    impact: Optional[str] = None,
    mitigation: Optional[str] = None,
    early_warning_signal: Optional[str] = None,
    status: str = "open",
) -> Dict[str, Any]:
    """写入一条 TechRisk；severity ∈ {high, med, low}, status ∈ {open, mitigated, accepted, closed}."""
    if not project_id:
        raise ValueError("project_id is required")
    if not description:
        raise ValueError("description is required")
    if severity not in TECH_RISK_SEVERITIES:
        raise ValueError(
            f"severity must be one of {sorted(TECH_RISK_SEVERITIES)}, got {severity!r}"
        )
    if status not in TECH_RISK_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(TECH_RISK_STATUSES)}, got {status!r}"
        )

    risk_id = _new_id()
    now = _now_iso()
    conn = _cto_own_connect()
    try:
        conn.execute(
            'INSERT INTO "TechRisk" '
            '("id", "project_id", "severity", "probability", "impact", "description", '
            '"mitigation", "early_warning_signal", "status", "created_at", "updated_at") '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                risk_id,
                project_id,
                severity,
                probability,
                impact,
                description,
                mitigation,
                early_warning_signal,
                status,
                now,
                now,
            ),
        )
        conn.commit()
        return _row_to_dict(
            conn.execute('SELECT * FROM "TechRisk" WHERE "id" = ?', (risk_id,)).fetchone()
        )
    finally:
        conn.close()


def list_risks(
    project_id: str, status_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """列项目下 TechRisk；可按 status 过滤；按 created_at 降序。"""
    if not project_id:
        return []
    if status_filter is not None and status_filter not in TECH_RISK_STATUSES:
        raise ValueError(
            f"status_filter must be one of {sorted(TECH_RISK_STATUSES)}, "
            f"got {status_filter!r}"
        )

    conn = _cto_own_connect()
    try:
        if status_filter is None:
            rows = conn.execute(
                'SELECT * FROM "TechRisk" WHERE "project_id" = ? '
                'ORDER BY "created_at" DESC',
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM "TechRisk" WHERE "project_id" = ? AND "status" = ? '
                'ORDER BY "created_at" DESC',
                (project_id, status_filter),
            ).fetchall()
        return _rows_to_list(rows)
    finally:
        conn.close()


def update_risk_status(risk_id: str, new_status: str) -> Dict[str, Any]:
    """切换 TechRisk.status；返回更新后的行。找不到行抛 ValueError。"""
    if not risk_id:
        raise ValueError("risk_id is required")
    if new_status not in TECH_RISK_STATUSES:
        raise ValueError(
            f"new_status must be one of {sorted(TECH_RISK_STATUSES)}, got {new_status!r}"
        )

    now = _now_iso()
    conn = _cto_own_connect()
    try:
        cur = conn.execute(
            'UPDATE "TechRisk" SET "status" = ?, "updated_at" = ? WHERE "id" = ?',
            (new_status, now, risk_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"TechRisk not found: {risk_id}")
        conn.commit()
        return _row_to_dict(
            conn.execute('SELECT * FROM "TechRisk" WHERE "id" = ?', (risk_id,)).fetchone()
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TechDebt
# ---------------------------------------------------------------------------

def create_debt(
    project_id: str,
    type: str,
    description: str,
    introduced_in_commit: Optional[str] = None,
    paydown_estimate: Optional[str] = None,
    priority: str = "med",
    status: str = "open",
) -> Dict[str, Any]:
    """写入一条 TechDebt；priority ∈ {high, med, low}, status ∈ {open, scheduled, paid_down, accepted}."""
    if not project_id:
        raise ValueError("project_id is required")
    if not type:
        raise ValueError("type is required")
    if not description:
        raise ValueError("description is required")
    if priority not in TECH_DEBT_PRIORITIES:
        raise ValueError(
            f"priority must be one of {sorted(TECH_DEBT_PRIORITIES)}, got {priority!r}"
        )
    if status not in TECH_DEBT_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(TECH_DEBT_STATUSES)}, got {status!r}"
        )

    debt_id = _new_id()
    now = _now_iso()
    conn = _cto_own_connect()
    try:
        conn.execute(
            'INSERT INTO "TechDebt" '
            '("id", "project_id", "type", "description", "introduced_in_commit", '
            '"paydown_estimate", "priority", "status", "created_at", "updated_at") '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                debt_id,
                project_id,
                type,
                description,
                introduced_in_commit,
                paydown_estimate,
                priority,
                status,
                now,
                now,
            ),
        )
        conn.commit()
        return _row_to_dict(
            conn.execute('SELECT * FROM "TechDebt" WHERE "id" = ?', (debt_id,)).fetchone()
        )
    finally:
        conn.close()


def list_debts(
    project_id: str, status_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """列项目下 TechDebt；可按 status 过滤；按 created_at 降序。"""
    if not project_id:
        return []
    if status_filter is not None and status_filter not in TECH_DEBT_STATUSES:
        raise ValueError(
            f"status_filter must be one of {sorted(TECH_DEBT_STATUSES)}, "
            f"got {status_filter!r}"
        )

    conn = _cto_own_connect()
    try:
        if status_filter is None:
            rows = conn.execute(
                'SELECT * FROM "TechDebt" WHERE "project_id" = ? '
                'ORDER BY "created_at" DESC',
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM "TechDebt" WHERE "project_id" = ? AND "status" = ? '
                'ORDER BY "created_at" DESC',
                (project_id, status_filter),
            ).fetchall()
        return _rows_to_list(rows)
    finally:
        conn.close()


def update_debt_status(debt_id: str, new_status: str) -> Dict[str, Any]:
    """切换 TechDebt.status；返回更新后的行。找不到行抛 ValueError。"""
    if not debt_id:
        raise ValueError("debt_id is required")
    if new_status not in TECH_DEBT_STATUSES:
        raise ValueError(
            f"new_status must be one of {sorted(TECH_DEBT_STATUSES)}, got {new_status!r}"
        )

    now = _now_iso()
    conn = _cto_own_connect()
    try:
        cur = conn.execute(
            'UPDATE "TechDebt" SET "status" = ?, "updated_at" = ? WHERE "id" = ?',
            (new_status, now, debt_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"TechDebt not found: {debt_id}")
        conn.commit()
        return _row_to_dict(
            conn.execute('SELECT * FROM "TechDebt" WHERE "id" = ?', (debt_id,)).fetchone()
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CodeReview
# ---------------------------------------------------------------------------

def create_review(
    project_id: str,
    pr_url: Optional[str] = None,
    commit_sha: Optional[str] = None,
    checklist: Optional[List[Dict[str, Any]]] = None,
    blocker_count: int = 0,
    suggestion_count: int = 0,
    appeal_status: str = "none",
    reviewer: str = "AICTO",
) -> Dict[str, Any]:
    """写入一条 CodeReview；checklist 存 JSON 字符串到 checklist_json.

    Args:
        checklist: 10 项审查 list[{item, status, message}]，dump 为 checklist_json
        appeal_status: ∈ {none, pending, retracted, maintained, escalated}
    """
    if not project_id:
        raise ValueError("project_id is required")
    if appeal_status not in CODE_REVIEW_APPEAL_STATUSES:
        raise ValueError(
            f"appeal_status must be one of {sorted(CODE_REVIEW_APPEAL_STATUSES)}, "
            f"got {appeal_status!r}"
        )

    checklist_json = (
        json.dumps(checklist, ensure_ascii=False) if checklist is not None else None
    )

    review_id = _new_id()
    now = _now_iso()
    conn = _cto_own_connect()
    try:
        conn.execute(
            'INSERT INTO "CodeReview" '
            '("id", "project_id", "pr_url", "commit_sha", "checklist_json", '
            '"blocker_count", "suggestion_count", "appeal_status", "reviewer", '
            '"reviewed_at", "updated_at") '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                review_id,
                project_id,
                pr_url,
                commit_sha,
                checklist_json,
                int(blocker_count),
                int(suggestion_count),
                appeal_status,
                reviewer,
                now,
                now,
            ),
        )
        conn.commit()
        return _hydrate_review_row(_row_to_dict(
            conn.execute('SELECT * FROM "CodeReview" WHERE "id" = ?', (review_id,)).fetchone()
        ))
    finally:
        conn.close()


def _hydrate_review_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """CodeReview 行后处理：解 checklist_json 为 list（保留原 string key 不动）。"""
    if row is None:
        return None
    raw = row.get("checklist_json")
    if raw:
        try:
            row["checklist"] = json.loads(raw)
        except (TypeError, ValueError):
            row["checklist"] = None
    else:
        row["checklist"] = None
    return row


def list_reviews(
    project_id: str, pr_url: Optional[str] = None
) -> List[Dict[str, Any]]:
    """列项目下 CodeReview；可按 pr_url 精确过滤；按 reviewed_at 降序。"""
    if not project_id:
        return []
    conn = _cto_own_connect()
    try:
        if pr_url is None:
            rows = conn.execute(
                'SELECT * FROM "CodeReview" WHERE "project_id" = ? '
                'ORDER BY "reviewed_at" DESC',
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM "CodeReview" WHERE "project_id" = ? AND "pr_url" = ? '
                'ORDER BY "reviewed_at" DESC',
                (project_id, pr_url),
            ).fetchall()
        return [_hydrate_review_row(dict(r)) for r in rows]
    finally:
        conn.close()


def update_appeal_status(review_id: str, new_status: str) -> Dict[str, Any]:
    """切换 CodeReview.appeal_status；返回更新后的行。找不到行抛 ValueError。"""
    if not review_id:
        raise ValueError("review_id is required")
    if new_status not in CODE_REVIEW_APPEAL_STATUSES:
        raise ValueError(
            f"new_status must be one of {sorted(CODE_REVIEW_APPEAL_STATUSES)}, "
            f"got {new_status!r}"
        )

    now = _now_iso()
    conn = _cto_own_connect()
    try:
        cur = conn.execute(
            'UPDATE "CodeReview" SET "appeal_status" = ?, "updated_at" = ? '
            'WHERE "id" = ?',
            (new_status, now, review_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"CodeReview not found: {review_id}")
        conn.commit()
        return _hydrate_review_row(_row_to_dict(
            conn.execute('SELECT * FROM "CodeReview" WHERE "id" = ?', (review_id,)).fetchone()
        ))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# EngineerProfile
# ---------------------------------------------------------------------------

def create_profile(
    commander_id: str,
    skills: Optional[Dict[str, Any]] = None,
    strengths: Optional[List[str]] = None,
    weaknesses: Optional[List[str]] = None,
    past_tasks_count: int = 0,
    dispatch_recommendation: Optional[str] = None,
) -> Dict[str, Any]:
    """写入一条 EngineerProfile；commander_id 唯一（已建 UNIQUE 约束）。

    重复 commander_id 会触发 sqlite3.IntegrityError，调用方按需捕获。
    """
    if not commander_id:
        raise ValueError("commander_id is required")

    skills_json = json.dumps(skills, ensure_ascii=False) if skills is not None else None
    strengths_json = (
        json.dumps(strengths, ensure_ascii=False) if strengths is not None else None
    )
    weaknesses_json = (
        json.dumps(weaknesses, ensure_ascii=False) if weaknesses is not None else None
    )

    profile_id = _new_id()
    now = _now_iso()
    conn = _cto_own_connect()
    try:
        conn.execute(
            'INSERT INTO "EngineerProfile" '
            '("id", "commander_id", "skills_json", "strengths", "weaknesses", '
            '"past_tasks_count", "dispatch_recommendation", "created_at", "updated_at") '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                profile_id,
                commander_id,
                skills_json,
                strengths_json,
                weaknesses_json,
                int(past_tasks_count),
                dispatch_recommendation,
                now,
                now,
            ),
        )
        conn.commit()
        return _hydrate_profile_row(_row_to_dict(
            conn.execute(
                'SELECT * FROM "EngineerProfile" WHERE "id" = ?', (profile_id,)
            ).fetchone()
        ))
    finally:
        conn.close()


def _hydrate_profile_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """EngineerProfile 行后处理：解 skills_json / strengths / weaknesses JSON。"""
    if row is None:
        return None
    for key, out_key in (
        ("skills_json", "skills"),
        ("strengths", "strengths_list"),
        ("weaknesses", "weaknesses_list"),
    ):
        raw = row.get(key)
        if raw:
            try:
                row[out_key] = json.loads(raw)
            except (TypeError, ValueError):
                row[out_key] = None
        else:
            row[out_key] = None
    return row


def list_profiles() -> List[Dict[str, Any]]:
    """列全部 EngineerProfile；按 commander_id 升序。"""
    conn = _cto_own_connect()
    try:
        rows = conn.execute(
            'SELECT * FROM "EngineerProfile" ORDER BY "commander_id" ASC'
        ).fetchall()
        return [_hydrate_profile_row(dict(r)) for r in rows]
    finally:
        conn.close()


def get_profile(commander_id: str) -> Optional[Dict[str, Any]]:
    """按 commander_id 拉一条 EngineerProfile；找不到返回 None。"""
    if not commander_id:
        return None
    conn = _cto_own_connect()
    try:
        row = conn.execute(
            'SELECT * FROM "EngineerProfile" WHERE "commander_id" = ?',
            (commander_id,),
        ).fetchone()
        return _hydrate_profile_row(_row_to_dict(row))
    finally:
        conn.close()


def update_skills(
    commander_id: str,
    skills: Optional[Dict[str, Any]] = None,
    strengths: Optional[List[str]] = None,
    weaknesses: Optional[List[str]] = None,
    dispatch_recommendation: Optional[str] = None,
) -> Dict[str, Any]:
    """更新 EngineerProfile 的能力字段（None = 不变）；返回更新后的行。

    找不到 commander_id 抛 ValueError（不自动 upsert，避免静默写新行）。
    """
    if not commander_id:
        raise ValueError("commander_id is required")

    sets: List[str] = []
    params: List[Any] = []
    if skills is not None:
        sets.append('"skills_json" = ?')
        params.append(json.dumps(skills, ensure_ascii=False))
    if strengths is not None:
        sets.append('"strengths" = ?')
        params.append(json.dumps(strengths, ensure_ascii=False))
    if weaknesses is not None:
        sets.append('"weaknesses" = ?')
        params.append(json.dumps(weaknesses, ensure_ascii=False))
    if dispatch_recommendation is not None:
        sets.append('"dispatch_recommendation" = ?')
        params.append(dispatch_recommendation)

    if not sets:
        # 没有要更新的字段：直接返回当前行（避免空 UPDATE）
        existing = get_profile(commander_id)
        if existing is None:
            raise ValueError(f"EngineerProfile not found: {commander_id}")
        return existing

    sets.append('"updated_at" = ?')
    params.append(_now_iso())
    params.append(commander_id)

    conn = _cto_own_connect()
    try:
        cur = conn.execute(
            f'UPDATE "EngineerProfile" SET {", ".join(sets)} '
            'WHERE "commander_id" = ?',
            params,
        )
        if cur.rowcount == 0:
            raise ValueError(f"EngineerProfile not found: {commander_id}")
        conn.commit()
        return _hydrate_profile_row(_row_to_dict(
            conn.execute(
                'SELECT * FROM "EngineerProfile" WHERE "commander_id" = ?',
                (commander_id,),
            ).fetchone()
        ))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Module-level bootstrap (runs once on import)
# ---------------------------------------------------------------------------
# 与 ProdMind tools.py 风格一致（参见 prodmind/hermes-plugin/tools.py:9673）：
# 模块导入时自动执行一次 schema 创建（幂等），让 plugin 启动即就绪。
_ensure_cto_tables()
