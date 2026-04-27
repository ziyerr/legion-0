"""CTO operating model / command center tests."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        full,
        str(PLUGIN_DIR / f"{name}.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


_load_submodule("error_classifier")
_load_submodule("pm_db_api")
_load_submodule("feishu_api")
_load_submodule("adr_storage")
cto_memory = _load_submodule("cto_memory")
cto_operating_model = _load_submodule("cto_operating_model")
legion_api = _load_submodule("legion_api")
portfolio_manager = _load_submodule("portfolio_manager")
legion_command_center = _load_submodule("legion_command_center")
legion_system_maintenance = _load_submodule("legion_system_maintenance")


class TestCtoOperatingModel(unittest.TestCase):
    def test_decision_gate_fails_without_evidence(self):
        result = json.loads(
            cto_operating_model.run(
                {"action": "decision_gate", "decision_type": "authorization"}
            )
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["passes"])
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("L1 request/report id", result["missing_evidence"])

    def test_decision_gate_passes_with_matching_evidence(self):
        result = json.loads(
            cto_operating_model.run(
                {
                    "action": "decision_gate",
                    "decision_type": "authorization",
                    "evidence": [
                        {
                            "source": "l1_outbox",
                            "ref": "auth-1",
                            "detail": "L1 request report id includes rationale constraints rollback appeal path",
                        }
                    ],
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["passes"])
        self.assertEqual(result["missing_evidence"], [])

    def test_bootstrap_memory_writes_then_skips(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"AICTO_MEMORY_PATH": str(Path(temp_dir) / "cto_memory.jsonl")},
        ):
            first = json.loads(
                cto_operating_model.run({"action": "bootstrap_memory", "force": True})
            )
            second = json.loads(
                cto_operating_model.run({"action": "bootstrap_memory"})
            )
            query = cto_memory.query_memory(
                {"tag": "cto-operating-model-v1", "limit": 10}
            )

        self.assertTrue(first["success"])
        self.assertEqual(first["memory_count"], 2)
        self.assertTrue(second["success"])
        self.assertTrue(second["skipped"])
        self.assertGreaterEqual(query["total_matched"], 2)

    def test_source_basis_exposes_authoritative_links(self):
        result = json.loads(cto_operating_model.run({"action": "source_basis"}))

        self.assertTrue(result["success"])
        source_ids = {source["id"] for source in result["sources"]}
        self.assertIn("dora-metrics", source_ids)
        self.assertIn("nist-ssdf", source_ids)
        self.assertIn("owasp-llm-top10", source_ids)


class TestLegionCommandCenterEvidence(unittest.TestCase):
    def test_decide_authorization_requires_evidence_for_approval(self):
        result = json.loads(
            legion_command_center.run(
                {
                    "action": "decide_authorization",
                    "commander_id": "L1-AICTO",
                    "verdict": "approved",
                    "rationale": "方案看起来合理",
                }
            )
        )

        self.assertIn("error", result)
        self.assertIn("requires evidence", result["error"])

    def test_decide_authorization_with_evidence_sends_and_records(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"AICTO_MEMORY_PATH": str(Path(temp_dir) / "cto_memory.jsonl")},
        ), mock.patch.object(
            legion_command_center.legion_api,
            "send_to_commander",
            return_value={
                "message_id": "msg-1",
                "inbox_path": "/tmp/inbox.json",
                "tmux_session": "legion-test",
                "tmux_notified": True,
                "legacy_inbox_written": True,
            },
        ) as send:
            result = json.loads(
                legion_command_center.run(
                    {
                        "action": "decide_authorization",
                        "commander_id": "L1-AICTO",
                        "verdict": "approved",
                        "rationale": "L1 已提交计划，测试门和回滚路径完整",
                        "evidence": [
                            {
                                "source": "l1_outbox",
                                "ref": "auth-1",
                                "detail": "L1 request/report id auth-1 rationale constraints rollback appeal path",
                            }
                        ],
                    }
                )
            )
            auth_records = cto_memory.query_memory(
                {"kind": "authorization", "legion_id": "L1-AICTO", "limit": 5}
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["evidence_count"], 1)
        self.assertEqual(result["directive"]["evidence_count"], 1)
        send.assert_called_once()
        sent_payload = send.call_args.kwargs["payload"]
        self.assertIn("## 事实证据", sent_payload)
        self.assertGreaterEqual(auth_records["total_matched"], 1)


class TestLegionApiProjectDisambiguation(unittest.TestCase):
    def test_send_to_duplicate_commander_requires_legion_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.object(legion_api, "LEGION_ROOT", Path(temp_dir)), \
             mock.patch.object(legion_api, "LEGION_DIRECTORY", Path(temp_dir) / "directory.json"), \
             mock.patch.object(legion_api, "_live_tmux_sessions", return_value=set()):
            root = Path(temp_dir)
            (root / "aaaa1111" / "team-L1").mkdir(parents=True)
            (root / "bbbb2222" / "team-L1").mkdir(parents=True)
            (root / "directory.json").write_text(
                json.dumps(
                    {
                        "legions": [
                            {"hash": "aaaa1111", "project": "A"},
                            {"hash": "bbbb2222", "project": "B"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(legion_api.LegionError):
                legion_api.send_to_commander("L1", "hello")
            result = legion_api.send_to_commander(
                "L1",
                "hello",
                legion_hash="bbbb2222",
            )

        self.assertEqual(result["legion_hash"], "bbbb2222")
        self.assertIn("bbbb2222/team-L1/inboxes/L1.json", result["inbox_path"])

    def test_send_to_mixed_commander_writes_mixed_inbox(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.object(legion_api, "LEGION_ROOT", Path(temp_dir)), \
             mock.patch.object(legion_api, "LEGION_DIRECTORY", Path(temp_dir) / "directory.json"), \
             mock.patch.object(
                 legion_api,
                 "_live_tmux_sessions",
                 return_value={"legion-mixed-cccc3333-L1-demo"},
             ), \
             mock.patch.object(legion_api, "_tmux_send_keys"):
            root = Path(temp_dir)
            (root / "cccc3333" / "mixed").mkdir(parents=True)
            (root / "directory.json").write_text(
                json.dumps({"legions": [{"hash": "cccc3333", "project": "Demo"}]}),
                encoding="utf-8",
            )
            (root / "cccc3333" / "mixed" / "mixed-registry.json").write_text(
                json.dumps(
                    {
                        "commanders": [
                            {
                                "id": "L1-demo",
                                "session": "legion-mixed-cccc3333-L1-demo",
                                "status": "commanding",
                            }
                        ],
                        "tasks": [],
                    }
                ),
                encoding="utf-8",
            )

            result = legion_api.send_to_commander(
                "L1-demo",
                "mixed hello",
                legion_hash="cccc3333",
            )
            mixed_inbox = Path(result["mixed_inbox_path"])
            mixed_lines = mixed_inbox.read_text(encoding="utf-8").splitlines()

        self.assertTrue(result["mixed_inbox_written"])
        self.assertEqual(json.loads(mixed_lines[-1])["content"], "mixed hello")


class TestLegionSystemMaintenance(unittest.TestCase):
    def test_scan_detects_attention_task_and_duplicate_commander(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.object(legion_api, "LEGION_ROOT", Path(temp_dir)):
            root = Path(temp_dir)
            (root / "directory.json").write_text(
                json.dumps(
                    {
                        "legions": [
                            {"hash": "aaaa1111", "project": "A", "path": "/tmp/a"},
                            {"hash": "bbbb2222", "project": "B", "path": "/tmp/b"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            for h in ("aaaa1111", "bbbb2222"):
                (root / h / "team-L1").mkdir(parents=True)
                (root / h / "registry.json").write_text(
                    json.dumps(
                        {
                            "teams": [
                                {
                                    "id": "L1",
                                    "role": "commander",
                                    "status": "commanding",
                                    "task": "lead",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
            (root / "aaaa1111" / "mixed").mkdir(parents=True)
            (root / "aaaa1111" / "mixed" / "mixed-registry.json").write_text(
                json.dumps(
                    {
                        "commanders": [],
                        "tasks": [
                            {
                                "id": "task-running",
                                "status": "running",
                                "commander": "L2-x",
                                "origin_commander": "L1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = json.loads(legion_system_maintenance.run({"action": "scan"}))

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"]["duplicate_commander_count"], 1)
        self.assertGreaterEqual(result["summary"]["attention_tasks"], 1)

    def test_ack_status_detects_acked_and_overdue(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.dict(
                 os.environ,
                 {"AICTO_MEMORY_PATH": str(Path(temp_dir) / "cto_memory.jsonl")},
             ), \
             mock.patch.object(legion_api, "LEGION_ROOT", Path(temp_dir)):
            root = Path(temp_dir)
            outbox_a = root / "aaaa1111" / "team-L1-A" / "outbox.jsonl"
            outbox_a.parent.mkdir(parents=True)
            cto_memory.record_event(
                kind="directive",
                scope="legion",
                title="acked directive",
                content="needs ack",
                legion_id="L1-A",
                source="AICTO",
                tags=["cto-directive", "request_plan"],
                metadata={
                    "directive_id": "dir-a",
                    "send_result": {
                        "message_id": "msg-a",
                        "legion_hash": "aaaa1111",
                        "inbox_path": str(root / "aaaa1111" / "team-L1-A" / "inboxes" / "L1-A.json"),
                    },
                },
            )
            cto_memory.record_event(
                kind="directive",
                scope="legion",
                title="overdue directive",
                content="needs ack",
                legion_id="L1-B",
                source="AICTO",
                tags=["cto-directive", "request_plan"],
                metadata={
                    "directive_id": "dir-b",
                    "send_result": {
                        "message_id": "msg-b",
                        "legion_hash": "bbbb2222",
                        "inbox_path": str(root / "bbbb2222" / "team-L1-B" / "inboxes" / "L1-B.json"),
                    },
                },
            )
            outbox_a.write_text(
                json.dumps(
                    {
                        "ts": "2999-01-01T00:00:00Z",
                        "from": "L1-A",
                        "to": "AICTO-CTO",
                        "type": "report",
                        "directive_id": "dir-a",
                        "in_reply_to": "msg-a",
                        "report_type": "AICTO-REPORT",
                        "summary": "ack received",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            mixed_b = root / "bbbb2222" / "mixed" / "inbox" / "l1-b.jsonl"
            mixed_b.parent.mkdir(parents=True)
            mixed_b.write_text(
                json.dumps(
                    {
                        "ts": "2999-01-01T00:00:00Z",
                        "from": "AICTO-CTO",
                        "to": "L1-B",
                        "type": "message",
                        "content": "original instruction directive_id=dir-b",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = json.loads(
                legion_system_maintenance.run(
                    {
                        "action": "ack_status",
                        "ack_timeout_minutes": -1,
                        "lookback_hours": 999999,
                    }
                )
            )

        statuses = {item["directive_id"]: item["ack_status"] for item in result["directives"]}
        self.assertEqual(statuses["dir-a"], "acked")
        self.assertEqual(statuses["dir-b"], "overdue")

    def test_escalate_overdue_acks_dry_run_builds_escalation(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.dict(
                 os.environ,
                 {"AICTO_MEMORY_PATH": str(Path(temp_dir) / "cto_memory.jsonl")},
             ), \
             mock.patch.object(legion_api, "LEGION_ROOT", Path(temp_dir)):
            root = Path(temp_dir)
            cto_memory.record_event(
                kind="directive",
                scope="legion",
                title="overdue directive",
                content="needs ack",
                legion_id="L1-B",
                source="AICTO",
                tags=["cto-directive", "request_plan"],
                metadata={
                    "directive_id": "dir-b",
                    "send_result": {
                        "message_id": "msg-b",
                        "legion_hash": "bbbb2222",
                        "inbox_path": str(root / "bbbb2222" / "team-L1-B" / "inboxes" / "L1-B.json"),
                    },
                },
            )

            result = json.loads(
                legion_system_maintenance.run(
                    {
                        "action": "escalate_overdue_acks",
                        "dry_run": True,
                        "ack_timeout_minutes": -1,
                        "lookback_hours": 999999,
                    }
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["overdue_count"], 1)
        self.assertEqual(result["results"][0]["directive"]["directive_type"], "escalate")


if __name__ == "__main__":
    unittest.main(verbosity=2)
