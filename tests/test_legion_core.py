import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.legion_core import (
    ClaudeAdapter,
    CodexAdapter,
    CommandRunner,
    LegionCore,
    ProjectContext,
    TaskSpec,
    build_interactive_view_tmux_script,
    build_duo_applescript,
    build_dou_terminal_commands,
    build_duo_terminal_commands,
    build_duo_tmux_script,
    external_aicto_status_text,
    launch_duo_terminal,
)


class RecordingRunner(CommandRunner):
    def __init__(self):
        self.commands = []

    def run(self, argv, cwd=None):
        self.commands.append((list(argv), cwd))
        return 0, "", ""


class SelectiveFailRunner(CommandRunner):
    def __init__(self, fail_prefix):
        if fail_prefix and isinstance(fail_prefix[0], list):
            self.fail_prefixes = fail_prefix
        else:
            self.fail_prefixes = [fail_prefix]
        self.commands = []

    def run(self, argv, cwd=None):
        self.commands.append((list(argv), cwd))
        for fail_prefix in self.fail_prefixes:
            if list(argv)[: len(fail_prefix)] == fail_prefix:
                return 1, "", "simulated failure"
        return 0, "", ""


class BranchCommanderLaunchFailRunner(CommandRunner):
    def __init__(self):
        self.commands = []

    def run(self, argv, cwd=None):
        self.commands.append((list(argv), cwd))
        if list(argv)[:2] == ["tmux", "has-session"]:
            return 1, "", "missing session"
        if list(argv)[:2] == ["tmux", "new-session"] and any("L2-" in str(part) for part in argv):
            return 1, "", "simulated branch launch failure"
        return 0, "", ""


class MissingWindowRunner(CommandRunner):
    def __init__(self):
        self.commands = []

    def run(self, argv, cwd=None):
        self.commands.append((list(argv), cwd))
        if list(argv)[:2] == ["tmux", "has-session"]:
            return 0, "", ""
        if list(argv)[:2] == ["tmux", "list-windows"]:
            return 0, "commander\n", ""
        return 0, "", ""


class OfflineTmuxRunner(CommandRunner):
    def __init__(self):
        self.commands = []

    def run(self, argv, cwd=None):
        self.commands.append((list(argv), cwd))
        if list(argv)[:2] == ["tmux", "has-session"]:
            return 1, "", "missing session"
        return 0, "", ""


class InaccessibleTmuxRunner(CommandRunner):
    def __init__(self):
        self.commands = []

    def run(self, argv, cwd=None):
        self.commands.append((list(argv), cwd))
        if list(argv)[:2] == ["tmux", "has-session"]:
            return 1, "", "permission denied connecting to tmux socket"
        if list(argv)[:2] == ["tmux", "list-windows"]:
            return 1, "", "permission denied connecting to tmux socket"
        return 0, "", ""


class NamedSessionRunner(CommandRunner):
    def __init__(self, live_sessions, attached_sessions=None, windows=None):
        self.live_sessions = set(live_sessions)
        self.attached_sessions = set(attached_sessions or [])
        self.windows = {session: list(items) for session, items in (windows or {}).items()}
        self.commands = []

    def run(self, argv, cwd=None):
        self.commands.append((list(argv), cwd))
        if list(argv)[:2] == ["tmux", "has-session"]:
            session = list(argv)[3] if len(argv) > 3 else ""
            if session in self.live_sessions:
                return 0, "", ""
            return 1, "", "missing session"
        if list(argv)[:2] == ["tmux", "display-message"]:
            session = ""
            if "-t" in argv:
                session = list(argv)[list(argv).index("-t") + 1]
            return 0, "1\n" if session in self.attached_sessions else "0\n", ""
        if list(argv)[:2] == ["tmux", "list-windows"]:
            session = ""
            if "-t" in argv:
                session = list(argv)[list(argv).index("-t") + 1]
            return 0, "\n".join(self.windows.get(session, [])) + "\n", ""
        return 0, "", ""


class CapturePaneRunner(NamedSessionRunner):
    def __init__(self, live_sessions, pane_outputs=None, capture_code=0):
        super().__init__(live_sessions)
        self.pane_outputs = dict(pane_outputs or {})
        self.capture_code = capture_code

    def run(self, argv, cwd=None):
        if list(argv)[:2] == ["tmux", "capture-pane"]:
            self.commands.append((list(argv), cwd))
            session = ""
            if "-t" in argv:
                session = list(argv)[list(argv).index("-t") + 1]
            if self.capture_code != 0 or session not in self.live_sessions:
                return self.capture_code or 1, "", "capture failed"
            return 0, self.pane_outputs.get(session, ""), ""
        return super().run(argv, cwd)


def worker_result_json(
    status="completed",
    summary="done",
    files_touched=None,
    verification=None,
    findings=None,
    risks=None,
    **overrides,
):
    data = {
        "status": status,
        "summary": summary,
        "files_touched": [] if files_touched is None else files_touched,
        "verification": [] if verification is None else verification,
        "findings": [] if findings is None else findings,
        "risks": [] if risks is None else risks,
    }
    data.update(overrides)
    return json.dumps(data)


class LegionCoreTests(unittest.TestCase):
    def register_commander(
        self,
        core,
        commander_id="L1-host",
        role="commander",
        branch="",
        parent="",
        session=None,
        provider="claude",
    ):
        core._upsert_commander(
            {
                "id": commander_id,
                "provider": provider,
                "role": role,
                "level": 1 if commander_id.startswith("L1-") else 2,
                "branch": branch,
                "parent": parent,
                "status": "commanding",
                "session": session or core.context.session_name,
                "run_dir": "",
                "project": str(core.context.project_dir),
                "updated": "old",
            }
        )

    def read_events(self, core):
        return [json.loads(line) for line in core.events_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    def assert_release_event_record(self, event, event_name=None, subject_id=None):
        self.assertEqual(event["schema_version"], 1)
        self.assertTrue(event["id"].startswith("evt-"))
        self.assertEqual(event["type"], "event")
        self.assertTrue(event["timestamp"])
        self.assertTrue(str(event["correlation_id"]).strip())
        self.assertIn("event", event)
        self.assertIn("task_id", event)
        self.assertIn("subject_id", event)
        self.assertEqual(event["task_id"], event["subject_id"])
        self.assertEqual(event["ts"], event["timestamp"])
        self.assertIsInstance(event["payload"], dict)
        self.assertIn("transition", event["payload"])
        self.assertEqual(event["payload"]["transition"], event["event"])
        if event_name is not None:
            self.assertEqual(event["event"], event_name)
        if subject_id is not None:
            self.assertEqual(event["subject_id"], subject_id)

    def test_worker_result_schema_marks_all_object_properties_as_required(self):
        schema = json.loads(Path("schemas/legion-worker-result.schema.json").read_text(encoding="utf-8"))

        def walk(node, path="root"):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object" and "properties" in node:
                properties = set(node["properties"].keys())
                required = set(node.get("required", []))
                self.assertEqual(
                    required,
                    properties,
                    msg=f"{path} required keys must match properties for Codex structured output",
                )
            for key, value in node.items():
                next_path = f"{path}.{key}"
                if isinstance(value, dict):
                    walk(value, next_path)
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        walk(item, f"{next_path}[{index}]")

        walk(schema)

    def test_project_context_uses_same_short_md5_hash_as_shell_legion(self):
        ctx = ProjectContext.from_path(Path("/tmp/example-project"))

        self.assertEqual(ctx.project_name, "example-project")
        self.assertEqual(ctx.project_hash, "7d1303b5")
        self.assertEqual(ctx.session_name, "legion-mixed-7d1303b5-example-project")

    def test_task_spec_defaults_provider_by_role(self):
        review = TaskSpec.from_mapping({"task": "review the diff", "role": "review"})
        implement = TaskSpec.from_mapping({"task": "add feature", "role": "implement"})

        self.assertEqual(review.provider, "codex")
        self.assertEqual(implement.provider, "claude")
        self.assertEqual(review.task_id, "task-001")

    def test_codex_adapter_builds_visible_exec_command_with_schema_and_sandbox(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = ProjectContext.from_path(root)
            spec = TaskSpec.from_mapping(
                {
                    "id": "review-api",
                    "provider": "codex",
                    "role": "review",
                    "task": "review API changes",
                    "scope": ["scripts/"],
                }
            )
            run_dir = root / ".run"
            run_dir.mkdir()
            prompt_file = run_dir / "prompt.md"
            result_file = run_dir / "result.md"
            schema_file = root / "schema.json"
            schema_file.write_text("{}", encoding="utf-8")

            cmd = CodexAdapter(ctx).build_command(spec, prompt_file, result_file, schema_file)

            self.assertEqual(cmd[:2], ["codex", "exec"])
            self.assertIn("--json", cmd)
            self.assertIn("--output-schema", cmd)
            self.assertIn(str(schema_file), cmd)
            self.assertIn("-s", cmd)
            self.assertIn("read-only", cmd)
            self.assertIn("-C", cmd)
            self.assertIn(str(root), cmd)
            self.assertNotIn("-a", cmd)
            self.assertNotIn("never", cmd)

    def test_codex_adapter_grants_workspace_write_to_delivery_roles(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ProjectContext.from_path(Path(td))
            adapter = CodexAdapter(ctx)

            for role in ("implement", "rescue", "product", "product-counselor", "ui", "ui-designer"):
                with self.subTest(role=role):
                    spec = TaskSpec.from_mapping({"id": role, "provider": "codex", "role": role, "task": "deliver"})
                    self.assertEqual(adapter.sandbox_for(spec), "workspace-write")

    def test_codex_adapter_keeps_read_only_roles_read_only_without_override(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ProjectContext.from_path(Path(td))
            adapter = CodexAdapter(ctx)

            for role in ("explore", "review", "verify", "audit", "security"):
                with self.subTest(role=role):
                    spec = TaskSpec.from_mapping({"id": role, "provider": "codex", "role": role, "task": "inspect"})
                    self.assertEqual(adapter.sandbox_for(spec), "read-only")

            override = TaskSpec.from_mapping(
                {"id": "audit-write", "provider": "codex", "role": "audit", "sandbox": "workspace-write", "task": "inspect"}
            )
            with self.assertRaises(SystemExit) as ctx:
                adapter.sandbox_for(override)
            self.assertIn("read-only gate", str(ctx.exception))

            delivery_read_only = TaskSpec.from_mapping(
                {"id": "impl-readonly", "provider": "codex", "role": "implement", "sandbox": "read-only", "task": "edit"}
            )
            with self.assertRaises(SystemExit) as delivery_ctx:
                adapter.sandbox_for(delivery_read_only)
            self.assertIn("requires workspace-write", str(delivery_ctx.exception))

            invalid = TaskSpec.from_mapping(
                {"id": "audit-invalid", "provider": "codex", "role": "audit", "sandbox": "danger-full-access", "task": "inspect"}
            )
            with self.assertRaises(SystemExit) as invalid_ctx:
                adapter.sandbox_for(invalid)
            self.assertIn("unsupported Codex sandbox", str(invalid_ctx.exception))

    def test_codex_worker_launch_uses_visible_tmux_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core.init_state()
            self.register_commander(
                core,
                commander_id="L2-audit-codex",
                role="branch-commander",
                branch="audit",
                parent="L1-codex",
                provider="codex",
                session="audit-session",
            )
            spec = TaskSpec.from_mapping(
                {
                    "id": "codex-visible-worker",
                    "provider": "codex",
                    "role": "review",
                    "task": "review the command plane",
                    "scope": ["scripts/legion_core.py"],
                }
            )
            core._run_dir(spec).mkdir(parents=True)
            core._upsert_task(spec.as_registry_entry("planned", "L2-audit-codex", core._run_dir(spec)))

            launched = core.launch_task(spec, "L2-audit-codex")

            self.assertTrue(launched)
            tmux_new_windows = [cmd for cmd, _cwd in runner.commands if cmd[:2] == ["tmux", "new-window"]]
            self.assertTrue(tmux_new_windows)
            self.assertTrue(any(str(item).startswith("audit-session:") for item in tmux_new_windows[-1]))
            self.assertIn("w-codex-visible-worker", tmux_new_windows[-1])
            send_keys = [cmd for cmd, _cwd in runner.commands if cmd[:2] == ["tmux", "send-keys"]]
            self.assertTrue(any("audit-session:w-codex-visible-worker" in cmd for cmd in send_keys[-1]))
            task = next(item for item in json.loads(core.registry_file.read_text())["tasks"] if item["id"] == "codex-visible-worker")
            self.assertEqual(task["session"], "audit-session")
            launch_script = core._run_dir(spec) / "launch.sh"
            self.assertIn("codex exec", launch_script.read_text(encoding="utf-8"))

    def test_claude_adapter_uses_permission_bypass_for_worker_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = ProjectContext.from_path(root)
            spec = TaskSpec.from_mapping({"id": "implement", "role": "implement", "task": "add feature"})
            prompt_file = root / "prompt.md"
            result_file = root / "result.md"

            body = ClaudeAdapter(ctx).build_launch_body(spec, prompt_file, result_file)

            self.assertIn("claude --dangerously-skip-permissions -p", body)
            self.assertIn("--max-turns 80", body)

    def test_codex_shim_routes_l1_to_legion_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_legion = root / "legion.sh"
            fake_legion.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
            fake_legion.chmod(0o755)

            env = os.environ.copy()
            env["CODEX_LEGION_SH"] = str(fake_legion)
            completed = subprocess.run(
                ["bash", "scripts/codex", "l1", "玄武军团", "--dry-run"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "codex l1 玄武军团 --dry-run")

    def test_codexl1_shim_routes_to_codex_l1_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_legion = root / "legion.sh"
            fake_legion.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
            fake_legion.chmod(0o755)

            env = os.environ.copy()
            env["CODEX_LEGION_SH"] = str(fake_legion)
            completed = subprocess.run(
                ["bash", "scripts/codexl1", "玄武军团", "--dry-run"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "codex l1 玄武军团 --dry-run")

    def test_codex_shim_forwards_non_legion_args_to_real_codex(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_codex = fake_bin / "codex"
            fake_codex.write_text("#!/usr/bin/env bash\nprintf 'REAL:%s\\n' \"$*\"\n", encoding="utf-8")
            fake_codex.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:/bin:/usr/bin"
            completed = subprocess.run(
                ["bash", "scripts/codex", "exec", "--help"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "REAL:exec --help")

    def test_claude_shim_routes_l1_to_legion_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_legion = root / "legion.sh"
            fake_legion.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
            fake_legion.chmod(0o755)

            env = os.environ.copy()
            env["CLAUDE_LEGION_SH"] = str(fake_legion)
            completed = subprocess.run(
                ["bash", "scripts/claude", "l1", "青龙军团", "--no-attach"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "claude l1 青龙军团 --no-attach")

    def test_claudel1_shim_routes_to_claude_l1_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_legion = root / "legion.sh"
            fake_legion.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
            fake_legion.chmod(0o755)

            env = os.environ.copy()
            env["CLAUDE_LEGION_SH"] = str(fake_legion)
            completed = subprocess.run(
                ["bash", "scripts/claudel1", "青龙军团", "--no-attach"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "claude l1 青龙军团 --no-attach")

    def test_claude_shim_forwards_non_legion_args_to_real_claude(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_claude = fake_bin / "claude"
            fake_claude.write_text("#!/usr/bin/env bash\nprintf 'REAL:%s\\n' \"$*\"\n", encoding="utf-8")
            fake_claude.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:/bin:/usr/bin"
            completed = subprocess.run(
                ["bash", "scripts/claude", "--version"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "REAL:--version")

    def test_legion_shim_routes_to_legion_entrypoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_legion = root / "legion.sh"
            fake_legion.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
            fake_legion.chmod(0o755)

            env = os.environ.copy()
            env["LEGION_SH"] = str(fake_legion)
            completed = subprocess.run(
                ["bash", "scripts/legion", "codex", "l1", "玄武军团", "--dry-run"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "codex l1 玄武军团 --dry-run")

    def test_dry_run_campaign_previews_without_mutating_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=home, runner=runner)
            plan = [
                {"id": "explore", "role": "explore", "task": "map the repo"},
                {"id": "implement", "role": "implement", "task": "add the feature", "scope": ["src/app.py"]},
            ]

            previewed = core.deploy_campaign(plan, commander="L1-mixed", dry_run=True)

            self.assertEqual([t.task_id for t in previewed], ["explore", "implement"])
            self.assertEqual(runner.commands, [])
            self.assertFalse(core.registry_file.exists())
            self.assertFalse(core.events_file.exists())
            self.assertFalse((core.state_dir / "runs").exists())

    def test_dry_run_campaign_does_not_append_to_existing_events_or_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.init_state()
            self.register_commander(core, "L1-host")
            registry_before = core.registry_file.read_text(encoding="utf-8")
            events_before = core.events_file.read_text(encoding="utf-8")

            core.deploy_campaign(
                [{"id": "implement", "role": "implement", "task": "preview only", "scope": ["src/app.py"]}],
                commander="L1-host",
                dry_run=True,
                corps=True,
            )

            self.assertEqual(core.registry_file.read_text(encoding="utf-8"), registry_before)
            self.assertEqual(core.events_file.read_text(encoding="utf-8"), events_before)
            self.assertFalse((core.state_dir / "runs").exists())

    def test_codex_l1_dry_run_previews_without_mutating_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)

            commander = core.start_commander(
                provider="codex",
                name="玄武军团",
                dry_run=True,
                attach=False,
            )

            self.assertEqual(commander["id"], "L1-玄武军团")
            self.assertEqual(commander["provider"], "codex")
            self.assertEqual(commander["status"], "planned")
            self.assertEqual(runner.commands, [])
            self.assertFalse(core.registry_file.exists())
            self.assertFalse(core.events_file.exists())
            self.assertFalse(Path(commander["run_dir"]).exists())

    def test_codex_l1_without_name_reuses_live_background_commander(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"live-codex-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L1-玄武军团",
                    "provider": "codex",
                    "role": "commander",
                    "status": "planned",
                    "session": "live-codex-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            commander = core.start_commander(provider="codex", name="", dry_run=False, attach=False)

            self.assertEqual(commander["id"], "L1-玄武军团")
            self.assertEqual(commander["status"], "commanding")
            self.assertEqual(commander["_action"], "载入在线军团")
            commands = [cmd for cmd, _ in runner.commands]
            self.assertFalse(any(cmd[:2] == ["tmux", "new-session"] for cmd in commands))

    def test_codex_l1_resume_refreshes_launch_artifacts_and_restores_legion_tmux_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "home" / "mixed" / "commanders" / "L1-玄武军团"
            run_dir.mkdir(parents=True)
            (run_dir / "prompt.md").write_text("stale prompt", encoding="utf-8")
            (run_dir / "launch.sh").write_text("LEGION_CODEX_STATUSLINE\n", encoding="utf-8")
            runner = NamedSessionRunner({"live-codex-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L1-玄武军团",
                    "provider": "codex",
                    "role": "commander",
                    "status": "planned",
                    "session": "live-codex-session",
                    "run_dir": str(run_dir),
                    "project": str(root),
                    "updated": "old",
                }
            )

            core.start_commander(provider="codex", name="", dry_run=False, attach=False)

            launch_text = (run_dir / "launch.sh").read_text(encoding="utf-8")
            self.assertNotIn("LEGION_CODEX_WINDOW_STATUS", launch_text)
            self.assertNotIn("LEGION_CODEX_STATUSLINE", launch_text)
            commands = [cmd for cmd, _ in runner.commands]
            self.assertTrue(any(cmd[:4] == ["tmux", "rename-window", "-t", "live-codex-session:0"] and cmd[-1] == "L1-玄武军团" for cmd in commands))
            self.assertTrue(any(cmd[:4] == ["tmux", "set-window-option", "-t", "live-codex-session:0"] and "automatic-rename" in cmd for cmd in commands))
            self.assertTrue(any(cmd[:4] == ["tmux", "set-option", "-u", "-t"] and cmd[4] == "live-codex-session" and cmd[-1] == "status-left" for cmd in commands))
            self.assertTrue(any(cmd[:4] == ["tmux", "set-option", "-u", "-t"] and cmd[4] == "live-codex-session" and cmd[-1] == "status-right" for cmd in commands))

    def test_codex_l1_without_name_reuses_commander_already_open_in_frontend(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"attached-codex-session"}, attached_sessions={"attached-codex-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L1-黑曜军团",
                    "provider": "codex",
                    "role": "commander",
                    "status": "commanding",
                    "session": "attached-codex-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            commander = core.start_commander(provider="codex", name="", dry_run=False, attach=False)

            self.assertEqual(commander["id"], "L1-黑曜军团")
            self.assertEqual(commander["provider"], "codex")
            self.assertEqual(commander["status"], "commanding")
            self.assertEqual(commander["_action"], "载入在线军团")
            commands = [cmd for cmd, _ in runner.commands]
            self.assertFalse(any(cmd[:2] == ["tmux", "new-session"] for cmd in commands))

    def test_codex_l1_without_name_creates_auto_named_commander_when_none_online(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = OfflineTmuxRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)

            commander = core.start_commander(provider="codex", name="", dry_run=False, attach=False)

            self.assertTrue(commander["id"].startswith("L1-"))
            self.assertEqual(commander["provider"], "codex")
            self.assertEqual(commander["status"], "commanding")
            self.assertEqual(commander["_action"], "新增军团")
            commands = [cmd for cmd, _ in runner.commands]
            self.assertTrue(any(cmd[:2] == ["tmux", "new-session"] for cmd in commands))

    def test_registry_temp_paths_are_unique_for_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            first = core._registry_tmp_path()
            second = core._registry_tmp_path()

            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, core.registry_file.parent)
            self.assertEqual(second.parent, core.registry_file.parent)

    def test_first_run_init_does_not_clobber_registry_committed_before_lock(self):
        class RacingInitCore(LegionCore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.injected = False

            @contextlib.contextmanager
            def _registry_lock(self):
                if not self.injected:
                    self.injected = True
                    self.state_dir.mkdir(parents=True, exist_ok=True)
                    committed = {
                        "project": self._project_record(),
                        "commanders": [],
                        "tasks": [{"id": "committed-task", "status": "planned"}],
                    }
                    self.registry_file.write_text(json.dumps(committed, ensure_ascii=False), encoding="utf-8")
                with super()._registry_lock():
                    yield

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = RacingInitCore(root, legion_home=root / "home", runner=RecordingRunner())

            core.init_state()

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertEqual([task["id"] for task in registry["tasks"]], ["committed-task"])

    def test_tmux_foreground_command_attaches_outside_tmux(self):
        with tempfile.TemporaryDirectory() as td:
            core = LegionCore(Path(td), legion_home=Path(td) / "home", runner=RecordingRunner())

            self.assertEqual(core._tmux_foreground_argv("legion-session", {}), ["tmux", "a", "-t", "legion-session"])

    def test_tmux_foreground_command_switches_client_inside_tmux(self):
        with tempfile.TemporaryDirectory() as td:
            core = LegionCore(Path(td), legion_home=Path(td) / "home", runner=RecordingRunner())

            self.assertEqual(
                core._tmux_foreground_argv("legion-session", {"TMUX": "/tmp/tmux,1,0"}),
                ["tmux", "switch-client", "-t", "legion-session"],
            )

    def test_commander_launch_script_marks_failed_when_cli_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            commander = core.start_commander(provider="codex", name="玄武军团", dry_run=False, attach=False)

            launch_text = (Path(commander["run_dir"]) / "launch.sh").read_text(encoding="utf-8")
            self.assertIn('if [ "$status" -eq 0 ]; then', launch_text)
            self.assertIn("mark-commander", launch_text)
            self.assertIn(" completed", launch_text)
            self.assertIn(" failed", launch_text)

    def test_codex_commander_launch_script_does_not_write_model_status_to_tmux_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            prompt_file = root / "prompt.md"
            prompt_file.write_text("commander prompt", encoding="utf-8")

            launch_text = core._codex_commander_launch_script(
                "L1-codex",
                prompt_file,
                root / "commander.log",
            )

            self.assertNotIn("LEGION_CODEX_WINDOW_STATUS", launch_text)
            self.assertNotIn("LEGION_CODEX_STATUSLINE", launch_text)
            self.assertNotIn("CODEX_INITIAL_TOKENS", launch_text)
            self.assertNotIn("models_cache.json", launch_text)
            self.assertNotIn("tmux rename-window", launch_text)
            self.assertNotIn("status-left", launch_text)
            self.assertIn("CODEX_INITIAL_PROMPT", launch_text)
            self.assertIn("codex -C", launch_text)

    def test_commander_tmux_launch_failure_marks_failed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = SelectiveFailRunner([["tmux", "has-session"], ["tmux", "new-session"]])
            core = LegionCore(root, legion_home=root / "home", runner=runner)

            commander = core.start_commander(provider="codex", name="玄武军团", dry_run=False, attach=False)

            self.assertEqual(commander["status"], "failed")
            self.assertIn("simulated failure", commander["failure"])

    def test_status_lists_commanders_and_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.start_commander(provider="codex", name="玄武军团", dry_run=False, attach=False)
            with patch.dict(
                os.environ,
                {"LEGION_COMMANDER_ID": "", "CLAUDE_CODE_AGENT_NAME": "", "CLAUDE_LEGION_TEAM_ID": ""},
            ):
                core.deploy_campaign([{"id": "review", "role": "review", "task": "review diff"}], dry_run=False)

            status = core.status_text()

            self.assertIn("Commanders", status)
            self.assertIn("L1-玄武军团", status)
            self.assertIn("L1 branch=-", status)
            self.assertIn("Tasks", status)
            self.assertIn("review", status)
            self.assertIn("branch=review", status)
            self.assertIn("parent=L1-mixed", status)
            self.assertIn("C=m", status)
            self.assertIn("commander: L2-review-", status)
            self.assertIn("origin: L1-mixed", status)

    def test_branch_commander_dry_run_previews_without_mutating_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            commander = core.create_branch_commander(
                branch="review",
                provider="codex",
                parent="L1-青龙军团",
                dry_run=True,
                attach=False,
            )

            self.assertEqual(commander["level"], 2)
            self.assertEqual(commander["branch"], "review")
            self.assertEqual(commander["parent"], "L1-青龙军团")
            self.assertEqual(commander["provider"], "codex")
            self.assertTrue(commander["id"].startswith("L2-review-"))
            self.assertFalse(core.registry_file.exists())
            self.assertFalse(core.events_file.exists())
            self.assertFalse(Path(commander["run_dir"]).exists())

    def test_l1_prompt_enforces_scale_first_legion_doctrine(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            prompt = core.render_commander_prompt("L1-host", "claude")

            self.assertIn("Core doctrine - scale-first Legion", prompt)
            self.assertIn("Resource cost is not a downgrade reason", prompt)
            self.assertIn("Default frontend topology is L1-only", prompt)
            self.assertIn("S-level directives", prompt)
            self.assertIn("M+ work expands upward", prompt)
            self.assertIn("mixed campaign --corps", prompt)
            self.assertIn("implementation, review, verify, and audit should be separated", prompt)
            self.assertIn("claw-roundtable-skill", prompt)
            self.assertIn("roundtable_health.py --require-runtime", prompt)
            self.assertLess(len(prompt.encode("utf-8")), 6500)
            self.assertNotIn("Campaign plan example", prompt)

    def test_l1_startup_message_is_lightweight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            message = core._commander_startup_message("L1-host", "claude")
            codex_message = core._commander_startup_message("L1-host", "codex")

            self.assertLess(len(message.encode("utf-8")), 1900)
            self.assertIn("启动 L1 军团初始化", message)
            self.assertIn("Claude L1 军团初始化", message)
            self.assertIn("不执行项目模板初始化", message)
            self.assertIn("全局/项目/记忆/技能/工具初始化只归 `legion 0`", message)
            self.assertIn("接入军团通讯", message)
            self.assertIn("AICTO 指挥链", message)
            self.assertIn("失败即 isolated", message)
            self.assertIn("mixed status", message)
            self.assertIn("mixed inbox L1-host", message)
            self.assertIn("peer-online / peer-sync", message)
            self.assertIn("Codex L1 军团初始化", codex_message)
            self.assertIn("侦察 / 审查 / 验证 / 审计", codex_message)
            self.assertNotIn(".planning/REQUIREMENTS.md", message)
            self.assertNotIn(".planning/DECISIONS.md", message)
            self.assertNotIn("memory/tactics/INDEX.md", message)
            self.assertNotIn("盘点 .claude/skills", message)

    def test_l2_prompt_enforces_specialty_scale_first_doctrine(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            prompt = core.render_branch_commander_prompt("L2-audit-1", "audit", "codex", "L1-host")

            self.assertIn("Core doctrine - scale-first Legion", prompt)
            self.assertIn("maximum effective specialty scale", prompt)
            self.assertIn("Resource cost is not a downgrade reason", prompt)
            self.assertIn("Do not create duplicate theater", prompt)
            self.assertIn("RoundTable", prompt)
            self.assertIn("roundtable_health.py --require-runtime", prompt)
            self.assertIn("Lightweight activation protocol", prompt)
            self.assertIn("Load only task-relevant context", prompt)
            self.assertIn("Do not perform full L1 initialization", prompt)

    def test_l2_prompt_keeps_roundtable_health_task_scoped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            for branch in ["implement", "audit", "review", "verify", "recon", "product", "ui", "backend"]:
                prompt = core.render_branch_commander_prompt(f"L2-{branch}-1", branch, "codex", "L1-host")

                self.assertIn("If assigned a RoundTable/圆桌 discussion task", prompt)
                self.assertIn("Do not run RoundTable health for unrelated branches", prompt)
                self.assertNotIn("for every branch", prompt)
                self.assertNotIn("your branch may handle planning/recon/product/audit decisions", prompt)

    def test_l2_launch_uses_lightweight_activation_message(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            prompt_file = root / "prompt.md"
            prompt_file.write_text("branch prompt", encoding="utf-8")

            script = core._branch_commander_launch_script("L2-audit-1", "codex", prompt_file, root / "worker.log")

            self.assertIn("L2 任务激活协议", script)
            self.assertIn("只围绕目标任务初始化", script)
            self.assertIn("不要执行 L1 的全量协议", script)
            self.assertNotIn("读取协议：AGENTS.md", script)

    def test_reused_l2_refreshes_prompt_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            first = core.create_branch_commander("audit", parent="L1-host", dry_run=False)
            prompt_file = Path(first["run_dir"]) / "prompt.md"
            prompt_file.write_text("stale prompt", encoding="utf-8")

            second = core.create_branch_commander("audit", parent="L1-host", dry_run=False)

            self.assertEqual(first["id"], second["id"])
            self.assertIn("Lightweight activation protocol", prompt_file.read_text(encoding="utf-8"))

    def test_branch_commander_reuse_respects_provider_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            codex = core.create_branch_commander("audit", provider="codex", parent="L1-host", dry_run=False)
            claude = core.create_branch_commander("audit", provider="claude", parent="L1-host", dry_run=False)

            self.assertNotEqual(codex["id"], claude["id"])
            self.assertEqual(codex["provider"], "codex")
            self.assertEqual(claude["provider"], "claude")

    def test_corps_campaign_does_not_reuse_wrong_provider_branch_commander(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")
            codex = core.create_branch_commander("audit", provider="codex", parent="L1-host", dry_run=False)

            core.deploy_campaign(
                [{"id": "audit-claude", "branch": "audit", "provider": "claude", "task": "audit with claude"}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            task = next(item for item in registry["tasks"] if item["id"] == "audit-claude")
            assigned = next(item for item in registry["commanders"] if item["id"] == task["commander"])
            self.assertNotEqual(task["commander"], codex["id"])
            self.assertEqual(assigned["provider"], "claude")

    def test_campaign_scope_and_task_insert_run_under_registry_lock(self):
        class LockAssertingCore(LegionCore):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.lock_depths = []

            def _assert_campaign_scope_conflicts(self, specs, existing_tasks):
                self.lock_depths.append(("scope", self._registry_lock_depth))
                return super()._assert_campaign_scope_conflicts(specs, existing_tasks)

            def create_branch_commander(self, *args, **kwargs):
                self.lock_depths.append(("commander", self._registry_lock_depth))
                return super().create_branch_commander(*args, **kwargs)

            def _upsert_task(self, entry):
                if entry.get("status") == "planned":
                    self.lock_depths.append(("task", self._registry_lock_depth))
                return super()._upsert_task(entry)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LockAssertingCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")

            core.deploy_campaign(
                [{"id": "backend-impl", "branch": "backend", "task": "edit backend", "scope": ["src/backend.py"]}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )

            checked = {name: depth for name, depth in core.lock_depths if name in {"scope", "commander", "task"}}
            self.assertGreaterEqual(checked["scope"], 1)
            self.assertGreaterEqual(checked["commander"], 1)
            self.assertGreaterEqual(checked["task"], 1)

    def test_corps_campaign_auto_creates_branch_commanders_and_routes_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-青龙军团")
            plan = [
                {
                    "id": "backend-impl",
                    "branch": "backend",
                    "task": "implement backend API",
                    "scope": ["scripts/api.py"],
                },
                {
                    "id": "audit-diff",
                    "branch": "audit",
                    "task": "audit the backend diff",
                    "depends_on": ["backend-impl"],
                },
            ]

            core.deploy_campaign(plan, commander="L1-青龙军团", dry_run=False, corps=True)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commanders = {item["branch"]: item for item in registry["commanders"]}
            self.assertEqual(commanders["backend"]["provider"], "claude")
            self.assertEqual(commanders["audit"]["provider"], "codex")

            tasks = {item["id"]: item for item in registry["tasks"]}
            self.assertEqual(tasks["backend-impl"]["branch"], "backend")
            self.assertEqual(tasks["backend-impl"]["commander"], commanders["backend"]["id"])
            self.assertEqual(tasks["audit-diff"]["commander"], commanders["audit"]["id"])

    def test_corps_campaign_infers_audit_role_and_codex_provider_from_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-青龙军团")

            core.deploy_campaign(
                [{"id": "audit-diff", "branch": "audit", "task": "audit backend diff"}],
                commander="L1-青龙军团",
                dry_run=False,
                corps=True,
            )

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            task = registry["tasks"][0]
            self.assertEqual(task["role"], "audit")
            self.assertEqual(task["provider"], "codex")

    def test_l1_campaign_auto_routes_m_complexity_through_l2_from_env(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            plan = [
                {"id": "audit-a", "role": "audit", "task": "audit shell changes"},
                {"id": "audit-b", "role": "audit", "task": "audit python changes"},
            ]

            with patch.dict(os.environ, {"CLAUDE_CODE_AGENT_NAME": "L1-星辰军团"}):
                core.deploy_campaign(plan, dry_run=False)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commanders = {item["branch"]: item for item in registry["commanders"]}
            self.assertIn("audit", commanders)
            self.assertEqual(commanders["audit"]["parent"], "L1-星辰军团")
            for task in registry["tasks"]:
                self.assertEqual(task["commander"], commanders["audit"]["id"])
                self.assertEqual(task["origin_commander"], "L1-星辰军团")
                self.assertEqual(task["complexity"], "m")

    def test_l1_s_complexity_direct_bypass_keeps_command_plane_task_on_l1(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            with patch.dict(os.environ, {"CLAUDE_CODE_AGENT_NAME": "L1-星辰军团"}):
                core.deploy_campaign(
                    [{"id": "ops-check", "role": "verify", "task": "verify command plane", "complexity": "s"}],
                    dry_run=False,
                    direct=True,
                )

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertEqual([commander["id"] for commander in registry["commanders"]], ["L1-星辰军团"])
            self.assertTrue(registry["commanders"][0]["synthetic_runtime"])
            self.assertEqual(registry["tasks"][0]["commander"], "L1-星辰军团")
            self.assertEqual(registry["tasks"][0]["origin_commander"], "L1-星辰军团")

    def test_l1_direct_allows_s_delivery_with_declared_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            with patch.dict(os.environ, {"CLAUDE_CODE_AGENT_NAME": "L1-星辰军团"}):
                core.deploy_campaign(
                    [
                        {
                            "id": "deliver-impl",
                            "role": "implement",
                            "task": "deliver small feature",
                            "complexity": "s",
                            "scope": ["src/app.py"],
                        }
                    ],
                    dry_run=False,
                    direct=True,
                )

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertEqual([commander["id"] for commander in registry["commanders"]], ["L1-星辰军团"])
            self.assertEqual(registry["tasks"][0]["commander"], "L1-星辰军团")
            self.assertEqual(registry["tasks"][0]["complexity"], "s")

    def test_l1_direct_rejects_m_delivery_role_without_corps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            with patch.dict(os.environ, {"CLAUDE_CODE_AGENT_NAME": "L1-星辰军团"}):
                with self.assertRaises(SystemExit) as ctx:
                    core.deploy_campaign(
                        [
                            {
                                "id": "rescue-fix",
                                "role": "rescue",
                                "task": "repair larger feature",
                                "complexity": "m",
                                "scope": ["src/app.py"],
                            }
                        ],
                        dry_run=True,
                        direct=True,
                    )

            self.assertIn("L1 M+ no-delivery", str(ctx.exception))

    def test_campaign_rejects_unknown_non_legion_commander_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            with self.assertRaises(SystemExit) as ctx:
                core.deploy_campaign(
                    [{"id": "audit-one", "role": "audit", "task": "audit diff"}],
                    commander="rogue-commander",
                    dry_run=True,
                )

            self.assertIn("unknown commander", str(ctx.exception))

    def test_l1_s_complexity_defaults_to_l1_without_base_l2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            with patch.dict(os.environ, {"CLAUDE_CODE_AGENT_NAME": "L1-星辰军团"}):
                core.deploy_campaign(
                    [{"id": "small-fix", "task": "fix one typo", "complexity": "s", "scope": ["src/typo.py"]}],
                    dry_run=False,
                )

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertEqual([commander["id"] for commander in registry["commanders"]], ["L1-星辰军团"])
            self.assertTrue(registry["commanders"][0]["synthetic_runtime"])
            self.assertEqual(registry["tasks"][0]["commander"], "L1-星辰军团")
            self.assertEqual(registry["tasks"][0]["origin_commander"], "L1-星辰军团")
            self.assertEqual(registry["tasks"][0]["complexity"], "s")

    def test_l2_campaign_defaults_to_direct_same_level_worker(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            with patch.dict(os.environ, {"CLAUDE_CODE_AGENT_NAME": "L2-audit-1"}):
                core.deploy_campaign([{"id": "audit-one", "role": "audit", "task": "audit diff"}], dry_run=False)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertEqual([commander["id"] for commander in registry["commanders"]], ["L2-audit-1"])
            self.assertTrue(registry["commanders"][0]["synthetic_runtime"])
            self.assertEqual(registry["tasks"][0]["commander"], "L2-audit-1")
            self.assertEqual(registry["tasks"][0]["origin_commander"], "L2-audit-1")

    def test_corps_campaign_notifies_l2_assignment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")

            core.deploy_campaign(
                [{"id": "audit-one", "role": "audit", "task": "audit diff"}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commander = next(item for item in registry["commanders"] if item.get("branch") == "audit")
            inbox = core._inbox_file(commander["id"]).read_text(encoding="utf-8")
            self.assertIn("TASK-ASSIGNED", inbox)
            self.assertIn("origin=L1-host", inbox)
            self.assertIn("target=audit diff", inbox)
            self.assertIn("L2 activation is task-scoped", inbox)
            self.assertIn("load only relevant project/tactic/skill context", inbox)

    def test_corps_campaign_blocks_task_when_branch_commander_launch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = BranchCommanderLaunchFailRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            self.register_commander(core, "L1-host")

            core.deploy_campaign(
                [{"id": "audit-one", "role": "audit", "task": "audit diff"}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            task = next(item for item in registry["tasks"] if item["id"] == "audit-one")
            self.assertEqual(task["status"], "blocked")
            self.assertIn("assigned commander unavailable", task["blocked_reason"])
            new_window_commands = [cmd for cmd, _ in runner.commands if cmd[:2] == ["tmux", "new-window"]]
            self.assertEqual(new_window_commands, [])

    def test_launch_ready_tasks_blocks_unknown_assigned_commander(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.init_state()
            spec = TaskSpec.from_mapping({"id": "orphan", "role": "audit", "task": "audit diff"})
            core._upsert_task(spec.as_registry_entry("planned", "L2-missing", core._run_dir(spec)))

            launched = core._launch_ready_tasks()

            task = next(item for item in json.loads(core.registry_file.read_text(encoding="utf-8"))["tasks"] if item["id"] == "orphan")
            self.assertEqual(launched, [])
            self.assertEqual(task["status"], "blocked")
            self.assertIn("unknown commander", task["blocked_reason"])

    def test_host_convenes_project_named_l1_and_claude_codex_l2_commanders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            first = core.convene_host(dry_run=True)
            second = LegionCore(root, legion_home=root / "home", runner=RecordingRunner()).convene_host(dry_run=True)

            host = first["host"]
            self.assertEqual(host["id"], second["host"]["id"])
            self.assertEqual(host["provider"], "claude")
            self.assertEqual(host["role"], "commander")
            self.assertTrue(host["id"].startswith(f"L1-{root.name}-"))
            self.assertTrue(host["id"].endswith("军团"))

            commanders = {item["branch"]: item for item in first["l2"]}
            self.assertEqual(commanders["implement"]["provider"], "claude")
            self.assertEqual(commanders["implement"]["parent"], host["id"])
            self.assertEqual(commanders["audit"]["provider"], "codex")
            self.assertEqual(commanders["audit"]["parent"], host["id"])

    def test_host_convene_sends_readiness_order_to_host(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            convened = core.convene_host(dry_run=False)
            host = convened["host"]
            l2_ids = [commander["id"] for commander in convened["l2"]]

            inbox_lines = core._inbox_file(host["id"]).read_text(encoding="utf-8").splitlines()
            records = [json.loads(line) for line in inbox_lines if line.strip()]
            record = next(item for item in records if item["type"] == "readiness-order")
            self.assertEqual(record["type"], "readiness-order")
            self.assertIn("INIT-READY-REQUEST", record["content"])
            self.assertIn("READY:init-complete", record["content"])
            self.assertIn("--parent", record["content"])
            self.assertIn("轻量任务激活检查", record["content"])
            self.assertIn("相关技能工具", record["content"])
            self.assertIn("必要预研", record["content"])
            self.assertIn("mixed readiness", record["content"])
            self.assertIn("--wait --timeout 180", record["content"])
            for commander_id in [host["id"], *l2_ids]:
                self.assertIn(commander_id, record["content"])

    def test_dual_host_convenes_provider_owned_l1s_without_base_l2_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            first = core.convene_dual_host(dry_run=True)
            second = LegionCore(root, legion_home=root / "home", runner=RecordingRunner()).convene_dual_host(dry_run=True)

            self.assertEqual(first["claude_l1"]["id"], second["claude_l1"]["id"])
            self.assertEqual(first["codex_l1"]["id"], second["codex_l1"]["id"])
            self.assertNotEqual(first["claude_l1"]["id"], first["codex_l1"]["id"])
            self.assertEqual(first["claude_l1"]["provider"], "claude")
            self.assertEqual(first["codex_l1"]["provider"], "codex")
            self.assertEqual(first["l2"], [])
            self.assertIsNone(first["claude_l2"])
            self.assertIsNone(first["codex_l2"])
            self.assertFalse(first["base_l2"])

    def test_dual_host_sends_delayed_peer_sync_between_l1s(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            convened = core.convene_dual_host(dry_run=False, peer_delay_seconds=0)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertNotIn("readiness_orders", registry)
            claude_inbox = core._inbox_file(convened["claude_l1"]["id"]).read_text(encoding="utf-8")
            codex_inbox = core._inbox_file(convened["codex_l1"]["id"]).read_text(encoding="utf-8")
            self.assertIn('"type": "peer-sync"', claude_inbox)
            self.assertIn('"type": "peer-sync"', codex_inbox)
            self.assertIn(convened["codex_l1"]["id"], claude_inbox)
            self.assertIn(convened["claude_l1"]["id"], codex_inbox)
            self.assertIn("delay=1s", claude_inbox)
            self.assertIn("delay=1s", codex_inbox)

    def test_l1_online_notifies_peer_l1_and_queues_aicto_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core._upsert_commander(
                {
                    "id": "L1-peer",
                    "provider": "codex",
                    "role": "commander",
                    "level": 1,
                    "status": "commanding",
                    "session": "peer-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            commander = core.start_commander(provider="claude", name="alpha", dry_run=False, attach=False)

            peer_inbox = core._inbox_file("L1-peer").read_text(encoding="utf-8")
            self.assertIn('"type": "peer-online"', peer_inbox)
            self.assertIn(commander["id"], peer_inbox)
            reports = [json.loads(line) for line in core.aicto_reports_file.read_text(encoding="utf-8").splitlines()]
            online_reports = [record for record in reports if record["kind"] == "l1-online"]
            self.assertEqual(online_reports[-1]["subject_id"], commander["id"])
            self.assertIn("L1-peer", online_reports[-1]["payload"]["peer_l1"])
            self.assertEqual(
                online_reports[-1]["payload"]["aicto_authority"]["control_plane"],
                "external-hermes-aicto",
            )
            self.assertEqual(online_reports[-1]["payload"]["awaiting_directives_from"], "AICTO-CTO")
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            registered = next(item for item in registry["commanders"] if item["id"] == commander["id"])
            self.assertEqual(registered["aicto_authority"]["authority"], "project-l1-command")
            self.assertEqual(registered["command_chains"]["aicto"]["status"], "connected")
            self.assertEqual(registered["command_chains"]["local_l1"]["status"], "connected")
            self.assertIn("L1-peer", registered["command_chains"]["local_l1"]["peer_l1"])

    def test_l1_enters_command_chain_only_after_external_aicto_handshake(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            handshake = {
                "status": "connected",
                "actual_communication": True,
                "message_id": "msg-aicto-online",
                "mixed_inbox_written": True,
                "legacy_inbox_written": True,
            }

            with patch.object(LegionCore, "_connect_aicto_command_chain", return_value=handshake, create=True) as connect:
                commander = core.start_commander(provider="claude", name="alpha", dry_run=False, attach=False)

            connect.assert_called_once()
            self.assertEqual(commander["status"], "commanding")
            self.assertEqual(commander["aicto_link"]["status"], "connected")
            self.assertTrue(commander["aicto_link"]["actual_communication"])
            self.assertEqual(commander["command_chains"]["aicto"]["status"], "connected")
            self.assertEqual(commander["command_chains"]["local_l1"]["status"], "no-peer-l1")
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            registered = next(item for item in registry["commanders"] if item["id"] == commander["id"])
            self.assertEqual(registered["aicto_link"]["message_id"], "msg-aicto-online")
            self.assertEqual(registered["command_chains"]["aicto"]["message_id"], "msg-aicto-online")

    def test_l1_is_isolated_when_external_aicto_handshake_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            with patch.object(
                LegionCore,
                "_connect_aicto_command_chain",
                side_effect=RuntimeError("external Hermes AICTO unreachable"),
                create=True,
            ):
                commander = core.start_commander(provider="claude", name="alpha", dry_run=False, attach=False)

            self.assertEqual(commander["status"], "isolated")
            self.assertEqual(commander["aicto_link"]["status"], "isolated")
            self.assertFalse(commander["aicto_link"]["actual_communication"])
            self.assertIn("external Hermes AICTO unreachable", commander["aicto_link"]["failure"])
            self.assertEqual(commander["command_chains"]["aicto"]["status"], "isolated")
            self.assertEqual(commander["command_chains"]["local_l1"]["status"], "not-established")
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            registered = next(item for item in registry["commanders"] if item["id"] == commander["id"])
            self.assertEqual(registered["status"], "isolated")
            events = [json.loads(line) for line in core.events_file.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events[-1]["event"], "aicto_command_chain_failed")

    def test_external_l1_registration_requires_external_aicto_handshake(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            handshake = {
                "status": "connected",
                "actual_communication": True,
                "message_id": "msg-register",
                "mixed_inbox_written": True,
                "legacy_inbox_written": True,
            }

            with patch.object(LegionCore, "_connect_aicto_command_chain", return_value=handshake, create=True) as connect:
                commander = core.register_external_commander(
                    provider="claude",
                    commander_id="L1-青龙军团",
                    session="legion-test-L1-青龙军团",
                    status="commanding",
                )

            connect.assert_called_once()
            self.assertEqual(commander["status"], "commanding")
            self.assertEqual(commander["aicto_link"]["status"], "connected")
            self.assertEqual(commander["command_chains"]["aicto"]["status"], "connected")

    def test_marking_l1_commanding_requires_external_aicto_handshake(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core._upsert_commander(
                {
                    "id": "L1-launching",
                    "provider": "claude",
                    "role": "commander",
                    "level": 1,
                    "status": "launching",
                    "session": "legion-test-L1-launching",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            with patch.object(
                LegionCore,
                "_connect_aicto_command_chain",
                side_effect=RuntimeError("external Hermes AICTO unreachable"),
            ):
                core.mark_commander("L1-launching", "commanding")

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            registered = next(item for item in registry["commanders"] if item["id"] == "L1-launching")
            self.assertEqual(registered["status"], "isolated")
            self.assertEqual(registered["command_chains"]["aicto"]["status"], "isolated")
            self.assertEqual(registered["command_chains"]["local_l1"]["status"], "not-established")

    def test_manual_aicto_report_is_durable_and_readable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            record = core.queue_aicto_report(
                kind="problem",
                subject_id="L1-host",
                summary="blocked on missing dependency",
                source="L1-host",
            )

            self.assertTrue(core.aicto_reports_file.exists())
            text = core.aicto_reports_text()
            self.assertIn(record["id"], core.aicto_reports_file.read_text(encoding="utf-8"))
            self.assertIn("problem L1-host: blocked on missing dependency", text)
            self.assertEqual(record["payload"]["aicto_authority"]["directive_sender"], "AICTO-CTO")

    def test_l1_prompt_declares_aicto_authority_and_next_directive_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            prompt = core.render_commander_prompt("L1-alpha", "claude")

            self.assertIn("External Hermes AICTO is the 总指挥部指挥链", prompt)
            self.assertIn("Same-project L1 peers are the 本地 L1 指挥链", prompt)
            self.assertIn("Peer-sync/local inbox communication never substitutes for AICTO", prompt)
            self.assertIn("AICTO-CTO", prompt)
            self.assertIn("next_directive_request", prompt)
            self.assertIn("report to AICTO and request the next directive", prompt)

    def test_dual_host_base_l2_mode_sends_independent_readiness_orders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            convened = core.convene_dual_host(dry_run=False, base_l2=True, peer_delay_seconds=0)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            orders = registry["readiness_orders"]
            self.assertEqual(orders[convened["claude_l1"]["id"]]["expected"], [convened["claude_l2"]["id"]])
            self.assertEqual(orders[convened["codex_l1"]["id"]]["expected"], [convened["codex_l2"]["id"]])
            claude_inbox = core._inbox_file(convened["claude_l1"]["id"]).read_text(encoding="utf-8")
            codex_inbox = core._inbox_file(convened["codex_l1"]["id"]).read_text(encoding="utf-8")
            self.assertIn(convened["claude_l2"]["id"], claude_inbox)
            self.assertIn(convened["codex_l2"]["id"], codex_inbox)
            self.assertNotIn(convened["codex_l2"]["id"], claude_inbox)
            self.assertNotIn(convened["claude_l2"]["id"], codex_inbox)

    def test_l1_only_dual_host_clears_stale_base_l2_readiness_orders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            old = core.convene_dual_host(dry_run=False, base_l2=True, peer_delay_seconds=0)
            core.mark_commander(old["claude_l2"]["id"], "completed")
            core.mark_commander(old["codex_l2"]["id"], "completed")

            current = core.convene_dual_host(dry_run=False, base_l2=False, peer_delay_seconds=0)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertNotIn(current["claude_l1"]["id"], registry.get("readiness_orders", {}))
            self.assertNotIn(current["codex_l1"]["id"], registry.get("readiness_orders", {}))
            codex_readiness = core.readiness_text(current["codex_l1"]["id"])
            self.assertIn("Expected L2: (none)", codex_readiness)
            self.assertIn("Ready: 0/0", codex_readiness)

    def test_dual_host_fails_before_readiness_when_launch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = SelectiveFailRunner([["tmux", "has-session"], ["tmux", "new-session"]])
            core = LegionCore(root, legion_home=root / "home", runner=runner)

            with self.assertRaises(SystemExit) as raised:
                core.convene_dual_host(dry_run=False)

            self.assertIn("launch failed before dual-L1 readiness", str(raised.exception))
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            self.assertNotIn("readiness_orders", registry)

    def test_external_aicto_status_points_to_hermes_profile_not_local_l0(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "AICTO"
            (project / "hermes-plugin").mkdir(parents=True)

            with patch("scripts.legion_core.subprocess.run", side_effect=FileNotFoundError()):
                text = external_aicto_status_text(project)

            self.assertIn("external Hermes CTO project", text)
            self.assertIn("not a local Legion L0 commander", text)
            self.assertIn("nohup aicto gateway run", text)
            self.assertIn("Use `legion host` for Claude L1 + Codex L1", text)
            self.assertNotIn("planned:", text)
            self.assertNotIn("L0-", text)

    def test_campaign_launches_only_dependency_ready_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)

            core.deploy_campaign(
                [
                    {"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]},
                    {"id": "review", "role": "review", "task": "review feature", "depends_on": ["implement"]},
                ],
                dry_run=False,
            )

            new_window_commands = [cmd for cmd, _ in runner.commands if cmd[:2] == ["tmux", "new-window"]]
            self.assertEqual(len(new_window_commands), 1)
            self.assertIn("w-implement", new_window_commands[0])

            tasks = {item["id"]: item for item in json.loads(core.registry_file.read_text())["tasks"]}
            self.assertEqual(tasks["implement"]["status"], "launched")
            self.assertEqual(tasks["review"]["status"], "planned")

    def test_completed_task_advances_newly_unblocked_dependents(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [
                    {"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]},
                    {"id": "review", "role": "review", "task": "review feature", "depends_on": ["implement"]},
                ],
                dry_run=False,
            )
            core.ensure_tmux_session()
            runner.commands.clear()

            core.mark_task("implement", "completed")

            new_window_commands = [cmd for cmd, _ in runner.commands if cmd[:2] == ["tmux", "new-window"]]
            self.assertEqual(len(new_window_commands), 1)
            self.assertIn("w-review", new_window_commands[0])
            tasks = {item["id"]: item for item in json.loads(core.registry_file.read_text())["tasks"]}
            self.assertEqual(tasks["review"]["status"], "launched")

    def test_failed_task_blocks_dependents(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [
                    {"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]},
                    {"id": "review", "role": "review", "task": "review feature", "depends_on": ["implement"]},
                ],
                dry_run=False,
            )

            core.mark_task("implement", "failed")

            tasks = {item["id"]: item for item in json.loads(core.registry_file.read_text())["tasks"]}
            self.assertEqual(tasks["review"]["status"], "blocked")
            self.assertIn("blocked_reason", tasks["review"])

    def test_explicit_reconcile_marks_missing_running_window_as_failed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=MissingWindowRunner())
            core.deploy_campaign(
                [
                    {"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]},
                    {"id": "review", "role": "review", "task": "review feature", "depends_on": ["implement"]},
                ],
                dry_run=False,
            )
            running = core._task_entry("implement")
            running["status"] = "running"
            running["window"] = "w-implement"
            core._upsert_task(running)

            # Status is read-only and must not mutate state.
            core.status_text()
            tasks_before = {item["id"]: item for item in json.loads(core.registry_file.read_text())["tasks"]}
            self.assertEqual(tasks_before["implement"]["status"], "running")
            self.assertEqual(tasks_before["review"]["status"], "planned")

            # Reconcile is the explicit mutation entry point.
            core.reconcile_state()

            tasks = {item["id"]: item for item in json.loads(core.registry_file.read_text())["tasks"]}
            self.assertEqual(tasks["implement"]["status"], "failed")
            self.assertIn("tmux window is not alive", tasks["implement"]["failure"])
            self.assertEqual(tasks["review"]["status"], "blocked")

    def test_reconcile_checks_task_window_in_recorded_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner(
                {"worker-session", "commander-session"},
                windows={"worker-session": ["w-implement"], "commander-session": []},
            )
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            spec = TaskSpec.from_mapping(
                {"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]}
            )
            entry = spec.as_registry_entry("running", "L2-implement-1", core._run_dir(spec))
            entry["window"] = "w-implement"
            entry["session"] = "worker-session"
            core._upsert_task(entry)

            core.reconcile_state()

            task = next(item for item in json.loads(core.registry_file.read_text())["tasks"] if item["id"] == "implement")
            self.assertEqual(task["status"], "running")

    def test_worker_schema_status_overrides_successful_process_exit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign([{"id": "audit", "role": "audit", "task": "audit diff"}], dry_run=False)
            result_file = core._run_dir(TaskSpec.from_mapping({"id": "audit", "task": "audit diff"})) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(
                worker_result_json(status="blocked", summary="need implementation first"),
                encoding="utf-8",
            )

            core.complete_task_from_result("audit", result_file, 0)

            task = json.loads(core.registry_file.read_text())["tasks"][0]
            self.assertEqual(task["status"], "blocked")

    def test_task_terminal_status_queues_aicto_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign([{"id": "audit", "role": "audit", "task": "audit diff"}], dry_run=False)
            result_file = core._run_dir(TaskSpec.from_mapping({"id": "audit", "task": "audit diff"})) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(worker_result_json(status="completed", summary="audit passed"), encoding="utf-8")

            core.complete_task_from_result("audit", result_file, 0)

            reports = [json.loads(line) for line in core.aicto_reports_file.read_text(encoding="utf-8").splitlines()]
            task_reports = [record for record in reports if record["subject_id"] == "audit"]
            self.assertEqual(task_reports[-1]["kind"], "task-completed")
            self.assertIn("audit completed: audit passed", task_reports[-1]["summary"])
            self.assertIn("requesting next AICTO directive", task_reports[-1]["summary"])
            self.assertEqual(task_reports[-1]["payload"]["status"], "completed")
            request = task_reports[-1]["payload"]["next_directive_request"]
            self.assertTrue(request["required"])
            self.assertEqual(request["request_type"], "next-task")
            self.assertEqual(request["requested_from"], "AICTO-CTO")
            events = [json.loads(line) for line in core.events_file.read_text(encoding="utf-8").splitlines()]
            next_events = [event for event in events if event["event"] == "aicto_next_directive_requested"]
            self.assertEqual(next_events[-1]["task_id"], "audit")
            self.assertEqual(next_events[-1]["payload"]["request_type"], "next-task")

    def test_claude_plain_text_worker_success_is_failed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [{"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]}],
                dry_run=False,
            )
            result_file = core._run_dir(TaskSpec.from_mapping({"id": "implement", "task": "add feature"})) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("implemented and verified", encoding="utf-8")

            core.complete_task_from_result("implement", result_file, 0)

            task = json.loads(core.registry_file.read_text())["tasks"][0]
            self.assertEqual(task["status"], "failed")
            self.assertIn("worker result was not valid JSON", task["failure"])

    def test_worker_result_must_be_whole_file_json_not_prose_wrapped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign(
                [{"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]}],
                dry_run=False,
            )
            result_file = core._run_dir(TaskSpec.from_mapping({"id": "implement", "task": "add feature"})) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(f"done\n{worker_result_json()}\n", encoding="utf-8")

            core.complete_task_from_result("implement", result_file, 0)

            task = json.loads(core.registry_file.read_text())["tasks"][0]
            self.assertEqual(task["status"], "failed")
            self.assertIn("worker result was not valid JSON", task["failure"])

    def test_worker_result_schema_validation_rejects_bad_nested_items(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign([{"id": "verify", "role": "verify", "task": "verify diff"}], dry_run=False)
            result_file = core._run_dir(TaskSpec.from_mapping({"id": "verify", "task": "verify diff"})) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(
                worker_result_json(
                    status="completed",
                    verification=[{"command": "pytest", "result": "pass", "details": 3}],
                ),
                encoding="utf-8",
            )

            core.complete_task_from_result("verify", result_file, 0)

            task = json.loads(core.registry_file.read_text())["tasks"][0]
            self.assertEqual(task["status"], "failed")
            self.assertIn("worker result failed schema validation", task["failure"])
            self.assertIn("verification[0]", task["failure"])

            core.deploy_campaign([{"id": "audit-findings", "role": "audit", "task": "audit findings"}], dry_run=False)
            result_file = core._run_dir(TaskSpec.from_mapping({"id": "audit-findings", "task": "audit findings"})) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(
                worker_result_json(
                    status="completed",
                    findings=[
                        {
                            "severity": "major",
                            "file": None,
                            "line": 0,
                            "description": "bad line",
                            "recommendation": None,
                        }
                    ],
                ),
                encoding="utf-8",
            )

            core.complete_task_from_result("audit-findings", result_file, 0)

            tasks = {item["id"]: item for item in json.loads(core.registry_file.read_text())["tasks"]}
            self.assertEqual(tasks["audit-findings"]["status"], "failed")
            self.assertIn("findings[0]", tasks["audit-findings"]["failure"])

    def test_worker_result_schema_validation_rejects_string_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign([{"id": "verify", "role": "verify", "task": "verify diff"}], dry_run=False)
            result_file = core._run_dir(TaskSpec.from_mapping({"id": "verify", "task": "verify diff"})) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(
                worker_result_json(
                    status="completed",
                    verification="python3 -m unittest tests/test_legion_core.py -v",
                ),
                encoding="utf-8",
            )

            core.complete_task_from_result("verify", result_file, 0)

            task = json.loads(core.registry_file.read_text())["tasks"][0]
            self.assertEqual(task["status"], "failed")
            self.assertIn("verification must be an array", task["failure"])

    def test_tmux_launch_failure_marks_task_failed_without_claiming_launched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = SelectiveFailRunner(["tmux", "new-window"])
            core = LegionCore(root, legion_home=root / "home", runner=runner)

            core.deploy_campaign(
                [{"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]}],
                dry_run=False,
            )

            task = json.loads(core.registry_file.read_text())["tasks"][0]
            self.assertEqual(task["status"], "failed")
            self.assertIn("simulated failure", task["failure"])

    def test_completed_branch_commander_is_not_reused_for_new_corps_campaign(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            first = core.create_branch_commander("audit", parent="L1-青龙军团", dry_run=False)
            core.mark_commander(first["id"], "completed")

            second = core.create_branch_commander("audit", parent="L1-青龙军团", dry_run=False)

            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(second["status"], "commanding")

    def test_completed_campaign_l2_disbands_when_context_not_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [{"id": "frontend-done", "branch": "frontend", "task": "finish frontend slice", "scope": ["src/frontend.py"]}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commander = next(item for item in registry["commanders"] if item.get("branch") == "frontend")
            result_file = Path(registry["tasks"][0]["run_dir"]) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(worker_result_json(), encoding="utf-8")

            core.complete_task_from_result("frontend-done", result_file, 0)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            retired = next(item for item in registry["commanders"] if item["id"] == commander["id"])
            self.assertEqual(retired["lifecycle"], "campaign")
            self.assertEqual(retired["status"], "completed")
            self.assertIn("disbanded_reason", retired)
            self.assertTrue(retired["tmux_killed"])
            inbox = core._inbox_file(commander["id"]).read_text(encoding="utf-8")
            self.assertIn("DISBAND:init-complete", inbox)
            kill_commands = [cmd for cmd, _ in runner.commands if cmd[:2] == ["tmux", "kill-session"]]
            self.assertTrue(kill_commands)

    def test_completed_campaign_l2_retains_context_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [
                    {
                        "id": "frontend-keep",
                        "branch": "frontend",
                        "task": "finish frontend slice",
                        "scope": ["src/frontend.py"],
                        "retain_context": True,
                    }
                ],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commander = next(item for item in registry["commanders"] if item.get("branch") == "frontend")
            result_file = Path(registry["tasks"][0]["run_dir"]) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(worker_result_json(), encoding="utf-8")

            core.complete_task_from_result("frontend-keep", result_file, 0)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            retained = next(item for item in registry["commanders"] if item["id"] == commander["id"])
            self.assertEqual(retained["status"], "commanding")
            kill_commands = [cmd for cmd, _ in runner.commands if cmd[:2] == ["tmux", "kill-session"]]
            self.assertFalse(kill_commands)

    def test_failed_campaign_l2_retains_context_for_diagnosis_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [{"id": "frontend-fail", "branch": "frontend", "task": "fail frontend slice", "scope": ["src/frontend.py"]}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commander = next(item for item in registry["commanders"] if item.get("branch") == "frontend")
            result_file = Path(registry["tasks"][0]["run_dir"]) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("failed", encoding="utf-8")

            core.complete_task_from_result("frontend-fail", result_file, 1)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            retained = next(item for item in registry["commanders"] if item["id"] == commander["id"])
            self.assertEqual(retained["status"], "commanding")
            self.assertEqual(registry["tasks"][0]["status"], "failed")

    def test_host_l2_is_not_auto_disbanded_after_completed_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = RecordingRunner()
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            convened = core.convene_host(host_name="host", dry_run=False)
            host_id = convened["host"]["id"]
            implement_l2 = next(item for item in convened["l2"] if item["branch"] == "implement")
            core.deploy_campaign(
                [
                    {
                        "id": "host-implement-done",
                        "branch": "implement",
                        "task": "finish host implement task",
                        "scope": ["src/host.py"],
                    }
                ],
                commander=host_id,
                dry_run=False,
                corps=True,
            )
            task = next(item for item in json.loads(core.registry_file.read_text(encoding="utf-8"))["tasks"] if item["id"] == "host-implement-done")
            result_file = Path(task["run_dir"]) / "result.md"
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(worker_result_json(), encoding="utf-8")

            core.complete_task_from_result("host-implement-done", result_file, 0)

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commander = next(item for item in registry["commanders"] if item["id"] == implement_l2["id"])
            self.assertEqual(commander["lifecycle"], "host")
            self.assertNotEqual(commander["status"], "completed")

    def test_external_claude_l1_registers_in_mixed_registry_for_cross_visibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            commander = core.register_external_commander(
                provider="claude",
                commander_id="L1-青龙军团",
                session="legion-test-L1-青龙军团",
                status="commanding",
            )

            self.assertEqual(commander["id"], "L1-青龙军团")
            self.assertEqual(commander["provider"], "claude")
            self.assertEqual(commander["level"], 1)
            self.assertEqual(commander["status"], "commanding")

            status = core.status_text()
            self.assertIn("L1-青龙军团", status)
            self.assertIn("claude", status)

    def test_mixed_msg_to_l2_uses_noninvasive_tmux_notice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"live-audit-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L2-audit-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "status": "commanding",
                    "session": "live-audit-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            record = core.send_message("L2-audit-1", "请审计安全边界", sender="L1-host")

            self.assertTrue(record["delivered_tmux"])
            inbox = core._inbox_file("L2-audit-1").read_text(encoding="utf-8").strip()
            saved = json.loads(inbox)
            self.assertEqual(saved["from"], "L1-host")
            self.assertEqual(saved["to"], "L2-audit-1")
            self.assertEqual(saved["content"], "请审计安全边界")
            commands = [cmd for cmd, _ in runner.commands]
            send_commands = [cmd for cmd in commands if cmd[:2] == ["tmux", "send-keys"]]
            notices = [cmd for cmd in commands if cmd[:2] == ["tmux", "display-message"]]
            self.assertFalse(send_commands)
            self.assertTrue(notices)
            self.assertIn("Legion inbox: L1-host -> L2-audit-1", " ".join(notices[0]))

    def test_mixed_msg_to_l1_uses_noninvasive_tmux_notice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"live-host-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L1-host",
                    "provider": "claude",
                    "role": "commander",
                    "status": "commanding",
                    "session": "live-host-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            record = core.send_message("L1-host", "READY:init-complete", sender="L2-audit-1")

            self.assertTrue(record["delivered_tmux"])
            commands = [cmd for cmd, _ in runner.commands]
            send_commands = [cmd for cmd in commands if cmd[:2] == ["tmux", "send-keys"]]
            notices = [cmd for cmd in commands if cmd[:2] == ["tmux", "display-message"]]
            self.assertFalse(send_commands)
            self.assertTrue(notices)
            self.assertIn("Legion inbox: L2-audit-1 -> L1-host", " ".join(notices[0]))

    def test_init_ready_request_to_idle_commander_stays_noninvasive_notice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = CapturePaneRunner(
                {"live-host-session"},
                {"live-host-session": "startup checks complete\n\u276f \ntransient footer"},
            )
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L1-host",
                    "provider": "claude",
                    "role": "commander",
                    "status": "commanding",
                    "session": "live-host-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            record = core.send_message(
                "L1-host",
                "INIT-READY-REQUEST order_id=ord-1 nonce=n1",
                sender="Legion Core",
                message_type="readiness-order",
            )

            self.assertTrue(record["delivered_tmux"])
            commands = [cmd for cmd, _ in runner.commands]
            capture_commands = [cmd for cmd in commands if cmd[:2] == ["tmux", "capture-pane"]]
            send_commands = [cmd for cmd in commands if cmd[:2] == ["tmux", "send-keys"]]
            notices = [cmd for cmd in commands if cmd[:2] == ["tmux", "display-message"]]
            self.assertFalse(capture_commands)
            self.assertFalse(send_commands)
            self.assertTrue(notices)
            self.assertIn("Legion inbox: Legion Core -> L1-host readiness-order", " ".join(notices[0]))

    def test_init_ready_request_to_busy_commander_stays_noninvasive_notice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = CapturePaneRunner(
                {"live-host-session"},
                {"live-host-session": "running startup checks\nstill working"},
            )
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L1-host",
                    "provider": "claude",
                    "role": "commander",
                    "status": "commanding",
                    "session": "live-host-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            record = core.send_message(
                "L1-host",
                "INIT-READY-REQUEST order_id=ord-1 nonce=n1",
                sender="Legion Core",
                message_type="readiness-order",
            )

            self.assertTrue(record["delivered_tmux"])
            commands = [cmd for cmd, _ in runner.commands]
            send_commands = [cmd for cmd in commands if cmd[:2] == ["tmux", "send-keys"]]
            notices = [cmd for cmd in commands if cmd[:2] == ["tmux", "display-message"]]
            self.assertFalse(send_commands)
            self.assertTrue(notices)
            self.assertIn("Legion inbox: Legion Core -> L1-host readiness-order", " ".join(notices[0]))

    def test_mixed_msg_keeps_inbox_record_when_commander_session_is_offline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            core._upsert_commander(
                {
                    "id": "L2-audit-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "status": "commanding",
                    "session": "missing-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            record = core.send_message("L2-audit-1", "离线也要留痕", sender="L1-host")

            self.assertFalse(record["delivered_tmux"])
            saved = json.loads(core._inbox_file("L2-audit-1").read_text(encoding="utf-8"))
            self.assertEqual(saved["content"], "离线也要留痕")

    def test_mixed_broadcast_targets_active_l2_commanders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"audit-session", "implement-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            for commander in [
                ("L1-host", "claude", "commander", "", "commanding", "host-session"),
                ("L2-implement-1", "claude", "branch-commander", "implement", "commanding", "implement-session"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "commanding", "audit-session"),
                ("L2-stale-1", "codex", "branch-commander", "audit", "commanding", "stale-session"),
                ("L2-old-1", "codex", "branch-commander", "audit", "failed", "old-session"),
            ]:
                commander_id, provider, role, branch, status, session = commander
                core._upsert_commander(
                    {
                        "id": commander_id,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )

            records = core.broadcast_message("全体 L2 汇报状态", sender="L1-host", l2_only=True)

            self.assertEqual([record["to"] for record in records], ["L2-implement-1", "L2-audit-1"])
            self.assertTrue(core._inbox_file("L2-implement-1").exists())
            self.assertTrue(core._inbox_file("L2-audit-1").exists())
            self.assertFalse(core._inbox_file("L2-stale-1").exists())
            self.assertFalse(core._inbox_file("L2-old-1").exists())

    def test_mixed_broadcast_can_target_direct_l2_by_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"child-session", "other-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            for commander in [
                ("L2-child-1", "claude", "branch-commander", "implement", "L1-host", "commanding", "child-session"),
                ("L2-other-1", "codex", "branch-commander", "audit", "L1-other", "commanding", "other-session"),
            ]:
                commander_id, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": commander_id,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )

            records = core.broadcast_message("直属 L2 汇报初始化", sender="L1-host", l2_only=True, parent="L1-host")

            self.assertEqual([record["to"] for record in records], ["L2-child-1"])
            self.assertTrue(core._inbox_file("L2-child-1").exists())
            self.assertFalse(core._inbox_file("L2-other-1").exists())

    def test_broadcast_uses_shared_correlation_and_idempotent_inbox_records(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"child-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L2-child-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "branch": "audit",
                    "parent": "L1-host",
                    "status": "commanding",
                    "session": "child-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            first = core.broadcast_message("status please", sender="L1-host", l2_only=True, parent="L1-host", correlation_id="corr-fixed")
            second = core.broadcast_message("status please", sender="L1-host", l2_only=True, parent="L1-host", correlation_id="corr-fixed")

            self.assertEqual(first[0]["id"], second[0]["id"])
            self.assertTrue(first[0]["appended"])
            self.assertFalse(second[0]["appended"])
            inbox_lines = core._inbox_file("L2-child-1").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(inbox_lines), 1)
            saved = json.loads(inbox_lines[0])
            self.assertEqual(saved["schema_version"], 1)
            self.assertEqual(saved["correlation_id"], "corr-fixed")
            events = [json.loads(line) for line in core.events_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(event["event"] == "broadcast_snapshot" and event["correlation_id"] == "corr-fixed" for event in events))

    def test_message_sent_event_correlation_matches_inbox_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=NamedSessionRunner({"child-session"}))
            core._upsert_commander(
                {
                    "id": "L2-child-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "branch": "audit",
                    "parent": "L1-host",
                    "status": "commanding",
                    "session": "child-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            record = core.send_message("L2-child-1", "status please", sender="L1-host", correlation_id="corr-fixed")

            inbox_lines = core._inbox_file("L2-child-1").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(inbox_lines), 1)
            saved = json.loads(inbox_lines[0])
            events = self.read_events(core)
            message_events = [event for event in events if event.get("event") == "message_sent"]
            self.assertTrue(message_events)
            message_event = message_events[-1]
            self.assert_release_event_record(message_event, "message_sent", "L2-child-1")
            self.assertEqual(record["correlation_id"], "corr-fixed")
            self.assertEqual(saved["correlation_id"], "corr-fixed")
            self.assertEqual(message_event["correlation_id"], "corr-fixed")
            self.assertEqual(message_event["payload"]["correlation_id"], saved["correlation_id"])
            self.assertEqual(message_event["payload"]["id"], saved["id"])

    def test_readiness_text_tracks_expected_l2_ready_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(
                root,
                legion_home=root / "home",
                runner=NamedSessionRunner({"host-session", "impl-session", "audit-session"}),
            )
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-implement-1", "claude", "branch-commander", "implement", "L1-host", "commanding", "impl-session"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "L1-host", "commanding", "audit-session"),
            ]:
                commander_id, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": commander_id,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )
            with patch.dict(
                os.environ,
                {
                    "LEGION_COMMANDER_ID": "L2-audit-1",
                    "CLAUDE_CODE_AGENT_NAME": "L2-audit-1",
                    "CLAUDE_LEGION_TEAM_ID": "L2-audit-1",
                    "LEGION_COMMANDER_SESSION": "audit-session",
                },
            ):
                core.send_message(
                    "L1-host",
                    "READY:init-complete branch=audit provider=codex weapons=loaded tactics=loaded inbox=empty",
                    sender="L2-audit-1",
                )

            report = core.readiness_text("L1-host")

            self.assertIn("Ready: 1/2", report)
            self.assertIn("L2-audit-1", report)
            self.assertIn("Missing: L2-implement-1", report)

    def test_wait_readiness_returns_when_all_expected_l2_are_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=NamedSessionRunner({"host-session", "audit-session"}))
            core._upsert_commander(
                {
                    "id": "L1-host",
                    "provider": "claude",
                    "role": "commander",
                    "status": "commanding",
                    "session": "host-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )
            # L2 must be registered as a direct branch-commander of the parent for
            # readiness validation to count its reply (non-forgeable sender).
            core._upsert_commander(
                {
                    "id": "L2-audit-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "branch": "audit",
                    "parent": "L1-host",
                    "status": "commanding",
                    "session": "audit-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )
            with patch.dict(
                os.environ,
                {
                    "LEGION_COMMANDER_ID": "L2-audit-1",
                    "CLAUDE_CODE_AGENT_NAME": "L2-audit-1",
                    "CLAUDE_LEGION_TEAM_ID": "L2-audit-1",
                    "LEGION_COMMANDER_SESSION": "audit-session",
                },
            ):
                core.send_message("L1-host", "READY:init-complete branch=audit", sender="L2-audit-1")

            ok, report = core.wait_readiness("L1-host", expected=["L2-audit-1"], timeout=0, interval=0.5)

            self.assertTrue(ok)
            self.assertIn("Ready: 1/1", report)
            self.assertIn("Missing: (none)", report)

    def test_view_targets_select_newest_live_host_with_direct_l2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"old-host", "new-host", "impl-session", "audit-session", "other-host", "other-l2"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            for commander in [
                ("L1-old", "claude", "commander", "", "", "", "commanding", "old-host", "2026-04-25T00:00:00Z"),
                ("L1-new", "claude", "commander", "", "", "", "commanding", "new-host", "2026-04-25T01:00:00Z"),
                ("L2-implement-1", "claude", "branch-commander", "implement", "L1-new", "host", "commanding", "impl-session", "2026-04-25T01:00:01Z"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "L1-new", "host", "commanding", "audit-session", "2026-04-25T01:00:02Z"),
            ]:
                commander_id, provider, role, branch, parent, lifecycle, status, session, updated = commander
                core._upsert_commander(
                    {
                        "id": commander_id,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "lifecycle": lifecycle,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": updated,
                    }
                )
            for commander in [
                ("L1-other-project", "claude", "commander", "", "", "", "commanding", "other-host", "2026-04-25T02:00:00Z"),
                ("L2-other-project", "claude", "branch-commander", "implement", "L1-other-project", "host", "commanding", "other-l2", "2026-04-25T02:00:01Z"),
            ]:
                commander_id, provider, role, branch, parent, lifecycle, status, session, updated = commander
                core._upsert_commander(
                    {
                        "id": commander_id,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "lifecycle": lifecycle,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root / "other-project"),
                        "updated": updated,
                    }
                )

            targets = core.view_targets()

            self.assertEqual([target["id"] for target in targets], ["L1-new", "L2-implement-1", "L2-audit-1"])
            self.assertEqual([target["session"] for target in targets], ["new-host", "impl-session", "audit-session"])

    def test_dual_view_targets_include_both_provider_l1s(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            convened = core.convene_dual_host(dry_run=True)

            targets = core.dual_view_targets(convened=convened)

            self.assertEqual(
                [target["id"] for target in targets],
                [
                    convened["claude_l1"]["id"],
                    convened["codex_l1"]["id"],
                ],
            )
            self.assertEqual(targets[0]["label"], "L1 Claude")
            self.assertEqual(targets[-1]["label"], "L1 Codex")

    def test_dual_view_rejects_dead_convened_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            convened = core.convene_dual_host(dry_run=True)
            convened["claude_l1"]["status"] = "commanding"

            with self.assertRaises(SystemExit) as raised:
                core.dual_view_targets(convened=convened)

            self.assertIn("tmux session is not alive", str(raised.exception))

    def test_view_targets_include_base_l2_and_active_task_l2_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner(
                {
                    "host-session",
                    "impl-session",
                    "audit-session",
                    "backend-session",
                    "verify-session",
                    "idle-session",
                    "other-task-session",
                }
            )
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            runner.live_sessions.add(core.context.session_name)
            runner.windows[core.context.session_name] = ["w-active-backend"]
            for commander in [
                ("L1-host", "claude", "commander", "", "", "", "commanding", "host-session"),
                ("L1-other", "claude", "commander", "", "", "", "commanding", "other-host-session"),
                ("L2-implement-base", "claude", "branch-commander", "implement", "L1-host", "host", "commanding", "impl-session"),
                ("L2-audit-base", "codex", "branch-commander", "audit", "L1-host", "host", "commanding", "audit-session"),
                ("L2-backend-task", "claude", "branch-commander", "backend", "L1-host", "campaign", "commanding", "backend-session"),
                ("L2-verify-task", "codex", "branch-commander", "verify", "L2-audit-base", "campaign", "commanding", "verify-session"),
                ("L2-retained-idle", "claude", "branch-commander", "frontend", "L1-host", "campaign", "commanding", "idle-session"),
                ("L2-other-task", "codex", "branch-commander", "audit", "L1-other", "campaign", "commanding", "other-task-session"),
            ]:
                commander_id, provider, role, branch, parent, lifecycle, status, session = commander
                core._upsert_commander(
                    {
                        "id": commander_id,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "lifecycle": lifecycle,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "2026-04-25T01:00:00Z",
                    }
                )
            for task in [
                {
                    "id": "active-backend",
                    "provider": "claude",
                    "role": "implement",
                    "commander": "L2-backend-task",
                    "status": "running",
                    "window": "w-active-backend",
                    "task": "execute backend slice",
                },
                {
                    "id": "active-verify",
                    "provider": "codex",
                    "role": "verify",
                    "commander": "L2-verify-task",
                    "status": "planned",
                    "task": "verify audit finding",
                },
                {
                    "id": "idle-retained",
                    "provider": "claude",
                    "role": "implement",
                    "commander": "L2-retained-idle",
                    "status": "completed",
                    "retain_context": True,
                    "task": "completed retained context",
                },
                {
                    "id": "other-active",
                    "provider": "codex",
                    "role": "audit",
                    "commander": "L2-other-task",
                    "status": "planned",
                    "task": "other host active task",
                },
            ]:
                core._upsert_task(task)

            targets = core.view_targets(host="L1-host")

            self.assertEqual(
                [target["id"] for target in targets],
                ["L1-host", "L2-implement-base", "L2-audit-base", "L2-backend-task", "L2-verify-task"],
            )
            self.assertEqual(
                [target["label"] for target in targets],
                [
                    "L1",
                    "L2 base implement [claude]",
                    "L2 base audit [codex]",
                    "L2 task backend [claude]",
                    "L2 task verify [codex]",
                ],
            )

    def test_interactive_view_tmux_script_embeds_real_sessions_in_split_panes(self):
        script = build_interactive_view_tmux_script(
            project_dir=Path("/tmp/example project"),
            view_session="legion-view-test",
            targets=[
                {"id": "L1-host", "label": "L1", "session": "host-session"},
                {"id": "L2-impl", "label": "L2 implement [claude]", "session": "impl-session"},
                {"id": "L2-audit", "label": "L2 audit [codex]", "session": "audit-session"},
            ],
            fresh=True,
        )

        self.assertIn('tmux kill-session -t "$VIEW_SESSION"', script)
        self.assertIn('tmux new-session -d -s "$VIEW_SESSION"', script)
        self.assertIn("TMUX= tmux attach -t host-session", script)
        self.assertIn("TMUX= tmux attach -t impl-session", script)
        self.assertIn("TMUX= tmux attach -t audit-session", script)
        self.assertIn("tmux split-window -h -p 60", script)
        self.assertIn("tmux split-window -v -p 50", script)
        self.assertIn("pane-border-status top", script)
        self.assertNotIn("select-layout", script)

    def test_interactive_view_tmux_script_splits_l2_column_evenly(self):
        script = build_interactive_view_tmux_script(
            project_dir=Path("/tmp/example project"),
            view_session="legion-view-test",
            targets=[
                {"id": "L1-host", "label": "L1", "session": "host-session"},
                {"id": "L2-1", "label": "L2 base implement [claude]", "session": "l2-1"},
                {"id": "L2-2", "label": "L2 base audit [codex]", "session": "l2-2"},
                {"id": "L2-3", "label": "L2 task backend [claude]", "session": "l2-3"},
                {"id": "L2-4", "label": "L2 task verify [codex]", "session": "l2-4"},
            ],
            fresh=False,
        )

        self.assertIn("tmux split-window -h -p 60", script)
        self.assertIn("tmux split-window -v -p 75", script)
        self.assertIn("tmux split-window -v -p 67", script)
        self.assertIn("tmux split-window -v -p 50", script)
        self.assertIn('L2_REMAINING_PANE="$L2_PANE_4"', script)
        self.assertNotIn("select-layout", script)

    def test_duo_terminal_commands_start_codex_and_claude_l1_in_project(self):
        project = Path("/tmp/example project")
        legion_sh = Path("/tmp/legion scripts/legion.sh")

        commands = build_duo_terminal_commands(
            project_dir=project,
            legion_sh=legion_sh,
            codex_name="玄武",
            claude_name="青龙",
        )

        self.assertEqual(len(commands), 2)
        self.assertIn("cd '/tmp/example project'", commands[0])
        self.assertIn("'/tmp/legion scripts/legion.sh' codex l1 '玄武'", commands[0])
        self.assertIn("cd '/tmp/example project'", commands[1])
        self.assertIn("'/tmp/legion scripts/legion.sh' claude l1 '青龙'", commands[1])

    def test_dou_terminal_commands_open_codex_in_new_window_and_claude_in_current(self):
        project = Path("/tmp/example project")
        legion_sh = Path("/tmp/legion scripts/legion.sh")

        commands = build_dou_terminal_commands(
            project_dir=project,
            legion_sh=legion_sh,
            codex_name="玄武",
            claude_name="青龙",
        )

        self.assertEqual(set(commands.keys()), {"new_window", "current_window"})
        self.assertIn("cd '/tmp/example project'", commands["new_window"])
        self.assertIn("'/tmp/legion scripts/legion.sh' codex l1 '玄武'", commands["new_window"])
        self.assertIn("cd '/tmp/example project'", commands["current_window"])
        self.assertIn("'/tmp/legion scripts/legion.sh' claude l1 '青龙'", commands["current_window"])

    def test_dual_host_cli_attaches_claude_without_opening_dual_view(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            captured = {}

            def fake_execvp(program, argv):
                captured["program"] = program
                captured["argv"] = list(argv)
                raise RuntimeError("exec-called")

            with patch("scripts.legion_core.CommandRunner", RecordingRunner):
                with patch("os.execvp", side_effect=fake_execvp):
                    with self.assertRaises(RuntimeError):
                        from scripts import legion_core

                        legion_core.main(
                            [
                                "--project-dir",
                                str(root),
                                "--legion-home",
                                str(home),
                                "dual-host",
                            ]
                        )

            self.assertEqual(captured["argv"][:2], ["tmux", "a"])
            self.assertIn("L1-", captured["argv"][-1])
            self.assertIn("claude", captured["argv"][-1])
            self.assertNotIn("legion-view", " ".join(captured["argv"]))

    def test_duo_applescript_opens_two_terminal_windows(self):
        script = build_duo_applescript(["echo codex", "echo claude"])

        self.assertIn('tell application "Terminal"', script)
        self.assertEqual(script.count("do script"), 2)
        self.assertIn('do script "echo codex"', script)
        self.assertIn('do script "echo claude"', script)

    def test_duo_tmux_script_runs_codex_and_claude_inside_current_terminal(self):
        project = Path("/tmp/example project")
        legion_sh = Path("/tmp/legion scripts/legion.sh")

        script = build_duo_tmux_script(
            project_dir=project,
            legion_sh=legion_sh,
            codex_name="玄武",
            claude_name="青龙",
            codex_launch_script=Path("/tmp/codex-launch.sh"),
            claude_launch_script=Path("/tmp/claude-launch.sh"),
        )

        self.assertIn('tmux -L "$SOCKET" new-session -d -s', script)
        self.assertIn("-n codex", script)
        self.assertIn("-n claude", script)
        self.assertIn("bash /tmp/codex-launch.sh", script)
        self.assertIn("bash /tmp/claude-launch.sh", script)
        self.assertIn('exec tmux -L "$SOCKET" attach -t', script)

    def test_vscode_duo_dry_run_uses_entrypoint_commands_without_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            legion_sh = root / "legion.sh"

            commands = launch_duo_terminal(
                project_dir=root,
                legion_sh=legion_sh,
                codex_name="玄武",
                claude_name="青龙",
                terminal="vscode",
                dry_run=True,
                legion_home=home,
            )

            self.assertEqual(len(commands), 1)
            self.assertIn("codex l1", commands[0])
            self.assertIn("claude l1", commands[0])
            self.assertNotIn("launch.sh", commands[0])
            self.assertFalse((home / ProjectContext.from_path(root).project_hash / "mixed" / "mixed-registry.json").exists())

    def test_vscode_duo_non_dry_run_uses_real_launch_artifacts(self):
        class ExecCalled(Exception):
            pass

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            legion_sh = root / "legion.sh"
            runner = RecordingRunner()

            with patch("os.execvp", side_effect=ExecCalled) as execvp:
                with self.assertRaises(ExecCalled):
                    launch_duo_terminal(
                        project_dir=root,
                        legion_sh=legion_sh,
                        codex_name="玄武",
                        claude_name="青龙",
                        terminal="vscode",
                        runner=runner,
                        dry_run=False,
                        legion_home=home,
                    )

            script = execvp.call_args.args[1][2]
            state_dir = home / ProjectContext.from_path(root).project_hash / "mixed"
            registry = json.loads((state_dir / "mixed-registry.json").read_text(encoding="utf-8"))
            commanders = {item["provider"]: item for item in registry["commanders"]}
            codex_launch = Path(commanders["codex"]["run_dir"]) / "launch.sh"
            claude_launch = Path(commanders["claude"]["run_dir"]) / "launch.sh"

            self.assertTrue(codex_launch.exists())
            self.assertTrue(claude_launch.exists())
            self.assertIn("bash", script)
            self.assertIn(str(codex_launch), script)
            self.assertIn(str(claude_launch), script)
            self.assertEqual(runner.commands, [])

    def test_scope_conflict_rejects_overlapping_active_delivery_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [{"id": "frontend-a", "branch": "frontend", "task": "edit shared tree", "scope": ["src"]}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )

            with self.assertRaises(SystemExit) as ctx:
                core.deploy_campaign(
                    [{"id": "frontend-b", "branch": "frontend", "task": "edit shared file again", "scope": ["src/app.py"]}],
                    commander="L1-host",
                    dry_run=False,
                    corps=True,
                )

            self.assertIn("scope conflict", str(ctx.exception))
            self.assertIn("frontend-a", str(ctx.exception))

    def test_delivery_task_requires_non_empty_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")

            with self.assertRaises(SystemExit) as ctx:
                core.deploy_campaign(
                    [{"id": "frontend-a", "branch": "frontend", "task": "edit without ownership"}],
                    commander="L1-host",
                    dry_run=False,
                    corps=True,
                )

            self.assertIn("delivery tasks must declare non-empty file scope", str(ctx.exception))

    def test_scope_paths_are_normalized_and_reject_absolute_or_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")

            core.deploy_campaign(
                [{"id": "frontend-a", "branch": "frontend", "task": "edit", "scope": ["./src/./app.py"]}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )

            task = json.loads(core.registry_file.read_text(encoding="utf-8"))["tasks"][0]
            self.assertEqual(task["scope"], ["src/app.py"])

            with self.assertRaises(SystemExit) as absolute:
                core.deploy_campaign(
                    [{"id": "frontend-b", "branch": "frontend", "task": "edit", "scope": [str(root / "src" / "b.py")]}],
                    commander="L1-host",
                    dry_run=False,
                    corps=True,
                )
            self.assertIn("project-relative", str(absolute.exception))

            with self.assertRaises(SystemExit) as traversal:
                core.deploy_campaign(
                    [{"id": "frontend-c", "branch": "frontend", "task": "edit", "scope": ["../outside.py"]}],
                    commander="L1-host",
                    dry_run=False,
                    corps=True,
                )
            self.assertIn("cannot traverse", str(traversal.exception))

    def test_scope_conflict_within_single_campaign_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")

            with self.assertRaises(SystemExit) as ctx:
                core.deploy_campaign(
                    [
                        {"id": "frontend-a", "branch": "frontend", "task": "edit", "scope": ["src/app.py"]},
                        {"id": "frontend-b", "branch": "frontend", "task": "edit again", "scope": ["src/app.py"]},
                    ],
                    commander="L1-host",
                    dry_run=True,
                    corps=True,
                )

            self.assertIn("scope conflict", str(ctx.exception))

    def test_scope_conflict_rechecked_at_launch_transition_blocks_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.init_state()
            core._upsert_commander(
                {
                    "id": "L2-frontend",
                    "provider": "claude",
                    "role": "branch-commander",
                    "branch": "frontend",
                    "status": "commanding",
                    "session": core.context.session_name,
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )
            active = TaskSpec.from_mapping({"id": "active", "branch": "frontend", "task": "active edit", "scope": ["src"]})
            pending = TaskSpec.from_mapping({"id": "pending", "branch": "frontend", "task": "pending edit", "scope": ["src/app.py"]})
            core._upsert_task(active.as_registry_entry("running", "L2-frontend", core._run_dir(active)))
            core._upsert_task(pending.as_registry_entry("planned", "L2-frontend", core._run_dir(pending)))

            launched = core._launch_ready_tasks()

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            tasks = {task["id"]: task for task in registry["tasks"]}
            self.assertEqual(launched, [])
            self.assertEqual(tasks["pending"]["status"], "blocked")
            self.assertIn("scope_conflict", tasks["pending"])
            events = [json.loads(line) for line in core.events_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(event["event"] == "scope_conflict_blocked" for event in events))

    def test_rescue_role_participates_in_delivery_scope_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L2-rescue", role="branch-commander", branch="rescue", provider="codex")
            self.register_commander(core, "L2-implement", role="branch-commander", branch="implement", provider="claude")
            core.deploy_campaign(
                [{"id": "rescue-a", "role": "rescue", "task": "repair", "scope": ["src/app.py"]}],
                commander="L2-rescue",
                dry_run=False,
                direct=True,
            )

            with self.assertRaises(SystemExit) as ctx:
                core.deploy_campaign(
                    [{"id": "implement-b", "role": "implement", "task": "edit", "scope": ["src/app.py"]}],
                    commander="L2-implement",
                    dry_run=False,
                    direct=True,
                )

            self.assertIn("scope conflict", str(ctx.exception))
            self.assertIn("rescue-a", str(ctx.exception))

    def test_scope_conflict_releases_after_task_reaches_terminal_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            self.register_commander(core, "L1-host")
            core.deploy_campaign(
                [{"id": "frontend-a", "branch": "frontend", "task": "edit", "scope": ["src/app.py"]}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )
            core.mark_task("frontend-a", "completed")

            # After terminal completion, the scope ownership window is released.
            core.deploy_campaign(
                [{"id": "frontend-b", "branch": "frontend", "task": "edit again", "scope": ["src/app.py"]}],
                commander="L1-host",
                dry_run=False,
                corps=True,
            )

            tasks = {item["id"]: item for item in json.loads(core.registry_file.read_text(encoding="utf-8"))["tasks"]}
            self.assertIn("frontend-b", tasks)
            self.assertEqual(tasks["frontend-b"]["status"], "launched")

    def test_status_text_does_not_mutate_registry_or_events(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=MissingWindowRunner())
            core.deploy_campaign(
                [{"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]}],
                dry_run=False,
            )
            running = core._task_entry("implement")
            running["status"] = "running"
            running["window"] = "w-implement"
            core._upsert_task(running)
            registry_before = core.registry_file.read_text(encoding="utf-8")
            events_before = core.events_file.read_text(encoding="utf-8")

            core.status_text()

            self.assertEqual(core.registry_file.read_text(encoding="utf-8"), registry_before)
            self.assertEqual(core.events_file.read_text(encoding="utf-8"), events_before)

    def test_events_include_release_schema_fields_and_non_empty_payloads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            core.deploy_campaign([{"id": "audit-one", "role": "audit", "task": "audit diff"}], dry_run=False)

            events = self.read_events(core)
            self.assertTrue(events)
            for event in events:
                self.assert_release_event_record(event)
                self.assertTrue(event["correlation_id"].startswith("corr-"))
                self.assertTrue(event["payload"])

    def test_read_only_paths_do_not_create_state_on_fresh_missing_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            self.assertFalse(core.state_dir.exists())

            status = core.status_text()
            readiness = core.readiness_text("L1-host", expected=["L2-missing"])
            inbox = core.inbox_text("L1-host")
            with self.assertRaises(SystemExit):
                core.view_targets()

            self.assertIn("Commanders", status)
            self.assertIn("Expected L2: L2-missing", readiness)
            self.assertIn("Ready: 0/1", readiness)
            self.assertIn("(empty)", inbox)
            self.assertFalse(core.state_dir.exists())

    def test_reconcile_does_not_resurrect_terminal_commanders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = NamedSessionRunner({"keep-session"})
            core = LegionCore(root, legion_home=root / "home", runner=runner)
            core._upsert_commander(
                {
                    "id": "L1-终结",
                    "provider": "claude",
                    "role": "commander",
                    "status": "completed",
                    "session": "keep-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            core.reconcile_state()

            commander = next(item for item in json.loads(core.registry_file.read_text())["commanders"] if item["id"] == "L1-终结")
            self.assertEqual(commander["status"], "completed")

    def test_reconcile_does_not_fail_commanders_when_tmux_probe_is_inaccessible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=InaccessibleTmuxRunner())
            core._upsert_commander(
                {
                    "id": "L2-audit-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "status": "commanding",
                    "session": "audit-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            core.reconcile_state()

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            commander = next(item for item in registry["commanders"] if item["id"] == "L2-audit-1")
            self.assertEqual(commander["status"], "commanding")
            events = [json.loads(line) for line in core.events_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(event["event"] == "tmux_probe_inaccessible" for event in events))

    def test_readiness_rejects_expected_ids_outside_direct_l2_roster(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            core._upsert_commander(
                {
                    "id": "L1-host",
                    "provider": "claude",
                    "role": "commander",
                    "status": "commanding",
                    "session": "host-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )
            core.send_message("L1-host", "READY:init-complete forged claim", sender="L2-impostor")

            state = core.readiness_state("L1-host", expected=["L2-impostor"])

            self.assertEqual(state["expected"], [])
            self.assertEqual(state["rejected_expected"], ["L2-impostor"])
            self.assertEqual(state["ready"], {})

    def test_readiness_rejects_forged_from_without_execution_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=NamedSessionRunner({"host-session", "audit-session"}))
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "L1-host", "commanding", "audit-session"),
            ]:
                cid, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )
            order = core._issue_readiness_order("L1-host", ["L2-audit-1"])

            core.send_message(
                "L1-host",
                f"READY:init-complete order_id={order['order_id']} nonce={order['nonce']}",
                sender="L2-audit-1",
            )
            forged = core.readiness_state("L1-host", expected=["L2-audit-1"])
            self.assertNotIn("L2-audit-1", forged["ready"])

            with patch.dict(
                os.environ,
                {
                    "LEGION_COMMANDER_ID": "L2-audit-1",
                    "CLAUDE_CODE_AGENT_NAME": "L2-audit-1",
                    "CLAUDE_LEGION_TEAM_ID": "L2-audit-1",
                    "LEGION_COMMANDER_SESSION": "audit-session",
                },
            ):
                core.send_message(
                    "L1-host",
                    f"READY:init-complete order_id={order['order_id']} nonce={order['nonce']}",
                    sender="L2-audit-1",
                )
            verified = core.readiness_state("L1-host", expected=["L2-audit-1"])
            self.assertIn("L2-audit-1", verified["ready"])

    def test_readiness_state_preserves_order_expected_roster_even_when_child_offline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=NamedSessionRunner({"host-session", "impl-session"}))
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-implement-1", "claude", "branch-commander", "implement", "L1-host", "commanding", "impl-session"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "L1-host", "commanding", "missing-session"),
            ]:
                cid, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )
            order = core._issue_readiness_order("L1-host", ["L2-implement-1", "L2-audit-1"])
            ready_message = f"READY:init-complete order_id={order['order_id']} nonce={order['nonce']}"

            with patch.dict(
                os.environ,
                {
                    "LEGION_COMMANDER_ID": "L2-implement-1",
                    "CLAUDE_CODE_AGENT_NAME": "L2-implement-1",
                    "CLAUDE_LEGION_TEAM_ID": "L2-implement-1",
                    "LEGION_COMMANDER_SESSION": "impl-session",
                },
            ):
                core.send_message("L1-host", ready_message, sender="L2-implement-1")

            state = core.readiness_state("L1-host")

            self.assertEqual(state["expected"], ["L2-implement-1", "L2-audit-1"])
            self.assertEqual(state["rejected_expected"], [])
            self.assertIn("L2-implement-1", state["ready"])
            self.assertEqual(state["missing"], ["L2-audit-1"])

    def test_readiness_rejects_spoofed_id_without_required_session_and_run_dir_bindings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audit_run_dir = root / "home" / "mixed" / "commanders" / "L2-audit-1"
            core = LegionCore(root, legion_home=root / "home", runner=NamedSessionRunner({"host-session", "audit-session"}))
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session", ""),
                (
                    "L2-audit-1",
                    "codex",
                    "branch-commander",
                    "audit",
                    "L1-host",
                    "commanding",
                    "audit-session",
                    str(audit_run_dir),
                ),
            ]:
                cid, provider, role, branch, parent, status, session, run_dir = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": run_dir,
                        "project": str(root),
                        "updated": "old",
                    }
                )
            order = core._issue_readiness_order("L1-host", ["L2-audit-1"])
            ready_message = f"READY:init-complete order_id={order['order_id']} nonce={order['nonce']}"

            with patch.dict(os.environ, {"LEGION_COMMANDER_ID": "L2-audit-1"}, clear=True):
                id_only_record = core.send_message("L1-host", ready_message, sender="L2-audit-1")
            id_only_state = core.readiness_state("L1-host", expected=["L2-audit-1"])
            self.assertFalse(id_only_record["sender_verified"])
            self.assertNotIn("L2-audit-1", id_only_state["ready"])

            with patch.dict(
                os.environ,
                {"LEGION_COMMANDER_ID": "L2-audit-1", "LEGION_COMMANDER_SESSION": "audit-session"},
                clear=True,
            ):
                missing_run_dir_record = core.send_message("L1-host", ready_message, sender="L2-audit-1")
            missing_run_dir_state = core.readiness_state("L1-host", expected=["L2-audit-1"])
            self.assertFalse(missing_run_dir_record["sender_verified"])
            self.assertNotIn("L2-audit-1", missing_run_dir_state["ready"])

            with patch.dict(
                os.environ,
                {
                    "LEGION_COMMANDER_ID": "L2-audit-1",
                    "LEGION_COMMANDER_SESSION": "audit-session",
                    "LEGION_COMMANDER_RUN_DIR": str(audit_run_dir),
                },
                clear=True,
            ):
                verified_record = core.send_message("L1-host", ready_message, sender="L2-audit-1")
            verified_state = core.readiness_state("L1-host", expected=["L2-audit-1"])
            self.assertTrue(verified_record["sender_verified"])
            self.assertIn("L2-audit-1", verified_state["ready"])

    def test_sender_authentication_keeps_system_and_unbound_external_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.register_external_commander(provider="claude", commander_id="L1-external", session="", status="commanding")

            self.assertTrue(core._sender_authentication("Legion Core")["verified"])

            with patch.dict(
                os.environ,
                {
                    "LEGION_COMMANDER_ID": "L1-external",
                    "LEGION_COMMANDER_SESSION": "external-session-not-bound",
                    "LEGION_COMMANDER_RUN_DIR": str(root / "unbound"),
                },
                clear=True,
            ):
                auth = core._sender_authentication("L1-external")

            self.assertTrue(auth["verified"])

    def test_wait_readiness_fails_rejected_expected_and_reports_original_roster(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())

            ok, report = core.wait_readiness("L1-host", expected=["L2-impostor"], timeout=0, interval=0)

            self.assertFalse(ok)
            self.assertIn("Expected L2: L2-impostor", report)
            self.assertIn("Ready: 0/1", report)
            self.assertIn("Rejected expected", report)
            self.assertFalse(core.state_dir.exists())

    def test_readiness_rejects_direct_l2_when_tmux_session_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "L1-host", "commanding", "missing-session"),
            ]:
                cid, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )
            core.send_message("L1-host", "READY:init-complete branch=audit", sender="L2-audit-1")

            state = core.readiness_state("L1-host", expected=["L2-audit-1"])

            self.assertEqual(state["expected"], [])
            self.assertEqual(state["rejected_expected"], ["L2-audit-1"])
            self.assertEqual(state["ready"], {})

    def test_readiness_rejects_replies_from_wrong_parent_l2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-other", "codex", "branch-commander", "audit", "L1-other", "commanding", "other-session"),
            ]:
                cid, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )
            core.send_message("L1-host", "READY:init-complete branch=audit", sender="L2-other")

            state = core.readiness_state("L1-host", expected=["L2-other"])

            self.assertEqual(state["expected"], [])
            self.assertEqual(state["rejected_expected"], ["L2-other"])

    def test_readiness_rejects_inactive_l2_sender(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-failed", "codex", "branch-commander", "audit", "L1-host", "failed", "audit-session"),
            ]:
                cid, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )
            core.send_message("L1-host", "READY:init-complete from a dead L2", sender="L2-failed")

            state = core.readiness_state("L1-host", expected=["L2-failed"])

            self.assertEqual(state["expected"], [])
            self.assertEqual(state["rejected_expected"], ["L2-failed"])

    def test_host_readiness_order_records_id_nonce_and_issued_at(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())

            convened = core.convene_host(dry_run=False)
            host_id = str(convened["host"]["id"])

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            order = registry["readiness_orders"][host_id]
            self.assertTrue(order["order_id"].startswith("ord-"))
            self.assertTrue(order["nonce"])
            self.assertTrue(order["issued_at"])
            self.assertEqual(set(order["expected"]), {commander["id"] for commander in convened["l2"]})
            inbox_lines = core._inbox_file(host_id).read_text(encoding="utf-8").splitlines()
            records = [json.loads(line) for line in inbox_lines if line.strip()]
            record = next(item for item in records if item["type"] == "readiness-order")
            self.assertIn(order["order_id"], record["content"])
            self.assertIn(order["nonce"], record["content"])

    def test_readiness_state_requires_order_id_and_nonce_after_order_issued(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            convened = core.convene_host(dry_run=False)
            host_id = str(convened["host"]["id"])
            l2_ids = [commander["id"] for commander in convened["l2"]]
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            order = registry["readiness_orders"][host_id]
            first_l2 = next(commander for commander in convened["l2"] if commander["id"] == l2_ids[0])
            first_l2_env = {
                "LEGION_COMMANDER_ID": l2_ids[0],
                "CLAUDE_CODE_AGENT_NAME": l2_ids[0],
                "CLAUDE_LEGION_TEAM_ID": l2_ids[0],
                "LEGION_COMMANDER_SESSION": str(first_l2["session"]),
                "LEGION_COMMANDER_RUN_DIR": str(first_l2["run_dir"]),
            }

            # A reply WITHOUT the current order_id/nonce must not satisfy readiness.
            with patch.dict(os.environ, first_l2_env):
                core.send_message(host_id, "READY:init-complete branch=stale", sender=l2_ids[0])
            stale_state = core.readiness_state(host_id)
            self.assertNotIn(l2_ids[0], stale_state["ready"])

            # A reply that echoes the order_id and nonce satisfies readiness.
            structured = (
                f"READY:init-complete order_id={order['order_id']} nonce={order['nonce']} "
                f"branch=audit weapons=loaded inbox=empty"
            )
            with patch.dict(os.environ, first_l2_env):
                core.send_message(host_id, structured, sender=l2_ids[0])
            fresh_state = core.readiness_state(host_id)
            self.assertIn(l2_ids[0], fresh_state["ready"])

    def test_readiness_state_ignores_replies_older_than_current_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=NamedSessionRunner({"host-session", "audit-session"}))
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "L1-host", "commanding", "audit-session"),
            ]:
                cid, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )

            # Pre-order stale reply — looks structured but order is issued AFTER it.
            stale_order_id = "ord-fake"
            stale_nonce = "nfake"
            with patch.dict(
                os.environ,
                {
                    "LEGION_COMMANDER_ID": "L2-audit-1",
                    "CLAUDE_CODE_AGENT_NAME": "L2-audit-1",
                    "CLAUDE_LEGION_TEAM_ID": "L2-audit-1",
                    "LEGION_COMMANDER_SESSION": "audit-session",
                },
            ):
                core.send_message(
                    "L1-host",
                    f"READY:init-complete order_id={stale_order_id} nonce={stale_nonce}",
                    sender="L2-audit-1",
                )
            # Now issue a fresh order with different id/nonce.
            order = core._issue_readiness_order("L1-host", ["L2-audit-1"])

            state = core.readiness_state("L1-host", expected=["L2-audit-1"])

            # Stale reply does not echo the current order_id/nonce → ignored.
            self.assertNotIn("L2-audit-1", state["ready"])
            self.assertIn("L2-audit-1", state["missing"])
            self.assertEqual(state["order"]["order_id"], order["order_id"])

    def test_readiness_state_rejects_stale_malformed_id_record_after_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=NamedSessionRunner({"host-session", "audit-session"}))
            for commander in [
                ("L1-host", "claude", "commander", "", "", "commanding", "host-session"),
                ("L2-audit-1", "codex", "branch-commander", "audit", "L1-host", "commanding", "audit-session"),
            ]:
                cid, provider, role, branch, parent, status, session = commander
                core._upsert_commander(
                    {
                        "id": cid,
                        "provider": provider,
                        "role": role,
                        "branch": branch,
                        "parent": parent,
                        "status": status,
                        "session": session,
                        "run_dir": "",
                        "project": str(root),
                        "updated": "old",
                    }
                )
            order = core._issue_readiness_order("L1-host", ["L2-audit-1"])
            core._append_inbox(
                "L1-host",
                {
                    "id": "msg-not-a-timestamp",
                    "ts": "1970-01-01T00:00:00Z",
                    "from": "L2-audit-1",
                    "to": "L1-host",
                    "type": "message",
                    "content": f"READY:init-complete order_id={order['order_id']} nonce={order['nonce']}",
                },
            )

            state = core.readiness_state("L1-host", expected=["L2-audit-1"])

            self.assertNotIn("L2-audit-1", state["ready"])
            self.assertEqual(state["missing"], ["L2-audit-1"])

    def test_repair_unblocks_dependents_and_swaps_dependency_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign(
                [
                    {"id": "implement-v1", "role": "implement", "task": "first attempt", "scope": ["src/a.py"]},
                    {"id": "review", "role": "review", "task": "review the impl", "depends_on": ["implement-v1"]},
                ],
                dry_run=False,
            )
            core.mark_task("implement-v1", "failed")
            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            tasks = {item["id"]: item for item in registry["tasks"]}
            self.assertEqual(tasks["review"]["status"], "blocked")

            # Add a replacement task with a different scope (so scope-conflict does not fire).
            core.deploy_campaign(
                [{"id": "implement-v2", "role": "implement", "task": "second attempt", "scope": ["src/b.py"]}],
                dry_run=False,
            )
            repaired = core.repair_dependents("implement-v1", replacement_task_id="implement-v2")

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            tasks = {item["id"]: item for item in registry["tasks"]}
            self.assertIn("review", repaired)
            self.assertEqual(tasks["review"]["status"], "planned")
            self.assertEqual(tasks["review"]["depends_on"], ["implement-v2"])
            self.assertEqual(tasks["implement-v1"]["status"], "failed")  # monotonic
            self.assertIn("implement-v2", tasks["implement-v1"]["repaired_by"])

    def test_repair_records_event_referencing_replacement_and_dependents(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign(
                [
                    {"id": "implement-v1", "role": "implement", "task": "first attempt", "scope": ["src/a.py"]},
                    {"id": "review", "role": "review", "task": "review", "depends_on": ["implement-v1"]},
                ],
                dry_run=False,
            )
            core.mark_task("implement-v1", "failed")
            core.deploy_campaign(
                [{"id": "implement-v2", "role": "implement", "task": "second attempt", "scope": ["src/b.py"]}],
                dry_run=False,
            )

            core.repair_dependents("implement-v1", replacement_task_id="implement-v2")

            events = self.read_events(core)
            repair_events = [event for event in events if event.get("event") == "task_repair"]
            self.assertTrue(repair_events)
            repair_event = repair_events[-1]
            self.assert_release_event_record(repair_event, "task_repair", "implement-v1")
            payload = repair_event["payload"]
            self.assertEqual(payload["replacement"], "implement-v2")
            self.assertIn("review", payload["dependents_unblocked"])
            planned_events = [
                event
                for event in events
                if event.get("event") == "task_planned"
                and event.get("task_id") == "review"
                and event.get("payload", {}).get("reason") == "repair"
            ]
            self.assertTrue(planned_events)
            planned_event = planned_events[-1]
            self.assert_release_event_record(planned_event, "task_planned", "review")
            self.assertEqual(planned_event["payload"]["original"], "implement-v1")
            self.assertEqual(planned_event["payload"]["replacement"], "implement-v2")

    def test_repair_rejects_invalid_replacement_without_mutating(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign(
                [
                    {"id": "implement-v1", "role": "implement", "task": "first attempt", "scope": ["src/a.py"]},
                    {"id": "review", "role": "review", "task": "review", "depends_on": ["implement-v1"]},
                ],
                dry_run=False,
            )
            core.mark_task("implement-v1", "failed")
            registry_before = core.registry_file.read_text(encoding="utf-8")
            events_before = core.events_file.read_text(encoding="utf-8")

            with self.assertRaises(SystemExit) as missing:
                core.repair_dependents("implement-v1", replacement_task_id="missing-replacement")

            self.assertIn("unknown replacement task", str(missing.exception))
            self.assertEqual(core.registry_file.read_text(encoding="utf-8"), registry_before)
            self.assertEqual(core.events_file.read_text(encoding="utf-8"), events_before)

            core.deploy_campaign(
                [{"id": "implement-v2", "role": "implement", "task": "second attempt", "scope": ["src/b.py"]}],
                dry_run=False,
            )
            core.mark_task("implement-v2", "failed")
            registry_before = core.registry_file.read_text(encoding="utf-8")
            events_before = core.events_file.read_text(encoding="utf-8")

            with self.assertRaises(SystemExit) as failed:
                core.repair_dependents("implement-v1", replacement_task_id="implement-v2")

            self.assertIn("replacement task must not be failed/blocked", str(failed.exception))
            self.assertEqual(core.registry_file.read_text(encoding="utf-8"), registry_before)
            self.assertEqual(core.events_file.read_text(encoding="utf-8"), events_before)

    def test_repair_unblocks_transitive_dependents_when_graph_is_repaired(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign(
                [
                    {"id": "implement-v1", "role": "implement", "task": "first attempt", "scope": ["src/a.py"]},
                    {"id": "review", "role": "review", "task": "review", "depends_on": ["implement-v1"]},
                    {"id": "verify", "role": "verify", "task": "verify", "depends_on": ["review"]},
                ],
                dry_run=False,
            )
            core.mark_task("implement-v1", "failed")
            core.deploy_campaign(
                [{"id": "implement-v2", "role": "implement", "task": "second attempt", "scope": ["src/b.py"]}],
                dry_run=False,
            )

            repaired = core.repair_dependents("implement-v1", replacement_task_id="implement-v2")

            registry = json.loads(core.registry_file.read_text(encoding="utf-8"))
            tasks = {item["id"]: item for item in registry["tasks"]}
            self.assertEqual(repaired, ["review", "verify"])
            self.assertEqual(tasks["review"]["status"], "planned")
            self.assertEqual(tasks["review"]["depends_on"], ["implement-v2"])
            self.assertEqual(tasks["verify"]["status"], "planned")
            self.assertEqual(tasks["verify"]["depends_on"], ["review"])

    def test_repair_refuses_to_modify_active_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign(
                [{"id": "implement", "role": "implement", "task": "still running", "scope": ["src/feature.py"]}],
                dry_run=False,
            )

            with self.assertRaises(SystemExit) as ctx:
                core.repair_dependents("implement", replacement_task_id="implement-v2")

            self.assertIn("only failed/blocked", str(ctx.exception))

    def test_inbox_record_persists_when_tmux_session_is_missing(self):
        # Inbox-before-tmux ordering: tmux failure must never delete the inbox row.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            core._upsert_commander(
                {
                    "id": "L2-audit-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "status": "commanding",
                    "session": "missing-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            record = core.send_message("L2-audit-1", "must persist", sender="L1-host")

            self.assertFalse(record["delivered_tmux"])
            inbox = core._inbox_file("L2-audit-1").read_text(encoding="utf-8").strip()
            saved = json.loads(inbox)
            self.assertEqual(saved["content"], "must persist")
            self.assertEqual(saved["id"], record["id"])

    def test_message_id_is_unique_across_rapid_send(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=OfflineTmuxRunner())
            core._upsert_commander(
                {
                    "id": "L2-audit-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "status": "commanding",
                    "session": "missing-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            ids = {core.send_message("L2-audit-1", f"hello {i}", sender="L1-host")["id"] for i in range(10)}

            self.assertEqual(len(ids), 10)

    def test_terminal_commander_status_is_monotonic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core._upsert_commander(
                {
                    "id": "L2-audit-1",
                    "provider": "codex",
                    "role": "branch-commander",
                    "status": "completed",
                    "session": "old-session",
                    "run_dir": "",
                    "project": str(root),
                    "updated": "old",
                }
            )

            core.mark_commander("L2-audit-1", "commanding")

            commander = next(item for item in json.loads(core.registry_file.read_text())["commanders"] if item["id"] == "L2-audit-1")
            self.assertEqual(commander["status"], "completed")

    def test_terminal_task_status_is_monotonic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            core = LegionCore(root, legion_home=root / "home", runner=RecordingRunner())
            core.deploy_campaign(
                [{"id": "implement", "role": "implement", "task": "add feature", "scope": ["src/feature.py"]}],
                dry_run=False,
            )
            core.mark_task("implement", "failed")

            core.mark_task("implement", "running")

            task = next(item for item in json.loads(core.registry_file.read_text())["tasks"] if item["id"] == "implement")
            self.assertEqual(task["status"], "failed")

    def test_provider_role_defaults_route_explore_review_audit_to_codex(self):
        from scripts.legion_core import default_provider_for_role

        for role in ("explore", "review", "verify", "audit"):
            self.assertEqual(default_provider_for_role(role), "codex", msg=f"role {role}")
        for role in ("implement", "product", "ui"):
            self.assertEqual(default_provider_for_role(role), "claude", msg=f"role {role}")


if __name__ == "__main__":
    unittest.main()
