# Communication Upgrade Implementation Plan

Date: 2026-04-25
Owner: mixed Legion communication-upgrade campaign

## Phase 1: Persistence Locks

- Add shared lock helpers for registry, inbox files, and `events.jsonl`.
- Route every registry read-modify-write path through one transaction helper.
- Keep atomic temp-file replacement, but perform it inside the registry lock.
- Add locked JSONL append helpers for inbox and event writes.
- Convert direct registry/inbox/event writers before changing higher-level
  behavior.

Acceptance:
- Concurrent registry updates preserve both writers' changes.
- Concurrent inbox/event appends produce valid JSONL without lost records.

## Phase 2: Message Delivery Ordering

- Change `mixed msg` and `mixed broadcast` so inbox persistence happens before
  tmux notification.
- Record tmux notification outcome separately from durable delivery.
- Keep missing/offline tmux sessions as non-fatal for inbox delivery.
- Replace any mixed commander prompt-injection path with durable inbox plus
  non-invasive tmux notice.

Acceptance:
- Forced inbox append failure produces no tmux notice.
- Missing tmux session still leaves exactly one inbox record and one event with
  `delivered_tmux=false`.

## Phase 3: Readiness Protocol

- Add readiness-order metadata under the locked registry transaction.
- Broadcast structured readiness requests with `order_id`, `issued_at`, parent
  id, expected direct L2 ids, and nonce.
- Require structured readiness replies that echo the current order fields.
- Validate every expected sender against the locked registry: direct child,
  branch-commander role, active allowed status, parent match, and current
  session/run binding.
- Remove readiness acceptance based only on historical inbox rows, arbitrary
  sender strings, or free-text content.

Acceptance:
- Stale, forged, wrong-parent, inactive, and type-only readiness records do not
  count.
- Fresh replies from live direct L2 commanders count.

## Phase 4: Hierarchy Delivery Boundary

- Encode L1 as the owner for S-level work and orchestration/synthesis for M+.
- Ensure L1-originated M+ delivery campaigns route through direct L2 commanders
  unless explicitly marked as non-delivery command-plane maintenance.
- Ensure task completion/acceptance is committed only by the owning L2 or worker
  result path under the registry transaction.
- Preserve worker file-scope ownership and block overlapping implementation
  scopes when lock support is available.

Acceptance:
- L1 cannot directly complete an M+ delivery task.
- L2/worker completion succeeds only with the expected task ownership and locked
  registry transition.

## Phase 5: Status And Reconcile Split

- Make mixed status read-only.
- Move mutating tmux reconciliation into an explicit repair/reconcile command.
- Classify tmux probe outcomes before mutating state.
- Write every reconcile mutation through the registry transaction helper.

Acceptance:
- Running status while another task is added cannot erase the new task.
- Tmux permission errors do not mark live commanders failed.

## Phase 6: Release Gate

- Run the syntax, unit, deterministic concurrency, readiness boundary, tmux
  delivery-order, and hierarchy-routing gates from
  `02-VERIFICATION-GATES.md`.
- Run the mixed patrol gate: unresolved patrol notices, gate blocks, M+ L1 delivery
  bypasses, or unapproved violations fail the release.
- Run the mixed retrospective gate: consume `retrospector.sh quick` evidence,
  decide whether full extraction is required, and record learnings or blockers
  in durable project truth.
- Run the legacy no-omission matrix and prove every preserved Claude-only
  mechanism is either retained directly or replaced by a stronger mixed
  mechanism with verification evidence.
- Do not mark the communication upgrade complete until all required gates pass
  or a blocker is recorded in `STATE.md` with exact command output.
