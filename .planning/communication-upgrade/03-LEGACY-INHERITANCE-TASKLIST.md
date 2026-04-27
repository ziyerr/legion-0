# Legacy Claude Inheritance Upgrade Tasklist

Date: 2026-04-25
Owner: mixed Legion architecture upgrade

## Goal

Preserve every useful Claude-only Legion mechanism and upgrade it into the
Claude + Codex mixed architecture. Claude keeps the implementation, product, and
UI strengths. Codex adds independent read-only recon, review, verification,
audit, red-team pressure, structured output, and synthesis judgment.

## No-Omission Rule

No legacy advantage may disappear silently. Each mechanism must be retained,
upgraded, replaced by a stronger mixed equivalent, or recorded as a blocker with
an owner and verification path.

## Legacy Mechanism Coverage

| Area | Claude-only value to keep | Mixed upgrade target |
| --- | --- | --- |
| Visible work | Every teammate visible in tmux | Claude and Codex workers launched through mixed tmux windows only |
| Hierarchy | L1 commands, teammates deliver | S stays with L1; M+ delivery uses L2 branch commanders supervising workers |
| Roles | explore, implement, review, verify, audit | Codex defaults to explore/review/verify/audit; Claude defaults to implement/product/UI |
| Communication | inbox/outbox, broadcast, SendMessage discipline | locked inbox + events + tmux wake-up, inbox before notification |
| State | registry, locks, taskboard | locked mixed registry, monotonic task states, explicit reconcile |
| Dependencies | campaign tasks block on dependencies | dependency graph is a real scheduler gate |
| Approval | gate block/approve | mixed gate records with approval audit trail |
| Patrol | notice, remediate, reinspect, release | patrol becomes a release gate and mixed status surface |
| Inspector | LLM patrol, warning escalation, adaptive memory | mixed inspector reads L1/L2 tmux and mixed registry/events |
| Review | paired review before trust | Codex review branches are independent and read-only |
| Verify | integration and runtime evidence | Codex verify branches run isolated HOME/tmux checks |
| Audit | any FAIL fails release | Codex audit/red-team + Claude implementation separation |
| Retrospective | after-action review extracts learnings | release gate consumes retrospector evidence before completion |
| Observations | repeated failure pattern detection | mixed events/results feed observations and protocol learning |
| Metrics | tasks, warnings, audit/recon rates | mixed metrics include throughput, quality, and false-positive rates |
| Protocol evolution | proposals from metrics | mixed proposals require review/audit before adoption |
| Tactics | memory/tactics and citation scoring | startup prompts load tactics; retro writes candidates with evidence |
| Skills | generated skills with capacity/validation | skill generation stays discoverable and validated, never dropped to hide warnings |
| Heartbeat/GC | commander heartbeat, dead-session cleanup | mixed heartbeat and GC keep sessions honest without mutating read-only status |
| War-room/status | operator sees the whole team | mixed view/status shows L1, L2, workers, blockers, patrol, retro, gates |
| Lifecycle | retain context when useful, disband when safe | failed/blocked or context-rich L2 stays alive; idle completed L2 can disband |
| Docs | README and protocol files teach operators | docs match runtime evidence and include old-to-new parity guarantees |

## Execution Tasks

### Phase A: Legacy Recon And Parity Baseline

- [ ] **T01 legacy-inventory-claude-mechanisms** - Codex explore. Compare commit `137d861` Claude-only files with current mixed files. Scope: `README.md`, `scripts/legion.sh`, `scripts/legion-commander.py`, `scripts/legion-patrol.sh`, `scripts/retrospector.sh`, `scripts/hooks/`, `memory/`, `.agents/skills/`. Output a mechanism matrix with retained, missing, upgraded, and blocked rows.
- [ ] **T02 mixed-gap-map** - Codex explore. Read current `mixed-registry.json`, `events.jsonl`, commander inboxes, and `.planning/communication-upgrade/`. Output concrete runtime gaps, not only doc gaps.
- [ ] **T03 requirements-parity-lock** - Claude product. Append locked requirements for all rows in the coverage table to `.planning/REQUIREMENTS.md`, `.planning/DECISIONS.md`, and `.planning/STATE.md`.

### Phase B: Hierarchy, Routing, And Ownership

- [ ] **T04 enforce-l1-no-delivery** - Claude implement. In `scripts/legion_core.py`, block L1 completion/acceptance for M+ delivery roles unless explicitly marked command-plane maintenance; S-level work may remain with L1.
- [ ] **T05 codex-claude-role-policy** - Claude implement with Codex review. Keep provider defaults: Codex for explore/review/verify/audit/security, Claude for implement/product/UI. Add tests that `--corps` preserves this split.
- [ ] **T06 file-scope-and-lock-policy** - Claude implement. Preserve file-scope ownership and add overlap warnings or blocks for concurrent implementation scopes.

### Phase C: Durable State And Communication

- [ ] **T07 registry-transaction-locks** - Claude implement. All mixed registry mutations use one transaction helper with flock, reread, validate, atomic replace, and monotonic terminal states.
- [ ] **T08 inbox-event-locks** - Claude implement. Inbox and events JSONL appends use locks, message ids, parseable rows, and correlation ids.
- [ ] **T09 inbox-before-tmux** - Claude implement. `mixed msg` and `broadcast` persist inbox records before tmux notification; tmux failure records `delivered_tmux=false`.
- [ ] **T10 readiness-trust-protocol** - Claude implement. Readiness requires order id, nonce, freshness, direct L2 validation, active status, parent match, and non-forgeable sender context.
- [ ] **T11 status-reconcile-split** - Claude implement. `mixed status` is read-only; repair/reconcile mutates explicitly and records events.

### Phase D: Patrol, Inspector, And Approval

- [ ] **T12 mixed-patrol-status** - Claude implement. Add mixed patrol status that correlates patrol notices, gate files, registry commander ids, events, and tmux liveness.
- [ ] **T13 patrol-release-gate** - Codex audit. Final release cannot PASS with unresolved patrol notices, M+ L1 delivery bypass, or unapproved gate blocks.
- [ ] **T14 mixed-inspector-loop** - Claude implement. Port legacy inspector behavior to mixed: screen snapshots, task-scale judgment, warning escalation, violation gate, inbox notice, and adaptive false-positive memory.
- [ ] **T15 gate-approval-audit-trail** - Claude implement. Gate block/approve writes locked events and links approval to the blocked patrol or inspector decision.
- [ ] **T16 commissar-reminders** - Claude implement. Preserve protocol reminder broadcasts for active commanders and adapt them to mixed inbox/events.

### Phase E: Review, Verify, Audit Quality Gates

- [ ] **T17 auto-independent-quality-branches** - Claude implement. M+ and all release campaigns auto-inject or require independent review, verify, and audit gates.
- [ ] **T18 codex-readonly-sandbox-discipline** - Codex audit. Verify read-only Codex branches cannot mutate working tree or runtime state except through approved result reporting.
- [ ] **T19 final-synthesis-fail-closed** - Codex audit. Any failed review, verify, audit, patrol, or retrospective gate makes final synthesis FAIL or WATCH, never PASS.

### Phase F: Retrospective, Memory, Skills, And Learning

- [ ] **T20 mixed-retrospector-sources** - Claude implement. Extend retrospector inputs to include mixed registry, events, run results, failed/blocked tasks, and inspector memory.
- [ ] **T21 retrospective-release-gate** - Codex audit. Release gate runs or consumes `retrospector.sh quick`; candidates require full extraction or a recorded blocker.
- [ ] **T22 after-action-learning-writeback** - Claude implement. Write mixed after-action results to `.planning/retrospectives/` before memory/tactics promotion.
- [ ] **T23 tactics-index-and-citation** - Claude implement. Preserve tactic score, citation, eviction, and startup loading for both global and project tactics.
- [ ] **T24 generated-skill-safety** - Codex review. Ensure generated skills keep frontmatter, trigger coverage, validation, capacity rules, and discoverability.
- [ ] **T25 metrics-and-protocol-evolution** - Claude implement. Mixed metrics track tasks, warnings, violations, audit pass/fail, recon rate, false positives, and protocol proposals.

### Phase G: Lifecycle, UX, And Operations

- [ ] **T26 heartbeat-and-gc-mixed** - Claude implement. Preserve heartbeat, dead-session detection, stale commander cleanup, tmp cleanup, and inbox/broadcast GC without read-only status mutation.
- [ ] **T27 war-room-and-status-ux** - Claude implement. Mixed status/view/war-room show L1, L2, worker windows, blockers, gates, patrol, retro, and release evidence.
- [ ] **T28 lifecycle-retain-disband-policy** - Claude implement. Failed/blocked/context-rich L2 stays alive; completed context-free campaign L2 receives DISBAND and tmux cleanup.
- [ ] **T29 install-and-hook-sync** - Claude implement. Keep global/local script sync, hooks, skills, schemas, and bare `legion` wrapper aligned.
- [ ] **T30 docs-runtime-contract** - Claude product. Update README, AGENTS, CLAUDE, and `.planning/communication-upgrade/` with exact operator commands and parity guarantees.

### Phase H: Verification And Release

- [ ] **T31 unit-contract-tests** - Claude implement. Add tests for every parity mechanism in `tests/test_legion_core.py` and hook/script syntax checks.
- [ ] **T32 isolated-runtime-verification** - Codex verify. Run mixed campaign, msg, broadcast, readiness, status, patrol, and retrospector in isolated HOME/tmux.
- [ ] **T33 adversarial-redteam** - Codex audit. Attack forged readiness, stale inbox rows, malicious commander ids, offline sessions, oversized messages, prompt injection, direct M+ L1 delivery, and fake retrospective evidence.
- [ ] **T34 no-omission-release-matrix** - Codex audit. Produce the final matrix. Any missing, unverified, or weaker-than-legacy mechanism blocks PASS.

## Provider Strategy

- Claude owns implementation, product contract, docs, lifecycle, UX, and hook integration.
- Codex owns read-only recon, review, verification, audit, red-team attacks, and final synthesis.
- Mixed campaign must use `--corps` so L2 branch commanders supervise their own specialty.
- Every implementation task declares file scope. No task may write outside its declared scope.
- Review, verify, audit, patrol, and retrospective gates are independent of implementation.
