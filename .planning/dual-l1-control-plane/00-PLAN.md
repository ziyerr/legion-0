# Dual L1 Control Plane Plan

Date: 2026-04-27
Owner: live repair campaign

## Problem

The current mixed host shape lets one L1 represent both Claude and Codex
workers. Live evidence showed this breaks the trust model:

- registry can report many `commanding` commanders whose tmux sessions are gone
- broadcasts can target stale or non-roster branch commanders
- `sender_verified=false` control messages can enter inboxes but cannot satisfy
  readiness
- the L1 view can accidentally embed panes from a different project

## Locked Direction

Use two provider-owned L1 commanders for normal operation:

- `L1-<project>-Claude-*` owns Claude L2/team routing
- `L1-<project>-Codex-*` owns Codex L2/team routing
- Legion Core remains L0: registry, events, inboxes, scopes, readiness orders,
  and cross-provider synthesis

Cross-provider coordination must happen through Legion Core orders and durable
results, not by one L1 spoofing another L1's execution context.

## Implementation Slices

1. Core routing and readiness
   - add dual-L1 host launch/convene support
   - make broadcast recipient selection live-session aware
   - keep readiness scoped to live direct children and verified replies

2. CLI and view
   - expose a usable dual-L1 launch path
   - prevent project-view contamination by building views only from sessions
     registered for the current project hash

3. Documentation and tests
   - record the new operating model in `.planning`, README, and command help
   - add focused tests for dual-L1 launch, live-only broadcast, and view
     project isolation

## Verification Gate

Minimum fresh checks before completion:

- `PYTHONPYCACHEPREFIX=/tmp/legion-pycache python3 -m py_compile scripts/legion_core.py`
- `TMPDIR=/tmp PYTHONPYCACHEPREFIX=/tmp/legion-pycache PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_legion_core.py -v`
- `bash -n scripts/legion.sh`
- `scripts/legion.sh mixed dual-host --dry-run` or equivalent dry-run command

## Completion Evidence

- Implemented on 2026-04-27.
- Final local verification passed:
  - `PYTHONPYCACHEPREFIX=/tmp/legion-pycache python3 -m py_compile scripts/legion_core.py`
  - `bash -n scripts/legion.sh`
  - `TMPDIR=/tmp PYTHONPYCACHEPREFIX=/tmp/legion-pycache PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_legion_core.py tests/test_legion_shell_contract.py -v`
  - `/bin/bash scripts/legion.sh host --dry-run --no-attach`
  - `/bin/bash scripts/legion.sh mixed host --dry-run --host-only`
- Independent review gates:
  - `dual-l1-control-plane-review` found shell compatibility regressions.
  - `dual-l1-control-plane-review-v2` verified those regressions closed.
