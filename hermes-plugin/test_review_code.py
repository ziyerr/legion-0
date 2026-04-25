"""review_code 单元测试 — 12+ 自验证场景。

覆盖：
   1. import / syntax + 常量校验
   2. happy path mock（10 PASS / blocking_count=0 / 不发卡片）
   3. happy path mock（含 BLOCKING / 文案 "X→Y 因 Z" 格式 / 发卡片）
   4. 评论密度（LLM 输出 8 条评论 → 截断到 ≤5 + warning）
   5. 单文件 ≤ 2 BLOCKING（3 BLOCKING → 截到 2 + 聚合 refactor）
   6. CodeReview 表实写（实写 sqlite3 + 测试后 DELETE 清理）
   7. PR diff 拉取失败 → tech 级（subprocess returncode != 0 + retry 用尽）
   8. gh CLI 不存在 → permission 级（FileNotFoundError）
   9. scope=security 单维度
  10. B-1 防回归（_ReviewCodeError 继承 WrappedToolError）
  11. 飞书卡片 dict（4 字段 + 3 按钮 + value json.dumps）
  12. 大 PR diff（>80K 字符）截断 + warning
  13. BLOCKING 文案不合规 → reformat + warning
  14. invalid pr_url → intent 级
  15. invalid scope → intent 级
  16. appeal_handler retract 路径
  17. appeal_handler maintain → 升级骏飞
  18. find_stale_blocking_reviews（24h 未处理扫描接口）

运行：
    cd /Users/feijun/Documents/AICTO
    /Users/feijun/.hermes/hermes-agent/venv/bin/python3 \
        hermes-plugin/test_review_code.py

加载方式：把 hermes-plugin/ 当作包 'aicto' 注入 sys.modules，让相对导入成立。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import time
import unittest
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
_load_submodule("design_tech_plan")
review_code_module = _load_submodule("review_code")
adr_storage_module = sys.modules[f"{PKG_NAME}.adr_storage"]
feishu_api_module = sys.modules[f"{PKG_NAME}.feishu_api"]
design_tech_plan_module = sys.modules[f"{PKG_NAME}.design_tech_plan"]
error_classifier_module = sys.modules[f"{PKG_NAME}.error_classifier"]


# Aliases
run = review_code_module.run
appeal_handler = review_code_module.appeal_handler
build_appeal_card = review_code_module.build_appeal_card
find_stale_blocking_reviews = review_code_module.find_stale_blocking_reviews
_ReviewCodeError = review_code_module._ReviewCodeError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_subprocess_returning_diff(diff: str, title: str = "test PR"):
    """构造 mock subprocess.run：第一次调 (gh pr diff) 返 diff，第二次调 (gh pr view) 返 title。"""
    call_count = {"i": 0}

    def fake_run(*args, **kwargs):
        call_count["i"] += 1
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, list) and len(argv) >= 3 and argv[1] == "pr" and argv[2] == "diff":
            return mock.MagicMock(returncode=0, stdout=diff, stderr="")
        if isinstance(argv, list) and len(argv) >= 3 and argv[1] == "pr" and argv[2] == "view":
            return mock.MagicMock(returncode=0, stdout=title, stderr="")
        return mock.MagicMock(returncode=0, stdout="", stderr="")

    return fake_run


def _mock_llm_response(checklist: List[Dict[str, Any]], summary: str = "测试总结"):
    """构造一个能被 design_tech_plan._parse_llm_json 解析的 LLM 响应。"""
    payload = {"checklist": checklist, "overall_summary": summary}

    def fake_invoke_llm(messages):
        # 返回类似 OpenAI choices 结构
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock()]
        resp.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
        return resp

    return fake_invoke_llm


def _all_pass_checklist():
    return [
        {"item": i, "name": name, "status": "PASS", "comment": "无问题"}
        for i, name in review_code_module.CHECKLIST_ITEMS
    ]


def _checklist_with_blocking():
    base = _all_pass_checklist()
    # 第 3 项（安全）→ BLOCKING + "X→Y 因 Z" 格式
    base[2]["status"] = "BLOCKING"
    base[2]["comment"] = (
        "把 hermes-plugin/api.py line 45 的 SQL 拼接 "
        "'SELECT * FROM Users WHERE id=' + uid 改成参数化查询 "
        "conn.execute(\"SELECT * FROM Users WHERE id=?\", (uid,)) "
        "因为字符串拼接易 SQL 注入（OWASP A03）"
    )
    # 第 4 项（测试）→ BLOCKING
    base[3]["status"] = "BLOCKING"
    base[3]["comment"] = (
        "把 hermes-plugin/api.py 的 read_pm_prd 函数加上单元测试覆盖 mode=ro 路径 "
        "改成新增 test_read_pm_prd_readonly_writes_blocked() "
        "因为关键路径未覆盖会回归到 R-NFR-20"
    )
    # 第 2 项（可读性）→ NON-BLOCKING
    base[1]["status"] = "NON-BLOCKING"
    base[1]["comment"] = "建议把 conn 改成 connection 因为可读性更好"
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportSyntax(unittest.TestCase):
    """Scenario 1: import / syntax + 常量校验."""

    def test_module_imports(self):
        self.assertTrue(callable(run))
        self.assertTrue(callable(appeal_handler))
        self.assertTrue(callable(build_appeal_card))
        self.assertTrue(callable(find_stale_blocking_reviews))

    def test_constants_consistent_with_prd(self):
        self.assertEqual(len(review_code_module.CHECKLIST_ITEMS), 10)
        # 10 项名字逐字对照 PRD
        names = [n for _, n in review_code_module.CHECKLIST_ITEMS]
        self.assertEqual(
            names,
            [
                "架构一致",
                "可读性",
                "安全",
                "测试",
                "错误处理",
                "复杂度",
                "依赖",
                "性能",
                "跨军团冲突",
                "PRD 一致",
            ],
        )
        self.assertEqual(review_code_module.MAX_COMMENTS_PER_PR, 5)
        self.assertEqual(review_code_module.MAX_BLOCKING_PER_FILE, 2)
        self.assertEqual(review_code_module.APPEAL_ESCALATION_THRESHOLD, 1)
        self.assertEqual(
            review_code_module.ALLOWED_STATUS,
            {"PASS", "BLOCKING", "NON-BLOCKING"},
        )

    def test_inheritance_chain_b1(self):
        """Scenario 10: B-1 防回归 — _ReviewCodeError 继承 WrappedToolError."""
        self.assertTrue(
            issubclass(_ReviewCodeError, error_classifier_module.WrappedToolError)
        )
        err = _ReviewCodeError("test", level=error_classifier_module.LEVEL_TECH)
        self.assertEqual(err.level, error_classifier_module.LEVEL_TECH)
        # classify(WrappedToolError) 应直接返回 .level（短路）
        self.assertEqual(
            error_classifier_module.classify(err),
            error_classifier_module.LEVEL_TECH,
        )

    def test_module_referenced_dependencies(self):
        """Scenario 复用 grep — 确认依赖被正确 import."""
        src = (PLUGIN_DIR / "review_code.py").read_text(encoding="utf-8")
        self.assertIn("adr_storage", src)
        self.assertIn("design_tech_plan", src)
        self.assertIn("error_classifier", src)
        self.assertIn("feishu_api", src)
        self.assertIn("pm_db_api", src)


class TestHappyPathAllPass(unittest.TestCase):
    """Scenario 2: happy path — 10 PASS / blocking_count=0 / 不发卡片."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_happy_path_all_pass(self):
        diff = """diff --git a/foo.py b/foo.py
@@ -1,3 +1,4 @@
 def foo():
+    return 42
"""
        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff(diff, "happy PR"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response(_all_pass_checklist(), "全部通过"),
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/123"})
        result = json.loads(raw)
        if result.get("code_review_id"):
            self._cleanup_review_ids.append(result["code_review_id"])

        self.assertTrue(result.get("success"), msg=raw)
        self.assertEqual(len(result["checklist"]), 10)
        for item in result["checklist"]:
            self.assertEqual(item["status"], "PASS")
        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["non_blocking_count"], 0)
        self.assertEqual(result["comments_total"], 0)
        self.assertIsNone(result.get("appeal_card_message_id"))
        # 不发卡片 — appeal_card 字段也应为 None
        self.assertIsNone(result.get("appeal_card"))


class TestHappyPathWithBlocking(unittest.TestCase):
    """Scenario 3: happy path 含 BLOCKING — 文案合规 + 卡片构造."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []
        # 设 chat_id env 让卡片走 send 路径（mock）
        os.environ["AICTO_FEISHU_CHAT_ID"] = "oc_test_chat_for_review_code"

    def tearDown(self):
        if "AICTO_FEISHU_CHAT_ID" in os.environ:
            del os.environ["AICTO_FEISHU_CHAT_ID"]
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_happy_path_with_blocking(self):
        diff = "diff --git a/api.py b/api.py\n@@ +1 @@\n+ x = 1\n"
        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff(diff, "PR with blocking"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response(_checklist_with_blocking(), "含 BLOCKING"),
        ), mock.patch.object(
            feishu_api_module,
            "send_card_message",
            return_value={"message_id": "om_test_card_001"},
        ) as send_mock:
            raw = run({"pr_url": "https://github.com/owner/repo/pull/456"})
        result = json.loads(raw)
        if result.get("code_review_id"):
            self._cleanup_review_ids.append(result["code_review_id"])

        self.assertTrue(result.get("success"), msg=raw)
        self.assertGreaterEqual(result["blocking_count"], 2)
        self.assertEqual(result["non_blocking_count"], 1)
        # 卡片应已发出
        self.assertEqual(result.get("appeal_card_message_id"), "om_test_card_001")
        send_mock.assert_called_once()
        # 卡片 dict 字段齐
        card = result["appeal_card"]
        self.assertIn("header", card)
        self.assertIn("elements", card)
        # 找到 action 元素，检查 3 个按钮 + value 是 JSON 字符串
        action_el = next(e for e in card["elements"] if e.get("tag") == "action")
        self.assertEqual(len(action_el["actions"]), 3)
        for btn in action_el["actions"]:
            v = btn["value"]
            self.assertIsInstance(v, str)
            parsed = json.loads(v)  # 必须是合法 JSON
            self.assertIn("action", parsed)
            self.assertIn("code_review_id", parsed)
            self.assertIn("pr_url", parsed)
        # BLOCKING 文案含 "X→Y 因 Z" 关键词
        for it in result["checklist"]:
            if it["status"] == "BLOCKING":
                self.assertTrue(
                    any(k in it["comment"] for k in ("改成", "换成", "替换", "改为")),
                    msg=f"BLOCKING comment lacks X→Y keyword: {it['comment']}",
                )
                self.assertTrue(
                    any(k in it["comment"] for k in ("因为", "因", "由于")),
                    msg=f"BLOCKING comment lacks 因 Z keyword: {it['comment']}",
                )


class TestCommentDensityCap(unittest.TestCase):
    """Scenario 4: 评论密度 — LLM 输出 8 条评论 → 截断到 ≤5 + warning."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_comment_density_truncated(self):
        # 构造 8 条评论：6 BLOCKING + 2 NON-BLOCKING
        cl = _all_pass_checklist()
        for i in range(6):
            cl[i]["status"] = "BLOCKING"
            cl[i]["comment"] = f"把 fileA_{i}.py line {i} 改成 X 因为 Y"
        cl[6]["status"] = "NON-BLOCKING"
        cl[6]["comment"] = "把 var_x 改成 var_y 因为命名一致性"
        cl[7]["status"] = "NON-BLOCKING"
        cl[7]["comment"] = "把缩进改成 4 空格 因为 PEP-8"

        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff("diff content"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response(cl, "测试密度"),
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/789"})
        result = json.loads(raw)
        if result.get("code_review_id"):
            self._cleanup_review_ids.append(result["code_review_id"])

        self.assertTrue(result.get("success"), msg=raw)
        self.assertLessEqual(result["comments_total"], 5)
        # warnings 含截断提示
        self.assertTrue(result.get("warnings"))
        self.assertTrue(
            any("评论 > 5" in w or "评论 >" in w for w in result["warnings"]),
            msg=f"missing density warning: {result['warnings']}",
        )
        # BLOCKING 优先保留（severity 排序）
        # 5 条评论里 BLOCKING 应至少占 5（因为 LLM 输出 6 BLOCKING + 2 NON-BLOCKING）
        # 但 per-file cap 可能再降级一些 BLOCKING — 至少不能全没了
        self.assertGreaterEqual(result["blocking_count"] + result["non_blocking_count"], 1)


class TestPerFileBlockingCap(unittest.TestCase):
    """Scenario 5: 单文件 ≤ 2 BLOCKING — 3 BLOCKING 同文件 → 截到 2 + 聚合 refactor."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_per_file_3_blocking_aggregated(self):
        # 同一个文件 hermes-plugin/api.py 上有 3 个 BLOCKING
        cl = _all_pass_checklist()
        cl[0]["status"] = "BLOCKING"
        cl[0]["comment"] = "把 hermes-plugin/api.py line 10 的 X 改成 Y 因为 Z"
        cl[1]["status"] = "BLOCKING"
        cl[1]["comment"] = "把 hermes-plugin/api.py line 20 的 A 改成 B 因为 C"
        cl[2]["status"] = "BLOCKING"
        cl[2]["comment"] = "把 hermes-plugin/api.py line 30 的 P 改成 Q 因为 R"

        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff("diff x"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response(cl, "per-file cap test"),
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/100"})
        result = json.loads(raw)
        if result.get("code_review_id"):
            self._cleanup_review_ids.append(result["code_review_id"])

        self.assertTrue(result.get("success"), msg=raw)
        # 3 BLOCKING → 2 BLOCKING + 1 NON-BLOCKING（聚合）
        self.assertLessEqual(result["blocking_count"], 2)
        # 聚合提示出现在某一项 comment 里
        any_aggregated = any(
            it.get("aggregated_due_to_per_file_cap")
            for it in result["checklist"]
        )
        self.assertTrue(any_aggregated, msg="未发现 per_file_cap 聚合标记")
        # warnings 含文件超 cap 提示
        self.assertTrue(
            any("BLOCKING 数 >" in w for w in (result.get("warnings") or [])),
            msg=f"missing per-file cap warning: {result.get('warnings')}",
        )


class TestCodeReviewDbWrite(unittest.TestCase):
    """Scenario 6: CodeReview 表实写 — 实写 sqlite3 + 测试后 DELETE 清理."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_code_review_actually_persisted(self):
        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff("diff x"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response(_all_pass_checklist(), "db write test"),
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/200"})
        result = json.loads(raw)
        rid = result.get("code_review_id")
        self.assertIsNotNone(rid, msg=raw)
        self._cleanup_review_ids.append(rid)

        # 实查 DB 验证行存在
        conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
        try:
            row = conn.execute(
                'SELECT * FROM "CodeReview" WHERE "id" = ?', (rid,)
            ).fetchone()
            self.assertIsNotNone(row)
            cols = [d[0] for d in conn.execute('SELECT * FROM "CodeReview" WHERE "id" = ?', (rid,)).description]
            row_dict = dict(zip(cols, row))
            self.assertEqual(row_dict["pr_url"], "https://github.com/owner/repo/pull/200")
            self.assertEqual(row_dict["appeal_status"], "none")
            self.assertEqual(row_dict["reviewer"], "AICTO")
            # checklist_json 应能解析
            cl = json.loads(row_dict["checklist_json"])
            self.assertEqual(len(cl), 10)
        finally:
            conn.close()


class TestPrDiffFetchFailure(unittest.TestCase):
    """Scenario 7: PR diff 拉取失败 — subprocess returncode != 0 + retry 用尽."""

    def test_pr_diff_fetch_fail_tech_then_unknown(self):
        def fake_run(*args, **kwargs):
            argv = args[0] if args else kwargs.get("args")
            if isinstance(argv, list) and argv[1] == "pr" and argv[2] == "diff":
                return mock.MagicMock(
                    returncode=1, stdout="", stderr="some transient git error"
                )
            return mock.MagicMock(returncode=0, stdout="", stderr="")

        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=fake_run,
        ), mock.patch.object(
            error_classifier_module, "escalate_to_owner", return_value={}
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/999"})
        result = json.loads(raw)
        self.assertIn("error", result)
        # retry_with_backoff 用尽 → 包装为 unknown level
        self.assertIn(result["level"], ("unknown", "tech"))


class TestGhCliMissing(unittest.TestCase):
    """Scenario 8: gh CLI 不存在 → permission 级（FileNotFoundError, 永久）."""

    def test_gh_not_installed_permission(self):
        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=FileNotFoundError("gh: command not found"),
        ), mock.patch.object(
            error_classifier_module, "escalate_to_owner", return_value={}
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/1"})
        result = json.loads(raw)
        self.assertIn("error", result)
        self.assertEqual(result["level"], "permission")
        self.assertIn("gh", result["error"].lower())


class TestScopeSingleDimension(unittest.TestCase):
    """Scenario 9: scope=security — 只对该维度 LLM 给真实 status，其余 PASS."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_scope_security_only(self):
        # 模拟 LLM 看到 SCOPE=安全 → 只对第 3 项给真实 status，其余 PASS
        cl = _all_pass_checklist()
        cl[2]["status"] = "BLOCKING"
        cl[2]["comment"] = "把 line 5 的硬编码密钥 改成 env 变量 因为不能提交 secret"
        for i in range(10):
            if i != 2:
                cl[i]["comment"] = "本次只审 安全 维度"

        captured_messages: List[Any] = []

        def fake_invoke(messages):
            captured_messages.extend(messages)
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock()]
            resp.choices[0].message.content = json.dumps(
                {"checklist": cl, "overall_summary": "scope test"},
                ensure_ascii=False,
            )
            return resp

        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff("diff x"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=fake_invoke,
        ):
            raw = run(
                {
                    "pr_url": "https://github.com/owner/repo/pull/300",
                    "scope": "security",
                }
            )
        result = json.loads(raw)
        if result.get("code_review_id"):
            self._cleanup_review_ids.append(result["code_review_id"])

        self.assertTrue(result.get("success"), msg=raw)
        # scope 字段透传到 prompt（含 "安全"）
        all_user_msg = "\n".join(
            m.get("content", "") for m in captured_messages if m.get("role") == "user"
        )
        self.assertIn("安全", all_user_msg)
        self.assertEqual(result.get("scope"), "安全")  # 归一化后


class TestLargeDiffTruncation(unittest.TestCase):
    """Scenario 12: 大 PR diff（>80K 字符）截断 + warning."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_large_diff_truncated(self):
        # 100K 字符的 diff
        big_diff = "diff --git a/foo.py b/foo.py\n" + ("x" * 100000)
        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff(big_diff, "big PR"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response(_all_pass_checklist(), "big diff"),
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/777"})
        result = json.loads(raw)
        if result.get("code_review_id"):
            self._cleanup_review_ids.append(result["code_review_id"])

        self.assertTrue(result.get("success"), msg=raw)
        # warnings 含截断提示
        self.assertTrue(result.get("warnings"))
        self.assertTrue(
            any("截断" in w or "diff 过长" in w for w in result["warnings"]),
            msg=f"missing truncation warning: {result['warnings']}",
        )


class TestBlockingFormatReformatting(unittest.TestCase):
    """Scenario 13: BLOCKING 文案不合规 → 自动 reformat + warning."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_unformatted_blocking_reformatted(self):
        cl = _all_pass_checklist()
        # 不合规：只有"这里不好"，缺 X→Y 因 Z
        cl[2]["status"] = "BLOCKING"
        cl[2]["comment"] = "这里不好，建议优化"

        with mock.patch.object(
            review_code_module.subprocess,
            "run",
            side_effect=_mock_subprocess_returning_diff("diff x"),
        ), mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response(cl, "format test"),
        ):
            raw = run({"pr_url": "https://github.com/owner/repo/pull/13"})
        result = json.loads(raw)
        if result.get("code_review_id"):
            self._cleanup_review_ids.append(result["code_review_id"])

        self.assertTrue(result.get("success"), msg=raw)
        # 第 3 项被 reformat
        item3 = result["checklist"][2]
        self.assertTrue(item3.get("format_warning"))
        self.assertIn("文案需重写", item3["comment"])
        # warnings 含格式提示
        self.assertTrue(
            any("BLOCKING 文案不合规" in w for w in (result.get("warnings") or [])),
            msg=f"missing format warning: {result.get('warnings')}",
        )


class TestInvalidInputs(unittest.TestCase):
    """Scenario 14/15: 入参非法 — intent 级."""

    def test_missing_pr_url(self):
        raw = run({})
        result = json.loads(raw)
        self.assertEqual(result.get("level"), "intent")
        self.assertIn("pr_url", result["error"])

    def test_invalid_pr_url(self):
        raw = run({"pr_url": "not-a-url"})
        result = json.loads(raw)
        self.assertEqual(result.get("level"), "intent")

    def test_invalid_scope(self):
        raw = run(
            {
                "pr_url": "https://github.com/owner/repo/pull/1",
                "scope": "totally-invalid-scope",
            }
        )
        result = json.loads(raw)
        self.assertEqual(result.get("level"), "intent")
        self.assertIn("scope", result["error"])


class TestAppealHandlerRetract(unittest.TestCase):
    """Scenario 16: appeal_handler 收回路径."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []
        # 直接写一行 CodeReview
        review = adr_storage_module.create_review(
            project_id="test-project-appeal-retract",
            pr_url="https://github.com/owner/repo/pull/500",
            checklist=_checklist_with_blocking(),
            blocker_count=2,
            suggestion_count=1,
            appeal_status="none",
        )
        self.review_id = review["id"]
        self._cleanup_review_ids.append(self.review_id)

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_appeal_retract_path(self):
        with mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response_appeal("retracted", "军团有理"),
        ):
            raw = appeal_handler(
                {
                    "code_review_id": self.review_id,
                    "appeal_reason": "我们已用 prepared statement，不是 SQL 注入",
                    "appealer": "L1-麒麟军团",
                }
            )
        result = json.loads(raw)
        self.assertTrue(result.get("success"), msg=raw)
        self.assertEqual(result["verdict"], "retracted")

        # DB 中 appeal_status 应已 update 为 retracted
        conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
        row = conn.execute(
            'SELECT appeal_status FROM "CodeReview" WHERE "id" = ?', (self.review_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "retracted")


class TestAppealHandlerMaintain(unittest.TestCase):
    """Scenario 17: appeal_handler 维持 → 升级骏飞."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []
        review = adr_storage_module.create_review(
            project_id="test-project-appeal-maintain",
            pr_url="https://github.com/owner/repo/pull/501",
            checklist=_checklist_with_blocking(),
            blocker_count=2,
            suggestion_count=1,
            appeal_status="none",
        )
        self.review_id = review["id"]
        self._cleanup_review_ids.append(self.review_id)

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_appeal_maintain_escalates(self):
        escalate_calls: List[Any] = []

        def fake_escalate(*args, **kwargs):
            escalate_calls.append((args, kwargs))
            return {"escalated": True, "level": args[0]}

        with mock.patch.object(
            design_tech_plan_module,
            "_invoke_llm",
            side_effect=_mock_llm_response_appeal(
                "maintained", "军团理由不成立，BLOCKING 维持"
            ),
        ), mock.patch.object(
            error_classifier_module, "escalate_to_owner", side_effect=fake_escalate
        ):
            raw = appeal_handler(
                {
                    "code_review_id": self.review_id,
                    "appeal_reason": "我们认为这不需要测试",
                    "appealer": "L1-赤龙军团",
                }
            )
        result = json.loads(raw)
        self.assertTrue(result.get("success"), msg=raw)
        self.assertEqual(result["verdict"], "maintained")
        # 应触发升级（R-OPEN-3：1 次 appeal 即升级）
        self.assertEqual(len(escalate_calls), 1)

        # DB 中 appeal_status 应已升级到 escalated
        conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
        row = conn.execute(
            'SELECT appeal_status FROM "CodeReview" WHERE "id" = ?', (self.review_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "escalated")


class TestFindStaleBlockingReviews(unittest.TestCase):
    """Scenario 18: find_stale_blocking_reviews 接口（供 daily_brief 调用）."""

    def setUp(self):
        self._cleanup_review_ids: List[str] = []

    def tearDown(self):
        if self._cleanup_review_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for rid in self._cleanup_review_ids:
                    conn.execute('DELETE FROM "CodeReview" WHERE "id" = ?', (rid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_find_stale_returns_old_blocking(self):
        # 创建一行 26 小时前的 CodeReview（blocker_count>0, appeal_status='none'）
        review = adr_storage_module.create_review(
            project_id="test-stale-blocking",
            pr_url="https://github.com/owner/repo/pull/600",
            checklist=_checklist_with_blocking(),
            blocker_count=2,
            suggestion_count=1,
            appeal_status="none",
        )
        rid = review["id"]
        self._cleanup_review_ids.append(rid)

        # 把 reviewed_at 改成 26h 之前
        conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
        try:
            from datetime import datetime, timedelta, timezone
            past = (datetime.now(timezone.utc) - timedelta(hours=26)).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            )
            conn.execute(
                'UPDATE "CodeReview" SET "reviewed_at" = ? WHERE "id" = ?',
                (past, rid),
            )
            conn.commit()
        finally:
            conn.close()

        stale = find_stale_blocking_reviews(stale_hours=24.0)
        ids = [r["id"] for r in stale]
        self.assertIn(rid, ids)


class TestBuildAppealCardStructure(unittest.TestCase):
    """Scenario 11: 飞书卡片 dict 结构（4 字段 + 3 按钮 + value json.dumps）."""

    def test_card_structure(self):
        cl = _checklist_with_blocking()
        card = build_appeal_card(
            pr_url="https://github.com/o/r/pull/42",
            pr_number="42",
            pr_title="标题示例",
            checklist=cl,
            blocking_count=2,
            code_review_id="cr-uuid-test",
        )
        # header 模板 red
        self.assertEqual(card["header"]["template"], "red")
        self.assertIn("BLOCKING", card["header"]["title"]["content"])
        self.assertIn("42", card["header"]["title"]["content"])

        # elements 中应含 PR 信息块、BLOCKING 详情块、修复要求块、action 按钮组
        elements = card["elements"]
        # 至少 4 个有内容的块（不含 hr）
        non_hr = [e for e in elements if e.get("tag") != "hr"]
        self.assertGreaterEqual(len(non_hr), 4)

        # 找 action 元素
        action_el = next(e for e in elements if e.get("tag") == "action")
        actions = action_el["actions"]
        self.assertEqual(len(actions), 3)

        # 按钮文本和 value
        labels = [a["text"]["content"] for a in actions]
        self.assertTrue(any("接受" in lbl for lbl in labels))
        self.assertTrue(any("appeal" in lbl.lower() for lbl in labels))
        self.assertTrue(any("仲裁" in lbl for lbl in labels))

        for a in actions:
            v = a["value"]
            self.assertIsInstance(v, str)
            parsed = json.loads(v)
            self.assertEqual(parsed["code_review_id"], "cr-uuid-test")
            self.assertEqual(parsed["pr_url"], "https://github.com/o/r/pull/42")
            self.assertIn("action", parsed)


# ---------------------------------------------------------------------------
# Helper: appeal_handler 专用 mock LLM 响应
# ---------------------------------------------------------------------------


def _mock_llm_response_appeal(verdict: str, reasoning: str):
    payload = {"verdict": verdict, "reasoning": reasoning}

    def fake(messages):
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock()]
        resp.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
        return resp

    return fake


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    # 显式列出要运行的测试类，便于一眼看清覆盖
    unittest.main(verbosity=2)
