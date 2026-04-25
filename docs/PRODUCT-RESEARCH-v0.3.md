# AICTO 产品调研与设计深化 v0.3

> v0.2 = 方案架构（what + how-high-level）
> v0.3 = 产品调研 + 能力深挖（why + how-deep）
>
> 2026-04-23 · Claude Code 产出 · 配合 PM 张小飞推进
>
> **⚠️ 2026-04-23 补注 · 越权自检**：本文档部分内容属于 PM 职责范畴（用户场景调研、Dogfood PRD 挑选推荐、"程小远一天"剧本），Claude Code 代 CTO 视角产出时**越了 PM 的权**。张小飞接棒后应覆盖以下标注为"🚩 PM 越权"的部分。详见《[PM × CTO 工作维度正交分解](./PM-CTO-BOUNDARY-MATRIX.md)》。
>
> 越权段落清单：
> - Part A §三 "使用场景调研" — 场景 2-7 属 PM 用户调研（🚩 PM 越权）
> - Part A §四 "各角色对 CTO 的期待差异" — 属 PM 用户画像（🚩 PM 越权）
> - Part B §一 "程小远的一天" — PM 用户场景剧本（🚩 PM 越权）
> - Part C §4 "Dogfood 的第一个 PRD" — 推荐具体 PRD 属 PM 决策（🚩 PM 越权）
> - Part D §4 "Phase 1 MVP 范围" — 能力优先级是 PM 决策（🚩 半越权）
>
> **CTO 应保留且深化的部分**：Part A §一（技术产品格局）、§二（L5 技术门槛）、§五（失败模式技术预判）；Part B §二（6 大能力的 JSON 契约 / skill 推理链）；Part C §1-3（skills 包 / Prisma migration / 工具实现）。

---

## Part A. 产品调研

### 一、市场上的 "AI Tech Lead / CTO / Code Reviewer" 格局

**产品分层**（2026 年当前市场）：

| 层级 | 代表产品 | 做的事 | 不做的事 |
|------|---------|--------|---------|
| L1 · 代码补全 | Copilot / Cursor / Claude Code | 行级补全 + 代码问答 + 重构建议 | 不决策、不调度、不记忆项目 |
| L2 · PR 评审 | Graphite / CodeRabbit / Bito | 单 PR 审查 + 评论 | 不管整体架构、不做任务分拆 |
| L3 · 测试生成 | Devin / Factory / Jules | E2E 自主完成 feature（写代码 + 测 + PR） | 单任务粒度，不跨项目决策 |
| L4 · 需求→代码 | Lovable / v0 / Bolt | PRD/草图 → 直接生成代码 | 无持久团队 + 无军团协同 |
| L5 · **团队级技术负责人** | **程小远（AICTO）** | **项目启动 + 技术决策 + 跨军团调度 + 代码审查 + 进度追踪** | — |

**L5 没有成熟产品**。Devin 号称"AI 工程师"但粒度在任务级；Copilot Workspace 是"IDE 内的计划辅助"，不跨项目；各家"AI project manager"更是偏任务看板。**"AI 技术总监"这个位置是空的**——这正好是 AICTO 的差异化定位。

### 二、为什么 L5 没人做（为什么程小远能做）

L5 的技术门槛：
1. **跨项目记忆**（需要 ADR/TechRisk/TechDebt 等长期档案）
2. **跨团队调度**（需要有"团队"这个概念 + 通讯协议）
3. **主动性**（不是人问才答，是自己发现问题）
4. **权力边界**（能拍板技术，但不能越产品）

市面上为什么没人做：
- **缺少"团队"载体**：Copilot/Cursor 面向个人开发者，没有"军团"
- **缺少持久化项目层**：多数工具是 session 级
- **缺少 PM 搭档**：CTO 角色必须和 PM 搭档才有权力边界
- **AI 模型 2025 年才刚够用**：需要长上下文 + 高推理能力 + tool use，Opus 4.6/4.7 这代才可行

**程小远的独特生态位**：
- 已有**军团体系**（Legion infrastructure）做调度底层
- 已有**PM 搭档**（张小飞 / ProdMind）
- 已有**项目执行管理**（Phase 6 的 TeamMember/Task 表）
- 已有**团队负责人**（张骏飞作为 lead）参与决策闭环

### 三、使用场景调研（什么时候团队需要 CTO）

**场景 1 · 新项目启动** · 频率：每周 1-3 次 · 痛点：PM 启动新项目时需要技术可行性判断、技术栈选型、首批任务拆分 — 当前 team lead 需亲自介入

**场景 2 · PRD 技术评审** · 频率：每天 2-5 次 · 痛点：PM 写完 PRD 后，分派军团前没人做技术审查，军团接活后才发现"这做不了"

**场景 3 · 跨军团任务冲突** · 频率：每周 1-2 次 · 痛点：两个军团同时改同一代码库、或一个 feature 依赖 3 个军团产出 — 需要跨军团协调

**场景 4 · 代码评审** · 频率：每天 5-10 次 · 痛点：军团交付后 PR 堆积，没人审；team lead 审不过来；军团互审质量参差

**场景 5 · 技术债盘点** · 频率：每周 1 次 · 痛点：代码越跑越慢，没人系统性盘点哪些是债、哪些该重构

**场景 6 · 架构演进决策** · 频率：每月 2-4 次 · 痛点：技术栈升级（如 Next.js 重大版本）、数据模型迁移、服务拆分 — 需要有"记忆"的决策者

**场景 7 · 风险提前预警** · 频率：每周 2-3 次 · 痛点：做到一半发现第三方依赖弃用、API 弃用、许可证冲突 — 应该在启动前就识别

### 四、各角色对 CTO 的期待差异

| 角色 | 核心期待 | 反模式（不要做） |
|------|---------|----------------|
| 团队负责人张骏飞 | **30 天睡得着**（不用天天看技术细节） | 不要每个决策都请示（抗干扰优先） |
| PM 张小飞 | **PRD 被快速过审**（不要等 3 天只为"技术可行性"） | 不要驳回却不给改法 |
| 军团指挥官 | **任务清晰**（验收标准明确、依赖清楚） | 不要事无巨细地 micromanage |
| 军团成员（工程师 / AI agent） | **code review 快但严**（2 小时内反馈 + 指出真问题） | 不要 nitpick 命名细节 |
| 未来的 AIHR | **工程师画像准确**（招人方向不错） | 不要推荐不存在的 skill |

**反模式汇总**：AI CTO 如果"什么都要插一脚"、"事无巨细指出问题"、"每个决策都问 lead"——就变成团队噪音源，起反作用。程小远必须守住"只管技术底线、只在关键节点介入"的分寸。

### 五、CTO 失败模式盘点（竞品观察 + 预判）

1. **幻觉工具调用**（前车之鉴：PM 曾虚构"飞书文档已创建"）→ SOUL.md 已嵌入反幻觉纪律
2. **过度审查**（审每一行代码 + nitpick）→ 10 项清单分 BLOCKING/NON-BLOCKING/NIT 三级，NIT 默认不提
3. **决策无记忆**（每次选型都从零推理）→ ADR 表强制每个非琐碎决策留痕
4. **跨项目知识泄漏**（一个项目的决策误用到另一个）→ ADR `projectId` 强隔离
5. **和 PM 越权冲突**（拍产品优先级）→ §八边界矩阵明确"WHAT 归 PM、HOW 归 CTO"
6. **和军团冲突**（指挥官觉得被干扰）→ Phase 1 只做硬 gate（BLOCKING）+ 非硬 gate 记录即可
7. **过于保守拖累迭代**（啥都要先做 spike）→ `feasibility=green` 必须 ≥50%（否则说明过度保守）

---

## Part B. 产品设计深化

### 一、程小远的"一天"（使用场景全链路）

模拟 2026-05-15（Phase 1 上线后）周二一天：

```
08:30  cron 触发：程小远扫所有 Project 的 StateActive 看有无 drift，生成 daily-tech-brief
       → 飞书群发给张骏飞 + 张小飞

09:15  张小飞：「我想做个 AI 客服模块」
       → 张小飞调 create_project("AI 客服")
       → 程小远接管（能力 0）：
         ├─ git init ~/Documents/AICS
         ├─ 写 ADR-0001：项目启动决策
         ├─ 召唤 L1-AICS-后端军团
         └─ 飞书群：「项目 AICS 启动，后端军团就位，等 PM 发 PRD」

10:00  张小飞 PRD 草稿发给程小远（通过 ProdMind 工具触发 design_tech_plan）
       → 程小远 5 分钟内产出：
         ├─ 技术栈：Next.js API route + Redis queue + 豆包 ASR
         ├─ 时间估计：乐观 4 天 / 可能 7 天 / 悲观 12 天
         ├─ 风险：豆包 ASR 未上架火山方舟 → 建议 spike 1 天验证可用性
         ├─ 缺信息：用户并发量？PRD 没写
         └─ 飞书文档：《AICS 技术方案 v0.1》（tenant_editable 自动开）
       → 张小飞补 PRD，程小远重评估

11:30  评估 green，程小远 breakdown_tasks：
       → T1 ~ T8，按复杂度 S/M/L/XL 标签
       → dispatch_to_legion: T1-T4 给 L1-AICS-后端，T5-T6 给 L1-AICS-前端
       → 飞书通知各军团指挥官

14:00  L1-AICS-后端交付 T1（PR URL）
       → 程小远 review_code：
         ├─ ✅ 架构符合
         ├─ ❌ BLOCKING: 缺测试（关键路径无覆盖）
         └─ 打回军团
       → 军团补测试重 PR

16:00  第二次 review 通过，自动合并
       → 通知张小飞做产品验收

17:30  cron 触发：技术债扫描
       → 发现 prodmind 的 some_module 使用弃用 API
       → 生成 TechDebt-0024，severity=mid，estimated 2 days
       → 不主动派单，进入技术债 backlog 等 PM 排期
```

这是"一天"的理想状态。Phase 1 MVP 可以从其中 **9:15 → 11:30** 这一小段（新项目 → 技术方案）跑通。

### 二、六大能力的深化规格

#### 能力 0 · 项目启动（auto kickoff）

**工具签名**：
```python
def kickoff_project(args: dict) -> dict:
    """args: {project_name, prd_source, tech_hint?, mode?}
    returns: {project_id, git_path, legion_commander_id, adr_id, initial_tasks}"""
```

**8 步流程 + 每步可失败点**（对应 v0.2 §四·能力 0 的失败分类矩阵）：

| Step | 动作 | 常见失败 | 失败类型 |
|------|------|---------|---------|
| 1 | 创建 `~/Documents/<name>/` | 目录已存在 | Tech → 加随机后缀重试 |
| 2 | `git init` + `CLAUDE.md`/`.planning/` 骨架 | 磁盘满、git 不可用 | Tech → rollback |
| 3 | ProdMind `create_project` | DB 锁 | Tech → 重试 3 次 |
| 4 | 写 ADR-0001（context=PRD摘要）| ADR 表不存在 | Tech → 自动跑 migration |
| 5 | `create_legion` 拉军团基础设施 | Legion dir 无写权限 | **Permission → 升级 lead** |
| 6 | 根据 PRD 技术栈选军团类型 + 命名 | PRD 太模糊无法选 | **Intent → 升级 lead** + 给 2-3 选项 |
| 7 | 建立 mailbox + outbox（持久化通讯）| mailbox 写入冲突 | Tech → 重试 |
| 8 | 飞书群发"项目 X 已启动" | 飞书 API 403 | **Permission → 升级 lead** |

**交互 UX（飞书卡片）**：
```
┌──────────────────────────────────────┐
│ 🚀 项目 「AICS」 启动                 │
├──────────────────────────────────────┤
│ 📍 Path: ~/Documents/AICS           │
│ 🏛️ Legion: L1-AICS-后端 (就位)       │
│ 📝 ADR-0001 已记录                   │
│ ⏳ 等 PM 发 PRD 启动首批任务          │
├──────────────────────────────────────┤
│ [查看 ADR]  [加入军团群]  [暂停项目]  │
└──────────────────────────────────────┘
```

#### 能力 1 · 技术方案设计（design_tech_plan）

**输入 / 输出 JSON 契约**（v0.2 §四·能力 1 已写，此处补充具体字段）：

```typescript
// Input
{
  "prd_id": string,  // 或
  "prd_markdown": string,
  "focus"?: "time_cost" | "tech_feasibility" | "scalability" | "team_fit" | "all",
  "constraints"?: {
    "deadline"?: string,  // ISO date
    "team_skills"?: string[],
    "forbidden_tech"?: string[],
    "existing_stack"?: string[]
  }
}

// Output
{
  "feasibility": "green" | "yellow" | "red",
  "feasibility_reason": string,
  "time_estimate_days": { "optimistic": int, "likely": int, "pessimistic": int },
  "tech_stack": {
    "selected": { "frontend"?: string, "backend"?: string, "data"?: string, "infra"?: string },
    "alternatives_rejected": [{ "name": string, "reason": string }],
    "fit_score": int  // 1..10
  },
  "architecture": {
    "summary": string,
    "mermaid_diagram": string,
    "key_modules": [{ "name": string, "responsibility": string }]
  },
  "data_model": {
    "new_tables": [{ "name": string, "columns": [...] }],
    "schema_changes": [...]
  },
  "api_contracts": [{ "method": string, "path": string, "summary": string }],
  "third_party_deps": [{ "name": string, "version": string, "license": string, "risk"?: string }],
  "risks": [{ "dimension": string, "severity": string, "mitigation": string }],
  "missing_info": string[],  // PRD 里缺的，要 PM 补
  "recommendation": "proceed" | "clarify" | "scope_cut" | "tech_spike",
  "adr_ids_created": string[],  // 本次产生的 ADR
  "feishu_doc_url": string  // 人类可读版
}
```

**内部推理链**（这是 skill 的核心）：

```
Read PRD → Extract requirements → 
Check ADR history of similar projects → 
Query team skills from EngineerProfile → 
Run feasibility matrix (tech × time × cost × risk) → 
Generate stack candidates (2-3) → 
Score and rank → 
Write ADR for the decision → 
Render Feishu doc
```

**Phase 1 MVP 简化**：先不做 mermaid 渲染 + data_model 自动推导，这些留 Phase 2。MVP 输出至少包含：feasibility / time_estimate / tech_stack.selected / risks / missing_info / feishu_doc_url。

#### 能力 2 · 任务拆分（breakdown_tasks）

**关键设计**：依赖关系用 **DAG**，不允许环；复杂度限 S/M/L/XL 四档（超过 XL 必须再拆）。

**Skill 核心逻辑**：
1. 读技术方案
2. 按 "垂直切片" 或 "水平分层" 选拆分策略（skill 内部决策树）
3. 生成任务列表 + 依赖图
4. 每个任务按 Given/When/Then 生成验收标准
5. 根据 EngineerProfile 推荐军团

**Phase 1 MVP**：产出 JSON，不做可视化 DAG（用文字表达依赖）。

#### 能力 3 · 军团调度（dispatch_to_legion + load balancing）

**关键规则**：
- 单军团并发 ≤ 2 个任务
- 有依赖关系的任务延迟派单（等前置完成）
- 派单时 mailbox 消息附：PRD 摘要 + 技术方案摘要 + 任务详情 + 验收标准

**Phase 1 MVP**：复用 ProdMind 现有的 `dispatch_to_legion` 工具，在程小远这层只加 "load check + 依赖排序" 的封装。

#### 能力 4 · 代码审查（review_code）

**10 项清单的审查标注算法**（关键是节制）：

```
for each file in changed_files:
  for each of 10 checklist items:
    if definitely_violated:
      mark BLOCKING
    elif likely_issue:
      mark NON-BLOCKING + suggest fix
    elif minor_style:
      SKIP (不产出 NIT 评论，减少噪音)
```

**评论密度上限**（反对过度审查）：
- 单 PR 最多 5 个评论（超出按 severity 排序，只留 top 5）
- 单文件最多 2 个 BLOCKING（超出说明整个设计有问题，直接建议 refactor）

**BLOCKING 硬 gate 语义**（2026-04-23 team lead 明确）：
- **程小远是 CTO，对开发团队有绝对指挥权**
- `BLOCKING` = **真阻塞 merge**，军团必须停 + 按 CTO 反馈修复 + 重 PR
- 军团无权忽略 BLOCKING 评论，忽略等同"执行纪律违规"，程小远自动升级到 team lead
- 配套：BLOCKING 必须附**明确的修复要求**（不是"这里写得不好"而是"把 X 改成 Y 因为 Z"）—— 否则军团无从下手
- 配套：**反向申诉通道** — 军团觉得 BLOCKING 不合理可提 `appeal`，程小远要么收回要么升级 team lead 仲裁（**绝对指挥权 ≠ 不可质疑，指挥的前提是论证充分**）

**Phase 1 MVP**：硬 gate 从第一天生效 — 结构化 review 报告输出 + `verdict=rejected` 时飞书自动 @ 军团指挥官"此 PR 需修复后重 PR"。自动合并功能（verdict=approved 时触发 git merge）Phase 2 接入。

#### 能力 5 · 进度汇报（escalate + daily_brief）

**主动触发频率**：
- 每日 18:00 自动生成 daily-tech-brief（汇总所有活跃项目的技术进度 + 风险 + 决策）
- 任何 BLOCKING 事件即时飞书推送
- 军团 >24h 无进展自动触发催促（通过 mailbox 给指挥官）+ 升级通知

**Phase 1 MVP**：先做 daily-brief + BLOCKING 即时推送，延迟预警 Phase 2 做。

---

## Part C · Phase 1 实施 spec（技术清单，接下来的具体活）

### 1. Skills 包（6 个文件）

| Skill 文件 | 对应能力 | 触发条件 |
|-----------|---------|---------|
| `~/.hermes/profiles/aicto/skills/aicto-project-kickoff.md` | 能力 0 | "启动项目 X" / `kickoff_project` 调用 |
| `~/.hermes/profiles/aicto/skills/aicto-design-tech-plan.md` | 能力 1 | "给 PRD 做技术方案" / `design_tech_plan` 调用 |
| `~/.hermes/profiles/aicto/skills/aicto-breakdown-tasks.md` | 能力 2 | "拆任务" / `breakdown_tasks` 调用 |
| `~/.hermes/profiles/aicto/skills/aicto-dispatch-with-load.md` | 能力 3 | "派单 + 负载均衡" / `dispatch_to_legion_balanced` 调用 |
| `~/.hermes/profiles/aicto/skills/aicto-code-review.md` | 能力 4 | "审 PR" / `review_code` 调用 |
| `~/.hermes/profiles/aicto/skills/aicto-daily-brief.md` | 能力 5 | cron 18:00 / `generate_daily_brief` 调用 |

每个 skill 文件格式参考 default profile 的 77 个 bundled skills（`~/.hermes/skills/` 下的 `*.md`）。

### 2. ADR 表 Prisma migration

schema 已在 v0.2 §6.1 定义，落地动作：
- 在 `prodmind/prisma/schema.prisma` 追加 5 张表（ADR / TechRisk / TechDebt / CodeReview / EngineerProfile）
- 生成 migration（`prisma migrate dev --name add_aicto_tables`）
- 应用到 dev.db（注意：此时 dev.db 已有 Phase 7 迁移产物，migration 需增量 over existing schema）

### 3. AICTO 工具实现（替换 stub）

6 个新工具在 `~/Documents/AICTO/hermes-plugin/tools.py` 替换现有 stub：
- `kickoff_project` · `design_tech_plan` · `breakdown_tasks` · `dispatch_to_legion_balanced` · `review_code` · `generate_daily_brief`

+ 2 个辅助：`record_tech_decision`（Phase 2 复用）· `escalate_risk`

### 4. Dogfood 的第一个 PRD

候选（从 v0.2 附录 A 推荐）：
- ⭐⭐⭐⭐ **"Phase 7 审查"** — 既是对刚完成实施的复盘（3 军团交付轨迹），又能验证 review_code 能力
- ⭐⭐⭐ "AI 客服"新需求
- ⭐⭐ 其他 PM backlog 里的小需求

### 5. 已决策 · 硬 gate + 绝对指挥权（2026-04-23 team lead 明确）

- **CTO 对开发团队有绝对指挥权**（程小远 > 军团指挥官在技术决策层面）
- **代码审查 BLOCKING = 硬阻塞 merge**，军团必须停 + 修 + 重 PR，不允许忽略
- **配套约束**：
  - BLOCKING 必须附明确修复要求（否则军团无从下手）
  - 军团有 `appeal` 反向通道 — 觉得 BLOCKING 不合理可上诉，程小远要么收回要么升级 team lead
  - 程小远自动识别"执行纪律违规"（连续 N 次忽略 BLOCKING）并升级 team lead

- **军团 workflow 改造**：Phase 1 实施时需在军团 auto-loop.sh 里加一个"收到 CTO BLOCKING 则暂停 feature"钩子（不多，一条判断 + 消息读取）

- **其他能力的指挥权体现**：
  - `dispatch_to_legion`：程小远派的任务，军团**必须**接（军团可 appeal 但不能直接拒）
  - `kickoff_project`：程小远命名军团、建立 mailbox 不需要军团同意
  - `escalate_risk`：程小远发现技术风险，直接飞书 @ team lead，不走 PM 中转

---

## Part D · 调研结论 + 推进建议

1. **差异化定位确认**：程小远做的是**"L5 团队级技术负责人"**，市场空位，有强竞争力
2. **绝对指挥权 = 定位深化**（2026-04-23）：CTO 不只是"评审者"，是"开发团队的技术决策最终权威"。这把程小远从"建议层"升级到"决策层"，拉开和 Copilot/CodeRabbit 等审查类产品的距离
3. **最怕的不是对手，是过度产品**：反模式里"什么都管"仍然是最大风险——绝对指挥权要配合**节制的评论密度（≤5/PR）**和**明确的 appeal 通道**，防止变成噪音源
4. **Phase 1 MVP 范围**：1 个真实 PRD 跑通 **能力 0 + 1 + 2 + 3** 四步（项目启动 → 方案 → 拆分 → 派单），能力 4 硬 gate 从 Day 1 启用（review 报告 + BLOCKING 阻塞），能力 5 daily-brief 也上线
5. **和 PM 的协同模式**：Claude Code 做技术实现；张小飞在飞书主导产品设计完整流程（PRD 流转 / 飞书 UX / team lead 同步 / 产品 decision log）；team lead 做关键决策的仲裁者 + 申诉判官
6. **下一步**（PM 接棒的 checklist）：
   - 张小飞接手完成产品设计完整流程（详见 HANDOFF-TO-PM.md）
   - Claude Code 等张小飞产出产品侧细化（卡片 UX / 对话 flow / 错误文案 / 申诉流程），然后承接 Skills 包、ADR migration、工具实现
