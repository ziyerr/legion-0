#!/usr/bin/env python3
"""Health check for claw-roundtable-skill."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


REQUIRED_FILES = [
    "SKILL.md",
    "requirement_analyzer.py",
    "roundtable_engine_v2.py",
    "roundtable_notifier.py",
    "agency_agents_loader.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check RoundTable skill readiness")
    parser.add_argument(
        "--require-runtime",
        action="store_true",
        help="Fail when OpenClaw sessions_spawn runtime is unavailable",
    )
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parent
    missing = [name for name in REQUIRED_FILES if not (skill_dir / name).exists()]
    if missing:
        print(f"FAIL files: missing {', '.join(missing)}")
        return 1
    print("OK files")

    agents_dir = skill_dir / "agency-agents"
    if not agents_dir.is_dir():
        print("FAIL agents: agency-agents directory missing")
        return 1
    agent_count = sum(1 for item in agents_dir.iterdir() if item.is_dir())
    print(f"OK agents: {agent_count}")

    sys.path.insert(0, str(skill_dir))
    try:
        engine = importlib.import_module("roundtable_engine_v2")
        result = engine.analyze_requirement("圆桌会议 讨论 Legion 架构、安全、用户体验")
    except Exception as exc:
        print(f"FAIL import/analyze: {type(exc).__name__}: {exc}")
        return 1

    print(f"OK analyze: {result.get('detected_types', [])}")

    try:
        tools = importlib.import_module("openclaw.tools")
        getattr(tools, "sessions_spawn")
    except Exception as exc:
        print(f"WARN runtime: openclaw.tools.sessions_spawn unavailable ({type(exc).__name__})")
        return 1 if args.require_runtime else 0

    print("OK runtime: openclaw.tools.sessions_spawn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
