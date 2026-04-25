# ADR-002：ADR 表存储位置 — 共享 prodmind dev.db

**状态**：🔒 LOCKED（PM 2026-04-25 15:05 同意默认方案）
**时间**：2026-04-25
**决策者**：L1-麒麟军团指挥官（基于历史立场默认推进）
**适用阶段**：Phase 1 全程

## Context

历史立场（v0.2 §11.3 + CTO-READ-ACCESS-SPEC §四）已结案：
- 5 张 CTO 自有表（ADR / TechRisk / TechDebt / CodeReview / EngineerProfile）放 ProdMind dev.db 共享
- 完整 Prisma schema 已设计
- 权限隔离靠 `_cto_own_connect()` (无 mode=ro 写自有表) vs `_readonly_connect()` (mode=ro 物理挡写 PM 表) 函数对

但 PM 派发 §五·风险 #2 把这一条重新挂为待决："独立 SQLite vs 与 ProdMind 共享 dev.db"。

L1 已通过 dispatch 反向问题 Q-1 反问 PM。**疑似 PM 不知历史立场**。

## Decision（默认推进）

**采用 v0.2 §11.3 历史立场**：5 张 CTO 自有表写入 ProdMind dev.db (`/Users/feijun/Documents/prodmind/dev.db`)。

- CTO 写自有表 → `_cto_own_connect()` 不带 mode=ro
- CTO 读 PM 表 → `_readonly_connect()` 带 mode=ro
- 启动时 `_ensure_cto_tables()` 用 CREATE TABLE IF NOT EXISTS 建 5 张表（不碰 PM 表）
- ADR number per-project 递增

## Alternatives Considered

| 方案 | 拒绝理由（默认推进） |
|-----|---------|
| 独立 SQLite（`~/.hermes/profiles/aicto/aicto.db`）| 1) 需要重新设计跨库 JOIN（CTO 引用 PM 的 Project.id）；2) PM 读 ADR 时需要跨库；3) 备份/迁移更复杂 |
| 文件系统（每个 ADR 一个 .md）| 1) 不利于 LLM 查询历史决策；2) 跨项目搜索性能差；3) 与 PM PRDDecision 风格不一致 |
| Postgres 集中库 | 1) Phase 1 没必要引入新基础设施；2) 与 ProdMind SQLite 不一致 |

## Consequences

### 正面（如默认推进生效）
- ✅ 复用现有 dev.db / WAL 模式 / 备份机制
- ✅ PM 读 ADR 决策链时无需跨库 JOIN
- ✅ ARCHITECTURE 完整规格已设计（CTO-READ-ACCESS-SPEC.md），实施风险低

### 负面（如 PM 推翻为独立 SQLite）
- ⚠️ 5 张表需迁移（CREATE 在新 db + 数据复制）— 估 1-2h 工作量
- ⚠️ 跨库引用 Project.id 需要冗余存储（不能用 FOREIGN KEY）
- ⚠️ 缓解：在 adr_storage.py 抽象 `STORAGE_DB_PATH` 常量，迁移时只改一处

## Verification

- [ ] `_cto_own_connect()` 实测可写 ADR 表
- [ ] `_readonly_connect()` 实测无法写 PM 表（抛 `attempt to write a readonly database`）
- [ ] grep CTO 代码：`_readonly_connect.*INSERT` / `_readonly_connect.*UPDATE` / `_readonly_connect.*DELETE` 应为空集
- [ ] PM 读 ADR：用 ProdMind SDK 查 `SELECT * FROM ADR WHERE project_id = ?` 成功

## Decision Reversal Plan（如 PM 推翻）

1. 写 ADR-002b：标 supersedes ADR-002，新位置 = 独立 SQLite
2. 数据迁移脚本：`sqlite3 prodmind/dev.db .dump ADR > /tmp/adr.sql && sqlite3 ~/.hermes/profiles/aicto/aicto.db < /tmp/adr.sql`
3. 改 adr_storage.py 顶部 `STORAGE_DB_PATH` 常量
4. PM bot 想读 ADR 时改用 AICTO HTTP API（如 PM 必须读 ADR）
