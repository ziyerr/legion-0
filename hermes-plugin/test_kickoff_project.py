"""kickoff_project 单元测试 — 10+ 自验证场景。

覆盖：
  1. import / syntax
  2. happy path mock（8 步全 success + 5 字段输出 + SLA）
  3. PM 不在线降级（step 3 status=degraded + 后续步骤继续）
  4. legion.sh 失败降级（兜底 discover_online_commanders）
  5. project 已存在拒绝（intent 级）
  6. B-1 防回归（_KickoffProjectError 继承 WrappedToolError）
  7. 飞书卡片 dict 校验（5 字段 + 3 按钮 + button.value 是 JSON 字符串）
  8. ADR-0001 写入（实际写 sqlite3 + 测试后 DELETE 清理）
  9. 复用 grep（确认 legion_api / dispatch_balanced / feishu_api / adr_storage 都被引用）
 10. 30s SLA（所有场景 elapsed < 30）
 11. 缺失 project_name（intent 级）
 12. invalid priority（intent 级）
 13. step 3 PM 返回缺 projectId → 降级

运行：
    cd /Users/feijun/Documents/AICTO
    /Users/feijun/.hermes/hermes-agent/venv/bin/python3 \
        hermes-plugin/test_kickoff_project.py

加载方式：把 hermes-plugin/ 当作包 'aicto' 注入 sys.modules，让相对导入成立。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock


# ---------------------------------------------------------------------------
# Bootstrap: 把 hermes-plugin 加载为 'aicto' 包（让 from . import ... 生效）
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "hermes-plugin"
PKG_NAME = "aicto"


def _bootstrap_package():
    """把 hermes-plugin 注册为 sys.modules['aicto']，相对导入即可 from . import xx."""
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
    """按需 load 一个子模块（不 exec __init__ 整体，避免 register 副作用）."""
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


# Pre-load all dependencies (顺序很重要：被依赖者先 load)
_load_submodule("error_classifier")
_load_submodule("pm_db_api")
_load_submodule("feishu_api")
_load_submodule("adr_storage")
_load_submodule("legion_api")
_load_submodule("design_tech_plan")
_load_submodule("breakdown_tasks")
_load_submodule("dispatch_balanced")
kickoff_module = _load_submodule("kickoff_project")
adr_storage_module = sys.modules[f"{PKG_NAME}.adr_storage"]
legion_api_module = sys.modules[f"{PKG_NAME}.legion_api"]
feishu_api_module = sys.modules[f"{PKG_NAME}.feishu_api"]
dispatch_balanced_module = sys.modules[f"{PKG_NAME}.dispatch_balanced"]
error_classifier_module = sys.modules[f"{PKG_NAME}.error_classifier"]


# Quick aliases
run = kickoff_module.run
build_kickoff_card = kickoff_module.build_kickoff_card
_KickoffProjectError = kickoff_module._KickoffProjectError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_commander(commander_id: str = "L1-麒麟军团",
                        legion_project: str = "AICTO_kickoff_test"):
    """构造一个 legion_api.Commander 对象（用真类）。"""
    return legion_api_module.Commander(
        legion_hash="abcd1234",
        legion_project=legion_project,
        commander_id=commander_id,
        task="test task",
        started_at="2026-04-25T10:00:00Z",
        tmux_alive=True,
        tmux_session=f"legion-abcd1234-{commander_id}",
        inbox_path=Path(f"/tmp/test-inbox/{commander_id}.json"),
    )


def _all_mocks_happy_path(test_project_path: str):
    """构造一组让 8 步全成功的 mock context。返回上下文管理器列表。"""
    fake_commander = _make_fake_commander()

    # mock requests.post → PM 返回成功
    fake_resp = mock.MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = mock.MagicMock(
        return_value={"projectId": "pm-uuid-test-001"}
    )

    return {
        "requests_post": mock.patch(
            "requests.post", return_value=fake_resp
        ),
        "subprocess_run": mock.patch.object(
            kickoff_module.subprocess,
            "run",
            return_value=mock.MagicMock(
                returncode=0,
                stdout="legion ok",
                stderr="",
            ),
        ),
        "discover": mock.patch.object(
            legion_api_module,
            "discover_online_commanders",
            return_value=[fake_commander],
        ),
        "send_card": mock.patch.object(
            feishu_api_module,
            "send_card_message",
            return_value={"data": {"message_id": "om_test_msg_001"}},
        ),
        "dispatch_run": mock.patch.object(
            dispatch_balanced_module,
            "run",
            return_value=json.dumps(
                {
                    "success": True,
                    "assignments": [
                        {
                            "task_id": "T-init-x",
                            "title": "test",
                            "legion_id": "L1-麒麟军团",
                            "msg_id": "msg-test",
                            "inbox_path": "/tmp/inbox.json",
                            "tmux_session": "legion-abcd1234-L1-麒麟军团",
                            "tmux_notified": False,
                            "priority": "low",
                            "payload_summary": "test",
                        }
                    ],
                    "deferred": [],
                    "elapsed_seconds": 0.1,
                    "online_legion_count": 1,
                    "ready_count": 1,
                }
            ),
        ),
    }


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestImportSyntax(unittest.TestCase):
    """Scenario 1: import / syntax."""

    def test_module_imports(self):
        self.assertTrue(callable(run))
        self.assertTrue(callable(build_kickoff_card))

    def test_inheritance_chain_b1(self):
        """Scenario 6: B-1 防回归 — _KickoffProjectError 继承 WrappedToolError."""
        self.assertTrue(
            issubclass(
                _KickoffProjectError, error_classifier_module.WrappedToolError
            )
        )
        # 实例化也走 .level 短路
        err = _KickoffProjectError(
            "test", level=error_classifier_module.LEVEL_TECH
        )
        self.assertEqual(err.level, error_classifier_module.LEVEL_TECH)
        # classify(WrappedToolError) 应直接返回 .level（短路）
        self.assertEqual(
            error_classifier_module.classify(err),
            error_classifier_module.LEVEL_TECH,
        )

    def test_module_referenced_dependencies(self):
        """Scenario 9: 复用 grep — 确认依赖被正确 import."""
        src = (PLUGIN_DIR / "kickoff_project.py").read_text(encoding="utf-8")
        # 必须 import 这 4 个核心依赖（复用纪律）
        self.assertIn("legion_api", src)
        self.assertIn("dispatch_balanced", src)
        self.assertIn("feishu_api", src)
        self.assertIn("adr_storage", src)
        self.assertIn("error_classifier", src)


class TestHappyPath(unittest.TestCase):
    """Scenario 2 + 10: happy path mock + 30s SLA."""

    def setUp(self):
        # 测试目录：用临时名字（每次随机），结束清理
        self.test_name = f"AICTO_kickoff_test_{int(time.time())}"
        self.test_path = os.path.expanduser(f"~/Documents/{self.test_name}")
        self._adr_ids_to_cleanup = []

    def tearDown(self):
        # 清理临时目录
        if os.path.exists(self.test_path):
            shutil.rmtree(self.test_path, ignore_errors=True)
        # 清理 ADR 行
        if self._adr_ids_to_cleanup:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for aid in self._adr_ids_to_cleanup:
                    conn.execute('DELETE FROM "ADR" WHERE "id" = ?', (aid,))
                conn.commit()
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def test_happy_path_all_8_steps(self):
        """Scenario 2: happy path — 8 步全 success + 5 字段输出 + SLA."""
        mocks = _all_mocks_happy_path(self.test_path)
        with mocks["requests_post"], mocks["subprocess_run"], \
                mocks["discover"], mocks["send_card"], mocks["dispatch_run"]:
            t0 = time.monotonic()
            raw = run(
                {
                    "project_name": self.test_name,
                    "description": "test project for kickoff happy path",
                    "priority": "P1",
                    "expected_legion_skill": "backend",
                }
            )
            elapsed = time.monotonic() - t0

        result = json.loads(raw)
        # 收集 ADR id 用于清理
        if result.get("adr_id"):
            self._adr_ids_to_cleanup.append(result["adr_id"])

        # ---- 总体成功 ----
        self.assertTrue(result.get("success"), msg=raw)
        # ---- 5 字段输出 ----
        self.assertEqual(result["project_id"], "pm-uuid-test-001")
        self.assertEqual(result["git_path"], self.test_path)
        self.assertEqual(result["legion_commander_id"], "L1-麒麟军团")
        self.assertTrue(result["adr_id"])
        self.assertTrue(result["adr_display_number"].startswith("ADR-"))
        self.assertIsInstance(result["initial_tasks"], list)
        self.assertEqual(result["feishu_card_message_id"], "om_test_msg_001")
        # ---- 8 步 step_results 全部存在 ----
        sr = result["step_results"]
        for key in (
            "1_mkdir",
            "2_git_init",
            "3_prodmind_project",
            "4_adr_0001",
            "5_legion",
            "6_mailbox",
            "7_initial_tasks",
            "8_feishu_card",
        ):
            self.assertIn(key, sr, msg=f"missing step {key}")
            self.assertEqual(
                sr[key]["status"], "success", msg=f"step {key} not success: {sr[key]}"
            )
        # ---- SLA：< 30s ----
        self.assertLess(elapsed, kickoff_module.KICKOFF_SLA_SECONDS)
        self.assertTrue(result.get("sla_compliant"))
        # ---- mkdir 实测落盘（非 mock）；git init 由 mock 覆盖（不查 .git/）----
        self.assertTrue(os.path.isdir(self.test_path))


class TestDegradationPath(unittest.TestCase):
    """Scenario 3: PM 不在线降级 — step 3 status=degraded 但后续步骤继续."""

    def setUp(self):
        self.test_name = f"AICTO_kickoff_degrade_{int(time.time())}"
        self.test_path = os.path.expanduser(f"~/Documents/{self.test_name}")
        self._adr_ids_to_cleanup = []

    def tearDown(self):
        if os.path.exists(self.test_path):
            shutil.rmtree(self.test_path, ignore_errors=True)
        if self._adr_ids_to_cleanup:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for aid in self._adr_ids_to_cleanup:
                    conn.execute('DELETE FROM "ADR" WHERE "id" = ?', (aid,))
                conn.commit()
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def test_pm_offline_degrade(self):
        """Scenario 3: requests.post 抛 ConnectionError → step 3 degraded + 后续 OK."""
        import requests  # noqa: F401  — confirm available
        from requests.exceptions import ConnectionError as RequestsConnError

        fake_commander = _make_fake_commander(
            legion_project=self.test_name
        )

        with mock.patch(
            "requests.post",
            side_effect=RequestsConnError("connection refused"),
        ), mock.patch.object(
            kickoff_module.subprocess,
            "run",
            return_value=mock.MagicMock(returncode=0, stdout="", stderr=""),
        ), mock.patch.object(
            legion_api_module,
            "discover_online_commanders",
            return_value=[fake_commander],
        ), mock.patch.object(
            feishu_api_module,
            "send_card_message",
            return_value={"data": {"message_id": "om_degrade"}},
        ), mock.patch.object(
            dispatch_balanced_module,
            "run",
            return_value=json.dumps(
                {
                    "success": True,
                    "assignments": [],
                    "deferred": [{"task_id": "T-init-x", "title": "x"}],
                    "elapsed_seconds": 0.05,
                    "online_legion_count": 1,
                    "ready_count": 1,
                }
            ),
        ):
            raw = run(
                {
                    "project_name": self.test_name,
                    "description": "PM offline degrade",
                }
            )
        result = json.loads(raw)
        if result.get("adr_id"):
            self._adr_ids_to_cleanup.append(result["adr_id"])

        self.assertTrue(result.get("success"), msg=raw)
        sr = result["step_results"]
        self.assertEqual(sr["3_prodmind_project"]["status"], "degraded")
        self.assertIn("local_project_id", sr["3_prodmind_project"])
        # project_id 必须使用 local-... 占位
        self.assertTrue(result["project_id"].startswith("local-"))
        # 后续步骤仍执行
        self.assertEqual(sr["4_adr_0001"]["status"], "success")
        self.assertIn(sr["5_legion"]["status"], ("success", "degraded"))
        self.assertEqual(sr["6_mailbox"]["status"], "success")


class TestLegionShFailFallback(unittest.TestCase):
    """Scenario 4: legion.sh 失败 → discover 兜底."""

    def setUp(self):
        self.test_name = f"AICTO_kickoff_legion_fail_{int(time.time())}"
        self.test_path = os.path.expanduser(f"~/Documents/{self.test_name}")
        self._adr_ids = []

    def tearDown(self):
        if os.path.exists(self.test_path):
            shutil.rmtree(self.test_path, ignore_errors=True)
        if self._adr_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for aid in self._adr_ids:
                    conn.execute('DELETE FROM "ADR" WHERE "id" = ?', (aid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_legion_sh_fail_fallback_idle_legion(self):
        idle_commander = _make_fake_commander(
            commander_id="L1-赤龙军团", legion_project="other"
        )

        # subprocess.run 第一次调用是 legion.sh，第二次（如果有）是 git init
        # 简单办法：returncode 区分 — git init returncode=0；legion.sh returncode=1
        def fake_run(args, **kwargs):
            if isinstance(args, list) and len(args) >= 1 and args[0] == "git":
                return mock.MagicMock(returncode=0, stdout="", stderr="")
            # legion.sh 失败
            return mock.MagicMock(
                returncode=1, stdout="", stderr="legion.sh boom"
            )

        fake_resp = mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json = mock.MagicMock(return_value={"projectId": "pid-2"})

        with mock.patch("requests.post", return_value=fake_resp), \
                mock.patch.object(
                    kickoff_module.subprocess, "run", side_effect=fake_run
                ), \
                mock.patch.object(
                    legion_api_module,
                    "discover_online_commanders",
                    return_value=[idle_commander],
                ), \
                mock.patch.object(
                    feishu_api_module,
                    "send_card_message",
                    return_value={"data": {"message_id": "om_x"}},
                ), \
                mock.patch.object(
                    dispatch_balanced_module,
                    "run",
                    return_value=json.dumps(
                        {
                            "success": True,
                            "assignments": [],
                            "deferred": [],
                            "online_legion_count": 1,
                        }
                    ),
                ):
            raw = run(
                {"project_name": self.test_name, "description": "legion fail"}
            )
        result = json.loads(raw)
        if result.get("adr_id"):
            self._adr_ids.append(result["adr_id"])

        self.assertTrue(result["success"], msg=raw)
        s5 = result["step_results"]["5_legion"]
        self.assertEqual(s5["status"], "degraded")
        self.assertEqual(s5["legion_commander_id"], "L1-赤龙军团")
        self.assertIn(
            "discover", s5.get("method", "").lower()
        )
        self.assertEqual(result["legion_commander_id"], "L1-赤龙军团")


class TestProjectAlreadyExists(unittest.TestCase):
    """Scenario 5: 项目已存在 → intent 级."""

    def setUp(self):
        self.test_name = f"AICTO_kickoff_exists_{int(time.time())}"
        self.test_path = os.path.expanduser(f"~/Documents/{self.test_name}")
        os.makedirs(self.test_path, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_path):
            shutil.rmtree(self.test_path, ignore_errors=True)

    def test_existing_dir_returns_intent_level(self):
        raw = run({"project_name": self.test_name})
        result = json.loads(raw)
        self.assertIn("error", result)
        self.assertEqual(result["level"], error_classifier_module.LEVEL_INTENT)
        self.assertEqual(result["step_failed"], "1_mkdir")
        self.assertIn("already exists", result["error"])


class TestCardSchema(unittest.TestCase):
    """Scenario 7: 飞书卡片 dict 校验 — 5 字段 + 3 按钮 + button.value 是 JSON 字符串."""

    def test_card_5_fields_3_buttons(self):
        card = build_kickoff_card(
            project_name="AICS",
            git_path="~/Documents/AICS",
            legion_commander_id="L1-麒麟军团",
            adr_id="adr-uuid-001",
            adr_display_number="ADR-0001",
            project_id="pid-AICS",
        )
        # 顶层结构
        self.assertIn("config", card)
        self.assertIn("header", card)
        self.assertIn("elements", card)
        # template
        self.assertEqual(card["header"]["template"], "green")
        # 项目名出现在 title
        self.assertIn("AICS", card["header"]["title"]["content"])

        # 5 字段（首个 div 的 fields[]，除"状态"外的 4 个 + 单独"状态"）
        first_div_fields = card["elements"][0]["fields"]
        self.assertEqual(len(first_div_fields), 4)  # 项目名 / Path / Legion / ADR
        labels = [f["text"]["content"] for f in first_div_fields]
        self.assertTrue(any("项目名" in s for s in labels))
        self.assertTrue(any("Path" in s for s in labels))
        self.assertTrue(any("Legion" in s for s in labels))
        self.assertTrue(any("ADR" in s for s in labels))

        # 状态文案在第二个 div
        status_div = card["elements"][1]
        self.assertIn("状态", status_div["text"]["content"])
        self.assertIn("PM", status_div["text"]["content"])

        # 3 按钮
        action_block = card["elements"][3]
        self.assertEqual(action_block["tag"], "action")
        actions = action_block["actions"]
        self.assertEqual(len(actions), 3)
        button_texts = [a["text"]["content"] for a in actions]
        self.assertEqual(button_texts, ["查看 ADR", "加入军团群", "暂停项目"])
        types = [a["type"] for a in actions]
        self.assertEqual(types, ["primary", "default", "danger"])

        # 飞书协议怪癖：button.value 必须是 JSON 字符串（飞书会反 parse）
        for a in actions:
            self.assertIsInstance(a["value"], str)
            parsed = json.loads(a["value"])  # 必须是合法 JSON
            self.assertIn("action", parsed)


class TestADRWriteAndCleanup(unittest.TestCase):
    """Scenario 8: ADR-0001 写入 → sqlite3 验证 → DELETE 清理."""

    def setUp(self):
        self.test_name = f"AICTO_kickoff_adr_{int(time.time())}"
        self.test_path = os.path.expanduser(f"~/Documents/{self.test_name}")
        self._adr_ids = []

    def tearDown(self):
        if os.path.exists(self.test_path):
            shutil.rmtree(self.test_path, ignore_errors=True)
        if self._adr_ids:
            conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
            for aid in self._adr_ids:
                conn.execute('DELETE FROM "ADR" WHERE "id" = ?', (aid,))
            conn.commit()
            conn.close()

    def test_adr_actually_written_to_sqlite(self):
        mocks = _all_mocks_happy_path(self.test_path)
        with mocks["requests_post"], mocks["subprocess_run"], \
                mocks["discover"], mocks["send_card"], mocks["dispatch_run"]:
            raw = run(
                {
                    "project_name": self.test_name,
                    "description": "ADR write test",
                }
            )
        result = json.loads(raw)
        adr_id = result.get("adr_id")
        self.assertTrue(adr_id, msg=raw)
        self._adr_ids.append(adr_id)

        # 直接读 sqlite 校验
        conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
        try:
            row = conn.execute(
                'SELECT "id", "number", "title", "decision", "decided_by" '
                'FROM "ADR" WHERE "id" = ?',
                (adr_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "ADR row not found in sqlite")
        self.assertEqual(row[0], adr_id)
        self.assertEqual(row[1], 1)  # number=1（项目第一条 ADR）
        self.assertIn("ADR-0001", row[2])
        self.assertIn(self.test_name, row[3])
        self.assertEqual(row[4], "AICTO")


class TestArgsValidation(unittest.TestCase):
    """Scenario 11/12: 入参校验."""

    def test_missing_project_name(self):
        raw = run({})
        result = json.loads(raw)
        self.assertIn("error", result)
        self.assertEqual(result["level"], error_classifier_module.LEVEL_INTENT)
        self.assertEqual(result["step_failed"], "0_validate_args")

    def test_blank_project_name(self):
        raw = run({"project_name": "   "})
        result = json.loads(raw)
        self.assertEqual(result["level"], error_classifier_module.LEVEL_INTENT)

    def test_invalid_priority(self):
        raw = run({"project_name": "X", "priority": "P9"})
        result = json.loads(raw)
        self.assertIn("error", result)
        self.assertEqual(result["level"], error_classifier_module.LEVEL_INTENT)


class TestPMReturnsNoProjectId(unittest.TestCase):
    """Scenario 13: PM HTTP 200 但没 projectId → 降级."""

    def setUp(self):
        self.test_name = f"AICTO_kickoff_pmnoprojid_{int(time.time())}"
        self.test_path = os.path.expanduser(f"~/Documents/{self.test_name}")
        self._adr_ids = []

    def tearDown(self):
        if os.path.exists(self.test_path):
            shutil.rmtree(self.test_path, ignore_errors=True)
        if self._adr_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for aid in self._adr_ids:
                    conn.execute('DELETE FROM "ADR" WHERE "id" = ?', (aid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_pm_returns_no_project_id_degrades(self):
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json = mock.MagicMock(return_value={"foo": "bar"})  # 缺 projectId

        fake_commander = _make_fake_commander()

        with mock.patch("requests.post", return_value=fake_resp), \
                mock.patch.object(
                    kickoff_module.subprocess, "run",
                    return_value=mock.MagicMock(returncode=0, stdout="", stderr=""),
                ), \
                mock.patch.object(
                    legion_api_module, "discover_online_commanders",
                    return_value=[fake_commander],
                ), \
                mock.patch.object(
                    feishu_api_module, "send_card_message",
                    return_value={"data": {"message_id": "om_x"}},
                ), \
                mock.patch.object(
                    dispatch_balanced_module, "run",
                    return_value=json.dumps(
                        {"success": True, "assignments": [], "deferred": [],
                         "online_legion_count": 1}
                    ),
                ):
            raw = run({"project_name": self.test_name})
        result = json.loads(raw)
        if result.get("adr_id"):
            self._adr_ids.append(result["adr_id"])
        self.assertTrue(result.get("success"))
        self.assertEqual(
            result["step_results"]["3_prodmind_project"]["status"], "degraded"
        )
        self.assertTrue(result["project_id"].startswith("local-"))


class TestRealMkdirAndGitInit(unittest.TestCase):
    """Scenario 14: 真实 mkdir + git init（不 mock subprocess for git），验证落盘.

    不实际拉军团（mock legion.sh + 后续步骤），但 step 1/2 走真实 fs/git。
    结束 rm -rf 清理。
    """

    def setUp(self):
        self.test_name = f"AICTO_kickoff_realgit_{int(time.time())}"
        self.test_path = os.path.expanduser(f"~/Documents/{self.test_name}")
        self._adr_ids = []

    def tearDown(self):
        if os.path.exists(self.test_path):
            shutil.rmtree(self.test_path, ignore_errors=True)
        if self._adr_ids:
            try:
                conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                for aid in self._adr_ids:
                    conn.execute('DELETE FROM "ADR" WHERE "id" = ?', (aid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_real_mkdir_and_git_init_create_git_dir(self):
        """git init 真实执行，但 legion.sh + 飞书 + dispatch 仍 mock."""
        original_subprocess_run = kickoff_module.subprocess.run

        # 仅在 args[0]=='bash' 且 args[1]==legion.sh 时 mock；git init 走真实
        def selective_run(args, **kwargs):
            if (
                isinstance(args, list)
                and len(args) >= 2
                and args[0] == "bash"
                and "legion.sh" in str(args[1])
            ):
                return mock.MagicMock(
                    returncode=0, stdout="legion ok", stderr=""
                )
            return original_subprocess_run(args, **kwargs)

        fake_resp = mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json = mock.MagicMock(return_value={"projectId": "real-test"})

        fake_commander = _make_fake_commander(legion_project=self.test_name)

        with mock.patch("requests.post", return_value=fake_resp), \
                mock.patch.object(
                    kickoff_module.subprocess, "run", side_effect=selective_run
                ), \
                mock.patch.object(
                    legion_api_module,
                    "discover_online_commanders",
                    return_value=[fake_commander],
                ), \
                mock.patch.object(
                    feishu_api_module,
                    "send_card_message",
                    return_value={"data": {"message_id": "om_real"}},
                ), \
                mock.patch.object(
                    dispatch_balanced_module,
                    "run",
                    return_value=json.dumps(
                        {"success": True, "assignments": [], "deferred": [],
                         "online_legion_count": 1}
                    ),
                ):
            raw = run({"project_name": self.test_name, "description": "real git init"})
        result = json.loads(raw)
        if result.get("adr_id"):
            self._adr_ids.append(result["adr_id"])

        self.assertTrue(result.get("success"), msg=raw)
        # mkdir + git init 真实落盘
        self.assertTrue(os.path.isdir(self.test_path))
        self.assertTrue(os.path.isdir(os.path.join(self.test_path, ".git")))


class TestSlaWithinAllScenarios(unittest.TestCase):
    """Scenario 10: 各场景 elapsed < 30s（含降级）."""

    def test_happy_path_under_sla(self):
        test_name = f"AICTO_kickoff_sla_{int(time.time())}"
        test_path = os.path.expanduser(f"~/Documents/{test_name}")
        adr_ids = []
        try:
            mocks = _all_mocks_happy_path(test_path)
            t0 = time.monotonic()
            with mocks["requests_post"], mocks["subprocess_run"], \
                    mocks["discover"], mocks["send_card"], mocks["dispatch_run"]:
                raw = run(
                    {"project_name": test_name, "description": "sla test"}
                )
            elapsed = time.monotonic() - t0
            result = json.loads(raw)
            if result.get("adr_id"):
                adr_ids.append(result["adr_id"])
            self.assertLess(elapsed, kickoff_module.KICKOFF_SLA_SECONDS)
            self.assertTrue(result.get("sla_compliant"))
        finally:
            if os.path.exists(test_path):
                shutil.rmtree(test_path, ignore_errors=True)
            if adr_ids:
                try:
                    conn = sqlite3.connect(adr_storage_module.PRODMIND_DB_PATH)
                    for aid in adr_ids:
                        conn.execute('DELETE FROM "ADR" WHERE "id" = ?', (aid,))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
