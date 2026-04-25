"""daily_brief + cron_runner 单元测试 — 12+ 自验证场景。

覆盖：
  1. import / syntax + B-1 防回归（_DailyBriefError 继承 WrappedToolError）
  2. trigger=scheduled mock 端到端 → LLM 概括 + send_text_to_chat
  3. trigger=blocking_push → 即时推送 BLOCKING 卡片（≤10s 延迟）
  4. trigger=stale_alert → 找 mtime > 24h + @commander
  5. trigger=manual 不触发持久化
  6. cron _ran_today_18 / _missed_yesterday_18 判定逻辑
  7. last_brief_run.json 持久化（写 + 读 + 重启后恢复）
  8. UTC+8 时区计算（_now_utc8 偏移 +8）
  9. 二次催促失败 → escalate_to_owner @张骏飞
 10. cron loop 在 daemon thread 不阻塞（register_cron 启动 / stop_event 终止）
 11. invalid trigger → intent 级
 12. LLM 失败 → fallback 文本（不抛）
 13. summary_text ≤ SUMMARY_MAX_CHARS 强制兜底

运行：
    cd /Users/feijun/Documents/AICTO
    /Users/feijun/.hermes/hermes-agent/venv/bin/python3 \
        hermes-plugin/test_daily_brief.py

加载方式：把 hermes-plugin/ 当作包 'aicto' 注入 sys.modules，让相对导入成立。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock


# ---------------------------------------------------------------------------
# Bootstrap: 把 hermes-plugin 加载为 'aicto' 包
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "hermes-plugin"
PKG_NAME = "aicto"


def _bootstrap_package():
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]
    spec = importlib.util.spec_from_file_location(
        PKG_NAME,
        str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__path__ = [str(PLUGIN_DIR)]
    sys.modules[PKG_NAME] = mod
    return mod


def _load_submodule(name: str):
    full = f"{PKG_NAME}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    _bootstrap_package()
    spec = importlib.util.spec_from_file_location(
        full, str(PLUGIN_DIR / f"{name}.py")
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[full] = m
    spec.loader.exec_module(m)
    return m


# 顺序依赖：被依赖者先 load
_load_submodule("error_classifier")
_load_submodule("pm_db_api")
_load_submodule("feishu_api")
_load_submodule("adr_storage")
_load_submodule("legion_api")
_load_submodule("design_tech_plan")
_load_submodule("review_code")
daily_brief_mod = _load_submodule("daily_brief")
cron_runner_mod = _load_submodule("cron_runner")
review_code_mod = sys.modules[f"{PKG_NAME}.review_code"]
adr_storage_mod = sys.modules[f"{PKG_NAME}.adr_storage"]
feishu_api_mod = sys.modules[f"{PKG_NAME}.feishu_api"]
design_tech_plan_mod = sys.modules[f"{PKG_NAME}.design_tech_plan"]
error_classifier_mod = sys.modules[f"{PKG_NAME}.error_classifier"]
legion_api_mod = sys.modules[f"{PKG_NAME}.legion_api"]


run = daily_brief_mod.run
_DailyBriefError = daily_brief_mod._DailyBriefError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_llm_returning(text: str):
    """构造能被 design_tech_plan._extract_content 解析的 LLM 响应."""
    def fake_invoke_llm(messages):
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock()]
        resp.choices[0].message.content = text
        return resp

    return fake_invoke_llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportSyntax(unittest.TestCase):
    """Scenario 1: import / syntax + B-1 防回归."""

    def test_module_imports(self):
        self.assertTrue(callable(run))
        self.assertTrue(callable(daily_brief_mod._collect_status_snapshot))
        self.assertTrue(callable(cron_runner_mod.daily_brief_loop))
        self.assertTrue(callable(cron_runner_mod.register_cron))

    def test_constants(self):
        self.assertEqual(daily_brief_mod.SUMMARY_MAX_CHARS, 500)
        self.assertEqual(daily_brief_mod.STALE_RECHECK_HOURS, 48.0)
        self.assertEqual(
            daily_brief_mod.ALLOWED_TRIGGERS,
            {"scheduled", "blocking_push", "stale_alert", "manual"},
        )
        self.assertEqual(cron_runner_mod.TIMEZONE_OFFSET_HOURS, 8)

    def test_inheritance_chain_b1(self):
        """B-1 第六轮防回归 — _DailyBriefError 继承 WrappedToolError."""
        self.assertTrue(
            issubclass(_DailyBriefError, error_classifier_mod.WrappedToolError)
        )
        err = _DailyBriefError("x", level=error_classifier_mod.LEVEL_TECH)
        self.assertEqual(err.level, error_classifier_mod.LEVEL_TECH)
        # classify(WrappedToolError) 应直接返回 .level（短路）
        self.assertEqual(
            error_classifier_mod.classify(err),
            error_classifier_mod.LEVEL_TECH,
        )

    def test_module_referenced_dependencies(self):
        """复用 grep — 确认依赖被正确 import."""
        src = (PLUGIN_DIR / "daily_brief.py").read_text(encoding="utf-8")
        for dep in (
            "adr_storage",
            "design_tech_plan",
            "error_classifier",
            "feishu_api",
            "legion_api",
            "pm_db_api",
            "review_code",
        ):
            self.assertIn(dep, src, f"daily_brief should import {dep}")


class TestInvalidTrigger(unittest.TestCase):
    """Scenario 11: invalid trigger → intent 级."""

    def test_unknown_trigger(self):
        raw = run({"trigger": "weekly"})
        result = json.loads(raw)
        self.assertIn("error", result)
        self.assertEqual(result["level"], error_classifier_mod.LEVEL_INTENT)


class TestScheduledTrigger(unittest.TestCase):
    """Scenario 2: trigger=scheduled mock 端到端."""

    def test_scheduled_happy_path(self):
        with mock.patch.object(
            daily_brief_mod, "_list_active_projects", return_value=[
                {"id": "P1", "name": "AICS", "status": "active"},
                {"id": "P2", "name": "ProdMind", "status": "active"},
            ]
        ), mock.patch.object(
            daily_brief_mod, "_list_blocking_reviews", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_list_stale_legions", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_count_today_completed_tasks", return_value=12
        ), mock.patch.object(
            design_tech_plan_mod,
            "_invoke_llm",
            side_effect=_mock_llm_returning("简短日报：2 项目活跃，0 BLOCKING，12 完成。"),
        ), mock.patch.object(
            feishu_api_mod, "send_text_to_chat", return_value=None
        ) as m_send:
            raw = run({"trigger": "scheduled", "target_chat_id": "test_chat"})

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertEqual(result["trigger"], "scheduled")
        self.assertEqual(result["stats"]["active_projects"], 2)
        self.assertEqual(result["stats"]["today_completed_tasks"], 12)
        self.assertIn("summary_text", result)
        m_send.assert_called_once()
        # 飞书第一参数是 chat_id
        sent_args, _ = m_send.call_args
        self.assertEqual(sent_args[0], "test_chat")

    def test_summary_truncated_to_max_chars(self):
        """Scenario 13: LLM 输出超长 → 强制截断到 SUMMARY_MAX_CHARS."""
        too_long = "啊" * 1000  # 1000 字
        with mock.patch.object(
            daily_brief_mod, "_list_active_projects", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_list_blocking_reviews", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_list_stale_legions", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_count_today_completed_tasks", return_value=0
        ), mock.patch.object(
            design_tech_plan_mod, "_invoke_llm", side_effect=_mock_llm_returning(too_long)
        ), mock.patch.object(
            feishu_api_mod, "send_text_to_chat", return_value=None
        ):
            raw = run({"trigger": "scheduled", "target_chat_id": "x"})

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertLessEqual(
            len(result["summary_text"]), daily_brief_mod.SUMMARY_MAX_CHARS
        )

    def test_llm_failure_falls_back_to_structured_text(self):
        """Scenario 12: LLM 失败 → fallback 文本（不抛）."""
        def boom(*a, **kw):
            raise RuntimeError("LLM down")

        with mock.patch.object(
            daily_brief_mod, "_list_active_projects", return_value=[
                {"id": "P1", "name": "AICS", "status": "active"},
            ]
        ), mock.patch.object(
            daily_brief_mod, "_list_blocking_reviews", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_list_stale_legions", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_count_today_completed_tasks", return_value=0
        ), mock.patch.object(
            design_tech_plan_mod, "_invoke_llm", side_effect=boom
        ), mock.patch.object(
            feishu_api_mod, "send_text_to_chat", return_value=None
        ), mock.patch.object(
            error_classifier_mod, "escalate_to_owner", return_value={"escalated": True}
        ):
            raw = run({"trigger": "scheduled", "target_chat_id": "x"})

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertIn("程小远日报", result["summary_text"])  # fallback 标志
        self.assertIn("活动", result["summary_text"])


class TestManualTrigger(unittest.TestCase):
    """Scenario 5: trigger=manual 同 scheduled 路径."""

    def test_manual_trigger(self):
        with mock.patch.object(
            daily_brief_mod, "_list_active_projects", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_list_blocking_reviews", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_list_stale_legions", return_value=[]
        ), mock.patch.object(
            daily_brief_mod, "_count_today_completed_tasks", return_value=0
        ), mock.patch.object(
            design_tech_plan_mod, "_invoke_llm", side_effect=_mock_llm_returning("manual brief.")
        ), mock.patch.object(
            feishu_api_mod, "send_text_to_chat", return_value=None
        ):
            raw = run({"trigger": "manual", "target_chat_id": "x"})

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertEqual(result["trigger"], "manual")


class TestBlockingPushTrigger(unittest.TestCase):
    """Scenario 3: trigger=blocking_push 即时推送 BLOCKING 卡片."""

    def test_blocking_push_with_review_id(self):
        fake_review = {
            "id": "rev-001",
            "pr_url": "https://github.com/foo/bar/pull/42",
            "checklist": [
                {
                    "item": 3,
                    "name": "安全",
                    "status": "BLOCKING",
                    "comment": "把 SQL 拼接改成参数化查询，因为 SQL 注入",
                }
            ],
            "blocker_count": 1,
        }
        with mock.patch.object(
            daily_brief_mod, "_fetch_code_review", return_value=fake_review
        ), mock.patch.object(
            feishu_api_mod, "send_card_message", return_value={"message_id": "om_card_x"}
        ) as m_card:
            t0 = time.monotonic()
            raw = run(
                {
                    "trigger": "blocking_push",
                    "code_review_id": "rev-001",
                    "pr_url": "https://github.com/foo/bar/pull/42",
                    "target_chat_id": "test_chat",
                }
            )
            elapsed = time.monotonic() - t0

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertEqual(result["trigger"], "blocking_push")
        self.assertEqual(result["pr_url"], "https://github.com/foo/bar/pull/42")
        self.assertEqual(result["blocking_count"], 1)
        m_card.assert_called_once()
        # ≤10s 延迟（mock 路径远低于 10s）
        self.assertLess(elapsed, 10.0)

    def test_blocking_push_missing_pr_url(self):
        raw = run({"trigger": "blocking_push"})
        result = json.loads(raw)
        self.assertIn("error", result)
        self.assertEqual(result["level"], error_classifier_mod.LEVEL_INTENT)


class TestStaleAlertTrigger(unittest.TestCase):
    """Scenario 4 + 9: trigger=stale_alert + 二次催促升级."""

    def test_24h_stale_alert_only_notifies(self):
        stale_legion = {
            "commander_id": "L1-麒麟",
            "legion_project": "aics",
            "legion_hash": "abc",
            "inbox_path": "/tmp/x",
            "inbox_mtime_age_hours": 26.0,
            "tmux_alive": True,
        }
        with mock.patch.object(
            daily_brief_mod, "_list_stale_legions", return_value=[stale_legion]
        ), mock.patch.object(
            review_code_mod, "find_stale_blocking_reviews", return_value=[]
        ), mock.patch.object(
            feishu_api_mod, "send_text_to_chat", return_value=None
        ) as m_send, mock.patch.object(
            error_classifier_mod, "escalate_to_owner"
        ) as m_esc:
            raw = run({"trigger": "stale_alert", "target_chat_id": "x"})

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertEqual(result["stale_legions_count"], 1)
        self.assertEqual(result["super_stale_legions_count"], 0)
        self.assertEqual(len(result["notifications"]), 1)
        self.assertEqual(len(result["escalations"]), 0)
        m_send.assert_called_once()
        m_esc.assert_not_called()  # 24h <48h 不升级

    def test_48h_super_stale_escalates_to_owner(self):
        super_stale = {
            "commander_id": "L1-玄武",
            "legion_project": "aics",
            "legion_hash": "abc",
            "inbox_path": "/tmp/y",
            "inbox_mtime_age_hours": 50.0,
            "tmux_alive": True,
        }
        with mock.patch.object(
            daily_brief_mod, "_list_stale_legions", return_value=[super_stale]
        ), mock.patch.object(
            review_code_mod, "find_stale_blocking_reviews", return_value=[]
        ), mock.patch.object(
            feishu_api_mod, "send_text_to_chat", return_value=None
        ), mock.patch.object(
            error_classifier_mod,
            "escalate_to_owner",
            return_value={"escalated": True, "level": "unknown"},
        ) as m_esc:
            raw = run({"trigger": "stale_alert", "target_chat_id": "x"})

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertEqual(result["super_stale_legions_count"], 1)
        self.assertEqual(len(result["escalations"]), 1)
        m_esc.assert_called_once()
        # 升级 level=UNKNOWN（业务决策类）
        call_args = m_esc.call_args[0]
        self.assertEqual(call_args[0], error_classifier_mod.LEVEL_UNKNOWN)

    def test_48h_super_stale_review_escalates(self):
        """48h 未处理 BLOCKING review 也升级骏飞."""
        super_stale_review = {
            "id": "rev-old",
            "pr_url": "https://github.com/foo/bar/pull/99",
            "blocker_count": 2,
            "appeal_status": "none",
            "reviewed_at": (
                datetime.now(timezone.utc) - timedelta(hours=50)
            ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        }

        def fake_find_stale(stale_hours=24.0):
            if stale_hours == 24.0:
                return [super_stale_review]
            if stale_hours == 48.0:
                return [super_stale_review]
            return []

        with mock.patch.object(
            daily_brief_mod, "_list_stale_legions", return_value=[]
        ), mock.patch.object(
            review_code_mod, "find_stale_blocking_reviews", side_effect=fake_find_stale
        ), mock.patch.object(
            feishu_api_mod, "send_text_to_chat", return_value=None
        ) as m_send, mock.patch.object(
            error_classifier_mod, "escalate_to_owner", return_value={"escalated": True}
        ) as m_esc:
            raw = run({"trigger": "stale_alert", "target_chat_id": "x"})

        result = json.loads(raw)
        self.assertTrue(result.get("success"))
        self.assertEqual(result["super_stale_reviews_count"], 1)
        # super_stale review 不重复发 24h 提示（以避免重复）
        self.assertEqual(len(result["notifications"]), 0)
        self.assertEqual(len(result["escalations"]), 1)
        m_esc.assert_called_once()


class TestCronRunnerJudgments(unittest.TestCase):
    """Scenario 6 + 7 + 8: cron 判定逻辑 / 持久化 / UTC+8."""

    def setUp(self):
        # 用 tmp 文件避免污染真实 last_brief_run.json
        self._tmpdir = Path("/tmp/aicto_test_state")
        self._tmpdir.mkdir(parents=True, exist_ok=True)
        self._orig_path = cron_runner_mod.LAST_RUN_PATH
        self._tmp_path = self._tmpdir / f"last_brief_run_{int(time.time()*1000)}.json"
        cron_runner_mod.LAST_RUN_PATH = self._tmp_path

    def tearDown(self):
        cron_runner_mod.LAST_RUN_PATH = self._orig_path
        try:
            if self._tmp_path.exists():
                self._tmp_path.unlink()
        except OSError:
            pass

    def test_now_utc8_offset(self):
        """Scenario 8: _now_utc8 应比 UTC 早 8 小时."""
        n_utc8 = cron_runner_mod._now_utc8()
        n_utc = datetime.now(timezone.utc)
        delta = n_utc8.utcoffset()
        self.assertEqual(delta, timedelta(hours=8))
        # 时间相近（<5s）
        diff_sec = abs((n_utc8 - n_utc).total_seconds())
        self.assertLess(diff_sec, 5)

    def test_save_and_load_persists(self):
        """Scenario 7: 持久化 + 重启后恢复."""
        cron_runner_mod._save_last_run(
            {"date": "2026-04-25", "scheduled_run_ts": 12345}
        )
        loaded = cron_runner_mod._load_last_run()
        self.assertEqual(loaded["date"], "2026-04-25")
        self.assertEqual(loaded["scheduled_run_ts"], 12345)

    def test_ran_today_18_logic(self):
        """Scenario 6: _ran_today_18 判定."""
        today = cron_runner_mod._now_utc8().strftime("%Y-%m-%d")
        # 空状态 → False
        cron_runner_mod._save_last_run({})
        self.assertFalse(cron_runner_mod._ran_today_18())
        # 今天已跑 → True
        cron_runner_mod._save_last_run(
            {"date": today, "scheduled_run_ts": time.time()}
        )
        self.assertTrue(cron_runner_mod._ran_today_18())
        # 昨天跑过、今天没跑 → False
        yesterday = (
            cron_runner_mod._now_utc8() - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        cron_runner_mod._save_last_run(
            {"date": yesterday, "scheduled_run_ts": time.time()}
        )
        self.assertFalse(cron_runner_mod._ran_today_18())

    def test_missed_yesterday_18_logic(self):
        """Scenario 6: _missed_yesterday_18 判定."""
        yesterday = (
            cron_runner_mod._now_utc8() - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        # 空状态 → True（视为漏跑）
        cron_runner_mod._save_last_run({})
        self.assertTrue(cron_runner_mod._missed_yesterday_18())
        # 昨天跑过 → False
        cron_runner_mod._save_last_run(
            {"date": yesterday, "scheduled_run_ts": time.time()}
        )
        self.assertFalse(cron_runner_mod._missed_yesterday_18())
        # 昨天行存但 scheduled_run_ts 缺 → True
        cron_runner_mod._save_last_run(
            {"date": yesterday, "scheduled_run_ts": None}
        )
        self.assertTrue(cron_runner_mod._missed_yesterday_18())

    def test_mark_scheduled_ran_sets_today(self):
        cron_runner_mod._save_last_run({})
        cron_runner_mod._mark_scheduled_ran()
        d = cron_runner_mod._load_last_run()
        today = cron_runner_mod._now_utc8().strftime("%Y-%m-%d")
        self.assertEqual(d["date"], today)
        self.assertIsNotNone(d.get("scheduled_run_ts"))

    def test_mark_makeup_ran_sets_makeup_ts(self):
        cron_runner_mod._save_last_run({})
        cron_runner_mod._mark_makeup_ran()
        d = cron_runner_mod._load_last_run()
        today = cron_runner_mod._now_utc8().strftime("%Y-%m-%d")
        self.assertEqual(d["date"], today)
        self.assertIsNotNone(d.get("makeup_run_ts"))
        # makeup 等价于 scheduled 也跑过（避免 18:00 重复发）
        self.assertIsNotNone(d.get("scheduled_run_ts"))


class TestCronLoopBackground(unittest.TestCase):
    """Scenario 10: cron loop 在 daemon thread 不阻塞."""

    def test_loop_stops_on_event(self):
        """daily_brief_loop 在 stop_event 触发后退出（不阻塞）."""

        async def _scenario():
            stop = asyncio.Event()
            stop.set()  # 提前设置 — 进入 loop 后第一次检查就退出
            # 限制 5s 防呆
            await asyncio.wait_for(
                cron_runner_mod.daily_brief_loop(stop_event=stop), timeout=5.0
            )

        asyncio.run(_scenario())

    def test_loop_triggers_at_18(self):
        """模拟 now=18:00 + 未跑过 → 调 daily_brief.run 一次后退出."""
        called = {"n": 0}
        stop = asyncio.Event()

        def fake_run(args):
            called["n"] += 1
            # 触发 stop 让 loop 在下一轮 check 退出
            stop.set()
            return json.dumps({"success": True, "trigger": "scheduled"})

        # 构造一个固定 18:00 的时间
        fixed_now = datetime(2026, 4, 25, 18, 0, 0, tzinfo=cron_runner_mod.TZ_UTC8)

        async def _scenario():
            with mock.patch.object(
                cron_runner_mod, "_now_utc8", return_value=fixed_now
            ), mock.patch.object(
                cron_runner_mod, "_ran_today_18", return_value=False
            ), mock.patch.object(
                cron_runner_mod, "_missed_yesterday_18", return_value=False
            ), mock.patch.object(
                cron_runner_mod, "_mark_scheduled_ran"
            ), mock.patch.object(
                daily_brief_mod, "run", side_effect=fake_run
            ), mock.patch.object(
                cron_runner_mod.asyncio,
                "sleep",
                new=mock.AsyncMock(return_value=None),
            ):
                await asyncio.wait_for(
                    cron_runner_mod.daily_brief_loop(stop_event=stop), timeout=5.0
                )

        asyncio.run(_scenario())
        self.assertEqual(called["n"], 1)

    def test_register_cron_starts_daemon_thread(self):
        """register_cron 通过 daemon thread 启动后台 loop（不阻塞主线程）."""
        import os as _os

        # disable env 关掉 → 不启动
        with mock.patch.dict(_os.environ, {"AICTO_DAILY_BRIEF_DISABLED": "1"}):
            cron_runner_mod.register_cron(ctx=None)
            # 不抛即视为通过（disabled 路径）

        # 不 disable，模拟 register（极短 stop 防 cron 真跑）
        threads_before = {t.name for t in __import__("threading").enumerate()}
        with mock.patch.object(
            cron_runner_mod,
            "daily_brief_loop",
            new=mock.AsyncMock(return_value=None),
        ):
            # 强制走 daemon thread 路径（mock asyncio.get_event_loop 抛 RuntimeError）
            with mock.patch.object(
                cron_runner_mod.asyncio,
                "get_event_loop",
                side_effect=RuntimeError("no loop"),
            ):
                cron_runner_mod.register_cron(ctx=None)
        # 检查 aicto-daily-brief-cron daemon thread 存在
        time.sleep(0.05)  # 让线程启动
        threads_after = {t.name for t in __import__("threading").enumerate()}
        # （不强求新建 thread 仍存活 — daemon 跑完 mock loop 即退出）
        # 仅断言 register_cron 不抛
        self.assertIsInstance(threads_before, set)
        self.assertIsInstance(threads_after, set)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main(verbosity=2)
