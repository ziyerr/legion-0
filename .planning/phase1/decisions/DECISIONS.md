# Phase 1 — DECISIONS（已锁定决策汇总）

> 本文档是 ADR-001~ADR-010 的索引与状态总览。详细背景见 ARCHITECTURE.md / REQUIREMENTS.md。
> **LOCKED** 决策实施阶段不可推翻；**PROVISIONAL** 决策按默认推进，PM 答复后视情况修订。
> 推翻 LOCKED 必须先写新 ADR 标记 supersedes。

## 决策状态总览

**2026-04-25 15:15 PM 已全数答复 R-OPEN 12 项，所有 PROVISIONAL 升级 LOCKED。**

| ADR | 主题 | 状态 |
|-----|------|------|
| [ADR-001](ADR-001-tool-naming-replacement.md) | 工具命名替换 8 stub → 16 工具 | 🔒 LOCKED |
| [ADR-002](ADR-002-adr-storage-location.md) | ADR 表存储位置：共享 prodmind dev.db | 🔒 LOCKED（PM 2026-04-25 同意）|
| [ADR-003](ADR-003-plugin-directory-structure.md) | plugin 目录结构 + symlink 部署 | 🔒 LOCKED |
| [ADR-004](ADR-004-feishu-api-reuse.md) | 飞书 API 整文件复用 ProdMind | 🔒 LOCKED |
| [ADR-005](ADR-005-dispatch-protocol.md) | dispatch 协议向后兼容 + appeal | 🔒 LOCKED |
| [ADR-006](ADR-006-error-classification.md) | 4 级错误分类边界 | 🔒 LOCKED（PM 2026-04-25 同意 + 3 补充边界）|
| [ADR-007](ADR-007-cron-implementation.md) | 18:00 cron plugin 自管 | 🔒 LOCKED |
| [ADR-008](ADR-008-prodmind-create-project-protocol.md) | kickoff_project HTTP 调 PM | 🔒 LOCKED（PM 2026-04-25 同意 + endpoint 给出）|
| [ADR-009](ADR-009-soul-md-personalization.md) | SOUL.md 程小远化 + 5 条纪律 | 🔒 LOCKED |
| [ADR-010](ADR-010-prd-data-source.md) | PRD 数据源三选一（dev.db 主）| 🔒 LOCKED（PM 2026-04-25 同意）|

## 决策摘要（一行版）

### LOCKED（4 个）

- **ADR-001**：8 个 v0.1 命名 stub → 替换为 PM 派发 6 能力命名（含 review_code 保留）+ 8 PM 只读 + 2 综合 = 16 工具。理由：PM 派发是最新需求，旧 stub 无引用无副作用。
- **ADR-003**：plugin 目录结构 = 5 个新 .py 模块（feishu_api / pm_db_api / adr_storage / legion_api / error_classifier / cron_runner）。部署 = symlink `~/.hermes/profiles/aicto/plugins/aicto`。理由：per-profile 隔离 + 模块职责清晰便于审计。
- **ADR-004**：feishu_api.py 整文件 copy ProdMind 黄金标本（2040 行），仅改 3 处常量。理由：ProdMind 生产稳定 9 个月，自己重写=重发明轮子+引入 bug。
- **ADR-005**：dispatch_to_legion_balanced 复用 ProdMind 双通道（tmux + inbox.jsonl），mailbox schema 加 cto_context / appeal_id 字段（向后兼容现有 commander）。理由：现有 L1 军团已基于 inbox.jsonl 工作，破坏性变更风险大。
- **ADR-007**：18:00 cron 用 plugin 自管 asyncio loop + last_brief_run.json 持久化，不用 launchd / crontab。理由：与 gateway 同生命周期，零额外依赖，便携。
- **ADR-009**：SOUL.md 改写为程小远版（53 行结构基础 + 5 条反幻觉迁入 + 边界声明 + 16 工具清单）。同时删 config.yaml 死代码 HERMES_SYSTEM_PROMPT。理由：PRD §三明确"反幻觉纪律 SOUL.md 嵌入"。

### PROVISIONAL（4 个，等 PM 答复）

- **ADR-002**：ADR / TechRisk / TechDebt / CodeReview / EngineerProfile 5 张 CTO 自有表写入 prodmind dev.db（v0.2 §11.3 历史立场）。如 PM 推翻则改独立 SQLite。
- **ADR-006**：4 级错误分类（技术/权限/意图/未知）按 ARCHITECTURE.md §6 矩阵推进，全 6 能力共享。如 PM 给出不同边界则修订。
- **ADR-008**：kickoff_project 第 3 步 ProdMind Project 条目用 HTTP POST 8642。如 PM 选其他协议（直写 dev.db / 飞书 @ / mailbox）则改。
- **ADR-010**：design_tech_plan input 三选一同时支持（prd_id / prd_markdown / prd_doc_token），dev.db 主链路。如 PM 限定单一来源则改。

## 默认推进风险评估

如所有 4 个 PROVISIONAL ADR 在实施完成时仍未得到 PM 答复，最坏情况：

| ADR | 推翻代价 | 缓解 |
|-----|---------|------|
| ADR-002（ADR 存储）| 中 — 5 张表数据迁移 | 写迁移脚本（1-2h），SQL dump → 新 SQLite |
| ADR-006（错误分类）| 低 — 主要是 prompt 调整 | error_classifier.py 把规则参数化 |
| ADR-008（PM 协议）| 中 — kickoff_project 第 3 步重写 | 抽象出 ProjectCreationProtocol 接口（HTTP / 飞书 / dev.db 直写三实现） |
| ADR-010（PRD 来源）| 低 — input schema 收窄 | schema 已支持三选一，PM 限定后只用一种即可 |

**结论**：4 个 PROVISIONAL 全失败的最大代价 = 1 天返工（比立即停下等 PM 答复造成的进度损失小）→ **决策：默认推进，不阻塞**。
