# External AICTO / Dual-L1 Control Plane Plan

## Objective

Correct the AICTO boundary:

- AICTO is the external Hermes CTO project at `/Users/feijun/Documents/AICTO`.
- Legion Core is the Claude/Codex army runtime, not the AICTO product.
- Claude L1 owns the Claude provider army and creates Claude L2 branches only for M+ work.
- Codex L1 owns the Codex provider army and creates Codex L2 branches only for M+ work.
- Codex L1/L2/workers use the same tmux-visible management path as Claude teams.
- Default public startup is L1-only. S-level AICTO directives are handled by the receiving L1; M+ directives expand through visible L2/team tmux windows.
- Claude L1 and Codex L1 receive a durable 1-second-delayed peer-sync handshake after startup.
- L2 commanders are task-scoped execution units; L1 activation must provide target/scope/dependency context so L2 only loads relevant skills, tactics, files, and pre-research.

## Implementation

1. Make `legion h` / `legion host` default to Claude/Codex dual L1 only, with no base L2 at startup.
2. Make `legion aicto` read-only status/startup guidance for the external Hermes AICTO profile.
3. Preserve explicit fallback paths:
   - `legion host --dual-only` / `legion mixed dual-host`
   - `legion mixed host --host-only`
4. Keep L1 readiness validation for direct L2 children only when an explicit readiness-order / M+ dynamic L2 roster exists.
5. Add tests for dual-L1 topology, no-base-L2 default, peer-sync behavior, L2 lightweight activation, external-AICTO status behavior, shell dry-run non-mutation, and Codex tmux parity.
6. Keep commander tmux notifications non-invasive; durable inbox is the source of truth for readiness orders, peer-sync, and long messages.

## Verification

- `python3 -m py_compile scripts/legion_core.py`
- `bash -n scripts/legion.sh`
- focused `unittest` for Legion core and shell contract
- `git diff --check` for the scoped patch
- dry-run smoke:
  - `/bin/bash scripts/legion.sh aicto --dry-run --no-attach`
  - `/bin/bash scripts/legion.sh host --dry-run --no-attach` (dual L1 only; no L2)
  - `/bin/bash scripts/legion.sh host --dual-only --dry-run --no-attach`
  - `/bin/bash scripts/legion.sh mixed aicto --dry-run --no-attach`
  - `/bin/bash scripts/legion.sh mixed dual-host --dry-run --no-attach` (dual L1 only; no L2)
