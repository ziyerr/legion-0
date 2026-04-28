# Memory Uplift Requirements

## Origin
启发来源：MemTensor/MemOS 的 memos-local-plugin（4 层认知记忆 + 反馈驱动自演进）。
评估结论：不外挂（协议/依赖/语义不匹配），借三件 idea 增量改造 Legion 自有 `scripts/memory_store.py`。

## In-scope
1. **Embedding column + 语义检索**
   - 在 `memories` 表增加 `embedding BLOB`（可空），保存固定维度 float32 向量。
   - search 路径在 FTS5 / lexical 之上叠加向量余弦相似度。
   - 默认 provider：纯 Python `hash-bag`（哈希词袋投影到 d=128 float32）。零依赖、离线、确定性。
   - 可选 provider：`sentence-transformers`（lazy import，`LEGION_MEMORY_EMBED_PROVIDER=st` 时启用）。本次实现仅留 hook，不强制依赖安装。

2. **自动 rollup 诱导**
   - 新增 `induce-rollup` 子命令。按 `task → commander → legion → project` 层级桶聚合。
   - 触发条件：桶内 `distinct memory sources >= --threshold`（默认 5）且未存在更高层级的有效 rollup。
   - 复用现有 `build_rollup` 实现，只新增聚合调度逻辑。
   - 第一版：CLI 触发的批处理；不做内置 cron。

3. **Reward 反馈环**
   - 新增字段：`reference_count INTEGER DEFAULT 0`、`last_referenced_at TEXT`、`reward_signal REAL DEFAULT 0`。
   - 新增 `apply-feedback` 子命令：按 memory_id 注入 reward signal 调整 confidence。
   - 隐式信号：search 命中累加 `reference_count`、刷新 `last_referenced_at`。
   - 公式：`new_confidence = clamp(old_confidence * 0.9 + reward_signal * 0.1, 0, 1)`，被引用且非负 reward 视为软增强。

## Out-of-scope（本次不做）
- 远程 LLM 调用做 induce / abstract / crystallize（破坏离线属性）。
- 真正的 sentence-transformers 集成（仅留 provider hook）。
- 后台 daemon / cron 自动 rollup（CLI 触发即可）。
- skill 层级 / Beta 后验技能晶体化（idea 层借鉴，但 Legion 已有 tactics/INDEX.md 承载该概念）。
- 重写 thought_retriever（与 memory_store 并存，互不影响）。

## Non-functional
- **向后兼容**：旧 schema_version=1 的 db 必须能被新代码自动迁移到 v2，**不丢数据**。
- **零强依赖**：默认运行不引入除标准库外的新依赖。
- **多语言友好**：tokenize 已支持中文 CJK 区，embedding 哈希同样语言无关。
- **测试覆盖**：核心方法（ingest / search / migration / rollup induce / feedback）必须覆盖。
- **可复现**：embedding hash 是确定性的，相同输入得相同向量。

## Acceptance
- `python -m pytest tests/test_memory_store.py -v` 全绿。
- 拿 v1 schema 创建一个 fixture db，运行任一新命令后 schema 升至 v2，所有原始记录 select 出来内容完全一致。
- `induce-rollup` 在 fixture 上能产出至少 1 条 commander 级 rollup 记录。
- `apply-feedback memory_id --reward 1.0` 后查看该条 confidence 上升、reference_count +1。
- search 命令多次调用同一 query 后，命中条目的 reference_count 单调递增。
