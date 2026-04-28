# Memory Uplift Implementation Plan

## Phase 1 — Schema bump + 列迁移
- `MEMORY_SCHEMA_VERSION = 2`
- `_migrate_schema` 探测并增列：embedding / reference_count / last_referenced_at / reward_signal
- `normalize_memory` 接受 v1 输入；新字段默认值齐备
- `validate_memory` schema_version 接受 1 或 2（兼容 ingest 输入）；写入时统一 normalize 到 v2
- `_row_values` / `_row_to_record` / INSERT/UPSERT SQL 同步加列

## Phase 2 — Embedding 模块
- 新增 `class EmbeddingProvider` 抽象 + `class HashBagEmbedder(d=128)` 实现
  - 输入：title / summary / content / tags / evidence 拼接
  - 输出：np-style list[float] 长度 128，L2-normalize
  - 实现：纯 Python，hash(token) % d → 累加 → L2 normalize；不引 numpy
- `MemoryStore.__init__` 接受可选 `embedder`；默认 HashBagEmbedder
- `upsert` 时计算 embedding 并写入 BLOB
- `search` 时如果有 embedding 列：拿 query 的向量做余弦，与 FTS/lexical score 加权融合

## Phase 3 — Auto-rollup induce
- 新方法 `induce_rollups(threshold: int, levels: list[str]) -> list[dict]`
- 内部按 levels 顺序处理：task / commander / legion / project
- 每层：
  - `SELECT memory_id, ... WHERE rollup_level='' AND <bucket_key> != ''`
  - GROUP BY 桶键，过滤 `count(distinct memory_id) >= threshold`
  - 调 `build_rollup(level, records, context)` → upsert
  - 已 rollup 过的 source 通过 `memory_events` event_type='rolled_up' 记录，避免下次重复触发
- CLI: `induce-rollup [--threshold N] [--levels task,commander,legion,project]`
- 决策：threshold 必须 >= 1。`induce_rollups` 入口校验 `int(threshold) < 1 → ValueError`，CLI main() 在边界 catch 后写 stderr + 返回非 0；threshold=0 会让单条 distinct count 也触发 rollup，语义无意义且会与 idempotent 防重叠冲突，禁止。

## Phase 4 — Reward feedback
- 新方法 `apply_feedback(memory_id: str, reward: float, *, increment_ref: bool=False)`
  - 拉取记录 → 套公式 → upsert（写入 reward_signal、新 confidence）
- `search` 内：命中后 batch update `reference_count = reference_count + 1`、`last_referenced_at = now`、套软 reward 公式（默认 reward=0.5、track_reference=True 时）
- CLI: `apply-feedback memory_id --reward 0.7`

## Phase 5 — Schema JSON 同步
- `schemas/legion-memory.schema.json`:
  - `schema_version`: const 2 → 改为 enum [1, 2]（兼容输入）；存盘统一 v2
  - 新增四个 properties + required 列表中加入

## Phase 6 — 测试 tests/test_memory_store.py
- 用 pytest tmp_path 隔离
- 案例：
  1. ingest_basic：upsert + load_all 往返
  2. fts_or_lexical：FTS5 命中 + 关闭 FTS 路径走 lexical
  3. embedding_blob_persisted：upsert 后 row 的 embedding 列长 == 128*4
  4. semantic_search_better_than_lexical：构造一组只有语义相关的条目，断言 embedding 分数加权后排序合理（弱断言：top-1 命中预期）
  5. v1_to_v2_migration：手工建 v1 schema 的 db + 一条记录 → 用新 MemoryStore 打开 → schema 已升级 + 旧记录可读
  6. induce_rollup_threshold：5 条 task_id 相同的记录 → 触发 1 条 task 级 rollup；2 条则不触发
  7. apply_feedback_updates：confidence 按公式变化、reference_count +1
  8. search_tracks_reference：连续 search 命中后 reference_count 单调
  9. compact_dedup：与现有 compact 行为不冲突
  10. export_jsonl_roundtrip：export 后 ingest 回去 hash 一致

## Phase 7 — 独立 review + verify（teammate）
- review：codex teammate 读 implementation + tests，输出结构化反馈（ok/issue 列表）
- verify：codex teammate 跑 pytest + CLI 烟测 + v1 fixture migration 验证

## Phase 8 — Commit + push + PR
- git add 仅本次相关文件
- conventional commit：`feat(memory): embedding column + auto-rollup + reward feedback (schema v2)`
- push origin feat/memory-uplift
- gh pr create 指向 master，body 包含 spec 摘要、acceptance evidence

## 风险点
- **CJK 哈希分词碰撞**：tokenize 已有 CJK 范围，`hash() % 128` 在 d=128 维下 token 多时容易冲突，但 hash-bag 本就接受这个噪音。
- **embedding 与 FTS 加权融合**：第一版用简单线性融合（fts_score * 0.6 + cosine * 0.4），权重写常数，后续可调。
- **track_reference 副作用**：search 默认改写 db，可能引发竞争；v1 项目用 sqlite WAL，并发读写可承；测试要覆盖 `--no-track`。
- **rollup 重复触发**：用 `memory_events` 表的 `rolled_up` 事件筛已处理 source。

## 不做的事（明确拒绝）
- 不动 thought_retriever
- 不引入 numpy / scipy / sentence-transformers
- 不接任何 LLM API
- 不改 mixed registry / events.jsonl 结构
- 不做 GUI
