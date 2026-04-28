# memory-uplift-implement — worker report

- task_id: memory-uplift-implement
- commander: L2-implement-1777385295
- status: PASS
- timestamp: 2026-04-28

## files_touched
- scripts/memory_store.py — schema v2 (`MEMORY_SCHEMA_VERSION = 2`), V2 columns (`embedding BLOB`, `reference_count`, `last_referenced_at`, `reward_signal`), `EmbeddingProvider` + `HashBagEmbedder` (sha1 → 128-dim, L2-norm, struct-pack BLOB), helpers (`encode_embedding` / `decode_embedding` / `cosine_similarity` / `clamp_unit` / `apply_reward`), `default_embedder()` w/ `LEGION_MEMORY_EMBED_PROVIDER` hook, `_migrate_schema` ALTER for V2 columns, upsert recomputes embedding & writes BLOB, search adds cosine fusion (0.6·fts + 0.4·max(0,cos)) with track_reference side-effect (`SEARCH_REWARD_SIGNAL=0.5`, batched UPDATE + `referenced` event), `_track_reference`, `apply_feedback` (formula `clamp(old·0.9 + reward·0.1, 0, 1)`), `induce_rollups` (levels task→commander→legion→project, threshold-gated, `rolled_up` event for idempotency), CLI `apply-feedback` / `induce-rollup` / `--no-track`. `validate_memory` accepts both v1 and v2 inputs via `SUPPORTED_SCHEMA_VERSIONS=(1,2)`; normalize unifies output to v2. `content_hash` excludes mutable v2 fields so reference/feedback writes don't invalidate the hash.
- schemas/legion-memory.schema.json — `schema_version` enum [1,2]; new `embedding` (array|null), `reference_count` (int≥0), `last_referenced_at` (string), `reward_signal` (number); last three required, `embedding` optional.
- tests/test_memory_store.py — new file, 15 tests, pytest tmp_path isolated.

## verification commands & tail output

### `python3 -m py_compile scripts/memory_store.py`
```
PY_COMPILE_OK
```

### `python3 -m pytest tests/test_memory_store.py -v` (full output)
```
============================= test session starts ==============================
platform darwin -- Python 3.14.4, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/feijun/Documents/legion-0
collecting ... collected 15 items

tests/test_memory_store.py::test_ingest_and_load_roundtrip PASSED        [  6%]
tests/test_memory_store.py::test_fts_and_lexical_fallback PASSED         [ 13%]
tests/test_memory_store.py::test_embedding_blob_persisted PASSED         [ 20%]
tests/test_memory_store.py::test_semantic_search_via_cosine PASSED       [ 26%]
tests/test_memory_store.py::test_v1_to_v2_migration PASSED               [ 33%]
tests/test_memory_store.py::test_induce_rollup_threshold PASSED          [ 40%]
tests/test_memory_store.py::test_induce_rollup_idempotent PASSED         [ 46%]
tests/test_memory_store.py::test_apply_feedback_clamps PASSED            [ 53%]
tests/test_memory_store.py::test_search_tracks_reference PASSED          [ 60%]
tests/test_memory_store.py::test_search_no_track PASSED                  [ 66%]
tests/test_memory_store.py::test_compact_dedup_preserves_high_confidence PASSED [ 73%]
tests/test_memory_store.py::test_export_jsonl_roundtrip PASSED           [ 80%]
tests/test_memory_store.py::test_validate_accepts_v1_input PASSED        [ 86%]
tests/test_memory_store.py::test_embedding_helpers PASSED                [ 93%]
tests/test_memory_store.py::test_cli_apply_feedback_and_induce PASSED    [100%]

============================== 15 passed in 0.12s ==============================
```

## deviations from spec
- **Test list extended**: kept all 12 cases the spec named (with `test_search_tracks_reference` and `test_search_no_track` as separate functions) and added `test_validate_accepts_v1_input`, `test_embedding_helpers`, `test_cli_apply_feedback_and_induce` for pure-helper and CLI smoke coverage. Strict superset.
- **`content_hash` excludes mutable v2 fields** (`embedding` / `reference_count` / `last_referenced_at` / `reward_signal`) in addition to `content_hash` itself. Spec didn't call this out, but otherwise every search hit (which writes the tracking columns) and every feedback would invalidate the hash, breaking export round-trip and dedup. Reasoning recorded in code via `HASH_EXCLUDED_FIELDS`.
- **Upsert UPDATE clause leaves `reference_count` / `last_referenced_at` / `reward_signal` alone** (only embedding is refreshed). Re-ingesting from the JSONL backup would otherwise zero out live tracking counters.
- **`apply_feedback` does not pre-clamp the reward input** to [-1, 1]; it relies on `apply_reward → clamp_unit` to saturate. Test asserts reward=±1000 → 1.0 / 0.0.
- **`default_embedder()` env hook honored but only `hash-bag` wired** per D1 (provider hook only).
- **Cosine fusion weights**: 0.6 lex + 0.4 max(0, cos), per PLAN.md first-pass guidance.

## known risks / open notes
- **CJK + 128-dim hash collisions**: documented noise (PLAN.md). Provider hook left for future ST swap.
- **`search` default mutates DB**: callers needing read-only must pass `--no-track` / `track_reference=False`.
- **`induce_rollups` idempotency** uses `memory_events.event_type='rolled_up'`; sources updated after rollup are not re-considered. Accepted per first-version scope.
- **`build_rollup` unchanged**; rollup memory now gets its own embedding via `upsert` recompute (derived behavior).
- **Adjacent test failure**: `tests/test_legion_core.py::test_dual_host_cli_attaches_claude_without_opening_dual_view` failed; that file was already modified on this branch before my work and is out of scope (not in my touched files).

## scope adherence
- Touched only the three files declared in the task.
- No edits to `thought_retriever.py`, `scripts/legion_core.py`, `tests/test_legion_core.py`, `.gitignore`, mixed registry, or events.jsonl.
- No new external dependencies (math/os/struct only — all stdlib).
- No git add/commit/push (left for L1).

## report mirrors
- Inbox-style mirror: attempted to write to `/Users/feijun/.claude/legion/bf21e79d/mixed/inbox/memory-uplift-implement-report-L2-implement-1777385295.md` and `.../mixed/runs/memory-uplift-implement/result.md` — both blocked by file-permission policy. This canonical report lives at `.planning/memory-uplift/REPORT.md` (within scope) and is the source of truth.
