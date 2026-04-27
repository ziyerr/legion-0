# Communication Upgrade Runtime Contract

Date: 2026-04-25
Owner: mixed Legion communication-upgrade campaign

This contract is based on the completed dependency results:
`comm-recon-current-state`, `comm-recon-legacy-claude`,
`comm-audit-concurrency-races`, `comm-audit-tmux-delivery`, and
`comm-audit-readiness-boundary-rerun`.

## Runtime Truth Surfaces

- `mixed-registry.json` is the authoritative state for commanders, tasks,
  parent-child relationships, task dependencies, file scopes, statuses, run
  directories, and lifecycle decisions.
- `inbox/*.jsonl` is the authoritative durable message payload store. A tmux
  notice is only a wake-up signal and never a substitute for an inbox record.
- `events.jsonl` is the append-only audit trail for accepted state changes and
  message delivery outcomes.
- tmux sessions and windows are the live execution plane. They prove process
  visibility/liveness only after tmux access is classified as live, missing, or
  inaccessible.
- Mixed state must be mutated only through mixed-core helpers. Legacy shell
  surfaces may display or bridge mixed state, but must not create split-brain
  mutations outside the mixed contract.

## Hierarchy And Delivery Boundary

- L1 owns orchestration, routing, user-facing synthesis, and S-level execution.
- M+ deliverables must flow through a direct L2 branch commander or a worker
  supervised by an L2. The L2 validates the worker result and commits acceptance
  through the locked mixed registry transition.
- L1 direct execution is reserved for S-level work or explicit command-plane
  maintenance. M+ product, implementation, review, verification, audit,
  documentation, and release-gate deliverables are L2/worker-owned.
- A task cannot be marked complete because tmux received text, because an event
  was appended, or because L1 summarized it. Completion requires the owning
  L2/worker result plus the registry transition.

## Locking Contract

- Registry, inbox, and event-log writes must use `flock`.
- Registry mutation is a transaction: acquire the registry lock, re-read the
  latest registry, validate the transition, mutate the in-memory state, write
  via temp file plus atomic replace while still holding the lock, then release.
- Registry transactions must cover task upserts, commander upserts, status
  transitions, dependency blocking/unblocking, commander lifecycle changes,
  readiness-order metadata, and reconcile/repair mutations.
- Inbox append/read-cursor updates must be protected by a per-inbox lock.
- Event appends must be protected by an event-log lock and include enough ids to
  correlate with registry or inbox records.
- Terminal task states are monotonic. Reopening `completed`, `failed`, or
  `blocked` tasks requires an explicit repair/retry operation.

## Message And Tmux Delivery Contract

- Message records need a stable message id, sender id, recipient id, timestamp,
  type, content, and optional `reply_to`, `order_id`, and `requires_ack` fields.
- `mixed msg` and `mixed broadcast` must persist the target inbox record before
  any tmux notification attempt.
- If inbox persistence fails, no tmux notification may be sent and no success
  event may be appended.
- If tmux notification fails or the session is missing, the inbox record remains
  authoritative and the event records `delivered_tmux=false`.
- Tmux delivery for commander messages must be non-invasive notification
  (`display-message` or equivalent), not prompt injection. The commander reads
  the durable inbox content.
- Broadcast recipient snapshots must be taken from a locked registry view and
  each target receives its own idempotent inbox record.

## Readiness Trust Boundary

- Readiness is scoped to a current readiness order, not to all historical inbox
  rows. The parent records `order_id`, `issued_at`, expected direct L2 ids, and
  a per-order nonce before broadcasting the request.
- A readiness reply counts only if it is newer than the order freshness boundary
  and echoes the current `order_id`/nonce.
- Expected ids must be normalized through registry validation. Each accepted
  sender must be a registered direct L2 child of the parent, in an active
  allowed status, and attached to the expected parent relationship.
- Sender identity for readiness/control-plane messages must not be forgeable by
  passing an arbitrary `--sender` string. The sender must be derived from the
  commander's own execution context and bound to registered commander metadata
  such as run id, session id, parent id, and readiness order.
- Free-text `READY:init-complete` is not sufficient by itself. Readiness records
  must use structured fields and the explicit readiness tag required by the
  current order.

## Status And Reconcile Boundary

- Read-only status must not mutate registry state.
- Reconcile/repair is an explicit operation and must perform every mutation
  through the registry transaction helper.
- Tmux probe failures must distinguish missing sessions from permission or
  socket access failures before marking a commander/task failed.

## Patrol, Retrospective, And Learning Boundary

- Mixed campaigns must preserve the legacy Claude-only patrol loop as a release
  concern, not as an optional hook. A release gate cannot pass while there are
  unresolved patrol notices, active M+ L1 delivery bypasses, or blocked gate records
  without an explicit approval event.
- Patrol state must be visible from mixed runtime evidence: registry commander
  ids, inbox records, events, gate files, and tmux liveness must be correlated
  before a patrol PASS is accepted.
- Mixed campaigns must preserve the legacy retrospective loop. A release gate
  must run or consume `retrospector.sh quick` evidence and record whether
  `retrospector.sh full` is required, skipped because there are zero candidates,
  or blocked by an environment issue.
- Retrospective inputs must include mixed-native data, not only legacy
  observations: `events.jsonl`, `mixed-registry.json`, worker `result.md` files,
  failed/blocked task records, inspector memory, and `.planning/STATE.md`.
- Useful learnings must flow into durable project truth: `.planning/` status or
  retrospectives first, then memory/tactics or generated skills only when they
  are cross-session reusable and not duplicates.
- Codex strengthens this loop by serving as independent read-only auditor,
  reviewer, verifier, red-team attacker, and synthesis judge; Claude remains
  preferred for implementation, product, and UI delivery unless a task has a
  concrete Codex advantage.

## Legacy Parity Boundary

- The mixed system is not allowed to drop a working legacy Claude-only mechanism
  unless the release report names the mechanism, proves the replacement is
  stronger, and records the verification evidence.
- The no-omission matrix for each large architecture campaign must cover:
  tmux visibility, L1/L2 hierarchy, branch roles, file scopes, registry state,
  locks, inbox/outbox or inbox/events durability, task dependencies, readiness,
  gates/approvals, patrol, review, verify, audit, retrospection, observations,
  metrics, protocol evolution, memory/tactics, skill generation, heartbeat, GC,
  war-room/status UX, disband/retain-context policy, and documentation.
