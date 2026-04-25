# PRD 6 能力规格抽取（按能力分解 + GAP 分析）

> **派生自**: `PRD-FULL.md`（飞书 docx ZeMedrjG1ogqhnxsxZuc5dF0nfe，2026-04-25 抓取）
> **对照对象**: `/Users/feijun/Documents/AICTO/.dispatch/inbox/task-001-phase1-full.md`（PM 派发简版）
> **目的**: 为架构 spec 阶段提供逐能力的可执行规格 + 暴露派发简版漏掉的 PRD 细节 + 列出需向 PM 反向澄清的点
> **方法**: 对每能力同时引用 PRD 原文与派发原文，逐字段比对

---

## 能力 0：项目启动自动化（kickoff_project）

### 触发条件

> PRD 原文（五节·能力 0）：
> "**触发**：PM 调用 create_project 或飞书 @程小远 说"启动项目 X""

两个入口：
- **机器入口**：PM Agent（张小飞）调用 `create_project`（疑似 ProdMind 已存在工具，PRD 未明示其调用形态——MCP / Hermes inter-agent / HTTP 不详）
- **人机入口**：飞书 IM 中 @程小远 自然语言："启动项目 X"

### 输入 schema

PRD 未给出字段级 schema。可推断的最小集（待澄清）：
- `project_name: str` — "AICS"（来自 PRD 飞书卡片样例）
- 期望伴随字段（PRD 未明示）：项目描述 / 优先级 / 飞书群 chat_id / 期望 Legion 分类（前端 / 后端 / 全栈）

### 输出 schema

> PRD 原文（五节·能力 0）：
> "**输出**：结构化 JSON（project_id / git_path / legion_commander_id / adr_id / initial_tasks）+ 飞书卡片通知"

字段映射（PRD 字面给出 5 字段）：

| 字段 | 类型（推断） | 来源 | 备注 |
|---|---|---|---|
| project_id | str | 8 步中第 3 步"ProdMind 项目条目" | 与 ProdMind dev.db 主键对齐 |
| git_path | str (绝对路径) | 8 步中第 1 步"创建项目目录" | 例：`~/Documents/AICS` |
| legion_commander_id | str | 8 步中第 5 步"拉军团" | Hermes agent_id 形态 |
| adr_id | str | 8 步中第 4 步"ADR-0001" | 编号格式 ADR-NNNN，未给位数 |
| initial_tasks | list[task] | 8 步中第 7 步"派首批任务" | 任务结构 PRD 未给 |

**飞书卡片字段**（PRD 字面给出 ASCII mock）：
- 项目名 `「AICS」`
- Path：`~/Documents/AICS`
- Legion：`L1-AICS-后端 (就位)`
- ADR：`ADR-0001 已记录`
- 状态文案：`等 PM 发 PRD 启动首批任务`
- 操作按钮：`[查看 ADR]` `[加入军团群]` `[暂停项目]`

### 错误处理

> PRD 原文（五节·能力 0）：
> "**失败处理**：4 级错误分类（技术→自主重试 / 权限→升级骏飞 / 意图→给选项 / 未知→保守升级）"

唯一明确写出 4 级错误分类的能力（其他能力 PRD 未明示是否套用同分类）。

| 级别 | 处理动作 | 判定边界 |
|---|---|---|
| 技术 | 自主重试 | PRD 未给：网络/API/LLM 错都算？重试次数？退避策略？ |
| 权限 | 升级骏飞 | PRD 未给：飞书权限不足？git push 拒绝？dev.db 写权限？ |
| 意图 | 给选项 | PRD 未给：选项格式（飞书卡片 vs 自然语言列表）？ |
| 未知 | 保守升级 | PRD 未给："保守"具体是停步还是不重试 |

### 验收标准

> dispatch 派发文件原文（"四、验收标准"第 1 条）：
> "**能力 0**：PM 说"启动项目 X" → 程小远自动完成 8 步 → 飞书群收到启动通知卡片"

PRD 第十节未给该能力 Given/When/Then 验收。

可执行验收标准（待 PM 确认）：
- **Given** PM 已配置好 ProdMind 项目模板 / Hermes profile / 飞书 bot 凭证
- **When** 在飞书群对程小远说「启动项目 测试 X」
- **Then** 飞书群在 ≤30 秒内收到启动卡片（含完整 5 字段：项目名 / Path / Legion / ADR / 状态），同时 git 目录创建、ADR-0001 写入、Legion commander 在线

### PRD 与派发的 GAP

| GAP 类型 | 内容 |
|---|---|
| 派发漏掉 | 飞书卡片 ASCII mock（项目名、Path、Legion、ADR 显示样式、3 个操作按钮） |
| 派发漏掉 | 输出字段与 8 步骤的对应关系（哪一步产出哪个 ID） |
| 待澄清 | 4 级错误分类的判定边界（每级具体落到哪种触发条件） |
| 待澄清 | `create_project` 工具的调用协议（是 ProdMind 暴露的 MCP？Hermes plugin？HTTP API？） |
| 待澄清 | "拉军团"是新建 Legion 还是复用已有 Legion？匹配逻辑？ |
| 待澄清 | 飞书"群通知"是发到哪个群——AICTO 群？项目专属新群？由谁建群？ |

---

## 能力 1：技术方案设计（design_tech_plan）

### 触发条件

PRD 未明示触发入口。可推断：
- PM 在 PRD 评审通过后调用 `design_tech_plan(prd_id=...)`
- 飞书 @程小远 + PRD 链接 / markdown

### 输入 schema

> PRD 原文（五节·能力 1）：
> "**输入**：prd_id 或 prd_markdown + 可选 focus/constraints"

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| prd_id | str | 二选一 | ProdMind dev.db 主键（PRD 未明示表名） |
| prd_markdown | str | 二选一 | 直接传整段 markdown |
| focus | str | 否 | PRD 未给定义（推断：聚焦某个子模块？） |
| constraints | str/list | 否 | PRD 未给定义（推断：技术栈白名单 / 黑名单 / 时限） |

### 输出 schema

> PRD 原文（五节·能力 1）：
> "**输出**：feasibility（green/yellow/red）+ 技术栈选型 + 时间估计（乐观/可能/悲观）+ 风险清单 + 缺失信息 + 飞书文档 URL"

| 字段 | 类型 | 取值/示例 |
|---|---|---|
| feasibility | enum | `green` / `yellow` / `red` |
| tech_stack | list[选型] | 字段 PRD 未细化（推断：language / framework / db / deploy） |
| estimate | object | `{optimistic, likely, pessimistic}`（单位 PRD 未给——天/小时？） |
| risks | list[risk] | 字段 PRD 未细化（推断：与第八节风险表同结构） |
| missing_info | list[str] | 缺失信息条目，反向推回 PM 澄清 |
| feishu_doc_url | str | 飞书 wiki/docx URL |

### 错误处理

PRD 第五节·能力 1 未明示错误分类。**只有能力 0 显式有 4 级分类**——派发简版隐式假设全 6 能力共享，但 PRD 未明确。

PRD 写到的"非常规出口"：
- `red` verdict 不直接报错，但**必须告诉 PM 改什么才能变绿**（非"不可行"而是"需要 X 才可行"）
- `missing_info` 反向推回 PM 澄清，**过不了就不能进任务分派**（即阻塞下游 breakdown_tasks）

### 验收标准

> dispatch 派发文件原文（"四、验收标准"第 2 条）：
> "**能力 1**：给程小远一个 PRD → 输出 feasibility 判断 + 技术栈选型 + 风险清单 + 飞书文档"

PRD 第九节相关 KR：
- KR4：`PRD → 技术方案时间 ≤5 分钟`（基线骏飞 1-2 小时）
- KR2：`100% PRD 有对应技术方案`

可执行验收标准（待 PM 确认）：
- **Given** PM 提供完整 PRD（prd_markdown ≥ 800 字 + 含验收标准）
- **When** 调用 `design_tech_plan(prd_markdown=...)`
- **Then** ≤5 分钟内返回 6 字段完整 JSON + 飞书文档 URL 可访问 + ADR 表至少新增 1 条记录

### PRD 与派发的 GAP

| GAP 类型 | 内容 |
|---|---|
| 派发漏掉 | "red verdict 必须告诉 PM 改什么才能变绿"——派发只说 "feasibility 判断"，没保留"red 必须可行性建议"约束 |
| 派发漏掉 | "missing_info 反向推回 PM 澄清，过不了就不能进任务分派"——派发未保留对下游的阻塞语义 |
| 派发漏掉 | "每个技术选型决策自动写入 ADR 表"——派发未保留 ADR 写入约束 |
| 派发漏掉 | KR4 5 分钟 SLA |
| 待澄清 | `prd_id` 对应的存储介质（ProdMind dev.db 哪张表？远程 API？） |
| 待澄清 | `estimate` 的单位（小时/天/周）和精度 |
| 待澄清 | "飞书文档 URL" 创建到哪个空间？docx 还是 wiki？所有者归属？ |
| 待澄清 | `red` 反弹给 PM 的协议（异步飞书消息？同步阻塞调用？响应式回填同一 prd_id？） |
| 待澄清 | `focus` / `constraints` 的字段定义和示例 |
| 待澄清 | ADR 表存储位置——独立 SQLite vs ProdMind dev.db 共享（dispatch 已识别为风险但 PRD 未给指引） |

---

## 能力 2：任务拆分（breakdown_tasks）

### 触发条件

PRD 未明示触发入口。可推断：
- 能力 1 输出 feasibility=green/yellow 后 PM 或程小远自身调用 `breakdown_tasks(tech_plan_id=...)`

### 输入 schema

> PRD 原文（五节·能力 2）：
> "技术方案 → 结构化任务列表 + 依赖 DAG + 验收标准"

PRD 未明示输入字段。推断：
- `tech_plan_id: str` 或 `tech_plan: object`（来自能力 1 输出）

### 输出 schema

| 字段 | 类型 | 备注 |
|---|---|---|
| tasks | list[task] | 结构化任务列表 |
| dag | object/list[edge] | 依赖关系（强制 DAG，禁环） |
| acceptance | list[gwt] | 每任务 Given/When/Then |

`task` 内部字段 PRD 未细化（推断：title / description / size / suggested_legion / depends_on）。

### 错误处理

PRD 未明示。可推断的错误场景：
- 输入技术方案 feasibility=red → 应拒绝拆分（PRD 隐含约束：能力 1 missing_info 过不了不能进任务分派）
- 检测到环依赖 → 应抛错（PRD：依赖关系强制 DAG，不允许环）
- 单任务 size 超过 XL → 应自动再拆或抛错

### 验收标准

> dispatch 派发文件原文（"四、验收标准"第 3 条）：
> "**能力 2**：给技术方案 → 输出结构化任务列表 + 依赖 DAG + 每个任务有 Given/When/Then"

PRD 关键规则（必须满足）：
- 单任务不超过 XL（≥3 天必须再拆）
- 依赖关系强制 DAG（不允许环）
- 每个任务的验收标准必须 Given/When/Then
- 按 EngineerProfile（未来）推荐军团

可执行验收标准（待 PM 确认）：
- **Given** 已通过能力 1 产出的 tech_plan（feasibility ∈ {green, yellow}）
- **When** 调用 `breakdown_tasks(tech_plan=...)`
- **Then** 返回任务列表，每任务 size ≤ XL（<3 天），依赖图无环（拓扑排序成功），每任务有完整 Given/When/Then 三段式

### PRD 与派发的 GAP

| GAP 类型 | 内容 |
|---|---|
| 派发漏掉 | "按 EngineerProfile（未来）推荐军团"——派发简版能力 2 完全没提 EngineerProfile 概念 |
| 待澄清 | "单任务不超过 XL（≥3 天）"——XL 是按什么基准（人天 / 工时 / 复杂度点）？现有 L1 军团对 XL 的定义是否一致？ |
| 待澄清 | task 内部字段格式（PRD 没列） |
| 待澄清 | DAG 表达方式（adjacency list / edge list / 嵌套？） |
| 待澄清 | EngineerProfile 当前为"未来"——Phase 1 是否还需要 suggested_legion 字段？ 默认怎么填？ |
| 待澄清 | 拆分失败的回退策略（无法拆到 XL 以下时如何处理） |

---

## 能力 3：军团调度（dispatch_to_legion_balanced）

### 触发条件

PRD 未明示。可推断：
- 能力 2 产出 tasks 后，程小远自动遍历 ready 节点（DAG 无前置）→ 调用 dispatch
- 或 PM/骏飞手动调用

### 输入 schema

PRD 未明示。推断：
- `tasks: list[task]`
- `legion_pool: list[legion]`（可能从 Hermes profile 列表或 ProdMind dev.db 读）

### 输出 schema

PRD 未给具体字段。推断：
- `assignments: list[{task_id, legion_id, payload}]`
- `deferred: list[task_id]`（因依赖未就绪而延迟派单）

### 错误处理

PRD 未明示 4 级错误分类是否套用。隐含约束：
- 军团接单失败 ≠ 直接拒（"必须接，可 appeal"）— 但 appeal 是 review_code 通道，非 dispatch 通道
- 所有军团均超载（>2 任务）→ PRD 未给指引

### 验收标准

> dispatch 派发文件原文（"四、验收标准"第 4 条）：
> "**能力 3**：有任务列表后 → 按负载均衡分配给军团 + 附完整上下文"

PRD 关键规则（必须满足）：
- 单军团同时 ≤2 个任务
- 有依赖关系的任务延迟派单
- 派单时附完整上下文（PRD 摘要 + 技术方案 + 验收标准）
- CTO 拥有调度决策权，军团必须接（可 appeal 但不可直接拒）

可执行验收标准（待 PM 确认）：
- **Given** 有 ≥3 个 ready 任务、≥2 个 Legion 在线
- **When** 调用 `dispatch_to_legion_balanced(tasks=..., legions=...)`
- **Then** 每 Legion 同时持有任务数 ≤2，依赖未就绪的任务进入 deferred 队列，每条 assignment.payload 包含 PRD 摘要 + 技术方案 + 验收标准三段

### PRD 与派发的 GAP

| GAP 类型 | 内容 |
|---|---|
| 派发漏掉 | "CTO 拥有调度决策权，军团必须接（可 appeal 但不可直接拒）"——派发能力 3 段落保留了，但未明确"appeal 不在 dispatch 阶段，在 review_code 阶段"——架构 spec 必须明确 appeal 路径 |
| 待澄清 | 全军团均超载时的策略（拒派？排队？升级骏飞？） |
| 待澄清 | "军团能力"的标定来源——Hermes profile 配置、Legion 自填、ProdMind 字段？ |
| 待澄清 | "完整上下文"的载体格式（飞书卡片？JSON payload？markdown 文件路径？mailbox 消息？） |
| 待澄清 | mailbox/outbox 协议是否兼容现有 L1 军团 inbox.jsonl（dispatch 已自识别为风险但 PRD 未给规格） |
| 待澄清 | 是否有调度决策回滚（已派但 Legion 反馈技术上做不了）路径 |

---

## 能力 4：代码审查（review_code）

### 触发条件

PRD 未明示。可推断：
- GitHub PR webhook 触发（但 PRD 未提 webhook）
- 军团主动调用 `review_code(pr_url=...)`
- 飞书 @程小远 + PR 链接

### 输入 schema

PRD 未明示。推断：
- `pr_url: str`（GitHub PR 链接）
- 可能伴随 `tech_plan_id` 用于"架构一致"维度核对

### 输出 schema

PRD 给出每项 PASS / BLOCKING / NON-BLOCKING 三态，但未给整体输出 JSON 形态。推断：

```jsonc
{
  "pr_url": "...",
  "checklist": [
    {"item": 1, "name": "架构一致", "status": "PASS|BLOCKING|NON-BLOCKING", "comment": "..."}
    // ...10 项
  ],
  "blocking_count": 2,
  "comments_total": 5,  // ≤5 强制
  "appeal_url": "..."   // 飞书卡片
}
```

**10 项审查清单**（PRD 字面，逐字保留）：

| # | 维度 | 检查点 |
|---|---|---|
| 1 | 架构一致 | 是否符合技术方案？ |
| 2 | 可读性 | 命名规范、代码清晰？ |
| 3 | 安全 | 有无安全漏洞？ |
| 4 | 测试 | 关键路径有覆盖？ |
| 5 | 错误处理 | 边界情况处理？ |
| 6 | 复杂度 | 有无不必要复杂性？ |
| 7 | 依赖 | 第三方依赖合理？ |
| 8 | 性能 | 性能可接受？ |
| 9 | 跨军团冲突 | 与其他军团代码冲突？ |
| 10 | PRD 一致 | 满足验收标准？ |

### 错误处理

PRD 未明示 4 级分类。能力 4 自有专用 BLOCKING 处理流程：

**BLOCKING 硬 gate 规则（骏飞 2026-04-23 拍板）**：
- BLOCKING = 真阻塞 merge，军团必须停 + 修 + 重 PR
- BLOCKING 必须附明确修复要求（"把 X 改成 Y 因为 Z"，不允许 "这里不好"）
- 军团忽略 BLOCKING = 执行纪律违规，自动升级骏飞

**Appeal 通道**：
- 军团觉得 BLOCKING 不合理 → 提 appeal
- 程小远收到 appeal → 要么收回 BLOCKING 并说明理由，要么维持并升级骏飞仲裁
- Appeal 飞书卡片字段：PR 编号 / 标题 / BLOCKING 内容 / 军团理由 / 3 个操作按钮（维持 / 收回 / 升级骏飞）

**评论密度限制（防过度审查）**：
- 单 PR 最多 5 个评论（超出按 severity 排序只留 top 5）
- 单文件最多 2 个 BLOCKING（超出建议整体 refactor）

### 验收标准

> dispatch 派发文件原文（"四、验收标准"第 5 条）：
> "**能力 4**：军团提交 PR → 按 10 项清单审查 → BLOCKING 附明确修复要求 → appeal 通道可用"

PRD 第九节相关指标：
- BLOCKING 准确率 ≥90%（骏飞复核）— 前 10 次强制复核
- 军团 appeal 率 ≤20%

可执行验收标准（待 PM 确认）：
- **Given** 军团提交一个含已知 BLOCKING（如缺测试 + 安全漏洞）和已知 NON-BLOCKING（如命名瑕疵）的 PR
- **When** 程小远收到 PR webhook / 调用
- **Then** 输出含 10 项 status 完整列表 + BLOCKING 附"X→Y 因为 Z"格式修复指令 + 总评论数 ≤5 + 单文件 BLOCKING ≤2 + appeal 飞书卡片可点击触发

### PRD 与派发的 GAP

| GAP 类型 | 内容 |
|---|---|
| 派发漏掉 | Appeal 飞书卡片 ASCII mock（PR 标题 / BLOCKING 内容 / 军团理由 / 3 操作按钮） |
| 派发漏掉 | "BLOCKING 必须附明确修复要求（不是这里不好而是把 X 改成 Y 因为 Z）"的精确文案约束 |
| 派发漏掉 | "军团忽略 BLOCKING = 执行纪律违规，自动升级骏飞"——派发未保留升级路径 |
| 待澄清 | PR 接入方式——GitHub webhook？Hermes plugin 主动轮询？军团 commander 主动通知？ |
| 待澄清 | "BLOCKING 准确率 ≥90%"的分母分子定义（10 个 BLOCKING 中 9 个被骏飞维持算 90%？） |
| 待澄清 | "军团 appeal 率 ≤20%"分子分母（appeal 数 / BLOCKING 总数 ？ appeal 数 / PR 总数？） |
| 待澄清 | 跨军团冲突维度（第 9 项）的检测方法——读其他军团 git log？ProdMind 字段？ |
| 待澄清 | 单文件 >2 BLOCKING 时"建议整体 refactor"是输出建议还是触发新任务？ |
| 待澄清 | Appeal 升级骏飞的载体（飞书私聊？飞书群艾特？专用 Hermes 通道？） |

---

## 能力 5：进度汇报（daily_brief + escalate）

### 触发条件

PRD 字面三个触发：
1. **每日 18:00** 定时（cron 性质）— 全军团技术进度摘要
2. **BLOCKING 事件** 即时推送（来自能力 4 输出）
3. **军团 >24h 无进展** 自动催促（需要某种心跳/状态轮询）

### 输入 schema

PRD 未明示。推断：
- 18:00 触发时无外部输入，从 ProdMind dev.db / 飞书消息 / Hermes state 自查
- BLOCKING 推送：从能力 4 输出 hook
- 24h 催促：从军团任务状态扫描（mtime / status 字段）

### 输出 schema

PRD 未给字段。推断：
- 18:00 brief：飞书群消息 / 卡片，结构化分项（每项目 / 每军团进展）
- BLOCKING 推送：飞书消息 + PR 链接 + BLOCKING 摘要
- 24h 催促：飞书 @军团 commander + 任务 ID + 已停滞时长

### 错误处理

PRD 未明示。隐含约束：
- 飞书发送失败应重试（属技术错误？4 级中"自主重试"层级未明确扩展到此能力）
- 18:00 cron miss（如 Hermes 宕机重启）→ PRD 未给补发策略

### 验收标准

> dispatch 派发文件原文（"四、验收标准"第 6 条）：
> "**能力 5**：每日 18:00 自动发技术进度摘要 → BLOCKING 即时推送 → >24h 无进展触发催促"

可执行验收标准（待 PM 确认）：
- **Given** 多个进行中的项目和 ≥1 个出现 BLOCKING 的 PR
- **When** 时钟到 18:00 / BLOCKING 产生 / 任务 mtime 距今 >24h
- **Then** 飞书群分别在三种触发下收到对应消息（brief 含每项目状态；BLOCKING 推送含 PR 链接；催促消息 @对应 commander）

### PRD 与派发的 GAP

| GAP 类型 | 内容 |
|---|---|
| 派发漏掉 | "骏飞每天 30 秒看一眼群消息就掌握全部技术进度"——隐含输出格式是高度概括的群消息，非长报告 |
| 待澄清 | 18:00 cron 实现机制（Hermes 内置 scheduler？crontab？plugin 自管 asyncio loop？）（dispatch 已自识别为风险） |
| 待澄清 | 时区——18:00 是 UTC+8？服务器本地时间？PM/骏飞所在时区？ |
| 待澄清 | "技术进度摘要"维度（每项目 / 每军团 / 每能力 / 每 KR）和粒度（标题级 / 任务级） |
| 待澄清 | "24h 无进展"判定来源（Hermes session 最后心跳？mailbox 最后消息？git commit mtime？） |
| 待澄清 | 催促失败（24h 后再 24h 还无进展）→ 升级路径？ |
| 待澄清 | 多群发布——是固定一个 AICTO 群，还是按项目群分别发？ |

---

# GAP 总览（PRD 全量 vs 派发简版）

## 一、派发简版漏掉的 PRD 细节（**必须在架构 spec 里补回**）

| # | 漏掉内容 | 来源章节 | 影响范围 |
|---|---|---|---|
| 1 | OKR 4 个 KR（KR1 ≤5次/周 / KR2 100% / KR3 ≤15% / KR4 ≤5min） | PRD §四 | 验收/SLA 设计 |
| 2 | 反角色（不服务谁）3 条 | PRD §三 | 边界/scope 控制 |
| 3 | 能力 0 飞书卡片 ASCII mock 5 字段 + 3 操作按钮 | PRD §五·能力 0 | UI 实现 |
| 4 | 能力 1：red verdict 必须给改进路径（不能只说不可行） | PRD §五·能力 1 | API 行为约束 |
| 5 | 能力 1：missing_info 反向推回 PM 阻塞下游 | PRD §五·能力 1 | 状态机/工作流 |
| 6 | 能力 1：每个技术选型自动写 ADR 表 | PRD §五·能力 1 | 数据持久化设计 |
| 7 | 能力 2：按 EngineerProfile（未来）推荐军团 | PRD §五·能力 2 | 数据模型扩展 |
| 8 | 能力 4：BLOCKING 文案约束（"把 X 改成 Y 因为 Z"） | PRD §五·能力 4 | 输出模板/红队验证 |
| 9 | 能力 4：军团忽略 BLOCKING = 纪律违规自动升级骏飞 | PRD §五·能力 4 | 监督闭环 |
| 10 | 能力 4：Appeal 飞书卡片 ASCII mock 4 字段 + 3 操作按钮 | PRD §五·能力 4 | UI 实现 |
| 11 | 能力 5：日报"30 秒掌握全部进度"= 高度概括而非长文 | PRD §五·能力 5 | 输出格式约束 |
| 12 | P1 Phase 2 蓝图（ADR 生命周期 / TechRisk / TechDebt / CodeReview 历史 / 周报） | PRD §五·P1 | 决策资产层架构预留 |
| 13 | P2 Phase 3 蓝图（propose_refactor / 打通 AIHR / 跨项目综述） | PRD §五·P2 | 长期架构预留 |
| 14 | 非功能：Dogfood 3 样例零幻觉 | PRD §六 | 质量验收 |
| 15 | 风险表 5 项 + 缓解措施（含"骏飞前 10 次强制复核"硬约束） | PRD §八 | 风险登记/治理 |
| 16 | 成功指标 6 项（30 天后衡量）含 BLOCKING 准确率 ≥90% / appeal 率 ≤20% | PRD §九 | 度量埋点设计 |
| 17 | 开放问题（Dogfood 选哪个 PRD / 跨项目技术债范围 / 介入模式 3 项尚未拍板） | PRD §十 | 决策追踪 |
| 18 | "ProdMind dev.db 共享数据层有项目/PRD/任务表可复用" | PRD §二 | 数据层架构选型 |
| 19 | "军团基础设施刚成熟（mailbox/outbox 通讯协议就绪）" | PRD §二 | 通讯协议复用 |

## 二、PRD 不清晰、需向 PM 反向澄清的点（**Q-1 ~ Q-15**）

| # | 待澄清问题 | 涉及能力 | 紧急度 |
|---|---|---|---|
| Q-1 | 4 级错误分类（技术/权限/意图/未知）的判定边界——每级对应哪些具体触发条件（网络超时 / 飞书 token 失效 / LLM 拒答 / git push 拒绝...）？且 4 级是否所有 6 能力共享，还是仅能力 0 适用？ | 能力 0 / 全 | **高** |
| Q-2 | ADR 表存储位置——独立 SQLite vs 与 ProdMind 共享 dev.db？字段 schema？谁写谁读？ | 能力 1 / P1 全 | **高** |
| Q-3 | 飞书 tenant_access_token 2h 过期，PRD 未给缓存刷新策略——文件缓存？内存？Hermes config 注入？ | 全 | **高** |
| Q-4 | 18:00 cron 实现机制——Hermes 内置 scheduler / crontab / plugin 自管 asyncio？时区？补发策略？ | 能力 5 | **高** |
| Q-5 | mailbox/outbox 协议是否兼容现有 L1 军团 inbox.jsonl？是直接复用 prodmind dispatch 的协议还是新设计？ | 能力 0、3 | **高** |
| Q-6 | `create_project` 工具的调用协议（是 ProdMind 暴露的 MCP？Hermes inter-agent message？飞书 webhook？） | 能力 0 | **中** |
| Q-7 | "拉军团"是新建 Legion 还是匹配复用？匹配键（项目类型 / 技术栈 / 历史经验）？ | 能力 0 | **中** |
| Q-8 | 飞书"群通知"——AICTO 全局群？项目专属新建群？由谁建群？bot 是否有建群权限？ | 能力 0 | **中** |
| Q-9 | 能力 1 输出"飞书文档 URL"——创建到哪个 wiki/space？docx 还是 wiki node？所有者归属？ | 能力 1 | **中** |
| Q-10 | red verdict 反弹给 PM 的协议——异步飞书消息 / 同步阻塞调用 / 响应式回填同一 prd_id？是否阻塞 dispatch_to_legion？ | 能力 1 | **中** |
| Q-11 | "单任务不超过 XL（≥3 天）"——XL 按什么基准（人天 / 工时 / 复杂度点）？现有 L1 军团对 XL 的定义是否一致？ | 能力 2 | **中** |
| Q-12 | EngineerProfile "未来"——Phase 1 是否也需要 suggested_legion 字段？默认值是什么？ | 能力 2 | **低** |
| Q-13 | 全军团均超载（>2 任务）时的派单策略——拒派？排队？降优先级？升级骏飞？ | 能力 3 | **中** |
| Q-14 | "BLOCKING 准确率 ≥90%"和"军团 appeal 率 ≤20%"的分子分母定义？前 10 次复核的具体执行流程？ | 能力 4 | **中** |
| Q-15 | "Dogfood 选哪个 PRD"（PRD 第十节开放问题）——建议 Phase 7 审查待骏飞确认；Phase 1 验收是否依赖此决策？ | 验收 | **低** |

## 三、关键风险（侦察阶段已识别，建议在 ARCHITECTURE.md 中独立成章）

| # | 风险 | 概率 | 影响 | 来源 |
|---|---|---|---|---|
| R-1 | 飞书 API 双 token 体系（tenant_access_token 2h / app_access_token）+ rate limit 未规划缓存刷新策略 | 高 | 高 | dispatch 自识别 + Q-3 |
| R-2 | 4 级错误分类边界模糊导致行为歧义（如同一异常被分到不同级别 → 自动重试 vs 升级骏飞结果不一致） | 中 | 高 | Q-1 |
| R-3 | ADR 表存储选型不当导致 P1 阶段重做（独立 SQLite 隔离更好但 ProdMind 共享 dev.db 数据流更顺） | 中 | 中 | Q-2 |
| R-4 | mailbox/outbox 协议与现有 L1 军团 inbox.jsonl 不兼容导致军团接不到任务 | 中 | 高 | Q-5 |
| R-5 | 18:00 cron 实现机制不当（如用 plugin 内 asyncio loop）→ Hermes 重启即失效 | 中 | 中 | Q-4 |
| R-6 | red verdict / missing_info 阻塞下游的协议未设计 → 能力 1 → 2 流转出现死状态 | 中 | 高 | Q-10 / GAP #5 |
| R-7 | "BLOCKING 准确率 ≥90%"度量缺埋点 → 30 天后无法验收 KR | 中 | 中 | Q-14 |
| R-8 | EngineerProfile 在 Phase 1 完全未实现，能力 2 输出 suggested_legion 字段语义空洞 | 低 | 中 | Q-12 |
| R-9 | 飞书卡片操作按钮（"维持/收回/升级骏飞"等）的回调机制未在 PRD 中给出 | 中 | 中 | GAP #3 / #10 |
| R-10 | 反幻觉 "Dogfood 3 样例零幻觉" 验收方法未定义 → 集成验收阶段判定主观化 | 中 | 中 | GAP #14 |

---

## 侦察结论

- **PRD 字数**：~6,200 字（blocks 渲染） / ~5,400 字（raw_content 纯文本），10 节齐全
- **6 能力齐全**：能力 0~5 在 PRD §五·P0 全部明确给出（描述 / 用户价值 / 关键规则）
- **GAP 数量**：派发漏掉 PRD 细节 **19 项** + 待 PM 澄清 **15 项** + 关键风险 **10 条**
- **建议下一步**：进入架构 spec 阶段时，必须读完 GAP 一节确保不漏 PRD 约束；同时启动 Q-1 ~ Q-5（高紧急度 5 项）反向澄清，在架构 spec 落锤前拿到 PM 答复
