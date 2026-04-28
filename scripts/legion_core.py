#!/usr/bin/env python3
"""Provider-neutral Legion core for mixed Claude/Codex teams."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import random
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


CODEX_DEFAULT_ROLES = {
    "explore",
    "review",
    "verify",
    "audit",
    "adversarial",
    "rescue",
    "second-opinion",
}

CLAUDE_DEFAULT_ROLES = {
    "plan",
    "implement",
    "product",
    "product-counselor",
    "ui",
    "ui-designer",
}

CODEX_DEFAULT_BRANCHES = {
    "audit",
    "explore",
    "review",
    "security",
    "verify",
}

CLAUDE_DEFAULT_BRANCHES = {
    "backend",
    "frontend",
    "implement",
    "product",
    "ui",
}

TERMINAL_TASK_STATUSES = {"completed", "failed", "blocked"}
TERMINAL_COMMANDER_STATUSES = {"completed", "failed"}
ACTIVE_COMMANDER_STATUSES = {"launching", "commanding"}
ISOLATED_COMMANDER_STATUS = "isolated"
DELIVERY_ROLES = {
    "implement",
    "product",
    "product-counselor",
    "rescue",
    "ui",
    "ui-designer",
}
DELIVERY_BRANCHES = {
    "backend",
    "frontend",
    "implement",
    "product",
    "ui",
}
READ_ONLY_CODEX_ROLES = (CODEX_DEFAULT_ROLES | {"security"}) - DELIVERY_ROLES
VALID_CODEX_SANDBOXES = {"read-only", "workspace-write"}
EVENT_SCHEMA_VERSION = 1
COMPLEXITY_ORDER = {"s": 0, "m": 1, "l": 2, "xl": 3}
WORKER_RESULT_KEYS = {"status", "summary", "files_touched", "verification", "findings", "risks"}
WORKER_VERIFICATION_KEYS = {"command", "result", "details"}
WORKER_FINDING_KEYS = {"severity", "file", "line", "description", "recommendation"}
WORKER_RESULT_STATUSES = {"completed", "blocked", "failed"}
WORKER_VERIFICATION_RESULTS = {"pass", "fail", "not-run"}
WORKER_FINDING_SEVERITIES = {"critical", "major", "minor", "suggestion"}
AICTO_CONTROL_PLANE_ID = "external-hermes-aicto"
AICTO_DIRECTIVE_SENDER = "AICTO-CTO"
AICTO_PLUGIN_ENTRYPOINT = "/Users/feijun/Documents/AICTO/hermes-plugin/legion_api.py::send_to_commander"

L1_CODENAMES = [
    "烈焰",
    "雷霆",
    "苍穹",
    "银河",
    "极光",
    "深渊",
    "星辰",
    "暴风",
    "磐石",
    "幻影",
    "猎鹰",
    "黑曜",
    "赤龙",
    "玄武",
    "白虎",
    "朱雀",
    "青龙",
    "麒麟",
    "鲲鹏",
    "凤凰",
]


@dataclass(frozen=True)
class ProjectContext:
    project_dir: Path
    project_hash: str
    project_name: str

    @classmethod
    def from_path(cls, project_dir: Path) -> "ProjectContext":
        expanded = project_dir.expanduser()
        absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
        digest = hashlib.md5(str(absolute).encode("utf-8")).hexdigest()[:8]
        return cls(project_dir=absolute, project_hash=digest, project_name=absolute.name)

    @property
    def session_name(self) -> str:
        return f"legion-mixed-{self.project_hash}-{self.project_name}"

    @property
    def team_name(self) -> str:
        return f"legion-{self.project_hash}"


@dataclass
class TaskSpec:
    task: str
    role: str = "implement"
    provider: str = "auto"
    task_id: str = "task-001"
    branch: str = ""
    scope: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    model: str | None = None
    sandbox: str | None = None
    complexity: str = ""
    role_explicit: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any], index: int = 1) -> "TaskSpec":
        branch = normalize_branch(str(data.get("branch", "")).strip())
        role_raw = data.get("role")
        role_explicit = role_raw is not None and str(role_raw).strip() != ""
        if role_explicit:
            role = str(role_raw).strip()
        elif branch:
            role = default_role_for_branch(branch)
        else:
            role = "implement"

        provider = str(data.get("provider", "auto")).strip().lower() or "auto"
        if provider == "auto":
            provider = default_provider_for_role(role)

        task_id = str(data.get("id", data.get("task_id", f"task-{index:03d}"))).strip()
        task_id = normalize_task_id(task_id or f"task-{index:03d}")

        scope = data.get("scope", data.get("files", []))
        if isinstance(scope, str):
            scope = [scope]

        depends_on = data.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]

        complexity = normalize_complexity(str(data.get("complexity", data.get("level", data.get("size", "")))))

        return cls(
            task=str(data.get("task", data.get("prompt", ""))).strip(),
            role=role,
            provider=provider,
            task_id=task_id,
            branch=branch,
            scope=[str(item) for item in scope],
            depends_on=[str(item) for item in depends_on],
            model=data.get("model"),
            sandbox=data.get("sandbox"),
            complexity=complexity,
            role_explicit=role_explicit,
            raw=dict(data),
        )

    def as_registry_entry(self, status: str, commander: str, run_dir: Path) -> dict[str, Any]:
        return {
            "id": self.task_id,
            "role": self.role,
            "provider": self.provider,
            "branch": self.branch,
            "task": self.task,
            "scope": self.scope,
            "depends_on": self.depends_on,
            "model": self.model,
            "sandbox": self.sandbox,
            "complexity": self.complexity,
            "commander": commander,
            "status": status,
            "run_dir": str(run_dir),
            "updated": iso_now(),
        }


class CommandRunner:
    def run(self, argv: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
        return completed.returncode, completed.stdout, completed.stderr


class CodexAdapter:
    def __init__(self, context: ProjectContext):
        self.context = context

    def sandbox_for(self, spec: TaskSpec) -> str:
        role = spec.role.lower()
        requested = str(spec.sandbox or "").strip()
        if requested and requested not in VALID_CODEX_SANDBOXES:
            raise SystemExit(f"{spec.task_id}: unsupported Codex sandbox {requested!r}")

        if role in DELIVERY_ROLES:
            sandbox = requested or "workspace-write"
            if sandbox != "workspace-write":
                raise SystemExit(f"{spec.task_id}: Codex delivery role {spec.role!r} requires workspace-write sandbox")
            return sandbox

        sandbox = requested or "read-only"
        if role in READ_ONLY_CODEX_ROLES and sandbox != "read-only":
            raise SystemExit(f"{spec.task_id}: Codex read-only gate {spec.role!r} cannot use sandbox {sandbox!r}")
        return sandbox

    def model_for(self, spec: TaskSpec) -> str | None:
        return spec.model or os.environ.get("CODEX_MODEL")

    def build_command(
        self,
        spec: TaskSpec,
        prompt_file: Path,
        result_file: Path,
        schema_file: Path,
    ) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "-C",
            str(self.context.project_dir),
            "--json",
            "--output-schema",
            str(schema_file),
            "-s",
            self.sandbox_for(spec),
            "-o",
            str(result_file),
        ]
        model = self.model_for(spec)
        if model:
            cmd.extend(["-m", model])
        cmd.append("-")
        return cmd

    def build_launch_body(
        self,
        spec: TaskSpec,
        prompt_file: Path,
        result_file: Path,
        schema_file: Path,
    ) -> str:
        cmd = " ".join(shlex.quote(part) for part in self.build_command(spec, prompt_file, result_file, schema_file))
        return f"{cmd} < {shlex.quote(str(prompt_file))}"


class ClaudeAdapter:
    def __init__(self, context: ProjectContext):
        self.context = context

    def build_launch_body(self, spec: TaskSpec, prompt_file: Path, result_file: Path) -> str:
        model_args = ""
        if spec.model:
            model_args = f" --model {shlex.quote(spec.model)}"
        return (
            "PROMPT=$(cat "
            f"{shlex.quote(str(prompt_file))}"
            ")\n"
            "claude --dangerously-skip-permissions -p \"$PROMPT\" --max-turns 80"
            f"{model_args} 2>&1 | tee {shlex.quote(str(result_file))}"
        )


class LegionCore:
    def __init__(
        self,
        project_dir: Path,
        legion_home: Path | None = None,
        runner: CommandRunner | None = None,
    ):
        self.context = ProjectContext.from_path(project_dir)
        self.legion_home = (legion_home or Path.home() / ".claude" / "legion").expanduser()
        self.state_dir = self.legion_home / self.context.project_hash / "mixed"
        self.registry_file = self.state_dir / "mixed-registry.json"
        self.events_file = self.state_dir / "events.jsonl"
        self.aicto_reports_file = self.state_dir / "aicto-reports.jsonl"
        self.inbox_dir = self.state_dir / "inbox"
        self.schema_file = Path(__file__).resolve().parents[1] / "schemas" / "legion-worker-result.schema.json"
        self.runner = runner or CommandRunner()
        self._registry_lock_depth = 0
        self._registry_lock_fh: Any = None

    def init_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        with self._registry_lock():
            if not self.registry_file.exists():
                self._write_registry({"project": self._project_record(), "commanders": [], "tasks": []})
        if not self.events_file.exists():
            self.events_file.touch()

    def start_commander(
        self,
        provider: str,
        name: str = "",
        dry_run: bool = False,
        attach: bool = True,
        fresh: bool = False,
        parent: str = "",
    ) -> dict[str, Any]:
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {"claude", "codex"}:
            raise SystemExit(f"unsupported provider: {provider!r}")

        if dry_run:
            commander_id = self._commander_id(name)
            if fresh:
                commander_id = self._fresh_commander_id(commander_id)
            elif name.strip():
                existing = self._commander_entry(commander_id)
                if existing:
                    session = str(existing.get("session", ""))
                    if session and self._tmux_has_session(session):
                        planned = dict(existing)
                        planned["_action"] = "planned"
                        return planned
            run_dir = self.state_dir / "commanders" / commander_id
            entry = {
                "id": commander_id,
                "provider": normalized_provider,
                "role": "commander",
                "level": 1,
                "parent": parent.strip(),
                "status": "planned",
                "session": f"legion-mixed-{self.context.project_hash}-{commander_id}",
                "run_dir": str(run_dir),
                "project": str(self.context.project_dir),
                "aicto_authority": self._aicto_control_contract(commander_id),
                "updated": iso_now(),
                "_action": "planned",
            }
            return entry

        self.init_state()

        if not name.strip() and not fresh and not dry_run:
            online = self._online_commander(normalized_provider, detached_only=False)
            if online:
                self._refresh_l1_commander_artifacts(online)
                online["status"] = "commanding"
                online["aicto_authority"] = self._aicto_control_contract(str(online.get("id", "")))
                online["updated"] = iso_now()
                self._upsert_commander(online)
                self._apply_commander_window_identity(online)
                self._event(
                    "commander_resumed",
                    str(online["id"]),
                    {"session": online.get("session", ""), "provider": normalized_provider},
                )
                online = self._announce_l1_online(online, action="resumed")
                online["_action"] = "载入在线军团"
                if attach and online.get("status") == "commanding":
                    os.execvp("tmux", self._tmux_foreground_argv(str(online["session"])))
                return online

        commander_id = self._commander_id(name)
        if fresh:
            commander_id = self._fresh_commander_id(commander_id)
        run_dir = self.state_dir / "commanders" / commander_id
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = run_dir / "prompt.md"
        launch_script = run_dir / "launch.sh"
        log_file = run_dir / "commander.log"
        session = f"legion-mixed-{self.context.project_hash}-{commander_id}"

        prompt_file.write_text(self.render_commander_prompt(commander_id, normalized_provider), encoding="utf-8")
        if normalized_provider == "codex":
            launch_text = self._codex_commander_launch_script(commander_id, prompt_file, log_file)
        else:
            launch_text = self._claude_commander_launch_script(commander_id, prompt_file, log_file)
        launch_script.write_text(launch_text, encoding="utf-8")
        launch_script.chmod(0o755)

        entry = {
            "id": commander_id,
            "provider": normalized_provider,
            "role": "commander",
            "level": 1,
            "parent": parent.strip(),
            "status": "planned" if dry_run else "launching",
            "session": session,
            "run_dir": str(run_dir),
            "project": str(self.context.project_dir),
            "aicto_authority": self._aicto_control_contract(commander_id),
            "updated": iso_now(),
        }
        self._upsert_commander(entry)
        self._event("commander_planned", commander_id, {"provider": normalized_provider, "session": session})

        if dry_run:
            entry["_action"] = "planned"
            return entry

        if self._tmux_has_session(session):
            entry["status"] = "commanding"
            self._upsert_commander(entry)
            self._event("commander_resumed", commander_id, {"session": session, "provider": normalized_provider})
            self._apply_commander_window_identity(entry)
            entry = self._announce_l1_online(entry, action="resumed")
            entry["_action"] = "载入在线军团"
            if attach and entry.get("status") == "commanding":
                os.execvp("tmux", self._tmux_foreground_argv(session))
            return entry

        code, stdout, stderr = self.runner.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(self.context.project_dir), "-n", commander_id]
        )
        if code != 0:
            return self._fail_commander_launch(
                entry,
                "commander_failed",
                f"tmux new-session failed: {(stderr or stdout).strip()}",
            )
        code, stdout, stderr = self.runner.run(
            ["tmux", "send-keys", "-t", f"{session}:{commander_id}", f"bash {shlex.quote(str(launch_script))}", "Enter"]
        )
        if code != 0:
            return self._fail_commander_launch(
                entry,
                "commander_failed",
                f"tmux send-keys failed: {(stderr or stdout).strip()}",
            )
        entry["status"] = "commanding"
        entry["updated"] = iso_now()
        self._upsert_commander(entry)
        self._event("commander_launched", commander_id, {"session": session, "provider": normalized_provider})
        entry = self._announce_l1_online(entry, action="launched")
        entry["_action"] = "新增军团"
        if attach and entry.get("status") == "commanding":
            os.execvp("tmux", self._tmux_foreground_argv(session))
        return entry

    def start_aicto(
        self,
        name: str = "",
        dry_run: bool = False,
        attach: bool = True,
    ) -> dict[str, Any]:
        commander_id = self._aicto_commander_id(name)
        run_dir = self.state_dir / "commanders" / commander_id
        session = f"legion-mixed-{self.context.project_hash}-{commander_id}"
        if dry_run:
            return {
                "id": commander_id,
                "provider": "codex",
                "runtime_provider": "codex",
                "role": "aicto",
                "level": 0,
                "branch": "command",
                "parent": "",
                "lifecycle": "persistent",
                "status": "planned",
                "session": session,
                "run_dir": str(run_dir),
                "project": str(self.context.project_dir),
                "updated": iso_now(),
                "_action": "planned",
            }

        self.init_state()
        existing = self._commander_entry(commander_id)
        if existing:
            existing_session = str(existing.get("session", ""))
            if existing_session and self._tmux_has_session(existing_session):
                resumed = dict(existing)
                resumed.update(
                    {
                        "provider": "codex",
                        "runtime_provider": "codex",
                        "role": "aicto",
                        "level": 0,
                        "branch": "command",
                        "parent": "",
                        "lifecycle": "persistent",
                        "status": "commanding",
                        "project": str(self.context.project_dir),
                        "updated": iso_now(),
                    }
                )
                self._upsert_commander(resumed)
                self._event("commander_resumed", commander_id, {"session": existing_session, "role": "aicto"})
                resumed["_action"] = "载入在线总司令"
                if attach:
                    os.execvp("tmux", self._tmux_foreground_argv(existing_session))
                return resumed

        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = run_dir / "prompt.md"
        launch_script = run_dir / "launch.sh"
        log_file = run_dir / "commander.log"
        prompt_file.write_text(self.render_aicto_prompt(commander_id), encoding="utf-8")
        launch_script.write_text(
            self._codex_commander_launch_script(
                commander_id,
                prompt_file,
                log_file,
                display_label="local L0 coordinator",
            ),
            encoding="utf-8",
        )
        launch_script.chmod(0o755)

        entry = {
            "id": commander_id,
            "provider": "codex",
            "runtime_provider": "codex",
            "role": "aicto",
            "level": 0,
            "branch": "command",
            "parent": "",
            "lifecycle": "persistent",
            "status": "launching",
            "session": session,
            "run_dir": str(run_dir),
            "project": str(self.context.project_dir),
            "aicto_authority": self._aicto_control_contract(commander_id),
            "updated": iso_now(),
        }
        self._upsert_commander(entry)
        self._event("aicto_planned", commander_id, {"session": session, "runtime_provider": "codex"})

        if self._tmux_has_session(session):
            entry["status"] = "commanding"
            self._upsert_commander(entry)
            entry["_action"] = "载入在线总司令"
            if attach:
                os.execvp("tmux", self._tmux_foreground_argv(session))
            return entry

        code, stdout, stderr = self.runner.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(self.context.project_dir), "-n", commander_id]
        )
        if code != 0:
            return self._fail_commander_launch(
                entry,
                "aicto_failed",
                f"tmux new-session failed: {(stderr or stdout).strip()}",
            )
        code, stdout, stderr = self.runner.run(
            ["tmux", "send-keys", "-t", f"{session}:{commander_id}", f"bash {shlex.quote(str(launch_script))}", "Enter"]
        )
        if code != 0:
            return self._fail_commander_launch(
                entry,
                "aicto_failed",
                f"tmux send-keys failed: {(stderr or stdout).strip()}",
            )
        entry["status"] = "commanding"
        entry["updated"] = iso_now()
        self._upsert_commander(entry)
        self._event("aicto_launched", commander_id, {"session": session, "runtime_provider": "codex"})
        entry["_action"] = "新增总司令"
        if attach:
            os.execvp("tmux", self._tmux_foreground_argv(session))
        return entry

    def prepare_commander_launch_artifacts(
        self,
        provider: str,
        name: str = "",
        fresh: bool = False,
        status: str = "planned",
    ) -> dict[str, Any]:
        """Create L1 prompt/launch artifacts without starting a tmux session."""
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {"claude", "codex"}:
            raise SystemExit(f"unsupported provider: {provider!r}")
        if status not in {"planned", "launching", "commanding"}:
            raise SystemExit(f"unsupported commander artifact status: {status!r}")

        self.init_state()
        commander_id = self._commander_id(name)
        if fresh:
            commander_id = self._fresh_commander_id(commander_id)
        run_dir = self.state_dir / "commanders" / commander_id
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = run_dir / "prompt.md"
        launch_script = run_dir / "launch.sh"
        log_file = run_dir / "commander.log"
        session = f"legion-mixed-{self.context.project_hash}-{commander_id}"

        prompt_file.write_text(self.render_commander_prompt(commander_id, normalized_provider), encoding="utf-8")
        if normalized_provider == "codex":
            launch_text = self._codex_commander_launch_script(commander_id, prompt_file, log_file)
        else:
            launch_text = self._claude_commander_launch_script(commander_id, prompt_file, log_file)
        launch_script.write_text(launch_text, encoding="utf-8")
        launch_script.chmod(0o755)

        entry = {
            "id": commander_id,
            "provider": normalized_provider,
            "role": "commander",
            "level": 1,
            "status": status,
            "session": session,
            "run_dir": str(run_dir),
            "project": str(self.context.project_dir),
            "updated": iso_now(),
        }
        self._upsert_commander(entry)
        self._event("commander_planned", commander_id, {"provider": normalized_provider, "session": session})
        return entry

    def register_external_commander(
        self,
        provider: str,
        commander_id: str,
        session: str = "",
        status: str = "commanding",
    ) -> dict[str, Any]:
        self.init_state()
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {"claude", "codex"}:
            raise SystemExit(f"unsupported provider: {provider!r}")
        entry = {
            "id": commander_id,
            "provider": normalized_provider,
            "role": "commander",
            "level": 1,
            "status": status,
            "session": session,
            "run_dir": "",
            "project": str(self.context.project_dir),
            "aicto_authority": self._aicto_control_contract(commander_id),
            "updated": iso_now(),
        }
        self._upsert_commander(entry)
        self._event("commander_registered", commander_id, {"provider": normalized_provider, "session": session})
        if status == "commanding":
            entry = self._announce_l1_online(entry, action="registered")
        return entry

    def convene_host(
        self,
        host_provider: str = "claude",
        host_name: str = "",
        claude_branch: str = "implement",
        codex_branch: str = "audit",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        normalized_host_provider = host_provider.strip().lower() if host_provider else "claude"
        if normalized_host_provider not in {"claude", "codex"}:
            raise SystemExit(f"unsupported host provider: {host_provider!r}")

        resolved_host_name = host_name.strip() or self._project_host_name(normalized_host_provider)
        host = self.start_commander(
            provider=normalized_host_provider,
            name=resolved_host_name,
            dry_run=dry_run,
            attach=False,
        )
        claude_l2 = self.create_branch_commander(
            branch=claude_branch,
            provider="claude",
            parent=str(host["id"]),
            dry_run=dry_run,
            attach=False,
            lifecycle="host",
        )
        codex_l2 = self.create_branch_commander(
            branch=codex_branch,
            provider="codex",
            parent=str(host["id"]),
            dry_run=dry_run,
            attach=False,
            lifecycle="host",
        )
        if not dry_run:
            self._event(
                "host_convened",
                str(host["id"]),
                {
                    "host_provider": normalized_host_provider,
                    "claude_l2": claude_l2["id"],
                    "codex_l2": codex_l2["id"],
                    "dry_run": dry_run,
                },
            )
        if not dry_run:
            self._send_host_readiness_order(host, [claude_l2, codex_l2])
        return {"host": host, "l2": [claude_l2, codex_l2], "claude_l2": claude_l2, "codex_l2": codex_l2}

    def convene_dual_host(
        self,
        claude_name: str = "",
        codex_name: str = "",
        claude_branch: str = "implement",
        codex_branch: str = "audit",
        dry_run: bool = False,
        parent: str = "",
        base_l2: bool = False,
        peer_delay_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Convene provider-owned Claude and Codex L1 commanders.

        Legion Core is the L0 coordination layer. Claude L1 owns Claude branch
        commanders; Codex L1 owns Codex branch commanders. By default startup is
        L1-only; M+ campaigns create visible L2/team windows when collaboration is
        needed. Cross-provider work moves through durable orders and results
        instead of one L1 spoofing the other's execution context.
        """
        claude_l1 = self.start_commander(
            provider="claude",
            name=claude_name.strip() or self._project_provider_l1_name("claude"),
            dry_run=dry_run,
            attach=False,
            parent=parent.strip(),
        )
        codex_l1 = self.start_commander(
            provider="codex",
            name=codex_name.strip() or self._project_provider_l1_name("codex"),
            dry_run=dry_run,
            attach=False,
            parent=parent.strip(),
        )
        claude_l2: dict[str, Any] | None = None
        codex_l2: dict[str, Any] | None = None
        l2_commanders: list[dict[str, Any]] = []
        if base_l2:
            claude_l2 = self.create_branch_commander(
                branch=claude_branch,
                provider="claude",
                parent=str(claude_l1["id"]),
                dry_run=dry_run,
                attach=False,
                lifecycle="host",
            )
            codex_l2 = self.create_branch_commander(
                branch=codex_branch,
                provider="codex",
                parent=str(codex_l1["id"]),
                dry_run=dry_run,
                attach=False,
                lifecycle="host",
            )
            l2_commanders = [claude_l2, codex_l2]
        if not dry_run:
            self._ensure_convened_commanders_live([claude_l1, codex_l1, *l2_commanders])
            self._event(
                "dual_host_convened",
                "dual-l1",
                {
                    "claude_l1": claude_l1["id"],
                    "codex_l1": codex_l1["id"],
                    "claude_l2": claude_l2["id"] if claude_l2 else "",
                    "codex_l2": codex_l2["id"] if codex_l2 else "",
                    "base_l2": base_l2,
                    "dry_run": dry_run,
                },
            )
            if base_l2 and claude_l2 and codex_l2:
                self._send_host_readiness_order(claude_l1, [claude_l2])
                self._send_host_readiness_order(codex_l1, [codex_l2])
            else:
                self._clear_readiness_orders(
                    [str(claude_l1["id"]), str(codex_l1["id"])],
                    reason="dual-l1-only-startup",
                )
            self._send_dual_l1_peer_sync(claude_l1, codex_l1, delay_seconds=peer_delay_seconds)
        return {
            "hosts": [claude_l1, codex_l1],
            "l2": l2_commanders,
            "claude_l1": claude_l1,
            "codex_l1": codex_l1,
            "claude_l2": claude_l2,
            "codex_l2": codex_l2,
            "base_l2": base_l2,
        }

    def convene_aicto(
        self,
        name: str = "",
        claude_name: str = "",
        codex_name: str = "",
        claude_branch: str = "implement",
        codex_branch: str = "audit",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Legacy helper for a local L0 coordinator and provider-owned Claude/Codex armies."""
        aicto = self.start_aicto(name=name, dry_run=dry_run, attach=False)
        convened = self.convene_dual_host(
            claude_name=claude_name,
            codex_name=codex_name,
            claude_branch=claude_branch,
            codex_branch=codex_branch,
            dry_run=dry_run,
            parent=str(aicto["id"]),
            base_l2=True,
        )
        if not dry_run:
            self._ensure_convened_commanders_live([aicto, *convened["hosts"], *convened["l2"]])
            self._event(
                "aicto_convened",
                str(aicto["id"]),
                {
                    "claude_l1": convened["claude_l1"]["id"],
                    "codex_l1": convened["codex_l1"]["id"],
                    "claude_l2": convened["claude_l2"]["id"],
                    "codex_l2": convened["codex_l2"]["id"],
                    "dry_run": dry_run,
                },
            )
            self._send_host_readiness_order(aicto, convened["hosts"])
        result = dict(convened)
        result["aicto"] = aicto
        return result

    def create_branch_commander(
        self,
        branch: str,
        provider: str = "auto",
        parent: str = "L1-mixed",
        dry_run: bool = False,
        attach: bool = False,
        lifecycle: str = "manual",
    ) -> dict[str, Any]:
        normalized_branch = normalize_branch(branch)
        if not normalized_branch:
            raise SystemExit("branch is required")
        normalized_provider = provider.strip().lower() if provider else "auto"
        if normalized_provider == "auto":
            normalized_provider = default_provider_for_branch(normalized_branch)
        if normalized_provider not in {"claude", "codex"}:
            raise SystemExit(f"unsupported provider: {provider!r}")

        if dry_run:
            existing = self._branch_commander(normalized_branch, parent, normalized_provider)
            if existing and self._branch_commander_is_reusable(existing, dry_run):
                return dict(existing)
            commander_id = self._branch_commander_id(normalized_branch)
            run_dir = self.state_dir / "commanders" / commander_id
            return {
                "id": commander_id,
                "provider": normalized_provider,
                "role": "branch-commander",
                "level": 2,
                "branch": normalized_branch,
                "parent": parent,
                "lifecycle": lifecycle,
                "status": "planned",
                "session": f"legion-mixed-{self.context.project_hash}-{commander_id}",
                "run_dir": str(run_dir),
                "project": str(self.context.project_dir),
                "updated": iso_now(),
            }

        self.init_state()

        existing = self._branch_commander(normalized_branch, parent, normalized_provider)
        if existing and self._branch_commander_is_reusable(existing, dry_run):
            return self._refresh_reused_branch_commander(existing, lifecycle)

        commander_id = self._branch_commander_id(normalized_branch)
        run_dir = self.state_dir / "commanders" / commander_id
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = run_dir / "prompt.md"
        launch_script = run_dir / "launch.sh"
        log_file = run_dir / "commander.log"
        session = f"legion-mixed-{self.context.project_hash}-{commander_id}"

        prompt_file.write_text(
            self.render_branch_commander_prompt(commander_id, normalized_branch, normalized_provider, parent),
            encoding="utf-8",
        )
        launch_script.write_text(
            self._branch_commander_launch_script(commander_id, normalized_provider, prompt_file, log_file),
            encoding="utf-8",
        )
        launch_script.chmod(0o755)

        entry = {
            "id": commander_id,
            "provider": normalized_provider,
            "role": "branch-commander",
            "level": 2,
            "branch": normalized_branch,
            "parent": parent,
            "lifecycle": lifecycle,
            "status": "planned" if dry_run else "launching",
            "session": session,
            "run_dir": str(run_dir),
            "project": str(self.context.project_dir),
            "updated": iso_now(),
        }
        self._upsert_commander(entry)
        self._event(
            "branch_commander_planned",
            commander_id,
            {"provider": normalized_provider, "branch": normalized_branch, "parent": parent},
        )

        if dry_run:
            return entry

        if self._tmux_has_session(session):
            entry["status"] = "commanding"
            self._upsert_commander(entry)
            if attach:
                os.execvp("tmux", ["tmux", "a", "-t", session])
            return entry

        code, stdout, stderr = self.runner.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(self.context.project_dir), "-n", commander_id]
        )
        if code != 0:
            return self._fail_commander_launch(
                entry,
                "branch_commander_failed",
                f"tmux new-session failed: {(stderr or stdout).strip()}",
            )
        code, stdout, stderr = self.runner.run(
            ["tmux", "send-keys", "-t", f"{session}:{commander_id}", f"bash {shlex.quote(str(launch_script))}", "Enter"]
        )
        if code != 0:
            return self._fail_commander_launch(
                entry,
                "branch_commander_failed",
                f"tmux send-keys failed: {(stderr or stdout).strip()}",
            )
        entry["status"] = "commanding"
        entry["updated"] = iso_now()
        self._upsert_commander(entry)
        self._event("branch_commander_launched", commander_id, {"session": session, "provider": normalized_provider})
        if attach:
            os.execvp("tmux", ["tmux", "a", "-t", session])
        return entry

    def deploy_campaign(
        self,
        plan: Iterable[dict[str, Any]],
        commander: str = "auto",
        dry_run: bool = False,
        corps: bool = False,
        direct: bool = False,
    ) -> list[TaskSpec]:
        if not dry_run:
            self.init_state()
        resolved_commander = self._resolve_commander(commander)
        explicit_commander = not self._is_implicit_commander_request(commander)
        self._validate_campaign_commander(resolved_commander, explicit_commander)
        specs = [TaskSpec.from_mapping(item, index=i + 1) for i, item in enumerate(plan)]
        if not specs:
            raise SystemExit("campaign plan is empty")
        for spec in specs:
            if not spec.task:
                raise SystemExit(f"{spec.task_id}: task is required")
        for spec in specs:
            if not spec.complexity:
                spec.complexity = self._infer_task_complexity(spec, len(specs))
        use_corps = self._should_use_corps(resolved_commander, specs, force=corps, direct=direct)

        # L1 defaults are stable and shallow: S work can stay with the L1.
        # M+ delivery still flows through L2/corps unless the caller explicitly
        # marks a non-delivery command-plane maintenance task as direct.
        if (
            self._commander_level(resolved_commander) == 1
            and not use_corps
            and COMPLEXITY_ORDER.get(self._campaign_complexity(specs), 1) >= COMPLEXITY_ORDER["m"]
        ):
            offenders = [spec for spec in specs if self._is_delivery_spec(spec)]
            if offenders:
                ids = ", ".join(spec.task_id for spec in offenders)
                raise SystemExit(
                    f"L1 M+ no-delivery: {ids} carries a delivery role/branch; route through L2/corps or set role/branch to a non-delivery slice"
                )

        self._normalize_campaign_scopes(specs)
        if dry_run:
            existing_tasks = list(self._read_registry().get("tasks", [])) if self.registry_file.exists() else []
            self._assert_campaign_scope_conflicts(specs, existing_tasks)
            return specs

        assignment_messages: list[tuple[str, str]] = []
        with self._registry_lock():
            registry = self._read_registry()
            self._assert_campaign_scope_conflicts(specs, list(registry.get("tasks", [])))

            for spec in specs:
                assigned_commander = resolved_commander
                assigned_commander_lifecycle = "direct"
                assignment_block: dict[str, Any] | None = None
                if use_corps:
                    branch = spec.branch or normalize_branch(spec.role)
                    spec.branch = branch
                    branch_commander = self.create_branch_commander(
                        branch=branch,
                        provider=spec.provider,
                        parent=resolved_commander,
                        dry_run=False,
                        attach=False,
                        lifecycle="campaign",
                    )
                    assigned_commander = branch_commander["id"]
                    assigned_commander_lifecycle = str(branch_commander.get("lifecycle", "campaign"))
                    ok, reason = self._commander_active_live(assigned_commander)
                    if not ok:
                        assignment_block = {
                            "blocked_reason": f"assigned commander unavailable: {reason}",
                            "commander_unavailable": {"commander": assigned_commander, "reason": reason},
                        }
                run_dir = self._run_dir(spec)
                run_dir.mkdir(parents=True, exist_ok=True)
                prompt_file = run_dir / "prompt.md"
                prompt_file.write_text(self.render_prompt(spec, assigned_commander), encoding="utf-8")
                entry = spec.as_registry_entry("blocked" if assignment_block else "planned", assigned_commander, run_dir)
                entry["origin_commander"] = resolved_commander
                entry["commander_lifecycle"] = assigned_commander_lifecycle
                entry["retain_context"] = self._spec_retains_context(spec)
                if assignment_block:
                    entry.update(assignment_block)
                context_policy = str(spec.raw.get("context_policy", "")).strip().lower()
                if context_policy:
                    entry["context_policy"] = context_policy
                self._upsert_task(entry)
                self._event(
                    "task_planned",
                    spec.task_id,
                    {
                        "provider": spec.provider,
                        "role": spec.role,
                        "commander": assigned_commander,
                        "origin_commander": resolved_commander,
                        "corps": use_corps,
                        "complexity": spec.complexity,
                    },
                )
                if assignment_block:
                    self._event(
                        "task_blocked",
                        spec.task_id,
                        {
                            "reason": "assigned-commander-unavailable",
                            "commander": assigned_commander,
                            "detail": assignment_block["blocked_reason"],
                        },
                    )
                elif use_corps:
                    scope_summary = ", ".join(spec.scope) if spec.scope else "(none)"
                    dependency_summary = ", ".join(spec.depends_on) if spec.depends_on else "(none)"
                    assignment_messages.append(
                        (
                            assigned_commander,
                            (
                                "TASK-ASSIGNED: "
                                f"id={spec.task_id} role={spec.role} provider={spec.provider} "
                                f"complexity={spec.complexity} origin={resolved_commander}. "
                                f"target={spec.task} scope={scope_summary} depends_on={dependency_summary}. "
                                "L2 activation is task-scoped: identify yourself, load only relevant project/tactic/skill context, "
                                "do minimal pre-research for this target, then supervise this worker through Legion Core status/result tracking."
                            ),
                        )
                    )

        for assigned_commander, content in assignment_messages:
            self.send_message(
                assigned_commander,
                content,
                sender=resolved_commander,
                message_type="task-assigned",
            )

        self.ensure_tmux_session()
        if not explicit_commander:
            self._ensure_runtime_commander_entry(resolved_commander)
        self._launch_ready_tasks()
        return specs

    def _resolve_commander(self, commander: str = "auto") -> str:
        requested = (commander or "").strip()
        if requested and requested.lower() not in {"auto", "current"}:
            return requested
        for key in ("LEGION_COMMANDER_ID", "CLAUDE_CODE_AGENT_NAME", "CLAUDE_LEGION_TEAM_ID"):
            value = os.environ.get(key, "").strip()
            if value.startswith(("L1-", "L2-")):
                return value
        return "L1-mixed"

    def _is_implicit_commander_request(self, requested_commander: str) -> bool:
        requested = (requested_commander or "").strip()
        return not requested or requested.lower() in {"auto", "current", "l1-mixed"}

    def _validate_campaign_commander(self, resolved_commander: str, explicit_commander: bool) -> None:
        if self._commander_entry(resolved_commander):
            return
        if explicit_commander:
            raise SystemExit(f"unknown commander: {resolved_commander}")

    def _ensure_runtime_commander_entry(self, commander_id: str) -> None:
        if self._commander_entry(commander_id):
            return
        if not commander_id.startswith(("L1-", "L2-")):
            return
        role = "commander" if commander_id.startswith("L1-") else "branch-commander"
        entry = {
            "id": commander_id,
            "provider": "mixed",
            "role": role,
            "level": 1 if role == "commander" else 2,
            "branch": "",
            "parent": "",
            "status": "commanding",
            "session": self.context.session_name,
            "run_dir": "",
            "project": str(self.context.project_dir),
            "updated": iso_now(),
            "synthetic_runtime": True,
        }
        self._upsert_commander(entry)
        self._event(
            "commander_registered",
            commander_id,
            {"provider": "mixed", "session": self.context.session_name, "synthetic_runtime": True},
        )

    def _is_delivery_spec(self, spec: TaskSpec) -> bool:
        return self._is_delivery_role_or_branch(spec.role, spec.branch)

    def _is_delivery_role_or_branch(self, role: str, branch: str) -> bool:
        normalized_role = (role or "").strip().lower()
        normalized_branch = normalize_branch(branch or "")
        if normalized_role in DELIVERY_ROLES:
            return True
        if normalized_branch in DELIVERY_BRANCHES:
            return True
        return False

    def _normalize_campaign_scopes(self, specs: list[TaskSpec]) -> None:
        for spec in specs:
            spec.scope = self._normalize_scope_paths(spec.scope, spec.task_id)
            if self._is_delivery_spec(spec) and not spec.scope:
                raise SystemExit(f"{spec.task_id}: delivery tasks must declare non-empty file scope")

    def _normalize_scope_paths(self, scope: Iterable[str], task_id: str) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in scope:
            path = self._normalize_scope_path(str(item), task_id)
            if path in seen:
                continue
            seen.add(path)
            normalized.append(path)
        return normalized

    def _normalize_scope_path(self, raw_path: str, task_id: str) -> str:
        display = raw_path.strip()
        if not display:
            raise SystemExit(f"{task_id}: scope path cannot be empty")
        if "\0" in display:
            raise SystemExit(f"{task_id}: scope path contains an invalid null byte")
        candidate = Path(display)
        if candidate.is_absolute():
            raise SystemExit(f"{task_id}: scope path must be project-relative: {display}")
        parts = [part for part in candidate.parts if part not in {"", "."}]
        if not parts:
            raise SystemExit(f"{task_id}: scope path cannot be the project root")
        if any(part == ".." for part in parts):
            raise SystemExit(f"{task_id}: scope path cannot traverse outside the project: {display}")
        normalized = Path(*parts).as_posix()
        project_root = self.context.project_dir.resolve(strict=False)
        absolute = (project_root / normalized).resolve(strict=False)
        try:
            absolute.relative_to(project_root)
        except ValueError:
            raise SystemExit(f"{task_id}: scope path is outside the project: {display}") from None
        return normalized

    def _assert_campaign_scope_conflicts(self, specs: list[TaskSpec], existing_tasks: list[dict[str, Any]]) -> None:
        active_scopes: list[tuple[str, str]] = []
        for task in existing_tasks:
            if str(task.get("status", "")) in TERMINAL_TASK_STATUSES:
                continue
            if not self._is_delivery_role_or_branch(str(task.get("role", "")), str(task.get("branch", ""))):
                continue
            task_id = str(task.get("id", ""))
            for scope_path in task.get("scope") or []:
                normalized = self._normalize_scope_path(str(scope_path), task_id or "existing-task")
                active_scopes.append((normalized, task_id))

        new_scopes: list[tuple[str, str]] = []
        for spec in specs:
            if not self._is_delivery_spec(spec):
                continue
            for normalized in spec.scope:
                for active_scope, active_owner in active_scopes:
                    if active_owner != spec.task_id and self._scope_paths_overlap(normalized, active_scope):
                        raise SystemExit(
                            f"scope conflict: {spec.task_id} claims {normalized} overlapping active task {active_owner} scope {active_scope}"
                        )
                for new_scope, new_owner in new_scopes:
                    if new_owner != spec.task_id and self._scope_paths_overlap(normalized, new_scope):
                        raise SystemExit(
                            f"scope conflict: {spec.task_id} claims {normalized} overlapping {new_owner} scope {new_scope} in this campaign"
                        )
                new_scopes.append((normalized, spec.task_id))

    def _scope_paths_overlap(self, left: str, right: str) -> bool:
        if left == right:
            return True
        return left.startswith(f"{right}/") or right.startswith(f"{left}/")

    def _launch_scope_conflict(self, task: dict[str, Any]) -> dict[str, str] | None:
        if not self._is_delivery_role_or_branch(str(task.get("role", "")), str(task.get("branch", ""))):
            return None
        task_id = str(task.get("id", ""))
        scope_paths = [
            self._normalize_scope_path(str(item), task_id or "task")
            for item in (task.get("scope") or [])
        ]
        if not scope_paths:
            return None
        for other in self._read_registry().get("tasks", []):
            other_id = str(other.get("id", ""))
            if not other_id or other_id == task_id:
                continue
            if str(other.get("status", "")) not in {"launching", "launched", "running"}:
                continue
            if not self._is_delivery_role_or_branch(str(other.get("role", "")), str(other.get("branch", ""))):
                continue
            for left in scope_paths:
                for raw_right in other.get("scope") or []:
                    right = self._normalize_scope_path(str(raw_right), other_id)
                    if self._scope_paths_overlap(left, right):
                        return {
                            "task": task_id,
                            "scope": left,
                            "conflicts_with": other_id,
                            "conflict_scope": right,
                        }
        return None

    def _block_task_scope_conflict(self, task_id: str, conflict: dict[str, str]) -> None:
        reason = (
            f"scope conflict: {task_id} claims {conflict['scope']} overlapping "
            f"{conflict['conflicts_with']} scope {conflict['conflict_scope']}"
        )
        self._set_task_status(
            task_id,
            "blocked",
            {
                "blocked_reason": reason,
                "scope_conflict": conflict,
            },
        )
        self._event("scope_conflict_blocked", task_id, {"reason": reason, "conflict": conflict})

    def _commander_level(self, commander: str) -> int:
        entry = self._commander_entry(commander)
        if entry and isinstance(entry.get("level"), int):
            return int(entry["level"])
        if commander.startswith("L1-"):
            return 1
        if commander.startswith("L2-"):
            return 2
        return 0

    def _commander_active_live(self, commander_id: str) -> tuple[bool, str]:
        commander = self._commander_entry(commander_id)
        if not commander:
            return False, f"unknown commander {commander_id}"
        status = str(commander.get("status", ""))
        if status not in ACTIVE_COMMANDER_STATUSES:
            return False, f"commander {commander_id} is {status or 'unknown'}"
        session = str(commander.get("session", ""))
        if not session:
            return False, f"commander {commander_id} has no tmux session"
        probe = self._tmux_probe_session(session)
        if probe["state"] == "live":
            return True, ""
        detail = probe.get("detail", "") or "tmux session is not alive"
        return False, f"commander {commander_id} tmux {probe['state']}: {detail}"

    def _infer_task_complexity(self, spec: TaskSpec, campaign_size: int) -> str:
        if campaign_size > 1:
            return "m"
        if spec.depends_on or spec.branch:
            return "m"
        if spec.role in CODEX_DEFAULT_ROLES or spec.role in {"security"}:
            return "m"
        if len(spec.scope) > 1:
            return "m"
        return "s"

    def _campaign_complexity(self, specs: list[TaskSpec]) -> str:
        return max((spec.complexity or "s" for spec in specs), key=lambda item: COMPLEXITY_ORDER.get(item, 1))

    def _should_use_corps(self, commander: str, specs: list[TaskSpec], force: bool, direct: bool) -> bool:
        if force:
            return True
        if direct:
            return False
        if self._commander_level(commander) != 1:
            return False
        return COMPLEXITY_ORDER.get(self._campaign_complexity(specs), 1) >= COMPLEXITY_ORDER["m"]

    def launch_task(self, spec: TaskSpec, commander: str) -> bool:
        ok, reason = self._commander_active_live(commander)
        if not ok:
            self._set_task_status(
                spec.task_id,
                "blocked",
                {
                    "blocked_reason": f"assigned commander unavailable: {reason}",
                    "commander_unavailable": {"commander": commander, "reason": reason},
                },
            )
            return False
        commander_entry = self._commander_entry(commander) or {}
        target_session = str(commander_entry.get("session") or self.context.session_name).strip()
        current = self._task_entry(spec.task_id)
        if current:
            conflict = self._launch_scope_conflict(current)
            if conflict:
                self._block_task_scope_conflict(spec.task_id, conflict)
                return False

        run_dir = self._run_dir(spec)
        prompt_file = run_dir / "prompt.md"
        result_file = run_dir / "result.md"
        log_file = run_dir / "worker.log"
        launch_script = run_dir / "launch.sh"

        launch_body = self._adapter_launch_body(spec, prompt_file, result_file)
        launch_script.write_text(
            self._launch_script(spec, commander, launch_body, log_file),
            encoding="utf-8",
        )
        launch_script.chmod(0o755)

        window = f"w-{spec.task_id}"[:60]
        code, stdout, stderr = self.runner.run(
            ["tmux", "new-window", "-t", f"{target_session}:", "-n", window, "-c", str(self.context.project_dir)]
        )
        if code != 0:
            self._fail_task_launch(spec.task_id, f"tmux new-window failed: {(stderr or stdout).strip()}")
            return False

        code, stdout, stderr = self.runner.run(
            ["tmux", "send-keys", "-t", f"{target_session}:{window}", f"bash {shlex.quote(str(launch_script))}", "Enter"]
        )
        if code != 0:
            self._fail_task_launch(spec.task_id, f"tmux send-keys failed: {(stderr or stdout).strip()}")
            return False

        self._set_task_status(spec.task_id, "launched", {"window": window, "session": target_session})
        launched_entry = self._task_entry(spec.task_id)
        return bool(launched_entry and launched_entry.get("status") == "launched")

    def mark_task(self, task_id: str, status: str) -> None:
        self.init_state()
        self._set_task_status(task_id, status)

    def send_message(
        self,
        target: str,
        content: str,
        sender: str = "L1-mixed",
        message_type: str = "message",
        correlation_id: str = "",
        dedupe_key: str = "",
    ) -> dict[str, Any]:
        self.init_state()
        target_id = target.strip()
        sender_id = sender.strip() or "L1-mixed"
        body = content.strip()
        if not target_id:
            raise SystemExit("target commander is required")
        if not body:
            raise SystemExit("message content is required")

        commander = self._commander_entry(target_id)
        if not commander:
            raise SystemExit(f"unknown commander: {target_id}")

        now = iso_now()
        correlation = correlation_id.strip() or self._new_correlation_id(f"msg:{sender_id}:{target_id}:{message_type}")
        parsed_control = self._parse_control_fields(body)
        sender_auth = self._sender_authentication(sender_id)
        message_id = (
            self._stable_message_id(dedupe_key, sender_id, target_id, body, message_type, correlation)
            if dedupe_key
            else f"msg-{time.time_ns()}-{random.randint(1000, 9999)}"
        )
        record: dict[str, Any] = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "id": message_id,
            "ts": now,
            "timestamp": now,
            "correlation_id": correlation,
            "from": sender_id,
            "to": target_id,
            "type": message_type,
            "content": body,
            "control": parsed_control,
            "sender_verified": bool(sender_auth.get("verified")),
            "sender_auth": sender_auth,
        }
        # Persist to durable inbox before any tmux delivery so a pane crash never
        # loses messages. tmux delivery is best-effort metadata.
        appended = self._append_inbox(target_id, record)
        delivered_tmux = self._deliver_tmux_message(commander, record)
        record["delivered_tmux"] = delivered_tmux
        record["appended"] = appended
        self._event(
            "message_sent",
            target_id,
            {
                "from": sender_id,
                "type": message_type,
                "delivered_tmux": delivered_tmux,
                "id": record["id"],
                "appended": appended,
                "correlation_id": correlation,
            },
            correlation_id=correlation,
        )
        return record

    def broadcast_message(
        self,
        content: str,
        sender: str = "L1-mixed",
        l2_only: bool = False,
        parent: str = "",
        correlation_id: str = "",
    ) -> list[dict[str, Any]]:
        self.init_state()
        sender_id = sender.strip() or "L1-mixed"
        parent_id = parent.strip()
        correlation = correlation_id.strip() or self._new_correlation_id(f"broadcast:{sender_id}:{parent_id}:{content}")
        with self._registry_lock():
            recipients = []
            for commander in self._read_registry().get("commanders", []):
                commander_id = str(commander.get("id", ""))
                if not commander_id or commander_id == sender_id:
                    continue
                if commander.get("status") not in ACTIVE_COMMANDER_STATUSES:
                    continue
                if not self._commander_project_matches(commander):
                    continue
                if not self._commander_has_live_session(commander):
                    continue
                if l2_only and commander.get("role") != "branch-commander":
                    continue
                if parent_id and commander.get("parent") != parent_id:
                    continue
                recipients.append(commander_id)
        self._event(
            "broadcast_snapshot",
            sender_id,
            {
                "recipients": recipients,
                "l2_only": l2_only,
                "parent": parent_id,
                "correlation_id": correlation,
            },
            correlation_id=correlation,
        )
        return [
            self.send_message(
                target,
                content,
                sender=sender_id,
                message_type="broadcast",
                correlation_id=correlation,
                dedupe_key=f"broadcast:{correlation}:{target}",
            )
            for target in recipients
        ]

    def readiness_state(self, parent: str, expected: list[str] | None = None) -> dict[str, Any]:
        """Aggregate readiness for `parent`.

        Trust boundary:
        - Sender must be a registered direct child of `parent` in active status
          (local L0 coordinators expect direct L1s; L1 commanders expect direct L2s).
          Arbitrary --from strings cannot satisfy a roster slot.
        - Caller-supplied `expected` ids are intersected with that roster;
          unregistered or wrong-parent ids are returned as `rejected_expected`.
        - When a current readiness order exists, only records newer than
          `issued_at` and echoing the same `order_id` and `nonce` count.
        - When no current order exists (legacy/test path), free-text
          `READY:init-complete` records still count, but only from validated
          direct-L2 senders.
        """
        parent_id = parent.strip()
        if not parent_id:
            raise SystemExit("parent commander is required")

        order = self._current_readiness_order(parent_id)
        order_expected = [str(item).strip() for item in (order or {}).get("expected", []) if str(item).strip()]
        active_children = {str(item["id"]) for item in self._active_readiness_children(parent_id)}
        roster_ids = order_expected if order else sorted(active_children)
        requested = [item.strip() for item in (expected or []) if item.strip()]
        if requested:
            expected_ids = [item for item in requested if item in roster_ids]
            rejected_expected = [item for item in requested if item not in roster_ids]
        else:
            expected_ids = list(roster_ids)
            rejected_expected = []

        order_id = str(order.get("order_id", "")) if order else ""
        nonce = str(order.get("nonce", "")) if order else ""
        issued_ns = int(order.get("issued_at_ns", 0)) if order else 0

        ready: dict[str, dict[str, Any]] = {}
        inbox = self._inbox_file(parent_id)
        try:
            lines = [line for line in inbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        except FileNotFoundError:
            lines = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            sender = str(record.get("from", ""))
            if sender not in expected_ids:
                continue
            if sender not in active_children:
                continue
            if not self._is_readiness_record(record):
                continue
            if not self._record_sender_verified(record):
                continue
            if order:
                fields = self._record_control_fields(record)
                if order_id and fields.get("order_id") != order_id:
                    continue
                if nonce and fields.get("nonce") != nonce:
                    continue
                if issued_ns and not self._record_after(record, issued_ns, str(order.get("issued_at", ""))):
                    continue
            ready[sender] = record

        missing = [commander_id for commander_id in expected_ids if commander_id not in ready]
        result = {
            "parent": parent_id,
            "expected": expected_ids,
            "requested_expected": requested,
            "ready": ready,
            "missing": missing,
            "rejected_expected": rejected_expected,
        }
        if order:
            result["order"] = {"order_id": order_id, "nonce": nonce, "issued_at": order.get("issued_at", "")}
        return result

    def _record_after(self, record: dict[str, Any], threshold_ns: int, threshold_iso: str = "") -> bool:
        """True iff record's id-encoded ns timestamp is newer than threshold_ns.

        Falls back to comparing iso `ts` lexicographically when id is missing.
        """
        record_id = str(record.get("id", ""))
        if record_id.startswith("msg-"):
            try:
                ns_part = record_id.split("-", 2)[1]
                return int(ns_part) > threshold_ns
            except (IndexError, ValueError):
                pass
        # Fallback: rely on iso timestamp ordering at second granularity.
        ts = str(record.get("ts", ""))
        # Permissive (>=) so records without id still count when the iso second
        # matches the order, but stale malformed-id records are rejected.
        return bool(ts and threshold_iso and ts >= threshold_iso)

    def readiness_text(self, parent: str, expected: list[str] | None = None) -> str:
        state = self.readiness_state(parent, expected=expected)
        parent_id = str(state["parent"])
        child_label = self._readiness_child_label(parent_id)
        expected_ids = list(state["expected"])
        requested_expected = list(state.get("requested_expected") or [])
        display_expected = requested_expected or expected_ids
        ready = dict(state["ready"])
        missing = list(state["missing"])
        rejected = list(state.get("rejected_expected") or [])
        lines_out = [
            f"Readiness: {parent_id}",
            f"Expected {child_label}: {', '.join(display_expected) if display_expected else '(none)'}",
            f"Ready: {len(ready)}/{len(display_expected)}",
        ]
        order = state.get("order")
        if order:
            lines_out.append(
                f"Order: order_id={order.get('order_id', '')} nonce={order.get('nonce', '')} issued_at={order.get('issued_at', '')}"
            )
        if ready:
            lines_out.append("Ready commanders:")
            for commander_id in expected_ids:
                record = ready.get(commander_id)
                if record:
                    lines_out.append(f"  {commander_id}: {record.get('content', '')}")
        lines_out.append(f"Missing: {', '.join(missing) if missing else '(none)'}")
        if rejected:
            lines_out.append(f"Rejected expected (not direct {child_label} of parent): {', '.join(rejected)}")
        return "\n".join(lines_out)

    def wait_readiness(
        self,
        parent: str,
        expected: list[str] | None = None,
        timeout: float = 180.0,
        interval: float = 5.0,
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + max(timeout, 0.0)
        sleep_interval = max(interval, 0.5)
        while True:
            state = self.readiness_state(parent, expected=expected)
            text = self.readiness_text(parent, expected=expected)
            if state.get("rejected_expected"):
                return False, text
            if not state["missing"]:
                return True, text
            if time.monotonic() >= deadline:
                return False, text
            time.sleep(sleep_interval)

    def view_targets(self, host: str = "") -> list[dict[str, str]]:
        # Read-only: do not call reconcile_state from view (status/view contract).
        if not host.strip():
            try:
                return self.dual_view_targets()
            except SystemExit:
                pass
        host_entry = self._resolve_view_host(host)
        live_l2 = self._view_l2_entries(str(host_entry["id"]))
        if not live_l2:
            raise SystemExit(f"{host_entry['id']}: no live active task L2 commanders")
        targets = [self._view_target(host_entry, "L1")]
        for commander in live_l2:
            l2_kind = "base" if self._is_base_l2(commander) else "task"
            label = f"L2 {l2_kind} {commander.get('branch', '?')} [{commander.get('provider', '?')}]"
            targets.append(self._view_target(commander, label))
        return targets

    def open_view(self, host: str = "", session: str = "", fresh: bool = True, dry_run: bool = False) -> str:
        targets = self.view_targets(host=host)
        host_id = targets[0]["id"]
        view_session = session.strip() or f"legion-view-{self.context.project_hash}-{normalize_task_id(host_id)}"
        script = build_interactive_view_tmux_script(self.context.project_dir, view_session, targets, fresh=fresh)
        if dry_run:
            return script
        os.execvp("bash", ["bash", "-lc", script])
        raise SystemExit(1)

    def dual_view_targets(self, convened: dict[str, Any] | None = None) -> list[dict[str, str]]:
        if convened:
            hosts = [dict(convened["claude_l1"]), dict(convened["codex_l1"])]
            l2_commanders = [dict(commander) for commander in convened.get("l2", []) if commander]
            for commander in hosts + l2_commanders:
                self._validate_dual_view_commander(commander)
        else:
            hosts = [self._resolve_provider_l1("claude"), self._resolve_provider_l1("codex")]
            l2_commanders = []
            for host in hosts:
                l2_commanders.extend(self._active_direct_l2(str(host["id"])))
        targets = [self._view_target(hosts[0], "L1 Claude")]
        for commander in l2_commanders:
            label = f"L2 {commander.get('provider', '?')} {commander.get('branch', '?')}"
            targets.append(self._view_target(commander, label))
        targets.append(self._view_target(hosts[1], "L1 Codex"))
        return targets

    def open_dual_view(
        self,
        convened: dict[str, Any] | None = None,
        session: str = "",
        fresh: bool = True,
        dry_run: bool = False,
    ) -> str:
        targets = self.dual_view_targets(convened=convened)
        view_session = session.strip() or f"legion-view-{self.context.project_hash}-dual-l1"
        script = build_interactive_view_tmux_script(self.context.project_dir, view_session, targets, fresh=fresh)
        if dry_run:
            return script
        os.execvp("bash", ["bash", "-lc", script])
        raise SystemExit(1)

    def aicto_view_targets(self, convened: dict[str, Any] | None = None) -> list[dict[str, str]]:
        if convened:
            aicto = dict(convened["aicto"])
            hosts = [dict(convened["claude_l1"]), dict(convened["codex_l1"])]
            l2_commanders = [dict(commander) for commander in convened.get("l2", []) if commander]
            for commander in [aicto] + hosts + l2_commanders:
                self._validate_dual_view_commander(commander)
        else:
            aicto = self._resolve_aicto()
            hosts = self._active_direct_l1(str(aicto["id"]))
            l2_commanders = []
            for host in hosts:
                l2_commanders.extend(self._active_direct_l2(str(host["id"])))
        by_parent = {str(host["id"]): [] for host in hosts}
        for commander in l2_commanders:
            by_parent.setdefault(str(commander.get("parent", "")), []).append(commander)
        targets = [self._view_target(aicto, "L0 Coordinator")]
        for host in hosts:
            provider = str(host.get("provider", "?")).capitalize()
            targets.append(self._view_target(host, f"L1 {provider}"))
            for commander in by_parent.get(str(host["id"]), []):
                label = f"L2 {commander.get('provider', '?')} {commander.get('branch', '?')}"
                targets.append(self._view_target(commander, label))
        return targets

    def open_aicto_view(
        self,
        convened: dict[str, Any] | None = None,
        session: str = "",
        fresh: bool = True,
        dry_run: bool = False,
    ) -> str:
        targets = self.aicto_view_targets(convened=convened)
        view_session = session.strip() or f"legion-view-{self.context.project_hash}-aicto"
        script = build_interactive_view_tmux_script(self.context.project_dir, view_session, targets, fresh=fresh)
        if dry_run:
            return script
        os.execvp("bash", ["bash", "-lc", script])
        raise SystemExit(1)

    def inbox_text(self, target: str, tail: int = 20) -> str:
        target_id = target.strip()
        if not target_id:
            raise SystemExit("target commander is required")
        inbox = self._inbox_file(target_id)
        try:
            lines = [line for line in inbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        except FileNotFoundError:
            return f"Inbox: {target_id}\n  (empty)"
        selected = lines[-tail:] if tail > 0 else lines
        rendered = [f"Inbox: {target_id}"]
        for line in selected:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                rendered.append(f"  malformed: {line}")
                continue
            rendered.append(
                f"  [{record.get('ts','?')}] {record.get('from','?')} -> "
                f"{record.get('to','?')} {record.get('type','message')}: {record.get('content','')}"
            )
        return "\n".join(rendered)

    def aicto_reports_text(self, tail: int = 20) -> str:
        try:
            lines = [line for line in self.aicto_reports_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        except FileNotFoundError:
            return "AICTO reports:\n  (empty)"
        selected = lines[-tail:] if tail > 0 else lines
        rendered = ["AICTO reports:"]
        for line in selected:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                rendered.append(f"  malformed: {line}")
                continue
            rendered.append(
                f"  [{record.get('timestamp','?')}] {record.get('source','?')} "
                f"{record.get('kind','report')} {record.get('subject_id','?')}: {record.get('summary','')}"
            )
        return "\n".join(rendered)

    def queue_aicto_report(
        self,
        kind: str,
        subject_id: str,
        summary: str,
        source: str = "Legion Core",
        payload: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        report_kind = (kind or "report").strip()
        subject = (subject_id or "project").strip()
        body = (summary or "").strip()
        if not report_kind:
            raise SystemExit("AICTO report kind is required")
        if not subject:
            raise SystemExit("AICTO report subject is required")
        if not body:
            raise SystemExit("AICTO report summary is required")
        return self._queue_aicto_report(
            kind=report_kind,
            subject_id=subject,
            summary=body,
            source=source,
            payload=payload or {},
            correlation_id=correlation_id,
        )

    def complete_task_from_result(self, task_id: str, result_file: Path, process_status: int) -> None:
        self.init_state()
        extra: dict[str, Any] = {
            "result_file": str(result_file),
            "worker_exit_code": process_status,
        }
        result = self._read_worker_result(result_file)
        invalid_result = bool(result.pop("_invalid_result", False)) if result else False
        if result and not invalid_result:
            extra["result_status"] = result.get("status")
            if result.get("summary"):
                extra["result_summary"] = result.get("summary")

        if process_status != 0:
            status = "failed"
            extra["failure"] = f"worker exited with status {process_status}"
        else:
            if invalid_result:
                status = "failed"
                extra["failure"] = str(result.get("failure", "worker result was not valid JSON")) if result else "worker result was not valid JSON"
            elif result and result.get("status"):
                status = str(result.get("status"))
            else:
                status = "failed"
                extra["failure"] = "worker did not produce a valid structured result"

            if status not in {"completed", "blocked", "failed"}:
                status = "failed"
                extra["failure"] = f"unsupported worker result status: {result.get('status')!r}"
        self._set_task_status(task_id, status, extra)

    def ensure_tmux_session(self) -> None:
        code, _, _ = self.runner.run(["tmux", "has-session", "-t", self.context.session_name])
        if code == 0:
            return
        code, stdout, stderr = self.runner.run(
            ["tmux", "new-session", "-d", "-s", self.context.session_name, "-c", str(self.context.project_dir), "-n", "commander"]
        )
        if code != 0:
            raise SystemExit(f"tmux new-session failed: {(stderr or stdout).strip()}")
        status_cmd = f"watch -n2 {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} status"
        code, stdout, stderr = self.runner.run(["tmux", "send-keys", "-t", f"{self.context.session_name}:commander", status_cmd, "Enter"])
        if code != 0:
            raise SystemExit(f"tmux send-keys failed: {(stderr or stdout).strip()}")

    def status_text(self) -> str:
        # Read-only: status must never mutate registry/events. Use the explicit
        # `reconcile` command to fail stale tmux-bound commanders/tasks.
        registry = self._read_registry()
        lines = [
            f"Mixed Legion: {self.context.session_name}",
            f"State: {self.state_dir}",
            "",
        ]
        commanders = registry.get("commanders", [])
        lines.append("Commanders")
        if not commanders:
            lines.append("  (none)")
        else:
            for commander in commanders:
                commander_id = str(commander.get("id", ""))
                level = commander.get("level")
                if not level:
                    if commander_id.startswith("L1-"):
                        level = 1
                    elif commander_id.startswith("L2-"):
                        level = 2
                    else:
                        level = "?"
                branch = commander.get("branch") or "-"
                parent = commander.get("parent") or "-"
                lifecycle = commander.get("lifecycle") or "-"
                chains = commander.get("command_chains") or {}
                aicto_chain = (chains.get("aicto") or commander.get("aicto_link") or {}).get("status", "-")
                local_chain = (chains.get("local_l1") or commander.get("local_l1_link") or {}).get("status", "-")
                lines.append(
                    f"  {commander_id:18} {commander.get('provider','?'):7} "
                    f"{commander.get('status','?'):10} L{level} branch={branch} "
                    f"parent={parent} lifecycle={lifecycle} "
                    f"chain=AICTO:{aicto_chain}/localL1:{local_chain} {commander.get('session','')}"
                )
        lines.append("")

        tasks = registry.get("tasks", [])
        lines.append("Tasks")
        if not tasks:
            lines.append("  (none)")
            return "\n".join(lines)
        for task in tasks:
            scope = ", ".join(task.get("scope") or []) or "(auto)"
            commander = task.get("commander") or "-"
            origin = task.get("origin_commander") or commander
            complexity = task.get("complexity") or "?"
            branch = task.get("branch") or "-"
            lines.append(
                f"  {task['id']:16} {task.get('provider','?'):7} {task.get('role','?'):14} "
                f"{task.get('status','?'):10} C={complexity} {task.get('task','')[:70]}"
            )
            lines.append(f"  {'':16} commander: {commander} origin: {origin} branch: {branch} scope: {scope}")
        return "\n".join(lines)

    def reconcile_state(self) -> None:
        """Explicit reconcile: probes tmux liveness and mutates registry.

        This is intentionally a separate operation from read-only `status`.
        Status must never mutate state (per the readiness/status contract).
        """
        self.init_state()
        commander_failures: list[tuple[str, str]] = []
        commander_recoveries: list[tuple[str, str]] = []
        inaccessible_probes: list[tuple[str, str]] = []
        with self._registry_lock():
            registry = self._read_registry()
            for commander in registry.get("commanders", []):
                status = commander.get("status")
                session = str(commander.get("session", ""))
                # Monotonic terminal commanders are never resurrected by reconcile.
                if str(status) in TERMINAL_COMMANDER_STATUSES:
                    continue
                probe = self._tmux_probe_session(session) if session else {"state": "missing", "detail": "missing tmux session"}
                if status in ACTIVE_COMMANDER_STATUSES and session and probe["state"] == "missing":
                    commander["status"] = "failed"
                    commander["failure"] = "tmux session is not alive"
                    commander["updated"] = iso_now()
                    commander_failures.append((str(commander.get("id")), commander["failure"]))
                elif status in ACTIVE_COMMANDER_STATUSES and probe["state"] == "inaccessible":
                    inaccessible_probes.append((str(commander.get("id")), probe.get("detail", "")))
                elif status == "planned" and session and probe["state"] == "live":
                    commander["status"] = "commanding"
                    commander["updated"] = iso_now()
                    commander_recoveries.append((str(commander.get("id")), session))
            if commander_failures or commander_recoveries:
                self._write_registry(registry)
        for commander_id, failure in commander_failures:
            self._event("commander_failed", commander_id, {"failure": failure})
        for commander_id, session in commander_recoveries:
            self._event("commander_resumed", commander_id, {"session": session})
        for commander_id, detail in inaccessible_probes:
            self._event("tmux_probe_inaccessible", commander_id, {"detail": detail or "tmux probe inaccessible"})

        session_probes: dict[str, dict[str, str]] = {}
        for task in list(self._read_registry().get("tasks", [])):
            if task.get("status") not in {"launched", "running"}:
                continue
            window = str(task.get("window", ""))
            if not window:
                continue
            task_session = str(task.get("session") or self.context.session_name).strip()
            if not task_session:
                continue
            session_probe = session_probes.get(task_session)
            if session_probe is None:
                session_probe = self._tmux_probe_session(task_session)
                session_probes[task_session] = session_probe
            if session_probe["state"] == "inaccessible":
                self._event(
                    "tmux_probe_inaccessible",
                    str(task.get("id", "")),
                    {"detail": session_probe.get("detail", "") or "tmux session probe inaccessible"},
                )
                continue
            window_probe = self._tmux_probe_window(task_session, window) if session_probe["state"] == "live" else session_probe
            if window_probe["state"] == "inaccessible":
                self._event(
                    "tmux_probe_inaccessible",
                    str(task.get("id", "")),
                    {"detail": window_probe.get("detail", "") or "tmux window probe inaccessible"},
                )
                continue
            if window_probe["state"] == "missing":
                self._set_task_status(str(task["id"]), "failed", {"failure": "tmux window is not alive"})

    def render_prompt(self, spec: TaskSpec, commander: str) -> str:
        scope = "\n".join(f"- {item}" for item in spec.scope) if spec.scope else "- Decide from repository context."
        deps = "\n".join(f"- {item}" for item in spec.depends_on) if spec.depends_on else "- None."
        return f"""You are a mixed Legion worker.

Identity:
- Commander: {commander}
- Task ID: {spec.task_id}
- Provider: {spec.provider}
- Role: {spec.role}
- Project: {self.context.project_dir}

Mission:
{spec.task}

Scope:
{scope}

Dependencies:
{deps}

Operating rules:
1. Keep changes inside the declared scope unless the task is impossible without a narrow adjacent change.
2. Preserve user changes. Do not revert unrelated work.
3. For read-only roles, do not edit files.
4. For implementation roles, verify with the smallest relevant command before reporting success.
5. Report concrete files touched, commands run, and remaining risks.
6. Final output must be only one JSON object with keys: status, summary, files_touched, verification, findings, risks. status must be one of completed, blocked, failed. Do not finish with prose outside the JSON object.
"""

    def render_commander_prompt(self, commander_id: str, provider: str) -> str:
        legion_sh = Path(__file__).resolve().with_name("legion.sh")
        return f"""You are {commander_id}, a project L1 commander running on {provider}.

Mission:
- Coordinate this project through Legion Core. Own your provider's L2/team tree and coordinate with same-project peer L1s through durable inbox/events/results.
- External Hermes AICTO is the 总指挥部指挥链. Treat `AICTO-CTO` durable inbox messages as superior directives, and report terminal task state back to AICTO before waiting for user-visible follow-up.
- Same-project L1 peers are the 本地 L1 指挥链 for coordination only. Peer-sync/local inbox communication never substitutes for AICTO command-chain access.
- On launch/resume, Legion Core must receive a real external Hermes AICTO inbox-write result before this L1 counts as in the 总指挥部指挥链. Without that handshake, the registry marks the L1 `isolated` and it must not accept command-chain work.
- After AICTO command-chain connection, Legion Core sends local L1 peer notices and queues AICTO reports. Keep workers visible in tmux; do not create invisible background work.

Project:
- Path: {self.context.project_dir}
- Mixed registry: {self.registry_file}
- Event log: {self.events_file}
- AICTO report queue: {self.aicto_reports_file}
- Mixed inbox: {self.inbox_dir}
- AICTO command source: {AICTO_PLUGIN_ENTRYPOINT} -> mixed inbox / legacy inbox as `AICTO-CTO`

Core doctrine - scale-first Legion:
1. Optimize for maximum effective collaboration scale.
2. Resource cost is not a downgrade reason. Do not skip corps, recon, review, verify, audit, or parallel workers to save tokens/time/processes.
3. Default frontend topology is L1-only. Do not create base L2 commanders during startup unless Legion Core sends an explicit readiness-order.
4. S-level directives stay with the receiving L1 unless a visible tracked task is needed.
5. M+ work expands upward: use `mixed campaign --corps` with specialized visible L2 branches and independent workers.
6. Parallel branches need distinct scope, risk hypothesis, verification method, or specialty.
7. Keep quality gates independent: implementation, review, verify, and audit should be separated for non-trivial work.
8. Stop for the user only on irreversible destruction, unresolved requirement ambiguity, cross-project/shared-state changes, or a high-cost fork.
9. Use `claw-roundtable-skill` for explicit RoundTable/圆桌, XL work, or high-cost architecture/API/security decisions. Before claiming RoundTable ran, execute `.claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime`; if unavailable, report analysis-only and use campaign/recon as fallback.

Startup protocol - run before taking work:
1. Read only current protocol files that exist: `AGENTS.md`, `CLAUDE.md`, `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, `.planning/DECISIONS.md`.
2. List project/global skills, but read only task-relevant `SKILL.md` files.
3. Load only role-relevant tactics from `memory/tactics/INDEX.md` and `~/.claude/memory/tactics/INDEX.md`.
4. Run `{legion_sh} mixed status` and `{legion_sh} mixed inbox {commander_id}`; process peer/readiness messages.
5. Inspect `tail -40 {self.events_file}` for recent launches, failures, and orders.
6. Run RoundTable health only for explicit RoundTable/high-cost decisions.
7. If a readiness-order exists, wait with `{legion_sh} mixed readiness {commander_id} --wait --timeout 180`; normal dual-L1 startup has no base L2 readiness.
8. Reuse online L2 commanders when appropriate; only then create M+ campaigns or route tasks.

Essential commands:
- Status/inbox: `{legion_sh} mixed status`; `{legion_sh} mixed inbox {commander_id}`.
- Peer coordination: `{legion_sh} mixed msg <commander-id> "message" --from {commander_id}`.
- AICTO problem report: `{legion_sh} mixed report-aicto <subject> "summary" --from {commander_id} --kind problem`.
- AICTO next-step request: task terminal transitions automatically queue a report with `next_directive_request`; use `mixed report-aicto` only for non-task requests.
- Readiness only when ordered: `{legion_sh} mixed readiness {commander_id} --wait --timeout 180`.
- S visible task: `{legion_sh} mixed campaign plan.json --complexity s --direct`.
- M+ collaboration: `{legion_sh} mixed campaign plan.json --corps`; dry-run first for complex plans.
- More L1s: `{legion_sh} claude l1 <name>`; `{legion_sh} codex l1 <name>`.

Operating rules:
1. Use `legion.sh mixed campaign` for subordinate creation; keep S at L1 unless a tracked task window is needed.
2. For M+ work, use `--corps`, declare scope, separate implementation from review/verify/audit, and preserve user changes.
3. Prefer Codex for explore/review/verify/audit/security and Claude for implementation/product/UI unless explicitly overridden.
4. Verify before reporting completion. Automatic task transitions report to AICTO and request the next directive; use `mixed report-aicto` for non-task problems or manual next-step requests.
"""

    def render_aicto_prompt(self, commander_id: str) -> str:
        legion_sh = Path(__file__).resolve().with_name("legion.sh")
        return f"""You are {commander_id}, a local Legion Core L0 coordinator.

Mission:
- Coordinate this project's development legion runtime. The real AICTO is the external Hermes CTO project at `/Users/feijun/Documents/AICTO`, not this local process.
- Command two L1 armies: Claude L1 owns Claude branches, Codex L1 owns Codex branches.
- Keep S-level work at the receiving L1 by default; route M+ implementation, review, verify, audit, product, and UI work through the proper L1/L2 tree using Legion Core.
- Keep all workers visible in tmux. Do not create invisible background work outside Legion Core.

Project:
- Path: {self.context.project_dir}
- Mixed registry: {self.registry_file}
- Event log: {self.events_file}
- Mixed inbox: {self.inbox_dir}

Command doctrine:
1. L0 owns strategy, priority, risk gates, synthesis, and escalation.
2. Claude L1 and Codex L1 each manage their own provider's team tree; L2/team windows are created dynamically for M+ work.
3. Cross-provider coordination must use durable orders/results, registry state, inboxes, events, and explicit synthesis gates.
4. Use `mixed campaign --corps` for M+ work so specialized L2 branches handle delivery and independent quality gates.
5. Codex read-only branches are the default for explore/review/verify/audit/security; Claude branches are the default for implementation/product/UI unless a scoped Codex write task is explicit.
6. Resource cost is not a downgrade reason. Expand to maximum effective scale when work can be split by file scope, risk hypothesis, verification method, or specialty.
7. Stop for the user only on irreversible destruction, unresolved requirement ambiguity, cross-project/shared-state changes, or high-cost forks likely to cause major rework.

Startup protocol:
1. Read current protocol files: `AGENTS.md`, `CLAUDE.md`, `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, `.planning/DECISIONS.md`.
2. Inventory project/global skills from `.claude/skills`, `.agents/skills`, `skills`, and `~/.claude/skills`; read relevant `SKILL.md` files before use.
3. Load historical tactics from `memory/tactics/INDEX.md` and `~/.claude/memory/tactics/INDEX.md` if present.
4. Run `{legion_sh} mixed status`; identify live L1/L2 commanders, stale commanders, blocked tasks, and active quality gates.
5. Run `{legion_sh} mixed inbox {commander_id}` and process readiness orders before assigning work.
6. Inspect `tail -40 {self.events_file}` for launch failures, readiness orders, and recent task completions.
7. If `claw-roundtable-skill` exists, run its health check before claiming RoundTable runtime is available.
8. If a readiness-order message exists, send `INIT-READY-REQUEST` to every direct L1 listed in the order, then wait with the exact `mixed readiness {commander_id} --expect ... --wait --timeout 180` command from the order.
9. Do not tell the user the legion is initialized until both Claude L1 and Codex L1 have reported `READY:init-complete` for the current order.

Control commands:
```bash
{legion_sh} mixed status
{legion_sh} mixed inbox {commander_id}
{legion_sh} mixed msg <L1-id> "message" --from {commander_id}
{legion_sh} mixed readiness {commander_id}
{legion_sh} mixed readiness {commander_id} --wait --timeout 180
{legion_sh} mixed campaign plan.json --commander <L1-id> --corps
{legion_sh} mixed dual-host --no-attach
{legion_sh} mixed dual-host --no-attach
```

Operating rules:
1. Never bypass the L1/L2 hierarchy for M+ delivery work; S-level work may remain with L1.
2. Keep provider ownership clean: do not impersonate Claude from Codex or Codex from Claude.
3. Require independent review/verify/audit for non-trivial implementation.
4. Preserve user changes and declare file scope for every implementation task.
5. Before final synthesis, consume worker result artifacts, tests, review findings, audit findings, patrol/gate status, and retrospective signals.
"""

    def render_branch_commander_prompt(self, commander_id: str, branch: str, provider: str, parent: str) -> str:
        legion_sh = Path(__file__).resolve().with_name("legion.sh")
        return f"""You are {commander_id}, a {branch} branch commander running on {provider}.

Mission:
- Command the {branch} specialty under parent commander {parent}.
- Accept tasks routed to your branch through the unified Legion Core registry.
- Create subordinate workers only through Legion Core so Claude and Codex commanders remain synchronized.

Project:
- Path: {self.context.project_dir}
- Mixed registry: {self.registry_file}
- Event log: {self.events_file}
- Mixed inbox: {self.inbox_dir}

Core doctrine - scale-first Legion:
1. Your branch exists to maximize efficiency and quality through maximum effective specialty scale.
2. Resource cost is not a downgrade reason. Do not avoid subordinate workers, parallel checks, or independent verification to save tokens, time, processes, tmux panes, or model calls.
3. Expand within your specialty when work can be split by file scope, risk hypothesis, verification method, or sub-domain.
4. Do not create duplicate theater: every subordinate must have a distinct purpose and report independently useful information.
5. Preserve valuable branch context for follow-up iteration, failures, blocked work, or complex background. Release only context that is explicitly disposable.
6. If assigned a RoundTable/圆桌 discussion task, first run `.claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime` when the skill exists. Do not report RoundTable completion if expert runtime is unavailable; report the limitation and return analysis/expert matching only.

Lightweight activation protocol:
1. Identify yourself: commander id `{commander_id}`, branch `{branch}`, provider `{provider}`, parent `{parent}`.
2. Read your mixed inbox and the `TASK-ASSIGNED` activation message from {parent}/Legion Core before doing work.
3. Load only task-relevant context: the assigned task target, declared scope, dependencies, worker prompt/result path, and project files needed for that task.
4. Load only branch-relevant experience/tools: matching entries from `memory/tactics/INDEX.md` or `~/.claude/memory/tactics/INDEX.md`, and only the `SKILL.md` files that directly support the assigned task.
5. Do minimal pre-research needed to avoid blind execution: inspect target files, constraints, dependency outputs, and known failure modes related to your branch.
6. If assigned a RoundTable/圆桌 discussion task, run `.claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime` when available before claiming full RoundTable execution. Do not run RoundTable health for unrelated branches or routine execution tasks.
7. If you receive an `INIT-READY-REQUEST` from {parent} that carries an `order_id` and `nonce`, reply with `READY:init-complete` echoing the supplied `order_id` and `nonce` after the targeted activation checks above. Otherwise report concise task readiness/progress only when there is assigned work.

Control commands:
```bash
{legion_sh} mixed inbox {commander_id}
{legion_sh} mixed msg {parent} "message" --from {commander_id}
{legion_sh} mixed campaign plan.json --commander {commander_id}
{legion_sh} mixed campaign plan.json --commander {commander_id} --direct --complexity s
{legion_sh} mixed campaign plan.json --commander {commander_id} --dry-run
```

Campaign plan rule:
- Use `"provider": "claude"` for implementation/product/UI work.
- Use `"provider": "codex"` for explore/review/verify/audit work.
- Keep work within your {branch} branch unless the parent commander explicitly expands scope.

Operating rules:
1. You are not the top-level L1. Keep parent commander {parent} informed through concrete task status summaries.
2. Do not perform full L1 initialization, global status audits, or broad protocol scans unless the assigned task explicitly requires them.
3. Route work to same-specialty workers first.
4. For cross-specialty dependencies, create a separate campaign task with the correct provider and branch.
5. Require every implementation task to declare file scope.
6. Prefer broader independent validation over saving resources when the task is M+ within your specialty.
7. Before reporting completion, verify with the smallest relevant command.
"""

    def _adapter_launch_body(self, spec: TaskSpec, prompt_file: Path, result_file: Path) -> str:
        if spec.provider == "codex":
            return CodexAdapter(self.context).build_launch_body(spec, prompt_file, result_file, self.schema_file)
        if spec.provider == "claude":
            return ClaudeAdapter(self.context).build_launch_body(spec, prompt_file, result_file)
        raise SystemExit(f"{spec.task_id}: unsupported provider {spec.provider!r}")

    def _launch_script(self, spec: TaskSpec, commander: str, launch_body: str, log_file: Path) -> str:
        mark_running_cmd = self._mark_task_cmd(spec.task_id, "running")
        complete_cmd = self._complete_task_cmd(spec.task_id, self._run_dir(spec) / "result.md")
        return f"""#!/usr/bin/env bash
set -o pipefail
cd {shlex.quote(str(self.context.project_dir))}
export CLAUDE_CODE_TEAM_NAME={shlex.quote(self.context.team_name)}
export CLAUDE_CODE_AGENT_NAME={shlex.quote(spec.task_id)}
export CLAUDE_LEGION_TEAM_ID={shlex.quote(spec.task_id)}
export LEGION_TASK_ID={shlex.quote(spec.task_id)}
export LEGION_PARENT_COMMANDER={shlex.quote(commander)}
export LEGION_DIR={shlex.quote(str(self.legion_home / self.context.project_hash))}
echo "== Mixed Legion task {spec.task_id} ({spec.provider}/{spec.role}) =="
echo "Commander: {commander}"
echo "Log: {log_file}"
{mark_running_cmd}
(
{launch_body}
) 2>&1 | tee {shlex.quote(str(log_file))}
status=${{PIPESTATUS[0]}}
{complete_cmd} "$status"
exit "$status"
"""

    def _base_cli_cmd(self) -> str:
        parts = [
            shlex.quote(sys.executable),
            shlex.quote(str(Path(__file__).resolve())),
            "--project-dir",
            shlex.quote(str(self.context.project_dir)),
        ]
        if self.legion_home:
            parts.extend(["--legion-home", shlex.quote(str(self.legion_home))])
        return " ".join(parts)

    def _mark_task_cmd(self, task_id: str, status: str) -> str:
        return (
            f"{self._base_cli_cmd()} "
            f"mark {shlex.quote(task_id)} {shlex.quote(status)}"
        )

    def _complete_task_cmd(self, task_id: str, result_file: Path) -> str:
        return (
            f"{self._base_cli_cmd()} "
            f"complete {shlex.quote(task_id)} {shlex.quote(str(result_file))}"
        )

    def _codex_commander_launch_script(
        self,
        commander_id: str,
        prompt_file: Path,
        log_file: Path,
        display_label: str = "Codex commander",
        startup_message: str | None = None,
    ) -> str:
        mark_running = self._mark_commander_cmd(commander_id, "commanding")
        finish = self._commander_finish_cmd(commander_id)
        resolved_startup_message = startup_message or self._commander_startup_message(commander_id, "codex")
        startup_heredoc = self._startup_message_heredoc(resolved_startup_message)
        return f"""#!/usr/bin/env bash
set -o pipefail
cd {shlex.quote(str(self.context.project_dir))}
export CLAUDE_CODE_TEAM_NAME={shlex.quote(self.context.team_name)}
export CLAUDE_CODE_AGENT_NAME={shlex.quote(commander_id)}
export CLAUDE_LEGION_TEAM_ID={shlex.quote(commander_id)}
export LEGION_COMMANDER_ID={shlex.quote(commander_id)}
export LEGION_COMMANDER_SESSION={shlex.quote(f"legion-mixed-{self.context.project_hash}-{commander_id}")}
export LEGION_COMMANDER_RUN_DIR={shlex.quote(str(prompt_file.parent))}
export LEGION_DIR={shlex.quote(str(self.legion_home / self.context.project_hash))}
PROMPT=$(cat {shlex.quote(str(prompt_file))})
{startup_heredoc}
echo "== Mixed Legion {display_label} {commander_id} =="
echo "Project: {self.context.project_dir}"
echo "Log: interactive Codex output remains in this tmux pane to preserve TTY"
{mark_running}
printf '%s\n' "$STARTUP_MESSAGE"
CODEX_INITIAL_PROMPT=$(printf '%s\n\n%s\n' "$PROMPT" "$STARTUP_MESSAGE")
codex -C {shlex.quote(str(self.context.project_dir))} --dangerously-bypass-approvals-and-sandbox --no-alt-screen "$CODEX_INITIAL_PROMPT"
status=$?
{finish}
exit "$status"
"""

    def _claude_commander_launch_script(self, commander_id: str, prompt_file: Path, log_file: Path) -> str:
        mark_running = self._mark_commander_cmd(commander_id, "commanding")
        finish = self._commander_finish_cmd(commander_id)
        startup_message = self._commander_startup_message(commander_id, "claude")
        startup_heredoc = self._startup_message_heredoc(startup_message)
        return f"""#!/usr/bin/env bash
set -o pipefail
cd {shlex.quote(str(self.context.project_dir))}
export CLAUDE_CODE_TEAM_NAME={shlex.quote(self.context.team_name)}
export CLAUDE_CODE_AGENT_NAME={shlex.quote(commander_id)}
export CLAUDE_LEGION_TEAM_ID={shlex.quote(commander_id)}
export LEGION_COMMANDER_ID={shlex.quote(commander_id)}
export LEGION_COMMANDER_SESSION={shlex.quote(f"legion-mixed-{self.context.project_hash}-{commander_id}")}
export LEGION_COMMANDER_RUN_DIR={shlex.quote(str(prompt_file.parent))}
export LEGION_DIR={shlex.quote(str(self.legion_home / self.context.project_hash))}
PROMPT=$(cat {shlex.quote(str(prompt_file))})
{startup_heredoc}
echo "== Mixed Legion Claude commander {commander_id} =="
echo "Project: {self.context.project_dir}"
echo "Log: interactive Claude output remains in this tmux pane"
{mark_running}
printf '%s\n' "$STARTUP_MESSAGE"
claude --dangerously-skip-permissions --effort max --append-system-prompt "$PROMPT" "$STARTUP_MESSAGE"
status=$?
{finish}
exit "$status"
"""

    def _branch_commander_launch_script(self, commander_id: str, provider: str, prompt_file: Path, log_file: Path) -> str:
        startup_message = self._branch_commander_startup_message(commander_id, provider)
        if provider == "codex":
            return self._codex_commander_launch_script(
                commander_id,
                prompt_file,
                log_file,
                display_label="Codex branch commander",
                startup_message=startup_message,
            )
        mark_running = self._mark_commander_cmd(commander_id, "commanding")
        finish = self._commander_finish_cmd(commander_id)
        startup_heredoc = self._startup_message_heredoc(startup_message)
        return f"""#!/usr/bin/env bash
set -o pipefail
cd {shlex.quote(str(self.context.project_dir))}
export CLAUDE_CODE_TEAM_NAME={shlex.quote(self.context.team_name)}
export CLAUDE_CODE_AGENT_NAME={shlex.quote(commander_id)}
export CLAUDE_LEGION_TEAM_ID={shlex.quote(commander_id)}
export LEGION_COMMANDER_ID={shlex.quote(commander_id)}
export LEGION_COMMANDER_SESSION={shlex.quote(f"legion-mixed-{self.context.project_hash}-{commander_id}")}
export LEGION_COMMANDER_RUN_DIR={shlex.quote(str(prompt_file.parent))}
export LEGION_DIR={shlex.quote(str(self.legion_home / self.context.project_hash))}
PROMPT=$(cat {shlex.quote(str(prompt_file))})
{startup_heredoc}
echo "== Mixed Legion Claude branch commander {commander_id} =="
echo "Project: {self.context.project_dir}"
echo "Log: interactive Claude output remains in this tmux pane"
{mark_running}
printf '%s\n' "$STARTUP_MESSAGE"
claude --dangerously-skip-permissions --effort max --append-system-prompt "$PROMPT" "$STARTUP_MESSAGE"
status=$?
{finish}
exit "$status"
"""

    def _commander_startup_message(self, commander_id: str, provider: str = "") -> str:
        legion_sh = Path(__file__).resolve().with_name("legion.sh")
        provider_key = provider.strip().lower()
        if provider_key == "claude":
            provider_init = "Claude L1 军团初始化：接管实现 / 产品 / UI 方向；后续 M+ 任务用 Claude L2 分支，不冒充 Codex。"
        elif provider_key == "codex":
            provider_init = "Codex L1 军团初始化：接管侦察 / 审查 / 验证 / 审计方向；后续 M+ 任务用 Codex L2 分支，不冒充 Claude。"
        else:
            provider_init = "L1 军团初始化：确认 provider 与职责边界。"
        return f"""启动 L1 军团初始化（创建新 L1 时先执行，完成后再接任务）：
1. 确认身份 {commander_id} 和项目路径；这是 L1 指挥官初始化，不执行项目模板初始化，不复制 CLAUDE/agents/skills；全局/项目/记忆/技能/工具初始化只归 `legion 0`。
2. {provider_init}
3. 接入军团通讯：确认 mixed registry/events/inbox/aicto-reports 可读；AICTO 指挥链由 Legion Core 上线握手接入，失败即 isolated。
4. 只运行必要态势命令：`{legion_sh} mixed status`、`{legion_sh} mixed inbox {commander_id}`、`tail -20 {self.events_file}`。
5. 只处理 peer-online / peer-sync / readiness-order 等待办消息；同项目同级 L1 是本地指挥链，常规双 L1 启动没有基础 L2 readiness。
6. 只在当前任务需要时，再按需读取 AGENTS.md、CLAUDE.md、.planning 文件、tactics index 或相关 SKILL.md。
7. RoundTable/圆桌健康检查只在显式圆桌、高成本架构/API/安全决策时运行。
8. 输出一段极短启动汇总：身份、provider 职责、AICTO/本地通讯链、在线 peer、待处理消息、是否有 readiness-order、下一步。
"""

    def _branch_commander_startup_message(self, commander_id: str, provider: str) -> str:
        legion_sh = Path(__file__).resolve().with_name("legion.sh")
        return f"""L2 任务激活协议（轻量版，收到任务后再执行）：
1. 明确身份：你是 {commander_id}，provider={provider}，是父级 L1 为 M+ 任务创建的执行单位。
2. 先读收件箱：运行 {legion_sh} mixed inbox {commander_id}，找到 TASK-ASSIGNED / INIT-READY-REQUEST。
3. 只围绕目标任务初始化：确认任务目标、scope、依赖、完成标准、结果文件和需要监督的 worker。
4. 只加载相关上下文：读取与任务 scope / branch / provider 相关的项目文件、tactics、SKILL.md；不要执行 L1 的全量协议/全局态势/全武器库扫描。
5. 做必要预研：检查目标文件、依赖输出、已知风险和完成该任务所需工具；没有必要的信息再向父级 L1 请求。
6. 如果收到 INIT-READY-REQUEST，按其中 order_id/nonce 回 `READY:init-complete`；否则直接进入任务监督和最小必要验证。
"""

    def _startup_message_heredoc(self, startup_message: str) -> str:
        return "STARTUP_MESSAGE=$(cat <<'STARTUP_EOF'\n" + startup_message + "\nSTARTUP_EOF\n)"

    def _mark_commander_cmd(self, commander_id: str, status: str) -> str:
        return (
            f"{self._base_cli_cmd()} "
            f"mark-commander {shlex.quote(commander_id)} {shlex.quote(status)}"
        )

    def _commander_finish_cmd(self, commander_id: str) -> str:
        completed = self._mark_commander_cmd(commander_id, "completed")
        failed = self._mark_commander_cmd(commander_id, "failed")
        return f"""if [ "$status" -eq 0 ]; then
  {completed}
else
  {failed}
fi"""

    def _run_dir(self, spec: TaskSpec) -> Path:
        return self.state_dir / "runs" / spec.task_id

    def _project_record(self) -> dict[str, Any]:
        return {
            "name": self.context.project_name,
            "hash": self.context.project_hash,
            "path": str(self.context.project_dir),
            "session": self.context.session_name,
            "aicto_control": self._aicto_control_contract(),
        }

    def _aicto_control_contract(self, commander_id: str = "") -> dict[str, Any]:
        return {
            "control_plane": AICTO_CONTROL_PLANE_ID,
            "authority": "project-l1-command",
            "directive_sender": AICTO_DIRECTIVE_SENDER,
            "directive_entrypoint": AICTO_PLUGIN_ENTRYPOINT,
            "directive_channels": ["mixed-inbox", "legacy-inbox"],
            "report_outbox": str(self.aicto_reports_file),
            "project_hash": self.context.project_hash,
            "project_path": str(self.context.project_dir),
            "commander_id": commander_id,
            "next_directive_required_on_terminal_task": True,
            "requires_actual_external_handshake": True,
            "isolated_status_without_handshake": ISOLATED_COMMANDER_STATUS,
        }

    def _read_registry(self) -> dict[str, Any]:
        try:
            return json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"project": self._project_record(), "commanders": [], "tasks": []}

    def _write_registry(self, registry: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._registry_tmp_path()
        tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.registry_file)

    def _registry_tmp_path(self) -> Path:
        return self.registry_file.with_name(
            f"{self.registry_file.name}.{os.getpid()}.{time.time_ns()}.{random.randint(1000, 9999)}.tmp"
        )

    def _registry_lock_path(self) -> Path:
        return self.state_dir / ".registry.lock"

    @contextlib.contextmanager
    def _registry_lock(self):
        """Reentrant exclusive lock guarding registry read-modify-write."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self._registry_lock_depth > 0:
            self._registry_lock_depth += 1
            try:
                yield
            finally:
                self._registry_lock_depth -= 1
            return
        fh = self._registry_lock_path().open("a")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        self._registry_lock_fh = fh
        self._registry_lock_depth = 1
        try:
            yield
        finally:
            self._registry_lock_depth = 0
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()
                self._registry_lock_fh = None

    @contextlib.contextmanager
    def _file_append_lock(self, path: Path):
        """Exclusive append lock for inbox/event log lines so concurrent writers
        cannot interleave bytes in a single JSONL entry."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_suffix(path.suffix + ".lock")
        fh = lock_path.open("a")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

    def _upsert_task(self, entry: dict[str, Any]) -> None:
        with self._registry_lock():
            registry = self._read_registry()
            tasks = registry.setdefault("tasks", [])
            for idx, existing in enumerate(tasks):
                if existing.get("id") == entry["id"]:
                    merged = dict(existing)
                    merged.update(entry)
                    tasks[idx] = merged
                    break
            else:
                tasks.append(entry)
            registry["project"] = self._project_record()
            self._write_registry(registry)

    def _upsert_commander(self, entry: dict[str, Any]) -> None:
        prepared = dict(entry)
        if prepared.get("role") == "commander" and self._entry_level(prepared) == 1:
            prepared["aicto_authority"] = self._aicto_control_contract(str(prepared.get("id", "")))
        with self._registry_lock():
            registry = self._read_registry()
            commanders = registry.setdefault("commanders", [])
            for idx, existing in enumerate(commanders):
                if existing.get("id") == prepared["id"]:
                    merged = dict(existing)
                    merged.update(prepared)
                    commanders[idx] = merged
                    break
            else:
                commanders.append(prepared)
            registry.setdefault("tasks", [])
            registry["project"] = self._project_record()
            self._write_registry(registry)

    def _commander_entry(self, commander_id: str) -> dict[str, Any] | None:
        for commander in self._read_registry().get("commanders", []):
            if commander.get("id") == commander_id:
                return dict(commander)
        return None

    def _inbox_file(self, target: str) -> Path:
        return self.inbox_dir / f"{normalize_task_id(target)}.jsonl"

    def _append_inbox(self, target: str, record: dict[str, Any]) -> bool:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        inbox_file = self._inbox_file(target)
        with self._file_append_lock(inbox_file):
            record_id = str(record.get("id", ""))
            if record_id and inbox_file.exists():
                for line in inbox_file.read_text(encoding="utf-8").splitlines():
                    try:
                        existing = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(existing.get("id", "")) == record_id:
                        return False
            with inbox_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True

    def _queue_aicto_report(
        self,
        kind: str,
        subject_id: str,
        summary: str,
        source: str = "Legion Core",
        payload: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        timestamp = iso_now()
        correlation = correlation_id.strip() or self._new_correlation_id(f"aicto:{kind}:{subject_id}")
        report_payload = dict(payload or {})
        report_payload.setdefault("project", self._project_record())
        source_id = str(source or "").strip()
        report_payload.setdefault("aicto_authority", self._aicto_control_contract(source_id))
        report_payload.setdefault(
            "communication_chain",
            {
                "direction": "legion-to-aicto",
                "outbox": str(self.aicto_reports_file),
                "control_plane": AICTO_CONTROL_PLANE_ID,
                "directive_sender": AICTO_DIRECTIVE_SENDER,
            },
        )
        material = json.dumps(
            {
                "timestamp": timestamp,
                "kind": kind,
                "subject_id": subject_id,
                "source": source,
                "summary": summary,
                "correlation_id": correlation,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        report_id = f"aicto-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"
        record = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "id": report_id,
            "type": "aicto-report",
            "timestamp": timestamp,
            "ts": timestamp,
            "correlation_id": correlation,
            "kind": kind,
            "subject_id": subject_id,
            "source": source,
            "summary": summary,
            "payload": report_payload,
        }
        with self._file_append_lock(self.aicto_reports_file):
            with self.aicto_reports_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._event(
            "aicto_report_queued",
            subject_id,
            {"report_id": report_id, "kind": kind, "source": source, "summary": summary},
            correlation_id=correlation,
        )
        return record

    def _report_task_to_aicto(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("id", ""))
        status = str(task.get("status", ""))
        if status == "completed":
            kind = "task-completed"
        elif status == "failed":
            kind = "task-failed"
        else:
            kind = "task-problem"
        detail = (
            str(task.get("result_summary", "")).strip()
            or str(task.get("failure", "")).strip()
            or str(task.get("blocked_reason", "")).strip()
            or str(task.get("task", "")).strip()
        )
        if len(detail) > 240:
            detail = detail[:237] + "..."
        source = str(task.get("origin_commander") or task.get("commander") or "Legion Core")
        request_type = "next-task" if status == "completed" else "remediation"
        request_summary = (
            "requesting next AICTO directive"
            if status == "completed"
            else "requesting AICTO remediation directive"
        )
        summary = f"{task_id} {status}: {detail or '(no detail)'} | {request_summary}"
        next_directive = {
            "required": True,
            "request_type": request_type,
            "requested_from": AICTO_DIRECTIVE_SENDER,
            "requested_by": source,
            "reason": "task-terminal-state",
            "status": status,
            "subject_id": task_id,
            "authority": "external Hermes AICTO holds project L1 command authority",
        }
        record = self._queue_aicto_report(
            kind=kind,
            subject_id=task_id,
            summary=summary,
            source=source,
            payload={
                "task_id": task_id,
                "status": status,
                "role": task.get("role", ""),
                "provider": task.get("provider", ""),
                "branch": task.get("branch", ""),
                "commander": task.get("commander", ""),
                "origin_commander": task.get("origin_commander", ""),
                "scope": task.get("scope", []),
                "depends_on": task.get("depends_on", []),
                "result_file": task.get("result_file", ""),
                "result_summary": task.get("result_summary", ""),
                "failure": task.get("failure", ""),
                "blocked_reason": task.get("blocked_reason", ""),
                "next_directive_request": next_directive,
            },
        )
        self._event(
            "aicto_next_directive_requested",
            task_id,
            {
                "report_id": record["id"],
                "request_type": request_type,
                "requested_from": AICTO_DIRECTIVE_SENDER,
                "requested_by": source,
            },
            correlation_id=str(record.get("correlation_id", "")),
        )
        return record

    def _parse_control_fields(self, content: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for raw_token in content.replace("\n", " ").split():
            if "=" not in raw_token:
                continue
            key, value = raw_token.split("=", 1)
            key = key.strip().strip(":,;")
            value = value.strip().strip(",:;")
            if key and value:
                fields[key] = value
        return fields

    def _record_control_fields(self, record: dict[str, Any]) -> dict[str, str]:
        control = record.get("control")
        if isinstance(control, dict):
            return {str(key): str(value) for key, value in control.items()}
        return self._parse_control_fields(str(record.get("content", "")))

    def _record_sender_verified(self, record: dict[str, Any]) -> bool:
        if bool(record.get("sender_verified")):
            return True
        auth = record.get("sender_auth")
        return isinstance(auth, dict) and bool(auth.get("verified"))

    def _sender_authentication(self, sender_id: str) -> dict[str, Any]:
        if sender_id == "Legion Core":
            return {"verified": True, "method": "system"}
        commander = self._commander_entry(sender_id)
        if not commander:
            return {"verified": False, "reason": "sender-not-registered"}

        env_ids = [
            os.environ.get("LEGION_COMMANDER_ID", "").strip(),
            os.environ.get("CLAUDE_CODE_AGENT_NAME", "").strip(),
            os.environ.get("CLAUDE_LEGION_TEAM_ID", "").strip(),
        ]
        if sender_id not in {value for value in env_ids if value}:
            return {"verified": False, "reason": "execution-context-mismatch"}

        expected_session = str(commander.get("session", "")).strip()
        env_session = os.environ.get("LEGION_COMMANDER_SESSION", "").strip()
        if expected_session:
            if not env_session:
                return {"verified": False, "reason": "session-binding-missing"}
            if env_session != expected_session:
                return {"verified": False, "reason": "session-binding-mismatch"}

        expected_run_dir = str(commander.get("run_dir", "")).strip()
        env_run_dir = os.environ.get("LEGION_COMMANDER_RUN_DIR", "").strip()
        if expected_run_dir:
            if not env_run_dir:
                return {"verified": False, "reason": "run-dir-binding-missing"}
            if Path(env_run_dir).expanduser().resolve(strict=False) != Path(expected_run_dir).expanduser().resolve(strict=False):
                return {"verified": False, "reason": "run-dir-binding-mismatch"}

        return {"verified": True, "method": "commander-execution-context"}

    def _new_correlation_id(self, seed: str = "") -> str:
        material = f"{seed}:{time.time_ns()}:{random.randint(1000, 9999)}"
        return f"corr-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"

    def _stable_message_id(
        self,
        dedupe_key: str,
        sender_id: str,
        target_id: str,
        content: str,
        message_type: str,
        correlation_id: str,
    ) -> str:
        material = "\0".join([dedupe_key, sender_id, target_id, message_type, correlation_id, content])
        return f"msg-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"

    def _deliver_tmux_message(self, commander: dict[str, Any], record: dict[str, Any]) -> bool:
        session = str(commander.get("session", ""))
        if not session or not self._tmux_has_session(session):
            return False
        if not self._should_inject_tmux_message(commander, record):
            return self._notify_tmux_message(session, record)
        code, _, _ = self.runner.run(["tmux", "send-keys", "-t", session, self._tmux_message_text(record), "Enter"])
        return code == 0

    def _tmux_pane_is_idle(self, session: str) -> bool:
        code, stdout, _ = self.runner.run(["tmux", "capture-pane", "-t", session, "-p"])
        if code != 0:
            return False
        lines = [l for l in (stdout or "").splitlines() if l.strip()]
        return any("❯" in line for line in lines[-5:])

    def _should_inject_tmux_message(self, commander: dict[str, Any], record: dict[str, Any]) -> bool:
        # Keep interactive commanders' prompts clean. Messages are durable in inbox;
        # tmux only gets a non-invasive notification so long reports or broadcasts
        # do not remain as unsent composer text.
        if commander.get("role") in {"aicto", "commander", "branch-commander"}:
            return False
        if record.get("type") in {"readiness", "readiness-order", "disband"}:
            return False
        return True

    def _notify_tmux_message(self, session: str, record: dict[str, Any]) -> bool:
        notice = (
            f"Legion inbox: {record.get('from', '?')} -> {record.get('to', '?')} "
            f"{record.get('type', 'message')}"
        )
        code, _, _ = self.runner.run(["tmux", "display-message", "-t", session, notice])
        return code == 0

    def _tmux_message_text(self, record: dict[str, Any]) -> str:
        return f"[Legion mixed {record.get('type','message')}] {record.get('from','?')}: {record.get('content','')}"

    def _connect_aicto_command_chain(
        self,
        commander: dict[str, Any],
        action: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        result = self._send_external_aicto_handshake(commander, action, correlation_id)
        if not isinstance(result, dict):
            raise RuntimeError("external Hermes AICTO returned a non-dict handshake result")

        missing: list[str] = []
        if not result.get("message_id"):
            missing.append("message_id")
        if result.get("mixed_inbox_written") is not True:
            missing.append("mixed_inbox_written")
        if result.get("legacy_inbox_written") is not True:
            missing.append("legacy_inbox_written")
        if missing:
            raise RuntimeError(f"AICTO handshake incomplete: missing {', '.join(missing)}")

        return {
            "status": "connected",
            "actual_communication": True,
            "connected_at": iso_now(),
            "control_plane": AICTO_CONTROL_PLANE_ID,
            "directive_sender": AICTO_DIRECTIVE_SENDER,
            "plugin_entrypoint": AICTO_PLUGIN_ENTRYPOINT,
            "message_id": result.get("message_id"),
            "mixed_inbox_written": result.get("mixed_inbox_written"),
            "legacy_inbox_written": result.get("legacy_inbox_written"),
            "inbox_path": result.get("inbox_path"),
            "mixed_inbox_path": result.get("mixed_inbox_path"),
            "legacy_inbox_path": result.get("legacy_inbox_path"),
            "tmux_notified": result.get("tmux_notified"),
        }

    def _send_external_aicto_handshake(
        self,
        commander: dict[str, Any],
        action: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        sender = self._external_aicto_sender()
        commander_id = str(commander.get("id", "")).strip()
        if not commander_id:
            raise RuntimeError("missing L1 commander id for AICTO handshake")
        payload = (
            f"AICTO-L1-HANDSHAKE action={action} commander={commander_id} "
            f"project={self.context.project_dir} correlation_id={correlation_id}. "
            "You are now connected to the external Hermes AICTO command chain. "
            "Report terminal task state to AICTO and request the next directive."
        )
        return sender(
            commander_id,
            payload,
            msg_type="task",
            summary=f"L1 command-chain handshake for {commander_id}",
            cto_context={
                "kind": "l1-command-chain-handshake",
                "required": True,
                "action": action,
                "correlation_id": correlation_id,
                "commander_id": commander_id,
                "project_hash": self.context.project_hash,
                "project_path": str(self.context.project_dir),
                "authority": "external Hermes AICTO holds project L1 command authority",
            },
            priority="high",
            legion_hash=self.context.project_hash,
        )

    def _external_aicto_sender(self) -> Any:
        if "::" not in AICTO_PLUGIN_ENTRYPOINT:
            raise RuntimeError(f"invalid AICTO plugin entrypoint: {AICTO_PLUGIN_ENTRYPOINT}")
        path_text, function_name = AICTO_PLUGIN_ENTRYPOINT.split("::", 1)
        plugin_path = Path(path_text).expanduser()
        if not plugin_path.exists():
            raise RuntimeError(f"external Hermes AICTO plugin not found: {plugin_path}")
        module_name = f"external_hermes_aicto_{hashlib.sha256(str(plugin_path).encode('utf-8')).hexdigest()[:12]}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load external Hermes AICTO plugin: {plugin_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if hasattr(module, "LEGION_ROOT"):
            module.LEGION_ROOT = self.legion_home
        if hasattr(module, "LEGION_DIRECTORY"):
            module.LEGION_DIRECTORY = self.legion_home / "directory.json"
        sender = getattr(module, function_name, None)
        if not callable(sender):
            raise RuntimeError(f"AICTO plugin function is not callable: {AICTO_PLUGIN_ENTRYPOINT}")
        return sender

    def _mark_commander_isolated_from_aicto(
        self,
        commander: dict[str, Any],
        action: str,
        correlation_id: str,
        failure: Exception,
    ) -> dict[str, Any]:
        commander_id = str(commander.get("id", "")).strip() or "unknown"
        failure_text = str(failure) or failure.__class__.__name__
        isolated = dict(commander)
        isolated["status"] = ISOLATED_COMMANDER_STATUS
        isolated["aicto_link"] = {
            "status": ISOLATED_COMMANDER_STATUS,
            "actual_communication": False,
            "failure": failure_text,
            "action": action,
            "control_plane": AICTO_CONTROL_PLANE_ID,
            "directive_sender": AICTO_DIRECTIVE_SENDER,
            "plugin_entrypoint": AICTO_PLUGIN_ENTRYPOINT,
            "isolated_at": iso_now(),
        }
        isolated["local_l1_link"] = {
            "status": "not-established",
            "actual_communication": False,
            "reason": "aicto-command-chain-required-first",
            "scope": "same-project-l1",
        }
        isolated["command_chains"] = {
            "aicto": isolated["aicto_link"],
            "local_l1": isolated["local_l1_link"],
        }
        isolated["aicto_failure"] = failure_text
        isolated["updated"] = iso_now()
        self._upsert_commander(isolated)
        self._event(
            "aicto_command_chain_failed",
            commander_id,
            {"action": action, "failure": failure_text, "status": ISOLATED_COMMANDER_STATUS},
            correlation_id=correlation_id,
        )
        return isolated

    def _announce_l1_online(self, commander: dict[str, Any], action: str) -> dict[str, Any]:
        if commander.get("role") != "commander" or self._entry_level(commander) != 1:
            return commander
        commander_id = str(commander.get("id", "")).strip()
        if not commander_id:
            return commander
        correlation = self._new_correlation_id(f"l1-online:{commander_id}:{action}")
        try:
            aicto_link = self._connect_aicto_command_chain(commander, action, correlation)
        except Exception as exc:  # noqa: BLE001 - failure becomes an explicit isolated commander state.
            return self._mark_commander_isolated_from_aicto(commander, action, correlation, exc)

        connected = dict(commander)
        connected["status"] = "commanding"
        connected["aicto_link"] = aicto_link
        connected["command_chains"] = {
            "aicto": aicto_link,
            "local_l1": {
                "status": "pending-peer-sync",
                "actual_communication": False,
                "scope": "same-project-l1",
            },
        }
        connected["updated"] = iso_now()
        self._upsert_commander(connected)

        peers = self._active_same_project_l1_peers(commander_id)
        content = (
            f"L1-ONLINE action={action} commander={commander_id} "
            f"provider={connected.get('provider', '?')} project={self.context.project_dir}. "
            "I am online for same-project L1 coordination; S work stays with L1, "
            "M+ work expands via `mixed campaign --corps`; external Hermes AICTO keeps "
            "project L1 command authority through durable inbox directives and report outbox."
        )
        delivered_peer_ids: list[str] = []
        for peer in peers:
            peer_id = str(peer.get("id", ""))
            if not peer_id:
                continue
            self.send_message(
                peer_id,
                content,
                sender=commander_id,
                message_type="peer-online",
                correlation_id=correlation,
            )
            delivered_peer_ids.append(peer_id)
        local_l1_link = {
            "status": "connected" if delivered_peer_ids else "no-peer-l1",
            "actual_communication": bool(delivered_peer_ids),
            "scope": "same-project-l1",
            "peer_l1": delivered_peer_ids,
            "authority": "local coordination only; cannot substitute for AICTO command chain",
            "updated": iso_now(),
        }
        connected["local_l1_link"] = local_l1_link
        connected["command_chains"] = {
            "aicto": aicto_link,
            "local_l1": local_l1_link,
        }
        connected["updated"] = iso_now()
        self._upsert_commander(connected)
        report = self._queue_aicto_report(
            kind="l1-online",
            subject_id=commander_id,
            summary=f"{commander_id} is online ({action}) for project {self.context.project_name}",
            source=commander_id,
            payload={
                "action": action,
                "provider": connected.get("provider", ""),
                "session": connected.get("session", ""),
                "peer_l1": delivered_peer_ids,
                "aicto_authority": self._aicto_control_contract(commander_id),
                "aicto_link": aicto_link,
                "local_l1_link": local_l1_link,
                "command_chains": connected["command_chains"],
                "awaiting_directives_from": AICTO_DIRECTIVE_SENDER,
            },
            correlation_id=correlation,
        )
        self._event(
            "l1_online_announced",
            commander_id,
            {"action": action, "peer_l1": delivered_peer_ids, "aicto_report": report["id"]},
            correlation_id=correlation,
        )
        return connected

    def _active_same_project_l1_peers(self, commander_id: str) -> list[dict[str, Any]]:
        peers: list[dict[str, Any]] = []
        for commander in self._read_registry().get("commanders", []):
            if str(commander.get("id", "")) == commander_id:
                continue
            if commander.get("role") != "commander" or self._entry_level(commander) != 1:
                continue
            if str(commander.get("status", "")) not in ACTIVE_COMMANDER_STATUSES:
                continue
            if not self._commander_project_matches(commander):
                continue
            if not self._commander_has_live_session(commander):
                continue
            peers.append(dict(commander))
        return peers

    def _send_dual_l1_peer_sync(
        self,
        claude_l1: dict[str, Any],
        codex_l1: dict[str, Any],
        delay_seconds: float = 1.0,
    ) -> None:
        delay = max(float(delay_seconds), 0.0)
        if delay:
            time.sleep(delay)
        claude_id = str(claude_l1["id"])
        codex_id = str(codex_l1["id"])
        correlation = self._new_correlation_id("dual-l1-peer-sync")
        shared_body = (
            "PEER-SYNC delay=1s: dual L1 cooperation is online. "
            "Default topology is L1-only; S-level directives stay with the receiving L1, "
            "and M+ work creates visible L2/team tmux windows through `mixed campaign --corps`. "
            "Coordinate through durable inbox/events/results and do not impersonate the peer provider."
        )
        codex_record = self.send_message(
            codex_id,
            f"{shared_body} Claude peer={claude_id}; Codex peer={codex_id}.",
            sender=claude_id,
            message_type="peer-sync",
            correlation_id=correlation,
        )
        claude_record = self.send_message(
            claude_id,
            f"{shared_body} Codex peer={codex_id}; Claude peer={claude_id}.",
            sender=codex_id,
            message_type="peer-sync",
            correlation_id=correlation,
        )
        self._event(
            "dual_l1_peer_sync_sent",
            "dual-l1",
            {
                "claude_l1": claude_id,
                "codex_l1": codex_id,
                "delay_seconds": delay,
                "messages": [codex_record["id"], claude_record["id"]],
            },
            correlation_id=correlation,
        )

    def _send_host_readiness_order(self, host: dict[str, Any], l2_commanders: list[dict[str, Any]]) -> None:
        host_id = str(host["id"])
        child_label = self._readiness_child_label(host_id, host)
        expected = [str(commander["id"]) for commander in l2_commanders]
        legion_sh = Path(__file__).resolve().with_name("legion.sh")
        roster = "\n".join(
            f"- {commander['id']} ({commander.get('provider', '?')}/{commander.get('branch', '?')})"
            for commander in l2_commanders
        )
        order = self._issue_readiness_order(host_id, expected)
        order_id = order["order_id"]
        nonce = order["nonce"]
        readiness_cmd = (
            f"{shlex.quote(str(legion_sh))} mixed readiness {shlex.quote(host_id)} "
            f"--expect {shlex.quote(','.join(expected))} --wait --timeout 180"
        )
        message = f"""Legion Core readiness order:
order_id={order_id}
nonce={nonce}
issued_at={order['issued_at']}
直属 {child_label} roster:
{roster}

你完成自身启动自检后必须执行启动握手：
1. 向直属 {child_label} 下发初始化就绪请求 (必须把 order_id/nonce 原样转发，让回报里回执相同的 order_id/nonce)：
   {self._readiness_request_command(host_id, l2_commanders, child_label, order_id, nonce)}
2. 等待全部直属 {child_label} 回报。用以下命令检查，不要把其他父级或历史 commander 算入本次 roster：
   {readiness_cmd}
3. 只有 readiness 显示 Ready: {len(expected)}/{len(expected)} 且 Missing: (none) 后，才向上级/用户汇报：军团体系展开初始化完成，可以开始任务/继续任务。
"""
        self.send_message(host_id, message, sender="Legion Core", message_type="readiness-order")
        self._event(
            "host_readiness_order_sent",
            host_id,
            {
                "expected": expected,
                "expected_l2": expected if child_label == "L2" else [],
                "expected_l1": expected if child_label == "L1" else [],
                "child_label": child_label,
                "order_id": order_id,
                "nonce": nonce,
                "issued_at": order["issued_at"],
            },
        )

    def _readiness_request_command(
        self,
        parent_id: str,
        children: list[dict[str, Any]],
        child_label: str,
        order_id: str,
        nonce: str,
    ) -> str:
        legion_sh = Path(__file__).resolve().with_name("legion.sh")
        if child_label == "L2":
            base_message = (
                f"INIT-READY-REQUEST order_id={order_id} nonce={nonce}: "
                f"完成轻量任务激活检查后，用 READY:init-complete order_id={order_id} nonce={nonce} "
                f"向 {parent_id} 汇报。汇报只需包含身份/branch/provider、目标任务、scope/依赖、相关技能工具、必要预研和当前阻塞。"
            )
        else:
            base_message = (
                f"INIT-READY-REQUEST order_id={order_id} nonce={nonce}: "
                f"完成各自启动自检后，用 READY:init-complete order_id={order_id} nonce={nonce} "
                f"向 {parent_id} 汇报。汇报必须包含协议/武器库/历史战法/圆桌健康/态势/收件箱摘要。"
            )
        legion_cmd = shlex.quote(str(legion_sh))
        parent_arg = shlex.quote(parent_id)
        message_arg = shlex.quote(base_message)
        if child_label == "L2":
            return (
                f"{legion_cmd} mixed broadcast {message_arg} "
                f"--from {parent_arg} --l2-only --parent {parent_arg}"
            )
        if not children:
            return f"# no direct {child_label} commanders registered"
        commands = [
            f"{legion_cmd} mixed msg {shlex.quote(str(commander['id']))} {message_arg} --from {parent_arg}"
            for commander in children
        ]
        return "\n   ".join(commands)

    def _issue_readiness_order(self, parent_id: str, expected: list[str]) -> dict[str, Any]:
        """Persist a fresh readiness order for parent_id; supersedes any prior order."""
        order = {
            "order_id": f"ord-{time.time_ns()}-{random.randint(1000, 9999)}",
            "nonce": f"n{random.getrandbits(64):016x}",
            "issued_at": iso_now(),
            "issued_at_ns": time.time_ns(),
            "expected": list(expected),
            "parent": parent_id,
        }
        with self._registry_lock():
            registry = self._read_registry()
            orders = registry.setdefault("readiness_orders", {})
            orders[parent_id] = order
            self._write_registry(registry)
        return order

    def _clear_readiness_orders(self, parent_ids: list[str], reason: str = "") -> list[str]:
        parents = [str(item).strip() for item in parent_ids if str(item).strip()]
        if not parents:
            return []
        removed: list[tuple[str, dict[str, Any]]] = []
        with self._registry_lock():
            registry = self._read_registry()
            orders = registry.get("readiness_orders")
            if not isinstance(orders, dict):
                return []
            for parent_id in parents:
                order = orders.pop(parent_id, None)
                if isinstance(order, dict):
                    removed.append((parent_id, dict(order)))
            if removed:
                if orders:
                    registry["readiness_orders"] = orders
                else:
                    registry.pop("readiness_orders", None)
                self._write_registry(registry)
        for parent_id, order in removed:
            self._event(
                "readiness_order_cleared",
                parent_id,
                {
                    "reason": reason or "cleared",
                    "order_id": order.get("order_id", ""),
                    "expected": order.get("expected", []),
                },
            )
        return [parent_id for parent_id, _order in removed]

    def _current_readiness_order(self, parent_id: str) -> dict[str, Any] | None:
        registry = self._read_registry()
        orders = registry.get("readiness_orders") or {}
        order = orders.get(parent_id)
        if not isinstance(order, dict):
            return None
        return dict(order)

    def _active_direct_l2(self, parent: str) -> list[dict[str, Any]]:
        commanders = []
        for commander in self._read_registry().get("commanders", []):
            if commander.get("role") != "branch-commander":
                continue
            if commander.get("parent") != parent:
                continue
            if commander.get("status") not in {"launching", "commanding"}:
                continue
            if not self._commander_project_matches(commander):
                continue
            if not self._commander_has_live_session(commander):
                continue
            commanders.append(dict(commander))
        return commanders

    def _active_direct_l1(self, parent: str) -> list[dict[str, Any]]:
        commanders = []
        for commander in self._read_registry().get("commanders", []):
            if commander.get("role") != "commander":
                continue
            if commander.get("parent") != parent:
                continue
            if commander.get("status") not in {"launching", "commanding"}:
                continue
            if self._entry_level(commander, 1) != 1:
                continue
            if not self._commander_project_matches(commander):
                continue
            if not self._commander_has_live_session(commander):
                continue
            commanders.append(dict(commander))
        return commanders

    def _active_readiness_children(self, parent: str) -> list[dict[str, Any]]:
        label = self._readiness_child_label(parent)
        if label == "L1":
            return self._active_direct_l1(parent)
        return self._active_direct_l2(parent)

    def _readiness_child_label(self, parent: str, parent_entry: dict[str, Any] | None = None) -> str:
        entry = parent_entry if parent_entry is not None else self._commander_entry(parent)
        if entry and (entry.get("role") == "aicto" or self._entry_level(entry) == 0):
            return "L1"
        if parent.startswith("L0-"):
            return "L1"
        return "L2"

    def _view_l2_entries(self, host_id: str) -> list[dict[str, Any]]:
        registry = self._read_registry()
        commanders = [dict(item) for item in registry.get("commanders", [])]
        tasks = [dict(item) for item in registry.get("tasks", [])]
        by_id = {str(item.get("id", "")): item for item in commanders if item.get("id")}
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()

        def add_if_live(commander: dict[str, Any]) -> None:
            commander_id = str(commander.get("id", ""))
            if not commander_id or commander_id in selected_ids:
                return
            if not self._commander_project_matches(commander):
                return
            if not self._commander_has_live_session(commander):
                return
            selected.append(dict(commander))
            selected_ids.add(commander_id)

        for commander in self._active_direct_l2(host_id):
            if self._is_base_l2(commander):
                add_if_live(commander)

        for commander in commanders:
            if commander.get("role") != "branch-commander":
                continue
            if commander.get("status") not in {"launching", "commanding"}:
                continue
            if not self._commander_is_in_host_tree(commander, host_id, by_id):
                continue
            if not self._commander_has_active_task(str(commander.get("id", "")), tasks):
                continue
            add_if_live(commander)

        return selected

    def _is_base_l2(self, commander: dict[str, Any]) -> bool:
        return str(commander.get("lifecycle", "")).strip().lower() == "host"

    def _commander_has_active_task(self, commander_id: str, tasks: list[dict[str, Any]]) -> bool:
        if not commander_id:
            return False
        for task in tasks:
            if task.get("commander") != commander_id:
                continue
            if str(task.get("status", "")) not in TERMINAL_TASK_STATUSES:
                return True
        return False

    def _commander_is_in_host_tree(
        self,
        commander: dict[str, Any],
        host_id: str,
        commanders_by_id: dict[str, dict[str, Any]],
    ) -> bool:
        parent = str(commander.get("parent", ""))
        seen: set[str] = set()
        while parent:
            if parent == host_id:
                return True
            if parent in seen:
                return False
            seen.add(parent)
            parent_commander = commanders_by_id.get(parent)
            if not parent_commander:
                return False
            parent = str(parent_commander.get("parent", ""))
        return False

    def _is_readiness_record(self, record: dict[str, Any]) -> bool:
        if record.get("type") == "readiness":
            return True
        content = str(record.get("content", ""))
        return "READY:init-complete" in content or "INIT_READY" in content

    def _spec_retains_context(self, spec: TaskSpec) -> bool:
        raw = spec.raw
        if str(raw.get("context_policy", "")).strip().lower() in {"retain", "keep", "preserve"}:
            return True
        for key in ("retain_context", "keep_l2", "preserve_context"):
            value = raw.get(key)
            if isinstance(value, bool) and value:
                return True
            if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on", "retain", "keep"}:
                return True
        return False

    def _task_allows_context_discard(self, task: dict[str, Any]) -> bool:
        policy = str(task.get("context_policy", "")).strip().lower()
        if policy in {"discard", "release", "auto", "ephemeral"}:
            return True
        return not bool(task.get("retain_context"))

    def _commander_context_should_be_retained(self, commander: dict[str, Any], tasks: list[dict[str, Any]]) -> bool:
        if commander.get("lifecycle") != "campaign":
            return True
        if commander.get("retain_context"):
            return True
        for task in tasks:
            status = str(task.get("status", ""))
            if status not in TERMINAL_TASK_STATUSES:
                return True
            if not self._task_allows_context_discard(task):
                return True
            if status in {"failed", "blocked"} and str(task.get("context_policy", "")).strip().lower() not in {"discard", "release"}:
                return True
        return False

    def _retire_idle_campaign_commanders(self) -> None:
        registry = self._read_registry()
        tasks = [dict(item) for item in registry.get("tasks", [])]
        for commander in list(registry.get("commanders", [])):
            if commander.get("role") != "branch-commander":
                continue
            if commander.get("lifecycle") != "campaign":
                continue
            if commander.get("status") not in {"planned", "launching", "commanding"}:
                continue
            owned_tasks = [task for task in tasks if task.get("commander") == commander.get("id")]
            if not owned_tasks:
                continue
            if self._commander_context_should_be_retained(dict(commander), owned_tasks):
                continue
            self._disband_campaign_commander(dict(commander), owned_tasks)

    def _disband_campaign_commander(self, commander: dict[str, Any], tasks: list[dict[str, Any]]) -> None:
        commander_id = str(commander.get("id", ""))
        if not commander_id:
            return
        task_ids = [str(task.get("id", "")) for task in tasks if task.get("id")]
        content = (
            "DISBAND:init-complete | all assigned campaign tasks reached terminal state "
            f"and context retention was not requested | tasks={','.join(task_ids)}"
        )
        try:
            self.send_message(commander_id, content, sender="Legion Core", message_type="disband")
        except SystemExit:
            pass

        session = str(commander.get("session", ""))
        tmux_killed = False
        if session and self._tmux_has_session(session):
            code, _, _ = self.runner.run(["tmux", "kill-session", "-t", session])
            tmux_killed = code == 0

        with self._registry_lock():
            registry = self._read_registry()
            for item in registry.setdefault("commanders", []):
                if item.get("id") == commander_id:
                    item["status"] = "completed"
                    item["disbanded_at"] = iso_now()
                    item["disbanded_reason"] = "campaign tasks completed and context not retained"
                    item["tmux_killed"] = tmux_killed
                    item["updated"] = iso_now()
                    break
            self._write_registry(registry)
        self._event("branch_commander_disbanded", commander_id, {"tasks": task_ids, "tmux_killed": tmux_killed})

    def mark_commander(self, commander_id: str, status: str) -> None:
        self.init_state()
        commander_to_announce: dict[str, Any] | None = None
        with self._registry_lock():
            registry = self._read_registry()
            for commander in registry.setdefault("commanders", []):
                if commander.get("id") == commander_id:
                    current = str(commander.get("status", ""))
                    # Monotonic terminal commander state — once completed/failed,
                    # do not silently revert (e.g. via stale reconcile).
                    if current in TERMINAL_COMMANDER_STATUSES and status != current:
                        self._event(
                            "commander_status_rejected",
                            commander_id,
                            {"current": current, "requested": status, "reason": "terminal-monotonic"},
                        )
                        return
                    commander["status"] = status
                    commander["updated"] = iso_now()
                    if (
                        status == "commanding"
                        and commander.get("role") == "commander"
                        and self._entry_level(commander) == 1
                        and not self._aicto_command_chain_connected(commander)
                    ):
                        commander_to_announce = dict(commander)
                    self._write_registry(registry)
                    self._event(f"commander_{status}", commander_id, {})
                    break
            else:
                raise SystemExit(f"unknown commander: {commander_id}")
        if commander_to_announce:
            self._announce_l1_online(commander_to_announce, action="marked-commanding")
        return

    def _aicto_command_chain_connected(self, commander: dict[str, Any]) -> bool:
        chains = commander.get("command_chains") or {}
        link = chains.get("aicto") or commander.get("aicto_link") or {}
        return link.get("status") == "connected" and link.get("actual_communication") is True

    def repair_dependents(self, original_task_id: str, replacement_task_id: str = "") -> list[str]:
        """Explicit repair operation: unblock dependents of a failed/blocked task.

        The original task stays in its terminal `failed`/`blocked` state
        (monotonic). Dependents whose `depends_on` referenced it have that
        reference rewritten to `replacement_task_id` (when given) or removed.
        Blocked dependents are reset to `planned` so the dependency engine can
        relaunch them once the replacement satisfies the dependency.
        """
        self.init_state()
        original_id = original_task_id.strip()
        replacement_id = replacement_task_id.strip()
        if not original_id:
            raise SystemExit("original task id is required for repair")
        repaired: list[str] = []
        with self._registry_lock():
            registry = self._read_registry()
            tasks = registry.setdefault("tasks", [])
            original = next((t for t in tasks if str(t.get("id", "")) == original_id), None)
            if not original:
                raise SystemExit(f"unknown task: {original_id}")
            current = str(original.get("status", ""))
            if current not in {"failed", "blocked"}:
                raise SystemExit(f"{original_id}: only failed/blocked tasks can be repaired (current={current})")
            if replacement_id:
                replacement = next((t for t in tasks if str(t.get("id", "")) == replacement_id), None)
                if not replacement:
                    raise SystemExit(f"unknown replacement task: {replacement_id}")
                replacement_status = str(replacement.get("status", ""))
                if replacement_status in {"failed", "blocked"}:
                    raise SystemExit(
                        f"{replacement_id}: replacement task must not be failed/blocked (current={replacement_status})"
                    )

            affected = self._dependent_closure(tasks, original_id)
            repairs = list(original.get("repaired_by", []))
            if replacement_id and replacement_id not in repairs:
                repairs.append(replacement_id)
                original["repaired_by"] = repairs
                original["updated"] = iso_now()
            for task in tasks:
                depends = [str(d) for d in task.get("depends_on", [])]
                if original_id not in depends:
                    continue
                if replacement_id:
                    new_depends = [replacement_id if d == original_id else d for d in depends]
                else:
                    new_depends = [d for d in depends if d != original_id]
                # Preserve order while removing duplicates introduced by rewrite.
                seen: set[str] = set()
                deduped: list[str] = []
                for dep in new_depends:
                    if dep in seen:
                        continue
                    seen.add(dep)
                    deduped.append(dep)
                task["depends_on"] = deduped

            task_by_id = {str(task.get("id", "")): task for task in tasks}
            repaired_seen: set[str] = set()
            changed = True
            while changed:
                changed = False
                for task_id in affected:
                    task = task_by_id.get(task_id)
                    if not task or str(task.get("status", "")) != "blocked":
                        continue
                    if self._has_failed_or_blocked_dependency(task, task_by_id):
                        continue
                    task["status"] = "planned"
                    task.pop("blocked_reason", None)
                    task["updated"] = iso_now()
                    if task_id not in repaired_seen:
                        repaired_seen.add(task_id)
                        repaired.append(task_id)
                    changed = True
            self._write_registry(registry)
        self._event(
            "task_repair",
            original_id,
            {"replacement": replacement_id, "dependents_unblocked": repaired},
        )
        for dep_id in repaired:
            self._event(
                "task_planned",
                dep_id,
                {"reason": "repair", "original": original_id, "replacement": replacement_id},
            )
        if repaired:
            # Try to launch any newly ready tasks (e.g. when replacement is already
            # completed). Best-effort: skip if no tmux session is desired in dry runs.
            try:
                self.ensure_tmux_session()
                self._launch_ready_tasks()
            except SystemExit:
                pass
        return repaired

    def _fail_commander_launch(self, entry: dict[str, Any], event: str, failure: str) -> dict[str, Any]:
        failed = dict(entry)
        failed["status"] = "failed"
        failed["failure"] = failure
        failed["updated"] = iso_now()
        self._upsert_commander(failed)
        self._event(event, str(failed["id"]), {"failure": failure})
        return failed

    def _set_task_status(self, task_id: str, status: str, extra: dict[str, Any] | None = None) -> None:
        report_entry: dict[str, Any] | None = None
        with self._registry_lock():
            entry = self._task_entry(task_id)
            if not entry:
                raise SystemExit(f"unknown task: {task_id}")
            current = str(entry.get("status", ""))
            # Monotonic terminal: once a task reaches a terminal state, only
            # transitions between terminal states are tolerated (and ignored as
            # no-ops) so reconcile/late workers cannot revive completed work.
            if current in TERMINAL_TASK_STATUSES and status != current:
                self._event(
                    "task_status_rejected",
                    task_id,
                    {"current": current, "requested": status, "reason": "terminal-monotonic"},
                )
                return
            if status in {"launching", "launched", "running"}:
                candidate = dict(entry)
                if extra:
                    candidate.update(extra)
                candidate["status"] = status
                conflict = self._launch_scope_conflict(candidate)
                if conflict:
                    entry["status"] = "blocked"
                    entry["blocked_reason"] = (
                        f"scope conflict: {task_id} claims {conflict['scope']} overlapping "
                        f"{conflict['conflicts_with']} scope {conflict['conflict_scope']}"
                    )
                    entry["scope_conflict"] = conflict
                    entry["updated"] = iso_now()
                    self._upsert_task(entry)
                    self._event(
                        "scope_conflict_blocked",
                        task_id,
                        {"reason": entry["blocked_reason"], "conflict": conflict},
                    )
                    report_entry = dict(entry)
                    self._block_dependents(task_id, "blocked")
                    self._report_task_to_aicto(report_entry)
                    return
            if extra:
                entry.update(extra)
            entry["status"] = status
            entry["updated"] = iso_now()
            self._upsert_task(entry)
            self._event(f"task_{status}", task_id, {})
            if status in TERMINAL_TASK_STATUSES:
                report_entry = dict(entry)

        if report_entry:
            self._report_task_to_aicto(report_entry)
        if status in {"failed", "blocked"}:
            self._block_dependents(task_id, status)
        elif status == "completed":
            self.ensure_tmux_session()
            self._launch_ready_tasks()
        if status in TERMINAL_TASK_STATUSES:
            self._retire_idle_campaign_commanders()

    def _launch_ready_tasks(self) -> list[str]:
        launched: list[str] = []
        for task in list(self._read_registry().get("tasks", [])):
            if task.get("status") != "planned":
                continue
            dependency_state = self._dependency_state(task)
            if dependency_state == "blocked":
                self._set_task_status(
                    str(task["id"]),
                    "blocked",
                    {"blocked_reason": "dependency failed or blocked"},
                )
                continue
            if dependency_state != "ready":
                continue
            spec = TaskSpec.from_mapping(task)
            commander = task.get("commander", "L1-mixed")
            ok, reason = self._commander_active_live(str(commander))
            if not ok:
                self._set_task_status(
                    spec.task_id,
                    "blocked",
                    {
                        "blocked_reason": f"assigned commander unavailable: {reason}",
                        "commander_unavailable": {"commander": str(commander), "reason": reason},
                    },
                )
                continue
            conflict = self._launch_scope_conflict(task)
            if conflict:
                self._block_task_scope_conflict(spec.task_id, conflict)
                continue
            if self.launch_task(spec, commander):
                launched.append(spec.task_id)
        return launched

    def _dependency_state(self, task: dict[str, Any]) -> str:
        dependencies = [str(item) for item in task.get("depends_on", [])]
        if not dependencies:
            return "ready"
        tasks = {str(item.get("id")): item for item in self._read_registry().get("tasks", [])}
        for dependency in dependencies:
            status = tasks.get(dependency, {}).get("status")
            if status in {"failed", "blocked"}:
                return "blocked"
            if status != "completed":
                return "waiting"
        return "ready"

    def _dependent_closure(self, tasks: list[dict[str, Any]], task_id: str) -> list[str]:
        reverse: dict[str, list[str]] = {}
        for task in tasks:
            current_id = str(task.get("id", ""))
            if not current_id:
                continue
            for dependency in [str(item) for item in task.get("depends_on", [])]:
                reverse.setdefault(dependency, []).append(current_id)

        affected: list[str] = []
        seen: set[str] = set()
        queue = list(reverse.get(task_id, []))
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            affected.append(current)
            queue.extend(reverse.get(current, []))
        return affected

    def _has_failed_or_blocked_dependency(self, task: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> bool:
        for dependency in [str(item) for item in task.get("depends_on", [])]:
            if str(tasks.get(dependency, {}).get("status", "")) in {"failed", "blocked"}:
                return True
        return False

    def _block_dependents(self, task_id: str, cause_status: str) -> None:
        blocked_entries: list[dict[str, Any]] = []
        with self._registry_lock():
            registry = self._read_registry()
            changed = False
            blocked_ids: list[str] = []
            for task in registry.get("tasks", []):
                if task_id not in [str(item) for item in task.get("depends_on", [])]:
                    continue
                if task.get("status") in {"completed", "failed", "blocked"}:
                    continue
                task["status"] = "blocked"
                task["blocked_reason"] = f"dependency {task_id} is {cause_status}"
                task["updated"] = iso_now()
                blocked_ids.append(str(task.get("id")))
                blocked_entries.append(dict(task))
                changed = True
            if changed:
                self._write_registry(registry)
        if blocked_ids:
            entries_by_id = {str(item.get("id", "")): item for item in blocked_entries}
            for blocked_id in blocked_ids:
                self._event("task_blocked", blocked_id, {"dependency": task_id, "dependency_status": cause_status})
                if blocked_id in entries_by_id:
                    self._report_task_to_aicto(entries_by_id[blocked_id])
                self._block_dependents(blocked_id, "blocked")

    def _fail_task_launch(self, task_id: str, failure: str) -> None:
        self._set_task_status(task_id, "failed", {"failure": failure})

    def _read_worker_result(self, result_file: Path) -> dict[str, Any] | None:
        try:
            text = result_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"_invalid_result": True, "failure": "worker result was not valid JSON"}
        if not isinstance(data, dict):
            return {"_invalid_result": True, "failure": "worker result failed schema validation: root must be an object"}
        schema_error = self._worker_result_schema_error(data)
        if schema_error:
            return {"_invalid_result": True, "failure": f"worker result failed schema validation: {schema_error}"}
        return data

    def _worker_result_schema_error(self, data: dict[str, Any]) -> str:
        keys = set(data.keys())
        if keys != WORKER_RESULT_KEYS:
            missing = sorted(WORKER_RESULT_KEYS - keys)
            extra = sorted(keys - WORKER_RESULT_KEYS)
            details = []
            if missing:
                details.append(f"missing keys {missing}")
            if extra:
                details.append(f"unexpected keys {extra}")
            return "; ".join(details)
        if not isinstance(data["status"], str) or data["status"] not in WORKER_RESULT_STATUSES:
            return "status must be one of completed, blocked, failed"
        if not isinstance(data["summary"], str) or not data["summary"]:
            return "summary must be a non-empty string"
        if not self._is_string_list(data["files_touched"]):
            return "files_touched must be an array of strings"
        if not isinstance(data["verification"], list):
            return "verification must be an array"
        for index, item in enumerate(data["verification"]):
            error = self._worker_verification_schema_error(item)
            if error:
                return f"verification[{index}] {error}"
        if not isinstance(data["findings"], list):
            return "findings must be an array"
        for index, item in enumerate(data["findings"]):
            error = self._worker_finding_schema_error(item)
            if error:
                return f"findings[{index}] {error}"
        if not self._is_string_list(data["risks"]):
            return "risks must be an array of strings"
        return ""

    def _worker_verification_schema_error(self, item: Any) -> str:
        if not isinstance(item, dict):
            return "must be an object"
        keys = set(item.keys())
        if keys != WORKER_VERIFICATION_KEYS:
            missing = sorted(WORKER_VERIFICATION_KEYS - keys)
            extra = sorted(keys - WORKER_VERIFICATION_KEYS)
            details = []
            if missing:
                details.append(f"missing keys {missing}")
            if extra:
                details.append(f"unexpected keys {extra}")
            return "; ".join(details)
        if not isinstance(item["command"], str):
            return "command must be a string"
        if not isinstance(item["result"], str) or item["result"] not in WORKER_VERIFICATION_RESULTS:
            return "result must be one of pass, fail, not-run"
        if item["details"] is not None and not isinstance(item["details"], str):
            return "details must be a string or null"
        return ""

    def _worker_finding_schema_error(self, item: Any) -> str:
        if not isinstance(item, dict):
            return "must be an object"
        keys = set(item.keys())
        if keys != WORKER_FINDING_KEYS:
            missing = sorted(WORKER_FINDING_KEYS - keys)
            extra = sorted(keys - WORKER_FINDING_KEYS)
            details = []
            if missing:
                details.append(f"missing keys {missing}")
            if extra:
                details.append(f"unexpected keys {extra}")
            return "; ".join(details)
        if not isinstance(item["severity"], str) or item["severity"] not in WORKER_FINDING_SEVERITIES:
            return "severity must be one of critical, major, minor, suggestion"
        if item["file"] is not None and not isinstance(item["file"], str):
            return "file must be a string or null"
        line = item["line"]
        if line is not None:
            if type(line) is not int or line < 1:
                return "line must be an integer >= 1 or null"
        if not isinstance(item["description"], str):
            return "description must be a string"
        if item["recommendation"] is not None and not isinstance(item["recommendation"], str):
            return "recommendation must be a string or null"
        return ""

    def _is_string_list(self, value: Any) -> bool:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    def _task_entry(self, task_id: str) -> dict[str, Any] | None:
        for task in self._read_registry().get("tasks", []):
            if task.get("id") == task_id:
                return dict(task)
        return None

    def _commander_id(self, name: str) -> str:
        if name.strip():
            raw = name.strip()
        else:
            raw = self._next_commander_name()
        return raw if raw.startswith("L1-") else f"L1-{raw}"

    def _aicto_commander_id(self, name: str = "") -> str:
        raw = name.strip() or f"{self.context.project_name}-coordinator"
        return raw if raw.startswith("L0-") else f"L0-{raw}"

    def _fresh_commander_id(self, preferred: str) -> str:
        used = {item.get("id") for item in self._read_registry().get("commanders", [])}
        if preferred not in used:
            return preferred
        base = preferred
        index = 2
        while f"{base}-{index}" in used:
            index += 1
        return f"{base}-{index}"

    def _next_commander_name(self) -> str:
        used = {item.get("id", "").replace("L1-", "").replace("军团", "") for item in self._read_registry().get("commanders", [])}
        available = [name for name in L1_CODENAMES if name not in used]
        if available:
            return f"{random.choice(available)}军团"
        return f"第{len(used) + 1}军团"

    def _project_host_name(self, provider: str) -> str:
        seed = f"{self.context.project_dir}:{self.context.project_hash}:host:{provider}"
        digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
        codename = L1_CODENAMES[int(digest[:8], 16) % len(L1_CODENAMES)]
        return f"{self.context.project_name}-{codename}军团"

    def _project_provider_l1_name(self, provider: str) -> str:
        provider_key = provider.strip().lower()
        seed = f"{self.context.project_dir}:{self.context.project_hash}:dual-l1:{provider_key}"
        digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
        codename = L1_CODENAMES[int(digest[:8], 16) % len(L1_CODENAMES)]
        return f"{self.context.project_name}-{provider_key}-{codename}军团"

    def _entry_level(self, commander: dict[str, Any], default: int = -1) -> int:
        try:
            return int(commander.get("level", default) or default)
        except (TypeError, ValueError):
            return default

    def _online_commander(self, provider: str, detached_only: bool = False) -> dict[str, Any] | None:
        for commander in self._read_registry().get("commanders", []):
            if commander.get("role") != "commander":
                continue
            if commander.get("provider") != provider:
                continue
            if commander.get("status") in {"completed", "failed"}:
                continue
            session = str(commander.get("session", ""))
            if session and self._tmux_has_session(session):
                if detached_only and self._tmux_session_attached(session):
                    continue
                return dict(commander)
        return None

    def _resolve_view_host(self, host: str = "") -> dict[str, Any]:
        requested = host.strip()
        commanders = [dict(item) for item in self._read_registry().get("commanders", [])]
        if requested:
            for commander in commanders:
                if commander.get("id") == requested:
                    if commander.get("role") != "commander":
                        raise SystemExit(f"{requested}: not an L1 commander")
                    if not self._commander_project_matches(commander):
                        raise SystemExit(f"{requested}: not registered for project {self.context.project_dir}")
                    session = str(commander.get("session", ""))
                    if not session or not self._tmux_has_session(session):
                        raise SystemExit(f"{requested}: tmux session is not alive")
                    return commander
            raise SystemExit(f"unknown host commander: {requested}")

        candidates: list[dict[str, Any]] = []
        for commander in commanders:
            if commander.get("role") != "commander":
                continue
            if not self._commander_project_matches(commander):
                continue
            if commander.get("status") in {"completed", "failed"}:
                continue
            if not self._commander_has_live_session(commander):
                continue
            if self._view_l2_entries(str(commander.get("id", ""))):
                candidates.append(commander)

        if not candidates:
            raise SystemExit("no live L1 host with active task L2 commanders and no dual-L1 view target; run `legion h` first")
        return max(candidates, key=lambda item: str(item.get("updated", "")))

    def _view_target(self, commander: dict[str, Any], label: str) -> dict[str, str]:
        session = str(commander.get("session", ""))
        if not session:
            raise SystemExit(f"{commander.get('id', '?')}: missing tmux session")
        return {
            "id": str(commander.get("id", "")),
            "label": label,
            "session": session,
        }

    def _resolve_provider_l1(self, provider: str) -> dict[str, Any]:
        normalized_provider = provider.strip().lower()
        candidates = []
        for commander in self._read_registry().get("commanders", []):
            if commander.get("role") != "commander":
                continue
            if commander.get("provider") != normalized_provider:
                continue
            if commander.get("status") in {"completed", "failed"}:
                continue
            if not self._commander_project_matches(commander):
                continue
            if not self._commander_has_live_session(commander):
                continue
            candidates.append(dict(commander))
        if not candidates:
            raise SystemExit(f"no live {normalized_provider} L1 commander for project {self.context.project_dir}")
        return max(candidates, key=lambda item: str(item.get("updated", "")))

    def _resolve_aicto(self) -> dict[str, Any]:
        candidates = []
        for commander in self._read_registry().get("commanders", []):
            if commander.get("role") != "aicto":
                continue
            if self._entry_level(commander) != 0:
                continue
            if commander.get("status") in {"completed", "failed"}:
                continue
            if not self._commander_project_matches(commander):
                continue
            if not self._commander_has_live_session(commander):
                continue
            candidates.append(dict(commander))
        if not candidates:
            raise SystemExit(f"no live local L0 coordinator for project {self.context.project_dir}")
        return max(candidates, key=lambda item: str(item.get("updated", "")))

    def _commander_project_matches(self, commander: dict[str, Any]) -> bool:
        project = str(commander.get("project", "")).strip()
        if not project:
            return True
        return Path(project).expanduser().resolve(strict=False) == self.context.project_dir.resolve(strict=False)

    def _commander_has_live_session(self, commander: dict[str, Any]) -> bool:
        session = str(commander.get("session", "")).strip()
        return bool(session and self._tmux_has_session(session))

    def _validate_dual_view_commander(self, commander: dict[str, Any]) -> None:
        commander_id = str(commander.get("id", "?"))
        if not self._commander_project_matches(commander):
            raise SystemExit(f"{commander_id}: not registered for project {self.context.project_dir}")
        if str(commander.get("status", "")) == "planned":
            return
        if not self._commander_has_live_session(commander):
            raise SystemExit(f"{commander_id}: tmux session is not alive")

    def _ensure_convened_commanders_live(self, commanders: list[dict[str, Any]]) -> None:
        for commander in commanders:
            commander_id = str(commander.get("id", "?"))
            status = str(commander.get("status", ""))
            if status != "commanding":
                raise SystemExit(f"{commander_id}: launch failed before dual-L1 readiness (status={status})")
            if not self._commander_has_live_session(commander):
                raise SystemExit(f"{commander_id}: launch did not create a live tmux session")

    def _branch_commander(self, branch: str, parent: str, provider: str = "") -> dict[str, Any] | None:
        normalized_provider = provider.strip().lower()
        fallback: dict[str, Any] | None = None
        for commander in self._read_registry().get("commanders", []):
            if commander.get("role") != "branch-commander":
                continue
            if commander.get("branch") != branch or commander.get("parent") != parent:
                continue
            if not self._commander_project_matches(commander):
                continue
            if normalized_provider and commander.get("provider") != normalized_provider:
                continue
            status = str(commander.get("status", ""))
            session = str(commander.get("session", ""))
            if status in {"commanding", "launching"} and session and self._tmux_has_session(session):
                return dict(commander)
            if fallback is None and status not in {"completed", "failed"}:
                fallback = dict(commander)
        return fallback

    def _branch_commander_is_reusable(self, commander: dict[str, Any], dry_run: bool) -> bool:
        status = str(commander.get("status", ""))
        if status in {"completed", "failed"}:
            return False
        if dry_run:
            return True
        session = str(commander.get("session", ""))
        if status in {"commanding", "launching"} and session and self._tmux_has_session(session):
            return True
        if status in {"commanding", "launching"}:
            stale = dict(commander)
            stale["status"] = "failed"
            stale["failure"] = "tmux session is not alive"
            stale["updated"] = iso_now()
            self._upsert_commander(stale)
            self._event("branch_commander_failed", str(stale["id"]), {"failure": stale["failure"]})
        return False

    def _refresh_reused_branch_commander(self, commander: dict[str, Any], lifecycle: str) -> dict[str, Any]:
        refreshed = dict(commander)
        self._refresh_branch_commander_artifacts(refreshed)
        requested_lifecycle = lifecycle.strip().lower() if lifecycle else ""
        current_lifecycle = str(refreshed.get("lifecycle", "")).strip().lower()
        if requested_lifecycle and (not current_lifecycle or requested_lifecycle == "host"):
            if current_lifecycle != requested_lifecycle:
                refreshed["lifecycle"] = requested_lifecycle
        refreshed["updated"] = iso_now()
        self._upsert_commander(refreshed)
        self._event("branch_commander_refreshed", str(refreshed.get("id", "")), {"lifecycle": refreshed.get("lifecycle", "")})
        return refreshed

    def _refresh_branch_commander_artifacts(self, commander: dict[str, Any]) -> None:
        commander_id = str(commander.get("id", "")).strip()
        branch = str(commander.get("branch", "")).strip()
        provider = str(commander.get("provider", "")).strip()
        parent = str(commander.get("parent", "")).strip() or "L1-mixed"
        run_dir_raw = str(commander.get("run_dir", "")).strip()
        if not commander_id or not branch or provider not in {"claude", "codex"} or not run_dir_raw:
            return
        run_dir = Path(run_dir_raw)
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = run_dir / "prompt.md"
        launch_script = run_dir / "launch.sh"
        log_file = run_dir / "commander.log"
        prompt_file.write_text(
            self.render_branch_commander_prompt(commander_id, branch, provider, parent),
            encoding="utf-8",
        )
        launch_script.write_text(
            self._branch_commander_launch_script(commander_id, provider, prompt_file, log_file),
            encoding="utf-8",
        )
        launch_script.chmod(0o755)

    def _refresh_l1_commander_artifacts(self, commander: dict[str, Any]) -> None:
        commander_id = str(commander.get("id", "")).strip()
        provider = str(commander.get("provider", "")).strip()
        run_dir_raw = str(commander.get("run_dir", "")).strip()
        if not commander_id or provider not in {"claude", "codex"} or not run_dir_raw:
            return
        run_dir = Path(run_dir_raw)
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = run_dir / "prompt.md"
        launch_script = run_dir / "launch.sh"
        log_file = run_dir / "commander.log"
        prompt_file.write_text(self.render_commander_prompt(commander_id, provider), encoding="utf-8")
        if provider == "codex":
            launch_text = self._codex_commander_launch_script(commander_id, prompt_file, log_file)
        else:
            launch_text = self._claude_commander_launch_script(commander_id, prompt_file, log_file)
        launch_script.write_text(launch_text, encoding="utf-8")
        launch_script.chmod(0o755)

    def _apply_commander_window_identity(self, commander: dict[str, Any]) -> None:
        session = str(commander.get("session", "")).strip()
        commander_id = str(commander.get("id", "")).strip()
        if not session or not commander_id:
            return
        window_target = f"{session}:0"
        commands = [
            ["tmux", "set-window-option", "-t", window_target, "automatic-rename", "off"],
            ["tmux", "rename-window", "-t", window_target, commander_id],
            ["tmux", "set-option", "-u", "-t", session, "status-left"],
            ["tmux", "set-option", "-u", "-t", session, "status-left-length"],
            ["tmux", "set-option", "-u", "-t", session, "status-right"],
            ["tmux", "set-option", "-u", "-t", session, "status-right-length"],
            ["tmux", "set-option", "-u", "-t", session, "status-position"],
            ["tmux", "set-option", "-u", "-t", session, "set-titles-string"],
        ]
        for command in commands:
            self.runner.run(command)

    def _branch_commander_id(self, branch: str) -> str:
        used = {item.get("id") for item in self._read_registry().get("commanders", [])}
        base = f"L2-{branch}-{int(time.time())}"
        if base not in used:
            return base
        index = 2
        while f"{base}-{index}" in used:
            index += 1
        return f"{base}-{index}"

    def _tmux_has_session(self, session: str) -> bool:
        return self._tmux_probe_session(session)["state"] == "live"

    def _tmux_probe_session(self, session: str) -> dict[str, str]:
        code, stdout, stderr = self.runner.run(["tmux", "has-session", "-t", session])
        if code == 0:
            return {"state": "live", "detail": ""}
        detail = (stderr or stdout).strip()
        return {"state": self._classify_tmux_probe_failure(detail), "detail": detail}

    def _tmux_probe_window(self, session: str, window: str) -> dict[str, str]:
        session_probe = self._tmux_probe_session(session)
        if session_probe["state"] != "live":
            return session_probe
        code, stdout, stderr = self.runner.run(["tmux", "list-windows", "-t", session, "-F", "#{window_name}"])
        if code != 0:
            detail = (stderr or stdout).strip()
            return {"state": self._classify_tmux_probe_failure(detail), "detail": detail}
        windows = {line.strip() for line in stdout.splitlines()}
        if window in windows:
            return {"state": "live", "detail": ""}
        return {"state": "missing", "detail": f"tmux window is not alive: {window}"}

    def _classify_tmux_probe_failure(self, detail: str) -> str:
        text = detail.lower()
        missing_markers = (
            "can't find session",
            "cannot find session",
            "no such session",
            "missing session",
            "no server running",
            "no such file or directory",
            "not found",
        )
        if any(marker in text for marker in missing_markers):
            return "missing"
        inaccessible_markers = (
            "permission denied",
            "operation not permitted",
            "access denied",
            "failed to connect",
            "can't connect",
            "cannot connect",
            "connection refused",
            "socket",
        )
        if any(marker in text for marker in inaccessible_markers):
            return "inaccessible"
        return "missing"

    def _tmux_session_attached(self, session: str) -> bool:
        code, stdout, _ = self.runner.run(["tmux", "display-message", "-p", "-t", session, "#{session_attached}"])
        if code != 0:
            return False
        try:
            return int(stdout.strip() or "0") > 0
        except ValueError:
            return stdout.strip().lower() not in {"", "0", "false", "no"}

    def _tmux_foreground_argv(self, session: str, env: dict[str, str] | None = None) -> list[str]:
        active_env = env if env is not None else os.environ
        if active_env.get("TMUX"):
            return ["tmux", "switch-client", "-t", session]
        return ["tmux", "a", "-t", session]

    def _tmux_has_window(self, session: str, window: str) -> bool:
        return self._tmux_probe_window(session, window)["state"] == "live"

    def _event(self, event: str, task_id: str, payload: dict[str, Any], correlation_id: str = "") -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        timestamp = iso_now()
        normalized_payload = dict(payload) if payload else {"transition": event}
        correlation = (
            correlation_id.strip()
            or str(normalized_payload.get("correlation_id", "")).strip()
            or os.environ.get("LEGION_CORRELATION_ID", "").strip()
            or self._new_correlation_id(f"event:{event}:{task_id}")
        )
        normalized_payload.setdefault("transition", event)
        event_material = json.dumps(
            {
                "timestamp": timestamp,
                "event": event,
                "subject": task_id,
                "payload": normalized_payload,
                "correlation_id": correlation,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        event_id = f"evt-{hashlib.sha256(event_material.encode('utf-8')).hexdigest()[:24]}"
        record = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "id": event_id,
            "type": "event",
            "timestamp": timestamp,
            "correlation_id": correlation,
            # Backward-compatible reader fields.
            "ts": timestamp,
            "event": event,
            "task_id": task_id,
            "subject_id": task_id,
            "payload": normalized_payload,
        }
        with self._file_append_lock(self.events_file):
            with self.events_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def default_provider_for_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in CODEX_DEFAULT_ROLES:
        return "codex"
    if normalized in CLAUDE_DEFAULT_ROLES:
        return "claude"
    return "codex"


def default_provider_for_branch(branch: str) -> str:
    normalized = normalize_branch(branch)
    if normalized in CLAUDE_DEFAULT_BRANCHES:
        return "claude"
    if normalized in CODEX_DEFAULT_BRANCHES:
        return "codex"
    return default_provider_for_role(normalized)


def default_role_for_branch(branch: str) -> str:
    normalized = normalize_branch(branch)
    if normalized in {"backend", "frontend", "implement", "ui"}:
        return "implement"
    if normalized in CODEX_DEFAULT_BRANCHES:
        return normalized
    if normalized in CODEX_DEFAULT_ROLES or normalized in CLAUDE_DEFAULT_ROLES:
        return normalized
    return "implement"


def normalize_complexity(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "": "",
        "s": "s",
        "small": "s",
        "simple": "s",
        "trivial": "s",
        "low": "s",
        "m": "m",
        "medium": "m",
        "moderate": "m",
        "mid": "m",
        "l": "l",
        "large": "l",
        "high": "l",
        "xl": "xl",
        "x-large": "xl",
        "xlarge": "xl",
        "extra-large": "xl",
    }
    return aliases.get(normalized, "")


def normalize_branch(value: str) -> str:
    return normalize_task_id(value.strip().lower()) if value.strip() else ""


def normalize_task_id(value: str) -> str:
    safe = []
    for char in value:
        if char.isalnum() or char in ("-", "_"):
            safe.append(char)
        elif char.isspace():
            safe.append("-")
    normalized = "".join(safe).strip("-_").lower()
    return normalized or f"task-{int(time.time())}"


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_plan(raw: str) -> list[dict[str, Any]]:
    if raw == "-":
        text = sys.stdin.read()
    elif Path(raw).exists():
        text = Path(raw).read_text(encoding="utf-8")
    else:
        text = raw
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("tasks", data.get("plan", []))
    if not isinstance(data, list):
        raise SystemExit("campaign plan must be a JSON array or an object with tasks/plan")
    return data


def external_aicto_status_text(project_dir: Path | str = "/Users/feijun/Documents/AICTO") -> str:
    """Describe the real Hermes AICTO control plane.

    AICTO is an external Hermes project/profile, not a Legion Core in-process
    L0 commander. This command is intentionally read-only: it reports the
    expected project/profile paths and startup commands without mutating Legion
    mixed state or launching a local placeholder commander.
    """
    project = Path(project_dir).expanduser()
    config = Path.home() / ".hermes" / "profiles" / "aicto" / "config.yaml"
    plugin = project / "hermes-plugin"
    lines = [
        "AICTO is the external Hermes CTO project, not a local Legion L0 commander.",
        f"project: {project} ({'found' if project.exists() else 'missing'})",
        f"plugin: {plugin} ({'found' if plugin.exists() else 'missing'})",
        f"profile_config: {config} ({'found' if config.exists() else 'missing'})",
        "",
        "Start/check AICTO from its own project/profile:",
        f"  cd {shlex.quote(str(project))}",
        "  hermes profile list",
        "  hermes profile show aicto",
        "  nohup aicto gateway run > /tmp/aicto-gateway.log 2>&1 &",
        "  curl http://127.0.0.1:8644/health",
        "",
        "Legion Core's job is only the tmux/registry/inbox runtime for Claude and Codex armies.",
        "Use `legion host` for Claude L1 + Codex L1; let Hermes AICTO command them via its plugin tools.",
    ]
    try:
        completed = subprocess.run(
            ["hermes", "profile", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        lines.append(f"hermes_profile_list: unavailable ({type(exc).__name__})")
    else:
        status = "ok" if completed.returncode == 0 else f"exit={completed.returncode}"
        snippet = " ".join((completed.stdout or completed.stderr).split())[:240]
        lines.append(f"hermes_profile_list: {status}" + (f" | {snippet}" if snippet else ""))
    return "\n".join(lines)


def example_plan() -> list[dict[str, Any]]:
    return [
        {
            "id": "explore-architecture",
            "provider": "codex",
            "role": "explore",
            "task": "Map the repository architecture and identify integration points.",
            "scope": ["README.md", "scripts/", "agents/", "skills/"],
        },
        {
            "id": "implement-feature",
            "provider": "claude",
            "role": "implement",
            "task": "Implement the approved feature in the declared files.",
            "scope": ["scripts/new-feature.sh", "README.md"],
            "depends_on": ["explore-architecture"],
        },
        {
            "id": "codex-review",
            "provider": "codex",
            "role": "review",
            "task": "Review the implementation diff and report correctness, security, and testing issues.",
            "depends_on": ["implement-feature"],
        },
    ]


def build_duo_terminal_commands(
    project_dir: Path,
    legion_sh: Path,
    codex_name: str = "玄武军团",
    claude_name: str = "青龙军团",
) -> list[str]:
    project = shlex.quote(str(project_dir))
    entrypoint = shlex.quote(str(legion_sh))
    codex = shlex.quote(codex_name)
    claude = shlex.quote(claude_name)
    return [
        f"cd {project} && {entrypoint} codex l1 {codex}",
        f"cd {project} && {entrypoint} claude l1 {claude}",
    ]


def build_dou_terminal_commands(
    project_dir: Path,
    legion_sh: Path,
    codex_name: str = "玄武军团",
    claude_name: str = "青龙军团",
) -> dict[str, str]:
    project = shlex.quote(str(project_dir))
    entrypoint = shlex.quote(str(legion_sh))
    codex = shlex.quote(codex_name)
    claude = shlex.quote(claude_name)
    return {
        "new_window": f"cd {project} && {entrypoint} codex l1 {codex}",
        "current_window": f"cd {project} && {entrypoint} claude l1 {claude}",
    }


def attach_tmux_session(session: str) -> None:
    if os.environ.get("TMUX"):
        os.execvp("tmux", ["tmux", "switch-client", "-t", session])
    os.execvp("tmux", ["tmux", "a", "-t", session])


def build_interactive_view_tmux_script(
    project_dir: Path,
    view_session: str,
    targets: list[dict[str, str]],
    fresh: bool = False,
) -> str:
    if not targets:
        raise SystemExit("view requires at least one target session")
    project = shlex.quote(str(project_dir))
    session = shlex.quote(view_session)
    lines = [
        "set -e",
        f"VIEW_SESSION={session}",
        f"PROJECT_DIR={project}",
    ]
    if fresh:
        lines.append('tmux kill-session -t "$VIEW_SESSION" 2>/dev/null || true')
    lines.extend(
        [
            'if tmux has-session -t "$VIEW_SESSION" 2>/dev/null; then',
            '  if [ -n "${TMUX:-}" ]; then exec tmux switch-client -t "$VIEW_SESSION"; fi',
            '  exec tmux attach -t "$VIEW_SESSION"',
            "fi",
        ]
    )

    def attach_command(target: dict[str, str]) -> str:
        title = f"{target['label']} · {target['id']}"
        return (
            f"printf '\\033]2;%s\\007' {shlex.quote(title)}; "
            f"TMUX= tmux attach -t {shlex.quote(target['session'])}"
        )

    first = targets[0]
    first_title = f"{first['label']} · {first['id']}"
    lines.append(
        'L1_PANE=$(tmux new-session -d -s "$VIEW_SESSION" -c "$PROJECT_DIR" -P -F "#{pane_id}" '
        f"-n legion {shlex.quote(attach_command(first))})"
    )
    lines.extend(
        [
            'tmux set-option -t "$VIEW_SESSION" pane-border-status top >/dev/null',
            'tmux set-option -t "$VIEW_SESSION" pane-border-format "#{pane_title}" >/dev/null',
            f'tmux select-pane -t "$L1_PANE" -T {shlex.quote(first_title)}',
        ]
    )
    l2_targets = targets[1:]
    if l2_targets:
        first_l2 = l2_targets[0]
        first_l2_title = f"{first_l2['label']} · {first_l2['id']}"
        lines.append(
            'L2_REMAINING_PANE=$(tmux split-window -h -p 60 -P -F "#{pane_id}" '
            '-t "$L1_PANE" -c "$PROJECT_DIR" '
            f"{shlex.quote(attach_command(first_l2))})"
        )
        lines.append(f'tmux select-pane -t "$L2_REMAINING_PANE" -T {shlex.quote(first_l2_title)}')

    for index, target in enumerate(l2_targets[1:], start=1):
        title = f"{target['label']} · {target['id']}"
        remaining = len(l2_targets) - index + 1
        percent = round((remaining - 1) * 100 / remaining)
        variable = f"L2_PANE_{index + 1}"
        lines.append(
            f'{variable}=$(tmux split-window -v -p {percent} -P -F "#{{pane_id}}" '
            '-t "$L2_REMAINING_PANE" -c "$PROJECT_DIR" '
            f"{shlex.quote(attach_command(target))})"
        )
        lines.append(f'tmux select-pane -t "${variable}" -T {shlex.quote(title)}')
        lines.append(f'L2_REMAINING_PANE="${variable}"')
    lines.extend(
        [
            'tmux select-pane -t "$L1_PANE"',
            'if [ -n "${TMUX:-}" ]; then exec tmux switch-client -t "$VIEW_SESSION"; fi',
            'exec tmux attach -t "$VIEW_SESSION"',
        ]
    )
    return "\n".join(lines) + "\n"


def build_duo_applescript(commands: list[str]) -> str:
    lines = ['tell application "Terminal"', "activate"]
    for command in commands:
        lines.append(f"do script {json.dumps(command, ensure_ascii=False)}")
    lines.append("end tell")
    return "\n".join(lines)


def build_duo_tmux_script(
    project_dir: Path,
    legion_sh: Path,
    codex_name: str = "玄武军团",
    claude_name: str = "青龙军团",
    codex_launch_script: Path | None = None,
    claude_launch_script: Path | None = None,
) -> str:
    context = ProjectContext.from_path(project_dir)
    session = f"legion-duo-{context.project_hash}-{context.project_name}"
    socket = f"legion-duo-{context.project_hash}"
    project = shlex.quote(str(context.project_dir))
    entrypoint = shlex.quote(str(legion_sh))
    codex = shlex.quote(codex_name)
    claude = shlex.quote(claude_name)
    codex_command = f"TMUX= {entrypoint} codex l1 {codex}"
    claude_command = f"TMUX= {entrypoint} claude l1 {claude}"
    if codex_launch_script:
        codex_command = f"bash {shlex.quote(str(codex_launch_script))}"
    if claude_launch_script:
        claude_command = f"bash {shlex.quote(str(claude_launch_script))}"
    return f"""set -e
SESSION={shlex.quote(session)}
SOCKET={shlex.quote(socket)}
unset TMUX
if tmux -L "$SOCKET" has-session -t "$SESSION" 2>/dev/null; then
  exec tmux -L "$SOCKET" attach -t "$SESSION"
fi
tmux -L "$SOCKET" new-session -d -s "$SESSION" -c {project} -n codex {shlex.quote(codex_command)}
tmux -L "$SOCKET" new-window -t "$SESSION:" -n claude -c {project} {shlex.quote(claude_command)}
tmux -L "$SOCKET" select-window -t "$SESSION:codex"
exec tmux -L "$SOCKET" attach -t "$SESSION"
"""


def launch_duo_terminal(
    project_dir: Path,
    legion_sh: Path,
    codex_name: str = "玄武军团",
    claude_name: str = "青龙军团",
    terminal: str = "terminal",
    runner: CommandRunner | None = None,
    dry_run: bool = False,
    legion_home: Path | None = None,
) -> list[str]:
    if terminal == "vscode":
        if dry_run:
            return [build_duo_tmux_script(project_dir, legion_sh, codex_name, claude_name)]
        core = LegionCore(project_dir, legion_home=legion_home, runner=runner)
        codex = core.prepare_commander_launch_artifacts(provider="codex", name=codex_name)
        claude = core.prepare_commander_launch_artifacts(provider="claude", name=claude_name)
        script = build_duo_tmux_script(
            project_dir,
            legion_sh,
            codex_name,
            claude_name,
            codex_launch_script=Path(codex["run_dir"]) / "launch.sh",
            claude_launch_script=Path(claude["run_dir"]) / "launch.sh",
        )
        os.execvp("bash", ["bash", "-lc", script])
        raise SystemExit(1)

    if terminal != "terminal":
        raise SystemExit(f"unsupported terminal: {terminal!r}")

    commands = build_duo_terminal_commands(project_dir, legion_sh, codex_name, claude_name)
    if dry_run:
        return commands
    if sys.platform != "darwin":
        raise SystemExit("duo currently opens Terminal.app windows and requires macOS")
    script = build_duo_applescript(commands)
    active_runner = runner or CommandRunner()
    code, stdout, stderr = active_runner.run(["osascript", "-e", script])
    if code != 0:
        detail = (stderr or stdout).strip()
        raise SystemExit(f"failed to open Terminal.app windows: {detail}")
    return commands


def launch_dou_new_window(
    project_dir: Path,
    legion_sh: Path,
    codex_name: str = "玄武军团",
    claude_name: str = "青龙军团",
    runner: CommandRunner | None = None,
    dry_run: bool = False,
) -> dict[str, str]:
    commands = build_dou_terminal_commands(project_dir, legion_sh, codex_name, claude_name)
    if dry_run:
        return commands
    if sys.platform != "darwin":
        raise SystemExit("dou currently opens a new Terminal.app window and requires macOS")
    script = build_duo_applescript([commands["new_window"]])
    active_runner = runner or CommandRunner()
    code, stdout, stderr = active_runner.run(["osascript", "-e", script])
    if code != 0:
        detail = (stderr or stdout).strip()
        raise SystemExit(f"failed to open Codex Terminal.app window: {detail}")
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mixed Claude/Codex Legion core")
    parser.add_argument("--project-dir", default=os.getcwd())
    parser.add_argument("--legion-home", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    campaign = sub.add_parser("campaign", help="Deploy a mixed provider campaign")
    campaign.add_argument("plan", help="JSON array, JSON file, or '-' for stdin")
    campaign.add_argument("--commander", default="auto", help="Commander id; defaults to current L1/L2 from environment")
    campaign.add_argument("--dry-run", action="store_true")
    campaign.add_argument("--corps", action="store_true", help="Route tasks through specialty L2 branch commanders")
    campaign.add_argument("--direct", action="store_true", help="Keep an S-level task with the current commander instead of routing through corps")
    campaign.add_argument("--complexity", choices=["s", "m", "l", "xl"], default="", help="Apply a campaign-wide complexity level")

    sub.add_parser("status", help="Show mixed Legion status (read-only)")
    sub.add_parser(
        "reconcile",
        help="Probe tmux liveness and update commander/task statuses (mutating, separate from status)",
    )

    l1 = sub.add_parser("l1", help="Start a mixed Legion L1 commander")
    l1.add_argument("--provider", choices=["claude", "codex"], default="codex")
    l1.add_argument("name", nargs="?", default="")
    l1.add_argument("--dry-run", action="store_true")
    l1.add_argument("--no-attach", action="store_true")
    l1.add_argument("--fresh", action="store_true")

    example = sub.add_parser("example", help="Print an example campaign plan")
    example.add_argument("--compact", action="store_true")

    duo = sub.add_parser("duo", help="Open Codex L1 and Claude L1")
    duo.add_argument("--codex", default="玄武军团")
    duo.add_argument("--claude", default="青龙军团")
    duo.add_argument(
        "--terminal",
        choices=["terminal", "vscode"],
        default="terminal",
        help="terminal opens macOS Terminal.app windows; vscode uses a tmux workspace in the current terminal",
    )
    duo.add_argument("--dry-run", action="store_true")

    dou = sub.add_parser("dou", help="Open Codex L1 in a new Terminal.app window and report current-window Claude command")
    dou.add_argument("--codex", default="玄武军团")
    dou.add_argument("--claude", default="青龙军团")
    dou.add_argument("--dry-run", action="store_true")

    host = sub.add_parser("host", help="Convene legacy single L1 host plus Claude and Codex L2 branch commanders")
    host.add_argument("--provider", "--host-provider", choices=["claude", "codex"], default="claude")
    host.add_argument("--name", default="")
    host.add_argument("--claude-branch", default="implement")
    host.add_argument("--codex-branch", default="audit")
    host.add_argument("--dry-run", action="store_true")
    host.add_argument("--no-attach", action="store_true", help="Launch in background and return instead of entering tmux")
    host.add_argument("--host-only", action="store_true", help="Attach only the L1 host session instead of the L1+L2 split view")

    dual_host = sub.add_parser("dual-host", help="Convene provider-owned Claude and Codex L1 commanders without base L2")
    dual_host.add_argument("--claude-name", default="")
    dual_host.add_argument("--codex-name", default="")
    dual_host.add_argument("--claude-branch", default="implement")
    dual_host.add_argument("--codex-branch", default="audit")
    dual_host.add_argument("--dry-run", action="store_true")
    dual_host.add_argument("--no-attach", action="store_true", help="Launch in background and return instead of attaching Claude L1")
    dual_host.add_argument("--view-session", default="", help=argparse.SUPPRESS)

    claude_host = sub.add_parser("claude-host", help="Launch Claude L1 in the current terminal and Codex L1 in the background")
    claude_host.add_argument("--claude-name", default="")
    claude_host.add_argument("--codex-name", default="")
    claude_host.add_argument("--claude-branch", default="implement")
    claude_host.add_argument("--codex-branch", default="audit")
    claude_host.add_argument("--dry-run", action="store_true")
    claude_host.add_argument("--no-attach", action="store_true", help="Launch both L1 sessions and return instead of attaching Claude L1")

    aicto = sub.add_parser("aicto", help="Show external Hermes AICTO profile status and startup commands")
    aicto.add_argument("--project", default="/Users/feijun/Documents/AICTO", help="Path to the external AICTO Hermes project")
    aicto.add_argument("--name", default="", help=argparse.SUPPRESS)
    aicto.add_argument("--claude-name", default="", help=argparse.SUPPRESS)
    aicto.add_argument("--codex-name", default="", help=argparse.SUPPRESS)
    aicto.add_argument("--claude-branch", default="implement", help=argparse.SUPPRESS)
    aicto.add_argument("--codex-branch", default="audit", help=argparse.SUPPRESS)
    aicto.add_argument("--dry-run", action="store_true")
    aicto.add_argument("--no-attach", action="store_true", help=argparse.SUPPRESS)
    aicto.add_argument("--view-session", default="", help=argparse.SUPPRESS)

    view = sub.add_parser("view", help="Open an interactive tmux split view for dual L1s and active task L2 commanders")
    view.add_argument("--host", default="", help="L1 host commander id; defaults to the newest live host with live L2")
    view.add_argument("--session", default="", help="tmux session name for the view workspace")
    view.add_argument("--fresh", action="store_true", help="Recreate the view session if it already exists")
    view.add_argument("--reuse", action="store_true", help="Reuse an existing view session instead of rebuilding it")
    view.add_argument("--dry-run", action="store_true", help="Print the tmux script without executing it")

    msg = sub.add_parser("msg", help="Send a durable mixed message to one commander")
    msg.add_argument("target")
    msg.add_argument("content")
    msg.add_argument("--from", dest="sender", default="L1-mixed")

    broadcast = sub.add_parser("broadcast", help="Send a durable mixed message to active commanders")
    broadcast.add_argument("content")
    broadcast.add_argument("--from", dest="sender", default="L1-mixed")
    broadcast.add_argument("--l2-only", action="store_true")
    broadcast.add_argument("--parent", default="", help="Only send to branch commanders whose parent matches this L1")

    inbox = sub.add_parser("inbox", help="Read a mixed commander inbox")
    inbox.add_argument("target")
    inbox.add_argument("--tail", type=int, default=20)

    aicto_reports = sub.add_parser("aicto-reports", help="Read queued durable reports for external Hermes AICTO")
    aicto_reports.add_argument("--tail", type=int, default=20)

    report_aicto = sub.add_parser("report-aicto", help="Queue a durable report for external Hermes AICTO")
    report_aicto.add_argument("subject")
    report_aicto.add_argument("summary")
    report_aicto.add_argument("--from", dest="sender", default="Legion Core")
    report_aicto.add_argument("--kind", default="manual-report")

    readiness = sub.add_parser("readiness", help="Check whether direct L2 commanders have reported startup readiness")
    readiness.add_argument("parent")
    readiness.add_argument(
        "--expect",
        action="append",
        default=[],
        help="Expected L2 commander id; may be repeated or comma-separated",
    )
    readiness.add_argument("--wait", action="store_true", help="Wait until all expected L2 commanders report readiness")
    readiness.add_argument("--timeout", type=float, default=180.0, help="Maximum seconds to wait with --wait")
    readiness.add_argument("--interval", type=float, default=5.0, help="Polling interval seconds with --wait")

    mark = sub.add_parser("mark", help="Mark a task status")
    mark.add_argument("task_id")
    mark.add_argument("status", choices=["planned", "launching", "launched", "running", "completed", "blocked", "failed"])

    complete = sub.add_parser("complete", help="Complete a task from its worker result file and process status")
    complete.add_argument("task_id")
    complete.add_argument("result_file")
    complete.add_argument("process_status", type=int)

    mark_commander = sub.add_parser("mark-commander", help="Mark a commander status")
    mark_commander.add_argument("commander_id")
    mark_commander.add_argument("status", choices=["planned", "launching", "commanding", "isolated", "completed", "failed"])

    repair = sub.add_parser(
        "repair",
        help="Unblock dependents of a failed/blocked task; optionally replace the dependency reference",
    )
    repair.add_argument("task_id", help="The failed/blocked task whose dependents need unblocking")
    repair.add_argument(
        "--replacement",
        default="",
        help="Replacement task id; dependents have the original reference rewritten to this id",
    )

    register_commander = sub.add_parser("register-commander", help="Register an external visible commander in mixed registry")
    register_commander.add_argument("provider", choices=["claude", "codex"])
    register_commander.add_argument("commander_id")
    register_commander.add_argument("--session", default="")
    register_commander.add_argument("--status", default="commanding", choices=["planned", "launching", "commanding", "isolated", "completed", "failed"])

    args = parser.parse_args(argv)
    core = LegionCore(Path(args.project_dir), Path(args.legion_home).expanduser() if args.legion_home else None)

    if args.command == "campaign":
        plan = load_plan(args.plan)
        if args.complexity:
            for item in plan:
                item.setdefault("complexity", args.complexity)
        specs = core.deploy_campaign(
            plan,
            commander=args.commander,
            dry_run=args.dry_run,
            corps=args.corps,
            direct=args.direct,
        )
        for spec in specs:
            task = core._task_entry(spec.task_id)
            mode = task.get("status", "planned") if task else "planned"
            print(f"{mode}: {spec.task_id} [{spec.provider}/{spec.role}] {spec.task[:80]}")
        if not args.dry_run:
            print(f"tmux: tmux a -t {core.context.session_name}")
        return 0

    if args.command == "status":
        print(core.status_text())
        return 0

    if args.command == "reconcile":
        core.reconcile_state()
        print(core.status_text())
        return 0

    if args.command == "l1":
        commander = core.start_commander(
            provider=args.provider,
            name=args.name,
            dry_run=args.dry_run,
            attach=not args.no_attach,
            fresh=args.fresh,
        )
        mode = commander.get("_action") or ("planned" if args.dry_run else "launched")
        print(f"{mode}: {commander['id']} [{commander['provider']}] {commander['session']}")
        if args.dry_run:
            print(f"run_dir: {commander['run_dir']}")
        return 0

    if args.command == "example":
        if args.compact:
            print(json.dumps(example_plan(), ensure_ascii=False))
        else:
            print(json.dumps(example_plan(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "duo":
        commands = launch_duo_terminal(
            project_dir=Path(args.project_dir),
            legion_sh=Path(__file__).resolve().with_name("legion.sh"),
            codex_name=args.codex,
            claude_name=args.claude,
            terminal=args.terminal,
            dry_run=args.dry_run,
            legion_home=Path(args.legion_home).expanduser() if args.legion_home else None,
        )
        if args.dry_run:
            for command in commands:
                print(command)
        else:
            print(f"opened {args.terminal}: Codex L1={args.codex}, Claude L1={args.claude}")
        return 0

    if args.command == "dou":
        commands = launch_dou_new_window(
            project_dir=Path(args.project_dir),
            legion_sh=Path(__file__).resolve().with_name("legion.sh"),
            codex_name=args.codex,
            claude_name=args.claude,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            print(f"new_window: {commands['new_window']}")
            print(f"current_window: {commands['current_window']}")
        else:
            print(f"opened Codex L1 new window: {args.codex}")
        return 0

    if args.command == "host":
        convened = core.convene_host(
            host_provider=args.provider,
            host_name=args.name,
            claude_branch=args.claude_branch,
            codex_branch=args.codex_branch,
            dry_run=args.dry_run,
        )
        mode = "planned" if args.dry_run else "launched"
        host = convened["host"]
        print(f"{mode} host: {host['id']} [{host['provider']}] {host['session']}")
        for commander in convened["l2"]:
            print(
                f"{mode} l2: {commander['id']} "
                f"[{commander['provider']}/{commander['branch']}] parent={commander['parent']}"
            )
        if not args.dry_run:
            print("status: legion mixed status")
            if args.host_only:
                print(f"attach: tmux a -t {host['session']}")
            else:
                print(f"view: legion view --host {host['id']}")
            sys.stdout.flush()
            if not args.no_attach:
                if args.host_only:
                    attach_tmux_session(str(host["session"]))
                else:
                    core.open_view(host=str(host["id"]), fresh=True)
        return 0

    if args.command == "dual-host":
        convened = core.convene_dual_host(
            claude_name=args.claude_name,
            codex_name=args.codex_name,
            claude_branch=args.claude_branch,
            codex_branch=args.codex_branch,
            dry_run=args.dry_run,
        )
        for host in convened["hosts"]:
            print(f"{host.get('_action', 'planned')}: {host['id']} [{host['provider']}] {host['session']}")
        for commander in convened["l2"]:
            print(f"L2: {commander['id']} [{commander['provider']}/{commander.get('branch', '?')}] {commander['session']}")
        if args.dry_run or args.no_attach:
            return 0
        print(f"attach claude: tmux a -t {convened['claude_l1']['session']}")
        print(f"codex background: tmux a -t {convened['codex_l1']['session']}")
        sys.stdout.flush()
        attach_tmux_session(str(convened["claude_l1"]["session"]))
        return 0

    if args.command == "claude-host":
        convened = core.convene_dual_host(
            claude_name=args.claude_name,
            codex_name=args.codex_name,
            claude_branch=args.claude_branch,
            codex_branch=args.codex_branch,
            dry_run=args.dry_run,
        )
        for host in convened["hosts"]:
            print(f"{host.get('_action', 'planned')}: {host['id']} [{host['provider']}] {host['session']}")
        if args.dry_run or args.no_attach:
            return 0
        print(f"attach claude: tmux a -t {convened['claude_l1']['session']}")
        print(f"codex background: tmux a -t {convened['codex_l1']['session']}")
        sys.stdout.flush()
        attach_tmux_session(str(convened["claude_l1"]["session"]))
        return 0

    if args.command == "aicto":
        print(external_aicto_status_text(args.project))
        return 0

    if args.command == "view":
        try:
            script = core.open_view(
                host=args.host,
                session=args.session,
                fresh=(not args.reuse) or args.fresh,
                dry_run=args.dry_run,
            )
        except SystemExit as exc:
            if not args.dry_run:
                raise
            print(f"# view unavailable: {exc}")
            return 0
        if args.dry_run:
            print(script, end="")
        return 0

    if args.command == "msg":
        record = core.send_message(args.target, args.content, sender=args.sender)
        route = "tmux+inbox" if record["delivered_tmux"] else "inbox"
        print(f"sent: {record['from']} -> {record['to']} via {route}")
        return 0

    if args.command == "broadcast":
        records = core.broadcast_message(args.content, sender=args.sender, l2_only=args.l2_only, parent=args.parent)
        print(f"broadcast: {len(records)} recipient(s)")
        for record in records:
            route = "tmux+inbox" if record["delivered_tmux"] else "inbox"
            print(f"  {record['to']} via {route}")
        return 0

    if args.command == "inbox":
        print(core.inbox_text(args.target, tail=args.tail))
        return 0

    if args.command == "aicto-reports":
        print(core.aicto_reports_text(tail=args.tail))
        return 0

    if args.command == "report-aicto":
        record = core.queue_aicto_report(
            kind=args.kind,
            subject_id=args.subject,
            summary=args.summary,
            source=args.sender,
            payload={"manual": True},
        )
        print(f"queued: {record['id']} {record['kind']} {record['subject_id']}")
        return 0

    if args.command == "readiness":
        expected = []
        for value in args.expect:
            expected.extend(item.strip() for item in value.split(",") if item.strip())
        if args.wait:
            ok, text = core.wait_readiness(
                args.parent,
                expected=expected,
                timeout=args.timeout,
                interval=args.interval,
            )
            print(text)
            return 0 if ok else 1
        print(core.readiness_text(args.parent, expected=expected))
        return 0

    if args.command == "mark":
        core.mark_task(args.task_id, args.status)
        print(f"{args.task_id}: {args.status}")
        return 0

    if args.command == "complete":
        core.complete_task_from_result(args.task_id, Path(args.result_file), args.process_status)
        task = core._task_entry(args.task_id)
        status = task.get("status", "unknown") if task else "unknown"
        print(f"{args.task_id}: {status}")
        return 0

    if args.command == "mark-commander":
        core.mark_commander(args.commander_id, args.status)
        print(f"{args.commander_id}: {args.status}")
        return 0

    if args.command == "repair":
        repaired = core.repair_dependents(args.task_id, replacement_task_id=args.replacement)
        if repaired:
            print(f"repaired: {args.task_id} -> {','.join(repaired)} replacement={args.replacement or '(none)'}")
        else:
            print(f"repaired: {args.task_id} no dependents to unblock")
        return 0

    if args.command == "register-commander":
        commander = core.register_external_commander(
            provider=args.provider,
            commander_id=args.commander_id,
            session=args.session,
            status=args.status,
        )
        print(f"registered: {commander['id']} [{commander['provider']}] {commander.get('session', '')}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
