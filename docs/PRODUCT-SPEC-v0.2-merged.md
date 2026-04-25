# AI CTO 程小远 — 产品方案设计 v0.2（合并版）

> 基于 PM (张小飞) v0.1 飞书方案 × AICTO 本地 v0.1 设计的合并版
>
> **合并原则**：PM 版的端到端闭环作为 Phase 1 骨架（快速落地）；本地版的决策资产层（ADR / TechRisk / TechDebt / EngineerProfile）作为 Phase 2 基础设施。名字采用 PM 版的"**程小远**"。
>
> 版本：v0.2 · 2026-04-23 · 作者：张骏飞 × 张小飞 × AICTO 合并

---

## 一、定位（解决"PM 越权"问题）

### 现状（broken）

```
张骏飞（团队负责人）→ 张小飞(PM) → dispatch_to_legion → 凤凰军团
                                                      → 赤龙军团
                                                      → ...
```

**问题清单**：
1. PM 不具备技术决策能力，直接派军团 = **越权**
2. 军团收到的任务缺乏技术评审、架构设计
3. 各军团独立工作，无跨军团协调
4. 无人做代码审查，质量无保障
5. 团队负责人偶尔人工介入技术决策，不可持续

### 目标状态（fixed）

```
张小飞(PM) ──需求/PRD──→ 程小远(CTO) ──技术方案+任务──→ 军团指挥官
    ↑                       ↓                              ↓
    └──进度汇报──────────── 代码审查 ←──────── PR/交付物 ──┘
```

PM 定义 **WHAT**（需求 + 优先级），程小远决定 **HOW**（技术 + 调度 + 质量），军团执行 **DO**（代码实现）。

---

## 二、程小远是谁

| 维度 | 定义 |
|------|------|
| 身份 | 独立 Hermes profile `aicto` + 飞书身份"程小远"（app `cli_a9495f70ddb85cc5`） |
| 角色 | Tech Lead / CTO — 云智 AI 团队的技术负责人 |
| 上游 | 张小飞（PM）— 接收需求和 PRD |
| 下游 | 各军团指挥官 — 分发任务、收集产出 |
| 平级 | 颜小汐（设计，未来）、卫小严（QA，未来）、瞿小明（情报官，未来）|
| 汇报 | 向张小飞汇报进度，向团队负责人（张骏飞）同步技术风险 |
| 基础设施 | `~/Documents/AICTO/` + `~/.hermes/profiles/aicto/` |

**拟人化家族**：张小飞（PM）· 程小远（CTO）· 颜小汐（Designer）· 卫小严（QA）· 瞿小明（情报官）· AI HR（待命名）

---

## 三、核心价值链（Phase 1 端到端闭环）

```
输入：张小飞发来一份 PRD 或需求描述
  ↓
Step 1：技术方案设计
  程小远读 PRD → 评估技术可行性 → 选技术栈 → 设计架构 → 输出《技术方案》
  ↓
Step 2：任务拆分
  《技术方案》→ 拆成可分配的开发任务 → 评估每个任务的复杂度和依赖关系
  ↓
Step 3：军团调度
  根据任务类型 + 军团能力 + 军团当前负载 → 分配任务给对应军团指挥官
  ↓
Step 4：进度追踪
  定期查询军团状态 → 发现阻塞主动介入 → 跨军团依赖协调
  ↓
Step 5：代码审查
  军团提交 PR → 程小远审查架构一致性、代码质量、安全性 → 批准或打回
  ↓
Step 6：交付汇报
  审查通过 → 合并 → 通知张小飞"xx 功能已交付" → 附验收要点
  ↓
输出：可验收的代码交付物 + 进度报告
```

**Phase 1 MVP 验收**：挑一份真实 PRD（例如"AI 客服"），让程小远从 PRD 走到代码交付，全流程飞书可见。

---

## 四、六大核心能力（Phase 1 落地）

**2026-04-23 老板明确**：程小远是**项目级自动化运营者**——从"创建项目路径"到"持续跟进军团开发"全链路由程小远自动完成。PM 只负责定义 WHAT（需求 + 优先级），**项目执行的全部 HOW 由程小远自理**。

自动化范围：
1. 项目路径创建（git 仓库 / 本地目录 / Hermes 配置 / ProdMind 项目条目）
2. 项目内军团体系初始化（调用 legion 基础设施）
3. 首个开发军团组建 + 指挥官持久化通讯建立
4. 任务分配给指挥官
5. 持续跟进开发进展（不是被动等汇报）

---

### 能力 0：项目启动（Project Kickoff — 自动化）

**触发**：PM 发起一个新项目（通过飞书"我要做个 xxx"）→ 程小远介入

**全流程动作**：
```
PM 发起新项目 → 程小远：
  1. 创建项目路径：git init ~/Documents/<project-name>
  2. 初始化目录骨架（CLAUDE.md / docs/ / .planning/ 等）
  3. 在 ProdMind dev.db 创建 Project 行（联 PM 填 mode=legion + authorization_scope）
  4. 写 ADR-0001：项目启动决策（标 context=PRD 摘要 + 老板意图）
  5. 拉起军团体系：调用 `legion init` / `create_legion` 辅助函数
  6. 组建第一个开发军团：
     - 根据 PRD 技术栈匹配军团类型（前端/后端/全栈/数据）
     - 命名：`L1-<项目代号>-<军团类型>`（如 L1-AICS-后端）
     - 创建指挥官 inbox + outbox 文件（~/.claude/legion/<id>/team-<name>/）
  7. 建立持久化通讯：
     - 在 ProdMind TeamMember 表写入 `memberType=legion_commander`
     - 双向 channel：PM/CTO ↔ 指挥官 mailbox（inbox + outbox 各自一份）
  8. 回传老板：飞书群发"项目 X 已启动，军团 Y 就位，首批任务 Z 已分配"
```

**输入**：
- `project_name`（项目代号）
- `prd_id` 或 `requirement_markdown`（需求源）
- `tech_hint`（可选：老板/PM 已有的技术栈倾向）

**输出**（结构化）：
```json
{
  "project": {
    "id": "uuid",
    "name": "AI 客服",
    "path": "/Users/feijun/Documents/AICS",
    "git_initialized": true,
    "mode": "legion",
    "authorization_scope": "程小远可自主分派代码实现 + 架构评审"
  },
  "legion_system": {
    "commander_id": "L1-AICS-后端",
    "inbox_path": "~/.claude/legion/<id>/team-L1-AICS-后端/inboxes/L1-AICS-后端.json",
    "outbox_path": "~/.claude/legion/<id>/team-L1-AICS-后端/outbox.jsonl",
    "communication_ready": true
  },
  "initial_tasks_dispatched": [
    {"task_id": "T001", "title": "..."}
  ],
  "adr_id": "ADR-0001",
  "feishu_notification_sent": true
}
```

**关键决策点**：
- **权力边界**：本能力**不需 PM 每步审批**——老板一旦批 `create_project`，程小远就有 full authority 走完步骤 1-8
- **不可逆点**：`git init` + `Project` DB 写入是不可逆（但非破坏性）。成功后回传老板，失败则自动 rollback（删目录 + 删 DB 行 + 删 legion 文件）
- **技术栈选择权**：第 6 步的军团类型选择由程小远自主决定（基于 PRD），PM 不干预——PM 干预的节点是"PRD 定义"的质量，不是"怎么派军团"
- **新项目 = 新 ADR**：第 4 步的 ADR-0001 是每个新项目必有的起点决策

**依赖**：
- `create_project`（ProdMind 现有工具，写 dev.db）
- `create_legion` / `dispatch_to_legion`（ProdMind 现有工具）
- git CLI（本地）
- 飞书 API（通知）

**失败分类与升级路径**（2026-04-23 老板明确）：

程小远在启动步骤 1-8 过程中遇到错误，先按**错误性质分类**再决定处理：

| 错误类型 | 例子 | 处理方式 | 通知谁 |
|---------|------|---------|-------|
| 🔧 **技术/环境问题** | `git init` 冲突、端口被占、Hermes 子进程挂、SQLite 锁、磁盘满、网络临时抖动 | **程小远自主解决** — 自动 rollback + 重试（最多 3 次）+ 尝试替代方案（换端口/换名字/绕过） | 不打扰人类 |
| 🔒 **权限/凭证问题** | 飞书 API 403（app 不是协作者）、legion mailbox 无写权限、仓库 push 凭证过期、某工具未开通 | **暂停 + 升级需求方** —— 飞书 @ 张骏飞 说明"哪一步哪个资源被拒，需要你做 X 才能继续" | 老板（张骏飞）|
| ❓ **意图/歧义问题** | PRD 描述模糊无法选军团类型、老板 mode 选择冲突、资源冲突（两个项目争同一军团名） | **暂停 + 升级需求方** —— 飞书 @ 张骏飞 + 给出 2-3 个选项让老板裁决 | 老板（张骏飞）|
| 🚫 **未知错误** | 未预期的 exception、tools.py 里的 bug | **保守升级** —— 暂停项目启动，飞书通知老板 + 附 stack trace，等人工介入 | 老板（张骏飞）|

**判断规则实现**：
- 每个工具调用包在 `try/except` 里
- Exception 捕获后按 type + message 做关键词匹配分类：
  - `OSError` / `GitError` / `ConnectionError` / `TimeoutError` / `sqlite3.OperationalError` → **Tech/Env**
  - HTTP 401/403 / `PermissionError` / FeishuError code ∈ {1063002, ...} → **Permission**
  - 自定义 `AmbiguityError`（工具主动抛）→ **Intent**
  - 其他所有 Exception → **Unknown**
- Tech/Env 类问题**自动重试 3 次**（指数退避），仍失败则降级为 Unknown 升级老板
- 所有升级通知都通过飞书 @ 老板 + 附上下文（哪个项目、哪一步、错误摘要、已尝试的重试记录）

**不升级 PM 的理由**：PM 的职责是 WHAT（需求定义），项目启动的 HOW 失败对 PM 是噪音。只有项目启动完毕后的"运营期"问题才可能 CC PM。团队负责人张骏飞作为 team lead 参与裁决，不是单向下达的甲方。

---

**风险点**：
- 新项目名冲突 → 前置检查 `~/Documents/<name>` 存在性
- 军团组建失败（legion infra 未就绪）→ fallback：创建"待命军团"，延迟派单直到 legion 恢复
- 老板突然改 mode 或 scope → 在第 2 步后的 "mode confirmation" 增加 30s 等待窗口（老板 @ 反悔可打断）

---

### 能力 1：技术方案设计

**触发**：收到张小飞发来的 PRD 或需求（通过飞书 @ 程小远 或 PM 工具调用）

**输入**：
- `prd_id`（ProdMind Project/PRD 表 ID）或 `prd_markdown`（直接传文本）
- `focus`（可选：time_cost / tech_feasibility / scalability / team_fit / all）

**输出**（结构化 JSON + 飞书文档）：
```json
{
  "feasibility": "green|yellow|red",
  "time_estimate_days": {"optimistic": 5, "likely": 10, "pessimistic": 15},
  "tech_stack_choice": {
    "selected": "Next.js + Prisma + SQLite",
    "alternatives_rejected": [{"name": "...", "reason": "..."}],
    "fit_score": 8
  },
  "architecture_summary": "...",
  "data_model_hint": "...",
  "api_contracts": [...],
  "dependencies": ["第三方库 X（版本 Y，许可证 Z）"],
  "risks": [{"dimension": "...", "severity": "high", "mitigation": "..."}],
  "missing_info": ["PRD 里没说清楚的点"],
  "doc_url": "https://ucnrf25nllyh.feishu.cn/docx/xxx"
}
```

**关键决策点**：
- `red` verdict 必须**明确告诉 PM 要改什么才能绿**（不能只说不可行）
- `time_estimate_days` 三档估（乐观/可能/悲观），PM 用悲观决定范围
- `missing_info` 反向推回 PM 澄清，**过不了就不能进 Phase 4 分派**

**依赖**：
- `get_prd(prd_id)`（读 ProdMind 的 PRD 上下文）
- 技术决策记录表 ADR（自动写入，见 §七）
- web_search（新技术的社区反馈/issue）

---

### 能力 2：任务拆分与排序

**触发**：技术方案设计完成后自动触发，或 PM 手动要求

**输入**：
- `tech_plan_id`（上一步输出的技术方案 ID）

**输出**：结构化任务列表
```json
{
  "tasks": [
    {
      "id": "T001",
      "title": "...",
      "description": "给开发者读完就能动手的详细描述",
      "depends_on": ["T000"],
      "complexity": "S|M|L|XL",
      "recommended_legion": "凤凰军团",
      "acceptance_criteria": [
        {"given": "...", "when": "...", "then": "..."}
      ],
      "estimated_hours": 4
    }
  ],
  "dependency_graph": "DAG 可视化（mermaid）",
  "total_estimated_hours": 40
}
```

**关键决策点**：
- 单任务不超过 XL（>=3 天），大于 XL 必须再拆
- 依赖关系强制 DAG（不允许环）
- 每个任务的验收标准必须结构化（Given/When/Then）

---

### 能力 3：军团调度

**触发**：任务拆分完成 + PM 批准分派

**分配规则**：
1. 按任务技术栈匹配军团能力（`EngineerProfile` 表，见 §六）
2. 查询军团当前负载（`query_legion`），避免过载
3. 有依赖关系的任务**按顺序分发**（后置任务等前置完成）
4. 单个军团同时不超过 **2 个任务**
5. 分发时附完整上下文（PRD 摘要 + 技术方案 + 相关代码库位置）

**输出**：
```json
{
  "assignments": [
    {
      "task_id": "T001",
      "legion_id": "L1-凤凰军团",
      "dispatched_at": "2026-04-23T19:30:00",
      "mailbox_msg_id": "msg-xxx"
    }
  ]
}
```

**和 PM 的边界**（关键）：
- CTO 拥有**调度决策权**（派给哪个军团）
- PM 保留**分派授权权**（是否启动 Phase 4）
- 冲突时走"升级到老板"仲裁

---

### 能力 4：代码审查

**触发**：军团交付 PR / auto run 完成某个 feature / CTO 主动扫描

**10 项审查清单**（每项 PASS / BLOCKING / NON-BLOCKING）：

| # | 维度 | 检查点 |
|---|------|-------|
| 1 | 架构一致 | 是否符合技术方案的架构设计？ |
| 2 | 可读性 | 代码是否可读、命名是否规范？ |
| 3 | 安全 | 是否有明显安全漏洞？ |
| 4 | 测试 | 是否有测试覆盖关键路径？ |
| 5 | 错误处理 | 是否处理了错误和边界情况？ |
| 6 | 复杂度 | 是否有不必要的复杂性？ |
| 7 | 依赖 | 第三方依赖是否合理？ |
| 8 | 性能 | 性能是否可接受？ |
| 9 | 跨军团冲突 | 是否与其他军团的代码冲突？ |
| 10 | PRD 一致 | 是否满足 PRD 中的验收标准？ |

**结论规则**：
- 0 个 BLOCKING → 批准合并
- 有任一 BLOCKING → 打回并说明修改要求
- NON-BLOCKING 进入 TechDebt 档案（见 §六），不阻塞但留痕

---

### 能力 5：进度汇报

**主动行为**：
1. 每个任务分派后追踪到完成
2. 发现阻塞（军团 >24h 无进展、或出现 BLOCKING review 后未修）→ **主动在飞书群通知** 张小飞 + 老板
3. 每日 18:00 在飞书群发技术进度摘要（所有在飞项目汇总）
4. 军团交付后**主动通知 PM 做产品验收**

**输出**：飞书群消息 + ProdMind Activity 记录

---

## 五、组织协作矩阵

### 程小远 vs 张小飞（PM）

| 张小飞负责 | 程小远负责 |
|-----------|-----------|
| 做什么（What）| 怎么做（How）|
| 产品需求和优先级 | 技术方案和架构 |
| 用户价值判断 | 技术可行性判断 |
| 产品验收 | 代码审查 |
| 项目整体进度 | 技术交付进度 |

### 程小远 vs 军团指挥官

| 程小远负责 | 指挥官负责 |
|-----------|-----------|
| 跨军团任务分配 | 军团内部任务执行 |
| 整体架构一致性 | 具体代码实现 |
| 代码审查（PR 级） | 开发过程管理 |
| 技术风险升级 | 技术问题解决 |

### 程小远 vs 卫小严（QA · Phase 3+）

| 程小远负责 | 卫小严负责 |
|-----------|-----------|
| 代码质量（技术层面） | 功能质量（用户层面） |
| 架构审查 | E2E 测试 |
| 安全审查 | 回归测试 |
| 合并决策 | 发布决策 |

---

## 六、技术实现架构

### Phase 1 技术实现

```
程小远 = 一个 Hermes profile（aicto）
├── SOUL.md：CTO 角色定义 + 行为准则 + 反幻觉纪律
├── Skills：技术方案模板、代码审查清单、军团调度策略
├── Memory：跨对话记忆（项目技术栈、军团能力画像、架构决策历史）
├── 飞书身份：程小远（app cli_a9495f70ddb85cc5，可被 @、可发消息/文档）
├── 端口：8644（独立，不影响 default PM 的 8642、ai-hr 的 8643）
└── 工具集：
    ├── design_tech_plan（能力 1）
    ├── breakdown_tasks（能力 2）
    ├── dispatch_to_legion（能力 3，复用 ProdMind 现有工具）
    ├── query_legion（能力 3 辅助）
    ├── review_code（能力 4）
    ├── escalate_risk（能力 5）
    └── record_tech_decision（Phase 2 ADR 核心，下文 §七）
```

### Phase 2 决策资产层（本地 v0.1 的核心贡献）

除 Phase 1 的执行工具，CTO 还需要**独有的数据资产**来支撑长期决策质量：

#### 6.1 ADR 表（Architecture Decision Records）

```prisma
model ADR {
  id             String   @id @default(uuid())
  projectId      String?
  title          String
  status         String   @default("proposed")  // proposed|accepted|deprecated|superseded
  context        String                          // 为什么做这个决策（背景）
  decision       String                          // 决策是什么
  consequences   String                          // 后果（正面+负面）
  alternativesConsidered String?                 // JSON array
  supersedes     String?                         // 前一个 ADR 的 id
  createdAt      DateTime @default(now())
  updatedAt      DateTime @updatedAt
  project        Project? @relation(fields: [projectId], references: [id])
}
```

**生命周期**：proposed → accepted → [ maintain / superseded_by ADR-N ] → deprecated

**价值**：
- 所有技术决策白纸黑字留痕
- 新人入组能读懂"为什么选 A 不选 B"
- 决策演化链可追溯

#### 6.2 TechRisk 表

```prisma
model TechRisk {
  id             String   @id @default(uuid())
  projectId      String
  dimension      String   // dependency/integration/team_skill/vendor/compliance/performance/security
  description    String
  likelihood     Float    // 0.0 ~ 1.0
  impact         String   // low|mid|high
  mitigation     String
  earlyWarningSignal String // 什么信号说明风险开始发生
  status         String @default("open")  // open|mitigated|materialized|closed
  materializedAt DateTime?  // 风险真发生的时间
  createdAt      DateTime @default(now())
}
```

**复盘价值**：open → materialized 比例 = CTO 风险预测准确度，用来迭代风险模型。

#### 6.3 TechDebt 表

```prisma
model TechDebt {
  id          String   @id @default(uuid())
  projectId   String?
  category    String   // duplication/coupling/test_gap/outdated_dep/perf/security/doc
  location    String   // file:line 或 pattern
  severity    String   // low|mid|high
  impactOnVelocity  String  // 这个债如何拖慢迭代
  estimatedRefactorEffortDays Int
  suggestedRefactor String
  status      String @default("open")   // open|accepted|repaid|obsolete
  repaidAt    DateTime?
  createdAt   DateTime @default(now())
}
```

**价值**：量化技术债，支持"每周还多少债"的工程健康度指标。

#### 6.4 CodeReview 表

```prisma
model CodeReview {
  id          String   @id @default(uuid())
  projectId   String
  taskId      String?
  prUrl       String?
  commitSha   String?
  verdict     String   // approved|changes_requested|rejected
  comments    String   // JSON array of CodeReviewComment
  blockerCount    Int @default(0)
  suggestionCount Int @default(0)
  reviewedAt  DateTime @default(now())
}
```

**价值**：历史评审数据驱动**自动 linting 规则**（同类问题高频 → 自动检测）。

#### 6.5 EngineerProfile 表（和 AIHR 的接口）

```prisma
model EngineerProfile {
  id          String   @id @default(uuid())
  legionId    String?  // 军团指挥官
  humanMember String?  // 人类工程师飞书 open_id
  skills      String   // JSON: {language: level, domain: level, legion_workflow: level}
  strengths   String[]
  weaknesses  String[]
  lastAssessment DateTime
}
```

**关键**：这张表是 AIHR 招人时的**输入**——HR 按 CTO 评估过的工程师画像做定向挖人，形成 CTO → HR 反向驱动。

---

## 七、和 ProdMind 的数据共享

所有 CTO 独有表放在 **ProdMind 的 dev.db** 里共享（按原则："数据属于项目，不属于员工"）：

| 表 | PM 权限 | CTO 权限 | 说明 |
|----|---------|---------|------|
| Project | RW | R | 项目元数据 |
| PRD | RW | R | PRD 版本链 + decisions |
| UserStory / Feature | RW | R | |
| Task | RW | R + 评审 write | CTO 可加 review_result |
| TeamMember | R | R | |
| **ADR** | R | RW | 架构决策记录 |
| **TechRisk** | R | RW | 技术风险档案 |
| **TechDebt** | R | RW | 技术债登记 |
| **CodeReview** | R | RW | 代码评审结果 |
| **EngineerProfile** | R | RW | 工程师能力画像（AIHR 读） |

权限隔离靠应用层约束（SQLite 不支持表级权限），Hermes 工具 registry 控制写入能力。

**技术实现** — CTO 读 PM 表的具体方案见 `[CTO-READ-ACCESS-SPEC.md](./CTO-READ-ACCESS-SPEC.md)`：
- SQLite URI `mode=ro` 物理挡写（即使 CTO 代码 bug 也写不了 PM 表）
- 飞书 docx 用 AICTO 自己的 app token 读（依赖权限 bug 修复后 tenant_editable 默认开）
- CTO 发现 PRD 问题只能调 `escalate_to_pm(feedback)` 反馈，**不能直接改 PM 表**
- 审计日志记录每次 CTO 读 PM 数据的 trail

---

## 八、实施路线（MVP → 成熟）

### Phase 1（本周/下周）— 端到端跑通一个真实 PRD

**3 件最小交付物（按 PM v0.1）**：
1. ✅ AICTO profile 已就绪（2026-04-23，SOUL.md + port 8644 + 飞书 app）
2. 🔲 Skills 包（skill file × 5，对应 5 大能力的工作流）
3. 🔲 **Dogfood**：挑一个真实 PRD 走完 Step 1-6

**额外（在 ProdMind dev.db 里）**：
- 🔲 ADR 表 Prisma migration
- 🔲 `record_tech_decision` 工具（Phase 1 就用起来，让决策开始留痕）

**验收**：挑 1 个 PRD（例如"AI 客服"），从 PM 发给程小远 → 方案 → 任务 → 派军团 → 代码审查 → 汇报 PM，**全程飞书可见、飞书可追溯**。

### Phase 2（Phase 1 完成后 1-2 周）— 决策资产层铺开

- 🔲 TechRisk / TechDebt / CodeReview 表上线
- 🔲 `assess_technical_risk` / `analyze_technical_debt` / `review_code` 结构化输出
- 🔲 每周"技术健康度"日报自动生成

**验收**：连续 2 周每个新项目都有 ADR，CTO 给出的风险有 >=70% 预测准确度。

### Phase 3（Phase 2 完成后）— 自主优化

- 🔲 `propose_refactor` 基于 TechDebt 自动生成重构方案
- 🔲 EngineerProfile 打通 AIHR（招人按 CTO 评估挖）
- 🔲 跨项目技术决策综述（季度）

---

## 九、质量门槛（每阶段 Go/No-Go）

| 维度 | 门槛 |
|------|------|
| 输出结构化 | 所有工具输出必须是 JSON（不是自由文本），否则下游无法机读 |
| 反幻觉 | Dogfood 3 个样例，0 hallucination |
| ADR 留痕率 | 非琐碎决策 ≥ 90% 有 ADR 记录 |
| 生产零影响 | 新增 AICTO 能力不得影响 PM / AIHR / default gateway 运行 |
| 军团对接 | Phase 1 能派至少 1 个真实任务到真实军团并收到 ack |

---

## 十、和 Phase 7（Legion Hybrid Team）的关系

ProdMind Phase 7（worktree 里跑）完成后会多出：
- `Project.mode`（legion/human/hybrid）
- `TeamMember.memberType`（human/legion_commander）
- `authorization_scope`（老板选 mode 时的文字授权）
- `CommanderOutbox`（指挥官 ACK 回流）

**程小远直接利用这些**：
- `design_tech_plan` 输出会带 `recommended_mode`（建议走军团还是人工）
- `assess_technical_risk` 参考 `authorization_scope` 判断风险边界
- `review_code` 结果写到 `CommanderOutbox` 反馈给 PM
- ADR 的 `projectId` 关联 Project（已有）

Phase 7 完成 = 程小远的基础设施 80% 铺好，Phase 1 实施可直接利用。

---

## 十一、已解决 / 待确认

### ✅ 已解决（v0.2 合并过程中定下 + 2026-04-23 补充）
1. **CTO 名字**：程小远（PM v0.1 起，本地 v0.2 采纳）
2. **军团调度权**：**完全归程小远**（老板 2026-04-23 明确：从项目启动到军团运营全自动化）
3. **ADR 放哪**：放 ProdMind dev.db 共享（方便 PM 读决策链）
4. **Phase 1 最小交付**：SOUL + Skills + 飞书身份 + 1 个真实 PRD dogfood
5. **项目启动权归 CTO**：新增能力 0（§四），程小远自动创建项目路径、拉起军团、建立持久化通讯、分派首批任务
6. **CTO → 军团直连**：不需要 PM 中转（老板 2026-04-23 明确）。PM 的权力边界收缩到"定义 WHAT"，HOW 全部 CTO 自理

### 🟡 待老板确认
1. **代码审查 verdict 硬度**：`BLOCKING` 是**真的阻塞 merge**（硬 gate）还是"强烈建议"（软 gate）？既然军团调度全归 CTO，倾向**硬 gate** — CTO 说 BLOCKING 军团就停，不走 PM 仲裁
2. **跨项目技术债盘点**：项目级还是云智团队全局级？全局级要一个跨项目 dashboard，单独建设
3. **Dogfood 的 PRD 选哪个**：从现有 prodmind projects 里挑一个跑通端到端（建议 "Phase 7 审查"—— 详见附录 A）
4. **项目启动失败的升级路径**：能力 0 里的步骤 1-8 如果某步失败（git init 冲突、legion infra 挂了），CTO 是自动 rollback + 通知 PM？还是直接升级到老板？

### 🔴 需要老板拍板才能进 Phase 1
- 上述 4 个 🟡 问题中，**问题 1（代码审查 verdict 硬度）** 必须先定，否则军团收到 BLOCKING 不知道该停还是继续

---

## 附录 A · Phase 1 的"第一个真实 PRD"候选

按"技术评审价值 × 闭环可观测"排序，建议从 ProdMind 现有 projects 里挑：

| 候选 | 复杂度 | 跨军团 | 可观测性 | 建议指数 |
|------|-------|--------|----------|---------|
| "AI 客服" 新 PRD | M | 可能 2 个（后端 + 前端） | 高（终端用户用） | ⭐⭐⭐ |
| "Phase 7 审查" 回看 | XL | 已涉及 3+ 军团 | 高（刚有完整实施轨迹）| ⭐⭐⭐⭐ |
| 某个 PM backlog 里的小需求 | S | 单军团 | 低 | ⭐⭐ |

**建议**：挑 "Phase 7 审查" —— 既是对刚完成实施的复盘，又能验证程小远的 review_code 能力。

## 附录 B · 和飞书文档权限 bug 的关联

2026-04-23 用户发现：所有 PM 创建的文档**默认无团队编辑权限**，必须手工分享。已定位到 `feishu_api.py:_grant_doc_tenant_read` 仅设了 tenant_readable，未设 tenant_editable。**已修复**（commit 见 git log）——本 v0.2 文档**本身**不会再有这个问题（由修后的 PM 重新 create 即可自动开权限）。
