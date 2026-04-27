# Release Retrospective Contract

Date: 2026-04-25
Owner: mixed Legion communication-upgrade campaign
Companion to:
- `00-RUNTIME-CONTRACT.md` ("Patrol, Retrospective, And Learning Boundary")
- `01-IMPLEMENTATION-PLAN.md` (Phase 6: Release Gate)
- `02-VERIFICATION-GATES.md` (Gate 10: Mixed Retrospective Continuity)
- `03-LEGACY-INHERITANCE-TASKLIST.md` (T20-T23, Phase F)
- `04-LEGACY-PARITY-MATRIX.md` (Row 15: Retrospective)

## Purpose

The legacy Claude-only Legion always closed a release with `retrospector.sh`.
The mixed Legion must preserve that loop as a fail-closed release gate, not as
an optional hook. This document is the normative contract that
`scripts/retrospector.sh` (repaired under `repair-retrospector-script-v4`) and
the release synthesis must satisfy. It defines required inputs, mode behavior,
blocker handling, writeback expectations, and the release-gate rule.

It does not define how to implement the script. The dependent task owns the
script. This document defines what the script and the release gate must
guarantee, regardless of provider (Claude or Codex) running them.

## Restored Runtime Evidence

`repair-retrospector-script-v4` restored the mixed-source ingestion path while
preserving the useful Claude-only after-action loop. The v13 repair hardens
that path for read-only Codex workers: `quick` no longer depends on runtime
shell heredocs, accounts for I1-I8, emits run id/hash evidence, and explicitly
scans `LEGION_DIR/daemon_evidence.jsonl` in addition to observations and
`inspector_memory.json`.

`repair-retrospective-disposition-v16` restored the release disposition rule
for historical extraction records: historical-only candidates remain visible
for learning without forcing release WATCH by themselves. Explicit blockers,
current WATCH sources, and current FAIL candidates still force non-PASS.
Verification recorded by the repair: `python3 -m unittest tests.test_retrospector_contract`
passed (4 tests OK) and `bash -n scripts/retrospector.sh` passed.

That restoration does not lower the gate. Quick mode evidence proves the
sources are wired; release PASS still requires the classification/writeback
rules below. If quick mode reports candidates, `full` extraction or an explicit
STATE.md blocker is still mandatory.

## Required Mixed Inputs

A retrospective run must read every input below. Missing inputs are not silent
skips; they are blockers.

| # | Input | Source | Required content |
| --- | --- | --- | --- |
| I1 | Mixed registry snapshot | `mixed-registry.json` | commanders, parent/level/lifecycle, tasks with status, scope, dependencies, readiness orders |
| I2 | Event log | `events.jsonl` | accepted state transitions, message delivery outcomes, gate block/approve, repair events, and available correlation ids; append locking and release-grade ids/correlation are required. `repair-event-correlation-evidence-v16` proves the current B9 contract, and any future run missing these fields must record an explicit blocker |
| I3 | Worker run results | `runs/<task>/result.md` for every task that reached a terminal state in the campaign window | strict whole-file JSON outcome, files touched, verification evidence, findings, and risks; prose-wrapped or schema-invalid results are failure evidence |
| I4 | Failed and blocked task records | registry filtered by status `failed`/`blocked` plus matching events | reason, owner, dependency edges, last transition |
| I5 | Inspector / daemon memory | `inspector_memory.json`, hook `observations.jsonl`, and `LEGION_DIR/daemon_evidence.jsonl` | recent warnings, daemon/hook evidence, citations, eviction state; missing daemon evidence is an explicit WATCH unless a stronger mixed-native replacement is cited |
| I6 | Project truth state | `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, `.planning/DECISIONS.md` | open blockers (B1-B10), locked decisions, current requirements |
| I7 | Patrol evidence | non-mutating patrol evidence scan (`scripts/legion-patrol.sh` presence, patrol notice files, gate files, related mixed events) or captured `legion-patrol.sh status` equivalent | unresolved notices, gate blocks, approval audit trail, and whether evidence came from a direct status capture or the retrospector's read-only scan |
| I8 | Legacy parity matrix | `04-LEGACY-PARITY-MATRIX.md` | every BLK row that must be cleared before PASS |

A retrospective that reads only I1+I2 (or only legacy observation files) does
not satisfy this contract. The release synthesis must verify that each I1-I8
source was opened or an explicit blocker recorded for the missing source.
Legacy daemon evidence and mixed runtime evidence must both stay visible unless
a stronger mixed-native replacement is cited.

## Quick Mode Behavior

Command: `bash scripts/retrospector.sh quick`

Required behavior:

- Quick mode is read-only. It must not mutate registry, inbox, events, or
  `.planning/STATE.md`. It produces a candidate report only and must be usable
  in no-temp read-only Codex workers.
- Quick mode must scan I1-I8 and emit a structured candidate report containing,
  at minimum: candidate count, candidate ids, source pointers (registry task
  id, event id, run path, STATE.md anchor), severity, and proposed extraction
  type (incident, learning, tactic, protocol-evolution, skill).
- I7 does not require quick mode to execute `legion-patrol.sh status` itself.
  A read-only scan of the patrol script, patrol notice files, gate files, and
  related mixed events satisfies I7 when the report marks it as a
  non-mutating source scan. A captured patrol-status equivalent is also valid
  when cited by path/run id.
- Direct quick mode defaults project truth to the current working directory.
  Inherited `PROJECT_DIR`, `PLANNING_DIR`, `LEGION_DIR`, or `MIXED_DIR` values
  that resolve outside cwd's project boundary are ignored unless
  `RETROSPECTOR_TRUST_PROJECT_DIR=1` (or an equivalent retrospector boundary
  trust marker) is set; the JSON report must record the ignored values in
  `run.project_boundary`.
- Quick mode must classify the run as one of:
  - `zero-candidates` — every input was opened, nothing extractable found.
  - `candidates-pending` — at least one candidate identified; full extraction
    is required before release synthesis.
  - `blocked` — an input was unreadable or an environment dependency failed;
    full extraction cannot run.
- Quick mode must print exit-code semantics that the release gate can rely on:
  zero for any successful classification, non-zero only when the script itself
  cannot complete (process error, missing dependency, unreadable input).
- Quick mode output must include the exact command line, timestamp, working
  directory, and a content hash or run id that downstream gates can cite as
  evidence.

The release gate consumes quick-mode evidence; quick mode by itself never
constitutes PASS.

## Full Extraction Behavior

Command: `bash scripts/retrospector.sh full` (or the equivalent extraction path
the script exposes).

Required behavior:

- Full extraction is required whenever quick mode reported
  `candidates-pending`. It is optional only when quick mode reported
  `zero-candidates`.
- Full extraction must read the same I1-I8 inputs and re-classify; it may not
  trust the quick report alone. Stale quick reports are not authoritative. The
  release-gate extraction path may be deterministic; an LLM is optional and
  must not be required to create the release evidence record.
- Full extraction must produce a per-release retrospective record in
  `.planning/retrospectives/<YYYY-MM-DD>-<campaign-slug>.md` containing:
  - the campaign and release identifier;
  - the inputs opened (with paths and run ids);
  - extracted learnings, each with evidence pointers and proposed durable
    destination (project-truth file, memory/tactics, generated skill);
  - any candidate that was rejected, with the rejection reason;
  - a verdict line: `verdict: pass | watch | fail` matching the release-gate
    rule below;
  - a writeback summary listing every file the run is responsible for
    updating.
- Full extraction must treat strict worker result files as authoritative:
  a task with no parseable result, schema-invalid result, or `status` other
  than `completed` is a learning/blocker candidate, even if the process exited
  0.
- Full extraction must distinguish historical candidates from current release
  blockers. Historical-only candidates are kept in the retrospective record
  and may become learnings, but they do not by themselves force WATCH after
  `repair-retrospective-disposition-v16`. Explicit blockers, current WATCH
  sources, and current FAIL candidates still force `watch` or `fail`.
- Promotion to memory/tactics or generated skills is allowed only after the
  retrospective record exists and only when the candidate is cross-session
  reusable and not a duplicate. Project-truth writeback (`.planning/`) is
  always first; memory/tactics and skills are downstream.
- Full extraction must write through the locked event-log helper so that each
  extraction action is auditable and correlates to the registry transaction
  and run id. The event must include at least a timestamp, event id or content
  hash, correlation id/run id, classification, verdict, and retrospective path.

## Blocker Handling

The retrospective gate is fail-closed. Any of the following is a release
blocker, not a silent skip:

1. **Missing input** — any of I1-I8 is unreadable, absent, or out of date for
   the campaign window. The blocker entry names the missing input, the path
   attempted, and the underlying error. The daemon evidence sub-input under I5
   is a documented WATCH when absent, because some isolated runs have no
   daemon history; release synthesis may not PASS unless it cites a stronger
   mixed-native replacement or accepts the WATCH verdict.
2. **Environment failure** — script cannot run (missing interpreter, locked
   files, permission errors, unavailable tmux/registry helpers). The blocker
   entry includes the exact command and exit status.
3. **Stale candidates** — quick mode reported `candidates-pending` and full
   extraction did not run, or completed without producing the
   `.planning/retrospectives/` record.
4. **Unmapped legacy row** — a row in `04-LEGACY-PARITY-MATRIX.md` is `BLK`
   and the retrospective did not name a repair task and verification path for
   it.
5. **Forged or fabricated evidence** — extracted learnings cite events,
   results, or registry rows that do not exist. Red-team T33 must be able to
   detect this; the retrospective must fail.

Recording a blocker satisfies the contract only when the blocker entry lands
in `.planning/STATE.md` (see next section) and is referenced from the release
synthesis verdict.

## STATE.md Writeback Expectations

After every retrospective run that touches the release gate, `.planning/STATE.md`
must reflect the outcome before any user-facing completion claim:

- A `Retrospective` block must record:
  - run timestamp, command, and run id from the quick or full output;
  - classification (`zero-candidates`, `candidates-pending`, `extracted`, or
    `blocked`);
  - links to the retrospective record under `.planning/retrospectives/` when
    extraction ran;
  - explicit blocker entries for each blocker in the section above, with
    owner and repair task id from `03-LEGACY-INHERITANCE-TASKLIST.md`
    (typically T20, T21, T22, or T23).
- Existing blocker/watch entries B1-B10 in `STATE.md` may not be removed by a
  retrospective run; only the owning repair task's verification gate may clear
  or downgrade them. The retrospective may add or update its own entries.
- `STATE.md` writeback must occur through the same locked-event audit trail as
  any other registry-affecting change so that the release synthesis can
  correlate the writeback with the run.
- Empty or zero-candidate runs still write a `STATE.md` entry stating "zero
  candidates, inputs opened: I1-I8". A silent skip is a blocker by itself.

## Release Synthesis Rule

The release synthesis (the final L1/L2 verdict for the communication-upgrade
campaign) must obey:

- **No retrospective evidence, no PASS.** If `STATE.md` does not contain a
  retrospective entry whose run id matches a quick or full retrospector
  output for the current release, the verdict is `FAIL`. This applies even
  when every other gate (1-9, 11) has passed.
- **Pending candidates, no PASS.** If the latest retrospective entry is
  classified `candidates-pending` and no full extraction record exists at
  `.planning/retrospectives/<...>.md`, the verdict is `FAIL` or `WATCH`,
  never `PASS`.
- **Historical-only candidates do not force WATCH.** A full extraction record
  may preserve historical learning candidates without making release
  non-PASS, provided the record has no explicit blockers, no current WATCH
  sources, and no current FAIL candidates. Evidence:
  `repair-retrospective-disposition-v16` with `python3 -m unittest tests.test_retrospector_contract`
  and `bash -n scripts/retrospector.sh`.
- **Blocked retrospective, no PASS.** Any retrospective blocker recorded in
  `STATE.md` (missing input, environment failure, stale candidates, unmapped
  legacy row, fabricated evidence) forces `FAIL` or `WATCH`.
- **Zero candidates is PASS-eligible.** A `zero-candidates` classification
  with all I1-I8 inputs opened, written to `STATE.md`, and consistent with
  the legacy parity matrix is sufficient retrospective evidence; the verdict
  may be `PASS` if every other gate passes.
- **Docs alone are not evidence.** Adding sections to `00-RUNTIME-CONTRACT.md`
  or this file does not satisfy the rule. The synthesis must cite a concrete
  run id and STATE.md entry.

This rule is the retrospective half of the no-omission release gate
(`04-LEGACY-PARITY-MATRIX.md` row 15 and row 35). It composes with Gate 9
(patrol) and Gate 11 (no-omission matrix); any of the three failing forces
non-PASS.

## Cross-Reference Index

- Runtime boundary: `00-RUNTIME-CONTRACT.md` "Patrol, Retrospective, And
  Learning Boundary".
- Implementation phase: `01-IMPLEMENTATION-PLAN.md` Phase 6 retrospective
  step.
- Gate definition: `02-VERIFICATION-GATES.md` Gate 10.
- Repair tasks: `03-LEGACY-INHERITANCE-TASKLIST.md` T20
  (mixed-retrospector-sources), T21 (retrospective-release-gate), T22
  (after-action-learning-writeback), T23 (tactics-index-and-citation).
- Parity row: `04-LEGACY-PARITY-MATRIX.md` row 15 (Retrospective) and row 35
  (no-omission release gate).
- State and blockers: `.planning/STATE.md` (B6 legacy bridge, retrospective
  entries appended per run).
- Locked decisions: `.planning/DECISIONS.md` (legacy parity, no split-brain
  on legacy surfaces).
- Requirements: `.planning/REQUIREMENTS.md` R35 (legacy bridges or
  mixed-native equivalents the release gate consumes).
