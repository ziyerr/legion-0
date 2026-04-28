#!/usr/bin/env python3
"""Canonical local memory store for Legion.

This is the lightweight core behind the higher-level Thought-Retriever,
startup cache, and wiki projections. SQLite is the authoritative store; JSONL
is a rebuildable backup/export, and Markdown outputs are derived views.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

MEMORY_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, 2)
EMBEDDING_DIM = 128
SEARCH_REWARD_SIGNAL = 0.5
REWARD_DECAY = 0.9
REWARD_GAIN = 0.1
TOKEN_RE = re.compile(r"[A-Za-z0-9_\-./\u4e00-\u9fff]+")
STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "must", "should", "into", "when", "then",
    "一个", "以及", "需要", "必须", "如果", "当前", "任务", "文件", "系统",
}
CONTEXT_COLUMNS = {
    "legion_id": "TEXT NOT NULL DEFAULT ''",
    "commander_id": "TEXT NOT NULL DEFAULT ''",
    "parent_commander_id": "TEXT NOT NULL DEFAULT ''",
    "campaign_id": "TEXT NOT NULL DEFAULT ''",
    "task_id": "TEXT NOT NULL DEFAULT ''",
    "rollup_level": "TEXT NOT NULL DEFAULT ''",
}
V2_COLUMNS = {
    "embedding": "BLOB",
    "reference_count": "INTEGER NOT NULL DEFAULT 0",
    "last_referenced_at": "TEXT NOT NULL DEFAULT ''",
    "reward_signal": "REAL NOT NULL DEFAULT 0",
}
FILTER_FIELDS = ("memory_type", "scope", "legion_id", "commander_id", "campaign_id", "task_id", "rollup_level")
HASH_EXCLUDED_FIELDS = ("content_hash", "embedding", "reference_count", "last_referenced_at", "reward_signal")
ROLLUP_BUCKET_KEYS = {
    "task": "task_id",
    "commander": "commander_id",
    "legion": "legion_id",
    "project": "project_hash",
}
DEFAULT_ROLLUP_LEVELS = ("task", "commander", "legion", "project")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def trim_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text.lower()):
        token = token.strip("-_. /")
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def apply_reward(old_confidence: float, reward_signal: float) -> float:
    return clamp_unit(float(old_confidence) * REWARD_DECAY + float(reward_signal) * REWARD_GAIN)


def encode_embedding(vec: list[float] | None) -> bytes | None:
    if not vec:
        return None
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(f"embedding length must be {EMBEDDING_DIM}, got {len(vec)}")
    return struct.pack(f"{EMBEDDING_DIM}f", *(float(v) for v in vec))


def decode_embedding(blob: bytes | memoryview | None) -> list[float]:
    if not blob:
        return []
    raw = bytes(blob) if isinstance(blob, memoryview) else blob
    if len(raw) != EMBEDDING_DIM * 4:
        return []
    return list(struct.unpack(f"{EMBEDDING_DIM}f", raw))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class EmbeddingProvider:
    """Abstract embedding provider. Subclasses implement `embed`."""

    dim: int = EMBEDDING_DIM

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class HashBagEmbedder(EmbeddingProvider):
    """Hash-bag projection embedder. Pure stdlib, deterministic, language-agnostic."""

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = int(dim)

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        text = text or ""
        if not text.strip():
            return vec
        for token in tokenize(text):
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


def default_embedder() -> EmbeddingProvider:
    """Resolve the embedding provider. Only `hash-bag` is implemented; env hook reserved."""
    provider = (os.environ.get("LEGION_MEMORY_EMBED_PROVIDER", "hash-bag") or "hash-bag").strip().lower()
    if provider in ("", "hash-bag", "hashbag", "default"):
        return HashBagEmbedder()
    return HashBagEmbedder()


def _embedding_text(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("title", "") or ""),
        str(record.get("summary", "") or ""),
        str(record.get("content", "") or ""),
        " ".join(str(t) for t in record.get("tags", []) or []),
        " ".join(str(e) for e in record.get("evidence", []) or []),
    ]
    return " ".join(part for part in parts if part)


def normalize_memory(record: dict[str, Any]) -> dict[str, Any]:
    now = iso_now()
    evidence = [str(item) for item in record.get("evidence", []) if str(item).strip()]
    tags = sorted({str(item).strip().lower() for item in record.get("tags", []) if str(item).strip()})
    permissions = dict(record.get("permissions", {}) or {})
    invalidated_by = [str(item) for item in record.get("invalidated_by", []) if str(item).strip()]
    embedding_in = record.get("embedding")
    if embedding_in is None:
        embedding_value: list[float] | None = None
    else:
        try:
            embedding_value = [float(v) for v in embedding_in]
        except (TypeError, ValueError):
            embedding_value = None
    normalized = {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "memory_id": str(record.get("memory_id", "")).strip(),
        "memory_type": str(record.get("memory_type", record.get("type", "thought")) or "thought").strip().lower(),
        "scope": str(record.get("scope", "project") or "project").strip().lower(),
        "source_app": str(record.get("source_app", "legion") or "legion").strip().lower(),
        "source_type": str(record.get("source_type", "manual") or "manual").strip().lower(),
        "source_id": str(record.get("source_id", "")).strip(),
        "source_file": str(record.get("source_file", "")).strip(),
        "project_hash": str(record.get("project_hash", "")).strip(),
        "project_path": str(record.get("project_path", "")).strip(),
        "legion_id": str(record.get("legion_id", "")).strip(),
        "commander_id": str(record.get("commander_id", "")).strip(),
        "parent_commander_id": str(record.get("parent_commander_id", "")).strip(),
        "campaign_id": str(record.get("campaign_id", "")).strip(),
        "task_id": str(record.get("task_id", record.get("source_id", ""))).strip(),
        "rollup_level": str(record.get("rollup_level", "")).strip().lower(),
        "title": trim_text(record.get("title", record.get("summary", "")), 160),
        "summary": trim_text(record.get("summary", ""), 800),
        "content": trim_text(record.get("content", record.get("abstraction", "")), 2400),
        "evidence": evidence[:24],
        "tags": tags[:32],
        "confidence": float(record.get("confidence", 0.5)),
        "permissions": permissions,
        "invalidated_by": invalidated_by,
        "created_at": str(record.get("created_at") or now),
        "updated_at": str(record.get("updated_at") or now),
        "embedding": embedding_value,
        "reference_count": max(0, int(record.get("reference_count", 0) or 0)),
        "last_referenced_at": str(record.get("last_referenced_at", "") or "").strip(),
        "reward_signal": float(record.get("reward_signal", 0.0) or 0.0),
        "content_hash": "",
    }
    normalized["confidence"] = round(clamp_unit(normalized["confidence"]), 4)
    if not normalized["memory_id"]:
        normalized["memory_id"] = "mem-" + stable_hash(
            {
                "memory_type": normalized["memory_type"],
                "scope": normalized["scope"],
                "source_app": normalized["source_app"],
                "source_type": normalized["source_type"],
                "source_id": normalized["source_id"],
                "summary": normalized["summary"],
                "content": normalized["content"],
                "evidence": normalized["evidence"],
            }
        )[:16]
    content = {k: v for k, v in normalized.items() if k not in HASH_EXCLUDED_FIELDS}
    normalized["content_hash"] = stable_hash(content)[:24]
    return normalized


def validate_memory(record: dict[str, Any]) -> str:
    required = {
        "schema_version", "memory_id", "memory_type", "scope", "source_app", "source_type", "source_id",
        "source_file", "project_hash", "project_path", "legion_id", "commander_id", "parent_commander_id",
        "campaign_id", "task_id", "rollup_level", "title", "summary", "content", "evidence", "tags",
        "confidence", "permissions", "invalidated_by", "created_at", "updated_at", "content_hash",
        "reference_count", "last_referenced_at", "reward_signal",
    }
    missing = sorted(required - set(record))
    if missing:
        return f"missing keys: {missing}"
    if record["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        return "unsupported schema_version"
    if not record["memory_id"] or not record["memory_type"] or not record["scope"]:
        return "memory_id, memory_type, and scope are required"
    if not record["summary"] and not record["content"]:
        return "summary or content is required"
    if not isinstance(record["evidence"], list) or not isinstance(record["tags"], list):
        return "evidence and tags must be arrays"
    confidence = record["confidence"]
    if not isinstance(confidence, int | float) or confidence < 0 or confidence > 1:
        return "confidence must be between 0 and 1"
    if not isinstance(record["reference_count"], int) or record["reference_count"] < 0:
        return "reference_count must be a non-negative integer"
    if not isinstance(record["reward_signal"], int | float):
        return "reward_signal must be a number"
    embedding = record.get("embedding")
    if embedding is not None and not isinstance(embedding, list):
        return "embedding must be an array of numbers or null"
    return ""


class MemoryStore:
    def __init__(
        self,
        db_path: Path,
        backup_jsonl: Path | None = None,
        embedder: EmbeddingProvider | None = None,
    ):
        self.db_path = db_path
        self.backup_jsonl = backup_jsonl or db_path.with_suffix(".jsonl")
        self.embedder: EmbeddingProvider = embedder or default_embedder()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema(conn)
        return conn

    @contextlib.contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
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
                legion_id TEXT NOT NULL,
                commander_id TEXT NOT NULL,
                parent_commander_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                rollup_level TEXT NOT NULL,
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
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                event_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._migrate_schema(conn)
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(memory_id UNINDEXED, title, summary, content, tags, evidence)
                """
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
        for column, definition in CONTEXT_COLUMNS.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {column} {definition}")
        for column, definition in V2_COLUMNS.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {column} {definition}")

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_memory(record)
        if not normalized.get("embedding"):
            normalized["embedding"] = self.embedder.embed(_embedding_text(normalized))
        error = validate_memory(normalized)
        if error:
            raise ValueError(error)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    memory_id, schema_version, memory_type, scope, source_app, source_type, source_id,
                    source_file, project_hash, project_path, legion_id, commander_id, parent_commander_id,
                    campaign_id, task_id, rollup_level, title, summary, content, evidence_json, tags_json,
                    confidence, permissions_json, invalidated_by_json, created_at, updated_at, content_hash,
                    embedding, reference_count, last_referenced_at, reward_signal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    memory_type=excluded.memory_type,
                    scope=excluded.scope,
                    source_app=excluded.source_app,
                    source_type=excluded.source_type,
                    source_id=excluded.source_id,
                    source_file=excluded.source_file,
                    project_hash=excluded.project_hash,
                    project_path=excluded.project_path,
                    legion_id=excluded.legion_id,
                    commander_id=excluded.commander_id,
                    parent_commander_id=excluded.parent_commander_id,
                    campaign_id=excluded.campaign_id,
                    task_id=excluded.task_id,
                    rollup_level=excluded.rollup_level,
                    title=excluded.title,
                    summary=excluded.summary,
                    content=excluded.content,
                    evidence_json=excluded.evidence_json,
                    tags_json=excluded.tags_json,
                    confidence=excluded.confidence,
                    permissions_json=excluded.permissions_json,
                    invalidated_by_json=excluded.invalidated_by_json,
                    updated_at=excluded.updated_at,
                    content_hash=excluded.content_hash,
                    embedding=excluded.embedding
                """,
                self._row_values(normalized),
            )
            self._upsert_fts(conn, normalized)
            self._append_event(conn, normalized["memory_id"], "upsert", {"content_hash": normalized["content_hash"]})
            conn.commit()
        self.export_jsonl()
        return normalized

    def _row_values(self, record: dict[str, Any]) -> tuple[Any, ...]:
        embedding_blob: bytes | None
        emb = record.get("embedding")
        if emb is None or len(emb) == 0:
            embedding_blob = None
        else:
            embedding_blob = encode_embedding(list(emb))
        return (
            record["memory_id"],
            record["schema_version"],
            record["memory_type"],
            record["scope"],
            record["source_app"],
            record["source_type"],
            record["source_id"],
            record["source_file"],
            record["project_hash"],
            record["project_path"],
            record["legion_id"],
            record["commander_id"],
            record["parent_commander_id"],
            record["campaign_id"],
            record["task_id"],
            record["rollup_level"],
            record["title"],
            record["summary"],
            record["content"],
            json.dumps(record["evidence"], ensure_ascii=False),
            json.dumps(record["tags"], ensure_ascii=False),
            record["confidence"],
            json.dumps(record["permissions"], ensure_ascii=False, sort_keys=True),
            json.dumps(record["invalidated_by"], ensure_ascii=False),
            record["created_at"],
            record["updated_at"],
            record["content_hash"],
            embedding_blob,
            int(record.get("reference_count", 0) or 0),
            str(record.get("last_referenced_at", "") or ""),
            float(record.get("reward_signal", 0.0) or 0.0),
        )

    def _upsert_fts(self, conn: sqlite3.Connection, record: dict[str, Any]) -> None:
        try:
            conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (record["memory_id"],))
            conn.execute(
                "INSERT INTO memory_fts(memory_id, title, summary, content, tags, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record["memory_id"],
                    record["title"],
                    record["summary"],
                    record["content"],
                    " ".join(record["tags"]),
                    " ".join(record["evidence"]),
                ),
            )
        except sqlite3.OperationalError:
            return

    def _append_event(self, conn: sqlite3.Connection, memory_id: str, event_type: str, payload: dict[str, Any]) -> None:
        event_id = "mev-" + stable_hash({"memory_id": memory_id, "event_type": event_type, "payload": payload, "ts": iso_now()})[:16]
        conn.execute(
            "INSERT OR IGNORE INTO memory_events(event_id, memory_id, event_type, created_at, payload_json) VALUES (?, ?, ?, ?, ?)",
            (event_id, memory_id, event_type, iso_now(), json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )

    def load_all(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC, confidence DESC").fetchall()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        embedding: list[float] = []
        if "embedding" in keys:
            embedding = decode_embedding(row["embedding"])
        reference_count = int(row["reference_count"]) if "reference_count" in keys and row["reference_count"] is not None else 0
        last_referenced_at = row["last_referenced_at"] if "last_referenced_at" in keys and row["last_referenced_at"] is not None else ""
        reward_signal = float(row["reward_signal"]) if "reward_signal" in keys and row["reward_signal"] is not None else 0.0
        return {
            "schema_version": int(row["schema_version"]),
            "memory_id": row["memory_id"],
            "memory_type": row["memory_type"],
            "scope": row["scope"],
            "source_app": row["source_app"],
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "source_file": row["source_file"],
            "project_hash": row["project_hash"],
            "project_path": row["project_path"],
            "legion_id": row["legion_id"],
            "commander_id": row["commander_id"],
            "parent_commander_id": row["parent_commander_id"],
            "campaign_id": row["campaign_id"],
            "task_id": row["task_id"],
            "rollup_level": row["rollup_level"],
            "title": row["title"],
            "summary": row["summary"],
            "content": row["content"],
            "evidence": json.loads(row["evidence_json"]),
            "tags": json.loads(row["tags_json"]),
            "confidence": float(row["confidence"]),
            "permissions": json.loads(row["permissions_json"]),
            "invalidated_by": json.loads(row["invalidated_by_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "content_hash": row["content_hash"],
            "embedding": embedding,
            "reference_count": reference_count,
            "last_referenced_at": last_referenced_at,
            "reward_signal": reward_signal,
        }

    def search(
        self,
        query: str,
        limit: int = 5,
        memory_type: str = "",
        scope: str = "",
        legion_id: str = "",
        commander_id: str = "",
        campaign_id: str = "",
        task_id: str = "",
        rollup_level: str = "",
        min_score: float = 0.01,
        track_reference: bool = True,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        filters = self._filters(
            memory_type=memory_type,
            scope=scope,
            legion_id=legion_id,
            commander_id=commander_id,
            campaign_id=campaign_id,
            task_id=task_id,
            rollup_level=rollup_level,
        )
        records = self._search_fts(query, limit=max(limit * 3, limit), **filters)
        if not records:
            records = self._search_lexical(query, **filters)
        records = [record for record in records if float(record.get("score", 0)) >= min_score]
        query_vec = self.embedder.embed(query)
        if any(abs(v) > 0 for v in query_vec):
            for record in records:
                emb = record.get("embedding") or []
                if not emb:
                    continue
                cos = cosine_similarity(query_vec, emb)
                cos_score = max(0.0, cos)
                fts_score = float(record.get("score", 0))
                record["score"] = round(0.6 * fts_score + 0.4 * cos_score, 4)
        records.sort(key=lambda item: (float(item.get("score", 0)), float(item.get("confidence", 0))), reverse=True)
        records = records[:limit]
        if track_reference and records:
            with self.connection() as conn:
                self._track_reference(conn, [r["memory_id"] for r in records], reward_signal=SEARCH_REWARD_SIGNAL)
                conn.commit()
        for record in records:
            record.pop("embedding", None)
        return records

    def _track_reference(
        self,
        conn: sqlite3.Connection,
        memory_ids: list[str],
        reward_signal: float = SEARCH_REWARD_SIGNAL,
    ) -> None:
        if not memory_ids:
            return
        placeholders = ",".join(["?"] * len(memory_ids))
        rows = conn.execute(
            f"SELECT memory_id, confidence FROM memories WHERE memory_id IN ({placeholders})",
            memory_ids,
        ).fetchall()
        now = iso_now()
        for row in rows:
            new_conf = round(apply_reward(float(row["confidence"]), reward_signal), 4)
            conn.execute(
                "UPDATE memories SET reference_count = reference_count + 1, last_referenced_at = ?, "
                "reward_signal = ?, confidence = ? WHERE memory_id = ?",
                (now, float(reward_signal), new_conf, row["memory_id"]),
            )
            self._append_event(
                conn,
                row["memory_id"],
                "referenced",
                {"reward_signal": float(reward_signal), "new_confidence": new_conf},
            )

    def apply_feedback(self, memory_id: str, reward: float) -> dict[str, Any]:
        reward = float(reward)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT confidence FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if not row:
                raise KeyError(memory_id)
            prev = float(row["confidence"])
            new_conf = round(apply_reward(prev, reward), 4)
            now = iso_now()
            conn.execute(
                "UPDATE memories SET confidence = ?, reward_signal = ?, updated_at = ? WHERE memory_id = ?",
                (new_conf, reward, now, memory_id),
            )
            self._append_event(
                conn,
                memory_id,
                "feedback",
                {"reward": reward, "prev_confidence": prev, "new_confidence": new_conf},
            )
            conn.commit()
        self.export_jsonl()
        return {
            "memory_id": memory_id,
            "prev_confidence": prev,
            "new_confidence": new_conf,
            "reward": reward,
        }

    def induce_rollups(
        self,
        threshold: int = 5,
        levels: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        if int(threshold) < 1:
            raise ValueError("threshold must be >= 1")
        ordered_levels = list(levels) if levels else list(DEFAULT_ROLLUP_LEVELS)
        produced: list[dict[str, Any]] = []
        for level in ordered_levels:
            level = str(level or "").strip().lower()
            bucket_col = ROLLUP_BUCKET_KEYS.get(level)
            if not bucket_col:
                continue
            with self.connection() as conn:
                rolled_ids = {
                    row["memory_id"]
                    for row in conn.execute(
                        "SELECT DISTINCT memory_id FROM memory_events WHERE event_type = 'rolled_up'"
                    ).fetchall()
                }
                rows = conn.execute(
                    f"SELECT * FROM memories WHERE rollup_level = '' AND {bucket_col} != ''"
                ).fetchall()
            buckets: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                if row["memory_id"] in rolled_ids:
                    continue
                record = self._row_to_record(row)
                buckets.setdefault(row[bucket_col], []).append(record)
            for bucket_value, records in buckets.items():
                unique_ids = {r["memory_id"] for r in records}
                if len(unique_ids) < int(threshold):
                    continue
                first = records[0]
                context = {bucket_col: bucket_value}
                for ck in (
                    "project_hash", "project_path", "legion_id", "commander_id",
                    "parent_commander_id", "campaign_id", "task_id",
                ):
                    if ck not in context and first.get(ck):
                        context[ck] = first[ck]
                rollup = self.build_rollup(level, records, context)
                stored = self.upsert(rollup)
                with self.connection() as conn:
                    for rec in records:
                        self._append_event(
                            conn,
                            rec["memory_id"],
                            "rolled_up",
                            {"rollup_id": stored["memory_id"], "level": level},
                        )
                    conn.commit()
                produced.append(stored)
        return produced

    def _filters(self, **filters: str) -> dict[str, str]:
        return {key: str(value).strip() for key, value in filters.items() if key in FILTER_FIELDS and str(value).strip()}

    def _search_fts(self, query: str, limit: int, **filters: str) -> list[dict[str, Any]]:
        fts_query = " OR ".join(tokenize(query)[:12])
        if not fts_query:
            return []
        where = ["memory_fts MATCH ?"]
        params: list[Any] = [fts_query]
        for field, value in filters.items():
            where.append(f"m.{field} = ?")
            params.append(value)
        params.append(limit)
        try:
            with self.connection() as conn:
                rows = conn.execute(
                    f"""
                    SELECT m.*, bm25(memory_fts) AS rank
                    FROM memory_fts
                    JOIN memories m ON m.memory_id = memory_fts.memory_id
                    WHERE {' AND '.join(where)}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        records: list[dict[str, Any]] = []
        for row in rows:
            record = self._row_to_record(row)
            rank = float(row["rank"])
            record["score"] = round((1 / (1 + abs(rank))) * (0.5 + record["confidence"] / 2), 4)
            records.append(record)
        return records

    def _search_lexical(self, query: str, **filters: str) -> list[dict[str, Any]]:
        query_tokens = set(tokenize(query))
        records: list[dict[str, Any]] = []
        for record in self.load_all():
            if any(str(record.get(field, "")) != value for field, value in filters.items()):
                continue
            haystack = " ".join(
                [
                    record["title"],
                    record["summary"],
                    record["content"],
                    " ".join(record["tags"]),
                    " ".join(record["evidence"]),
                ]
            )
            tokens = set(tokenize(haystack))
            overlap = len(tokens & query_tokens)
            if not overlap:
                continue
            invalidated_penalty = 0.2 if record.get("invalidated_by") else 1.0
            record = dict(record)
            record["score"] = round((overlap / max(4, len(query_tokens))) * (0.5 + record["confidence"] / 2) * invalidated_penalty, 4)
            records.append(record)
        return records

    def export_jsonl(self) -> int:
        records = self.load_all()
        self.backup_jsonl.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.backup_jsonl.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8")
        tmp.replace(self.backup_jsonl)
        return len(records)

    def ingest_jsonl(self, path: Path) -> int:
        count = 0
        if not path.exists():
            return count
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            self.upsert(record)
            count += 1
        return count

    def compile_startup(self, output_dir: Path, query: str = "", limit: int = 12, max_chars: int = 2200) -> dict[str, str]:
        records = self.search(query or "startup project preference workflow failure verification", limit=limit) if query else self.load_all()[:limit]
        return self.compile_startup_records(output_dir, records, max_chars=max_chars)

    def compile_startup_records(self, output_dir: Path, records: list[dict[str, Any]], max_chars: int = 2200) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        user_records = [item for item in records if item["memory_type"] in {"user_profile", "preference", "identity"}]
        project_records = [item for item in records if item not in user_records]
        memory_text = self._startup_markdown("MEMORY", project_records, max_chars=max_chars)
        user_text = self._startup_markdown("USER", user_records, max_chars=max(800, max_chars // 2))
        memory_path = output_dir / "MEMORY.md"
        user_path = output_dir / "USER.md"
        memory_path.write_text(memory_text, encoding="utf-8")
        user_path.write_text(user_text, encoding="utf-8")
        return {"memory": str(memory_path), "user": str(user_path)}

    def _startup_markdown(self, title: str, records: list[dict[str, Any]], max_chars: int) -> str:
        lines = [f"# Legion {title} Cache", "", "Derived from canonical Memory Store. Safe to delete and rebuild.", ""]
        if not records:
            lines.append("- No high-confidence memories compiled yet.")
        for record in records:
            evidence = ", ".join(record["evidence"][:2])
            lines.append(
                f"- [{record['memory_id']}] ({record['memory_type']}/{record['scope']} c={record['confidence']}) "
                f"{record['summary']} Evidence: {evidence}"
            )
        text = "\n".join(lines).strip() + "\n"
        return trim_text(text, max_chars)

    def compile_wiki(self, output_dir: Path, limit: int = 200) -> dict[str, str]:
        records = self.load_all()[:limit]
        return self.compile_wiki_records(output_dir, records)

    def compile_wiki_records(self, output_dir: Path, records: list[dict[str, Any]]) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        index = [
            "# Legion Memory Wiki",
            "",
            "Derived view from the canonical Memory Store. Do not edit as source of truth.",
            "",
            f"- Total memories: {len(records)}",
            "",
            "## By Type",
        ]
        by_type: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_type.setdefault(record["memory_type"], []).append(record)
        type_dir = output_dir / "types"
        type_dir.mkdir(exist_ok=True)
        written = {"index": str(output_dir / "index.md")}
        for memory_type, items in sorted(by_type.items()):
            page = type_dir / f"{memory_type}.md"
            index.append(f"- [{memory_type}](types/{memory_type}.md): {len(items)}")
            page.write_text(self._wiki_page(memory_type, items), encoding="utf-8")
            written[f"type:{memory_type}"] = str(page)
        (output_dir / "index.md").write_text("\n".join(index).strip() + "\n", encoding="utf-8")
        return written

    def build_rollup(
        self,
        level: str,
        records: list[dict[str, Any]],
        context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        level = str(level or "project").strip().lower()
        context = context or {}
        source_ids = [str(record.get("memory_id", "")) for record in records if str(record.get("memory_id", "")).strip()]
        evidence: list[str] = []
        for record in records:
            source = str(record.get("source_file", "")).strip() or str(record.get("memory_id", "")).strip()
            if source and source not in evidence:
                evidence.append(source)
            if len(evidence) >= 24:
                break
        top_tags: list[str] = []
        for record in records:
            for tag in record.get("tags", []):
                if tag not in top_tags:
                    top_tags.append(tag)
                if len(top_tags) >= 12:
                    break
            if len(top_tags) >= 12:
                break
        summaries = [trim_text(record.get("summary", ""), 180) for record in records if str(record.get("summary", "")).strip()]
        rollup_source = {
            "level": level,
            "source_ids": source_ids[:100],
            "context": context,
        }
        summary = trim_text(f"{level} rollup from {len(records)} memories: " + "; ".join(summaries[:6]), 800)
        content_lines = [f"Rollup level: {level}", f"Source memories: {len(records)}", ""]
        for record in records[:20]:
            content_lines.append(
                f"- [{record.get('memory_id')}] {record.get('memory_type')}/{record.get('scope')} "
                f"c={record.get('confidence')}: {trim_text(record.get('summary', ''), 220)}"
            )
        confidence = 0.5
        if records:
            confidence = min(0.95, sum(float(item.get("confidence", 0.5)) for item in records) / len(records))
        return normalize_memory(
            {
                "memory_id": "rollup-" + stable_hash(rollup_source)[:18],
                "memory_type": "summary",
                "scope": "system" if level == "system" else level,
                "source_app": "legion",
                "source_type": "memory-rollup",
                "source_id": str(context.get("source_id") or context.get("commander_id") or context.get("legion_id") or level),
                "source_file": "",
                "project_hash": context.get("project_hash", ""),
                "project_path": context.get("project_path", ""),
                "legion_id": context.get("legion_id", ""),
                "commander_id": context.get("commander_id", ""),
                "parent_commander_id": context.get("parent_commander_id", ""),
                "campaign_id": context.get("campaign_id", ""),
                "task_id": context.get("task_id", ""),
                "rollup_level": level,
                "title": f"{level.title()} memory rollup",
                "summary": summary or f"{level} rollup has no source summaries yet.",
                "content": "\n".join(content_lines),
                "evidence": evidence or source_ids[:24],
                "tags": ["rollup", level, *top_tags],
                "confidence": confidence,
                "permissions": {"read": ["legion"], "write": ["legion"], "export": ["local"]},
            }
        )

    def _wiki_page(self, title: str, records: Iterable[dict[str, Any]]) -> str:
        lines = [f"# {title}", ""]
        for record in records:
            lines.extend(
                [
                    f"## {record['title'] or record['memory_id']}",
                    "",
                    f"- ID: `{record['memory_id']}`",
                    f"- Scope: `{record['scope']}`",
                    f"- Source: `{record['source_app']}/{record['source_type']}/{record['source_id']}`",
                    f"- Confidence: `{record['confidence']}`",
                    f"- Tags: {', '.join(record['tags'])}",
                    "",
                    record["summary"],
                    "",
                    record["content"],
                    "",
                    "Evidence:",
                    *[f"- `{item}`" for item in record["evidence"][:8]],
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def compact(self) -> int:
        records = self.load_all()
        by_hash: dict[str, dict[str, Any]] = {}
        for record in records:
            key = stable_hash({"summary": record["summary"], "content": record["content"], "evidence": record["evidence"]})
            current = by_hash.get(key)
            if not current or record["confidence"] >= current["confidence"]:
                by_hash[key] = record
        keep = set(item["memory_id"] for item in by_hash.values())
        removed = 0
        with self.connection() as conn:
            for record in records:
                if record["memory_id"] in keep:
                    continue
                conn.execute("DELETE FROM memories WHERE memory_id = ?", (record["memory_id"],))
                try:
                    conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (record["memory_id"],))
                except sqlite3.OperationalError:
                    pass
                removed += 1
            conn.commit()
        self.export_jsonl()
        return removed


def format_records(records: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for record in records:
        tags = ",".join(record.get("tags", [])[:6])
        lines.append(
            f"- {record.get('memory_id')} type={record.get('memory_type')} score={record.get('score', 0)} "
            f"confidence={record.get('confidence')} tags={tags}\n"
            f"  summary: {record.get('summary')}\n"
            f"  content: {record.get('content')}\n"
            f"  evidence: {', '.join(record.get('evidence', [])[:4])}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Legion canonical Memory Store")
    parser.add_argument("db", type=Path)
    parser.add_argument("--backup-jsonl", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest a JSON object or @file into memory.db")
    ingest.add_argument("record_json")

    search_cmd = sub.add_parser("search", help="Search memory.db")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--limit", type=int, default=5)
    search_cmd.add_argument("--type", default="", help="Filter by memory_type")
    search_cmd.add_argument("--scope", default="")
    search_cmd.add_argument("--legion", default="", help="Filter by legion_id")
    search_cmd.add_argument("--commander", default="", help="Filter by commander_id")
    search_cmd.add_argument("--campaign", default="", help="Filter by campaign_id")
    search_cmd.add_argument("--task", default="", help="Filter by task_id")
    search_cmd.add_argument("--rollup-level", default="")
    search_cmd.add_argument("--json", action="store_true")
    search_cmd.add_argument("--no-track", dest="track", action="store_false")
    search_cmd.set_defaults(track=True)

    startup = sub.add_parser("compile-startup", help="Compile MEMORY.md/USER.md startup cache")
    startup.add_argument("output_dir", type=Path)
    startup.add_argument("--query", default="")
    startup.add_argument("--limit", type=int, default=12)

    wiki = sub.add_parser("compile-wiki", help="Compile Markdown wiki projection")
    wiki.add_argument("output_dir", type=Path)
    wiki.add_argument("--limit", type=int, default=200)

    sub.add_parser("compact", help="Deduplicate memory.db")
    sub.add_parser("export-jsonl", help="Export memory.db to backup JSONL")

    feedback = sub.add_parser("apply-feedback", help="Apply reward feedback to a memory")
    feedback.add_argument("memory_id")
    feedback.add_argument("--reward", type=float, required=True)

    induce = sub.add_parser("induce-rollup", help="Induce hierarchical rollups when buckets meet threshold")
    induce.add_argument("--threshold", type=int, default=5)
    induce.add_argument(
        "--levels",
        default=",".join(DEFAULT_ROLLUP_LEVELS),
        help="Comma-separated rollup levels (task, commander, legion, project)",
    )

    args = parser.parse_args(argv)
    store = MemoryStore(args.db, backup_jsonl=args.backup_jsonl)
    if args.command == "ingest":
        raw = args.record_json
        if raw.startswith("@"):
            raw = Path(raw[1:]).read_text(encoding="utf-8")
        print(json.dumps(store.upsert(json.loads(raw)), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "search":
        records = store.search(
            args.query,
            limit=args.limit,
            memory_type=args.type,
            scope=args.scope,
            legion_id=args.legion,
            commander_id=args.commander,
            campaign_id=args.campaign,
            task_id=args.task,
            rollup_level=args.rollup_level,
            track_reference=getattr(args, "track", True),
        )
        print(json.dumps(records, ensure_ascii=False, sort_keys=True) if args.json else format_records(records))
        return 0
    if args.command == "compile-startup":
        print(json.dumps(store.compile_startup(args.output_dir, query=args.query, limit=args.limit), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "compile-wiki":
        print(json.dumps(store.compile_wiki(args.output_dir, limit=args.limit), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "compact":
        print(store.compact())
        return 0
    if args.command == "export-jsonl":
        print(store.export_jsonl())
        return 0
    if args.command == "apply-feedback":
        try:
            result = store.apply_feedback(args.memory_id, args.reward)
        except KeyError:
            print(f"apply-feedback: memory_id not found: {args.memory_id}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "induce-rollup":
        levels = [item.strip() for item in str(args.levels).split(",") if item.strip()]
        try:
            produced = store.induce_rollups(threshold=args.threshold, levels=levels or None)
        except ValueError as exc:
            print(f"induce-rollup: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(produced, ensure_ascii=False, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
