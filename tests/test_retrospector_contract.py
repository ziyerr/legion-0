import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RETROSPECTOR = REPO_ROOT / "scripts" / "retrospector.sh"


def md5_short(value: str) -> str:
    return hashlib.md5(value.encode("utf-8", errors="replace")).hexdigest()[:8]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def create_project(root: Path, state_marker: str) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "legion-patrol.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    planning = root / ".planning"
    (planning / "communication-upgrade").mkdir(parents=True, exist_ok=True)
    (planning / "STATE.md").write_text(f"# State\n\n{state_marker}\n", encoding="utf-8")
    (planning / "REQUIREMENTS.md").write_text("# Requirements\n", encoding="utf-8")
    (planning / "DECISIONS.md").write_text("# Decisions\n", encoding="utf-8")
    (planning / "communication-upgrade" / "04-LEGACY-PARITY-MATRIX.md").write_text(
        "| # | Legacy | Mixed | Status | Evidence |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 15 | Retrospective | mixed | UPG | synthetic fixture |\n",
        encoding="utf-8",
    )


def create_runtime(home: Path, project: Path) -> tuple[Path, Path]:
    legion_dir = home / ".claude" / "legion" / md5_short(str(project.resolve()))
    mixed_dir = legion_dir / "mixed"
    run_dir = mixed_dir / "runs" / "task-completed"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "result.md",
        {
            "status": "completed",
            "summary": "done",
            "files_touched": [],
            "verification": [],
            "findings": [],
            "risks": [],
        },
    )
    write_json(
        mixed_dir / "mixed-registry.json",
        {
            "project": {"path": str(project.resolve())},
            "commanders": [
                {
                    "id": "L1-test",
                    "project": str(project.resolve()),
                    "run_dir": str(mixed_dir / "commanders" / "L1-test"),
                }
            ],
            "tasks": [
                {
                    "id": "task-completed",
                    "status": "completed",
                    "role": "verify",
                    "provider": "codex",
                    "project": str(project.resolve()),
                    "run_dir": str(run_dir),
                }
            ],
        },
    )
    (mixed_dir / "events.jsonl").write_text(
        json.dumps({"ts": "2026-04-25T00:00:00Z", "event": "task_completed", "task_id": "task-completed"}) + "\n",
        encoding="utf-8",
    )
    write_json(legion_dir / "inspector_memory.json", {"judgments": []})
    (legion_dir / "daemon_evidence.jsonl").write_text("", encoding="utf-8")
    return legion_dir, mixed_dir


def add_terminal_task(
    mixed_dir: Path,
    project: Path,
    task_id: str,
    registry_status: str,
    result_status: str,
    event_name: str,
) -> None:
    run_dir = mixed_dir / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "result.md",
        {
            "status": result_status,
            "summary": f"{task_id} {result_status}",
            "files_touched": [],
            "verification": [],
            "findings": [],
            "risks": [],
        },
    )
    registry_path = mixed_dir / "mixed-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["tasks"].append(
        {
            "id": task_id,
            "status": registry_status,
            "role": "implement",
            "provider": "codex",
            "project": str(project.resolve()),
            "run_dir": str(run_dir),
            "failure": "historical terminal task fixture",
        }
    )
    write_json(registry_path, registry)
    with (mixed_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": "2026-04-25T00:01:00Z",
                    "event": event_name,
                    "task_id": task_id,
                    "payload": {"reason": "historical terminal task fixture"},
                }
            )
            + "\n"
        )


def clean_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in (
        "PROJECT_DIR",
        "PLANNING_DIR",
        "LEGION_DIR",
        "MIXED_DIR",
        "OBS_FILE",
        "INSPECTOR_FILE",
        "DAEMON_EVIDENCE_FILE",
        "RETROSPECTIVE_RUN_ID",
        "RETROSPECTIVE_CAMPAIGN",
        "LEGION_CAMPAIGN",
        "RETROSPECTOR_TRUST_PROJECT_DIR",
        "RETROSPECTOR_TRUST_BOUNDARY_ENV",
        "LEGION_TRUST_PROJECT_DIR",
    ):
        env.pop(key, None)
    obs_dir = home / ".claude" / "homunculus"
    obs_dir.mkdir(parents=True, exist_ok=True)
    (obs_dir / "observations.jsonl").write_text("", encoding="utf-8")
    return env


def run_quick(cwd: Path, env: dict[str, str]) -> dict:
    proc = subprocess.run(
        ["bash", str(RETROSPECTOR), "quick"],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"retrospector failed: rc={proc.returncode}\nstderr={proc.stderr}\nstdout={proc.stdout}")
    return json.loads(proc.stdout)


def run_full(cwd: Path, env: dict[str, str]) -> dict:
    proc = subprocess.run(
        ["bash", str(RETROSPECTOR), "full"],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"retrospector failed: rc={proc.returncode}\nstderr={proc.stderr}\nstdout={proc.stdout}")
    return json.loads(proc.stdout)


class RetrospectorContractTests(unittest.TestCase):
    def test_direct_quick_ignores_stale_project_and_runtime_envs_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            current = root / "legion-0"
            foreign = root / "other-repo"
            create_project(current, "CURRENT_PROJECT_TRUTH")
            create_project(foreign, "FOREIGN_PROJECT_TRUTH")
            create_runtime(home, current)
            foreign_legion, foreign_mixed = create_runtime(home, foreign)

            env = clean_env(home)
            env["PROJECT_DIR"] = str(foreign)
            env["PLANNING_DIR"] = str(foreign / ".planning")
            env["LEGION_DIR"] = str(foreign_legion)
            env["MIXED_DIR"] = str(foreign_mixed)

            report = run_quick(current, env)

            self.assertEqual(report["run"]["project_dir"], str(current.resolve()))
            self.assertEqual(report["run"]["planning_dir"], str((current / ".planning").resolve()))
            self.assertEqual(report["run"]["mixed_dir"], str((home / ".claude" / "legion" / md5_short(str(current.resolve())) / "mixed").resolve()))
            boundary = report["run"]["project_boundary"]
            self.assertEqual(boundary["project_dir_source"], "cwd_ignored_stale_env")
            self.assertEqual(boundary["planning_dir_source"], "project_default_ignored_stale_env")
            self.assertEqual(boundary["ignored_project_dir_env"], str(foreign.resolve()))
            self.assertEqual(boundary["ignored_mixed_dir_env"], str(foreign_mixed.resolve()))
            i6_paths = report["input_accounting"]["I6"]["paths"]
            self.assertTrue(i6_paths)
            self.assertTrue(all(str(current.resolve()) in path for path in i6_paths))
            self.assertTrue(all(str(foreign.resolve()) not in path for path in i6_paths))

    def test_explicit_trust_marker_allows_project_dir_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            current = root / "legion-0"
            foreign = root / "other-repo"
            create_project(current, "CURRENT_PROJECT_TRUTH")
            create_project(foreign, "FOREIGN_PROJECT_TRUTH")
            create_runtime(home, current)
            foreign_legion, foreign_mixed = create_runtime(home, foreign)

            env = clean_env(home)
            env["PROJECT_DIR"] = str(foreign)
            env["PLANNING_DIR"] = str(foreign / ".planning")
            env["LEGION_DIR"] = str(foreign_legion)
            env["MIXED_DIR"] = str(foreign_mixed)
            env["RETROSPECTOR_TRUST_PROJECT_DIR"] = "1"

            report = run_quick(current, env)

            self.assertEqual(report["run"]["project_dir"], str(foreign.resolve()))
            self.assertEqual(report["run"]["planning_dir"], str((foreign / ".planning").resolve()))
            self.assertEqual(report["run"]["mixed_dir"], str(foreign_mixed.resolve()))
            boundary = report["run"]["project_boundary"]
            self.assertEqual(boundary["project_dir_source"], "trusted_env:RETROSPECTOR_TRUST_PROJECT_DIR")
            self.assertEqual(boundary["planning_dir_source"], "env_inside_project")
            self.assertEqual(boundary["mixed_dir_source"], "env_trusted")
            i6_paths = report["input_accounting"]["I6"]["paths"]
            self.assertTrue(i6_paths)
            self.assertTrue(all(str(foreign.resolve()) in path for path in i6_paths))

    def test_full_disposes_historical_candidates_without_release_watch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            current = root / "legion-0"
            create_project(current, "CURRENT_PROJECT_TRUTH")
            _, mixed_dir = create_runtime(home, current)
            add_terminal_task(mixed_dir, current, "historical-failed-task", "failed", "failed", "task_failed")

            env = clean_env(home)
            report = run_full(current, env)

            self.assertEqual(report["classification"], "extracted")
            self.assertEqual(report["verdict"], "pass")
            self.assertEqual(report["release_gate"]["verdict"], "pass")
            self.assertFalse(report["release_gate"]["blocks_release"])
            self.assertGreater(report["release_gate"]["historical_learning_candidate_count"], 0)
            self.assertEqual(report["release_gate"]["release_blocking_candidate_count"], 0)
            self.assertTrue(report["candidates"])
            self.assertTrue(all(candidate["disposition"] == "historical-learning" for candidate in report["candidates"]))
            self.assertTrue(Path(report["retrospective_record"]).exists())

    def test_full_fails_closed_for_active_parity_blocker(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            current = root / "legion-0"
            create_project(current, "CURRENT_PROJECT_TRUTH")
            matrix_path = current / ".planning" / "communication-upgrade" / "04-LEGACY-PARITY-MATRIX.md"
            matrix_path.write_text(
                "| # | Legacy | Mixed | State | Evidence |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 15 | Retrospective | mixed | repair | BLK active release blocker |\n",
                encoding="utf-8",
            )
            create_runtime(home, current)

            env = clean_env(home)
            report = run_full(current, env)

            self.assertEqual(report["classification"], "extracted")
            self.assertEqual(report["verdict"], "fail")
            self.assertEqual(report["release_gate"]["verdict"], "fail")
            self.assertTrue(report["release_gate"]["blocks_release"])
            self.assertEqual(report["release_gate"]["release_blocking_candidate_count"], 1)
            self.assertEqual(report["release_gate"]["current_blockers"][0]["trigger"], "legacy_parity_blk")
            self.assertEqual(report["candidates"][0]["disposition"], "current-blocker")


if __name__ == "__main__":
    unittest.main()
