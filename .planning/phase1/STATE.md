# Phase 1 — STATE（实时进度）

> 这份文件是 Phase 1 全流程的"指南针"。每阶段切换、每个 teammate 接棒都要更新此处。
> 旧版 `.planning/STATE.md` 是 Phase 0 时期的，保留作为历史快照。

## 当前阶段
**🚧 阶段 3 · 实施 P1.3 — 待启动**（2026-04-25）

P1.2 完成（commit 待落地）。reviewer 1 BLOCKING 已修，verifier 9/9 PASS。
ad8ee5fb 7 + c2e9ad6b 9 = 16 条真 ADR 留存 dev.db（Dogfood/真分析，待 Phase 1 收尾决策）。

5 NON-BLOCKING（reviewer-p1-2）+ 3 MED（verifier-p1-2）= 8 项收尾批次：
- N-1 permission 静默不 escalate
- N-2 ADR catch 太宽
- N-3 LLM 没用 response_format
- N-4 import 在函数内
- N-5 多 1 次 DB round-trip
- M-1 apimart fallback SSE 兼容
- M-2 HTTP 400 → unknown 而非 intent
- M-3 ProjectDocument 反查失败静默降级标注

—— 留 P1.7 / 收官前批量打补丁（与 cron 实现一并）

## 历史阶段记录

### P1.2 流水线
| Teammate | 任务 | Task | 状态 | 产出 |
|---------|------|------|------|------|
| impl-design-tech-plan | 6 步推理链 + ADR 自动写入 + 飞书 doc | #16 | ✅ done | 1049 行 + 87 行 prompt + tools.py 接入 |
| **reviewer-p1-2** | 7 维审查 | #17 | 🟡 in_progress | — |
| **verifier-p1-2** | 9 场景实测 | #18 | 🟡 in_progress | — |

### P1.2 implementer 自验证关键证据
- ✅ 9/9 自验证 PASS
- ✅ KR4 实测 41-68 秒（远低于 300s SLA）
- ✅ red verdict improvement_path 含 4 段详细改进路径
- ✅ missing_info → blocking_downstream=true
- ✅ ADR 写入 7 条（number 1-7 自动递增）
- ✅ 飞书 doc 回读 2654 字符（feasibility/工期/技术栈/风险/missing_info 全段齐）
- ✅ gateway restart 无 ERROR，1 hook loaded

### P1.1 流水线团队进度
| Teammate | 模块 | Task | 状态 | 产出 |
|---------|------|------|------|------|
| impl-feishu | feishu_api.py | #9 | ✅ done | 2040 行（整文件 copy + 3 处常量改）|
| impl-pmdb | pm_db_api.py + tools.py 接入 | #10 | ✅ done | 627 行 + 接入 10 工具 + 审计日志 |
| impl-adr | adr_storage.py | #11 | ✅ done | 933 行 + 11 项自验证 + 5 张 CTO 表 |
| impl-legion | legion_api.py | #12 | ✅ done | 547 行 + L1-麒麟军团双通道实测 |
| impl-errcls | error_classifier.py | #13 | ✅ done | 507 行 + 47/47 单测 + escalation.log 兜底 |
| **reviewer-p1-1** | 批次审查 5 模块 | #14 | 🟡 in_progress | — |
| **verifier-p1-1** | 7 场景实测 | #15 | 🟡 in_progress | — |

### P1.1 关键证据（implementer 自验证）
- ✅ mode=ro 物理挡写：INSERT/UPDATE/DELETE 三 SQL 全抛 `attempt to write a readonly database`
- ✅ Plugin 加载：aicto 1.0.0 enabled / 16 工具注册 / 1 hook loaded
- ✅ Gateway 已 restart：8644 LISTEN / no ERROR
- ✅ 真实 token：t-g1044peu...（42 字符）
- ✅ 真实 PRD 读取：用 prdid `4f3e135a-...` 跑通
- ✅ 5 张 CTO 表创建：sqlite3 dev.db 验证存在
- ✅ 10 个 commander discover：含 L1-麒麟军团 alive=True
- ✅ 47 单测：4 级分类 + retry + escalate + give_options 全过

## 历史阶段记录
- 阶段 1 · 侦察（2026-04-25）— 三路并行参谋全数交付
- 阶段 2 · 架构 spec（2026-04-25）— REQUIREMENTS / ARCHITECTURE / PHASE-PLAN / DECISIONS / 10 ADR / features.json
- 阶段 3 · P1.0 基础设施（2026-04-25）— plugin 挂载 + 16 工具骨架注册 + SOUL.md 程小远化 + gateway 重启
- **PM 答复 R-OPEN 12 项全闭**（2026-04-25 15:05 + 15:15）— 所有 PROVISIONAL ADR 升级 LOCKED

## Phase 1 任务来源
- 派发文件：`.dispatch/inbox/task-001-phase1-full.md`
- PRD（飞书）：https://ucnrf25nllyh.feishu.cn/docx/ZeMedrjG1ogqhnxsxZuc5dF0nfe
- 派发方：ProdMind / 张小飞
- 复杂度判定：**XL 级**（6 能力 + 独立 profile + 飞书集成 + 军团通信）

## 已完成
- ✅ 接收派发任务（task-001 状态 🟢）
- ✅ git init AICTO 项目（master 分支）
- ✅ 创建 `.planning/phase1/` 工作区
- ✅ 项目 CLAUDE.md 端口纠错（8643→8644）
- ✅ TeamCreate `phase1-aicto` 团队
- ✅ 3 路侦察参谋启动（Task #1/#2/#3，状态 in_progress）

## 进行中（侦察阶段）
| 参谋 | 任务 | 输出文件 | 状态 |
|------|------|---------|------|
| scout-prd | 飞书 PRD 全量抓取 | `recon/PRD-FULL.md` + `recon/PRD-CAPABILITIES.md` | ✅ **completed**（PRD 6200 字 10 节齐全，19 项派发漏掉的细节，15 个反问，10 条风险） |
| scout-history | AICTO 历史文档梳理 | `recon/RECON-HISTORY.md` | ✅ **completed**（378 行，24 条有效决策，4 个真冲突点） |
| scout-reference | AIHR/ProdMind 参照 | `recon/RECON-REFERENCE.md` | ✅ **completed**（815 行 / 24 项可复用资产 / 15 避坑点 / 12 不确定项） |

## 当前阶段
**🔍 侦察阶段已完成 → 架构 spec 阶段（2026-04-25）**

## scout-prd 关键吸收（2026-04-25）

### 派发漏掉的 PRD 关键约束（必须补回 spec）
- **KR4**: design_tech_plan PRD → 技术方案 ≤5 分钟（SLA）
- **KR2**: 100% PRD 有对应技术方案
- **KR1**: ≤5 次/周（不知道指标含义，需问 PM）
- **KR3**: ≤15%（不知道指标含义，需问 PM）
- **BLOCKING 准确率 ≥90%**（前 10 次骏飞强制复核）
- **军团 appeal 率 ≤20%**
- **Dogfood 3 样例零幻觉**（验收）
- 能力 1：red verdict 必须给改进路径（不能只说不可行）/ missing_info 阻塞下游 / 每个技术选型自动写 ADR
- 能力 4：BLOCKING 文案"把 X 改成 Y 因为 Z"格式约束 / 忽略 BLOCKING = 纪律违规升级骏飞
- 能力 5：日报"30 秒掌握全部进度"= 高度概括而非长文
- Phase 2/3 蓝图（架构必须预留扩展点）

### 反问清单合并（scout-history + scout-prd 交叉去重）
最终需向 PM 反问的高优先级问题：
1. 🔴 **ADR 表存储位置**（scout-history 7-A + scout-prd Q-2 / R-3）
2. 🔴 **4 级错误分类的判定边界**（scout-prd Q-1，全 6 能力是否共享）
3. 🔴 **飞书 token 缓存刷新策略**（scout-prd Q-3）
4. 🔴 **18:00 cron 实现机制 + 时区 + 补发**（scout-prd Q-4）
5. 🔴 **mailbox/outbox 协议规格 + L1 军团 inbox.jsonl 兼容性**（scout-prd Q-5）
6. 🟡 BLOCKING appeal 升级阈值（scout-history 7-B）
7. 🟡 PRD 数据源（飞书 docx / dev.db / 双源）（scout-history 7-C + scout-prd Q-9）
8. 🟡 EngineerProfile 表 Phase 1 是否落地（scout-history 7-D + scout-prd Q-12）
9. 🟡 KR1 / KR3 指标含义（scout-prd 派发漏掉 #1）
10. 🟡 BLOCKING 准确率 / appeal 率分子分母定义（scout-prd Q-14）

### scout-prd 识别的 10 条风险（已加入风险登记）
R-1~R-10 覆盖：飞书 API 限流 / 4 级错误歧义 / ADR 选型 / mailbox 兼容 / cron 实现 / 阻塞协议 / 度量埋点 / EngineerProfile / 卡片回调 / 幻觉验收方法

## 侦察吸收笔记（scout-history 已交付）

### 决策升级 — 历史立场被 PM 派发"重启"的（必须仲裁）
- 🔴 **ADR 表存储位置**：v0.2 §11.3 已结案=共享 prodmind dev.db；PM 派发 §五·风险 #2 重新挂为待决。**疑似 PM 不知历史立场**。需 dispatch 反问。
- 🟡 **BLOCKING appeal 升级阈值**：HANDOFF-TO-PM.md 建议 1 次；PM 派发未明确。
- 🟡 **PRD 数据源**：CTO-READ-ACCESS-SPEC.md 是 dev.db + 飞书 docx 双源；PM 派发只给飞书 docx URL。
- 🟡 **EngineerProfile 表 Phase 1 是否落地**：能力 3 隐含需要，PM 派发未要求建表。

### 决策固化 — 历史立场仍有效，无需仲裁
- ✅ 端口 8644 / app_id cli_a949... / 程小远命名 / 绝对指挥权 / BLOCKING 硬 gate / appeal 通道
- ✅ 4 级失败分类（Tech/Permission/Intent/Unknown）+ exception 关键词匹配规则
- ✅ 单 PR ≤ 5 评论 / 单文件 ≤ 2 BLOCKING（评论密度规则）
- ✅ 单军团并发 ≤ 2 任务 / 派单附完整上下文 / DAG 不允许环
- ✅ design_tech_plan 三档时间估计 / red 必须告诉 PM 改什么 / missing_info 反向推回 PM
- ✅ 18:00 daily_brief / >24h 无进展自动催促
- ✅ 反幻觉 5 条（迁入 SOUL.md）
- ✅ 工具输出必须结构化 JSON

### 可复用资产（scout-history §8 完整清单）
- v0.2/v0.3 已经铺好的 JSON 契约（kickoff_project / design_tech_plan / breakdown_tasks / dispatch_to_legion_balanced / review_code）
- 5 张 Prisma schema（ADR / TechRisk / TechDebt / CodeReview / EngineerProfile）
- `_readonly_connect()` / `_cto_own_connect()` 函数对（dev.db `mode=ro` + 自有表写）
- 8 个 PM 只读工具签名 + 2 个综合工具
- review_code 评论密度算法（BLOCKING/NON-BLOCKING/SKIP NIT 决策树）
- design_tech_plan 内部推理链（Read PRD → Extract → ADR history → EngineerProfile → feasibility matrix → tech stack → score → write ADR → 飞书 doc）
- 项目启动飞书卡片 UX（含 [查看 ADR] / [加入军团群] / [暂停项目] 按钮）

### 已识别 4 个真正需 PM 仲裁的冲突点（spec 阶段统一汇总反问 PM）
等 scout-prd 抓完飞书 PRD，看 PRD 全文是否已自答了 7-A/B/C/D，再决定是否反问 PM。

## 现状速查（已确认事实）

### Hermes profile
- aicto profile **已存在**且 gateway running
- 端口 **8644** 已 LISTEN（与 PM 派发要求一致）
- HERMES_HOME = `/Users/feijun/.hermes/profiles/aicto`
- Skills: 77 (bundled)，.env 模板已存在
- ⚠️ `config.yaml` 的 `HERMES_SYSTEM_PROMPT` 错抄自 AIHR（"你是团队里的 HR"）— 待修
- ⚠️ `SOUL.md` 叫 "AICTO" 而非 "程小远" — 待改名

### hermes-plugin 现状
- 8 个 stub 工具：review_architecture / assess_technical_risk / recommend_tech_stack / review_code / evaluate_prd_feasibility / analyze_technical_debt / propose_refactor / record_tech_decision
- 全部返回 `{"status": "not_implemented"}`
- 反幻觉 hook 已注册（pre_llm_call）
- ⚠️ 工具命名与 PM 派发 6 能力 GAP 巨大（仅 review_code 重叠）

### 端口分配（确认）
- 8642 → default profile（PM / ProdMind / 张小飞）
- 8643 → ai-hr profile（AIHR / 招聘）
- 8644 → aicto profile（AICTO / 程小远）

### Phase 1 6 能力（PM 派发简版）
| ID | 能力 | 优先级（建议顺序） |
|----|------|-------------------|
| 0 | kickoff_project（项目启动 8 步） | 5（依赖 1+2+3） |
| 1 | design_tech_plan（PRD→技术方案） | 1（核心入口） |
| 2 | breakdown_tasks（方案→任务 DAG） | 2 |
| 3 | dispatch_to_legion_balanced（智能调度） | 3 |
| 4 | review_code（10 项审查 + 硬 gate） | 6（独立可并行） |
| 5 | daily_brief + escalate（进度汇报） | 7（依赖军团通信） |

## 下一阶段（侦察完成后）
- 阶段 2 · 架构 spec：综合 3 路侦察 → 写 REQUIREMENTS / ARCHITECTURE / PHASE-PLAN
- ADR-001~ADR-00X：关键决策日志（端口/飞书 app/dev.db 共享/工具命名替换）
- baseline commit + 创建 worktree

## 关键决策（已做 / 待决）

### 已做
- D1: 工具命名按 PM 派发 6 能力替换 8 stub（仅 review_code 保留）
- D2: 端口 8644（与 PM 派发一致）
- D3: 启用完整军团流程（XL 级，3 路侦察 + 流水线 + 3 验证）

### 待决（侦察后定）
- D4: ADR 存储位置（独立 SQLite / 共享 ProdMind dev.db / 文件系统）
- D5: 飞书 app 共用 PM 的 cli_a9495f70ddb85cc5 还是申请独立 app（PM 派发给的就是这个 app_id，含义待 PRD 确认）
- D6: 18:00 cron 实现（Hermes 内置 cron / plugin 自管 / 系统 cron）
- D7: 4 级错误分类的判定边界细节
- D8: 与 L1 军团通信协议（沿用 inbox.jsonl 还是另起 mailbox）

## 风险登记（侦察阶段实时更新）
1. 飞书 token 2h 过期需缓存刷新
2. ADR 表存储与 ProdMind dev.db 的耦合
3. 军团调度协议向后兼容现有 L1 军团 inbox.jsonl
4. 6 能力的实现顺序依赖关系（PM 建议 1→2→3→0→4→5，本指挥官采纳）
5. profile config.yaml 的 system_prompt 错抄是否影响当前 8644 gateway 运行（如已有用户调用过会报错——需验证）

## 反向问题（汇总后通过 dispatch 文件反问 PM）
（侦察完成后填）
