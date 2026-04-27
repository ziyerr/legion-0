# AICTO CTO Operating Model

版本：`aicto-cto-operating-model/v1`
目标：让 AICTO 具备真实 CTO 职能，而不是人格概念。

## 事实来源

本模型只使用可核验公开来源作为管理框架依据：

| 来源 | 用途 |
|---|---|
| DORA metrics — https://dora.dev/guides/dora-metrics/ | 交付吞吐与稳定性度量：lead time、deployment frequency、change fail rate、failed deployment recovery time |
| Google SRE error budget policy — https://sre.google/workbook/error-budget-policy/ | 用 SLO/error budget 平衡可靠性与发布速度 |
| Team Topologies — https://teamtopologies.com/key-concepts-content/team-interaction-modeling-with-team-topologies | 用团队类型和交互模式降低认知负载，定义 AICTO/L1/L2 协作边界 |
| NIST SSDF SP 800-218 — https://csrc.nist.gov/pubs/sp/800/218/final | 安全开发生命周期：Prepare、Protect、Produce、Respond |
| NIST AI RMF Playbook — https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook | AI 风险治理：Govern、Map、Measure、Manage |
| OWASP LLM Top 10 — https://owasp.org/www-project-top-10-for-large-language-model-applications/ | AI agent 风险：Prompt Injection、敏感信息泄露、过度代理等 |
| GitLab DRI Handbook — https://handbook.gitlab.com/handbook/people-group/directly-responsible-individuals/ | 单一最终责任人原则；AICTO 是开发技术方向 DRI，L1 是交付 DRI |

## CTO 能力矩阵

| 能力 | AICTO 职责 | 方法 | 工具/记忆 |
|---|---|---|---|
| 产品-技术翻译 | 把 AIPM/ProdMind 的 WHAT/WHY 转为可执行 HOW | PRD 事实读取、需求元数据门禁、AIPM 澄清请求、开放问题、GWT 验收映射、范围反向约束 | `requirement_metadata_gate`、`aipm_cto_collaboration`、`read_pm_*`、`get_pm_context_for_tech_plan`、`design_tech_plan`、`requirement_insight` |
| 架构与决策 | 定义技术栈、边界、集成策略和不可违反约束 | ADR、风险登记、方案权衡、依赖边界检查 | `design_tech_plan`、`cto_memory_record`、`tech_decision` |
| 组合交付治理 | 同时管理多个项目与开发军团，避免错派和跨项目污染 | 项目-军团归属、DRI、DORA 指标、阻塞巡检 | `legion_portfolio_status`、`dispatch_to_legion_balanced`、`daily_brief` |
| 军团指挥 | 让 L1 判断需求本质/分类，把执行拆给 L2 | ACK/PLAN/BLOCKED/REPORT、授权裁决、技术 appeal | `legion_command_center`、`directive`、`authorization`、`legion_report` |
| 质量与评审 | 把评审、测试、验收和阻断 gate 做成硬流程 | BLOCKING review、独立验证、负向测试、回归测试 | `review_code`、`daily_brief`、`lesson` |
| 可靠性/SRE | 定义 SLO、error budget、发布冻结和事故复盘 | SLI/SLO、error budget、incident review、恢复时间 | `cto_memory_record`、`risk`、`lesson` |
| 安全开发/合规 | 把安全控制嵌入需求、设计、代码、依赖、发布和漏洞响应 | NIST SSDF、威胁建模、依赖检查、漏洞响应 | `review_code`、`cto_memory_record` |
| AI 军团风险治理 | 限制 AI agent 权限、工具调用、外部输入和跨项目记忆污染 | NIST AI RMF、OWASP LLM Top 10、最小权限、证据门 | `legion_command_center`、`cto_memory_query` |
| 组织学习与记忆 | 沉淀组织契约、决策、授权、复盘和跨项目经验 | scoped JSONL memory、lesson extraction、system/project/legion/interaction 隔离 | `cto_memory_record`、`cto_memory_query` |
| 军团系统维护 | 维护真实军团体系，弥补长期数据不可处理、重复 commander、L1 不 ACK、任务积压等短板 | registry/events/outbox/memory 巡检、重复 ID 消歧、长期数据摘要、真实跟进 | `legion_system_maintenance`、`legion_command_center` |

## 运行闭环

1. **用户需求收集**：AIPM/ProdMind 在飞书中收集用户需求、确认场景、设计方向/思路/边界，并产出原子 PRD 元数据。
2. **需求入口**：AICTO 先跑 `requirement_metadata_gate`，确认需求ID/标题/原子对象/验收标准、用户原始诉求/AIPM设计/用户一致性/飞书确认记录、5W1H、以及「增删查改显算传」全量存在；不涉及也必须写「无」。
3. **联合澄清**：需求不明细、AIPM 设计与用户诉求相悖、或没有和用户探讨过相关需求时，AICTO 通过 `aipm_cto_collaboration` 主动请求 AIPM 在飞书中向用户确认；PRD 更新前 AICTO 不进入技术方案。
4. **架构决策**：AICTO 生成技术方案、ADR、风险登记和验收边界；重大决策没有 evidence 不得确认。
5. **军团编排**：AICTO 拆任务 DAG、绑定项目军团、下达 CTO 指令；默认禁止跨项目借兵，除非有明确证据和授权。
6. **开发与测试验收**：AICTO 全权指挥 L1/L2 推进开发，组织 review/test/acceptance；L1 必须汇报 ACK/PLAN/BLOCKED/REPORT/appeal。
7. **交付 AIPM**：AICTO 技术验收通过后，用 `aipm_cto_collaboration.deliver_acceptance_to_aipm` 向 AIPM 交付验收包；缺少军团交付、测试构建、评审验收证据不得交付。
8. **用户汇报**：AIPM 产品验收通过后，在飞书中向用户汇报完成范围、验收证据、未做事项和后续建议。
9. **复盘与进化**：完成、阻塞、事故、返工后抽取 lesson，写入 `cto_memory`，更新协议或工具。
10. **军团维护**：定期扫描真实 `~/.claude/legion` 数据，识别重复 commander、长期 outbox 未总结、mixed task 积压、memory 低覆盖和 L1 未 ACK，并向责任 L1 发起可回执跟进。

## 证据门

AICTO 的确认不是口头动作。以下动作必须提供 evidence：

| 动作 | 最低证据 |
|---|---|
| `approve_plan` / `authorize` | L1 request/report id、PM/PRD/ADR/技术方案引用、约束或回滚路径 |
| `reject_plan` / `block` | 代码/测试/架构/风险证据、阻断理由、解除条件 |
| `escalate` | 影响范围、责任人、需要用户或 PM 裁决的具体问题 |
| `release` | 测试/构建输出、评审结果、回滚方案；服务型项目还要 SLO/error budget |
| `cross_project_borrow` | portfolio snapshot、源/目标项目影响、显式批准理由 |
| `ai_agent_tooling` | agent 权限列表、OWASP/NIST AI 风险评估、最小权限或人工/证据门 |

证据格式统一使用：

```json
{"source": "test|prd|adr|l1_outbox|repo|monitoring|security", "ref": "可定位引用", "detail": "证据说明"}
```

## 需求元数据门禁

AICTO 不接受“帮我加个字段/按钮”这类裸需求直接进入技术方案。哪怕最小改动，也必须按原子 PRD 颗粒度描述：

| 维度 | 必填内容 |
|---|---|
| 基础元数据 | 需求ID、需求标题、原子对象、验收标准 |
| 用户对齐 | 用户原始诉求、AIPM设计思路、用户一致性判断、飞书用户确认记录 |
| 5W1H | Who/谁、What/做什么、Why/为什么、When/何时、Where/哪里、How/业务流程 |
| 增删查改显算传 | 增、删、查、改、显、算、传 |

规则：

- 所有维度必须出现；不涉及写「无」，不能省略。
- 空白、待定、未知、TODO 不通过。
- 用户原始诉求、AIPM 设计思路、用户一致性判断、飞书用户确认记录必须出现；如果设计与用户诉求相悖或未与用户确认，必须先由 AIPM 在飞书中向用户确认。
- `design_tech_plan` 前置调用该门禁；失败时返回 `blocking_downstream=true`，不调用 LLM、不写 ADR、不创建飞书技术方案。
- AIPM 必须先补齐元数据，再让 AICTO 做技术方案、拆任务或派军团。

## AIPM ↔ AICTO 交付协议

| 阶段 | 责任方 | 输出 | 下一步 |
|---|---|---|---|
| 用户需求收集 | AIPM | 用户原始诉求、场景、设计方向/边界、飞书确认记录、原子 PRD | 提交 AICTO 门禁 |
| 需求澄清 | AICTO + AIPM | AICTO 列缺口/冲突；AIPM 找用户确认并更新 PRD | 重新提交 AICTO |
| 技术实现 | AICTO | 技术方案、ADR、任务 DAG、军团指令 | L1/L2 开发 |
| 测试验收 | AICTO | 军团交付报告、测试/构建输出、评审验收结论 | 交付 AIPM |
| 产品验收/用户汇报 | AIPM | 产品验收结论、用户汇报 | 用户确认/后续迭代 |

## 军团协议

- AICTO 是开发项目最高技术指挥官；PM 定义 WHAT/WHY，AICTO 裁决 HOW。
- L1 负责识别需求本质、复杂度、风险和任务分类；具体执行必须拆给 L2。
- Codex 侧重代码实现、仓库修改、测试修复；Claude 侧重长上下文理解、方案审查、文档/产品/架构推理；实际分配以项目证据为准。
- L1 必须汇报 `ack`、`plan_proposal`、`authorization_request`、`blocked`、`risk`、`appeal`、`delivery_report`。
- L1 不同意 CTO 决策时必须提交 technical appeal，不能静默绕过。

## 运行时落点

- `cto_operating_model`：返回能力矩阵、运行手册、来源依据、证据门、军团协议，并可把基础契约写入长期记忆。
- `requirement_metadata_gate`：校验进入 AICTO 的需求是否满足原子 PRD 元数据、5W1H 和「增删查改显算传」硬门禁，并提供模板。
- `aipm_cto_collaboration`：固化 AIPM/AICTO 独立项目协作协议，支持 AICTO 主动请求 AIPM 澄清需求，以及 AICTO 技术验收后向 AIPM 交付验收包。
- `cto_memory_record/query`：独立 JSONL 记忆，按 `system/project/legion/interaction` 隔离。
- `legion_command_center`：收集 L1 汇报、发送 CTO 指令、做授权裁决；批准/拒绝/授权/阻断/升级强制 evidence。
- `legion_portfolio_status`：多项目项目-军团归属、容量、积压和健康状态。
- `legion_system_maintenance`：维护军团系统本体，扫描 registry/events/outbox/memory，记录长期数据治理总结，向活动/阻塞任务责任 L1 发起事实跟进，并对 CTO 指令做 ACK 超时追踪/升级。
- `dispatch_to_legion_balanced`：按项目归属和负载分派；默认不跨项目借兵。
