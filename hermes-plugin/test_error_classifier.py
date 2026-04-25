"""error_classifier 单元测试 — 覆盖 4 级分类 + 重试 + 升级。

运行：
    cd ~/Documents/AICTO/hermes-plugin
    python -m unittest test_error_classifier -v
或：
    python test_error_classifier.py
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import error_classifier as ec
from error_classifier import (
    LEVEL_INTENT,
    LEVEL_PERMISSION,
    LEVEL_TECH,
    LEVEL_UNKNOWN,
    WrappedToolError,
    classify,
    escalate_to_owner,
    give_options_to_pm,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# Test infrastructure: redirect escalation log to a temp file per test
# ---------------------------------------------------------------------------

class _LogRedirectMixin:
    """Redirect ec._ESCALATION_LOG_PATH to a per-test temp file."""

    def setUp(self) -> None:  # type: ignore[override]
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_log_path = ec._ESCALATION_LOG_PATH
        ec._ESCALATION_LOG_PATH = Path(self._tmpdir.name) / "escalation.log"

    def tearDown(self) -> None:  # type: ignore[override]
        ec._ESCALATION_LOG_PATH = self._original_log_path
        self._tmpdir.cleanup()


# ---------------------------------------------------------------------------
# classify — 4 级分类
# ---------------------------------------------------------------------------

class TestClassifyTech(unittest.TestCase):
    """技术级（≥2 case 必覆盖）"""

    def test_connection_error_type(self):
        self.assertEqual(classify(ConnectionError("network down")), LEVEL_TECH)

    def test_timeout_error_type(self):
        self.assertEqual(classify(TimeoutError("read timeout")), LEVEL_TECH)

    def test_http_503_string(self):
        self.assertEqual(classify("HTTP 503 Service Unavailable"), LEVEL_TECH)

    def test_rate_limit_429(self):
        self.assertEqual(classify("rate limit 429"), LEVEL_TECH)

    def test_database_locked(self):
        self.assertEqual(classify("database is locked"), LEVEL_TECH)

    def test_timeout_lowercased_match(self):
        self.assertEqual(classify("Operation Timeout after 30s"), LEVEL_TECH)

    def test_500_internal_server(self):
        self.assertEqual(classify("500 Internal Server Error"), LEVEL_TECH)

    def test_llm_context_window(self):
        self.assertEqual(classify("context length exceeded"), LEVEL_TECH)


class TestClassifyPermission(unittest.TestCase):
    """权限级（≥2 case 必覆盖）"""

    def test_readonly_database(self):
        self.assertEqual(
            classify("attempt to write a readonly database"),
            LEVEL_PERMISSION,
        )

    def test_403_forbidden(self):
        self.assertEqual(classify("403 Forbidden"), LEVEL_PERMISSION)

    def test_feishu_app_lock(self):
        self.assertEqual(classify("feishu_app_lock failed"), LEVEL_PERMISSION)

    def test_git_push_rejected(self):
        self.assertEqual(
            classify("git push rejected: non-fast-forward"),
            LEVEL_PERMISSION,
        )

    def test_unauthorized_401(self):
        self.assertEqual(classify("401 Unauthorized"), LEVEL_PERMISSION)


class TestClassifyIntent(unittest.TestCase):
    """意图级（≥2 case 必覆盖）"""

    def test_chinese_unable_to_judge(self):
        self.assertEqual(classify("我无法判断这个 PRD"), LEVEL_INTENT)

    def test_unique_constraint(self):
        self.assertEqual(classify("UNIQUE constraint failed"), LEVEL_INTENT)

    def test_required_field_missing(self):
        self.assertEqual(classify("required field missing: prd_id"), LEVEL_INTENT)

    def test_foreign_key(self):
        self.assertEqual(
            classify("FOREIGN KEY constraint violation on adr.project_id"),
            LEVEL_INTENT,
        )

    def test_validation_error(self):
        self.assertEqual(classify("validation error: type mismatch"), LEVEL_INTENT)


class TestClassifyUnknown(unittest.TestCase):
    """未知级（≥2 case 必覆盖）"""

    def test_exotic_message(self):
        self.assertEqual(classify("unexpected exotic error"), LEVEL_UNKNOWN)

    def test_empty_string(self):
        self.assertEqual(classify(""), LEVEL_UNKNOWN)

    def test_none_keywords_in_random_runtime_error(self):
        self.assertEqual(classify(RuntimeError("something weird")), LEVEL_UNKNOWN)


# ---------------------------------------------------------------------------
# classify — 优先级裁剪（多级命中时取最保守一级）
# ---------------------------------------------------------------------------

class TestClassifyPriority(unittest.TestCase):

    def test_tech_and_permission_picks_permission(self):
        # 同时含 tech("503") 和 permission("forbidden")
        self.assertEqual(
            classify("HTTP 503 forbidden by upstream policy"),
            LEVEL_PERMISSION,
        )

    def test_permission_and_intent_picks_intent(self):
        # 同时含 permission("403") 和 intent("我无法")
        self.assertEqual(
            classify("403 我无法判断"),
            LEVEL_INTENT,
        )

    def test_wrapped_tool_error_passthrough(self):
        e = WrappedToolError("custom failure", level=LEVEL_PERMISSION)
        self.assertEqual(classify(e), LEVEL_PERMISSION)

    def test_wrapped_tool_error_default_unknown(self):
        e = WrappedToolError("oops")
        self.assertEqual(classify(e), LEVEL_UNKNOWN)


# ---------------------------------------------------------------------------
# retry_with_backoff
# ---------------------------------------------------------------------------

class TestRetryWithBackoff(unittest.TestCase):

    def test_success_on_first_try(self):
        calls = []

        def f():
            calls.append(1)
            return "ok"

        self.assertEqual(retry_with_backoff(f, max_retries=3, base_delay=0.001), "ok")
        self.assertEqual(len(calls), 1)

    def test_retry_then_success(self):
        calls = []

        def f():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("network down")
            return "ok"

        self.assertEqual(retry_with_backoff(f, max_retries=3, base_delay=0.001), "ok")
        self.assertEqual(len(calls), 3)

    def test_exhausted_raises_wrapped_unknown(self):
        def f():
            raise ConnectionError("still down")

        with self.assertRaises(WrappedToolError) as cm:
            retry_with_backoff(f, max_retries=3, base_delay=0.001)
        self.assertEqual(cm.exception.level, LEVEL_UNKNOWN)
        self.assertIsInstance(cm.exception.original, ConnectionError)

    def test_non_tech_error_does_not_retry(self):
        calls = []

        def f():
            calls.append(1)
            raise PermissionError("403 Forbidden")

        with self.assertRaises(PermissionError):
            retry_with_backoff(f, max_retries=3, base_delay=0.001)
        # PermissionError 是 permission 级 → 不重试
        self.assertEqual(len(calls), 1)

    def test_intent_error_does_not_retry(self):
        calls = []

        def f():
            calls.append(1)
            raise ValueError("UNIQUE constraint failed")

        with self.assertRaises(ValueError):
            retry_with_backoff(f, max_retries=3, base_delay=0.001)
        self.assertEqual(len(calls), 1)

    def test_wrapped_tech_retried(self):
        calls = []

        def f():
            calls.append(1)
            if len(calls) < 2:
                raise WrappedToolError("transient", level=LEVEL_TECH)
            return "ok"

        self.assertEqual(retry_with_backoff(f, max_retries=3, base_delay=0.001), "ok")
        self.assertEqual(len(calls), 2)

    def test_wrapped_permission_not_retried(self):
        calls = []

        def f():
            calls.append(1)
            raise WrappedToolError("nope", level=LEVEL_PERMISSION)

        with self.assertRaises(WrappedToolError) as cm:
            retry_with_backoff(f, max_retries=3, base_delay=0.001)
        self.assertEqual(cm.exception.level, LEVEL_PERMISSION)
        self.assertEqual(len(calls), 1)

    def test_backoff_sequence_1s_2s(self):
        """Verify exponential backoff: 1s/2s (no sleep after final attempt)."""
        delays = []

        def fake_sleep(d):
            delays.append(d)

        def f():
            raise ConnectionError("x")

        with mock.patch("error_classifier.time.sleep", fake_sleep):
            with self.assertRaises(WrappedToolError):
                retry_with_backoff(f, max_retries=3, base_delay=1.0)
        # 3 次尝试 → 仅在前 2 次失败后 sleep（1s, 2s）
        self.assertEqual(delays, [1.0, 2.0])

    def test_invalid_max_retries(self):
        with self.assertRaises(ValueError):
            retry_with_backoff(lambda: None, max_retries=0)

    def test_invalid_base_delay(self):
        with self.assertRaises(ValueError):
            retry_with_backoff(lambda: None, base_delay=-1)

    def test_passes_args_kwargs(self):
        result = retry_with_backoff(
            lambda a, b, c: a + b + c, 1, 2, c=3, max_retries=1, base_delay=0.001
        )
        self.assertEqual(result, 6)


# ---------------------------------------------------------------------------
# escalate_to_owner / give_options_to_pm — 兜底到本地日志
# ---------------------------------------------------------------------------

class TestEscalateToOwner(_LogRedirectMixin, unittest.TestCase):

    def test_no_chat_id_falls_back_to_log(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = escalate_to_owner(
                LEVEL_PERMISSION,
                "test error",
                {"tool": "kickoff_project"},
            )
        self.assertTrue(result["escalated"])
        self.assertFalse(result["sent_via_feishu"])
        self.assertEqual(result["level"], LEVEL_PERMISSION)
        self.assertTrue(result["log_written"])
        # 验证日志真的写了
        self.assertTrue(ec._ESCALATION_LOG_PATH.exists())
        content = ec._ESCALATION_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn("test error", content)
        self.assertIn("permission", content)

    def test_unknown_level_includes_stack(self):
        try:
            raise RuntimeError("very weird")
        except RuntimeError as e:
            with mock.patch.dict(os.environ, {}, clear=True):
                result = escalate_to_owner(LEVEL_UNKNOWN, e, {})
        self.assertTrue(result["escalated"])
        content = ec._ESCALATION_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn("RuntimeError", content)
        # 未知级应含 stack 字段
        self.assertIn("Stack", content)

    def test_owner_user_id_renders_at_mention(self):
        import json as _json
        with mock.patch.dict(
            os.environ,
            {"AICTO_OWNER_FEISHU_USER_ID": "ou_test123"},
            clear=True,
        ):
            escalate_to_owner(LEVEL_PERMISSION, "x", {})
        line = ec._ESCALATION_LOG_PATH.read_text(encoding="utf-8").strip()
        payload = _json.loads(line)
        self.assertIn('<at user_id="ou_test123">张骏飞</at>', payload["text"])


class TestGiveOptionsToPM(_LogRedirectMixin, unittest.TestCase):

    def test_basic(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = give_options_to_pm(
                "选哪个数据库？",
                ["PostgreSQL", "MySQL", "SQLite"],
                {"prd_id": "p-1"},
            )
        self.assertTrue(result["asked_pm"])
        self.assertEqual(len(result["options"]), 3)
        self.assertFalse(result["sent_via_feishu"])

    def test_too_few_options_raises(self):
        with self.assertRaises(ValueError):
            give_options_to_pm("?", ["only one"])

    def test_empty_question_raises(self):
        with self.assertRaises(ValueError):
            give_options_to_pm("", ["a", "b"])

    def test_options_must_be_list(self):
        with self.assertRaises(ValueError):
            give_options_to_pm("?", "not a list")  # type: ignore


# ---------------------------------------------------------------------------
# 任务验收 contract — team-lead 提供的 8 个断言全跑通
# ---------------------------------------------------------------------------

class TestSpecContract(unittest.TestCase):
    """team-lead 任务书 §验证 给的 8 个核心断言。"""

    def test_spec_tech_assertions(self):
        self.assertEqual(classify(ConnectionError("timeout")), "tech")
        self.assertEqual(classify("HTTP 503"), "tech")
        self.assertEqual(classify("rate limit 429"), "tech")
        self.assertEqual(classify("database is locked"), "tech")

    def test_spec_permission_assertions(self):
        self.assertEqual(
            classify("attempt to write a readonly database"), "permission"
        )
        self.assertEqual(classify("403 Forbidden"), "permission")
        self.assertEqual(classify("feishu_app_lock failed"), "permission")

    def test_spec_intent_assertions(self):
        self.assertEqual(classify("我无法判断"), "intent")
        self.assertEqual(classify("UNIQUE constraint failed"), "intent")
        self.assertEqual(classify("required field missing"), "intent")

    def test_spec_unknown_assertion(self):
        self.assertEqual(classify("unexpected exotic error"), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
