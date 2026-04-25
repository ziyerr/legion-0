"""daily_brief.py — 能力 5：项目动向日报 + BLOCKING 即时推送 + 24h 催促

P1.7 核心入口实现。tools.py 仅 dispatch 到本模块的 ``run`` 函数。

四种触发处理（详见 REQUIREMENTS §1.6 / PRD-CAPABILITIES 能力 5）：
  1. trigger="scheduled"      18:00 cron 自动调用 — 30 秒"掌握全部"概括（≤500 字 飞书消息）
  2. trigger="blocking_push"  review_code 输出 hook — 即时推送 BLOCKING 卡片（≤10 秒延迟）
  3. trigger="stale_alert"    24h 未进展催促 — @对应 commander；二次催促失败 → 升级骏飞
  4. trigger="manual"         手动调用 — 同 scheduled 但不写 last_brief_run.json

关键约束（硬纪律）：
- LLM prompt 强约束 ≤500 字（30 秒可读）
- UTC+8 时区（PM R-OPEN-7 默认）
- 二次催促失败 → escalate_to_owner @张骏飞
- _DailyBriefError 继承 WrappedToolError（防 B-1 第六轮）
- 错误异常一律 4 级分类
- 不实际发飞书消息到生产 chat_id（测试 mock）
- 全程 retry_with_backoff 包裹 LLM 调用

复用清单：
- pm_db_api — 拉 Project / Task / PRD 摘要
- adr_storage.list_reviews / list_adrs — 拉 BLOCKING 待处理
- review_code.find_stale_blocking_reviews — 24h 扫描
- review_code.build_appeal_card — BLOCKING 即时推送卡片复用
- legion_api.discover_online_commanders — 找 commander mtime
- feishu_api.send_text_to_chat / send_card_message — 飞书发送
- error_classifier — 4 级分类 + 升级
- design_tech_plan._invoke_llm / _extract_content — LLM 摘要

参考：
- .planning/phase1/specs/REQUIREMENTS.md §1.6 R-FN-5.x
- .planning/phase1/recon/PRD-CAPABILITIES.md 能力 5
- .dispatch/inbox/pm-clarification-20250425-1505.md R-OPEN-7（UTC+8）
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import (
    adr_storage,
    design_tech_plan,
    error_classifier,
    feishu_api,
    legion_api,
    pm_db_api,
    review_code,
)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ALLOWED_TRIGGERS: set = {"scheduled", "blocking_push", "stale_alert", "manual"}

# 30 秒可读 ≈ 500 字（中文）；LLM prompt 硬约束此上限
SUMMARY_MAX_CHARS: int = 500

# 二次催促间隔（单位：小时）— 第一次扫描 stale_hours=24，第二次 +24（即 48h）
STALE_RECHECK_HOURS: float = 48.0

# UTC+8 时区（PM R-OPEN-7 默认）
TZ_UTC8 = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 异常类（继承 WrappedToolError，防 B-1 第六轮）
# ---------------------------------------------------------------------------


class _DailyBriefError(error_classifier.WrappedToolError):
    """本模块专用异常，继承 WrappedToolError 让 retry_with_backoff 走 .level 短路。

    防 B-1（第六轮固化）：照 design_tech_plan / breakdown_tasks /
    dispatch_balanced / kickoff_project / review_code 修复方案，继承
    WrappedToolError 让 retry 走 level 短路 → 技术级正常 3 次重试。
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
    """daily_brief 主入口（4 触发分流）。

    返回 JSON 字符串（与其他 AICTO 工具风格一致），所有错误用 4 级分类。
    """
    started_at = time.monotonic()
    args = args or {}

    trigger = (args.get("trigger") or "scheduled").strip().lower()
    if trigger not in ALLOWED_TRIGGERS:
        return _fail(
            f"unknown trigger {trigger!r}; allowed: "
            f"{', '.join(sorted(ALLOWED_TRIGGERS))}",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    target_chat_id = (
        (args.get("target_chat_id") or "").strip()
        or os.environ.get("AICTO_FEISHU_CHAT_ID", "").strip()
    )

    try:
        if trigger == "scheduled":
            return _run_scheduled(
                args=args,
                target_chat_id=target_chat_id,
                started_at=started_at,
            )
        if trigger == "manual":
            return _run_manual(
                args=args,
                target_chat_id=target_chat_id,
                started_at=started_at,
            )
        if trigger == "blocking_push":
            return _run_blocking_push(
                args=args,
                target_chat_id=target_chat_id,
                started_at=started_at,
            )
        if trigger == "stale_alert":
            return _run_stale_alert(
                args=args,
                target_chat_id=target_chat_id,
                started_at=started_at,
            )
    except _DailyBriefError as e:
        if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                e.level, e, {"phase": f"daily_brief.{trigger}", "args_summary": _summarize_args(args)}
            )
        return _fail(
            f"daily_brief.{trigger}: {e}",
            level=e.level,
            elapsed=time.monotonic() - started_at,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        error_classifier.escalate_to_owner(
            level, e, {"phase": f"daily_brief.{trigger}", "args_summary": _summarize_args(args)}
        )
        return _fail(
            f"daily_brief.{trigger}: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    # 防御性：不应到达
    return _fail(
        "internal: trigger dispatch fell through",
        level=error_classifier.LEVEL_UNKNOWN,
        elapsed=time.monotonic() - started_at,
    )


# ---------------------------------------------------------------------------
# trigger="scheduled" / "manual"
# ---------------------------------------------------------------------------


def _run_scheduled(
    *,
    args: Dict[str, Any],
    target_chat_id: str,
    started_at: float,
) -> str:
    """每日 18:00 路径：扫所有 active project + LLM 概括 + 飞书 send_text。"""
    return _build_and_send_brief(
        args=args,
        target_chat_id=target_chat_id,
        started_at=started_at,
        trigger="scheduled",
        is_makeup=bool(args.get("_makeup")),
    )


def _run_manual(
    *,
    args: Dict[str, Any],
    target_chat_id: str,
    started_at: float,
) -> str:
    """trigger=manual：直接执行 scheduled 路径但不写 last_brief_run.json。"""
    return _build_and_send_brief(
        args=args,
        target_chat_id=target_chat_id,
        started_at=started_at,
        trigger="manual",
        is_makeup=False,
    )


def _build_and_send_brief(
    *,
    args: Dict[str, Any],
    target_chat_id: str,
    started_at: float,
    trigger: str,
    is_makeup: bool,
) -> str:
    """scheduled / manual 共享路径：扫数据 → LLM 概括 → 飞书 send_text。"""
    # 1. 拉数据
    stats, projects, blocked_reviews, stale_legions = _collect_status_snapshot()

    # 2. LLM 30 秒概括（≤500 字）
    summary_text = _llm_summarize(
        projects=projects,
        blocked_reviews=blocked_reviews,
        stale_legions=stale_legions,
        stats=stats,
        is_makeup=is_makeup,
    )

    # 3. 飞书 send_text_to_chat
    message_id: Optional[str] = None
    send_error: Optional[str] = None
    if not target_chat_id:
        send_error = "AICTO_FEISHU_CHAT_ID env not set; brief not sent"
    else:
        try:
            send_result = feishu_api.send_text_to_chat(target_chat_id, summary_text)
            # send_text_to_chat 当前实现返回 None；message_id 不可恢复，留 None
            if isinstance(send_result, dict):
                message_id = send_result.get("message_id") or (
                    (send_result.get("data") or {}).get("message_id")
                )
        except Exception as e:  # noqa: BLE001
            send_error = f"{type(e).__name__}: {e}"

    elapsed = time.monotonic() - started_at
    return _success(
        {
            "trigger": trigger,
            "is_makeup": is_makeup,
            "message_id": message_id,
            "summary_text": summary_text,
            "stats": stats,
            "send_error": send_error,
            "elapsed_seconds": round(elapsed, 2),
        }
    )


def _collect_status_snapshot() -> Tuple[
    Dict[str, int], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]
]:
    """扫 ProdMind dev.db + adr_storage + 军团 mtime，构造概括用快照。

    Returns:
        (stats, projects, blocked_reviews, stale_legions)
    """
    projects = _list_active_projects()
    blocked_reviews = _list_blocking_reviews()
    stale_legions = _list_stale_legions()
    today_completed = _count_today_completed_tasks()

    stats = {
        "active_projects": len(projects),
        "blocked_prs": len(blocked_reviews),
        "stale_legions": len(stale_legions),
        "today_completed_tasks": today_completed,
    }
    return stats, projects, blocked_reviews, stale_legions


def _list_active_projects() -> List[Dict[str, Any]]:
    """ProdMind Project 表 status != 'archived' 的 project 列表（best-effort）。"""
    try:
        uri = f"file:{pm_db_api.PRODMIND_DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='Project'"
            ).fetchone()
            if tbl is None:
                return []
            rows = conn.execute(
                'SELECT "id", "name", "status", "updatedAt" FROM "Project" '
                'WHERE "status" IS NULL OR "status" != ? '
                'ORDER BY "updatedAt" DESC LIMIT 20',
                ("archived",),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def _list_blocking_reviews() -> List[Dict[str, Any]]:
    """所有 blocker_count>0 且 appeal_status='none' 的 CodeReview 行。"""
    try:
        return review_code.find_stale_blocking_reviews(stale_hours=0.0)
    except Exception:  # noqa: BLE001
        return []


def _list_stale_legions() -> List[Dict[str, Any]]:
    """找 24h 未进展的军团（基于 inbox 文件 mtime / discover commander started_at）。

    Phase 1 best-effort：
      - 拉 discover_online_commanders
      - 对 inbox_path 文件取 mtime
      - 若 (now - mtime) > 24h → stale
    """
    try:
        commanders = legion_api.discover_online_commanders()
    except Exception:  # noqa: BLE001
        return []

    threshold = time.time() - 24 * 3600
    stale: List[Dict[str, Any]] = []
    for c in commanders:
        inbox = c.inbox_path
        try:
            mtime = inbox.stat().st_mtime if inbox.exists() else 0.0
        except OSError:
            mtime = 0.0
        if mtime and mtime < threshold:
            stale.append(
                {
                    "commander_id": c.commander_id,
                    "legion_project": c.legion_project,
                    "legion_hash": c.legion_hash,
                    "inbox_path": str(inbox),
                    "inbox_mtime_age_hours": round((time.time() - mtime) / 3600, 1),
                    "tmux_alive": c.tmux_alive,
                }
            )
    return stale


def _count_today_completed_tasks() -> int:
    """ProdMind Task 表今日 completedAt（UTC+8 当天）的计数（best-effort）。"""
    try:
        uri = f"file:{pm_db_api.PRODMIND_DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='Task'"
            ).fetchone()
            if tbl is None:
                return 0
            today_utc8_start = (
                datetime.now(TZ_UTC8).replace(hour=0, minute=0, second=0, microsecond=0)
            )
            today_utc = today_utc8_start.astimezone(timezone.utc)
            cur = conn.execute(
                'SELECT COUNT(*) AS cnt FROM "Task" '
                'WHERE "status" = ? AND "completedAt" >= ?',
                ("completed", today_utc.isoformat()),
            )
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _llm_summarize(
    *,
    projects: List[Dict[str, Any]],
    blocked_reviews: List[Dict[str, Any]],
    stale_legions: List[Dict[str, Any]],
    stats: Dict[str, int],
    is_makeup: bool,
) -> str:
    """LLM 30 秒概括（≤500 字 飞书消息）。

    LLM 失败 → fallback 到结构化 fallback 文本（不抛，避免 cron 死循环）。
    """
    # 构造 prompt
    proj_lines = [
        f"  - {p.get('name') or p.get('id')}({(p.get('status') or '?')})"
        for p in projects[:10]
    ]
    block_lines = [
        f"  - {(b.get('pr_url') or '?')[:80]} BLOCKING={b.get('blocker_count')}"
        for b in blocked_reviews[:5]
    ]
    stale_lines = [
        f"  - {s['commander_id']} ({s['legion_project']}) 停滞 {s['inbox_mtime_age_hours']}h"
        for s in stale_legions[:5]
    ]

    user_msg = (
        ("【补发】" if is_makeup else "")
        + "请你（程小远，AI CTO）用中文写一条「30 秒掌握全部」的飞书日报。\n\n"
        f"统计：{json.dumps(stats, ensure_ascii=False)}\n\n"
        f"在线项目（前 10）:\n{chr(10).join(proj_lines) or '  （无）'}\n\n"
        f"未处理 BLOCKING（前 5）:\n{chr(10).join(block_lines) or '  （无）'}\n\n"
        f"停滞军团（前 5）:\n{chr(10).join(stale_lines) or '  （无）'}\n\n"
        f"严格要求：\n"
        f"  - 总长度 ≤{SUMMARY_MAX_CHARS} 字（中文计），便于 30 秒读完\n"
        "  - 不要 markdown 围栏、不要标题层级；用项目编号 / 行内强调即可\n"
        "  - 顺序：① 总览一句话 ② 待你介入 ③ 进度亮点 ④ 风险提醒\n"
        "  - 输出纯文本，不要 JSON 包装\n"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是程小远，云智 OPC 团队的 AI CTO。每日 18:00 给骏飞推送 30 秒可读的"
                "项目日报，必须高度概括、措辞精准、无废话。"
            ),
        },
        {"role": "user", "content": user_msg},
    ]

    def _do_call() -> str:
        try:
            response = design_tech_plan._invoke_llm(messages)
            content = design_tech_plan._extract_content(response)
        except design_tech_plan._DesignTechPlanError as e:
            raise _DailyBriefError(str(e), level=e.level)
        if not content or not content.strip():
            raise _DailyBriefError(
                "LLM returned empty content for daily brief",
                level=error_classifier.LEVEL_TECH,
            )
        return content.strip()

    try:
        text = error_classifier.retry_with_backoff(
            _do_call, max_retries=3, base_delay=2.0
        )
    except Exception as e:  # noqa: BLE001
        # LLM 重伤 → 升级 + fallback 文本（不抛，daily_brief 必须出消息）
        try:
            error_classifier.escalate_to_owner(
                error_classifier.classify(e),
                e,
                {"phase": "daily_brief.llm_summarize"},
            )
        except Exception:  # noqa: BLE001
            pass
        text = _fallback_summary_text(
            projects=projects,
            blocked_reviews=blocked_reviews,
            stale_legions=stale_legions,
            stats=stats,
            is_makeup=is_makeup,
        )

    # 长度兜底 — LLM 偶尔会超
    if len(text) > SUMMARY_MAX_CHARS:
        suffix = "...（截）"
        text = text[: SUMMARY_MAX_CHARS - len(suffix)].rstrip() + suffix
    return text


def _fallback_summary_text(
    *,
    projects: List[Dict[str, Any]],
    blocked_reviews: List[Dict[str, Any]],
    stale_legions: List[Dict[str, Any]],
    stats: Dict[str, int],
    is_makeup: bool,
) -> str:
    """LLM 失败兜底：结构化文本（≤500 字）。"""
    prefix = "【补发】" if is_makeup else ""
    parts = [
        f"{prefix}程小远日报｜{stats['active_projects']} 活动 / "
        f"{stats['blocked_prs']} BLOCKING / {stats['stale_legions']} 停滞 / "
        f"{stats['today_completed_tasks']} 今日完成。"
    ]
    if blocked_reviews:
        parts.append(
            f"待你介入：{len(blocked_reviews)} 条 BLOCKING 未处理，"
            f"首条：{(blocked_reviews[0].get('pr_url') or '?')[:60]}"
        )
    if stale_legions:
        first = stale_legions[0]
        parts.append(
            f"停滞军团：{first['commander_id']}（{first['inbox_mtime_age_hours']}h）"
        )
    text = " ".join(parts)
    if len(text) > SUMMARY_MAX_CHARS:
        suffix = "...（截）"
        text = text[: SUMMARY_MAX_CHARS - len(suffix)].rstrip() + suffix
    return text


# ---------------------------------------------------------------------------
# trigger="blocking_push"
# ---------------------------------------------------------------------------


def _run_blocking_push(
    *,
    args: Dict[str, Any],
    target_chat_id: str,
    started_at: float,
) -> str:
    """review_code 输出 hook：即时推送 BLOCKING 卡片（≤10s 延迟）。

    args 必填：
      - code_review_id（用于反查 review row）
      - pr_url（卡片 header）
      - blocking_summary（可选，summary 文案）
    """
    code_review_id = args.get("code_review_id")
    pr_url = args.get("pr_url")
    if not pr_url:
        raise _DailyBriefError(
            "blocking_push 需要 pr_url",
            level=error_classifier.LEVEL_INTENT,
        )

    # 拉 review 行（best-effort 反查 checklist + blocking_count）
    review_row: Optional[Dict[str, Any]] = None
    if code_review_id:
        try:
            review_row = _fetch_code_review(code_review_id)
        except Exception:  # noqa: BLE001
            review_row = None

    checklist: List[Dict[str, Any]] = []
    blocking_count = 0
    pr_number = ""
    pr_title = args.get("pr_title") or ""

    if review_row:
        checklist = review_row.get("checklist") or []
        blocking_count = int(review_row.get("blocker_count") or 0)
        # 从 pr_url 反推 number
        pr_number = _extract_pr_number(review_row.get("pr_url") or pr_url) or ""
    else:
        pr_number = _extract_pr_number(pr_url) or ""
        # 没有 review row → 构造极简 checklist 让 build_appeal_card 不崩
        blocking_summary = args.get("blocking_summary") or "review 行不可读，详情未知"
        checklist = [
            {
                "item": 0,
                "name": "未知",
                "status": "BLOCKING",
                "comment": str(blocking_summary)[:300],
            }
        ]
        blocking_count = 1

    card = review_code.build_appeal_card(
        pr_url=pr_url,
        pr_number=pr_number,
        pr_title=pr_title,
        checklist=checklist,
        blocking_count=blocking_count,
        code_review_id=code_review_id,
    )

    message_id: Optional[str] = None
    send_error: Optional[str] = None
    if not target_chat_id:
        send_error = "AICTO_FEISHU_CHAT_ID env not set; blocking card not sent"
    else:
        try:
            send_result = feishu_api.send_card_message(target_chat_id, card)
            if isinstance(send_result, dict):
                message_id = send_result.get("message_id") or (
                    (send_result.get("data") or {}).get("message_id")
                )
        except Exception as e:  # noqa: BLE001
            send_error = f"{type(e).__name__}: {e}"

    elapsed = time.monotonic() - started_at
    return _success(
        {
            "trigger": "blocking_push",
            "message_id": message_id,
            "code_review_id": code_review_id,
            "pr_url": pr_url,
            "blocking_count": blocking_count,
            "send_error": send_error,
            "elapsed_seconds": round(elapsed, 2),
        }
    )


def _fetch_code_review(code_review_id: str) -> Optional[Dict[str, Any]]:
    """从 CodeReview 表反查一行（adr_storage 没暴露 get_review，直查）。

    与 review_code._fetch_code_review 等价（避免 cross-import 私有函数）。
    """
    try:
        # fix W-2 reviewer-p1-7：用 mode=ro 只读 URI，与 _list_active_projects / _count_today_completed_tasks 一致
        conn = sqlite3.connect(
            f"file:{adr_storage.PRODMIND_DB_PATH}?mode=ro", uri=True
        )
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                'SELECT * FROM "CodeReview" WHERE "id" = ?', (code_review_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            raw = d.get("checklist_json")
            if raw:
                try:
                    d["checklist"] = json.loads(raw)
                except (TypeError, ValueError):
                    d["checklist"] = None
            else:
                d["checklist"] = None
            return d
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _extract_pr_number(pr_url: str) -> str:
    """从 pr_url 反推 number（GitHub URL 末段 /pull/<n>）。"""
    if not pr_url:
        return ""
    parts = pr_url.rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "pull":
        return parts[-1]
    return ""


# ---------------------------------------------------------------------------
# trigger="stale_alert"
# ---------------------------------------------------------------------------


def _run_stale_alert(
    *,
    args: Dict[str, Any],
    target_chat_id: str,
    started_at: float,
) -> str:
    """24h 未进展催促：扫 stale_legions + stale BLOCKING reviews → @对应 commander。

    二次催促失败（再 24h，total 48h）→ escalate_to_owner @张骏飞。
    """
    # 24h 一次催促
    stale_legions = _list_stale_legions()
    stale_reviews = []
    try:
        stale_reviews = review_code.find_stale_blocking_reviews(stale_hours=24.0)
    except Exception:  # noqa: BLE001
        stale_reviews = []

    # 48h 二次催促（升级骏飞）
    super_stale_legions = [
        s for s in stale_legions if s.get("inbox_mtime_age_hours", 0) >= STALE_RECHECK_HOURS
    ]
    super_stale_reviews: List[Dict[str, Any]] = []
    try:
        super_stale_reviews = review_code.find_stale_blocking_reviews(
            stale_hours=STALE_RECHECK_HOURS
        )
    except Exception:  # noqa: BLE001
        super_stale_reviews = []

    notifications: List[Dict[str, Any]] = []
    escalations: List[Dict[str, Any]] = []

    # 1. 24h 催促：发飞书 @对应 commander（仅文本提示，不 escalate）
    for s in stale_legions:
        # fix W-1 reviewer-p1-7：跳过已在 super_stale_legions 中的（避免重复 24h 催促后再 48h 升级，与 stale_reviews 模式对齐）
        if any(sl["commander_id"] == s["commander_id"] for sl in super_stale_legions):
            continue
        text = _build_stale_legion_text(s, super_stale=False)
        nt = _try_send_text(target_chat_id, text)
        nt["target"] = "stale_legion"
        nt["commander_id"] = s["commander_id"]
        notifications.append(nt)
    for r in stale_reviews:
        # 跳过已在 super_stale_reviews 中的（避免重复 24h 提示后再 48h 升级）
        if any(sr.get("id") == r.get("id") for sr in super_stale_reviews):
            continue
        text = _build_stale_review_text(r, super_stale=False)
        nt = _try_send_text(target_chat_id, text)
        nt["target"] = "stale_review"
        nt["code_review_id"] = r.get("id")
        notifications.append(nt)

    # 2. 48h 二次催促失败 → escalate
    for s in super_stale_legions:
        try:
            res = error_classifier.escalate_to_owner(
                error_classifier.LEVEL_UNKNOWN,
                f"军团 {s['commander_id']}（{s['legion_project']}）"
                f"停滞 {s['inbox_mtime_age_hours']}h（≥48h），二次催促未响应。",
                {
                    "phase": "daily_brief.stale_alert.super_stale_legion",
                    "commander_id": s["commander_id"],
                    "legion_project": s["legion_project"],
                    "inbox_path": s["inbox_path"],
                    "age_hours": s["inbox_mtime_age_hours"],
                },
            )
            escalations.append({"target": "stale_legion", "commander_id": s["commander_id"], "result": res})
        except Exception as e:  # noqa: BLE001
            escalations.append(
                {"target": "stale_legion", "commander_id": s["commander_id"], "error": str(e)}
            )

    for r in super_stale_reviews:
        try:
            res = error_classifier.escalate_to_owner(
                error_classifier.LEVEL_UNKNOWN,
                f"BLOCKING PR {r.get('pr_url')} 已 ≥48h 未处理，"
                f"军团忽略 BLOCKING = 执行纪律违规（R-FN-4.6）。",
                {
                    "phase": "daily_brief.stale_alert.super_stale_review",
                    "code_review_id": r.get("id"),
                    "pr_url": r.get("pr_url"),
                    "blocker_count": r.get("blocker_count"),
                    "reviewed_at": r.get("reviewed_at"),
                },
            )
            escalations.append({"target": "stale_review", "code_review_id": r.get("id"), "result": res})
        except Exception as e:  # noqa: BLE001
            escalations.append(
                {"target": "stale_review", "code_review_id": r.get("id"), "error": str(e)}
            )

    elapsed = time.monotonic() - started_at
    return _success(
        {
            "trigger": "stale_alert",
            "stale_legions_count": len(stale_legions),
            "stale_reviews_count": len(stale_reviews),
            "super_stale_legions_count": len(super_stale_legions),
            "super_stale_reviews_count": len(super_stale_reviews),
            "notifications": notifications,
            "escalations": escalations,
            "elapsed_seconds": round(elapsed, 2),
        }
    )


def _build_stale_legion_text(s: Dict[str, Any], *, super_stale: bool) -> str:
    """构造 stale 军团催促飞书文案（含 @at 标签）。"""
    cid = s.get("commander_id") or "?"
    proj = s.get("legion_project") or "?"
    age = s.get("inbox_mtime_age_hours", 0)
    head = "【二次催促 / 即将升级】" if super_stale else "【24h 催促】"
    return (
        f"{head} 军团 {cid}（项目 {proj}）"
        f"已停滞 {age}h（inbox 文件无更新）。请尽快处理或回报状态。"
    )


def _build_stale_review_text(r: Dict[str, Any], *, super_stale: bool) -> str:
    """构造 stale BLOCKING review 催促飞书文案。"""
    pr_url = r.get("pr_url") or "?"
    n_block = r.get("blocker_count") or 0
    head = "【二次催促 / 即将升级】" if super_stale else "【24h 催促】"
    return (
        f"{head} PR {pr_url} 还有 {n_block} 项 BLOCKING 未处理（appeal_status=none）。"
        "请军团及时 retract / appeal / 修复，否则将升级骏飞仲裁。"
    )


def _try_send_text(chat_id: str, text: str) -> Dict[str, Any]:
    """best-effort 发文本飞书消息；失败返 {sent_via_feishu: False, error: ...}。"""
    if not chat_id:
        return {"sent_via_feishu": False, "error": "chat_id empty"}
    try:
        feishu_api.send_text_to_chat(chat_id, text)
        return {"sent_via_feishu": True, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"sent_via_feishu": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 公共辅助（与其他工具风格一致）
# ---------------------------------------------------------------------------


def _summarize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """脱敏 args（去掉巨大字段，便于错误上下文）。"""
    if not isinstance(args, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "...（截断）"
        else:
            out[k] = v
    return out


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
    "ALLOWED_TRIGGERS",
    "SUMMARY_MAX_CHARS",
    "STALE_RECHECK_HOURS",
    "TZ_UTC8",
    "_DailyBriefError",
]
