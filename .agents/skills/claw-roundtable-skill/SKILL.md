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

This is a shared weapon for all L1/L2 branches. Every branch can invoke it when the task requires multi-perspective decision pressure, but completion claims require runtime health evidence.
