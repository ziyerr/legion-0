"""Row 11 (Inspector) parity contract for the mixed Legion daemon.

The legacy parity matrix marks row 11 as `RAS + UPG + WATCH`: the legacy LLM
patrol behavior is preserved, but the mixed inspector active loop only had
docs-level evidence. This module makes the active-loop / replacement evidence
explicit and runtime-checkable:

  1. The daemon main loop dispatches `inspector_patrol` on a fixed cadence,
     so a mixed commander cannot silently slip past the inspector.
  2. `inspector_patrol` enumerates mixed commanders via
     `discover_active_commanders()` and screen-captures their mixed tmux
     session (`legion-mixed-{hash}-{cmd_id}`).
  3. Judgment evidence is persisted to `LEGION_DIR/daemon_evidence.jsonl`
     with `schema_version=1`, `evidence_id`, `commander_source`, `cmd_id`,
     `session`, and a `record_hash` that is reproducible from the rest of
     the payload — the schema retrospector consumes.
  4. The judgment also feeds `LEGION_DIR/inspector_memory.json` at the path
     `retrospector.sh discover_inspector_file` reads.

Together these prove the WATCH item from `04-LEGACY-PARITY-MATRIX.md` row 11.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess as real_subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDER_PY = REPO_ROOT / "scripts" / "legion-commander.py"


def _load_commander_module(legion_dir: Path):
    """Re-execute legion-commander.py against a sandboxed LEGION_DIR.

    LEGION_DIR / PROJECT_HASH / module-level globals are bound at import
    time, so each test re-imports under a unique module name to keep the
    inspector's _inspector_last_check / _inspector_history caches isolated.
    """
    os.environ["LEGION_DIR"] = str(legion_dir)
    spec = importlib.util.spec_from_file_location(
        f"legion_commander_contract_{time.time_ns()}",
        COMMANDER_PY,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._start_time = time.monotonic()
    return module


class InspectorMixedActiveLoopContractTests(unittest.TestCase):
    """Row 11 active-loop contract for the mixed inspector."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="legion-commander-contract-")
        self.project_hash = "abcd1234"
        self.legion_dir = Path(self._tmp) / self.project_hash
        self.mixed_dir = self.legion_dir / "mixed"
        self.mixed_dir.mkdir(parents=True, exist_ok=True)
        self._old_env = {k: os.environ.get(k) for k in ("LEGION_DIR", "HOME")}
        # Isolate ~/.claude writes (TACTICS_DIR / GLOBAL_SKILLS_DIR mkdir at import).
        os.environ["HOME"] = self._tmp
        self.module = _load_commander_module(self.legion_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _seed_mixed_commander(self, cid="L2-implement-1777107899", session=None):
        session = session or f"legion-mixed-{self.project_hash}-{cid}"
        registry = {
            "commanders": [
                {
                    "id": cid,
                    "status": "commanding",
                    "session": session,
                    "role": "implement",
                    "provider": "claude",
                    "task": "repair-inspector-parity-active-loop-v17",
                    "parent": "L1-host",
                    "level": 2,
                }
            ]
        }
        (self.mixed_dir / "mixed-registry.json").write_text(
            json.dumps(registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        team_dir = self.legion_dir / f"team-{cid}"
        team_dir.mkdir(parents=True, exist_ok=True)
        (team_dir / "heartbeat.counter").write_text("80")
        return cid, session, team_dir

    def test_inspector_loop_is_wired_into_main_with_fixed_cadence(self):
        """The daemon main loop must dispatch inspector_patrol on a fixed
        cadence, otherwise the mixed inspector is dead code regardless of
        how well a single call works."""
        source = COMMANDER_PY.read_text(encoding="utf-8")
        self.assertGreater(self.module.INSPECTOR_INTERVAL_SECONDS, 0)
        self.assertGreater(self.module.POLL_INTERVAL, 0)

        main_split = source.split("def main(")
        self.assertEqual(
            len(main_split), 2,
            "expected exactly one main() definition in legion-commander.py",
        )
        main_src = main_split[1]
        self.assertIn(
            "inspector_patrol", main_src,
            "main() must dispatch inspector_patrol; row 11 active-loop "
            "evidence depends on the daemon actually calling it",
        )
        self.assertIn(
            "INSPECTOR_INTERVAL_SECONDS", main_src,
            "main() loop cadence must reference INSPECTOR_INTERVAL_SECONDS",
        )

    def test_discover_active_commanders_includes_mixed_commanding_records(self):
        """discover_active_commanders() must surface mixed commanders so the
        inspector loop can see them."""
        cid, session, _ = self._seed_mixed_commander()
        records = self.module.discover_active_commanders()
        mixed = [r for r in records if r.get("source") == "mixed"]
        self.assertEqual(
            len(mixed), 1,
            f"mixed commander must surface in active discovery; got {records}",
        )
        rec = mixed[0]
        self.assertEqual(rec["id"], cid)
        self.assertEqual(rec["session"], session)
        self.assertEqual(rec["status"], "commanding")
        self.assertEqual(rec["role"], "implement")
        self.assertEqual(rec["provider"], "claude")

    def test_inspector_patrol_captures_mixed_session_and_writes_evidence(self):
        """End-to-end: two patrol passes must (a) screen-capture the mixed
        tmux session, (b) hand snapshots to the LLM judge, (c) persist a
        patrol_judgment row to daemon_evidence.jsonl with stable schema/hash
        and commander_source=mixed, and (d) record the judgment in
        inspector_memory.json so retrospector can ingest it."""
        cid, session, team_dir = self._seed_mixed_commander()

        captured = {"tmux_targets": [], "claude_calls": 0}
        verdict_payload = json.dumps(
            {
                "user_task": "repair inspector parity active loop",
                "task_scale": "medium",
                "has_teammates": True,
                "verdict": "normal",
                "reason": "L2 已派合规分支并行执行",
                "suggestion": "",
            },
            ensure_ascii=False,
        )
        # Screen has to be > 50 chars for inspector_patrol to keep going.
        screen_text = (
            "❯ 收到掌门派下任务：修复 inspector 主动巡查循环\n"
            "已发起 L2 implement 分支并通过 audit 通道复核。\n"
            + ("行内容 " * 40)
        )

        def fake_run(cmd, *args, **kwargs):
            result = real_subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if not isinstance(cmd, (list, tuple)) or not cmd:
                return result
            if cmd[:2] == ["tmux", "capture-pane"]:
                target = cmd[cmd.index("-t") + 1]
                captured["tmux_targets"].append(target)
                result.stdout = screen_text
                return result
            if cmd[0] == "claude":
                captured["claude_calls"] += 1
                result.stdout = verdict_payload
                return result
            # Any other subprocess call (pgrep / list-panes / pwd) is benign.
            return result

        with patch("subprocess.run", side_effect=fake_run):
            # Pass 1: builds first inspector snapshot. history < 2 → no LLM yet.
            self.module.inspector_patrol()
            # Bump heartbeat counter so the >=20-tool-call gate opens for pass 2.
            (team_dir / "heartbeat.counter").write_text("160")
            # Pass 2: history reaches 2 → _inspect_with_llm fires → evidence is written.
            self.module.inspector_patrol()

        # (a) The active loop targeted the mixed tmux session at least twice.
        self.assertGreaterEqual(
            len(captured["tmux_targets"]), 2,
            "inspector_patrol must screen-capture the mixed session on each pass",
        )
        for target in captured["tmux_targets"]:
            self.assertEqual(
                target, session,
                f"inspector_patrol must target the mixed session, got {target!r}",
            )

        # (b) The second pass must hand the snapshots to the LLM judge.
        self.assertGreaterEqual(
            captured["claude_calls"], 1,
            "second pass should hand snapshots to the LLM judge via _call_claude",
        )

        # (c) Daemon evidence: schema_version + evidence_id + commander_source
        # + cmd_id + session + record_hash are all present, and record_hash is
        # reproducible from the rest of the payload (stable schema).
        evidence_file = self.legion_dir / "daemon_evidence.jsonl"
        self.assertTrue(
            evidence_file.exists(),
            "inspector loop must persist evidence to LEGION_DIR/daemon_evidence.jsonl "
            "(retrospector.discover_daemon_file reads this exact path)",
        )
        records = [
            json.loads(line)
            for line in evidence_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(records, "evidence file must have at least one record")

        patrol_records = [r for r in records if r.get("kind") == "patrol_judgment"]
        self.assertTrue(
            patrol_records,
            "active mixed inspector loop must record at least one patrol_judgment evidence row",
        )
        record = patrol_records[-1]
        for key in (
            "schema_version",
            "evidence_id",
            "project_hash",
            "cwd",
            "kind",
            "record_hash",
            "commander_source",
            "cmd_id",
            "session",
            "verdict",
            "reason",
        ):
            self.assertIn(key, record, f"patrol_judgment evidence missing key: {key}")
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["project_hash"], self.project_hash)
        self.assertEqual(
            record["commander_source"], "mixed",
            "mixed inspector evidence must label commander_source=mixed",
        )
        self.assertEqual(record["cmd_id"], cid)
        self.assertEqual(record["session"], session)
        self.assertEqual(record["verdict"], "normal")
        self.assertTrue(
            record["evidence_id"].startswith("daemon-"),
            f"evidence_id must use daemon- prefix, got {record['evidence_id']!r}",
        )

        material = {k: v for k, v in record.items() if k != "record_hash"}
        recomputed = hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            record["record_hash"], recomputed,
            "record_hash must be sha256 of the sorted payload sans record_hash; "
            "any drift would break retrospector evidence ingestion",
        )

        # (d) inspector_memory.json is at the path retrospector reads from,
        # and contains the judgment for the mixed commander.
        memory_file = self.legion_dir / "inspector_memory.json"
        self.assertTrue(
            memory_file.exists(),
            "inspector_memory.json must live at LEGION_DIR/inspector_memory.json "
            "(retrospector.discover_inspector_file reads this exact path)",
        )
        memory = json.loads(memory_file.read_text(encoding="utf-8"))
        judgments = memory.get("judgments", [])
        self.assertTrue(
            judgments,
            "inspector loop must record judgments into inspector_memory.json",
        )
        latest = judgments[-1]
        self.assertEqual(latest.get("cmd_id"), cid)
        self.assertEqual(latest.get("verdict"), "normal")
        self.assertIn("L2 已派合规分支并行执行", latest.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
