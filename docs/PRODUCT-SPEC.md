# AICTO 产品方案 v0.1

> 云智 AI 团队的技术总监（CTO）。与 ProdMind (PM / 张小飞) 搭档构成"WHAT × HOW"产品-技术决策闭环。
>
> 版本 v0.1 · 2026-04-23 · 状态 = 设计中（专有能力尚未落地实现）

---

## 1. 核心使命

**1.1 一句话定位**
在云智 AI 团队的产品交付链路里，AICTO 是守住技术底线的节点——守住可行性、守住成本、守住风险、守住质量。

**1.2 存在的理由**
PM 的职责是"定义值得做什么"（WHAT），但 PM 不是技术人，对技术可行性/成本/风险判断有盲区。
军团指挥官擅长"按任务把代码写出来"（EXECUTE），但不擅长跨项目架构权衡。
CTO 补的是**中间那一层**——把 PM 的 WHAT 翻译成**技术可行、成本可控、风险可测**的实现方案，并在军团实施后把关质量。

**1.3 不做什么（边界）**
- 不写业务代码 → 军团做
- 不做产品决策 → PM 做
- 不招聘 → HR 做
- 不直接面对终端用户 → 未来的 AI 客服做

**1.4 核心价值主张**
> "让张骏飞能够安心睡 30 天"——回来时 PM 做的每个需求过了技术评审、每份派单经过架构审查、每次上线有风险档案、每个技术债有提案。

---

## 2. 八大能力维度详述

每个能力包含：**场景** / **输入** / **输出** / **触发方式** / **关键决策点** / **依赖**。

### 2.1 `review_architecture` — 架构评审

**场景**：PM 提了一个 PRD，描述要做一个"AI 直播主"系统。技术方案涉及实时流、多模型编排、WebRTC、Redis 队列。CTO 要对这套架构做评审。

**输入**：
- `description` — 架构描述文本、飞书文档 URL 或代码仓库路径
- `focus_areas[]` — 关注点（scalability / security / maintainability / cost / latency）

**输出结构**（JSON）：
```
{
  "verdict": "approved" | "conditional" | "rejected",
  "strengths": [str],
  "concerns": [{"area": str, "severity": "low|mid|high|critical", "detail": str, "suggestion": str}],
  "missing_info": [str],          # 评审需要但描述里没有的信息
  "recommendation": str,           # 一句话总体建议
  "docs_id": str                  # 写入 ADR 的 ID，便于回查
}
```

**触发方式**：
1. PM 主动调 `review_architecture` 附带 PRD（推荐路径）
2. 军团指挥官在接到复杂任务前主动调（咨询路径）
3. 老板直接调（审阅路径）

**关键决策点**：
- 评审不依赖"感觉"——必须落到**至少 3 个维度的具体度量**（时间成本估算、QPS 上限、数据量增长曲线等任选其三）
- `rejected` 不是绝对否决——必须给出"改成什么可以 approved"的条件
- 风险必须分级，`critical` 会触发 `escalate_risk` 反向回弹到 PM

**依赖**：
- ProdMind 的 `get_prd(prd_id)` 工具（读 PRD 上下文）
- ADR（Architecture Decision Records）存储层（见 §6.1）

---

### 2.2 `assess_technical_risk` — 技术风险评估

**场景**：PM 说"我想用 xxxx 这个新出的开源库来做推荐系统"。CTO 要评估这个方案的风险。

**输入**：
- `approach` — 要评估的技术方案
- `context` — 业务/团队/时间上下文

**输出结构**：
```
{
  "overall_risk": "low|mid|high|critical",
  "risks": [
    {
      "dimension": "dependency|integration|team_skill|vendor|compliance|performance|security|data",
      "description": str,
      "likelihood": 0.0..1.0,
      "impact": "low|mid|high",
      "mitigation": str,
      "early_warning_signal": str  # 什么情况说明风险开始发生
    }
  ],
  "go_no_go": "go|conditional|no-go",
  "conditions_to_go": [str]  # 如果 conditional，具体要满足什么
}
```

**触发方式**：
1. PM PRD 写完准备分派前（强制，过不了技术评审不能分派）
2. 军团接手任务后进入新领域时（咨询）
3. 定期扫描（每 Phase 末进行项目级风险盘点）

**关键决策点**：
- 7 个风险维度必须全部回答（至少给 low），缺项意味着评估未完成
- likelihood × impact 组合决定 overall_risk（有成熟的映射矩阵）
- `early_warning_signal` 不是可选——没预警信号等于无法监控

**依赖**：
- web_search（查新技术的社区反馈/issue）
- 技术债档案（看历史项目是否踩过同类坑）

---

### 2.3 `recommend_tech_stack` — 技术栈选型

**场景**：启动新项目（如 AICTO 自己的 dashboard，或给某个 AI 员工做新 feature），PM 问 CTO 用什么栈。

**输入**：
- `requirements` — 需求描述
- `constraints` — 约束（团队 skill / 预算 / 时间 / 合规 / 现有技术栈）

**输出结构**：
```
{
  "candidates": [
    {
      "stack_name": "Next.js + Prisma + SQLite",
      "fit_score": 1..10,
      "pros": [str],
      "cons": [str],
      "first_pr_effort_days": 1..30,
      "long_term_maintenance_cost": "low|mid|high"
    }
  ],
  "recommended": str,
  "rationale": str,
  "decision_record_id": str  # 会自动写入 ADR
}
```

**触发方式**：新项目启动节点（和 PM 的 `create_project` 强耦合）

**关键决策点**：
- 至少给 2 个候选（单一选项不算 "推荐"）
- 必须考虑**团队现有 skill**（不是最优解而是最能跑起来的解）
- 输出一定要进 ADR（这是每个新项目最早的技术决策，后续所有实现都建立在这基础上）

---

### 2.4 `review_code` — 代码评审

**场景**：军团指挥官交付了一个 PR（GitHub 或本地 worktree 分支），CTO 做代码评审。

**输入**：
- `repo_path` — 本地路径、PR URL 或 commit SHA
- `scope` — security / performance / readability / test_coverage / all

**输出结构**：
```
{
  "verdict": "approved|changes_requested|rejected",
  "comments": [
    {
      "file": str,
      "line": int,
      "severity": "nit|suggestion|issue|blocker",
      "type": "bug|perf|security|readability|test",
      "comment": str,
      "suggested_change": str  # 可选
    }
  ],
  "test_coverage": {
    "covered_files": int,
    "uncovered_files": int,
    "missing_critical_paths": [str]
  },
  "tech_debt_introduced": [str],  # 这次 PR 新增的技术债（如有）
  "summary": str
}
```

**触发方式**：
1. 军团 auto run 完成一个 feature 后自动触发（未来 Phase 7 F022 扩展）
2. 老板手动调（PR 大时）
3. CTO 自己发起（对高风险区域主动审查）

**关键决策点**：
- `blocker` = 阻塞 merge；`issue` = 需修改但可后续处理；`nit` = 可选
- 不是行行都评——聚焦高价值（架构违规、未处理边界、测试缺失关键路径）
- 发现 `tech_debt_introduced` 要写进技术债档案（§6.2），不能只吐槽不记账

---

### 2.5 `evaluate_prd_feasibility` — PRD 可行性评估

**场景**：PM 写完一版 PRD，准备分派实施前，CTO 做整体可行性评估。**这是 AICTO 和 PM 最核心的协作点**。

**输入**：
- `prd_id` — ProdMind 里的 PRD ID
- `focus` — time_cost / tech_feasibility / scalability / team_fit / all

**输出结构**：
```
{
  "overall_feasibility": "green|yellow|red",
  "time_estimate_days": {"optimistic": int, "likely": int, "pessimistic": int},
  "missing_details": [str],   # PRD 里模糊需要 PM 澄清的点
  "risks_flagged": [risk_id],  # 自动触发的 assess_technical_risk 结果 ID
  "team_skill_gaps": [str],    # 当前军团能力和需求的差距
  "architecture_implications": str,   # 对现有架构的影响
  "recommendation": {
    "action": "proceed|clarify|scope_cut|tech_spike",
    "detail": str,
    "priority_features_if_scope_cut": [str]
  }
}
```

**触发方式**：
1. PM 在 PRD 进入 `ready_for_review` 状态时自动触发（强制 gate）
2. PRD 有重大变更后重新触发（以防漂移）

**关键决策点**：
- `red` verdict 必须明确告诉 PM"要改什么才能绿"——不能只说不可行
- `time_estimate_days` 三档估计（乐观/可能/悲观）——PM 只看最坏情况决定范围
- `tech_spike` 是特殊选项：需求里有不确定性，建议先做 1-2 天技术验证再决定

**依赖**：
- ProdMind 的 `get_prd` + `get_project`
- 共享 dev.db（读 Feature 表的历史实施记录做对比）

---

### 2.6 `analyze_technical_debt` — 技术债务分析

**场景**：定期或特定场景下分析代码库的技术债。

**输入**：
- `repo_path` — 代码仓库路径
- `depth` — quick（表层问题）/ standard / deep（含性能 profiling）

**输出结构**：
```
{
  "debt_items": [
    {
      "id": str,
      "category": "duplication|coupling|test_gap|outdated_dep|perf|security|doc",
      "location": "file:line" or "pattern",
      "severity": "low|mid|high",
      "impact_on_velocity": str,  # 这个债如何拖慢迭代
      "estimated_refactor_effort_days": int,
      "suggested_refactor": str
    }
  ],
  "total_debt_score": 0..100,
  "trend": "improving|stable|deteriorating",  # 和上次对比
  "top_3_to_fix": [debt_id]
}
```

**触发方式**：
1. 每 Phase 末（固定节奏）
2. 军团反馈"这块代码改不动了"（信号驱动）
3. 老板主动问（审计驱动）

**关键决策点**：
- debt_score 变化趋势比绝对值更重要（trending 很关键）
- top_3_to_fix 是行动建议——不给优先级等于没建议

---

### 2.7 `propose_refactor` — 重构方案

**场景**：当 `analyze_technical_debt` 发现某项债已经成为瓶颈，CTO 给出具体重构方案。

**输入**：
- `pain_point` — 痛点描述
- `current_state` — 当前实现概述

**输出结构**：
```
{
  "refactor_plan": {
    "goal": str,
    "scope": [str],  # 哪些文件/模块会动
    "approach": "incremental|big_bang|strangler_fig|branch_by_abstraction",
    "steps": [
      {"order": int, "action": str, "estimated_hours": int, "verification": str}
    ],
    "rollback_strategy": str
  },
  "impact_analysis": {
    "breaking_changes": [str],
    "affected_features": [str],
    "test_updates_needed": [str]
  },
  "opportunity_cost": str,  # 做这个重构等于不做什么
  "go_no_go_criteria": str  # 满足什么才建议现在做
}
```

**关键决策点**：
- 默认 `approach = incremental`（小步）—— big_bang 必须有非常强的理由
- 必须提供 `rollback_strategy`（重构失败时怎么退）
- `opportunity_cost` 很重要——CTO 不能只看技术层面，还要看机会成本

---

### 2.8 `record_tech_decision` — 技术决策记录

**场景**：任何重大技术决策都要留痕——选型、架构权衡、弃用某技术等。

**输入**：
- `decision` — 决策内容
- `reasoning` — 决策理由
- `alternatives_considered[]` — 考虑过的替代方案
- `project_id` — 关联 Project（可选）

**输出结构**：
```
{
  "adr_id": str,
  "status": "proposed|accepted|deprecated|superseded",
  "created_at": timestamp,
  "storage_location": "path/to/adr/0042.md"
}
```

**关键决策点**：
- 每条决策都有 ADR ID，可以被后续决策 `supersedes`（决策演化可追溯）
- ADR 格式遵循 Michael Nygard 风格：Context / Decision / Consequences
- CTO 做的每个非琐碎动作都要落 ADR（否则决策就蒸发了）

---

## 3. 和 PM 的协作契约

### 3.1 PM → CTO 的标准请求流

```
PM 写完 PRD → ProdMind 触发 pm_pre_dispatch_hook
  → 调 evaluate_prd_feasibility(prd_id)
  → CTO 返回 {verdict, missing_details, time_estimate, risks_flagged}
  → PM 根据 verdict:
      green   → 继续分派（conditional green = 走但要监控）
      yellow  → 根据 missing_details 补全 PRD，再 evaluate 一次
      red     → 根据 recommendation 调整 scope/tech_spike/clarify
```

### 3.2 CTO → PM 的反向回弹（critical path）

```
CTO 在评审/分析中发现 critical risk
  → 调 escalate_to_pm(project_id, risk_detail)
  → ProdMind 在飞书里 @ PM 并展示 CTO 的关注
  → PM 决定：继续、延期、降级、或砍 feature
```

### 3.3 共享数据源（dev.db）

| 表 | PM 读写 | CTO 读写 | 说明 |
|----|---------|---------|------|
| Project | RW | R | 项目级元数据 |
| PRD | RW | R | PRD 版本链、内容、decisions |
| UserStory | RW | R | |
| Feature | RW | R | |
| Task | RW | R + 评审日志 write | CTO 可加 review_result |
| TeamMember | R | R | |
| **ADR**（新增） | R | RW | 架构决策记录，CTO 的主要产出 |
| **TechRisk**（新增） | R | RW | 技术风险档案 |
| **TechDebt**（新增） | R | RW | 技术债登记 |
| **CodeReview**（新增） | R | RW | 代码评审结果 |

CTO 新增 4 张表（§6），放在 ProdMind 项目的 dev.db 里共享。

---

## 4. 和军团的协作契约

### 4.1 CTO 触发军团（通过 PM 中转）
CTO 自己不直接分派军团任务。建议路径：
1. CTO 发现技术债需要重构 → 生成 `propose_refactor` 方案
2. 调 `escalate_to_pm(action='refactor_task')` 建议 PM 把这个做成 Task
3. PM 决定是否接纳，采纳后走正常分派流程

**设计理由**：CTO 不越过 PM 直接调军团——避免 PM 的排期被 CTO 打乱。军团资源调度权属于 PM。

### 4.2 军团提交评审 → CTO
军团 auto run 完成一个 feature 后：
1. auto-loop.sh 调 `review_code(repo_path, commits)` 通知 CTO
2. CTO 返回 verdict —— `blocker` 触发 auto rollback
3. 评审结果进 CodeReview 表，PM 可见

### 4.3 跨域咨询
军团指挥官在接到跨域复杂任务（多语言、多系统）时，可以直接 @ CTO 咨询：
- 以 `oc_b54452c8...`（"111222"群）为协作空间
- CTO 回应时同步 push ADR（如果讨论产生决策）

---

## 5. 技术决策日志（TDL）设计

### 5.1 数据结构（ADR 表 Prisma schema）

```prisma
model ADR {
  id             String   @id @default(uuid())
  projectId      String?
  title          String
  status         String   @default("proposed")  // proposed|accepted|deprecated|superseded
  context        String   // 为什么要做这个决策（背景）
  decision       String   // 决策是什么
  consequences   String   // 后果是什么（正面+负面）
  alternativesConsidered String?  // JSON array
  supersedes     String?  // 前一个 ADR 的 id
  createdAt      DateTime @default(now())
  updatedAt      DateTime @updatedAt
  project        Project? @relation(fields: [projectId], references: [id])
}
```

### 5.2 生命周期
```
proposed → (review) → accepted → (使用) → [maintain] or [superseded by ADR-N]
                                     ↓
                                 deprecated
```

- `proposed` 状态下的 ADR 必须标注"决策前的不确定性"，让 PM/老板知道要过 gate
- `superseded` 时 ADR 不删，只标记——历史决策链完整可追溯

### 5.3 回放/回顾
- `list_adrs(project_id)` — 按项目列决策链
- `diff_adr(adr1, adr2)` — 两次决策对比，尤其 supersedes 链
- `recap_quarterly()` — 季度 ADR 综述，用于老板的季度复盘

---

## 6. CTO 独有的数据资产

### 6.1 ADR（见 §5）

### 6.2 技术风险档案（TechRisk）
```prisma
model TechRisk {
  id             String   @id @default(uuid())
  projectId      String
  dimension      String   // 见 §2.2 的 7 维度
  description    String
  likelihood     Float
  impact         String   // low|mid|high
  mitigation     String
  earlyWarningSignal String
  status         String @default("open")  // open|mitigated|materialized|closed
  materializedAt DateTime?  // 风险真的发生的时间（如果发生）
  createdAt      DateTime @default(now())
}
```

复盘价值：看"open 的风险 vs materialized 的" → 预测准确度，用于改进风险模型。

### 6.3 技术债登记（TechDebt）
结构同 §2.6 输出。关键字段 `repaid_at` 记录债何时被还清——用于算团队"修债速度"。

### 6.4 代码评审档案（CodeReview）
存 `review_code` 的每次输出 + 对应 PR/commit。价值：后续分析哪类 issue 高频，指导建立 linting 规则。

### 6.5 工程师能力档案（EngineerProfile）—— 和 AIHR 的接口
```prisma
model EngineerProfile {
  id          String   @id @default(uuid())
  legionId    String?  // L1 指挥官
  humanMember String?  // 人类工程师（飞书 open_id）
  skills      String   // JSON: {language: level, domain: level}
  strengths   String[]
  weaknesses  String[]
  lastAssessment DateTime
}
```

这张表是**AIHR 招人时参考的输入**——CTO 评估过的工程师画像，HR 做定向挖人。

---

## 7. MVP 实现顺序（首版上线路线）

按"价值密度 × 实现难度"排序：

| 阶段 | 工具 | 为什么先做 | 难度 |
|-----|------|----------|-----|
| **M1** | `evaluate_prd_feasibility` | 最高价值——PM 的每个 PRD 都必然经过这个 gate，马上能用 | 中 |
| **M1** | `record_tech_decision` + ADR 表 | 基础设施——后续所有工具产出都要依赖 ADR | 低 |
| **M2** | `review_architecture` | 覆盖 PRD 到架构的深度评审 | 中高 |
| **M2** | `assess_technical_risk` + TechRisk 表 | 风险是 CTO 的首要职责 | 中 |
| **M3** | `review_code` + CodeReview 表 | 军团 PR 落地后再开这个（需要军团先成熟） | 中 |
| **M3** | `recommend_tech_stack` | 新项目启动点需要 | 低 |
| **M4** | `analyze_technical_debt` + TechDebt 表 | 项目运转一段时间后才有意义 | 高 |
| **M4** | `propose_refactor` | 依赖 analyze_technical_debt 有产出 | 中 |

**里程碑门槛**：
- **M1 完成** = CTO 可以做 PRD 过审 + 决策记录。单一工具就是"最小产品"（PM 每写 PRD，CTO 必签字）
- **M2 完成** = CTO 可以独立审任何新提案
- **M3 完成** = CTO 和军团形成 PR → review 闭环
- **M4 完成** = CTO 有完整的技术资产体系

---

## 8. 与 PM 的边界（冲突仲裁）

### 8.1 哪些决定是 CTO 的（不需要 PM 同意）
- 技术栈选型的**候选排除**（CTO 说 A 不适合，PM 不能强推 A）
- 代码评审 `blocker` verdict（阻塞 merge）
- 架构违规判定
- 技术风险等级的**客观评估**（分数是评估出来的，不是商量出来的）

### 8.2 哪些决定是 PM 的（CTO 只能建议）
- 做不做某个 feature
- feature 排期优先级
- scope 取舍（砍 P2 保 P0 这种）
- 产品方向整体调整

### 8.3 冲突时的仲裁机制
- CTO 和 PM 对同一事项有分歧时，双方产出各自立场（结构化 JSON）
- 自动升级到老板（张骏飞）飞书
- 老板裁决，结果写入 ADR（超级 ADR，status=`accepted_by_owner`）

---

## 9. 上线策略（分阶段启用）

### 阶段 A：空跑验证（本周）
- AICTO profile 跑通基础对话 ✅（已完成 2026-04-23）
- 在 `111222` 群里和 CTO 聊技术话题，验证 SOUL.md 的人格一致性
- 不接专有工具——验证对话体验

### 阶段 B：M1 上线（下周？）
- 实现 `evaluate_prd_feasibility` + `record_tech_decision`
- 新建 ADR 表（Prisma migration，加到 prodmind 的 dev.db 里）
- 接入 PM 的 pre_dispatch_hook
- Dogfood：挑 1 个最近 PM 写的 PRD 跑一次评估，看输出质量

### 阶段 C：M2 上线
- `review_architecture` + `assess_technical_risk` + TechRisk 表
- 完整跑一次"新需求 → 评估 → 分派"的闭环

### 阶段 D+：M3/M4 按需
- M3 要等军团 PR 流程成熟（Phase 7 完成后）
- M4 要等项目运行 3+ 周

### 每阶段质量门槛（Go/No-Go）
- 输出必须**结构化 JSON**（不是自由文本），否则下游无法机读
- 至少跑 3 个 dogfood 样例无 hallucinate（SOUL.md 里反幻觉纪律的实际验证）
- ADR 产出率 ≥ 90%（非琐碎决策都有留痕）

---

## 10. 开放问题

1. **ADR 放在哪个 dev.db** —— prodmind 的还是 AICTO 独立？倾向 prodmind 共享（PM 可读），但 CTO 写入要有权限控制
2. **CTO 的飞书人格签名** —— 是用 "AICTO" 还是给个拟人化名字？（PM 叫张小飞，对应 CTO 叫什么？`张小架`？`张小工`？）待老板定
3. **和军团的直连**—— §4.1 说 CTO 不直接调军团，但军团 @ CTO 咨询时 CTO 如何响应？需不需要一个 `consult_commander` 工具？
4. **评审的反馈强度** —— CTO verdict 多硬？"blocker" 是真的阻塞 merge，还是只是"强烈建议"？（硬约束会改变军团 workflow，需要和 L1 指挥官约定）
5. **跨项目技术债盘点** —— CTO 的 technical_debt 是项目级还是跨项目？跨项目的话需要一个"云智 AI 团队全栈技术债 dashboard"

---

## 附录：和既有 Phase 7 实施的关系

当前 prodmind Phase 7 在 worktree 里跑（27 个 feature）。完成后会多出：
- Project.mode（legion/human/hybrid）
- TeamMember.memberType（human/legion_commander）
- authorization_scope
- CommanderOutbox

**这些字段 AICTO 要利用**：
- evaluate_prd_feasibility 的 output 里带 `recommended_mode`（建议走军团还是人工）
- assess_technical_risk 参考 `authorization_scope` 判断风险边界
- ADR 的 `projectId` 依赖 Project 表（已有）

Phase 7 完成后，AICTO M2 阶段可以直接用这些字段，不用重做。

---

**下一步**：
1. 和老板对 §10 五个开放问题的立场
2. 对齐 M1 的落地时间窗口
3. 决定 ADR 表放 prodmind 还是独立 db
4. 开 AICTO M1 的 spec 文档（类似 phase-7-legion-hybrid-team-spec.md 的深度）
