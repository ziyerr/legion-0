"""Tests for the canonical Memory Store (v2 schema with embedding/rollup/feedback)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.memory_store import (
    EMBEDDING_DIM,
    HashBagEmbedder,
    MemoryStore,
    SUPPORTED_SCHEMA_VERSIONS,
    apply_reward,
    cosine_similarity,
    decode_embedding,
    encode_embedding,
    main as cli_main,
    normalize_memory,
    validate_memory,
)


def _record(**overrides) -> dict:
    base = {
        "memory_id": "",
        "memory_type": "thought",
        "scope": "project",
        "source_app": "legion",
        "source_type": "manual",
        "source_id": "src-1",
        "source_file": "",
        "project_hash": "phash",
        "project_path": "/proj",
        "legion_id": "",
        "commander_id": "",
        "parent_commander_id": "",
        "campaign_id": "",
        "task_id": "",
        "rollup_level": "",
        "title": "Sample title",
        "summary": "Sample summary",
        "content": "Sample content body",
        "evidence": ["ev/one.md"],
        "tags": ["alpha"],
        "confidence": 0.5,
        "permissions": {},
        "invalidated_by": [],
    }
    base.update(overrides)
    return base


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.db")


def test_ingest_and_load_roundtrip(store: MemoryStore):
    rec = store.upsert(_record(title="alpha", summary="alpha sample", content="alpha beta gamma"))
    assert rec["memory_id"]
    assert rec["schema_version"] == 2
    assert rec["reference_count"] == 0
    assert rec["last_referenced_at"] == ""
    assert rec["reward_signal"] == 0.0

    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0]["memory_id"] == rec["memory_id"]
    assert loaded[0]["title"] == "alpha"
    assert loaded[0]["content_hash"] == rec["content_hash"]


def test_fts_and_lexical_fallback(store: MemoryStore):
    store.upsert(_record(memory_id="rec-fts", title="alpha hits", content="lookup token alpha", task_id="t1"))
    fts_results = store.search("alpha", track_reference=False)
    assert fts_results, "FTS path should match"
    assert any(r["memory_id"] == "rec-fts" for r in fts_results)

    with store.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS memory_fts")
        conn.commit()

    lex_results = store.search("alpha", track_reference=False)
    assert lex_results, "lexical fallback should match after FTS dropped"
    assert any(r["memory_id"] == "rec-fts" for r in lex_results)


def test_embedding_blob_persisted(store: MemoryStore):
    store.upsert(_record(memory_id="rec-emb", title="dog runs", content="cat sits"))
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT embedding FROM memories WHERE memory_id = ?", ("rec-emb",)).fetchone()
    assert row is not None
    assert row[0] is not None
    assert len(row[0]) == EMBEDDING_DIM * 4


def test_semantic_search_via_cosine(store: MemoryStore):
    store.upsert(_record(memory_id="match", title="alpha beta", content="alpha beta gamma delta", tags=["alpha"]))
    store.upsert(_record(memory_id="other", title="zeta", content="zeta theta omega", tags=["zeta"]))
    results = store.search("alpha beta gamma", track_reference=False)
    assert results, "search should produce results"
    assert results[0]["memory_id"] == "match"
    # cosine boost should produce a positive non-trivial score
    assert results[0]["score"] > 0.05
    # embedding stripped from output
    assert "embedding" not in results[0]


def test_v1_to_v2_migration(tmp_path: Path):
    db_path = tmp_path / "v1.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memories (
            memory_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            memory_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            source_app TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_file TEXT NOT NULL,
            project_hash TEXT NOT NULL,
            project_path TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            content TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            permissions_json TEXT NOT NULL,
            invalidated_by_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            content_hash TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "old-1", 1, "thought", "project", "legion", "manual", "src", "", "phash", "/proj",
            "Old title", "Old summary", "Old content body",
            json.dumps(["legacy.md"]), json.dumps(["legacy"]), 0.7,
            json.dumps({}), json.dumps([]), "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
            "legacy-hash-1234",
        ),
    )
    conn.commit()
    conn.close()

    store = MemoryStore(db_path)
    records = store.load_all()
    assert len(records) == 1
    rec = records[0]
    assert rec["memory_id"] == "old-1"
    assert rec["title"] == "Old title"
    assert rec["confidence"] == 0.7
    assert rec["content_hash"] == "legacy-hash-1234"
    assert rec["reference_count"] == 0
    assert rec["last_referenced_at"] == ""
    assert rec["reward_signal"] == 0.0
    assert rec["embedding"] == []  # no embedding set for legacy row

    with store.connection() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
    for required in ("embedding", "reference_count", "last_referenced_at", "reward_signal",
                     "legion_id", "commander_id", "task_id", "rollup_level"):
        assert required in cols, f"missing column after migration: {required}"


def test_induce_rollup_threshold(store: MemoryStore):
    for i in range(5):
        store.upsert(_record(memory_id=f"task-mem-{i}", task_id="t-shared", title=f"task entry {i}",
                              summary=f"work item {i}", content=f"content body {i}"))
    for i in range(2):
        store.upsert(_record(memory_id=f"other-mem-{i}", task_id="t-orphan", title=f"orphan {i}"))

    produced = store.induce_rollups(threshold=5, levels=["task"])
    assert len(produced) == 1
    rollup = produced[0]
    assert rollup["rollup_level"] == "task"
    assert rollup["memory_type"] == "summary"
    assert rollup["task_id"] == "t-shared"


def test_induce_rollup_idempotent(store: MemoryStore):
    for i in range(5):
        store.upsert(_record(memory_id=f"r-{i}", task_id="t-id", content=f"body {i}"))
    first = store.induce_rollups(threshold=5, levels=["task"])
    second = store.induce_rollups(threshold=5, levels=["task"])
    assert len(first) == 1
    assert len(second) == 0


def test_apply_feedback_clamps(store: MemoryStore):
    rec = store.upsert(_record(memory_id="fb", confidence=0.5))
    up = store.apply_feedback(rec["memory_id"], reward=1.0)
    assert up["new_confidence"] > 0.5
    assert up["new_confidence"] <= 1.0

    down = store.apply_feedback(rec["memory_id"], reward=-1.0)
    assert down["new_confidence"] < up["new_confidence"]
    assert down["new_confidence"] >= 0.0

    saturate_high = store.apply_feedback(rec["memory_id"], reward=1000.0)
    assert saturate_high["new_confidence"] == 1.0

    saturate_low = store.apply_feedback(rec["memory_id"], reward=-1000.0)
    assert saturate_low["new_confidence"] == 0.0


def test_search_tracks_reference(store: MemoryStore):
    rec = store.upsert(_record(memory_id="ref-track", title="alpha", content="alpha beta"))
    initial = store.load_all()[0]["reference_count"]
    assert initial == 0
    for _ in range(3):
        results = store.search("alpha")
        assert any(r["memory_id"] == "ref-track" for r in results)
    record = next(r for r in store.load_all() if r["memory_id"] == "ref-track")
    assert record["reference_count"] == 3
    assert record["last_referenced_at"] != ""


def test_search_no_track(store: MemoryStore):
    rec = store.upsert(_record(memory_id="no-track", title="alpha", content="alpha gamma"))
    for _ in range(3):
        store.search("alpha", track_reference=False)
    record = next(r for r in store.load_all() if r["memory_id"] == "no-track")
    assert record["reference_count"] == 0
    assert record["last_referenced_at"] == ""


def test_compact_dedup_preserves_high_confidence(store: MemoryStore):
    # Same summary/content/evidence; different confidence; compact keeps higher.
    base = dict(summary="dup summary", content="dup content body",
                evidence=["dup.md"], tags=["dup"])
    store.upsert(_record(memory_id="low", confidence=0.2, **base))
    store.upsert(_record(memory_id="high", confidence=0.9, **base))
    removed = store.compact()
    assert removed == 1
    surviving_ids = {rec["memory_id"] for rec in store.load_all()}
    assert "high" in surviving_ids


def test_export_jsonl_roundtrip(tmp_path: Path):
    src = MemoryStore(tmp_path / "src" / "memory.db")
    src.upsert(_record(memory_id="r1", title="alpha", content="alpha bravo"))
    src.upsert(_record(memory_id="r2", title="charlie", content="charlie delta", task_id="t-x"))
    src.export_jsonl()
    backup = src.backup_jsonl
    assert backup.exists()
    src_records = sorted(src.load_all(), key=lambda r: r["memory_id"])

    dst = MemoryStore(tmp_path / "dst" / "memory.db")
    count = dst.ingest_jsonl(backup)
    assert count == 2
    dst_records = sorted(dst.load_all(), key=lambda r: r["memory_id"])
    src_hashes = [r["content_hash"] for r in src_records]
    dst_hashes = [r["content_hash"] for r in dst_records]
    assert src_hashes == dst_hashes


def test_validate_accepts_v1_input():
    rec = normalize_memory(_record(memory_id="ok", schema_version=1))
    assert rec["schema_version"] == 2
    err = validate_memory(rec)
    assert err == ""
    # If we manually downgrade to 1 (e.g., legacy ingest input), validation still passes.
    rec_v1 = dict(rec)
    rec_v1["schema_version"] = 1
    assert validate_memory(rec_v1) == ""
    rec_bad = dict(rec)
    rec_bad["schema_version"] = 99
    assert validate_memory(rec_bad) != ""
    assert SUPPORTED_SCHEMA_VERSIONS == (1, 2)


def test_embedding_helpers():
    embedder = HashBagEmbedder()
    a = embedder.embed("alpha beta gamma")
    b = embedder.embed("alpha beta gamma")
    c = embedder.embed("zeta theta")
    assert len(a) == EMBEDDING_DIM
    assert a == b
    assert cosine_similarity(a, b) == pytest.approx(1.0, rel=1e-6)
    assert cosine_similarity(a, c) < 0.99
    blob = encode_embedding(a)
    assert blob is not None
    assert len(blob) == EMBEDDING_DIM * 4
    decoded = decode_embedding(blob)
    assert len(decoded) == EMBEDDING_DIM
    for x, y in zip(a, decoded):
        assert abs(x - y) < 1e-5
    assert decode_embedding(None) == []
    assert encode_embedding(None) is None
    assert apply_reward(0.5, 1.0) == pytest.approx(0.55)
    assert apply_reward(0.0, -1.0) == 0.0
    assert apply_reward(1.0, 5.0) == 1.0


def test_cli_apply_feedback_and_induce(tmp_path: Path, capsys):
    db = tmp_path / "cli" / "memory.db"
    store = MemoryStore(db)
    for i in range(5):
        store.upsert(_record(memory_id=f"cli-{i}", task_id="cli-task", content=f"body {i}"))

    rc = cli_main([str(db), "apply-feedback", "cli-0", "--reward", "1.0"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["memory_id"] == "cli-0"
    assert payload["new_confidence"] > payload["prev_confidence"]

    rc = cli_main([str(db), "induce-rollup", "--threshold", "5", "--levels", "task"])
    assert rc == 0
    out = capsys.readouterr().out
    produced = json.loads(out)
    assert isinstance(produced, list)
    assert len(produced) == 1
    assert produced[0]["rollup_level"] == "task"


def test_cli_apply_feedback_missing_id_graceful(tmp_path: Path, capsys):
    db = tmp_path / "cli-missing" / "memory.db"
    # Touch the store so the schema exists; no records inserted.
    MemoryStore(db).export_jsonl()

    rc = cli_main([str(db), "apply-feedback", "non-existent", "--reward", "1.0"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "memory_id not found" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_induce_rollup_rejects_threshold_zero(store: MemoryStore):
    with pytest.raises(ValueError, match="threshold must be >= 1"):
        store.induce_rollups(threshold=0)


def test_cli_induce_rollup_rejects_zero(tmp_path: Path, capsys):
    db = tmp_path / "cli-zero" / "memory.db"
    MemoryStore(db).export_jsonl()

    rc = cli_main([str(db), "induce-rollup", "--threshold", "0"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "threshold must be >= 1" in captured.err
