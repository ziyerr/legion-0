# AICTO 产品设计 · 交接给 PM 张小飞

> 团队负责人张骏飞 2026-04-23 决定：AICTO 产品设计的**完整流程**由张小飞主导完成，Claude Code 这边承接 PM 产出细化后的技术实施。

## 最新决策（三条已锁定）

1. **程小远（CTO）对开发团队有绝对指挥权**
2. **代码审查 BLOCKING = 硬 gate 阻塞 merge**（配套：BLOCKING 必须附明确修复要求 + 军团有 appeal 通道）
3. **PM × CTO 工作维度正交**：PM 做原子化需求（WHAT+WHY），CTO 做原子化实现方式（HOW），互不越权。详见《[PM-CTO-BOUNDARY-MATRIX.md](./PM-CTO-BOUNDARY-MATRIX.md)》

## 对 PM 接棒的重要提醒 · 不要被 v0.3 误导

Claude Code 代 CTO 视角产出的 v0.3 里**有几段 PM 越权的部分**（见 v0.3 顶部自检清单）：

- Part A §三-四（使用场景 / 角色期待）— 应该由 PM 从用户侧重调研
- Part B §一（程小远的一天剧本）— 这是 PM 的用户场景剧本
- Part C §4（Dogfood PRD 推荐"Phase 7 审查"）— PRD 挑选是 PM 职责
- Part D §4（MVP 范围优先级）— 能力优先级是 PM 决策

**这些你要覆盖/重写，不是照抄**——它们属于 PM 用户调研 + 产品决策，Claude Code 不该做。你接棒后从用户需求起点重做。

## 给张小飞的触发消息（team lead 直接复制到飞书）

```
小飞，AICTO 产品设计的完整流程交给你主导。

三条最新决策：
1. 程小远（CTO）对开发团队有绝对指挥权
2. BLOCKING 是硬 gate 阻塞 merge，配 appeal 通道
3. PM × CTO 工作维度正交：你做原子化需求（WHAT+WHY），程小远做原子化实现（HOW），互不越权

材料：
- 方案架构：~/Documents/AICTO/docs/PRODUCT-SPEC-v0.2-merged.md
- 产品调研 v0.3（含越权自检）：~/Documents/AICTO/docs/PRODUCT-RESEARCH-v0.3.md
- 工作边界矩阵：~/Documents/AICTO/docs/PM-CTO-BOUNDARY-MATRIX.md（必读）
- 基础设施：aicto profile 已起（port 8644），SOUL.md 已写，8 个工具 stub 待实现

你要做的（只做 PM 的事）：
1. 从用户视角做调研：团队 lead / 军团指挥官 / 工程师各自对"技术总监"的真实期待 + 现有痛点频率
2. 把 6 大能力重写成原子化需求（不提技术栈/架构/实现方式）
3. 每个需求写用户角色 + 场景 + 价值 + 用户侧可感知的验收标准
4. 挑选 Dogfood 的第一个真实 PRD（你按需求池+价值判断，不用参考 v0.3 里 CTO 推荐）
5. 产品 UX 细化（飞书卡片 / 对话 flow / BLOCKING appeal 交互）
6. 产品里程碑 + 验收标准
7. 飞书和 team lead 对齐每阶段产品决策

你不要做（CTO 的事）：
× 技术栈选型 / 架构 / 数据库表结构 / API 规范 / 实现细节
× "应该用 xxx 做" 类表达（换成 "需要满足 xxx 能力"）

v0.3 里有几段 Claude Code 越权帮你写了用户调研、一天剧本、Dogfood 推荐——你要覆盖重写，不是照抄（详见 v0.3 顶部"越权自检"提示）。

产出完成后通知 Claude Code 接棒做技术实现（Skills / migration / 工具）。

开始。
```

## Claude Code 这边的承诺（CTO 视角）

PM 产出产品侧设计后，**team lead 在 Claude Code 会话里起动后**，我承接以下技术实施（**只做 CTO 的事**）：

1. **技术栈调研** — 6 大能力各自的实现选型（skills 格式 / ADR 存储 / code review 机制）
2. **6 个 skill 文件** — `~/.hermes/profiles/aicto/skills/aicto-*.md`
3. **Prisma migration** — ADR / TechRisk / TechDebt / CodeReview / EngineerProfile 5 张表
4. **8 个工具真实实现** — `~/Documents/AICTO/hermes-plugin/tools.py` 替换 stub
5. **军团 hook** — auto-loop.sh 加"收到 CTO BLOCKING 暂停 feature"判断
6. **性能/成本指标** — 每个能力的 API 调用量、延迟、成本
7. **技术风险披露** — 副作用给 PM 看
8. **工程验收** — 测试覆盖率、压测、代码质量 gate
9. **CTO 读 PM 文档能力** — 8 个只读工具 + dev.db `mode=ro` 直连 + 飞书 docx API 读（详见 [CTO-READ-ACCESS-SPEC.md](./CTO-READ-ACCESS-SPEC.md)） — 让 CTO 能"随时查阅 AIPM 的文档理解需求目标和范围"（team lead 2026-04-23 要求）

我不做（PM 的事）：
× 用户调研 / 场景剧本 / 功能优先级 / 验收标准（用户侧）/ Dogfood PRD 挑选

## PM 可能需要澄清的开放点（可以在飞书问 team lead）

- **CTO 申诉链路升级阈值**：军团 appeal 多少次之后程小远自动升级到 team lead？（建议 = 1 次，避免拉锯）
- **Dogfood PRD 选哪个**：由 PM 自己从需求池按价值挑
- **cron 频率**：daily-brief 每天 18:00 合适吗？
- **飞书机器人在哪些群里可见**：AICTO app `cli_a9495f70ddb85cc5` 需要 team lead 手动添加进至少 1 个工作群
