# 📋 开发任务派发 — AI CTO 程小远 Phase 1 全量

**派发方**: ProdMind（张小飞）
**接收方**: L1-麒麟军团
**派发时间**: 2026-04-25
**优先级**: P0
**PRD 文档**: https://ucnrf25nllyh.feishu.cn/docx/ZeMedrjG1ogqhnxsxZuc5dF0nfe

---

## 一、项目背景

程小远是云智 OPC 团队的 AI 技术总监（CTO Agent）。

**核心问题**：当前 PM Agent 通过 dispatch_to_legion 直接给军团派活，跳过技术评审。军团收到的任务缺乏技术审查、架构设计和质量把关，返工成本约占 30-50%。

**实现基础**：基于 Hermes 实例 + 飞书身份，与张小飞（PM Agent）同架构。通过 Hermes Agent 间通信协议与军团交互。

**飞书应用凭证**：App ID = cli_a9495f70ddb85cc5, App Secret = UH0SFH3erBluBRe3EfYZEdyWVgbAXZp3

---

## 二、Phase 1 — 6 个核心能力

### 能力 0：项目启动自动化（kickoff_project）

PM 发起新项目后，程小远自动完成 8 步：
1. 创建项目目录
2. git init
3. ProdMind 项目条目
4. ADR-0001（首条架构决策记录）
5. 拉军团
6. 建通讯（mailbox/outbox）
7. 派首批任务
8. 飞书群通知

**触发**：PM 调用 create_project 或飞书 @程小远 说"启动项目 X"
**输出**：结构化 JSON（project_id / git_path / legion_commander_id / adr_id / initial_tasks）+ 飞书卡片通知
**失败处理**：4 级错误分类（技术→自主重试 / 权限→升级骏飞 / 意图→给选项 / 未知→保守升级）

### 能力 1：技术方案设计（design_tech_plan）

读 PRD → 评估可行性 → 选技术栈 → 设计架构 → 识别风险 → 输出飞书文档。

**输入**：prd_id 或 prd_markdown + 可选 focus/constraints
**输出**：feasibility（green/yellow/red）+ 技术栈选型 + 时间估计（乐观/可能/悲观）+ 风险清单 + 缺失信息 + 飞书文档 URL
**关键规则**：
- red verdict 必须告诉 PM 改什么才能变绿
- missing_info 反向推回 PM 澄清
- 每个技术选型决策自动写入 ADR 表

### 能力 2：任务拆分（breakdown_tasks）

技术方案 → 结构化任务列表 + 依赖 DAG + 验收标准。

**关键规则**：
- 单任务不超过 XL（≥3 天必须再拆）
- 依赖关系强制 DAG（不允许环）
- 每个任务的验收标准必须 Given/When/Then

### 能力 3：军团调度（dispatch_to_legion_balanced）

根据任务技术栈 × 军团能力 × 军团当前负荷，智能分配任务。

**关键规则**：
- 单军团同时 ≤2 个任务
- 有依赖关系的任务延迟派单
- 派单时附完整上下文（PRD 摘要 + 技术方案 + 验收标准）
- CTO 拥有调度决策权，军团必须接（可 appeal 但不可直接拒）

### 能力 4：代码审查（review_code）

10 项审查清单，每项 PASS / BLOCKING / NON-BLOCKING，硬 gate 阻塞 merge。

**10 项清单**：
1. 架构一致（是否符合技术方案）
2. 可读性（命名规范、代码清晰）
3. 安全（有无安全漏洞）
4. 测试（关键路径有覆盖）
5. 错误处理（边界情况处理）
6. 复杂度（有无不必要复杂性）
7. 依赖（第三方依赖合理）
8. 性能（性能可接受）
9. 跨军团冲突（与其他军团代码冲突）
10. PRD 一致（满足验收标准）

**BLOCKING 硬 gate 规则**（骏飞 2026-04-23 拍板）：
- BLOCKING = 真阻塞 merge，军团必须停 + 修 + 重 PR
- BLOCKING 必须附明确修复要求（"把 X 改成 Y 因为 Z"）
- 军团忽略 BLOCKING = 执行纪律违规，自动升级骏飞
- 评论密度限制：单 PR 最多 5 个评论，单文件最多 2 个 BLOCKING

**Appeal 通道**：军团觉得 BLOCKING 不合理 → 提 appeal → 程小远收回或维持并升级骏飞仲裁

### 能力 5：进度汇报（daily_brief + escalate）

每日 18:00 技术进度摘要 + BLOCKING 即时推送 + 军团 >24h 无进展自动催促。

---

## 三、技术约束

- **独立 Hermes 实例**：端口 8644（不占 PM 8642 / AIHR 8643）
- **独立 state.db / sessions / plugins**
- **反幻觉纪律**：SOUL.md 嵌入反幻觉规则；所有工具输出结构化 JSON
- **宕机不影响 PM / AIHR / 军团运行**

---

## 四、验收标准

1. **能力 0**：PM 说"启动项目 X" → 程小远自动完成 8 步 → 飞书群收到启动通知卡片
2. **能力 1**：给程小远一个 PRD → 输出 feasibility 判断 + 技术栈选型 + 风险清单 + 飞书文档
3. **能力 2**：给技术方案 → 输出结构化任务列表 + 依赖 DAG + 每个任务有 Given/When/Then
4. **能力 3**：有任务列表后 → 按负载均衡分配给军团 + 附完整上下文
5. **能力 4**：军团提交 PR → 按 10 项清单审查 → BLOCKING 附明确修复要求 → appeal 通道可用
6. **能力 5**：每日 18:00 自动发技术进度摘要 → BLOCKING 即时推送 → >24h 无进展触发催促

---

## 五、建议开发顺序（按依赖关系）

1. 先搭 Hermes 实例基础框架（独立 profile、端口、state.db）
2. 能力 1（技术方案设计）— 核心价值链入口
3. 能力 2（任务拆分）— 依赖能力 1 输出
4. 能力 3（军团调度）— 依赖能力 2 输出
5. 能力 0（项目启动自动化）— 串联 1+2+3
6. 能力 4（代码审查）— 独立能力，可并行
7. 能力 5（进度汇报）— 依赖军团通讯建立后

---

**状态**: 🟢 已接收（L1-麒麟军团 · 2026-04-25）
**接收确认**: 见下方「接收确认」段落

---

## 接收确认

**接收方**: L1-麒麟军团（AICTO 指挥官）
**接收时间**: 2026-04-25
**复杂度判定**: **XL 级**（6 能力 + 独立 profile + 飞书集成 + 军团通信，跨 10+ 文件、架构层）
**流程**: 启用完整军团流程（3 路侦察 + 流水线实现 + 3 验证者 + worktree 隔离）

### 现状速查（已确认）
- ✅ aicto profile **已存在**且 gateway running，端口 **8644 已 LISTEN**（ai-hr=8643, default=8642）
- ✅ HERMES_HOME = `/Users/feijun/.hermes/profiles/aicto`（独立 state.db / sessions / skills）
- ✅ 现有 hermes-plugin 8 个 stub 工具 + 反幻觉 hook 已注册
- ✅ AICTO 项目已 git init（worktree 隔离就绪）
- ⚠️ aicto profile `config.yaml` 的 `HERMES_SYSTEM_PROMPT` **是 AIHR 的**（"你是团队里的 HR"）— 必须修
- ⚠️ SOUL.md 叫 "AICTO" 而非 "程小远" — 修正为人格化名字
- ⚠️ 现有 8 stub 工具命名（review_architecture / assess_technical_risk 等）与 PM 派发的 6 能力（kickoff_project / design_tech_plan / breakdown_tasks / dispatch_to_legion_balanced / review_code / daily_brief）**几乎完全不重叠** — 决策：替换为 PM 6 能力命名（仅 review_code 保留）

### 执行计划

| 阶段 | 内容 | 产出 | 预计 |
|-----|------|------|-----|
| **侦察**（进行中） | 3 路并行参谋：飞书 PRD 全量抓取 / AICTO 历史文档梳理 / AIHR&ProdMind 同类实现参照 | `.planning/phase1/recon/*.md` | 1-2h |
| **架构 spec** | REQUIREMENTS / ARCHITECTURE / PHASE-PLAN / ADR-001~ADR-00X | `.planning/phase1/specs/*.md` + `.planning/phase1/decisions/*.md` | 2-3h |
| **基础修复** | 修 profile system_prompt / SOUL→程小远 / hermes-plugin 8stub→6 能力骨架 | `hermes-plugin/` 重构 | 0.5d |
| **能力 1**（design_tech_plan） | 飞书 PRD 读取 + 可行性评估 + 技术栈选型 + 飞书文档输出 + ADR 写入 | + 测试 | 1-2d |
| **能力 2**（breakdown_tasks） | 任务 DAG + Given/When/Then 验收标准 | + 测试 | 0.5-1d |
| **能力 3**（dispatch_to_legion_balanced） | 军团调度 + 负载均衡 + 上下文注入 | + 测试 | 0.5-1d |
| **能力 0**（kickoff_project） | 8 步串联（含飞书卡片）+ 4 级错误分类 | + 测试 | 1d |
| **能力 4**（review_code） | 10 项审查清单 + BLOCKING 硬 gate + appeal 通道 | + 测试 | 1-2d |
| **能力 5**（daily_brief + escalate） | 18:00 cron + BLOCKING 即时推送 + 24h 催促 | + 测试 | 0.5-1d |
| **集成验收** | 6 能力端到端 + 红队 + 合规审计 | 验收报告 | 1d |

**全程预计**：5-9 个工作日。

### 关键风险（已识别）
1. 飞书 tenant_access_token 2h 过期需缓存刷新机制
2. ADR 表存储位置（独立 SQLite vs 与 ProdMind 共享 dev.db）— 需架构决策
3. 军团调度的 mailbox/outbox 协议（与现有 L1 军团 inbox.jsonl 兼容）
4. 4 级错误分类（技术/权限/意图/未知）的判定边界 — 需 PRD 细节确认
5. 18:00 cron 实现机制（Hermes 内置 cron 还是 plugin 自管）

—— L1-麒麟军团指挥官 / 2026-04-25

---

## 反向问题（侦察阶段后发现，2026-04-25）

经三路并行侦察（飞书 PRD 全量抓取 / AICTO 历史文档梳理 / AIHR&ProdMind 同类实现参照），合并去重后真正需要 PM 仲裁的问题：

### 🔴 高优先级（架构 spec 落锤前需答复）

**Q-1: ADR 表存储位置 — 历史 v0.2 已结案，PM 派发疑似重启**

历史立场（`docs/PRODUCT-SPEC-v0.2-merged.md` §11.3 + `docs/CTO-READ-ACCESS-SPEC.md` §四）已结案：**ADR / TechRisk / TechDebt / CodeReview / EngineerProfile 5 张 CTO 自有表放 ProdMind dev.db 共享**，权限隔离靠 `_cto_own_connect()` vs `_readonly_connect()` 函数对 + SQLite URI `mode=ro` 物理挡写。完整 Prisma schema 已写。

但 PM 派发 §五·风险 #2 把这一条重新挂为"独立 SQLite vs 与 ProdMind 共享 dev.db"待决。

请确认：是 PM 不知历史决策（默认沿用共享 dev.db 即可）？还是有意推翻另起独立 SQLite？

→ **L1 默认采用 v0.2 历史立场（共享 dev.db）推进 spec**，如 PM 推翻则 ADR 层重做。

**Q-2: 4 级错误分类的判定边界**

PRD §五·能力 0 仅一笔带过"技术→自主重试 / 权限→升级骏飞 / 意图→给选项 / 未知→保守升级"，未给具体判定规则。

请明确：
1. 每级具体落到哪些异常（如：网络超时、飞书 token 失效、LLM 拒答、git push 拒绝、SQL 错误、参数缺失... 各属哪级？）
2. 是否全 6 能力共享此分类？还是仅能力 0 适用？
3. 重试参数（次数、退避策略、上限）

→ **L1 默认基于行业标准做 reasonable assumption，spec 中标注待 PM 仲裁**。

**Q-3: BLOCKING appeal 升级阈值**

`docs/HANDOFF-TO-PM.md` 抛给 PM 的开放点：建议 1 次 appeal 失败后即升级骏飞（避免拉锯）。PM 派发 §二·能力 4 仅说"appeal 通道可用"未明确阈值。

请确认：Phase 1 是否采纳"1 次"作为默认值？

→ **L1 默认采用 1 次（与历史立场一致）推进**。

**Q-4: PRD 数据源 — 飞书 docx vs ProdMind dev.db vs 双源**

PM 派发顶部给的是飞书 PRD 文档链接（ZeMedrjG1ogqhnxsxZuc5dF0nfe）。但 `docs/CTO-READ-ACCESS-SPEC.md` 完整规格是 dev.db + 飞书 docx 双源（dev.db 主、飞书 docx 含全文链接）。

请明确：design_tech_plan 的 input 是 `prd_id`（dev.db）/ `prd_markdown`（直接传文本）/ `prd_doc_token`（飞书 docx URL）三选一同时支持，还是只取派发的飞书 docx 直读？

→ **L1 默认三选一同时支持（Schema 已在历史规格中定义），spec 中以 dev.db `prd_id` 为主链路 + 飞书 docx URL 为备用**。

**Q-5: KR1（≤5 次/周）和 KR3（≤15%）的指标含义**

PRD §四给出 4 个 KR，KR2/KR4 含义清楚（100% PRD 有方案 / ≤5 分钟 SLA），但 KR1 和 KR3 仅给数字未给指标含义。请补充。

### 🟡 中优先级（实现阶段前需答复，不阻塞 spec）

**Q-6: EngineerProfile 表 Phase 1 是否落地**

PM 派发能力 3 隐含需要 EngineerProfile 数据（按军团能力 × 负荷分派），但派发未要求建表。`docs/PRODUCT-SPEC-v0.2-merged.md` §6.5 列为 Phase 2/3 范围。

请确认：Phase 1 是建 EngineerProfile 表落地完整算法？还是先用 hardcoded 军团能力 dict + Phase 2 再落表？

→ **L1 默认采用 Phase 1 hardcoded + Phase 2 落表的渐进路径**。

**Q-7: 18:00 daily_brief 的时区与补发策略**

请确认：18:00 是 UTC+8（服务器本地）还是 PM/骏飞所在时区？Hermes 重启错过 18:00 是否补发？

→ **L1 默认 UTC+8 + 错过则下一日 09:00 补发摘要**。

**Q-8: kickoff_project 第 3 步 "ProdMind 项目条目" 的协议**

候选：(a) CTO 直接写 prodmind dev.db Project 表（违背只读纪律）；(b) HTTP 调 ProdMind 8642 端口；(c) 飞书 @张小飞 自然语言；(d) inter-agent mailbox 文件接口。请 PM 选定。

→ **L1 默认采用 (b) HTTP 调 ProdMind 8642 端口**（最规整、不违反读写边界）。

**Q-9: 飞书"项目群通知"目标群**

候选：(a) AICTO 工作群（固定）；(b) 项目专属新群（CTO 自动建群）；(c) 现有 PM/项目群。请 PM 确认 Phase 1 目标群 chat_id。

→ **L1 默认 (a) AICTO 工作群（最简单），需 PM 提供 chat_id**。

**Q-10: BLOCKING 准确率 ≥90% 和 appeal 率 ≤20% 的分子分母定义**

请明确度量口径（如：被骏飞复核维持的 BLOCKING / 总 BLOCKING ≥ 90%？ appeal 数 / BLOCKING 总数 ≤ 20%？）— 影响埋点设计。

---

**所有 🔴 问题如未在 24h 内得到 PM 答复，L1 将按各问题下方的"默认推进"决策继续 spec 与实施，并在 ADR 中明确标注"待 PM 仲裁如推翻则修订"**。

—— L1-麒麟军团指挥官 / 2026-04-25
