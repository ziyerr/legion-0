"""AICTO P1.1 — PM 只读数据访问层（pm_db_api）.

CTO 读 ProdMind dev.db 的唯一入口。所有 SQL 通过 `_readonly_connect()` 走
SQLite URI `mode=ro`，物理层挡住一切 UPDATE/INSERT/DELETE。

实现内容（详见 .planning/phase1/specs/REQUIREMENTS.md §3.2/3.3
+ docs/CTO-READ-ACCESS-SPEC.md §三）：

- 8 个 PM 只读工具（R-TL-7 ~ R-TL-14）
  - read_pm_project / read_pm_prd / list_pm_prd_decisions / list_pm_open_questions
  - list_pm_user_stories / list_pm_features / read_pm_research_doc / read_pm_evaluation_doc
- 2 个综合工具（R-TL-15/16）
  - get_pm_context_for_tech_plan / diff_pm_prd_versions

纪律（不可违反，违反即审查 BLOCKING）：
1. 本模块**不得**有 INSERT / UPDATE / DELETE / REPLACE / DROP 语句（grep 验证）
2. 全部 SQL 用参数化查询（? 占位符），不得拼接字符串（防 SQL 注入）
3. 输入 args 用 args.get(key, default)，禁止 args[key]
4. 失败返 {"error": "msg"}，不得包装成 {"success": False, "message": "..."}
5. 所有工具 return json.dumps({...}, ensure_ascii=False)
6. 每次工具调用末尾 append 一行 JSON 到审计日志
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PRODMIND_DB_PATH = "/Users/feijun/Documents/prodmind/dev.db"
"""ProdMind dev.db 绝对路径。CTO 借 PM 的 db 加自己的表（详见 ARCHITECTURE.md §1）。"""

AUDIT_LOG_PATH = pathlib.Path.home() / ".hermes/profiles/aicto/logs/read-audit.log"
"""读权限审计日志（R-NFR-31）。每次工具调用 append 一行 JSON。"""

# ---------------------------------------------------------------------------
# 连接 & 审计
# ---------------------------------------------------------------------------


def _readonly_connect() -> sqlite3.Connection:
    """只读连接 ProdMind dev.db。

    使用 SQLite URI `mode=ro` 在驱动层禁止任何写操作 —— 即使本模块代码出 bug
    写了 UPDATE/INSERT/DELETE 也会抛 `attempt to write a readonly database`。

    详见 docs/CTO-READ-ACCESS-SPEC.md §二·A、ARCHITECTURE.md §4.2。
    """
    uri = f"file:{PRODMIND_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _audit_log(tool: str, args: Dict[str, Any], rows_returned: int) -> None:
    """append 一行 JSON 到 read-audit.log。

    高频读不需要锁：append 模式 + 单行 JSON 即使并发交错也保证行完整性
    （POSIX append O_APPEND 原子性 + 每行一次 write）。
    """
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": tool,
            "args": args,
            "rows_returned": rows_returned,
        }
        line = json.dumps(record, ensure_ascii=False)
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # 审计失败不阻塞业务返回（审计是观测，不是关键路径）
        pass


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """sqlite3.Row → dict（None 透传）。"""
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _rows_to_list(rows) -> List[Dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in rows]


def _ok(payload: Dict[str, Any]) -> str:
    """成功返回 — 顶层带 success=True 的结构化 JSON。"""
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _err(message: str, **extra: Any) -> str:
    """失败返回 — 顶层 error key（反幻觉硬约束：不得用 success=False）。"""
    return json.dumps({"error": message, **extra}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 8 个 PM 只读工具
# ---------------------------------------------------------------------------


def read_pm_project(args: Dict[str, Any], **kwargs) -> str:
    """读 Project 行（R-TL-7）。

    入参：project_id (required)
    """
    project_id = args.get("project_id")
    if not project_id:
        return _err("missing required arg: project_id")

    try:
        conn = _readonly_connect()
        try:
            cur = conn.execute(
                'SELECT * FROM "Project" WHERE id = ?',
                (project_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("read_pm_project", args, 0)
        return _err(f"sqlite error: {e}")

    if row is None:
        _audit_log("read_pm_project", args, 0)
        return _err(f"project not found: {project_id}", project_id=project_id)

    _audit_log("read_pm_project", args, 1)
    return _ok({"project": _row_to_dict(row)})


def read_pm_prd(args: Dict[str, Any], **kwargs) -> str:
    """读 PRD 行（R-TL-8）。

    入参：
    - prd_id (required)
    - include_versions (optional, bool, default False) — 是否含 PRDVersion 历史
    """
    prd_id = args.get("prd_id")
    if not prd_id:
        return _err("missing required arg: prd_id")
    include_versions = bool(args.get("include_versions", False))

    try:
        conn = _readonly_connect()
        try:
            cur = conn.execute(
                'SELECT * FROM "PRD" WHERE id = ?',
                (prd_id,),
            )
            prd_row = cur.fetchone()
            if prd_row is None:
                _audit_log("read_pm_prd", args, 0)
                return _err(f"prd not found: {prd_id}", prd_id=prd_id)

            versions: List[Dict[str, Any]] = []
            if include_versions:
                vcur = conn.execute(
                    'SELECT * FROM "PRDVersion" WHERE prdId = ? ORDER BY versionNumber ASC',
                    (prd_id,),
                )
                versions = _rows_to_list(vcur.fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("read_pm_prd", args, 0)
        return _err(f"sqlite error: {e}")

    rows_returned = 1 + len(versions)
    _audit_log("read_pm_prd", args, rows_returned)
    payload: Dict[str, Any] = {"prd": _row_to_dict(prd_row)}
    if include_versions:
        payload["versions"] = versions
        payload["versions_count"] = len(versions)
    return _ok(payload)


def list_pm_prd_decisions(args: Dict[str, Any], **kwargs) -> str:
    """列 PRDDecision 行（R-TL-9）。

    入参：prd_id (required)
    """
    prd_id = args.get("prd_id")
    if not prd_id:
        return _err("missing required arg: prd_id")

    try:
        conn = _readonly_connect()
        try:
            cur = conn.execute(
                'SELECT * FROM "PRDDecision" WHERE prdId = ? ORDER BY decidedAt DESC',
                (prd_id,),
            )
            rows = _rows_to_list(cur.fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("list_pm_prd_decisions", args, 0)
        return _err(f"sqlite error: {e}")

    _audit_log("list_pm_prd_decisions", args, len(rows))
    return _ok({"decisions": rows, "count": len(rows), "prd_id": prd_id})


def list_pm_open_questions(args: Dict[str, Any], **kwargs) -> str:
    """列 PRDOpenQuestion 行（R-TL-10）。

    入参：
    - prd_id (required)
    - status_filter (optional, "open" | "answered" | "all", default "open")
    """
    prd_id = args.get("prd_id")
    if not prd_id:
        return _err("missing required arg: prd_id")
    status_filter = args.get("status_filter", "open")
    if status_filter not in ("open", "answered", "all"):
        return _err(
            f"invalid status_filter: {status_filter} (must be one of: open / answered / all)"
        )

    try:
        conn = _readonly_connect()
        try:
            if status_filter == "all":
                cur = conn.execute(
                    'SELECT * FROM "PRDOpenQuestion" WHERE prdId = ? '
                    "ORDER BY createdAt DESC",
                    (prd_id,),
                )
            else:
                cur = conn.execute(
                    'SELECT * FROM "PRDOpenQuestion" WHERE prdId = ? AND status = ? '
                    "ORDER BY createdAt DESC",
                    (prd_id, status_filter),
                )
            rows = _rows_to_list(cur.fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("list_pm_open_questions", args, 0)
        return _err(f"sqlite error: {e}")

    _audit_log("list_pm_open_questions", args, len(rows))
    return _ok(
        {
            "open_questions": rows,
            "count": len(rows),
            "prd_id": prd_id,
            "status_filter": status_filter,
        }
    )


def list_pm_user_stories(args: Dict[str, Any], **kwargs) -> str:
    """列 UserStory 行（R-TL-11）。

    入参（二选一，至少一个）：
    - project_id — 直接按 projectId 列
    - prd_id — 先用 prd_id 反查 projectId 再列（UserStory 表无 prdId 列）
    """
    project_id = args.get("project_id")
    prd_id = args.get("prd_id")
    if not project_id and not prd_id:
        return _err("must provide either project_id or prd_id")

    try:
        conn = _readonly_connect()
        try:
            # 若只给了 prd_id，先反查 projectId
            if not project_id:
                pcur = conn.execute(
                    'SELECT projectId FROM "PRD" WHERE id = ?',
                    (prd_id,),
                )
                prow = pcur.fetchone()
                if prow is None:
                    _audit_log("list_pm_user_stories", args, 0)
                    return _err(
                        f"prd not found: {prd_id} (cannot resolve projectId)",
                        prd_id=prd_id,
                    )
                project_id = prow["projectId"]

            cur = conn.execute(
                'SELECT * FROM "UserStory" WHERE projectId = ? '
                "ORDER BY priority DESC, createdAt DESC",
                (project_id,),
            )
            rows = _rows_to_list(cur.fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("list_pm_user_stories", args, 0)
        return _err(f"sqlite error: {e}")

    _audit_log("list_pm_user_stories", args, len(rows))
    return _ok({"user_stories": rows, "count": len(rows), "project_id": project_id})


def list_pm_features(args: Dict[str, Any], **kwargs) -> str:
    """列 Feature 行（R-TL-12，含 RICE 评分）。

    入参：
    - project_id (required)
    - min_rice_score (optional, number)
    """
    project_id = args.get("project_id")
    if not project_id:
        return _err("missing required arg: project_id")

    min_rice_score = args.get("min_rice_score")

    try:
        conn = _readonly_connect()
        try:
            if min_rice_score is None:
                cur = conn.execute(
                    'SELECT * FROM "Feature" WHERE projectId = ? '
                    "ORDER BY riceScore DESC NULLS LAST, createdAt DESC",
                    (project_id,),
                )
            else:
                # SQLite 数值比较（min_rice_score 为 None 时 riceScore 也匹配不上 → 排除）
                cur = conn.execute(
                    'SELECT * FROM "Feature" WHERE projectId = ? AND riceScore IS NOT NULL '
                    "AND riceScore >= ? ORDER BY riceScore DESC, createdAt DESC",
                    (project_id, min_rice_score),
                )
            rows = _rows_to_list(cur.fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("list_pm_features", args, 0)
        return _err(f"sqlite error: {e}")

    _audit_log("list_pm_features", args, len(rows))
    return _ok({"features": rows, "count": len(rows), "project_id": project_id})


def read_pm_research_doc(args: Dict[str, Any], **kwargs) -> str:
    """读 Research 行（R-TL-13，市场 / 用户调研）。

    入参：research_id (required) — 即 Research.id
    """
    research_id = args.get("research_id")
    if not research_id:
        return _err("missing required arg: research_id")

    try:
        conn = _readonly_connect()
        try:
            cur = conn.execute(
                'SELECT * FROM "Research" WHERE id = ?',
                (research_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("read_pm_research_doc", args, 0)
        return _err(f"sqlite error: {e}")

    if row is None:
        _audit_log("read_pm_research_doc", args, 0)
        return _err(
            f"research not found: {research_id}", research_id=research_id
        )

    _audit_log("read_pm_research_doc", args, 1)
    return _ok({"research": _row_to_dict(row)})


def read_pm_evaluation_doc(args: Dict[str, Any], **kwargs) -> str:
    """读 Evaluation 行（R-TL-14，三层评估）。

    入参：evaluation_id (required) — 即 Evaluation.id
    """
    evaluation_id = args.get("evaluation_id")
    if not evaluation_id:
        return _err("missing required arg: evaluation_id")

    try:
        conn = _readonly_connect()
        try:
            cur = conn.execute(
                'SELECT * FROM "Evaluation" WHERE id = ?',
                (evaluation_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("read_pm_evaluation_doc", args, 0)
        return _err(f"sqlite error: {e}")

    if row is None:
        _audit_log("read_pm_evaluation_doc", args, 0)
        return _err(
            f"evaluation not found: {evaluation_id}", evaluation_id=evaluation_id
        )

    _audit_log("read_pm_evaluation_doc", args, 1)
    return _ok({"evaluation": _row_to_dict(row)})


# ---------------------------------------------------------------------------
# 2 个综合工具
# ---------------------------------------------------------------------------


def get_pm_context_for_tech_plan(args: Dict[str, Any], **kwargs) -> str:
    """一键拉取 design_tech_plan 所需 PM 上下文（R-TL-15）。

    一次连接、5 张表查询：
    - PRD（含基础元数据 + 内容）
    - UserStory[]（按 projectId 拉，priority 降序）
    - Feature[]（按 projectId 拉，riceScore 降序）
    - PRDDecision[]（按 prdId 拉，decidedAt 降序）
    - PRDOpenQuestion[]（按 prdId 拉，仅 status='open'）

    入参（二选一，prd_id 优先）：
    - prd_id — 主链路（dev.db 主键）
    - project_id — 备用（如未指定 prd_id 则按 projectId 找最新 PRD）
    """
    prd_id = args.get("prd_id")
    project_id = args.get("project_id")
    if not prd_id and not project_id:
        return _err("must provide either prd_id or project_id")

    try:
        conn = _readonly_connect()
        try:
            # 1. PRD 定位
            if prd_id:
                cur = conn.execute(
                    'SELECT * FROM "PRD" WHERE id = ?',
                    (prd_id,),
                )
                prd_row = cur.fetchone()
                if prd_row is None:
                    _audit_log("get_pm_context_for_tech_plan", args, 0)
                    return _err(f"prd not found: {prd_id}", prd_id=prd_id)
                project_id = prd_row["projectId"]
            else:
                # 按 projectId 找该项目最新一条 PRD（按 version 降序，再按 updatedAt）
                cur = conn.execute(
                    'SELECT * FROM "PRD" WHERE projectId = ? '
                    "ORDER BY version DESC, updatedAt DESC LIMIT 1",
                    (project_id,),
                )
                prd_row = cur.fetchone()
                if prd_row is None:
                    _audit_log("get_pm_context_for_tech_plan", args, 0)
                    return _err(
                        f"no PRD found for project: {project_id}",
                        project_id=project_id,
                    )
                prd_id = prd_row["id"]

            # 2. UserStory[]
            ucur = conn.execute(
                'SELECT * FROM "UserStory" WHERE projectId = ? '
                "ORDER BY priority DESC, createdAt DESC",
                (project_id,),
            )
            user_stories = _rows_to_list(ucur.fetchall())

            # 3. Feature[]
            fcur = conn.execute(
                'SELECT * FROM "Feature" WHERE projectId = ? '
                "ORDER BY riceScore DESC NULLS LAST, createdAt DESC",
                (project_id,),
            )
            features = _rows_to_list(fcur.fetchall())

            # 4. PRDDecision[]
            dcur = conn.execute(
                'SELECT * FROM "PRDDecision" WHERE prdId = ? '
                "ORDER BY decidedAt DESC",
                (prd_id,),
            )
            decisions = _rows_to_list(dcur.fetchall())

            # 5. PRDOpenQuestion[] — 仅 status=open（CTO 评估时重点看）
            qcur = conn.execute(
                'SELECT * FROM "PRDOpenQuestion" WHERE prdId = ? AND status = ? '
                "ORDER BY createdAt DESC",
                (prd_id, "open"),
            )
            open_questions = _rows_to_list(qcur.fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("get_pm_context_for_tech_plan", args, 0)
        return _err(f"sqlite error: {e}")

    rows_returned = (
        1
        + len(user_stories)
        + len(features)
        + len(decisions)
        + len(open_questions)
    )
    _audit_log("get_pm_context_for_tech_plan", args, rows_returned)

    return _ok(
        {
            "prd_id": prd_id,
            "project_id": project_id,
            "prd": _row_to_dict(prd_row),
            "user_stories": user_stories,
            "user_stories_count": len(user_stories),
            "features": features,
            "features_count": len(features),
            "decisions": decisions,
            "decisions_count": len(decisions),
            "open_questions": open_questions,
            "open_questions_count": len(open_questions),
        }
    )


def diff_pm_prd_versions(args: Dict[str, Any], **kwargs) -> str:
    """对比同一 PRD 的两个版本（R-TL-16）。

    入参：
    - prd_id (required)
    - version_a (required, integer) — 基准版本号（PRDVersion.versionNumber）
    - version_b (required, integer) — 目标版本号

    返回：两版本元数据 + 内容 + 字符级 unified diff（用 difflib.unified_diff）。
    review_code 检查"PRD 一致"维度时调用。
    """
    prd_id = args.get("prd_id")
    version_a = args.get("version_a")
    version_b = args.get("version_b")
    if not prd_id:
        return _err("missing required arg: prd_id")
    if version_a is None or version_b is None:
        return _err("missing required args: version_a / version_b")
    if not isinstance(version_a, int) or not isinstance(version_b, int):
        return _err(
            "version_a / version_b must be integers (PRDVersion.versionNumber)"
        )

    try:
        conn = _readonly_connect()
        try:
            cur = conn.execute(
                'SELECT * FROM "PRDVersion" WHERE prdId = ? AND versionNumber IN (?, ?)',
                (prd_id, version_a, version_b),
            )
            rows = _rows_to_list(cur.fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        _audit_log("diff_pm_prd_versions", args, 0)
        return _err(f"sqlite error: {e}")

    by_version = {r["versionNumber"]: r for r in rows}
    if version_a not in by_version:
        _audit_log("diff_pm_prd_versions", args, len(rows))
        return _err(
            f"version_a not found: prd_id={prd_id} versionNumber={version_a}",
            prd_id=prd_id,
            version_a=version_a,
        )
    if version_b not in by_version:
        _audit_log("diff_pm_prd_versions", args, len(rows))
        return _err(
            f"version_b not found: prd_id={prd_id} versionNumber={version_b}",
            prd_id=prd_id,
            version_b=version_b,
        )

    a_row = by_version[version_a]
    b_row = by_version[version_b]

    import difflib

    a_content = a_row.get("content") or ""
    b_content = b_row.get("content") or ""
    diff_lines = list(
        difflib.unified_diff(
            a_content.splitlines(keepends=True),
            b_content.splitlines(keepends=True),
            fromfile=f"v{version_a}",
            tofile=f"v{version_b}",
            n=3,
        )
    )

    _audit_log("diff_pm_prd_versions", args, len(rows))
    return _ok(
        {
            "prd_id": prd_id,
            "version_a": {
                "versionNumber": version_a,
                "title": a_row.get("title"),
                "changeReason": a_row.get("changeReason"),
                "changeType": a_row.get("changeType"),
                "changedBy": a_row.get("changedBy"),
                "createdAt": a_row.get("createdAt"),
                "content": a_content,
            },
            "version_b": {
                "versionNumber": version_b,
                "title": b_row.get("title"),
                "changeReason": b_row.get("changeReason"),
                "changeType": b_row.get("changeType"),
                "changedBy": b_row.get("changedBy"),
                "createdAt": b_row.get("createdAt"),
                "content": b_content,
            },
            "unified_diff": "".join(diff_lines),
            "diff_line_count": len(diff_lines),
        }
    )
