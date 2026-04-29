---
name: claw-roundtable-skill
description: Use when Legion/Codex is asked for RoundTable, 圆桌会议, multi-expert debate, high-cost architecture/API/security decisions, XL planning, or when recon leaves multiple viable paths. Bridges to the project Claude RoundTable runtime and must health-check before claiming execution.
---

# Claw RoundTable Bridge

Use this skill inside Codex/Legion branches to access the project RoundTable package at `.claude/skills/claw-roundtable-skill`.

## Required Checks

1. Confirm the project package exists:
`test -f .claude/skills/claw-roundtable-skill/SKILL.md`

2. Run base health before using analysis or expert matching:
`python3 .claude/skills/claw-roundtable-skill/roundtable_health.py`

3. Before claiming a real multi-expert RoundTable execution, run:
`python3 .claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime`

If `--require-runtime` fails with missing `openclaw.tools.sessions_spawn`, do not claim RoundTable completed. Report that only analysis/expert matching is available and use Legion Core `mixed campaign --corps` for the actual multi-agent discussion.

## Analysis

For demand analysis without runtime:

```bash
PYTHONPATH=.claude/skills/claw-roundtable-skill python3 - <<'PY'
from roundtable_engine_v2 import analyze_requirement

result = analyze_requirement("要讨论的问题")
print(result)
PY
```

## Legion Rule

This is an on-demand shared weapon for all L1/L2 branches. Codex commanders perform RoundTable initialization during normal startup because the default runtime bridge uses the Codex CLI. Claude commanders do not run RoundTable initialization during routine startup, but they can run explicit RoundTable/OpenClaw access tests when requested. Completion claims always require runtime health evidence.

For native OpenClaw backend integration testing:

```bash
OPENCLAW_ROUNDTABLE_BACKEND=openclaw python3 .claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime
```
