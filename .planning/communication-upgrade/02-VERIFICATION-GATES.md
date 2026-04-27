# Communication Upgrade Verification Gates

Date: 2026-04-25
Owner: mixed Legion communication-upgrade campaign

These gates define the minimum evidence required before the communication
upgrade can be reported complete.

## Gate 1: Static Sanity

Commands:

```bash
bash -n scripts/legion.sh
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast, pathlib; ast.parse(pathlib.Path("scripts/legion_core.py").read_text(encoding="utf-8")); print("ast-ok")'
```

Pass criteria:
- Shell syntax passes.
- `scripts/legion_core.py` parses.

## Gate 2: Registry Transaction Safety

Required tests:
- Concurrent commander registration preserves both commanders.
- Concurrent campaign/task upserts preserve all tasks.
- Concurrent complete/fail paths preserve monotonic terminal transitions.
- Dependency unblocking/blocking cannot launch a task after a dependency fails.
- Status/reconcile cannot erase concurrent registry changes.

Pass criteria:
- Deterministic barriered tests pass repeatedly.
- No registry writer bypasses the transaction helper.

## Gate 3: Inbox And Event Durability

Required tests:
- Concurrent inbox appends produce valid JSONL and preserve all message ids.
- Concurrent event appends produce valid JSONL and preserve all event ids.
- Inbox read cursor or unread state updates are locked.
- Every message event correlates to an inbox message id.

Pass criteria:
- No partial JSONL rows.
- No lost message/event records.

## Gate 4: Tmux Delivery Ordering

Required tests:
- Forced inbox append failure sends no tmux notice.
- Successful inbox append followed by missing tmux session records
  `delivered_tmux=false`.
- Commander delivery uses non-invasive notification, not prompt injection.
- Broadcast creates one durable inbox record per target before notification.

Pass criteria:
- Inbox is always persisted before tmux notification.
- Tmux failure never deletes or suppresses the durable inbox record.

## Gate 5: Readiness Trust Boundary

Required tests:
- Stale readiness rows from before the current order are ignored.
- `--expect` ids outside the parent's direct L2 roster are rejected.
- Arbitrary sender strings cannot forge readiness.
- Wrong-parent, inactive, or missing-session senders are ignored.
- Type-only readiness records without the required structured order fields are
  ignored.
- Fresh structured replies from expected direct L2 commanders count.

Pass criteria:
- Readiness requires freshness, direct L2 validation, and non-forgeable sender
  context.

## Gate 6: Hierarchy Delivery Boundary

Required tests:
- L1 cannot directly complete or accept an M+ delivery task.
- L1 S-level work and command-plane maintenance remain explicitly allowed.
- L1-originated M+ delivery campaigns route through direct L2 commanders.
- L2/worker completion commits only under the registry transaction.

Pass criteria:
- All deliverables are accepted through L2/worker ownership, never direct L1
  delivery.

## Gate 7: Runtime Integration

Commands:

```bash
scripts/legion.sh mixed campaign --help
scripts/legion.sh mixed readiness --help
scripts/legion.sh mixed status
```

Pass criteria:
- Help surfaces expose the updated contract fields or options.
- Status is read-only. If tmux is inaccessible, it reports the access boundary
  instead of mutating commanders/tasks to failed.

## Gate 8: Release Evidence

Required evidence:
- Exact commands run.
- Exit status and failure count.
- Files touched.
- Known residual risks.

Pass criteria:
- `STATE.md` records successful gate results or exact blockers before any
  completion claim.

## Gate 9: Mixed Patrol Continuity

Commands:

```bash
bash scripts/legion-patrol.sh status
scripts/legion.sh mixed status
```

Required checks:
- No unresolved patrol notice remains for the releasing L1/L2 tree.
- Any active gate block has a matching approval event or remains a release
  blocker.
- The release task verifies that delivery work was owned by L2/worker tasks, not
  directly completed by L1.
- The legacy warning to violation to gate flow remains documented and testable
  for mixed commanders.

Pass criteria:
- Patrol PASS is backed by patrol state plus mixed registry/events evidence.
- Missing patrol runtime support is a blocker, not a silent skip.

## Gate 10: Mixed Retrospective Continuity

Commands:

```bash
bash scripts/retrospector.sh quick
```

Required checks:
- Retrospective evidence is consumed before release synthesis.
- If quick mode reports knowledge candidates, the release gate either runs full
  extraction or records an explicit blocker with the command output.
- Mixed-native sources are included in the follow-up implementation plan:
  registry, events, run results, failed/blocked tasks, inspector memory, and
  `.planning/STATE.md`.
- New learnings are written to durable project truth before final user-facing
  completion reporting.

Pass criteria:
- Zero candidates, extracted learnings, or an exact blocker is recorded in
  `STATE.md`.
- The release synthesis cannot PASS while retrospective evidence is missing.

## Gate 11: Legacy No-Omission Matrix

Required checks:
- The release report includes a matrix for every preserved legacy mechanism:
  tmux visibility, L1/L2 hierarchy, branch roles, file scopes, locks, durable
  communication, dependencies, readiness, approvals, patrol, review, verify,
  audit, retrospection, observations, metrics, protocol evolution, tactics,
  generated skills, heartbeat, GC, war-room/status UX, disband/retain-context,
  and docs.
- Each row states one of: retained as-is, upgraded in mixed, replaced by a
  stronger mixed mechanism, or blocked with a repair task.

Pass criteria:
- No row is omitted.
- Any blocked row forces the final release verdict to FAIL or WATCH, never PASS.
