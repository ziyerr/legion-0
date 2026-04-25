"""cron_runner.py — daily_brief 定时调度（asyncio loop / 后台 thread）。

P1.7：注册到 plugin __init__.py register(ctx) 后启动后台 loop，
每分钟检查时间，到点触发 daily_brief：
  - 18:00 UTC+8 → trigger=scheduled
  - 09:00 UTC+8 且昨天 18:00 漏跑 → trigger=scheduled with [补发] 标记

last_brief_run.json 持久化到
  ~/.hermes/profiles/aicto/plugins/aicto/state/last_brief_run.json
gateway 重启后从此恢复，避免重复发送 / 漏发。

设计纪律：
- 不阻塞主线程（asyncio task 或 daemon thread 都可）
- 日志 / 异常吃掉，避免一次失败导致 cron 死循环 stop
- 测试时 mock asyncio.sleep / _now_utc8 / daily_brief.run
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# UTC+8（PM R-OPEN-7 默认）
TIMEZONE_OFFSET_HOURS: int = 8
TZ_UTC8 = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))

# 持久化路径（gateway 重启后恢复）
LAST_RUN_PATH: Path = (
    Path.home()
    / ".hermes"
    / "profiles"
    / "aicto"
    / "plugins"
    / "aicto"
    / "state"
    / "last_brief_run.json"
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 时区 / 持久化辅助
# ---------------------------------------------------------------------------


def _now_utc8() -> datetime:
    """当前 UTC+8 时间。"""
    return datetime.now(TZ_UTC8)


def _load_last_run() -> dict:
    """读 last_brief_run.json — 返回 {date, scheduled_run_ts, makeup_run_ts}。"""
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LAST_RUN_PATH.exists():
        return {}
    try:
        return json.loads(LAST_RUN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _save_last_run(data: dict) -> None:
    """落盘 last_brief_run.json（覆盖写）。"""
    try:
        LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("save last_brief_run.json failed: %s", e)


def _ran_today_18() -> bool:
    """今天 18:00 是否已经跑过 scheduled brief。"""
    last = _load_last_run()
    today = _now_utc8().strftime("%Y-%m-%d")
    return bool(last.get("date") == today and last.get("scheduled_run_ts"))


def _missed_yesterday_18() -> bool:
    """昨天 18:00 是否漏跑（用于 09:00 补发判定）。

    - last.date != yesterday → 昨天那一行根本没存（漏跑或 gateway 当时离线）
    - last.date == yesterday 但无 scheduled_run_ts → 也算漏跑
    """
    last = _load_last_run()
    yesterday = (_now_utc8() - timedelta(days=1)).strftime("%Y-%m-%d")
    if last.get("date") != yesterday:
        return True
    if not last.get("scheduled_run_ts"):
        return True
    return False


def _mark_scheduled_ran() -> None:
    """标记今天 18:00 已跑过。"""
    today = _now_utc8().strftime("%Y-%m-%d")
    data = _load_last_run()
    # 跨日清理：日期变更则重置
    if data.get("date") != today:
        data = {}
    data["date"] = today
    data["scheduled_run_ts"] = time.time()
    _save_last_run(data)


def _mark_makeup_ran() -> None:
    """标记今天 09:00 已补发过。"""
    today = _now_utc8().strftime("%Y-%m-%d")
    data = _load_last_run()
    if data.get("date") != today:
        data = {}
    data["date"] = today
    data["makeup_run_ts"] = time.time()
    # 补发 = 今天 brief 已出，不再 18:00 重发
    data["scheduled_run_ts"] = data.get("scheduled_run_ts") or time.time()
    _save_last_run(data)


# ---------------------------------------------------------------------------
# Async loop
# ---------------------------------------------------------------------------


async def daily_brief_loop(stop_event: Optional[asyncio.Event] = None) -> None:
    """每分钟检查时间，到点触发 daily_brief。

    18:00 UTC+8                       → trigger=scheduled
    09:00 UTC+8 且昨天 18:00 漏跑       → trigger=scheduled with _makeup=True

    异常一律吃掉（不让 cron 死循环 stop）。
    """
    logger.info("Daily brief cron loop started (UTC+8)")
    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Daily brief cron loop stopping")
            break
        try:
            now = _now_utc8()
            # 18:00 整点（仅在 :00 那一分钟触发；防 60s sleep 错过）
            if now.hour == 18 and now.minute == 0 and not _ran_today_18():
                _trigger_scheduled(makeup=False)
                _mark_scheduled_ran()
            elif now.hour == 9 and now.minute == 0 and _missed_yesterday_18():
                _trigger_scheduled(makeup=True)
                _mark_makeup_ran()
        except Exception as e:  # noqa: BLE001
            logger.exception("daily_brief_loop iteration failed: %s", e)
        await asyncio.sleep(60)


def _trigger_scheduled(*, makeup: bool) -> None:
    """实际调用 daily_brief.run（封一层 try/except，避免 cron stop）。"""
    # 延迟 import 避免 plugin 注册期循环依赖
    from . import daily_brief as db

    args = {"trigger": "scheduled"}
    if makeup:
        args["_makeup"] = True
    logger.info(
        "Triggering daily brief: makeup=%s (UTC+8 %s)",
        makeup,
        _now_utc8().isoformat(),
    )
    try:
        db.run(args)
    except Exception as e:  # noqa: BLE001
        logger.exception("daily_brief.run raised: %s", e)


# ---------------------------------------------------------------------------
# 注册入口（plugin __init__.py register(ctx) 调用）
# ---------------------------------------------------------------------------


def register_cron(ctx: Any = None) -> None:
    """启动后台 daily_brief loop（不阻塞主线程）。

    优先方案：把 loop 注入当前 event loop 作为 task；
    fallback：起 daemon thread 跑独立 event loop（同步初始化期常见）。

    可通过 env AICTO_DAILY_BRIEF_DISABLED=1 关掉（开发环境免打扰）。
    """
    if os.environ.get("AICTO_DAILY_BRIEF_DISABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.info("AICTO_DAILY_BRIEF_DISABLED set; daily_brief cron not started")
        return

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(daily_brief_loop())
            logger.info("daily_brief cron registered as asyncio task")
            return
    except RuntimeError:
        # 没有当前 event loop（极少见 — get_event_loop 在 3.12 起对此场景报错）
        pass

    # Fallback: daemon thread 跑独立 loop
    def _start_loop() -> None:
        try:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(daily_brief_loop())
        except Exception as e:  # noqa: BLE001
            logger.exception("daily_brief cron thread crashed: %s", e)

    t = threading.Thread(
        target=_start_loop, daemon=True, name="aicto-daily-brief-cron"
    )
    t.start()
    logger.info("daily_brief cron registered as daemon thread (tid=%s)", t.ident)


__all__ = [
    "TIMEZONE_OFFSET_HOURS",
    "TZ_UTC8",
    "LAST_RUN_PATH",
    "daily_brief_loop",
    "register_cron",
    "_now_utc8",
    "_load_last_run",
    "_save_last_run",
    "_ran_today_18",
    "_missed_yesterday_18",
    "_mark_scheduled_ran",
    "_mark_makeup_ran",
]
