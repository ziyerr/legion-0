import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


class LegionShellContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.legion_sh = cls.repo_root / "scripts" / "legion.sh"
        cls.commander_py = cls.repo_root / "scripts" / "legion-commander.py"

    def run_shell_contract(self, args, setup=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            home.mkdir()
            env = os.environ.copy()
            for key in (
                "LEGION_DIR",
                "MIXED_DIR",
                "REGISTRY_DIR",
                "PROJECT_DIR",
                "PLANNING_DIR",
                "LEGION_TRUST_PROJECT_DIR",
                "RETROSPECTOR_TRUST_BOUNDARY_ENV",
                "RETROSPECTOR_TRUST_PROJECT_DIR",
            ):
                env.pop(key, None)
            env.update(
                {
                    "HOME": str(home),
                    "TMPDIR": str(root / "missing-tmp"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            if setup is not None:
                setup(root, project, home, env)
            completed = subprocess.run(
                ["bash", str(self.legion_sh), *args],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            return completed, project, home

    def assert_read_only_shell_result(self, args, setup=None, expect_clean_home=True):
        completed, project, home = self.run_shell_contract(args, setup=setup)
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        if expect_clean_home:
            self.assertFalse((home / ".claude").exists())
        self.assertFalse((home / ".claude" / "legion" / "directory.json").exists())
        self.assertFalse((project / ".claude").exists())
        return completed

    def test_dry_run_entrypoints_skip_directory_registration_with_invalid_tmpdir(self):
        plan = json.dumps([{"id": "review", "role": "review", "task": "review diff"}])
        cases = [
            ["mixed", "campaign", plan, "--dry-run"],
            ["mixed", "host", "--dry-run", "--host-only"],
            ["mixed", "dual-host", "--dry-run", "--no-attach"],
            ["mixed", "aicto", "--dry-run", "--no-attach"],
            ["mixed", "view", "--dry-run"],
            ["host", "--dry-run", "--no-attach"],
            ["host", "--dry-run", "--host-only"],
            ["host", "--dual-only", "--dry-run", "--no-attach"],
            ["claude", "h", "--dry-run", "--no-attach"],
            ["claude", "l1", "--dry-run", "--no-attach"],
            ["codex", "l1", "--dry-run"],
            ["aicto", "--dry-run", "--no-attach"],
            ["duo", "--dry-run"],
            ["dou", "--dry-run"],
        ]

        for args in cases:
            with self.subTest(args=args):
                self.assert_read_only_shell_result(args)

    def test_host_default_dry_run_starts_dual_l1_not_local_aicto(self):
        completed = self.assert_read_only_shell_result(["host", "--dry-run", "--no-attach"])

        self.assertIn("L1-", completed.stdout)
        self.assertIn("[claude]", completed.stdout)
        self.assertIn("[codex]", completed.stdout)
        self.assertNotIn("L0-", completed.stdout)
        self.assertNotIn("L2:", completed.stdout)
        self.assertNotIn("[AICTO/", completed.stdout)

    def test_claude_h_dry_run_uses_separate_l1_sessions_without_dual_view(self):
        completed = self.assert_read_only_shell_result(["claude", "h", "--dry-run", "--no-attach"])

        self.assertIn("[claude]", completed.stdout)
        self.assertIn("[codex]", completed.stdout)
        self.assertNotIn("L2:", completed.stdout)
        self.assertNotIn("legion-view", completed.stdout)
        self.assertNotIn("view:", completed.stdout)

    def test_provider_l1_entrypoints_initialize_runtime_without_deploying_project_templates(self):
        def run_provider_l1(root, args):
            project = root / "project"
            home = root / "home"
            fake_bin = root / "fake-bin"
            reference = root / "reference"
            project.mkdir()
            home.mkdir()
            fake_bin.mkdir()
            (reference / ".claude" / "agents").mkdir(parents=True)
            (reference / ".claude" / "skills").mkdir(parents=True)
            for agent in ("explore", "implement", "plan", "review", "verify"):
                (reference / ".claude" / "agents" / f"{agent}.md").write_text(
                    f"# {agent}\n", encoding="utf-8"
                )
            for skill in ("agent-team", "audit", "recon", "safe-exec"):
                skill_dir = reference / ".claude" / "skills" / skill
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"# {skill}\n", encoding="utf-8")
            tmux = fake_bin / "tmux"
            tmux.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"has-session\" ]]; then exit 1; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            tmux.chmod(0o755)
            env = os.environ.copy()
            for key in (
                "LEGION_DIR",
                "MIXED_DIR",
                "REGISTRY_DIR",
                "PROJECT_DIR",
                "PLANNING_DIR",
                "LEGION_TRUST_PROJECT_DIR",
                "RETROSPECTOR_TRUST_BOUNDARY_ENV",
                "RETROSPECTOR_TRUST_PROJECT_DIR",
            ):
                env.pop(key, None)
            env.update(
                {
                    "HOME": str(home),
                    "TMPDIR": str(root / "missing-tmp"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "LEGION_REFERENCE_PROJECT": str(reference),
                }
            )
            env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            completed = subprocess.run(
                ["bash", str(self.legion_sh), *args],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            return project, home, completed

        cases = [
            ["claude", "l1", "青龙军团", "--no-attach"],
            ["codex", "l1", "玄武军团", "--no-attach"],
        ]

        for args in cases:
            with self.subTest(args=args):
                with tempfile.TemporaryDirectory() as td:
                    project, home, completed = run_provider_l1(Path(td), args)
                    self.assertEqual(
                        completed.returncode,
                        0,
                        msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                    )
                    self.assertFalse((project / "CLAUDE.md").exists())
                    self.assertFalse((project / ".claude" / "agents").exists())
                    self.assertFalse((project / ".claude" / "skills").exists())
                    self.assertFalse((project / ".claude" / "settings.local.json").exists())
                    self.assertTrue((home / ".claude" / "legion").is_dir())
                    self.assertTrue(any((home / ".claude" / "legion").glob("*/mixed/mixed-registry.json")))
                    self.assertFalse((project / ".claude" / "skills" / "safe-exec").exists())

    def test_project_initializer_merges_execution_discipline_into_existing_claude_md_once(self):
        core_skills = [
            "agent-team",
            "audit",
            "autonomous-loop",
            "degradation-policy",
            "recon",
            "spec-driven",
            "startup",
            "verification-before-completion",
            "using-superpowers",
            "writing-plans",
            "brainstorming",
            "claw-roundtable-skill",
            "product-counselor",
            "sniper",
        ]
        core_agents = ["implement.md", "review.md", "verify.md", "explore.md", "plan.md"]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            home = root / "home"
            reference = root / "reference"
            project.mkdir()
            home.mkdir()
            (project / ".git").mkdir()
            claude_md = project / "CLAUDE.md"
            original_claude = (
                "# Project Notes\n\n"
                "Keep custom local rules.\n\n"
                "## Long History\n\n"
                + "\n".join(f"- legacy detail {i}: verbose historical note that should be compacted" for i in range(80))
                + "\n"
            )
            claude_md.write_text(original_claude, encoding="utf-8")
            target_skills_dir = project / ".claude" / "skills"
            target_skills_dir.mkdir(parents=True)
            (target_skills_dir / "brainstorming").symlink_to("../../.agents/skills/brainstorming")
            (target_skills_dir / "legacy-file").write_text("not a skill directory", encoding="utf-8")
            (target_skills_dir / "broken-skill").mkdir()

            skills_dir = reference / ".claude" / "skills"
            agents_dir = reference / ".claude" / "agents"
            skills_dir.mkdir(parents=True)
            agents_dir.mkdir(parents=True)
            for skill in core_skills:
                skill_dir = skills_dir / skill
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"# {skill}\n", encoding="utf-8")
            for agent in core_agents:
                if agent == "implement.md":
                    agent_body = "# implement\n\n" + "\n".join(
                        f"- long agent rule {i}: detailed operational instruction" for i in range(120)
                    )
                    (agents_dir / agent).write_text(agent_body + "\n", encoding="utf-8")
                else:
                    (agents_dir / agent).write_text(f"# {agent}\n", encoding="utf-8")

            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "LEGION_INIT_ASSUME_YES": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )

            first = subprocess.run(
                [
                    "bash",
                    str(self.repo_root / "scripts" / "legion-init.sh"),
                    "--from",
                    str(reference),
                    "--minimal",
                ],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(first.returncode, 0, msg=f"stdout:\n{first.stdout}\nstderr:\n{first.stderr}")
            self.assertIn("skills 目录已清理", first.stdout)
            self.assertIn("CLAUDE.md 已备份并合并压缩最新纪律模板", first.stdout)

            updated = claude_md.read_text(encoding="utf-8")
            self.assertLessEqual(len(updated), 2500)
            self.assertIn("Keep custom local rules.", updated)
            self.assertIn("历史 CLAUDE.md（已压缩）", updated)
            self.assertNotIn("legacy detail 79", updated)
            self.assertTrue(updated.startswith("# >>> legion-init execution-discipline/v2 >>>"))
            self.assertIn("# >>> legion-init execution-discipline/v2 >>>", updated)
            self.assertIn("# 指挥官自主权（全局第一原则）", updated)
            self.assertIn("## 军团核心原则：规模优先", updated)
            self.assertIn("## 作战纪律", updated)
            backups = list((project / ".claude" / "backups" / "legion-init").glob("*/CLAUDE.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original_claude)
            self.assertTrue((target_skills_dir / "brainstorming").is_dir())
            self.assertFalse((target_skills_dir / "brainstorming").is_symlink())
            self.assertFalse((target_skills_dir / "legacy-file").exists())
            self.assertFalse((target_skills_dir / "broken-skill").exists())
            for skill_entry in target_skills_dir.iterdir():
                self.assertTrue(skill_entry.is_dir(), msg=f"{skill_entry} should be a directory")
                self.assertFalse(skill_entry.is_symlink(), msg=f"{skill_entry} should not be a symlink")
            backup_root = project / ".claude" / "backups" / "legion-init"
            symlink_backups = []
            file_backups = []
            broken_skill_backups = []
            for dirpath, dirnames, filenames in os.walk(backup_root):
                for name in dirnames + filenames:
                    path = Path(dirpath) / name
                    if name == "brainstorming" and os.path.islink(path):
                        symlink_backups.append(path)
                    if name == "legacy-file" and path.is_file():
                        file_backups.append(path)
                    if name == "broken-skill" and path.is_dir():
                        broken_skill_backups.append(path)
            self.assertEqual(len(symlink_backups), 1)
            self.assertEqual(len(file_backups), 1)
            self.assertEqual(len(broken_skill_backups), 1)
            implement_agent = project / ".claude" / "agents" / "implement.md"
            implement_text = implement_agent.read_text(encoding="utf-8")
            self.assertLessEqual(len(implement_text), 2500)
            self.assertIn("legion-agent-compressed/v1", implement_text)

            second = subprocess.run(
                [
                    "bash",
                    str(self.repo_root / "scripts" / "legion-init.sh"),
                    "--from",
                    str(reference),
                    "--minimal",
                ],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(second.returncode, 0, msg=f"stdout:\n{second.stdout}\nstderr:\n{second.stderr}")
            rerun = claude_md.read_text(encoding="utf-8")
            self.assertEqual(rerun.count("# >>> legion-init execution-discipline/v2 >>>"), 1)
            self.assertIn("CLAUDE.md 已是最新压缩纪律模板，跳过", second.stdout)

            fresh_project = root / "fresh-project"
            fresh_project.mkdir()
            (fresh_project / ".git").mkdir()
            fresh = subprocess.run(
                [
                    "bash",
                    str(self.repo_root / "scripts" / "legion-init.sh"),
                    "--from",
                    str(reference),
                    "--minimal",
                ],
                cwd=fresh_project,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(fresh.returncode, 0, msg=f"stdout:\n{fresh.stdout}\nstderr:\n{fresh.stderr}")
            fresh_claude = (fresh_project / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertLessEqual(len(fresh_claude), 2500)
            self.assertIn("# >>> legion-init execution-discipline/v2 >>>", fresh_claude)
            self.assertIn("## 军团核心原则：规模优先", fresh_claude)
            self.assertIn("# Project: fresh-project", fresh_claude)
            self.assertEqual(fresh_claude.count("# Project: fresh-project"), 1)

    def test_entrypoint_self_check_compresses_oversized_claude_on_every_invocation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            home.mkdir()
            long_claude = "# Project Notes\n\n" + "\n".join(
                f"- historical project detail {i}: verbose content that must be compacted" for i in range(120)
            )
            (project / "CLAUDE.md").write_text(long_claude + "\n", encoding="utf-8")
            skill_dir = project / ".agents" / "skills" / "recon"
            skill_dir.mkdir(parents=True)
            long_skill = "# recon skill\n\n" + "\n".join(
                f"- skill instruction {i}: this must remain a skill document, not an agent definition" for i in range(120)
            )
            (skill_dir / "SKILL.md").write_text(long_skill + "\n", encoding="utf-8")

            env = os.environ.copy()
            for key in (
                "LEGION_DIR",
                "MIXED_DIR",
                "REGISTRY_DIR",
                "PROJECT_DIR",
                "PLANNING_DIR",
                "LEGION_TRUST_PROJECT_DIR",
                "RETROSPECTOR_TRUST_BOUNDARY_ENV",
                "RETROSPECTOR_TRUST_PROJECT_DIR",
            ):
                env.pop(key, None)
            env.update(
                {
                    "HOME": str(home),
                    "TMPDIR": str(root / "missing-tmp"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            completed = subprocess.run(
                ["bash", str(self.legion_sh), "status"],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            claude_text = (project / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertLessEqual(len(claude_text), 2500)
            self.assertTrue(claude_text.startswith("# >>> legion-init execution-discipline/v2 >>>"))
            self.assertIn("历史 CLAUDE.md（已压缩）", claude_text)
            skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(skill_text, long_skill + "\n")
            self.assertNotIn("legion-agent-compressed/v1", skill_text)
            self.assertTrue(any((project / ".claude" / "backups" / "legion-self-check").glob("*/CLAUDE.md")))
            self.assertFalse((home / ".claude" / "legion" / "directory.json").exists())

    def test_aicto_entrypoint_is_external_hermes_status_not_local_commander(self):
        completed = self.assert_read_only_shell_result(["aicto", "--dry-run", "--no-attach"])

        self.assertIn("external Hermes CTO", completed.stdout)
        self.assertIn("not a local Legion L0 commander", completed.stdout)
        self.assertIn("nohup aicto gateway run", completed.stdout)
        self.assertNotIn("planned:", completed.stdout)
        self.assertNotIn("L0-", completed.stdout)

    def test_read_only_entrypoints_work_with_invalid_tmpdir_without_registration(self):
        cases = [
            ["status"],
            ["locks"],
            ["board"],
            ["sitrep"],
            ["watch"],
            ["inbox"],
            ["patrol"],
            ["retro"],
            ["retrospector"],
            ["mailbox"],
            ["mailbox", "read", "L1"],
            ["mailbox", "unread", "L1"],
            ["mailbox", "list", "L1"],
            ["gate", "L1", "status"],
            ["mixed", "status"],
            ["mixed", "inbox", "L1"],
            ["mixed", "readiness", "L1"],
            ["mixed", "aicto-reports"],
            ["ops"],
        ]

        for args in cases:
            with self.subTest(args=args):
                self.assert_read_only_shell_result(args)

    def test_ops_surface_unifies_team_blockers_patrol_retro_gate(self):
        completed = self.assert_read_only_shell_result(["ops"])
        out = completed.stdout
        for marker in (
            "Mixed 部队",
            "阻塞 / 失败任务",
            "巡查通知书",
            "Release Gate",
            "Retrospective Release Status",
            "Mixed 事件",
        ):
            self.assertIn(marker, out, msg=f"missing section marker {marker!r} in ops output:\n{out}")

    def test_ops_surface_prints_actual_operator_evidence_without_registration(self):
        def seed_ops_evidence(_root, project, home, _env):
            retros_dir = project / ".planning" / "retrospectives"

            retros_dir.mkdir(parents=True)

            def write_runtime(registry_dir):
                mixed_dir = registry_dir / "mixed"
                patrol_dir = registry_dir / "patrol"
                gate_dir = registry_dir / "team-L2-implement"

                mixed_dir.mkdir(parents=True)
                patrol_dir.mkdir(parents=True)
                gate_dir.mkdir(parents=True)

                (mixed_dir / "mixed-registry.json").write_text(
                    json.dumps(
                        {
                            "project": {"path": str(project)},
                            "commanders": [
                                {
                                    "id": "L1-host",
                                    "provider": "claude",
                                    "status": "commanding",
                                    "level": 1,
                                    "branch": "root",
                                    "lifecycle": "persistent",
                                },
                                {
                                    "id": "L2-verify",
                                    "provider": "codex",
                                    "status": "failed",
                                    "level": 2,
                                    "branch": "verify",
                                    "parent": "L1-host",
                                    "lifecycle": "campaign",
                                    "failure": "tmux new-session failed",
                                },
                            ],
                            "tasks": [
                                {
                                    "id": "repair-v17",
                                    "role": "implement",
                                    "status": "failed",
                                    "commander": "L2-implement",
                                    "task": "operator UX old worker",
                                    "scope": ["scripts/legion.sh"],
                                    "failure": "wrapped JSON in Markdown",
                                },
                                {
                                    "id": "audit-v17",
                                    "role": "audit",
                                    "status": "blocked",
                                    "commander": "L2-audit",
                                    "task": "audit operator UX",
                                    "scope": "tests/test_legion_shell_contract.py",
                                    "blocked_reason": "dependency repair-v17 is failed",
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                (mixed_dir / "events.jsonl").write_text(
                    "\n".join(
                        json.dumps(event, ensure_ascii=False)
                        for event in (
                            {
                                "timestamp": "2026-04-25T01:00:00Z",
                                "event": "task_failed",
                                "subject_id": "repair-v17",
                                "payload": {"failure": "wrapped JSON in Markdown"},
                            },
                            {
                                "timestamp": "2026-04-25T01:05:00Z",
                                "event": "gate_blocked",
                                "subject_id": "L2-implement",
                                "payload": {"reason": "release gate hold"},
                            },
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )
                (patrol_dir / "notice-L2-implement.json").write_text(
                    json.dumps(
                        {
                            "team_id": "L2-implement",
                            "status": "pending_remediation",
                            "edit_count": 23,
                            "issued_at": "2026-04-25T01:10:00Z",
                            "reason": "源码编辑无团队",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                (gate_dir / "gate.json").write_text(
                    json.dumps(
                        {
                            "status": "blocked",
                            "reason": "release gate hold",
                            "blocked_at": "2026-04-25T01:15:00Z",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            project_hashes = {
                hashlib.md5(str(path).encode("utf-8")).hexdigest()[:8]
                for path in (project, project.resolve())
            }
            for project_hash in project_hashes:
                write_runtime(home / ".claude" / "legion" / project_hash)

            (retros_dir / "2026-04-25-operator-ux.md").write_text(
                "\n".join(
                    [
                        "# Operator UX Retrospective",
                        "- Release gate verdict: fail",
                        "- blocks_release: true",
                        "- classification: release_blocking",
                    ]
                ),
                encoding="utf-8",
            )
            (project / ".planning" / "STATE.md").write_text(
                "Release gate verdict: fail\nRetrospective status: current blocker\n",
                encoding="utf-8",
            )

        completed = self.assert_read_only_shell_result(
            ["ops"],
            setup=seed_ops_evidence,
            expect_clean_home=False,
        )
        out = completed.stdout
        for needle in (
            "L1-host",
            "L2-verify",
            "tmux new-session failed",
            "repair-v17",
            "wrapped JSON in Markdown",
            "audit-v17",
            "dependency repair-v17 is failed",
            "status=pending_remediation",
            "源码编辑无团队",
            "status=blocked",
            "release gate hold",
            "2026-04-25-operator-ux.md",
            "Release gate verdict: fail",
            "blocks_release: true",
            "task_failed",
            "gate_blocked",
        ):
            self.assertIn(needle, out, msg=f"missing ops evidence {needle!r} in:\n{out}")

    def test_shell_prefers_repo_commander_script_over_global_copy(self):
        text = self.legion_sh.read_text(encoding="utf-8")

        repo_probe = 'if [[ -f "$LEGION_SCRIPT_DIR/legion-commander.py" ]]'
        global_probe = 'elif [[ -f "$HOME/.claude/scripts/legion-commander.py" ]]'
        self.assertIn(repo_probe, text)
        self.assertIn(global_probe, text)
        self.assertLess(text.index(repo_probe), text.index(global_probe))
        self.assertNotIn('COMMANDER_SCRIPT="$HOME/.claude/scripts/legion-commander.py"', text)
        self.assertNotIn("python3 $HOME/.claude/scripts/legion-commander.py", text)

    def test_commander_init_writes_startup_daemon_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            legion_dir = Path(td) / "legion-home" / "abcd1234"
            old_legion_dir = os.environ.get("LEGION_DIR")
            os.environ["LEGION_DIR"] = str(legion_dir)
            try:
                spec = importlib.util.spec_from_file_location(
                    f"legion_commander_contract_{time.time_ns()}",
                    self.commander_py,
                )
                module = importlib.util.module_from_spec(spec)
                self.assertIsNotNone(spec.loader)
                spec.loader.exec_module(module)
                module._start_time = time.monotonic()

                module.init()
            finally:
                if old_legion_dir is None:
                    os.environ.pop("LEGION_DIR", None)
                else:
                    os.environ["LEGION_DIR"] = old_legion_dir

            evidence_file = legion_dir / "daemon_evidence.jsonl"
            self.assertTrue(evidence_file.exists())
            records = [json.loads(line) for line in evidence_file.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            record = records[0]
            for key in ("schema_version", "evidence_id", "project_hash", "cwd", "kind", "record_hash"):
                self.assertIn(key, record)
            self.assertEqual(record["schema_version"], 1)
            self.assertEqual(record["project_hash"], "abcd1234")
            self.assertEqual(record["kind"], "daemon_started")

            record_hash = record["record_hash"]
            material = dict(record)
            del material["record_hash"]
            expected_hash = hashlib.sha256(
                json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            self.assertEqual(record_hash, expected_hash)


if __name__ == "__main__":
    unittest.main()
