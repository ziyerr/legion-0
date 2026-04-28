# Memory Uplift Decisions (LOCKED)

> 锁定决策，执行阶段不可推翻。需变更须先在此追加 SUPERSEDED 段。

## D1 — Embedding 方案：hash-bag 默认 + provider hook  [LOCKED]
**决策**：默认 `hash-bag`（128 维 float32 哈希词袋），纯 Python 标准库实现；保留 `EmbeddingProvider` 接口允许未来插入 `sentence-transformers` / `openai` 等，但本次只实现 hash-bag 一条路径。
**理由**：
- 保 Legion 离线 + 零强依赖原则。
- hash-bag 在小规模（<10k 条）语义检索效果"够用"，比 lexical FTS 已是显著升级。
- provider hook 让后续替换为真实模型只需改一处。
**拒绝**：
- 引入 sentence-transformers 作硬依赖（违反零依赖）。
- 走 OpenAI/Cohere API（破坏离线 + 引入 token 成本）。

## D2 — Embedding 维度：128  [LOCKED]
**决策**：固定 d=128 float32（每条 512 字节）。
**理由**：1 万条 ≈ 5 MB，暴力扫描可承受；与 MemOS 的"<100k 时 BLOB+暴力即可"一致。
**升级路径**：超过 10 万条再考虑磁盘 ANN 索引。

## D3 — Schema 升至 v2，ALTER 兼容 v1  [LOCKED]
**决策**：`MEMORY_SCHEMA_VERSION = 2`；新增列 `embedding BLOB`、`reference_count INTEGER NOT NULL DEFAULT 0`、`last_referenced_at TEXT NOT NULL DEFAULT ''`、`reward_signal REAL NOT NULL DEFAULT 0`。
**迁移**：复用现有 `_migrate_schema` 模式（`PRAGMA table_info` 探测缺列后 `ALTER TABLE ADD COLUMN`）；`normalize_memory` 接受 v1 输入并补默认值。
**拒绝**：bump 到 v2 后拒收 v1 输入（会破坏既有 ingest 调用方）。

## D4 — Rollup 触发：手动 CLI + 阈值参数  [LOCKED]
**决策**：新增 `induce-rollup` 子命令，参数 `--threshold N`（默认 5）、`--levels task,commander,legion,project`（默认全部）。
**桶键**：
- task：`task_id`
- commander：`commander_id`
- legion：`legion_id`
- project：`project_hash`
**触发条件**：桶内 `distinct memory_id（已排除已 rollup 的 source）>= threshold`。
**幂等**：同样输入产出同一 rollup memory_id（依赖现有 stable_hash）。
**拒绝**：内置定时任务 / 守护进程（第一版避免运行时复杂度）。

## D5 — Reward 公式  [LOCKED]
**决策**：`new_confidence = clamp(old_confidence * decay + reward_signal * gain, 0.0, 1.0)`，`decay=0.9`、`gain=0.1`。
**signal 注入**：
- 显式：`apply-feedback memory_id --reward {-1..+1}`
- 隐式：search 命中时 `reward_signal := 0.5`（弱正反馈）、`reference_count += 1`、刷新 `last_referenced_at`
**拒绝**：复杂的 Beta 后验或 multi-armed bandit（首版避免引入概率模型）。

## D6 — Search 副作用：可选默认开启  [LOCKED]
**决策**：`search()` 默认在返回前对命中条目写入隐式反馈；新增 `track_reference: bool = True` 参数，CLI 提供 `--no-track` 关闭，便于 dry-run / 内部探针。

## D7 — 不动 thought_retriever  [LOCKED]
**决策**：本次只改 `memory_store.py` 与配套 schema/test；`thought_retriever.py` 暂不动。
**理由**：两套系统并存且独立；统一是更大的工程，独立任务再做。

## D8 — 测试隔离：tmp_path  [LOCKED]
**决策**：所有测试使用 `pytest tmp_path`，不写到用户 `~/.claude/legion/...`，不污染真实 db。
**理由**：项目当前用户尚无 memory.db；本次改造也必须不依赖真实数据。
