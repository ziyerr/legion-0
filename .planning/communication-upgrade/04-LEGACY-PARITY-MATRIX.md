# Legacy Parity Matrix (No-Omission Release Contract)

Date: 2026-04-25
Owner: mixed Legion communication-upgrade campaign
Upstream evidence:
- `~/.claude/legion/bf21e79d/mixed/runs/legacy-inventory-claude-mechanisms/result.md`
- `~/.claude/legion/bf21e79d/mixed/runs/mixed-gap-map-runtime/result.md`
- `.planning/communication-upgrade/03-LEGACY-INHERITANCE-TASKLIST.md`
- `.planning/communication-upgrade/00-RUNTIME-CONTRACT.md`
- `.planning/communication-upgrade/02-VERIFICATION-GATES.md`
- `.planning/REQUIREMENTS.md` (R20-R37)
- `.planning/DECISIONS.md`
- `.planning/STATE.md`

## Purpose

This matrix is the no-omission release gate for the mixed Legion legacy
inheritance work. Every Claude-only mechanism present in commit `137d861` is
listed once and assigned exactly one outcome:

- **retained-as-is** — same code path is alive at HEAD with runtime evidence.
- **upgraded-in-mixed** — same mechanism exists at HEAD with mixed-native
  changes, and the change is proven by runtime evidence.
- **replaced-by-stronger-mixed** — legacy mechanism is intentionally removed,
  replaced by a named stronger mechanism, and the replacement is proven by
  runtime evidence.
- **blocked-with-repair-task** — the parity is not yet enforced at runtime;
  a named owner, a repair task id from
  `03-LEGACY-INHERITANCE-TASKLIST.md`, and a verification path are recorded.

Documenting a contract in `.planning/` does not satisfy parity. The matrix is
fail-closed: any row in `blocked-with-repair-task`, any unverified
"upgraded" claim, or any docs-only "implemented" claim forces the final
synthesis to FAIL or WATCH (Gate 11 in `02-VERIFICATION-GATES.md`).

## Runtime Evidence And Watch Items (Locked)

These rows are explicitly locked here so downstream summaries cannot silently
claim release without evidence. Several original blockers were repaired by
`repair-core-completion-readiness-v10a`, `repair-core-scope-repair-v10b`,
`repair-patrol-hook-gate-v3`, `repair-patrol-status-v3`, and
`repair-retrospector-script-v4`; the v16 repair artifacts close the B6 and B9
implementation watches with runtime evidence. Remaining WATCH rows still force
WATCH/FAIL until the final synthesis cites fresh gate evidence or names a
repair.

| # | State | Mechanism | Evidence pointer |
| --- | --- | --- | --- |
| B1 | RESTORED | Registry / inbox / events `flock` transactions | `scripts/legion_core.py` now has `_registry_lock()` plus `_file_append_lock()` for inbox/event JSONL appends; `repair-core-scope-repair-v10b` verified registry-locked scope/task insertion. B9-derived id/schema/correlation evidence is closed by `repair-event-correlation-evidence-v16`; verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_legion_core.py -v` passed (113 tests OK). |
| B2 | RESTORED | Inbox-before-tmux delivery | `send_message()` persists `_append_inbox()` before `_deliver_tmux_message()` and records `delivered_tmux`; tests cover offline tmux preserving inbox and non-invasive commander notification. |
| B3 | RESTORED | Readiness order/nonce/freshness/direct-L2/non-forgeable sender | Readiness orders record `order_id`, nonce, `issued_at`, expected direct L2 ids; tests reject stale, wrong-parent, inactive, missing-session, and non-roster replies. |
| B4 | RESTORED | Status / reconcile split (read-only status, classified tmux probe) | `status_text()` is read-only and `reconcile_state()` is explicit; patrol status classifies tmux liveness as live/missing/inaccessible for release evidence. |
| B5 | RESTORED | Strict worker completion schema for all providers | `complete_task_from_result()` consumes strict whole-file JSON; Claude/Codex exit 0 without parseable schema-valid result is failed/blocked, not completed. |
| B6 | RESTORED | Legacy shell / patrol / gate / retrospector bridge | `repair-legacy-surface-contract-v16` added executable contract coverage for `locks`, `board`, `sitrep`, `watch`, `patrol`, `retro`/`retrospector`, mailbox read/unread/list, gate status, and mixed status/inbox/readiness under isolated HOME/project with invalid TMPDIR. Verification: `python3 -m unittest tests.test_legion_shell_contract` passed (4 tests OK), after the intentional RED run for mailbox read/unread/list failed and then passed with the repo-local mailbox shim fallback. |
| B7 | RESTORED | File-scope ownership / lock | Delivery tasks require normalized project-relative scope; overlap detection runs under registry lock and blocks conflicting active delivery scopes. |
| B8 | RESTORED | Dependency repair after replacement completion | `repair_dependents` validates replacement tasks, preserves original terminal state, emits `task_repair`, rewrites dependencies, and unblocks direct/transitive repaired dependents. |
| B9 | RESTORED | Event log id / schema / correlation id | `repair-event-correlation-evidence-v16` added runtime-grade event coverage for `schema_version`, `id`, `type`, `timestamp`, `correlation_id`, `event`, `task_id`, `subject_id`, `payload.transition`, message/event correlation, and dependency-repair `task_repair`/repair `task_planned` events. Verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_legion_core.py -v` passed (113 tests OK). |
| B10 | RELEASE-GATE WATCH | No-omission release matrix is fail-closed | this document; PASS still requires independent review/verify/audit, patrol, retrospective, and synthesis evidence. Concrete blocker/repair: `synthesis-no-omission-release-gate-v16` must enumerate B1-B10 and rows 1-35 after the v16 closures and cite fresh evidence for remaining WATCH rows. |

RESTORED does not mean final release PASS. The final verdict still depends on
fresh Gates 1-11 evidence, including independent review, verify, audit, patrol,
retrospective, and no-omission synthesis.

## Matrix

Status legend: `RAS` retained-as-is · `UPG` upgraded-in-mixed ·
`REP` replaced-by-stronger-mixed · `BLK` blocked-with-repair-task ·
`WATCH` restored/retained behavior still needs final-gate evidence before PASS.

| # | Area | Legacy mechanism (137d861) | Mixed target | Status | Evidence / Owner / Repair task / Verification path |
| --- | --- | --- | --- | --- | --- |
| 1 | Visible work | Every teammate visible in tmux session/window per L1 and team, plus war-room/joint views | Mixed L1/L2 sessions, task windows, `legion view`, VS Code/Terminal duo | UPG | Live: `tmux ls` lists `L1-鲲鹏军团`, `L2-explore/implement/review/verify-1777100234`, mixed task session; `STATE.md` records `legion view` interactive split. Verification: tmux probe must classify accessible vs inaccessible (B4); ties to T11/T27. |
| 2 | Hierarchy | L1 prompts + team conventions | Stable dual L1 by default; dynamic branch L2 for M+; parent, level, lifecycle, corps, hierarchy delivery boundary | UPG | `mixed-registry.json` records commanders with parent/level/lifecycle. Verification: Gate 6 (S stays with L1; M+ delivery campaigns route through L2). Owner: Claude implement T04. |
| 3 | Roles | Mostly Claude team roles + Codex paratrooper scripts | Provider defaults: Codex owns explore/review/verify/audit/security; Claude owns implement/product/UI; `--corps` preserves split | UPG | AGENTS.md and live registry show role/provider defaults. Verification: T05 tests for `--corps` split. Owner: Claude implement + Codex review. |
| 4 | Communication / inbox-outbox + SendMessage discipline | JSON inbox/outbox, tmux SendMessage, broadcast, deprecated mailbox helper | Locked inbox JSONL + locked events + non-invasive tmux notification, inbox-before-tmux | UPG (B2 restored) | Evidence: `send_message()` writes `_append_inbox()` before tmux delivery, commander notifications use non-invasive `display-message`, offline tmux leaves inbox authoritative with `delivered_tmux=false`, and broadcast snapshots active L2 recipients. Verification: `test_mixed_msg_keeps_inbox_record_when_commander_session_is_offline`, `test_mixed_msg_to_l1_uses_noninvasive_tmux_notice`, broadcast tests, plus `repair-core-completion-readiness-v10a` / v10b core suite. |
| 5 | Locks (registry/inbox/events `flock` transactions) | `registry.json` + `locks.json` mutated under shell `flock` paths in legacy `legion.sh` | `fcntl.flock` registry lock plus inbox/event append locks in `scripts/legion_core.py` | UPG | Evidence: `_registry_lock()` guards registry read-modify-write and `_file_append_lock()` guards inbox/events JSONL append; v10b verified campaign scope check, branch commander reuse/creation, and task insertion under the registry lock. B9-derived event id/schema/correlation evidence is closed by `repair-event-correlation-evidence-v16`; verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_legion_core.py -v` passed (113 tests OK). |
| 6 | Registry state (mixed truth) | `registry.json` legacy commander/team/task fields | `mixed-registry.json` with monotonic states, dependency edges, lifecycle, scope, readiness orders | UPG | Evidence: registry now stores readiness orders, normalized scope ownership, dependency repair metadata, lifecycle, origin commander, branch commander provider compatibility, and strict terminal-state handling. Verification: `python3 -m unittest tests.test_legion_core` in v10a/v10b. |
| 7 | Taskboard | `taskboard.json` + commander daemon task APIs | Mixed registry tasks + read-only `mixed status` + explicit reconcile/repair + dependency block/unblock | UPG | Evidence: `status_text()` no longer calls reconcile, `reconcile_state()` is explicit, and dependency block/repair writes registry/events through controlled paths. Verification: `test_status_text_does_not_mutate_registry_or_events`, explicit reconcile tests, repair tests. |
| 8 | Dependencies | Prompt-level / ad hoc DAG waits | `depends_on` launch gating with recursive downstream blocking and explicit repair | UPG (B8 restored) | Evidence: failed/blocked dependencies recursively block downstream tasks; `repair_dependents` rewrites dependency edges to a valid replacement, preserves the original terminal state, records `task_repair`, and unblocks direct plus transitive repaired dependents. Verification: v10b repair tests. |
| 9 | Approval gates | Gate files + hooks + quality checks | Mixed gate records with fail-closed patrol/gate enforcement and release evidence | UPG | Evidence: `repair-patrol-hook-gate-v3` preserved legacy 1-5/6-10/11+ escalation for L1 and L2, blocks unresolved notices and unapproved/unknown/corrupt gates, and `repair-patrol-status-v3` surfaces gate files plus related mixed events. B9 event correlation is now closed by `repair-event-correlation-evidence-v16`; verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_legion_core.py -v` passed (113 tests OK). |
| 10 | Patrol | `legion-patrol.sh` notice/remediate/reinspect/release flow tied to hook gate | Mixed patrol status correlating notices, gate files, registry ids, events, tmux liveness | UPG | Evidence: legacy notice/remediate/reinspect entrypoints preserved; `legion-patrol.sh status` emits unresolved notices, mixed commander registry, live/missing/inaccessible tmux classification, gate files, and recent mixed patrol/gate/blocked/failed events. Verification: `bash -n scripts/legion-patrol.sh`, `bash scripts/legion-patrol.sh status`, synthetic notice/remediate/reinspect cases. |
| 11 | Inspector | Legacy LLM patrol, warning escalation, adaptive false-positive memory | Legacy daemon/inspector evidence retained and fed into mixed retrospective; active mixed inspector remains release-gate evidence | RAS + UPG + WATCH | Evidence: `verify-runtime-parity-v15b` validated `daemon_evidence.jsonl` schema/hash and `retrospector.sh` reads `inspector_memory.json` plus legacy observations alongside mixed sources. WATCH remains because no named v16 artifact proves an active mixed screen-reading inspector loop or a formally accepted stronger replacement. Concrete blocker/repair: `synthesis-no-omission-release-gate-v16` must cite active-loop/replacement evidence or open a focused inspector parity repair. |
| 12 | Review | Team/audit/codex-paratrooper scripts; paired review | Independent Codex review branches read-only via `.agents/skills/agent-team` and `audit` | UPG | Skills present at HEAD. Verification: T17 auto-injects independent review for M+ campaigns; T18 verifies Codex read-only sandbox cannot mutate working tree. Final synthesis still needs fresh review evidence. |
| 13 | Verify | Integration / runtime evidence scripts | Independent Codex verify branches in isolated HOME/tmux | UPG | Skills present at HEAD. Verification: T32 isolated runtime verification across mixed campaign/msg/broadcast/readiness/status/patrol/retrospector. Final synthesis still needs fresh verify evidence. |
| 14 | Audit | "Any FAIL fails release" via `audit.sh` and codex-paratrooper | Independent Codex audit + red-team + Claude implementation separation | UPG | Skills present at HEAD. Verification: T19 final synthesis FAIL/WATCH on any failed gate; T33 adversarial red-team. Final synthesis still needs fresh audit evidence. |
| 15 | Retrospective | After-action review through `retrospector.sh` | Release gate runs/consumes `retrospector.sh quick/full` with mixed-native and legacy daemon sources | UPG | Evidence: `repair-retrospector-script-v4` made quick mode read legacy observations, inspector memory, `.planning`, mixed registry, events, failed/blocked/latest `result.md`, and emit structured patterns/candidates. `repair-retrospective-disposition-v16` then fixed release disposition so historical-only candidates remain visible without forcing WATCH, while explicit blockers, current WATCH sources, and current FAIL candidates still block. Verification: `python3 -m unittest tests.test_retrospector_contract` passed (4 tests OK) and `bash -n scripts/retrospector.sh` passed. |
| 16 | Observations | Hook-generated observation JSONL + repeated-failure pattern detection | Mixed events/results feed observations and protocol learning | RAS (hook layer) + UPG (mixed events) | `scripts/hooks/post-tool-use.sh` writes observations at HEAD. Verification: T25 metrics-and-protocol-evolution test; mixed events appear in retrospector inputs. Owner: Claude implement T25. |
| 17 | Metrics | tasks/warnings/audit/recon rates via legacy daemon | Mixed metrics with throughput, quality, false-positive | UPG | Verification: T25 covers tasks, warnings, violations, audit pass/fail, recon rate, false positives, protocol proposals. Owner: Claude implement T25. |
| 18 | Protocol evolution | Daemon proposals from metrics | Mixed proposals require review/audit before adoption | UPG | Verification: T25 proposals run review/audit gate; AGENTS.md scale-first doctrine encodes the policy. Owner: Claude implement T25 + Codex review. |
| 19 | Tactics | `memory/tactics/INDEX.md` + citation scoring | Startup prompts load tactics; retro writes candidates with evidence | RAS + UPG | Tactics index present at HEAD; startup prompts load it (per inventory result). Verification: T23 preserves score, citation, eviction, startup loading for global+project tactics. Owner: Claude implement T23. |
| 20 | Generated skills | Absent at 137d861 | `.agents/skills/` for agent-team, audit, claw-roundtable, degradation-policy, product-counselor, recon, sniper, spec-driven, ui-designer; Codex skill budget compaction | REP (no legacy to retain) | Skills present at HEAD. Verification: T24 frontmatter, trigger coverage, validation, capacity rules, discoverability; never drop skills to hide warnings. Owner: Codex review T24. |
| 21 | Heartbeat | Commander/tool heartbeat via legacy daemon and hooks | Tmux liveness + readiness order, read-only status, explicit reconcile, patrol liveness classification | RAS + UPG | Evidence: readiness rejects missing-session direct L2, `status_text()` stays read-only, `reconcile_state()` is explicit, and `legion-patrol.sh status` classifies live/missing/inaccessible. Final synthesis should still cite daemon/hook heartbeat evidence when making release claims. |
| 22 | GC / lifecycle | Zombie/lock/inbox cleanup + team cleanups in legacy daemon | Mixed campaign L2 retirement, context retention, disband messages | UPG | `STATE.md` records `--corps` lifecycle=campaign, `DISBAND:init-complete`, retain_context. Verification: T28 lifecycle policy test (failed/blocked/context-rich L2 stays alive; idle completed campaign L2 disbands). Owner: Claude implement T28. |
| 23 | War-room / status UX | Operator sees the whole team via legacy view + L1/team tmux | Mixed `legion view` Claude-Team split + read-only `mixed status`, plus patrol/retro gate evidence surfaces | UPG + WATCH | Evidence: `legion view` embeds live L1/L2 sessions; `mixed status` is read-only; `repair-legacy-surface-contract-v16` proves read-only `board`, `sitrep`, `watch`, `patrol`, `retro`/`retrospector`, gate status, and mixed status/inbox/readiness surfaces under isolated HOME/project with invalid TMPDIR (`python3 -m unittest tests.test_legion_shell_contract`, 4 tests OK). WATCH remains because no named artifact proves one operator UX surface shows blockers, patrol, retrospective, and gates together. Concrete blocker/repair: `synthesis-no-omission-release-gate-v16` must cite unified UX evidence or open a focused UX surfacing repair. |
| 24 | Disband / retain-context | Legacy team cleanup vs retention by hand | Mixed `lifecycle=campaign` + `retain_context` + `DISBAND:init-complete` | UPG | Verification: T28 test that completed context-free campaign L2 receives DISBAND and tmux cleanup; failed/blocked/context-rich L2 preserved. Owner: Claude implement T28. |
| 25 | Install / hooks lifecycle | `legion-init.sh` initializes project + hooks | `legion 0` + `legion h` self-healing global wrapper, Codex shim, RoundTable bridge skill, synchronous hook verification | UPG | `STATE.md` records `legion 0` self-sync and bare wrapper install. Verification: T29 keeps global/local script sync, hooks, skills, schemas, and bare `legion` wrapper aligned; hook syntax check (Gate 1). Owner: Claude implement T29. |
| 26 | Codex shim | Absent at 137d861 | `scripts/codex` shim intercepts `codex l1`/`l1+1` while forwarding normal Codex CLI | REP (no legacy to retain) | Verification: shim test that Legion entrypoints route through mixed and unrelated Codex calls forward unchanged. Owner: Claude implement T29. |
| 27 | Codex skill budget | Absent at 137d861 | `scripts/codex_skill_budget.py` audits/compacts skill frontmatter without dropping skills | REP (no legacy to retain) | Verification: T24 ensures generated skills keep frontmatter, trigger coverage, validation, capacity, and discoverability. Owner: Codex review T24. |
| 28 | Docs | README + CLAUDE + tactics docs | README + AGENTS + CLAUDE + `.planning` truth source + builder journal | UPG | Evidence: this v11b docs repair updates README, requirements, decisions, state, parity matrix, and retrospective contract to match restored runtime mechanisms without deleting legacy principles. Verification: scoped grep/diff checks plus core repair result artifacts. |
| 29 | File scope | Worker scope conventions in legacy team docs | Normalized project-relative scope per delivery task with overlap detection + scope-conflict block + review/verify/audit visibility | UPG (B7 restored) | Evidence: v10b requires non-empty scope for delivery tasks, rejects absolute/traversal/root paths, normalizes paths, checks overlap inside the registry lock, and releases ownership at terminal states. Verification: scope conflict, normalization, traversal, in-campaign conflict, rescue-role, and terminal release tests. |
| 30 | Status / reconcile split | Legacy `sitrep`/`status` mutated state via daemon repair | Read-only `mixed status` + explicit reconcile/repair + classified patrol tmux probe | UPG (B4 restored) | Evidence: `status_text()` is read-only and does not mutate registry/events; `reconcile_state()` is the explicit mutation entry point; patrol status classifies tmux access as live/missing/inaccessible. Verification: status non-mutation and explicit reconcile tests plus patrol status run. |
| 31 | Readiness trust | None at legacy commit (the same gap existed pre-mixed) | Order-id + nonce + freshness + direct-L2 registry validation + parent match + active session/run binding + non-forgeable sender | UPG (B3 restored) | Evidence: current readiness order is stored in registry, requests include order/nonce, expected roster is direct-L2 filtered, stale and forged rows are ignored, missing tmux sessions are rejected, and arbitrary sender strings cannot satisfy a roster slot. Verification: v10a readiness tests. |
| 32 | Worker completion | Legacy team scripts assumed Claude exit was acceptance | Strict worker result schema for all providers; non-success transitions to `blocked`/`failed`; repair workflow reopens dependents through recorded event | UPG (B5+B8 restored) | Evidence: whole-file JSON schema validation governs Claude and Codex; plain text/prose-wrapped output fails; result `status` overrides process exit; repair workflow validates replacements and emits `task_repair`. Verification: v10a/v10b worker-result and repair tests. |
| 33 | Legacy shell / patrol / gate / mailbox / board / sitrep / watch / retrospector | Active surfaces at 137d861 over `registry.json`, `locks.json`, `taskboard.json`, mailbox/inbox, patrol notices, gate files, retrospector outputs | Preserve useful legacy surfaces and expose mixed-native evidence the release gate consumes | UPG | Evidence: `repair-legacy-surface-contract-v16` proves `locks`, `board`, `sitrep`, `watch`, `patrol`, `retro`/`retrospector`, mailbox read/unread/list, gate status, and mixed status/inbox/readiness under isolated HOME/project with invalid TMPDIR. Verification: intentional RED `python3 -m unittest tests.test_legion_shell_contract.LegionShellContractTests.test_read_only_entrypoints_work_with_invalid_tmpdir_without_registration` failed for mailbox read/unread/list, then passed after the repo-local mailbox shim fallback; final `python3 -m unittest tests.test_legion_shell_contract` passed (4 tests OK). Parallel split-brain remains forbidden. |
| 34 | Event log durability | Legacy `events.jsonl` (where present) was unstructured | Locked event append plus stable event id, schema version, type, timestamp, and correlation id linking registry transaction / inbox message / dependency edge / readiness order | UPG | Evidence: `_file_append_lock()` protects event JSONL append, and `repair-event-correlation-evidence-v16` proves release-grade event fields/correlation for state transitions, `message_sent`, and dependency repair events. Verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_legion_core.py -v` passed (113 tests OK). Empty-payload status events still do not satisfy release-grade audit evidence unless synthesis cites the v16-covered event paths. |
| 35 | No-omission release gate | Implicit at 137d861 (audit FAIL = release FAIL) | Fail-closed final matrix consumed by release synthesis | WATCH (B10) | Owner: Codex audit T34. Verification/blocker: `synthesis-no-omission-release-gate-v16` must enumerate every row above after v16 closure, cite independent review/verify/audit, patrol, retrospective, and synthesis evidence, and resolve remaining row 11 and row 23 WATCH items. Any remaining WATCH/BLK row, unverified upgrade claim, docs-only "implemented" claim, failed review/verify/audit, unresolved patrol notice, or current retrospective blocker/current WATCH/current FAIL candidate forces FAIL or WATCH. PASS requires runtime evidence for every row. |

## Acceptance Rules

1. **Runtime evidence beats docs.** A "RAS" or "UPG" row may be marked
   verified only when a concrete command (Gates 1-10 in
   `02-VERIFICATION-GATES.md`) produces evidence. `git grep`, `bash -n`, AST
   parse, deterministic concurrency tests, forced-failure tests, isolated
   HOME/tmux integration runs, and red-team probes are valid sources.
2. **No silent omission.** A mechanism not appearing here is a release-blocking
   bug. The release synthesis must verify that every row in
   `03-LEGACY-INHERITANCE-TASKLIST.md`'s coverage table maps to one or more
   rows in this matrix.
3. **Blocked rows must name a repair task.** Every BLK row references a task
   id from `03-LEGACY-INHERITANCE-TASKLIST.md` and a verification path from
   `02-VERIFICATION-GATES.md`. A blocker without an owner is itself a release
   bug.
4. **Docs-only is not implementation.** Adding a section to
   `00-RUNTIME-CONTRACT.md`, `01-IMPLEMENTATION-PLAN.md`, or this matrix is
   not evidence of runtime support. The mechanism must be enforced in
   `scripts/legion_core.py`, `scripts/legion.sh`, hooks, or the agent-team
   skills before being marked verified.
5. **Fail-closed.** Final synthesis sets PASS only when every row carries
   runtime evidence and no blocker/watch item remains. Otherwise FAIL or
   WATCH.

## Cross-Reference Index

- Coverage table: `03-LEGACY-INHERITANCE-TASKLIST.md` (rows 23-44 in that file).
- Runtime contract: `00-RUNTIME-CONTRACT.md` (truth surfaces, locking,
  delivery, readiness, status/reconcile, patrol/retro/learning, legacy
  parity).
- Implementation plan: `01-IMPLEMENTATION-PLAN.md` (Phases 1-6).
- Verification gates: `02-VERIFICATION-GATES.md` (Gates 1-11).
- Requirements: `.planning/REQUIREMENTS.md` (R20-R37).
- Decisions: `.planning/DECISIONS.md` (no-omission parity, locking,
  inbox-before-tmux, readiness trust, status/reconcile split, structured
  worker completion, legacy bridge ban on split-brain, file-scope
  enforcement, fail-closed release gate).
- Current state and blockers: `.planning/STATE.md` (B1-B10 enumerated).
