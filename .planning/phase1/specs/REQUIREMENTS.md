# Phase 1 — REQUIREMENTS（需求清单）

> 本文档是 Phase 1 实施的真相源。每条需求带稳定 ID + PRD 出处 + 验收依据。
> 子文档 `PRD-CAPABILITIES.md` 已逐字段抽取 6 能力规格；本文档是**扁平化清单**，便于 ADR / 实现 / 验收回链。
> 任何争议以本文档为准；本文档变动需更新 STATE.md 并发 ADR。

## 0. 总览

| 类别 | 数量 |
|------|------|
| 功能需求 R-FN | 6 能力（含 19 个派发漏掉的 PRD 子项）|
| 数据需求 R-DT | 5 张 CTO 自有表 + 14+5 张 PM 只读表访问 |
| 工具需求 R-TL | 6 + 8 PM 只读 + 2 综合 = 16 个工具 |
| 非功能需求 R-NFR | 反幻觉 / 生产隔离 / SLA / 度量 / 错误处理 / 飞书集成 |
| KR 度量需求 R-KR | 4 项（KR1 / KR2 / KR3 / KR4）|
| 风险登记 R-RK | 10 条 |
| 开放问题 R-OPEN | 10 项（5 🔴 + 5 🟡，已通过 dispatch 反问）|

## 1. 功能需求（R-FN）

### 1.1 能力 0：kickoff_project — 项目启动自动化

| ID | 需求 | 出处 | 验收依据 |
|----|------|------|---------|
| R-FN-0.1 | 触发：PM 调用 `create_project` 或飞书 @程小远 "启动项目 X" | PRD §五·能力 0 | 双触发可达成 |
| R-FN-0.2 | 8 步串联：创建项目目录 → git init → ProdMind Project 条目 → ADR-0001 → 拉军团 → 建通讯（mailbox）→ 派首批任务 → 飞书群通知 | PRD §五·能力 0 | 8 步全部成功才算完成 |
| R-FN-0.3 | 输出 5 字段 JSON：project_id / git_path / legion_commander_id / adr_id / initial_tasks | PRD §五·能力 0 | JSON schema 校验 |
| R-FN-0.4 | 飞书启动卡片 5 字段 + 3 操作按钮：项目名 / Path / Legion / ADR / 状态文案 + [查看 ADR][加入军团群][暂停项目] | PRD §五·能力 0 ASCII mock | 卡片实测点击可触发 |
| R-FN-0.5 | 4 级错误分类：技术→自主重试 / 权限→升级骏飞 / 意图→给选项 / 未知→保守升级 | PRD §五·能力 0 | 各级测试用例覆盖 |
| R-FN-0.6 | SLA：≤30 秒完成 8 步 | 推断 / 验收标准 | 集成测试计时 |

### 1.2 能力 1：design_tech_plan — 技术方案设计

| ID | 需求 | 出处 | 验收依据 |
|----|------|------|---------|
| R-FN-1.1 | 输入：prd_id（dev.db 主键）/ prd_markdown（直接传文本）/ prd_doc_token（飞书 docx URL）三选一 + focus（可选）+ constraints（可选）| PRD §五·能力 1 + R-OPEN-4 | 三选一同时支持 |
| R-FN-1.2 | 输出 6 字段 JSON：feasibility（green/yellow/red）+ tech_stack + estimate{optimistic, likely, pessimistic} + risks + missing_info + feishu_doc_url | PRD §五·能力 1 | JSON schema 校验 |
| R-FN-1.3 | **red verdict 必须告诉 PM 改什么才能变绿**（不能只说"不可行"）| PRD §五·能力 1 | red 测试用例必含改进路径字段 |
| R-FN-1.4 | **missing_info 反向推回 PM 阻塞下游**（breakdown_tasks 不能基于 red/missing PRD 触发）| PRD §五·能力 1 | 阻塞协议测试 |
| R-FN-1.5 | **每个技术选型决策自动写入 ADR 表**（无须 PM 显式调 record_tech_decision）| PRD §五·能力 1 | tech_stack 每项 ↔ ADR 至少一条 |
| R-FN-1.6 | 输出飞书技术方案文档（含 mermaid 图、API contract、data model）| PRD §五·能力 1 + RECON 8.4 | 飞书 doc URL 可访问 |
| R-FN-1.7 | KR4 SLA：≤5 分钟完成 PRD → 技术方案 | PRD §九 KR4 | 计时测试（基线骏飞 1-2h）|
| R-FN-1.8 | 内部推理链：Read PRD → Extract → ADR history → EngineerProfile → feasibility matrix → tech stack candidates → score → write ADR → render 飞书 doc | RECON HISTORY 8.4 / PRD 隐含 | 实现路径合理性 |

### 1.3 能力 2：breakdown_tasks — 任务拆分

| ID | 需求 | 出处 | 验收依据 |
|----|------|------|---------|
| R-FN-2.1 | 输入：tech_plan_id 或完整 tech_plan 对象（来自能力 1 输出）| PRD §五·能力 2 | input schema |
| R-FN-2.2 | 输出：tasks[] + dependency_graph（强制 DAG，禁环）+ 每任务 Given/When/Then 验收标准 | PRD §五·能力 2 | 拓扑排序成功 + GWT 三段齐全 |
| R-FN-2.3 | 单任务规模上限：≤ XL（≥3 天必须再拆）| PRD §五·能力 2 | size 字段 ∈ {S, M, L, XL} |
| R-FN-2.4 | feasibility=red 或 missing_info 未清的 PRD 不能进入拆分（拒绝触发）| PRD §五·能力 1 隐含 | 阻塞测试 |
| R-FN-2.5 | task 字段建议：title / description / size / acceptance_gwt / depends_on / suggested_legion（按 EngineerProfile）| PRD §五·能力 2 + RECON | 字段齐全度 |
| R-FN-2.6 | EngineerProfile 来源：Phase 1 用 hardcoded（待 R-OPEN-6 仲裁）| RECON 6.5 + R-OPEN-6 | 默认 hardcoded 可工作 |

### 1.4 能力 3：dispatch_to_legion_balanced — 智能调度

| ID | 需求 | 出处 | 验收依据 |
|----|------|------|---------|
| R-FN-3.1 | 输入：tasks[] + legion_pool（自动 discover_online_commanders）| PRD §五·能力 3 + RECON 6.1 | 自动发现军团 |
| R-FN-3.2 | 输出：assignments[{task_id, legion_id, payload}] + deferred[task_id]（依赖未就绪）| PRD §五·能力 3 隐含 | 输出结构 |
| R-FN-3.3 | 单军团并发上限：≤2 个未完成任务（派前查 + 排队）| PRD §五·能力 3 | 派后 count ≤ 2 |
| R-FN-3.4 | DAG 依赖未就绪的任务延迟派单（拓扑排序）| PRD §五·能力 3 | 测试含依赖任务 |
| R-FN-3.5 | 派单 payload 必含三段：PRD 摘要 + 技术方案 + 验收标准（GWT）| PRD §五·能力 3 | payload 字段校验 |
| R-FN-3.6 | **CTO 拥有调度决策权，军团必须接（可 appeal 但不可直接拒）** | PRD §五·能力 3 | 军团接单成功率 100% |
| R-FN-3.7 | 双通道复用 ProdMind 实现：tmux send-keys 直发（在线+空闲）+ inbox.json 排队（在线+忙 OR 离线）| RECON 6.2 | 两通道可达 |
| R-FN-3.8 | 派 inbox 的同时 tmux send-keys 一行通知（避免军团埋头不读 inbox）| RECON 6.4 | 通知行实测 |
| R-FN-3.9 | mailbox 协议向后兼容现有 inbox.jsonl schema（CTO 加 cto_context / appeal_id 字段，不破坏现有字段）| RECON 9.11 + R-OPEN-5 | 现有军团 commander 接单不报错 |

### 1.5 能力 4：review_code — 代码审查

| ID | 需求 | 出处 | 验收依据 |
|----|------|------|---------|
| R-FN-4.1 | 输入：pr_url（GitHub PR 链接）+ 可选 tech_plan_id（用于"架构一致"维度）| PRD §五·能力 4 推断 | input schema |
| R-FN-4.2 | 10 项审查清单（逐字保留）：架构一致 / 可读性 / 安全 / 测试 / 错误处理 / 复杂度 / 依赖 / 性能 / 跨军团冲突 / PRD 一致 | PRD §五·能力 4 | 10 项 status 全有 |
| R-FN-4.3 | 每项 status：PASS / BLOCKING / NON-BLOCKING | PRD §五·能力 4 | 三态枚举 |
| R-FN-4.4 | **BLOCKING 硬 gate**：真阻塞 merge，军团必须停 + 修 + 重 PR | PRD §五·能力 4 | 集成验收测试 |
| R-FN-4.5 | **BLOCKING 文案约束**："把 X 改成 Y 因为 Z"格式（不允许"这里不好"）| PRD §五·能力 4 | 文案模板 lint |
| R-FN-4.6 | **军团忽略 BLOCKING = 执行纪律违规，自动升级骏飞** | PRD §五·能力 4 | 升级路径测试 |
| R-FN-4.7 | 评论密度限制：单 PR ≤ 5 评论 + 单文件 ≤ 2 BLOCKING | PRD §五·能力 4 | count 校验 |
| R-FN-4.8 | Appeal 通道：军团 → CTO 提 appeal → CTO 维持/收回 → 维持时升级骏飞仲裁 | PRD §五·能力 4 + R-OPEN-3 | 三态完整流转 |
| R-FN-4.9 | Appeal 飞书卡片 4 字段 + 3 操作按钮：PR 编号 / 标题 / BLOCKING 内容 / 军团理由 + [维持][收回][升级骏飞]| PRD §五·能力 4 ASCII mock | 卡片实测 |
| R-FN-4.10 | Appeal 升级阈值默认 1 次（待 R-OPEN-2 仲裁）| HANDOFF-TO-PM.md + R-OPEN-2 | 阈值可配置 |
| R-FN-4.11 | KR：BLOCKING 准确率 ≥ 90%（前 10 次骏飞强制复核）| PRD §九 | 度量埋点 |
| R-FN-4.12 | KR：军团 appeal 率 ≤ 20% | PRD §九 | 度量埋点 |

### 1.6 能力 5：daily_brief + escalate — 进度汇报

| ID | 需求 | 出处 | 验收依据 |
|----|------|------|---------|
| R-FN-5.1 | 三触发：每日 18:00 cron / BLOCKING 即时推送 / 军团 >24h 无进展自动催促 | PRD §五·能力 5 | 三类触发实测 |
| R-FN-5.2 | 18:00 cron 时区：UTC+8（默认，待 R-OPEN-7 确认）| R-OPEN-7 | 时区可配置 |
| R-FN-5.3 | 18:00 cron 补发策略：错过则下一日 09:00 补发摘要（默认，待 R-OPEN-7 确认）| R-OPEN-7 | 补发实测 |
| R-FN-5.4 | 输出格式："骏飞 30 秒掌握全部进度" — 高度概括飞书群消息，非长报告 | PRD §五·能力 5 | 消息长度限制 |
| R-FN-5.5 | 18:00 brief 维度：每项目状态（已完成/进行中/BLOCKED/风险）| PRD §五·能力 5 推断 | 维度齐全 |
| R-FN-5.6 | BLOCKING 推送字段：PR 链接 + BLOCKING 摘要 + @对应 commander | PRD §五·能力 5 | 字段齐全 |
| R-FN-5.7 | 24h 催促：飞书 @军团 commander + 任务 ID + 已停滞时长 | PRD §五·能力 5 | 催促消息 |
| R-FN-5.8 | 24h 判定来源：CommanderOutbox 表的 mtime 或最后状态变更 | RECON 7.1 推断 | 数据源一致 |
| R-FN-5.9 | 催促失败（再 24h 仍无进展）→ 升级路径：飞书 @骏飞 + 升级日志 | 推断 / R-OPEN-7 | 二次升级测试 |

## 2. 数据需求（R-DT）

### 2.1 CTO 自有表（5 张，写权限）

| ID | 表 | 字段（推荐）| 出处 |
|----|-----|------------|------|
| R-DT-1 | ADR | id / project_id / number / title / decision / rationale / alternatives_considered_json / decided_by / decided_at / superseded_by | PRODUCT-SPEC-v0.2 §6.1 |
| R-DT-2 | TechRisk | id / project_id / severity{high,med,low} / probability / impact / mitigation / earlyWarningSignal / status / created_at | PRODUCT-SPEC-v0.2 §6.2 |
| R-DT-3 | TechDebt | id / project_id / type / description / introduced_in_commit / paydown_estimate / priority / status | PRODUCT-SPEC-v0.2 §6.3 |
| R-DT-4 | CodeReview | id / project_id / pr_url / commit_sha / checklist_json / blocker_count / suggestion_count / appeal_status / reviewed_at / reviewer | PRODUCT-SPEC-v0.2 §6.4 |
| R-DT-5 | EngineerProfile | id / commander_id / skills_json / strengths / weaknesses / past_tasks_count / dispatch_recommendation | PRODUCT-SPEC-v0.2 §6.5（Phase 1 hardcoded 优先）|

### 2.2 ADR 存储位置（待 R-OPEN-1 仲裁）

- **默认（v0.2 §11.3 历史立场）**：5 张表写入 ProdMind dev.db（共享）
- **物理边界**：CTO 用 `_cto_own_connect()` 无 mode=ro 写自有表；用 `_readonly_connect()` mode=ro 读 PM 表
- **如 PM 派发 §五·风险 #2 推翻**：改为独立 SQLite（路径 `~/.hermes/profiles/aicto/aicto.db`），数据迁移路径需另写 ADR

### 2.3 PM 表只读访问（14+5 张）

| ID | 表 | CTO 用途 |
|----|-----|---------|
| R-DT-6 | Project | 读 mode / authorization_scope / stage |
| R-DT-7 | PRD | 读 content / version / feishuDocToken |
| R-DT-8 | PRDVersion | 读历史版本 + diff |
| R-DT-9 | PRDDecision | 读历史决策 + decidedBy |
| R-DT-10 | PRDOpenQuestion | CTO 评估时重点看 |
| R-DT-11 | UserStory | 读 acceptanceCriteria / asA / iWant / soThat |
| R-DT-12 | Feature | 读 rice score |
| R-DT-13 | Research | 读市场调研 |
| R-DT-14 | Evaluation | 读三层评估 |
| R-DT-15 | Activity | 读项目活动流 |
| R-DT-16 | Task | 读 + CTO 加 review_result 字段 |
| R-DT-17 | TeamMember | 读军团成员 |
| R-DT-18 | ProjectRepo | 读 repoUrl / localPath / legionHash |
| R-DT-19 | CommanderOutbox | 读派单状态（24h 催促判定用）|
| R-DT-20 | ProjectDocument | 读飞书 doc 索引 |

## 3. 工具需求（R-TL）

### 3.1 6 能力工具（顶层）

| ID | 工具名 | 能力 |
|----|--------|------|
| R-TL-1 | kickoff_project | 0 |
| R-TL-2 | design_tech_plan | 1 |
| R-TL-3 | breakdown_tasks | 2 |
| R-TL-4 | dispatch_to_legion_balanced | 3 |
| R-TL-5 | review_code | 4 |
| R-TL-6 | daily_brief | 5 |

### 3.2 PM 只读工具（8 个，复用 CTO-READ-ACCESS-SPEC §三）

| ID | 工具名 | 用途 |
|----|--------|------|
| R-TL-7 | read_pm_project | 读 Project |
| R-TL-8 | read_pm_prd | 读 PRD（含 PRDVersion）|
| R-TL-9 | list_pm_prd_decisions | 列 PRDDecision |
| R-TL-10 | list_pm_open_questions | 列 PRDOpenQuestion |
| R-TL-11 | list_pm_user_stories | 列 UserStory |
| R-TL-12 | list_pm_features | 列 Feature（含 RICE）|
| R-TL-13 | read_pm_research_doc | 读 Research |
| R-TL-14 | read_pm_evaluation_doc | 读 Evaluation |

### 3.3 综合工具（2 个）

| ID | 工具名 | 用途 |
|----|--------|------|
| R-TL-15 | get_pm_context_for_tech_plan | design_tech_plan 一键拉取所需 PM 上下文（PRD + UserStories + Features + Decisions + OpenQuestions）|
| R-TL-16 | diff_pm_prd_versions | 对比 PRD 两个版本 diff（review_code 检查 PRD 一致维度用）|

### 3.4 内部辅助工具（保留为非顶层）

| ID | 工具名 | 用途 |
|----|--------|------|
| R-TL-17 | record_tech_decision | 内部辅助：写 ADR 表（被 design_tech_plan 自动调用）|
| R-TL-18 | escalate（命名待定）| 内部辅助：升级骏飞通道（被 review_code / daily_brief 调用）|

## 4. 非功能需求（R-NFR）

### 4.1 反幻觉（5 条 — 来自 v0.1 hook + PRD §三）

| ID | 需求 | 出处 |
|----|------|------|
| R-NFR-1 | 不得声称未做的事（不说"评审完成""文档已创建"，除非工具调用成功）| 现有 hook |
| R-NFR-2 | 识别飞书引用回复（聚焦最后一段新提问）| 现有 hook |
| R-NFR-3 | 承认缺失不编造（找不到记忆直接说没记录）| 现有 hook |
| R-NFR-4 | 技术决策要有根据（基于实际代码/文档/数据，没数据说"我需要先看 X"）| 现有 hook |
| R-NFR-5 | stub 工具透明（返回 `{"status": "not_implemented"}`，不包装成 success）| 现有 hook |
| R-NFR-6 | 5 条纪律迁入 SOUL.md（PRD §三明确"反幻觉纪律：SOUL.md 嵌入"）| PRD §三 |

### 4.2 生产隔离（PM 派发 §三 + RECON 9）

| ID | 需求 | 出处 |
|----|------|------|
| R-NFR-7 | 独立 Hermes profile `aicto`，端口 8644，独立 state.db / sessions / plugins / 飞书 app | PRD §三 |
| R-NFR-8 | AICTO 启停 / 崩溃 / 升级**零影响** default profile（PM）和 ai-hr | PRD §三 + CLAUDE.md |
| R-NFR-9 | 飞书 app 独立 `cli_a9495f70ddb85cc5`（避开 app_lock 冲突）| PRD §一 + RECON 9.1 |
| R-NFR-10 | plugin 加载 per-profile 隔离：放 `~/.hermes/profiles/aicto/plugins/aicto`（symlink → `~/Documents/AICTO/hermes-plugin`）| RECON 9.2 |

### 4.3 SLA / 性能

| ID | 需求 | 出处 |
|----|------|------|
| R-NFR-11 | design_tech_plan ≤ 5 分钟（KR4）| PRD §九 KR4 |
| R-NFR-12 | kickoff_project ≤ 30 秒 | 推断 |
| R-NFR-13 | review_code ≤ 2 分钟（推断，PR 平均 ≤500 LOC）| 推断 |
| R-NFR-14 | daily_brief 18:00 触发延迟 ≤ 1 分钟 | 推断 |

### 4.4 飞书集成（来自 RECON 2）

| ID | 需求 | 出处 |
|----|------|------|
| R-NFR-15 | 飞书 token 缓存策略：进程内 + 5 分钟提前刷新（复用 ProdMind 实现）| RECON 2.1 + R-OPEN-（已自决）|
| R-NFR-16 | 飞书消息 ws_reconnect_interval 默认 120s（使用 Hermes 默认）| RECON 10.L |
| R-NFR-17 | 飞书文档读取使用 `/blocks` 端点（保留结构）而非 `/raw_content` | RECON 2.3 |
| R-NFR-18 | 飞书文档创建后自动 `_grant_doc_tenant_read()`（让 PM 同 tenant 可读）| RECON 2.0 / 9.9 |

### 4.5 错误处理 / 4 级分类（待 R-OPEN-2 PM 仲裁，下方为默认）

| ID | 错误级别 | 触发条件（默认） | 处理动作 |
|----|---------|----------------|---------|
| R-NFR-19 | 技术 | 网络超时 / API 5xx / LLM API 暂时拒答 / SQL constraint 违反非业务 | 自动重试 3 次（指数退避 1s/2s/4s），仍失败转未知 |
| R-NFR-20 | 权限 | 飞书 401/403 / git push 拒绝 / dev.db `attempt to write a readonly database` / SQL 权限错 | 立即升级骏飞（飞书 @张骏飞）|
| R-NFR-21 | 意图 | 输入校验失败 / 参数歧义 / PRD missing_info 太多无法 feasibility 判断 | 给 2-3 个候选选项让 PM 选 |
| R-NFR-22 | 未知 | 上面三类都不命中 / 异常 stack trace 中含未识别关键词 | 保守升级（飞书 @张骏飞 + 完整 stack）|
| R-NFR-23 | 4 级分类适用范围：全 6 能力共享（默认，待 R-OPEN-2 仲裁）| | |

### 4.6 度量埋点

| ID | 需求 | 出处 |
|----|------|------|
| R-NFR-24 | KR1（≤5 次/周）需埋点（指标含义待 R-OPEN-9 确认）| PRD §九 KR1 |
| R-NFR-25 | KR2（100% PRD 有方案）：每个 PRD 触发 design_tech_plan 计数 | PRD §九 KR2 |
| R-NFR-26 | KR3（≤15%）需埋点（指标含义待 R-OPEN-9 确认）| PRD §九 KR3 |
| R-NFR-27 | KR4（≤5 分钟）：design_tech_plan 调用计时埋点 | PRD §九 KR4 |
| R-NFR-28 | BLOCKING 准确率 ≥ 90%：CodeReview 表加 `senior_review_verdict` 字段（前 10 次骏飞强制复核）| PRD §九 |
| R-NFR-29 | 军团 appeal 率 ≤ 20%：CodeReview.appeal_status 计数 | PRD §九 |

### 4.7 路径白名单（来自 CTO-READ-ACCESS-SPEC §二·C）

| ID | 需求 | 出处 |
|----|------|------|
| R-NFR-30 | 本地文件读取仅允许 `~/Documents/prodmind/.planning/` 目录（防止 design_tech_plan 误读其他项目）| CTO-READ-ACCESS-SPEC §二·C |
| R-NFR-31 | 读权限审计日志写入 `~/.hermes/profiles/aicto/logs/read-audit.log` | CTO-READ-ACCESS-SPEC §七 |

## 5. KR 度量需求（R-KR）

| KR | 数值 | 含义 | 度量方式 |
|----|------|------|---------|
| KR1 | ≤5 次/周 | （待 R-OPEN-9 确认）| 待定 |
| KR2 | 100% | PRD 有对应技术方案 | (有 design_tech_plan 输出的 PRD 数 / 总 PRD 数) × 100% |
| KR3 | ≤15% | （待 R-OPEN-9 确认）| 待定 |
| KR4 | ≤5 分钟 | PRD → 技术方案时间 | design_tech_plan 调用耗时（基线骏飞 1-2h）|

## 6. 风险登记（R-RK）

源自 PRD-CAPABILITIES R-1 ~ R-10：

| ID | 风险 | 概率 | 影响 | 缓解（默认）|
|----|------|------|------|-----------|
| R-RK-1 | 飞书 API token 过期/限流 | 高 | 高 | 复用 ProdMind 5 分钟提前刷新 + 失败抛 FeishuError 上抛 |
| R-RK-2 | 4 级错误分类边界模糊导致行为歧义 | 中 | 高 | spec 阶段写明判定规则（R-NFR-19~22）+ 待 PM 仲裁 |
| R-RK-3 | ADR 表存储选型不当 → P1 阶段重做 | 中 | 中 | 默认共享 dev.db（v0.2 历史立场）+ 已反问 PM |
| R-RK-4 | mailbox/outbox 协议与 inbox.jsonl 不兼容 | 中 | 高 | 直接复用 inbox.jsonl schema + 加新字段（向后兼容）|
| R-RK-5 | 18:00 cron 实现机制不当 → 重启失效 | 中 | 中 | plugin 自管 + last_run_ts 持久化到文件 |
| R-RK-6 | red verdict / missing_info 阻塞协议未设计 | 中 | 高 | spec 阶段定义阻塞状态机（design_tech_plan 输出阻塞标记 → breakdown_tasks 检查后拒绝）|
| R-RK-7 | BLOCKING 准确率 ≥ 90% 度量缺埋点 | 中 | 中 | CodeReview 表加 senior_review_verdict 字段 |
| R-RK-8 | EngineerProfile Phase 1 未实现 → 派单语义空洞 | 低 | 中 | hardcoded dict 兜底 + Phase 2 落表 |
| R-RK-9 | 飞书卡片操作按钮回调机制未在 PRD 给出 | 中 | 中 | 复用 ProdMind 卡片回调路径（飞书 webhook + value 字段 JSON）|
| R-RK-10 | "Dogfood 3 样例零幻觉"验收方法未定义 | 中 | 中 | spec 阶段定义"零幻觉"判定规则 + 集成验收用例 |

## 7. 开放问题（R-OPEN）

已通过 dispatch 文件 `## 反向问题` 段落反问 PM。所有 🔴 默认推进路径已写明，如 PM 推翻则按 ADR 修订。

| ID | 问题 | 优先级 | 默认推进 | 影响范围 |
|----|------|-------|---------|---------|
| R-OPEN-1 | ADR 表存储位置 | 🔴 | 共享 prodmind dev.db（v0.2 §11.3 立场）| 全 P1 数据层 |
| R-OPEN-2 | 4 级错误分类判定边界 + 是否全 6 能力共享 | 🔴 | R-NFR-19~22 默认 + 全 6 能力共享 | 错误处理实现 |
| R-OPEN-3 | BLOCKING appeal 升级阈值 | 🔴 | 1 次（HANDOFF-TO-PM 立场）| review_code 实现 |
| R-OPEN-4 | PRD 数据源（飞书 docx vs dev.db vs 双源）| 🔴 | 三选一同时支持 + dev.db 主链路 | design_tech_plan input |
| R-OPEN-5 | 飞书 token 缓存刷新（已自决）| 🔴→自决 | 复用 ProdMind 5min 提前刷新 | feishu_api.py |
| R-OPEN-6 | EngineerProfile Phase 1 是否落地 | 🟡 | hardcoded dict + Phase 2 落表 | breakdown_tasks / dispatch_to_legion_balanced |
| R-OPEN-7 | 18:00 cron 时区 + 补发策略 | 🟡 | UTC+8 + 错过则下一日 09:00 补发 | daily_brief |
| R-OPEN-8 | kickoff_project 第 3 步 ProdMind 项目条目协议 | 🟡 | HTTP 调 ProdMind 8642 端口 | kickoff_project |
| R-OPEN-9 | 飞书项目群通知目标 chat_id | 🟡 | AICTO 工作群（待 PM 提供 chat_id）| kickoff_project / daily_brief |
| R-OPEN-10 | BLOCKING 准确率 / appeal 率分子分母定义 | 🟡 | (维持的 BLOCKING / 总 BLOCKING) × 100% / (appeal 数 / BLOCKING 总数) × 100% | 度量埋点 |
| R-OPEN-11 | KR1 / KR3 指标含义 | 🟡 | 待 PM 答复 | 度量埋点 |
| R-OPEN-12 | mailbox 协议规格（已自决：复用现有 inbox.jsonl + 加新字段）| 🟡→自决 | 向后兼容 | dispatch_to_legion_balanced |

## 8. 与 ARCHITECTURE.md 的边界

本文档回答**"做什么"**，不回答**"怎么做"**。

- 模块拆分、文件组织、技术选型、协议细节 → ARCHITECTURE.md
- 实施顺序、依赖关系、团队编制 → PHASE-PLAN.md
- 关键决策的来龙去脉 → ADR-001 ~ ADR-00N

## 9. 实施验收 checklist（Phase 1 全量上线门槛）

源自 PM 派发 §四 验收标准 + 历史 v0.2 §九 质量门槛：

- [ ] 能力 0：PM 飞书说"启动项目 X" → 8 步全成 → 飞书群收到启动卡片（5 字段 + 3 按钮）
- [ ] 能力 1：给 PRD → 输出 6 字段 JSON + ≤5 分钟 SLA + 飞书 doc URL 可访问 + ADR 至少 1 条
- [ ] 能力 2：给 tech_plan → 输出 tasks DAG（无环 + 全 GWT 验收 + 全 size ≤ XL）
- [ ] 能力 3：给 tasks → 派单到 ≥2 军团 + 单军团 ≤2 + payload 三段齐全 + 双通道可达
- [ ] 能力 4：给 PR → 10 项 status + BLOCKING 文案规整 + appeal 卡片可触发 + 升级路径
- [ ] 能力 5：18:00 自动 brief + BLOCKING 即时推送 + 24h 催促
- [ ] **结构化 JSON**：所有工具输出符合 schema，无自由文本
- [ ] **零幻觉**：Dogfood 3 样例（待选）无虚构事实（来自 PRD §六）
- [ ] **生产零影响**：PM(default) / AIHR 启停崩溃测试 → AICTO 不受影响、AICTO 崩溃不影响其他
- [ ] **真实派单 ack**：dispatch 后 ≥1 个军团 commander 收到并 ack
- [ ] **ADR 覆盖率 ≥ 90%**：每个技术选型决策都有 ADR 条目

---

**REQUIREMENTS 完。**

下一步：ARCHITECTURE.md（架构决策落锤）+ PHASE-PLAN.md（实施编排）+ ADR-001~00N（决策日志）+ features.json（功能追踪）。
