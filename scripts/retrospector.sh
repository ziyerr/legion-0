#!/bin/bash
# ============================================================================
# retrospector.sh — release retrospective gate over legacy + mixed evidence.
# ============================================================================
#
# The shell entrypoint intentionally avoids runtime heredocs so `quick` can run
# in read-only/no-temp Codex workers. The Python body is loaded from this file
# itself via python -c and does not require a temporary file.
#
# Usage:
#   retrospector.sh quick   # read-only candidate report
#   retrospector.sh full    # deterministic extraction + writeback
# ============================================================================

set -euo pipefail

PYTHON_BIN="${PYTHON:-python3}"
exec "$PYTHON_BIN" -c 'import pathlib, sys; script = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"); marker = "# __RETROSPECTOR_PYTHON__\n"; code = script.split(marker, 1)[1].rsplit("\n__RETROSPECTOR_PYTHON__", 1)[0]; sys.argv = [sys.argv[1]] + sys.argv[2:]; exec(compile(code, sys.argv[0], "exec"))' "$0" "$@"

# Parsed only by `bash -n`; runtime `quick`/`full` is replaced by exec above
# before this no-op block can require shell heredoc temp handling.
: <<'__RETROSPECTOR_PYTHON__'

# __RETROSPECTOR_PYTHON__
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shlex
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None


TERMINAL_STATUSES = {"completed", "failed", "blocked"}
RESULT_REQUIRED_KEYS = {"status", "summary", "files_touched", "verification", "findings", "risks"}
INPUT_ORDER = ["I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8"]
CURRENT_RELEASE_SOURCES = {"planning_state_md", "legacy_parity_matrix", "patrol"}
HISTORICAL_RELEASE_SOURCES = {"mixed_registry", "events", "inspector", "daemon_evidence", "observations"}


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def short_hash(value: str | bytes, length: int = 16) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()[:length]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except Exception as exc:
        return None, str(exc)


def load_json(path: Path) -> tuple[object | None, str | None]:
    text, err = safe_read_text(path)
    if err:
        return None, err
    try:
        return json.loads(text or ""), None
    except Exception as exc:
        return None, str(exc)


def load_jsonl(path: Path) -> tuple[list[dict], int, str | None]:
    rows: list[dict] = []
    invalid = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                    if isinstance(obj, dict):
                        rows.append(obj)
                    else:
                        invalid += 1
                except Exception:
                    invalid += 1
    except Exception as exc:
        return [], 0, str(exc)
    return rows, invalid, None


def md5_short(value: str) -> str:
    return hashlib.md5(value.encode("utf-8", errors="replace")).hexdigest()[:8]


def newest(paths: list[Path]) -> Path | None:
    existing = [p for p in paths if p.exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def sorted_recent(paths: list[Path]) -> list[Path]:
    existing = [p for p in paths if p.exists()]
    return sorted(existing, key=lambda p: p.stat().st_mtime, reverse=True)


def coerce_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser()


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return slug or "release"


def truthy_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value.strip().lower() in {"1", "true", "yes", "on"}:
            return name
    return ""


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_boundary_paths(cwd: Path) -> tuple[Path, Path, dict]:
    trust_marker = truthy_env("RETROSPECTOR_TRUST_PROJECT_DIR", "RETROSPECTOR_TRUST_BOUNDARY_ENV", "LEGION_TRUST_PROJECT_DIR")
    boundary = {
        "trust_marker": trust_marker,
        "project_dir_source": "cwd",
        "planning_dir_source": "project_default",
        "env_project_dir": os.environ.get("PROJECT_DIR", ""),
        "env_planning_dir": os.environ.get("PLANNING_DIR", ""),
        "ignored_project_dir_env": "",
        "ignored_planning_dir_env": "",
    }
    resolved_cwd = cwd.resolve()
    env_project = coerce_path(os.environ.get("PROJECT_DIR"))
    project_dir = resolved_cwd
    if env_project:
        env_project = env_project.resolve()
        if env_project == resolved_cwd:
            project_dir = env_project
            boundary["project_dir_source"] = "env_matches_cwd"
        elif trust_marker:
            project_dir = env_project
            boundary["project_dir_source"] = f"trusted_env:{trust_marker}"
        else:
            boundary["project_dir_source"] = "cwd_ignored_stale_env"
            boundary["ignored_project_dir_env"] = str(env_project)

    default_planning = (project_dir / ".planning").resolve()
    planning_dir = default_planning
    env_planning = coerce_path(os.environ.get("PLANNING_DIR"))
    if env_planning:
        env_planning = env_planning.resolve()
        if env_planning == default_planning or path_is_relative_to(env_planning, project_dir):
            planning_dir = env_planning
            boundary["planning_dir_source"] = "env_inside_project"
        elif trust_marker:
            planning_dir = env_planning
            boundary["planning_dir_source"] = f"trusted_env:{trust_marker}"
        else:
            boundary["planning_dir_source"] = "project_default_ignored_stale_env"
            boundary["ignored_planning_dir_env"] = str(env_planning)

    boundary["project_dir"] = str(project_dir)
    boundary["planning_dir"] = str(planning_dir)
    return project_dir, planning_dir, boundary


def runtime_matches_project(mixed_dir: Path, project_dir: Path) -> bool:
    mixed_dir = mixed_dir.resolve()
    project_dir = project_dir.resolve()
    if mixed_dir.name == "mixed" and mixed_dir.parent.name == md5_short(str(project_dir)):
        return True

    registry_path = mixed_dir / "mixed-registry.json"
    if not registry_path.exists():
        return False
    data, err = load_json(registry_path)
    if err or not isinstance(data, dict):
        return False

    candidates: list[str] = []
    project = data.get("project")
    if isinstance(project, dict):
        for key in ("path", "project_dir", "root"):
            value = project.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
    for collection_name in ("commanders", "tasks"):
        collection = data.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection[:25]:
            if isinstance(item, dict):
                value = item.get("project")
                if isinstance(value, str) and value:
                    candidates.append(value)
    for candidate in candidates:
        try:
            if Path(candidate).expanduser().resolve() == project_dir:
                return True
        except Exception:
            continue
    return False


class Retrospector:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.write_mode = mode == "full"
        self.cwd = Path.cwd()
        self.project_dir, self.planning_dir, self.boundary = resolve_boundary_paths(self.cwd)
        self.script_path = Path(sys.argv[0]).resolve()
        self.timestamp = iso_now()
        seed = f"{self.timestamp}|{self.cwd}|{self.mode}|{uuid.uuid4().hex[:8]}"
        self.run_id = os.environ.get("RETROSPECTIVE_RUN_ID") or f"retro-{self.timestamp.replace(':', '').replace('-', '')}-{short_hash(seed, 8)}"
        self.legion_dir: Path | None = None
        self.mixed_dir: Path | None = None
        self.registry: dict = {}
        self.tasks: list[dict] = []
        self.commanders: list[dict] = []
        self.events: list[dict] = []
        self.failed_or_blocked: list[dict] = []
        self.run_results: list[dict] = []
        self.input_records: dict[str, dict] = {}
        self.candidate_seq = 0
        self.report: dict = {
            "run": {
                "id": self.run_id,
                "mode": self.mode,
                "timestamp": self.timestamp,
                "command": shlex.join(["bash", str(self.script_path), *sys.argv[1:]]),
                "cwd": str(self.cwd),
                "project_dir": str(self.project_dir),
                "planning_dir": str(self.planning_dir),
                "project_boundary": self.boundary,
                "script_hash": "",
            },
            "classification": "zero-candidates",
            "verdict": "pass",
            "sources": {},
            "source_counts": {},
            "input_accounting": {},
            "patterns": [],
            "candidates": [],
            "blockers": [],
            "watch": [],
            "release_gate": {
                "verdict": "pass",
                "blocks_release": False,
                "current_blockers": [],
                "current_watch": [],
                "historical_learning_candidate_count": 0,
                "release_blocking_candidate_count": 0,
            },
        }
        try:
            self.report["run"]["script_hash"] = file_hash(self.script_path)
        except Exception:
            self.report["run"]["script_hash"] = ""

    def discover_runtime(self) -> None:
        env_legion = coerce_path(os.environ.get("LEGION_DIR"))
        env_mixed = coerce_path(os.environ.get("MIXED_DIR"))
        trust_marker = self.boundary.get("trust_marker", "")
        project_hash = md5_short(str(self.project_dir))
        if env_mixed and env_mixed.is_dir():
            env_mixed = env_mixed.resolve()
            if trust_marker or runtime_matches_project(env_mixed, self.project_dir):
                self.mixed_dir = env_mixed
                self.boundary["mixed_dir_source"] = "env_trusted" if trust_marker else "env_matches_project"
                if self.mixed_dir.name == "mixed":
                    self.legion_dir = self.mixed_dir.parent.resolve()
            else:
                self.boundary["ignored_mixed_dir_env"] = str(env_mixed)
        if env_legion and env_legion.is_dir():
            env_legion = env_legion.resolve()
            env_legion_mixed = (env_legion / "mixed").resolve()
            if trust_marker or env_legion.name == project_hash or runtime_matches_project(env_legion_mixed, self.project_dir):
                self.legion_dir = env_legion
                self.boundary["legion_dir_source"] = "env_trusted" if trust_marker else "env_matches_project"
                if not self.mixed_dir and env_legion_mixed.is_dir():
                    self.mixed_dir = env_legion_mixed
                    self.boundary["mixed_dir_source"] = "legion_env_matches_project"
            else:
                self.boundary["ignored_legion_dir_env"] = str(env_legion)

        search_roots = [
            Path.home() / ".claude" / "legion",
            Path("/tmp/claude-legion"),
        ]
        mixed_candidates: list[Path] = []
        for root in search_roots:
            direct = root / project_hash / "mixed"
            if (direct / "mixed-registry.json").exists():
                mixed_candidates.append(direct)
            if root.exists():
                for found in root.glob("*/mixed/mixed-registry.json"):
                    candidate = found.parent
                    if runtime_matches_project(candidate, self.project_dir):
                        mixed_candidates.append(candidate)
                    else:
                        self.boundary["ignored_runtime_candidates"] = int(self.boundary.get("ignored_runtime_candidates", 0)) + 1
        if not self.mixed_dir:
            chosen = newest(mixed_candidates)
            if chosen:
                self.mixed_dir = chosen.resolve()
                self.boundary["mixed_dir_source"] = "project_hash_search"
        if not self.legion_dir and self.mixed_dir and self.mixed_dir.name == "mixed":
            self.legion_dir = self.mixed_dir.parent.resolve()
            self.boundary["legion_dir_source"] = self.boundary.get("legion_dir_source") or "mixed_parent"
        if not self.legion_dir:
            direct = Path.home() / ".claude" / "legion" / project_hash
            self.legion_dir = direct.resolve()
            self.boundary["legion_dir_source"] = self.boundary.get("legion_dir_source") or "project_hash_default"

        self.report["run"]["legion_dir"] = str(self.legion_dir) if self.legion_dir else ""
        self.report["run"]["mixed_dir"] = str(self.mixed_dir) if self.mixed_dir else ""
        self.report["run"]["project_boundary"] = self.boundary

    def add_blocker(self, input_id: str, code: str, message: str, path: str = "", owner: str = "T21") -> None:
        entry = {"input": input_id, "code": code, "message": message, "path": path, "owner": owner}
        self.report["blockers"].append(entry)

    def add_watch(self, input_id: str, code: str, message: str, path: str = "", owner: str = "T20") -> None:
        entry = {"input": input_id, "code": code, "message": message, "path": path, "owner": owner}
        self.report["watch"].append(entry)

    def add_input(
        self,
        input_id: str,
        name: str,
        paths: list[str],
        status: str,
        count: int = 0,
        details: dict | None = None,
        error: str = "",
    ) -> None:
        self.input_records[input_id] = {
            "input": input_id,
            "name": name,
            "paths": paths,
            "status": status,
            "count": count,
            "details": details or {},
            "error": error,
        }

    def add_pattern(self, pattern_type: str, data, description: str = "") -> None:
        item = {"type": pattern_type, "data": data}
        if description:
            item["description"] = description
        self.report["patterns"].append(item)

    def add_candidate(
        self,
        source: str,
        candidate_type: str,
        trigger: str,
        content: str,
        *,
        input_id: str,
        severity: str = "WATCH",
        extraction_type: str = "tactic",
        pointer: dict | None = None,
    ) -> None:
        self.candidate_seq += 1
        self.report["candidates"].append({
            "id": f"C{self.candidate_seq:04d}",
            "source": source,
            "type": candidate_type,
            "trigger": trigger,
            "content": content,
            "severity": severity,
            "extraction_type": extraction_type,
            "source_pointer": {"input": input_id, **(pointer or {})},
        })

    def source_count(self, key: str, value: int) -> None:
        self.report["source_counts"][key] = value

    def source_value(self, key: str, value) -> None:
        self.report["sources"][key] = value

    def read_observations(self) -> None:
        obs_path = coerce_path(os.environ.get("OBS_FILE")) or (Path.home() / ".claude" / "homunculus" / "observations.jsonl")
        if not obs_path.exists():
            self.source_value("observations", 0)
            self.source_count("observations", 0)
            self.add_watch("I5", "missing_observations", "observations.jsonl is missing; hook observation evidence is absent", str(obs_path), "T22")
            self.add_candidate(
                "observations",
                "protocol-evolution",
                "missing_observations",
                "Hook observations were not found; release synthesis must cite a replacement source or keep retrospective WATCH.",
                input_id="I5",
                severity="WATCH",
                extraction_type="protocol-evolution",
                pointer={"path": str(obs_path)},
            )
            return
        observations, invalid, err = load_jsonl(obs_path)
        if err:
            self.source_value("observations", 0)
            self.source_count("observations", 0)
            self.add_blocker("I5", "unreadable_observations", err, str(obs_path), "T22")
            return
        self.source_value("observations", len(observations))
        self.source_count("observations", len(observations))
        file_counter: Counter[str] = Counter()
        tool_counter: Counter[str] = Counter()
        team_counter: Counter[str] = Counter()
        for obs in observations:
            f = str(obs.get("file", ""))
            if "/" in f:
                for p in f.split():
                    if "/" in p and not p.startswith("#") and not p.startswith("-"):
                        file_counter[p[:120]] += 1
                        break
            tool_counter[str(obs.get("tool", "?"))] += 1
            team_counter[str(obs.get("team", "?"))] += 1
        hot_files = [{"file": f, "count": c} for f, c in file_counter.most_common(10) if c >= 3]
        if hot_files:
            self.add_pattern("hot_files", hot_files, "频繁修改的文件（可能不稳定或职责过重）")
        if tool_counter:
            self.add_pattern("tool_usage", dict(tool_counter.most_common()))
        if team_counter:
            self.add_pattern("team_activity", dict(team_counter.most_common()))
        if invalid:
            self.add_candidate(
                "observations",
                "incident",
                "invalid_jsonl_rows",
                f"observations.jsonl contains {invalid} invalid JSONL rows.",
                input_id="I5",
                severity="WATCH",
                extraction_type="incident",
                pointer={"path": str(obs_path)},
            )

    def discover_inspector_file(self) -> Path | None:
        env = coerce_path(os.environ.get("INSPECTOR_FILE"))
        if env and env.exists():
            return env.resolve()
        if self.legion_dir:
            project_file = self.legion_dir / "inspector_memory.json"
            return project_file.resolve() if project_file.exists() else None
        candidates: list[Path] = []
        for root in [Path.home() / ".claude" / "legion", Path("/tmp/claude-legion")]:
            if root.exists():
                candidates.extend(root.glob("*/inspector_memory.json"))
        return newest(candidates)

    def discover_daemon_file(self) -> Path | None:
        env = coerce_path(os.environ.get("DAEMON_EVIDENCE_FILE"))
        if env and env.exists():
            return env.resolve()
        if self.legion_dir:
            project_file = self.legion_dir / "daemon_evidence.jsonl"
            return project_file.resolve() if project_file.exists() else None
        candidates: list[Path] = []
        for root in [Path.home() / ".claude" / "legion", Path("/tmp/claude-legion")]:
            if root.exists():
                candidates.extend(root.glob("*/daemon_evidence.jsonl"))
        return newest(candidates)

    def read_inspector_and_daemon(self) -> None:
        inspector_file = self.discover_inspector_file()
        inspector_count = 0
        inspector_path = ""
        if inspector_file and inspector_file.exists():
            inspector_path = str(inspector_file)
            inspector, err = load_json(inspector_file)
            if err:
                self.add_blocker("I5", "unreadable_inspector_memory", err, str(inspector_file), "T22")
            elif isinstance(inspector, dict):
                judgments = inspector.get("judgments", [])
                judgments = judgments if isinstance(judgments, list) else []
                inspector_count = len(judgments)
                reasons: Counter[str] = Counter()
                for judgment in judgments:
                    if isinstance(judgment, dict):
                        reason = str(judgment.get("reason") or "")[:120]
                        if reason:
                            reasons[reason] += 1
                repeated = [{"reason": r, "count": c} for r, c in reasons.items() if c >= 2]
                if repeated:
                    self.add_pattern("repeated_judgments", repeated, "重复出现的纠察判决（候选→自动规则）")
                    for item in repeated:
                        self.add_candidate(
                            "inspector",
                            "feedback",
                            f"判决重复 {item['count']} 次",
                            item["reason"],
                            input_id="I5",
                            severity="WATCH",
                            extraction_type="learning",
                            pointer={"path": str(inspector_file)},
                        )
        else:
            attempted = str(self.legion_dir / "inspector_memory.json") if self.legion_dir else ""
            self.add_watch("I5", "missing_inspector_memory", "inspector_memory.json is missing; adaptive inspector evidence is absent", attempted, "T22")
            self.add_candidate(
                "inspector",
                "protocol-evolution",
                "missing_inspector_memory",
                "Inspector memory was not found; release synthesis must cite a replacement source or keep retrospective WATCH.",
                input_id="I5",
                severity="WATCH",
                extraction_type="protocol-evolution",
                pointer={"path": attempted},
            )
        self.source_value("inspector_judgments", inspector_count)
        self.source_count("inspector_judgments", inspector_count)

        daemon_file = self.discover_daemon_file()
        daemon_count = 0
        daemon_path = ""
        if daemon_file and daemon_file.exists():
            daemon_path = str(daemon_file)
            rows, invalid, err = load_jsonl(daemon_file)
            if err:
                self.add_blocker("I5", "unreadable_daemon_evidence", err, str(daemon_file), "T22")
            else:
                daemon_count = len(rows)
                kind_counter = Counter(str(row.get("kind", "?")) for row in rows)
                self.add_pattern("daemon_evidence_kinds", dict(kind_counter.most_common(20)), "daemon_evidence.jsonl kind distribution")
                for index, row in enumerate(rows[-30:], start=max(len(rows) - 29, 1)):
                    kind = str(row.get("kind", ""))
                    if kind in {"patrol_warning", "patrol_violation", "retrospective_started", "retrospective_artifact_written", "mixed_commander_offline", "observation_pattern_detected", "observation_tactic_suggested"}:
                        pointer = {
                            "path": str(daemon_file),
                            "line": index,
                            "record_hash": short_hash(json.dumps(row, ensure_ascii=False, sort_keys=True)),
                            "kind": kind,
                        }
                        self.add_candidate(
                            "daemon_evidence",
                            "learning",
                            kind,
                            json.dumps({k: row.get(k) for k in sorted(row) if k not in {"screen_excerpt"}}, ensure_ascii=False)[:500],
                            input_id="I5",
                            severity="WATCH" if "warning" in kind or "offline" in kind else "INFO",
                            extraction_type="learning",
                            pointer=pointer,
                        )
                if invalid:
                    self.add_candidate(
                        "daemon_evidence",
                        "incident",
                        "invalid_jsonl_rows",
                        f"daemon_evidence.jsonl contains {invalid} invalid JSONL rows.",
                        input_id="I5",
                        severity="WATCH",
                        extraction_type="incident",
                        pointer={"path": str(daemon_file)},
                    )
        else:
            attempted = str(self.legion_dir / "daemon_evidence.jsonl") if self.legion_dir else ""
            self.add_watch("I5", "missing_daemon_evidence", "daemon_evidence.jsonl is missing; docs require daemon evidence or an explicit WATCH.", attempted, "T22")
            self.add_candidate(
                "daemon_evidence",
                "protocol-evolution",
                "missing_daemon_evidence",
                "LEGION_DIR/daemon_evidence.jsonl was not found. This is an explicit retrospective WATCH until release synthesis cites a stronger mixed-native replacement.",
                input_id="I5",
                severity="WATCH",
                extraction_type="protocol-evolution",
                pointer={"path": attempted},
            )
        self.source_value("daemon_evidence_log", daemon_path)
        self.source_value("daemon_evidence_count", daemon_count)
        self.source_count("daemon_evidence", daemon_count)

        status = "opened"
        paths = [p for p in [inspector_path, daemon_path] if p]
        if not paths:
            status = "watch"
        elif not daemon_path:
            status = "watch"
        self.add_input("I5", "Inspector / daemon memory", paths, status, inspector_count + daemon_count, {
            "inspector_judgments": inspector_count,
            "daemon_evidence": daemon_count,
        })

    def read_project_truth(self) -> None:
        paths = {
            "STATE.md": self.planning_dir / "STATE.md",
            "REQUIREMENTS.md": self.planning_dir / "REQUIREMENTS.md",
            "DECISIONS.md": self.planning_dir / "DECISIONS.md",
        }
        opened: list[str] = []
        state_blockers: list[str] = []
        missing: list[str] = []
        for name, path in paths.items():
            if not path.exists():
                missing.append(str(path))
                continue
            text, err = safe_read_text(path)
            if err:
                self.add_blocker("I6", f"unreadable_{name}", err, str(path), "T21")
                continue
            opened.append(str(path))
            if name == "STATE.md":
                for line in (text or "").splitlines():
                    stripped = line.lstrip("- ").strip()
                    lowered = stripped.lower()
                    if (
                        stripped.startswith("Runtime blocker")
                        or stripped.startswith("Residual risk")
                        or stripped.startswith("Reversal")
                        or lowered.startswith("blocker")
                        or lowered.startswith("known risk")
                        or "release-gate watch" in lowered
                        or "watch item" in lowered
                    ):
                        state_blockers.append(stripped[:260])
        if missing:
            for path in missing:
                self.add_blocker("I6", "missing_project_truth", "required project truth file is missing", path, "T21")
        if state_blockers:
            self.add_pattern(
                "planning_state_md_blockers",
                [{"line": line} for line in state_blockers[:30]],
                ".planning/STATE.md 残留风险 / blocker / reversal",
            )
            for line in state_blockers[:30]:
                self.add_candidate(
                    "planning_state_md",
                    "tactic",
                    "planning_blocker_or_reversal",
                    line,
                    input_id="I6",
                    severity="WATCH",
                    extraction_type="incident",
                    pointer={"path": str(paths["STATE.md"])},
                )
        self.source_value("state_failed_attempts", 0)
        self.source_value("state_md_blockers", len(state_blockers))
        self.source_count("state_md_blockers", len(state_blockers))
        self.add_input("I6", "Project truth state", opened, "opened" if not missing else "blocked", len(opened), {
            "state_md_blockers": len(state_blockers),
            "missing": missing,
        })

    def read_registry(self) -> None:
        registry_path = self.mixed_dir / "mixed-registry.json" if self.mixed_dir else None
        self.source_value("mixed_registry", str(registry_path) if registry_path and registry_path.exists() else "")
        if not registry_path or not registry_path.exists():
            attempted = str(registry_path) if registry_path else ""
            self.source_value("mixed_registry_tasks", 0)
            self.source_value("mixed_registry_commanders", 0)
            self.source_count("mixed_registry_tasks", 0)
            self.source_count("mixed_registry_commanders", 0)
            self.add_blocker("I1", "missing_mixed_registry", "mixed-registry.json is missing", attempted, "T20")
            self.add_input("I1", "Mixed registry snapshot", [attempted] if attempted else [], "blocked", 0)
            return
        data, err = load_json(registry_path)
        if err or not isinstance(data, dict):
            self.add_blocker("I1", "unreadable_mixed_registry", err or "registry is not a JSON object", str(registry_path), "T20")
            self.add_input("I1", "Mixed registry snapshot", [str(registry_path)], "blocked", 0, error=err or "not object")
            return
        self.registry = data
        self.tasks = data.get("tasks", []) if isinstance(data.get("tasks", []), list) else []
        self.commanders = data.get("commanders", []) if isinstance(data.get("commanders", []), list) else []
        self.source_value("mixed_registry_tasks", len(self.tasks))
        self.source_value("mixed_registry_commanders", len(self.commanders))
        self.source_count("mixed_registry_tasks", len(self.tasks))
        self.source_count("mixed_registry_commanders", len(self.commanders))

        status_counter = Counter(str(t.get("status", "?")) for t in self.tasks)
        provider_counter = Counter(str(t.get("provider", "?")) for t in self.tasks)
        role_counter = Counter(str(t.get("role", "?")) for t in self.tasks)
        scope_hot: Counter[str] = Counter()
        for task in self.tasks:
            for scope in task.get("scope") or []:
                if isinstance(scope, str) and scope:
                    scope_hot[scope] += 1
            if task.get("status") in {"failed", "blocked"}:
                fb = {
                    "id": task.get("id", "?"),
                    "status": task.get("status"),
                    "role": task.get("role", "?"),
                    "provider": task.get("provider", "?"),
                    "commander": task.get("commander", "?"),
                    "blocked_reason": str(task.get("blocked_reason") or task.get("failure") or "")[:180],
                    "task": str(task.get("task") or "")[:180],
                    "run_dir": task.get("run_dir") or "",
                    "depends_on": task.get("depends_on") or [],
                    "updated": task.get("updated") or "",
                }
                self.failed_or_blocked.append(fb)
        self.add_pattern("registry_status_distribution", dict(status_counter.most_common()))
        if provider_counter:
            self.add_pattern("registry_provider_split", dict(provider_counter.most_common()))
        if role_counter:
            self.add_pattern("registry_role_split", dict(role_counter.most_common()))
        hot_scopes = [{"path": p, "count": c} for p, c in scope_hot.most_common(15) if c >= 2]
        if hot_scopes:
            self.add_pattern("registry_hot_scopes", hot_scopes, "多任务声明的同一文件 scope（潜在 scope 冲突）")
        if self.failed_or_blocked:
            self.add_pattern("registry_failed_or_blocked", self.failed_or_blocked[:40], "mixed registry 中 failed / blocked 的任务")
            for fb in self.failed_or_blocked:
                content = f"[{fb['status']} {fb['role']}/{fb['provider']}] {fb['id']}"
                if fb["blocked_reason"]:
                    content += f" — {fb['blocked_reason']}"
                elif fb["task"]:
                    content += f" — {fb['task']}"
                self.add_candidate(
                    "mixed_registry",
                    "tactic",
                    f"task_{fb['status']}",
                    content,
                    input_id="I4",
                    severity="WATCH",
                    extraction_type="incident",
                    pointer={"path": str(registry_path), "task_id": str(fb["id"])},
                )
        self.add_input("I1", "Mixed registry snapshot", [str(registry_path)], "opened", len(self.tasks), {
            "tasks": len(self.tasks),
            "commanders": len(self.commanders),
            "status_distribution": dict(status_counter.most_common()),
        })
        self.add_input("I4", "Failed and blocked task records", [str(registry_path)], "opened", len(self.failed_or_blocked), {
            "failed_or_blocked": len(self.failed_or_blocked),
        })

    def read_events(self) -> None:
        events_path = self.mixed_dir / "events.jsonl" if self.mixed_dir else None
        self.source_value("events_log", str(events_path) if events_path and events_path.exists() else "")
        if not events_path or not events_path.exists():
            attempted = str(events_path) if events_path else ""
            self.source_value("events_count", 0)
            self.source_count("events_count", 0)
            self.add_blocker("I2", "missing_events_log", "events.jsonl is missing", attempted, "T20")
            self.add_input("I2", "Event log", [attempted] if attempted else [], "blocked", 0)
            return
        events, invalid, err = load_jsonl(events_path)
        if err:
            self.add_blocker("I2", "unreadable_events_log", err, str(events_path), "T20")
            self.add_input("I2", "Event log", [str(events_path)], "blocked", 0, error=err)
            return
        self.events = events
        self.source_value("events_count", len(events))
        self.source_count("events_count", len(events))
        event_type_counter: Counter[str] = Counter()
        failure_events = []
        repair_events = []
        delivery_failures = []
        gate_events = []
        for line_number, event in enumerate(events, start=1):
            ev = str(event.get("event", "?"))
            event_type_counter[ev] += 1
            payload = event.get("payload") or {}
            event_hash = short_hash(json.dumps(event, ensure_ascii=False, sort_keys=True))
            pointer = {"path": str(events_path), "line": line_number, "event_hash": event_hash}
            if ev in {"task_failed", "commander_failed", "task_blocked"}:
                item = {"ts": event.get("ts", "?"), "event": ev, "task_id": event.get("task_id", "?"), "payload": payload, "pointer": pointer}
                failure_events.append(item)
            elif ev in {"task_status_repaired", "task_repair"}:
                repair_events.append({"ts": event.get("ts", "?"), "task_id": event.get("task_id", "?"), "payload": payload, "pointer": pointer})
            elif ev == "message_sent" and isinstance(payload, dict) and payload.get("delivered_tmux") is False:
                delivery_failures.append({"ts": event.get("ts", "?"), "task_id": event.get("task_id", "?"), "payload": payload, "pointer": pointer})
            if any(key in ev.lower() for key in ("gate", "patrol", "blocked", "approve", "deny", "remediat")):
                gate_events.append({"ts": event.get("ts", "?"), "event": ev, "task_id": event.get("task_id", "?"), "pointer": pointer})
        self.add_pattern("events_type_distribution", dict(event_type_counter.most_common(20)))
        if failure_events:
            self.add_pattern("events_failures", failure_events[-30:], "事件流中的 failed / blocked")
            for fe in failure_events[-30:]:
                payload = fe["payload"] if isinstance(fe["payload"], dict) else {}
                reason = payload.get("reason") or payload.get("error") or payload.get("blocked_reason") or payload.get("failure") or ""
                content = f"[{fe['event']}] {fe['task_id']}"
                if reason:
                    content += f" — {str(reason)[:180]}"
                self.add_candidate(
                    "events",
                    "tactic",
                    str(fe["event"]),
                    content,
                    input_id="I2",
                    severity="WATCH",
                    extraction_type="incident",
                    pointer=fe["pointer"],
                )
        if repair_events:
            self.add_pattern("events_repairs", repair_events[-15:], "task repair / status repair events")
        if delivery_failures:
            self.add_pattern("events_tmux_delivery_failures", delivery_failures[-15:], "inbox 已持久化但 tmux 通知失败的消息")
            for de in delivery_failures[-15:]:
                self.add_candidate(
                    "events",
                    "tactic",
                    "tmux_delivery_failed",
                    f"message_sent delivered_tmux=false target={de.get('task_id','?')}",
                    input_id="I2",
                    severity="WATCH",
                    extraction_type="incident",
                    pointer=de["pointer"],
                )
        if invalid:
            self.add_candidate(
                "events",
                "incident",
                "invalid_jsonl_rows",
                f"events.jsonl contains {invalid} invalid JSONL rows.",
                input_id="I2",
                severity="FAIL",
                extraction_type="incident",
                pointer={"path": str(events_path)},
            )
        self.add_input("I2", "Event log", [str(events_path)], "opened", len(events), {
            "invalid_rows": invalid,
            "failure_events": len(failure_events),
            "gate_events": len(gate_events),
            "has_release_grade_ids": any("event_id" in e or "schema_version" in e or "correlation_id" in e for e in events),
        })

    def collect_run_result(self, task: dict) -> None:
        task_id = str(task.get("id", "?"))
        status = str(task.get("status", "?"))
        run_dir_value = str(task.get("run_dir") or "")
        run_dir = Path(run_dir_value).expanduser() if run_dir_value else None
        if (not run_dir or not run_dir.exists()) and self.mixed_dir:
            fallback = self.mixed_dir / "runs" / task_id
            if fallback.exists():
                run_dir = fallback
        result_path = run_dir / "result.md" if run_dir else Path("")
        worker_log = run_dir / "worker.log" if run_dir else Path("")
        record = {
            "task_id": task_id,
            "status": status,
            "run_dir": str(run_dir) if run_dir else run_dir_value,
            "result_path": str(result_path) if run_dir else "",
            "result_size": 0,
            "result_hash": "",
            "result_excerpt": "",
            "worker_log_size": 0,
            "result_present": False,
            "json_valid": False,
            "schema_valid": False,
            "result_status": "",
        }
        if worker_log.exists():
            try:
                record["worker_log_size"] = worker_log.stat().st_size
            except Exception:
                pass
        content = ""
        if result_path and result_path.exists():
            text, err = safe_read_text(result_path)
            if err:
                self.add_candidate(
                    "run_results",
                    "incident",
                    "unreadable_result_md",
                    f"{task_id} result.md is unreadable: {err}",
                    input_id="I3",
                    severity="FAIL",
                    extraction_type="incident",
                    pointer={"path": str(result_path), "task_id": task_id},
                )
            else:
                content = text or ""
                record["result_size"] = len(content)
                record["result_hash"] = short_hash(content)
                lines = content.strip().splitlines()
                record["result_excerpt"] = "\n".join(lines[:20]).strip()[:700]
                record["result_present"] = bool(content.strip())
                if content.strip():
                    try:
                        parsed = json.loads(content)
                        record["json_valid"] = isinstance(parsed, dict)
                        if isinstance(parsed, dict):
                            record["result_status"] = str(parsed.get("status", ""))
                            record["schema_valid"] = RESULT_REQUIRED_KEYS.issubset(parsed.keys())
                    except Exception:
                        record["json_valid"] = False
        self.run_results.append(record)
        pointer = {"path": record["result_path"], "task_id": task_id, "run_dir": record["run_dir"], "task_status": status}
        if not record["result_present"]:
            self.add_candidate(
                "run_results",
                "tactic",
                f"missing_result_md_{status}",
                f"{task_id} status={status} but result.md is missing or empty (run_dir={record['run_dir']})",
                input_id="I3",
                severity="FAIL" if status == "completed" else "WATCH",
                extraction_type="incident",
                pointer=pointer,
            )
        elif not record["json_valid"]:
            self.add_candidate(
                "run_results",
                "tactic",
                "schema_invalid_result_md",
                f"{task_id} result.md is not strict whole-file JSON.",
                input_id="I3",
                severity="FAIL",
                extraction_type="incident",
                pointer={**pointer, "result_hash": record["result_hash"]},
            )
        elif not record["schema_valid"]:
            self.add_candidate(
                "run_results",
                "tactic",
                "schema_missing_required_keys",
                f"{task_id} result.md JSON is missing required keys {sorted(RESULT_REQUIRED_KEYS)}.",
                input_id="I3",
                severity="FAIL",
                extraction_type="incident",
                pointer={**pointer, "result_hash": record["result_hash"]},
            )
        if record["result_status"] and record["result_status"] != "completed":
            self.add_candidate(
                "run_results",
                "tactic",
                f"result_status_{record['result_status']}",
                f"{task_id} worker result status={record['result_status']} requires learning/blocker extraction.",
                input_id="I3",
                severity="WATCH",
                extraction_type="incident",
                pointer={**pointer, "result_hash": record["result_hash"]},
            )

    def read_run_results(self) -> None:
        terminal = [task for task in self.tasks if str(task.get("status", "")) in TERMINAL_STATUSES]
        for task in terminal:
            self.collect_run_result(task)
        parseable = sum(1 for rr in self.run_results if rr["json_valid"])
        present = sum(1 for rr in self.run_results if rr["result_present"])
        self.source_value("run_results", len(self.run_results))
        self.source_count("run_results", len(self.run_results))
        self.source_count("run_results_present", present)
        self.source_count("run_results_parseable", parseable)
        if self.run_results:
            self.add_pattern("run_results", self.run_results[:60], "terminal tasks result.md evidence")
        status = "opened" if self.tasks else "blocked"
        if not self.tasks:
            self.add_blocker("I3", "no_registry_tasks_for_run_results", "cannot account for run results without registry tasks", "", "T20")
        self.add_input("I3", "Worker run results", [rr["result_path"] for rr in self.run_results if rr.get("result_path")][:80], status, len(self.run_results), {
            "terminal_tasks": len(terminal),
            "present": present,
            "parseable": parseable,
        })

    def read_patrol_evidence(self) -> None:
        patrol_script = self.project_dir / "scripts" / "legion-patrol.sh"
        paths: list[str] = []
        if patrol_script.exists():
            paths.append(str(patrol_script))
        else:
            self.add_blocker("I7", "missing_patrol_script", "scripts/legion-patrol.sh is missing", str(patrol_script), "T21")

        notices = []
        gates = []
        if self.legion_dir:
            patrol_dir = self.legion_dir / "patrol"
            if patrol_dir.exists():
                for path in sorted(patrol_dir.glob("notice-*.json")):
                    paths.append(str(path))
                    data, err = load_json(path)
                    if err or not isinstance(data, dict):
                        self.add_candidate(
                            "patrol",
                            "incident",
                            "unreadable_notice",
                            f"patrol notice unreadable: {err}",
                            input_id="I7",
                            severity="FAIL",
                            extraction_type="incident",
                            pointer={"path": str(path)},
                        )
                        continue
                    notices.append(data)
                    if data.get("status") not in {"approved", "cleared", "released"}:
                        self.add_candidate(
                            "patrol",
                            "incident",
                            "unresolved_patrol_notice",
                            f"patrol notice {data.get('team_id','?')} status={data.get('status','?')} reason={data.get('reason','')}",
                            input_id="I7",
                            severity="WATCH",
                            extraction_type="incident",
                            pointer={"path": str(path), "team_id": str(data.get("team_id", ""))},
                        )
            for path_text in glob.glob(str(self.legion_dir / "team-*" / "gate.json")):
                path = Path(path_text)
                paths.append(str(path))
                data, err = load_json(path)
                if err or not isinstance(data, dict):
                    self.add_candidate(
                        "patrol",
                        "incident",
                        "unreadable_gate",
                        f"gate.json unreadable: {err}",
                        input_id="I7",
                        severity="FAIL",
                        extraction_type="incident",
                        pointer={"path": str(path)},
                    )
                    continue
                gates.append(data)
                if data.get("status") == "blocked":
                    self.add_candidate(
                        "patrol",
                        "incident",
                        "blocked_gate",
                        f"release gate blocked: {data.get('reason','')}",
                        input_id="I7",
                        severity="FAIL",
                        extraction_type="incident",
                        pointer={"path": str(path)},
                    )
        gate_event_count = 0
        for event in self.events:
            ev = str(event.get("event", "")).lower()
            if any(key in ev for key in ("patrol", "gate", "blocked", "approve", "deny", "remediat")):
                gate_event_count += 1
        self.source_count("patrol_notices", len(notices))
        self.source_count("gate_files", len(gates))
        self.source_count("patrol_gate_events", gate_event_count)
        self.add_pattern("patrol_release_gate_summary", {
            "notices": len(notices),
            "gate_files": len(gates),
            "related_mixed_events": gate_event_count,
        })
        self.add_input("I7", "Patrol evidence", paths, "opened" if patrol_script.exists() else "blocked", len(paths), {
            "notices": len(notices),
            "gate_files": len(gates),
            "related_mixed_events": gate_event_count,
            "status_command": "not executed by retrospector; non-mutating source scan used",
        })

    def read_parity_matrix(self) -> None:
        matrix_path = self.planning_dir / "communication-upgrade" / "04-LEGACY-PARITY-MATRIX.md"
        if not matrix_path.exists():
            self.add_blocker("I8", "missing_legacy_parity_matrix", "04-LEGACY-PARITY-MATRIX.md is missing", str(matrix_path), "T23")
            self.add_input("I8", "Legacy parity matrix", [str(matrix_path)], "blocked", 0)
            return
        text, err = safe_read_text(matrix_path)
        if err:
            self.add_blocker("I8", "unreadable_legacy_parity_matrix", err, str(matrix_path), "T23")
            self.add_input("I8", "Legacy parity matrix", [str(matrix_path)], "blocked", 0, error=err)
            return
        watch_rows = []
        blocked_rows = []
        for line_number, line in enumerate((text or "").splitlines(), start=1):
            if not line.startswith("|") or "---" in line:
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            if cells[0].isdigit() and len(cells) >= 5:
                status_cell = cells[4]
            elif cells[0].startswith("B") and len(cells) >= 2:
                status_cell = cells[1]
            else:
                status_cell = ""
            if "BLK" in status_cell:
                blocked_rows.append({"line": line_number, "row": line[:400]})
            elif "WATCH" in status_cell:
                watch_rows.append({"line": line_number, "row": line[:400]})
        for row in blocked_rows:
            self.add_candidate(
                "legacy_parity_matrix",
                "protocol-evolution",
                "legacy_parity_blk",
                row["row"],
                input_id="I8",
                severity="FAIL",
                extraction_type="protocol-evolution",
                pointer={"path": str(matrix_path), "line": row["line"]},
            )
        for row in watch_rows:
            self.add_candidate(
                "legacy_parity_matrix",
                "protocol-evolution",
                "legacy_parity_watch",
                row["row"],
                input_id="I8",
                severity="WATCH",
                extraction_type="protocol-evolution",
                pointer={"path": str(matrix_path), "line": row["line"]},
            )
        self.source_count("legacy_parity_watch_rows", len(watch_rows))
        self.source_count("legacy_parity_blocked_rows", len(blocked_rows))
        self.add_pattern("legacy_parity_matrix_watch", {"watch_rows": len(watch_rows), "blocked_rows": len(blocked_rows)})
        self.add_input("I8", "Legacy parity matrix", [str(matrix_path)], "opened", len(watch_rows) + len(blocked_rows), {
            "watch_rows": len(watch_rows),
            "blocked_rows": len(blocked_rows),
        })

    def finalize_input_accounting(self) -> None:
        for input_id in INPUT_ORDER:
            if input_id not in self.input_records:
                self.add_blocker(input_id, "input_not_accounted", f"{input_id} was not accounted by retrospector", "", "T21")
                self.add_input(input_id, "Unknown input", [], "blocked", 0)
        self.report["input_accounting"] = {input_id: self.input_records[input_id] for input_id in INPUT_ORDER}

    def candidate_release_disposition(self, candidate: dict) -> tuple[str, str]:
        source = str(candidate.get("source") or "")
        severity = str(candidate.get("severity") or "WATCH").upper()
        pointer = candidate.get("source_pointer") if isinstance(candidate.get("source_pointer"), dict) else {}
        task_status = str(pointer.get("task_status") or "").lower()

        if source in CURRENT_RELEASE_SOURCES:
            return ("current-blocker", "fail") if severity == "FAIL" else ("current-watch", "watch")
        if source == "run_results":
            if task_status in {"failed", "blocked"}:
                return "historical-learning", "none"
            if severity == "FAIL":
                return "current-blocker", "fail"
            if task_status == "completed" and str(candidate.get("trigger") or "").startswith("result_status_"):
                return "current-watch", "watch"
            return "historical-learning", "none"
        if source in HISTORICAL_RELEASE_SOURCES and severity != "FAIL":
            return "historical-learning", "none"
        if severity == "FAIL":
            return "current-blocker", "fail"
        return "historical-learning", "none"

    def release_ref_from_candidate(self, candidate: dict) -> dict:
        return {
            "kind": "candidate",
            "id": candidate.get("id", ""),
            "source": candidate.get("source", ""),
            "trigger": candidate.get("trigger", ""),
            "severity": candidate.get("severity", ""),
            "disposition": candidate.get("disposition", ""),
            "pointer": candidate.get("source_pointer", {}),
        }

    def release_ref_from_entry(self, kind: str, entry: dict) -> dict:
        return {
            "kind": kind,
            "input": entry.get("input", ""),
            "code": entry.get("code", ""),
            "message": entry.get("message", ""),
            "path": entry.get("path", ""),
            "owner": entry.get("owner", ""),
        }

    def apply_release_disposition(self) -> str:
        current_blockers = [self.release_ref_from_entry("blocker", b) for b in self.report["blockers"]]
        current_watch = [self.release_ref_from_entry("watch", w) for w in self.report["watch"]]
        historical_count = 0
        release_blocking_candidate_count = 0
        for candidate in self.report["candidates"]:
            disposition, impact = self.candidate_release_disposition(candidate)
            candidate["disposition"] = disposition
            candidate["release_impact"] = impact
            candidate["release_blocking"] = impact in {"watch", "fail"}
            if impact == "fail":
                current_blockers.append(self.release_ref_from_candidate(candidate))
                release_blocking_candidate_count += 1
            elif impact == "watch":
                current_watch.append(self.release_ref_from_candidate(candidate))
                release_blocking_candidate_count += 1
            else:
                historical_count += 1

        verdict = "fail" if current_blockers else ("watch" if current_watch else "pass")
        self.report["release_gate"] = {
            "verdict": verdict,
            "blocks_release": verdict != "pass",
            "current_blockers": current_blockers,
            "current_watch": current_watch,
            "historical_learning_candidate_count": historical_count,
            "release_blocking_candidate_count": release_blocking_candidate_count,
            "candidate_count": len(self.report["candidates"]),
            "explicit_blocker_count": len(self.report["blockers"]),
            "explicit_watch_count": len(self.report["watch"]),
        }
        return verdict

    def classify(self, *, full_writeback: bool = False) -> None:
        blockers = self.report["blockers"]
        candidates = self.report["candidates"]
        if blockers:
            classification = "blocked"
        elif candidates:
            classification = "extracted" if full_writeback else "candidates-pending"
        else:
            classification = "zero-candidates"
        self.report["classification"] = classification
        release_verdict = self.apply_release_disposition()
        if self.mode == "quick" and not full_writeback and classification == "candidates-pending" and release_verdict == "pass":
            self.report["verdict"] = "watch"
            self.report["release_gate"]["quick_pending_full_required"] = True
        else:
            self.report["verdict"] = release_verdict

    def compute_content_hash(self) -> None:
        payload = {
            "run": {k: v for k, v in self.report["run"].items() if k != "content_hash"},
            "sources": self.report["sources"],
            "source_counts": self.report["source_counts"],
            "input_accounting": self.report["input_accounting"],
            "classification": self.report["classification"],
            "verdict": self.report["verdict"],
            "candidates": self.report["candidates"],
            "blockers": self.report["blockers"],
            "watch": self.report["watch"],
            "release_gate": self.report.get("release_gate", {}),
        }
        self.report["run"]["content_hash"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def analyze(self) -> dict:
        self.discover_runtime()
        self.read_observations()
        self.read_registry()
        self.read_events()
        self.read_run_results()
        self.read_inspector_and_daemon()
        self.read_project_truth()
        self.read_patrol_evidence()
        self.read_parity_matrix()
        self.finalize_input_accounting()
        self.classify()
        self.compute_content_hash()
        return self.report

    def campaign_slug(self) -> str:
        explicit = os.environ.get("RETROSPECTIVE_CAMPAIGN") or os.environ.get("LEGION_CAMPAIGN")
        if explicit:
            return normalize_slug(explicit)
        if (self.planning_dir / "communication-upgrade").exists():
            return "communication-upgrade"
        return normalize_slug(self.project_dir.name)

    def render_retrospective(self) -> str:
        date = self.timestamp[:10]
        candidates = self.report["candidates"]
        lines = [
            f"# Retrospective {self.run_id}",
            "",
            f"- campaign: {self.campaign_slug()}",
            f"- timestamp: {self.timestamp}",
            f"- command: `{self.report['run']['command']}`",
            f"- cwd: `{self.cwd}`",
            f"- classification: {self.report['classification']}",
            f"- verdict: {self.report['verdict']}",
            f"- release_gate_verdict: {self.report.get('release_gate', {}).get('verdict', self.report['verdict'])}",
            f"- release_gate_blocks_release: {self.report.get('release_gate', {}).get('blocks_release', self.report['verdict'] != 'pass')}",
            f"- historical_learning_candidate_count: {self.report.get('release_gate', {}).get('historical_learning_candidate_count', 0)}",
            f"- release_blocking_candidate_count: {self.report.get('release_gate', {}).get('release_blocking_candidate_count', 0)}",
            f"- content_hash: `{self.report['run'].get('content_hash','')}`",
            "",
            "## Inputs Opened",
            "",
        ]
        for input_id in INPUT_ORDER:
            info = self.report["input_accounting"][input_id]
            paths = ", ".join(f"`{p}`" for p in info.get("paths", [])[:6]) or "(none)"
            lines.append(f"- {input_id} {info['name']}: {info['status']} count={info.get('count', 0)} paths={paths}")
        lines.extend(["", "## Extracted Learnings", ""])
        if candidates:
            for candidate in candidates:
                pointer = json.dumps(candidate.get("source_pointer", {}), ensure_ascii=False, sort_keys=True)
                lines.append(f"- {candidate['id']} [{candidate['severity']}] {candidate['extraction_type']} {candidate.get('disposition','historical-learning')} from {candidate['source']}: {candidate['trigger']}")
                lines.append(f"  - evidence: `{pointer}`")
                lines.append(f"  - content: {candidate['content']}")
                lines.append("  - proposed_destination: project-truth first; memory/tactics/skill only after synthesis accepts reuse value")
        else:
            lines.append("- zero candidates, inputs opened: I1-I8")
        lines.extend(["", "## Rejected Candidates", "", "- none rejected by deterministic extraction; every candidate remains visible for release synthesis.", ""])
        lines.extend(["## Blockers And Watch", ""])
        if self.report["blockers"]:
            for blocker in self.report["blockers"]:
                lines.append(f"- BLOCKER {blocker['input']} {blocker['code']}: {blocker['message']} path=`{blocker.get('path','')}` owner={blocker.get('owner','')}")
        if self.report["watch"]:
            for watch in self.report["watch"]:
                lines.append(f"- WATCH {watch['input']} {watch['code']}: {watch['message']} path=`{watch.get('path','')}` owner={watch.get('owner','')}")
        if not self.report["blockers"] and not self.report["watch"]:
            lines.append("- none")
        lines.extend(["", f"verdict: {self.report['verdict']}", "", "## Writeback Summary", ""])
        lines.append(f"- retrospective_record: `.planning/retrospectives/{date}-{self.campaign_slug()}.md`")
        lines.append("- state_summary: `.planning/STATE.md`")
        lines.append("- mixed_event: `events.jsonl` when MIXED_DIR/events.jsonl is writable")
        lines.append("")
        return "\n".join(lines)

    def append_locked_jsonl(self, path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(path) + ".lock")
        if fcntl is None:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            return
        with lock_path.open("a", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def append_state_summary(self, state_path: Path, record_path: Path, event_id: str | None) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        event_text = event_id or "not-written"
        lines = [
            "",
            f"## Retrospective Run {self.run_id}",
            "",
            f"- Timestamp: {self.timestamp}",
            f"- Command: `{self.report['run']['command']}`",
            f"- CWD: `{self.cwd}`",
            f"- Classification: {self.report['classification']}",
            f"- Verdict: {self.report['verdict']}",
            f"- Release gate verdict: {self.report.get('release_gate', {}).get('verdict', self.report['verdict'])}",
            f"- Release gate blocks release: {self.report.get('release_gate', {}).get('blocks_release', self.report['verdict'] != 'pass')}",
            f"- Run hash: `{self.report['run'].get('content_hash','')}`",
            f"- Retrospective record: `{record_path}`",
            f"- Mixed event: `{event_text}`",
            "- Inputs opened: " + ", ".join(f"{i}={self.report['input_accounting'][i]['status']}" for i in INPUT_ORDER),
            f"- Candidate count: {len(self.report['candidates'])}",
            f"- Historical learning candidate count: {self.report.get('release_gate', {}).get('historical_learning_candidate_count', 0)}",
            f"- Release-blocking candidate count: {self.report.get('release_gate', {}).get('release_blocking_candidate_count', 0)}",
            f"- Blocker count: {len(self.report['blockers'])}",
            f"- Watch count: {len(self.report['watch'])}",
        ]
        for blocker in self.report["blockers"]:
            lines.append(f"- Retrospective blocker ({blocker['owner']}): {blocker['input']} {blocker['code']} path={blocker.get('path','')} message={blocker['message']}")
        for watch in self.report["watch"]:
            lines.append(f"- Retrospective WATCH ({watch['owner']}): {watch['input']} {watch['code']} path={watch.get('path','')} message={watch['message']}")
        lines.append("")
        with state_path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

    def write_full_outputs(self) -> None:
        self.classify(full_writeback=True)
        self.compute_content_hash()
        retrospectives_dir = self.planning_dir / "retrospectives"
        retrospectives_dir.mkdir(parents=True, exist_ok=True)
        record_path = retrospectives_dir / f"{self.timestamp[:10]}-{self.campaign_slug()}.md"
        record_text = self.render_retrospective()
        record_path.write_text(record_text, encoding="utf-8")

        event_id: str | None = None
        events_path = self.mixed_dir / "events.jsonl" if self.mixed_dir else None
        if events_path:
            event_id = f"retro-{uuid.uuid4().hex[:12]}"
            event = {
                "ts": self.timestamp,
                "event": "retrospective_writeback",
                "task_id": self.run_id,
                "schema_version": 1,
                "event_id": event_id,
                "correlation_id": self.run_id,
                "payload": {
                    "mode": self.mode,
                    "classification": self.report["classification"],
                    "verdict": self.report["verdict"],
                    "release_gate_verdict": self.report.get("release_gate", {}).get("verdict", self.report["verdict"]),
                    "release_gate_blocks_release": self.report.get("release_gate", {}).get("blocks_release", self.report["verdict"] != "pass"),
                    "retrospective_record": str(record_path),
                    "state_path": str(self.planning_dir / "STATE.md"),
                    "candidate_count": len(self.report["candidates"]),
                    "historical_learning_candidate_count": self.report.get("release_gate", {}).get("historical_learning_candidate_count", 0),
                    "release_blocking_candidate_count": self.report.get("release_gate", {}).get("release_blocking_candidate_count", 0),
                    "blocker_count": len(self.report["blockers"]),
                    "watch_count": len(self.report["watch"]),
                    "content_hash": self.report["run"].get("content_hash", ""),
                },
            }
            try:
                self.append_locked_jsonl(events_path, event)
                self.report["mixed_event"] = {"path": str(events_path), "event_id": event_id}
            except Exception as exc:
                self.add_blocker("I2", "mixed_event_write_failed", str(exc), str(events_path), "T21")
                self.report["mixed_event"] = {"path": str(events_path), "error": str(exc)}
                event_id = None
        else:
            self.report["mixed_event"] = {"path": "", "error": "MIXED_DIR not discovered"}

        self.classify(full_writeback=True)
        self.compute_content_hash()
        record_path.write_text(self.render_retrospective(), encoding="utf-8")
        state_path = self.planning_dir / "STATE.md"
        self.append_state_summary(state_path, record_path, event_id)
        self.report["retrospective_record"] = str(record_path)
        self.report["state_writeback"] = str(state_path)
        self.classify(full_writeback=True)
        self.compute_content_hash()


def emit_stderr_summary(report: dict, mode: str) -> None:
    print(f"[retrospector] mode={mode} classification={report.get('classification')} verdict={report.get('verdict')}", file=sys.stderr)
    print(f"[retrospector] run_id={report.get('run', {}).get('id')} hash={report.get('run', {}).get('content_hash','')[:16]}", file=sys.stderr)
    print(f"[retrospector] 数据源: {report.get('sources', {})}", file=sys.stderr)
    print(f"[retrospector] source_counts: {report.get('source_counts', {})}", file=sys.stderr)
    print(f"[retrospector] 发现模式: {len(report.get('patterns', []))} 种", file=sys.stderr)
    print(f"[retrospector] 知识候选: {len(report.get('candidates', []))} 条", file=sys.stderr)
    if mode == "quick" and report.get("classification") == "candidates-pending":
        print("[retrospector] 建议运行 'retrospector.sh full' 提取并写回 release retrospective", file=sys.stderr)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "quick"
    if mode not in {"quick", "full"}:
        print("用法: retrospector.sh {quick|full}", file=sys.stderr)
        return 1
    runner = Retrospector(mode)
    report = runner.analyze()
    if mode == "full":
        runner.write_full_outputs()
        report = runner.report
    emit_stderr_summary(report, mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
__RETROSPECTOR_PYTHON__
