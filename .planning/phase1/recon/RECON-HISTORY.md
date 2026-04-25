# AICTO 历史文档侦察报告

> **侦察兵**：scout-history（参谋 B）  
> **任务来源**：L1-麒麟军团 Task #2  
> **产出时间**：2026-04-25  
> **input 范围**：CLAUDE.md / README.md / docs/×7 / .planning/STATE.md / hermes-plugin/×4 / .dispatch/inbox/task-001-phase1-full.md（共 15 份）  
> **核心使命**：定位"哪些历史决策仍有效 / 哪些被 PM 派发覆盖 / 哪些 PM 派发没回答但历史已有立场"

---

## 0. 文档清单与来源映射

| # | 文件 | 作者 / 视角 | 时间 | 状态 |
|---|------|------------|------|------|
| 1 | `CLAUDE.md` | team lead × Claude Code | 2026-04-23 | 当前 |
| 2 | `README.md` | Claude Code | 2026-04-23 | 当前（尚未刷新） |
| 3 | `docs/ROLES.md` | Claude Code | 2026-04-23 | v0.1 角色拆解 |
| 4 | `docs/PRODUCT-SPEC.md` | Claude Code（CTO 视角） | 2026-04-23 上午 | **v0.1 已被 v0.2 取代** |
| 5 | `docs/PRODUCT-SPEC-v0.2-merged.md` | Claude Code 合并 PM v0.1 | 2026-04-23 中午 | **当前主基线** |
| 6 | `docs/PRODUCT-RESEARCH-v0.3.md` | Claude Code（含越权自检） | 2026-04-23 下午 | 部分有效（含越权段落） |
| 7 | `docs/PM-CTO-BOUNDARY-MATRIX.md` | Claude Code 基于 lead 提示 | 2026-04-23 | **当前协作宪法** |
| 8 | `docs/CTO-READ-ACCESS-SPEC.md` | Claude Code（CTO 技术实现） | 2026-04-23 | 当前 |
| 9 | `docs/HANDOFF-TO-PM.md` | Claude Code 交接 | 2026-04-23 | 当前（已交棒 PM） |
| 10 | `.planning/STATE.md` | Claude Code | 2026-04-23 | 待更新（Phase 0→Phase 1 翻页） |
| 11 | `hermes-plugin/__init__.py` | Claude Code | 2026-04-23 | 当前（含反幻觉 hook）|
| 12 | `hermes-plugin/plugin.yaml` | Claude Code | 2026-04-23 | 当前 |
| 13 | `hermes-plugin/schemas.py` | Claude Code | 2026-04-23 | 当前（8 schema）|
| 14 | `hermes-plugin/tools.py` | Claude Code | 2026-04-23 | 当前（全 stub）|
| 15 | `.dispatch/inbox/task-001-phase1-full.md` | PM 张小飞 | 2026-04-25 | **派发任务源** |

---

## 1. 项目时间线（按版本）

```
2026-04-23 (D-2)
 ├─ 上午  v0.1 PRODUCT-SPEC.md             ← Claude Code 起草 8 能力 (CTO 视角)
 │       · 8 工具：review_architecture / assess_technical_risk / recommend_tech_stack /
 │              review_code / evaluate_prd_feasibility / analyze_technical_debt /
 │              propose_refactor / record_tech_decision
 │       · 5 个 §10 开放问题挂起
 │
 ├─ 中午  v0.2 PRODUCT-SPEC-v0.2-merged.md ← 合并 PM 张小飞 v0.1 飞书方案
 │       · 起源：PM 提出"端到端闭环 6 能力"，本地 v0.1 提出"决策资产层"
 │       · 合并原则：PM 6 能力作 Phase 1 骨架 + 本地决策资产层作 Phase 2
 │       · CTO 名字定为 "程小远"（PM v0.1 起，本地 v0.2 采纳）
 │       · 新增 能力 0 = 项目启动自动化（8 步）
 │       · team lead 当日补充：CTO 全自动化、绝对指挥权、4 级失败分类
 │
 ├─ 下午  v0.3 PRODUCT-RESEARCH-v0.3.md   ← 产品调研深化（部分越权）
 │       · L5 团队级技术负责人定位
 │       · 6 大能力深规格 + JSON 契约
 │       · BLOCKING 硬 gate + appeal 通道
 │       · ⚠️ 自检：场景 2-7 / 一天剧本 / Dogfood 推荐 = PM 越权（需 PM 重写）
 │
 ├─ 同日  PM-CTO-BOUNDARY-MATRIX.md       ← 维度正交协作宪法
 │       · PM = WHAT+WHY 原子需求；CTO = HOW 原子实现
 │       · 越权清单 + 自检表
 │
 ├─ 同日  CTO-READ-ACCESS-SPEC.md         ← 8 个只读工具 + mode=ro 访问 dev.db
 │
 └─ 同日  HANDOFF-TO-PM.md                ← 完整产品设计交棒 PM
         · 4 个开放点等 PM 在飞书问 lead

2026-04-25 (D0)
 └─  task-001-phase1-full.md             ← PM 派发 Phase 1 全量任务 (P0)
        · 6 能力命名：kickoff_project / design_tech_plan / breakdown_tasks /
                      dispatch_to_legion_balanced / review_code / daily_brief
        · L1-麒麟军团接收，复杂度判 XL，启动完整军团流程
        · 接收确认中已识别：8 stub vs 6 能力命名几乎完全不重叠
```

**关键演进脉络**：
- v0.1 是**单方 CTO 视角**的 8 能力分解；v0.2 起以 **PM 端到端闭环 6 能力** 为骨架；v0.3 深化但越权；2026-04-25 PM 派发收口 Phase 1。
- "8 工具" 命名（v0.1）→ "6 能力" 命名（v0.2/PM 派发）的**命名空间替换**已在 PM 派发的接收确认段落明确：**仅 review_code 保留，其余 7 个全替换**。

---

## 2. 已落定的产品决策（仍有效）

按"决策内容 / 来源 / PM 派发是否覆盖"三栏列出：

| # | 决策 | 来源（文件 / 节） | PM 派发态度 | 是否仍有效 |
|---|------|------------------|------------|----------|
| 2.1 | 独立 Hermes profile `aicto`，端口 **8644**（避开 PM 8642、AIHR 8643），独立 state.db / sessions / plugins / 飞书 app | `CLAUDE.md` §部署 / `PRODUCT-SPEC-v0.2-merged.md` §六 / `task-001-phase1-full.md` §三 | **明确确认** | ✅ 有效 |
| 2.2 | 飞书 app 凭证：`app_id = cli_a9495f70ddb85cc5` | `plugin.yaml` / `PRODUCT-SPEC-v0.2-merged.md` §二 / `task-001-phase1-full.md` §一 | **明确给出 secret** | ✅ 有效 |
| 2.3 | CTO 人格名 = **程小远**（PM v0.1 起，本地 v0.2 采纳） | `PRODUCT-SPEC-v0.2-merged.md` §二 / §十一 | **派发标题明确**："AI CTO 程小远 Phase 1 全量" | ✅ 有效 |
| 2.4 | OPC 拓扑：PM 定 WHAT、CTO 决 HOW、军团 DO；CTO 是 PM 与军团之间的技术节点 | `CLAUDE.md` §云智 AI 团队协作拓扑 / `PRODUCT-SPEC-v0.2-merged.md` §一 | 隐含确认（派发即建立 PM→CTO 链路） | ✅ 有效 |
| 2.5 | **CTO 对开发团队有绝对指挥权**（team lead 2026-04-23 拍板） | `PRODUCT-RESEARCH-v0.3.md` Part C §5 / `HANDOFF-TO-PM.md` 顶部 | 派发 §二 能力 3 重申"军团必须接（可 appeal 但不可直接拒）" | ✅ 有效 |
| 2.6 | **代码审查 BLOCKING = 硬 gate 阻塞 merge**（team lead 2026-04-23 拍板） | `PRODUCT-RESEARCH-v0.3.md` Part B 能力 4 / `HANDOFF-TO-PM.md` | 派发 §二 能力 4 完整保留 | ✅ 有效 |
| 2.7 | BLOCKING 配套约束：必须附**明确修复要求**；评论密度上限**单 PR ≤ 5 / 单文件 ≤ 2 BLOCKING** | `PRODUCT-RESEARCH-v0.3.md` Part B 能力 4 | 派发 §二 能力 4 完整复用 | ✅ 有效 |
| 2.8 | **军团 appeal 反向通道**（觉得 BLOCKING 不合理可上诉） | `PRODUCT-RESEARCH-v0.3.md` Part C §5 / `HANDOFF-TO-PM.md` | 派发 §二 能力 4 复用 | ✅ 有效（但**升级阈值未定**，见 §3） |
| 2.9 | 项目启动 8 步自动化（创建目录 / git init / Project / ADR / 拉军团 / 通讯 / 派任务 / 飞书通知） | `PRODUCT-SPEC-v0.2-merged.md` §四 能力 0 | 派发 §二 能力 0 完整复用 | ✅ 有效 |
| 2.10 | **4 级失败分类矩阵**（Tech→自动重试 / Permission→升级 lead / Intent→给选项 / Unknown→保守升级） | `PRODUCT-SPEC-v0.2-merged.md` §四 能力 0 | 派发 §二 能力 0 复用 | ✅ 有效 |
| 2.11 | **PM × CTO 维度正交**：PM 做原子化需求 (WHAT+WHY)，CTO 做原子化实现 (HOW)，互不越权 | `PM-CTO-BOUNDARY-MATRIX.md` 全文 | 派发隐含遵守（PRD = WHAT，技术方案 = HOW） | ✅ 有效（**协作宪法**） |
| 2.12 | **CTO → 军团直连**（不经 PM 中转） | `PRODUCT-SPEC-v0.2-merged.md` §十一 已解决 #6 | 派发 §二 能力 3 默认 CTO 直接 dispatch | ✅ 有效 |
| 2.13 | **ADR 等 5 张 CTO 独有表放 ProdMind dev.db 共享** | `PRODUCT-SPEC-v0.2-merged.md` §6 / §七 / §十一 已解决 #3 | 派发 §五·风险 #2 重新点为待决（"独立 SQLite vs 共享 dev.db"） | ⚠️ **PM 派发把已结案的事重新挂回 open**（见 §7 冲突点 7-A） |
| 2.14 | CTO 读 PM 数据用 SQLite URI **`mode=ro`**（物理挡写）+ `_readonly_connect()` / `_cto_own_connect()` 函数对分离 | `CTO-READ-ACCESS-SPEC.md` §二 / §四 | 派发未提及（沉默） | ⚠️ 历史立场仍持，**PM 派发未确认**（见 §3） |
| 2.15 | 8 个只读工具：`read_pm_project` / `read_pm_prd` / `list_pm_prd_decisions` / `list_pm_open_questions` / `list_pm_user_stories` / `list_pm_features` / `read_pm_research_doc` / `read_pm_evaluation_doc` + 2 综合工具 `get_pm_context_for_tech_plan` / `diff_pm_prd_versions` | `CTO-READ-ACCESS-SPEC.md` §三 | 派发未提及 | ⚠️ 历史立场仍持，**PM 派发未点名**（落实于 design_tech_plan 实现里） |
| 2.16 | **反幻觉 5 条纪律**（不声称未做的事 / 识别飞书引用回复 / 承认缺失不编造 / 技术决策要有根据 / stub 必须返 not_implemented） | `hermes-plugin/__init__.py:38-50` / `CLAUDE.md` §执行纪律 | 派发 §三明确"反幻觉纪律：SOUL.md 嵌入" | ✅ 有效（要从 plugin pre_llm hook 迁入 SOUL.md / 结构化 JSON） |
| 2.17 | **生产保护硬约束**：AICTO 启停 / 崩溃 / 升级**零影响 default profile（PM）和 ai-hr** | `CLAUDE.md` §部署 / `PRODUCT-SPEC-v0.2-merged.md` §九 | 派发 §三"宕机不影响 PM / AIHR / 军团运行" | ✅ 有效 |
| 2.18 | 工具输出必须**结构化 JSON**（不是自由文本）—— 下游可机读 | `PRODUCT-SPEC.md` §9 / `PRODUCT-SPEC-v0.2-merged.md` §九 | 派发 §三复用 | ✅ 有效 |
| 2.19 | 10 项代码审查清单（架构一致 / 可读性 / 安全 / 测试 / 错误处理 / 复杂度 / 依赖 / 性能 / 跨军团冲突 / PRD 一致） | `PRODUCT-SPEC-v0.2-merged.md` §四 能力 4 | 派发 §二 能力 4 完整复用 | ✅ 有效 |
| 2.20 | 单军团并发 ≤ 2 任务 + 有依赖任务延迟派单 + 派单时附完整上下文（PRD 摘要 + 技术方案 + 验收标准） | `PRODUCT-SPEC-v0.2-merged.md` §四 能力 3 | 派发 §二 能力 3 复用 | ✅ 有效 |
| 2.21 | 任务拆分：单任务 ≤ XL（≥3 天必拆）/ DAG 不允许环 / 验收标准 Given/When/Then 强制结构化 | `PRODUCT-SPEC-v0.2-merged.md` §四 能力 2 | 派发 §二 能力 2 复用 | ✅ 有效 |
| 2.22 | design_tech_plan 输出 `feasibility = green/yellow/red`，`red` 必须告诉 PM 改什么才能绿，`missing_info` 反向推回 PM | `PRODUCT-SPEC-v0.2-merged.md` §四 能力 1 | 派发 §二 能力 1 完整复用 | ✅ 有效 |
| 2.23 | 时间估计三档（乐观 / 可能 / 悲观）—— PM 用悲观决定范围 | `PRODUCT-SPEC-v0.2-merged.md` §四 能力 1 | 派发 §二 能力 1 复用 | ✅ 有效 |
| 2.24 | daily_brief：每日 **18:00** 自动生成 / BLOCKING 即时推送 / 军团 >24h 无进展自动催促 | `PRODUCT-RESEARCH-v0.3.md` Part B 能力 5 / `HANDOFF-TO-PM.md` 开放点 | 派发 §二 能力 5 锁定 18:00 | ✅ 有效 |

**有效条数：24**

---

## 3. 5 个开放问题的现状立场

来源：`PRODUCT-SPEC.md` §10（v0.1）+ `PRODUCT-SPEC-v0.2-merged.md` §11（v0.2 进展）+ `HANDOFF-TO-PM.md`（v0.3 末态）

| # | 开放问题 | v0.1 状态 | v0.2 立场 | v0.3 / PM 派发立场 | 当前是否仍 open |
|---|---------|---------|---------|------------------|----------------|
| O1 | **ADR 放在哪个 dev.db**（prodmind 共享 vs AICTO 独立） | open | ✅ 已解决 = **prodmind 共享**（v0.2 §11.3） | PM 派发 §五 风险 #2 把它**重新点为"需架构决策"** | ⚠️ **历史已结，PM 派发疑似不知或重启** |
| O2 | **CTO 飞书人格名**（AICTO vs 拟人化名字） | open | ✅ 已解决 = **程小远**（v0.2 §11.1） | PM 派发使用"程小远" | ✅ closed |
| O3 | **CTO → 军团的直连**（是否需 `consult_commander` 工具 / 是否经 PM 中转） | open | ✅ 已解决 = **直连**（v0.2 §11.6，team lead 2026-04-23 明确） | 派发 §二 能力 3 默认 CTO 直接 dispatch | ✅ closed |
| O4 | **代码评审 verdict 强度**（硬 gate vs 软建议） | open | 🟡 v0.2 倾向硬 gate 但待 lead 拍板 | ✅ v0.3 已解决 = **硬 gate + 绝对指挥权 + appeal 通道**（team lead 2026-04-23 拍板） · PM 派发完整复用 | ✅ closed |
| O5 | **跨项目技术债盘点**（项目级 vs 团队全局级） | open | 🟡 仍 open（v0.2 §11.2） | v0.3 / 派发均未回答 | ⚠️ **仍 open**（Phase 1 派发不含 analyze_technical_debt 能力，可暂时挂起） |

**HANDOFF-TO-PM.md 中由 Claude Code 抛给 PM 的 4 个开放点**（PM 派发是否回答）：

| # | 开放点 | PM 派发回答 |
|---|------|----------|
| H1 | CTO 申诉链路升级阈值（建议 1 次） | ❌ 未回答（见 §7 冲突点 7-B） |
| H2 | Dogfood 第一个 PRD 选哪个 | ⚠️ 派发顶部给了**飞书 PRD 文档链接**（即 Phase 1 全量本身），但未明示这是首个 dogfood 项目 |
| H3 | daily-brief cron 频率（18:00 是否合适） | ✅ 派发明确 18:00 |
| H4 | 飞书机器人在哪些群里可见（需 lead 添加进至少 1 个工作群） | ❌ 未回答（部署侧问题，可在实施时再问） |

**当前真正仍 open 的问题**：O1（ADR 存储位置 — PM 派发疑似重启）+ O5（跨项目技术债 — 可挂到 Phase 2/3）+ H1（appeal 升级阈值）+ H4（飞书群可见性）。

---

## 4. PM-CTO 边界矩阵（一行一项）

来源：`PM-CTO-BOUNDARY-MATRIX.md` 全文 + `PRODUCT-SPEC-v0.2-merged.md` §七 表格 + `CTO-READ-ACCESS-SPEC.md` §一/§四。

### 4.1 数据库表权限（dev.db / ProdMind 共享）

| 表 | PM 权限 | CTO 权限 | 来源 |
|----|---------|---------|------|
| `Project` | RW | R（含 `mode` / `authorization_scope` / `stage`） | v0.2 §七 / read-spec §一·A |
| `PRD` | RW | R（含 `feishuDocToken`） | v0.2 §七 / read-spec |
| `PRDVersion` | RW | R | read-spec §一·A |
| `PRDDecision` | RW | R | read-spec §一·A |
| `PRDOpenQuestion` | RW | R（CTO 评估时重点看） | read-spec §一·A |
| `UserStory` | RW | R | v0.2 §七 |
| `Feature` | RW | R（含 rice score） | v0.2 §七 / read-spec |
| `Research` | RW | R | read-spec §一·A |
| `Evaluation` | RW | R | read-spec §一·A |
| `Requirement`（Phase 8）| RW | R | read-spec §一·A |
| `Activity` | RW | R | read-spec §一·A |
| `Task` | RW | **R + 评审写**（CTO 可加 `review_result` 字段） | v0.2 §七 |
| `TeamMember` | R | R | v0.2 §七 |
| **`ADR`** | R | **RW** | v0.2 §七 / §6.1 |
| **`TechRisk`** | R | **RW** | v0.2 §七 / §6.2 |
| **`TechDebt`** | R | **RW** | v0.2 §七 / §6.3 |
| **`CodeReview`** | R | **RW** | v0.2 §七 / §6.4 |
| **`EngineerProfile`** | R | **RW**（AIHR 也读） | v0.2 §七 / §6.5 |

权限隔离机制：**SQLite URI `mode=ro`** 物理挡写（CTO 代码 bug 也写不动 PM 表），加 `_readonly_connect()` vs `_cto_own_connect()` 函数名分离（`CTO-READ-ACCESS-SPEC.md` §二·A / §四）。

### 4.2 工作维度正交（来源：`PM-CTO-BOUNDARY-MATRIX.md`）

| 维度 | PM 做 | CTO 做 |
|------|-------|--------|
| 工作单位 | 原子化需求 | 原子化实现方式 |
| 回答问题 | WHAT + WHY | HOW |
| 粒度 | 最小独立**用户价值**单元 | 最小独立**技术内聚**单元 |
| 视角 | 外部（用户怎么感受） | 内部（系统怎么运作） |
| 验收 | 用户侧可感知 | 工程侧可度量 |
| 用户调研 | ✅ 主责 | ❌ 不该涉及 |
| 市场调研（功能层） | ✅ 主责 | ❌ 不该涉及 |
| 市场调研（技术层） | ❌ 不该涉及 | ✅ 主责 |
| 商业价值 / ROI / 机会成本 | ✅ 主责 | ❌ 不该涉及 |
| 合规（用户层 / 实现层） | ✅ / 🟡 | 🟡 / ✅ |
| 技术栈 / 架构模式 / 性能基准 / 依赖风险 / 安全风险（实现层） | ❌ / ❌ / 🟡 / ❌ / 🟡 | ✅ / ✅ / ✅ / ✅ / ✅ |

### 4.3 越权红线

PM 越权 CTO（禁止句式）：
- "用 React 做前端"、"必须用 MongoDB"、"API 要 RESTful"、"用 WebSocket 做实时"、"表结构应该是 XXX"
- 正确句式："需要在 Web 浏览器访问"、"需要存 10 万条日志查询 < 200ms"、"需要让第三方查询此数据"

CTO 越权 PM（禁止句式）：
- "这个功能用户不需要"、"先做 A 再做 B"、"验收标准改成 X"、"这个用户体验更好"、"Dogfood PRD 应该选 X"
- 正确句式："此需求技术评估为 red，原因 X/Y/Z，**你（PM）决定**是否删除/调整/spike"

### 4.4 互验通道

- **通道 A · PM → CTO**：`evaluate_prd_feasibility(prd_id)` → CTO 返 `{feasibility, 粒度反馈, 验收标准反馈, 缺失信息}`，**CTO 不改需求**。
- **通道 B · CTO → PM**：tech_plan 附"副作用披露"（用户感知性能 / 新增交互 / 降级行为 / 依赖用户数据），**PM 不改技术方案**。

---

## 5. CTO 读权限规格（CTO-READ-ACCESS-SPEC.md）

### 5.1 dev.db 共享方案

- **路径**：`/Users/feijun/Documents/prodmind/dev.db`
- **连接方式**：`sqlite3.connect(f"file:{path}?mode=ro", uri=True)` —— SQLite 层物理挡写
- **WAL 并发**：允许 PM 写、CTO 读同时进行（reader 看到事务前快照）
- **写自有表**：`_cto_own_connect()`（无 `mode=ro`），仅用于 ADR / TechRisk / TechDebt / CodeReview / EngineerProfile

### 5.2 ADR 存储位置（决策已结）

- **历史决策（v0.2 §11.3）**：放 ProdMind dev.db 共享。理由 = 方便 PM 读决策链；权限隔离靠应用层 + SQLite URI `mode=ro`。
- ⚠️ **PM 派发 §五 风险 #2 把这一条重新点为待决** —— 历史立场仍是"共享"，但 PM 派发疑似不知。建议指挥官在 Phase 1 spec 阶段确认（见 §7-A）。

### 5.3 飞书 docx 读取

- 用 AICTO 自己的 app token（`cli_a9495f70ddb85cc5`）
- 调 `/open-apis/docx/v1/documents/{doc_token}/raw_content`
- 依赖 commit `fc86969` 的权限修复（新建文档默认 tenant_editable）
- 老文档（3 个 backfill 失败的）需 lead 手工补权限

### 5.4 8 个只读工具

`read_pm_project` / `read_pm_prd` / `list_pm_prd_decisions` / `list_pm_open_questions` / `list_pm_user_stories` / `list_pm_features` / `read_pm_research_doc` / `read_pm_evaluation_doc` + 2 个综合 `get_pm_context_for_tech_plan` / `diff_pm_prd_versions`

### 5.5 审计与缓存

- 每次读 PM 数据 → 一行进 `~/.hermes/profiles/aicto/logs/read-audit.log`（timestamp / tool / args）
- 飞书文档可加 60s TTL 缓存
- dev.db 不缓存（读太快）

---

## 6. 现有 8 stub vs PM 派发 6 能力 GAP 表

| 现有 stub（v0.1 命名） | PM 派发 6 能力 | 关系 | 建议（仅指挥官参考，scout 不决策） |
|---|---|---|---|
| `review_architecture` | （无直接对应；架构判断融入 `design_tech_plan` 的 `architecture_summary` 字段） | 部分吸收 | 历史决策已并入 design_tech_plan |
| `assess_technical_risk` | （无直接对应；风险输出融入 `design_tech_plan.risks[]`）| 部分吸收 | 历史决策已并入 design_tech_plan |
| `recommend_tech_stack` | （无直接对应；选型输出融入 `design_tech_plan.tech_stack`）| 部分吸收 | 历史决策已并入 design_tech_plan |
| `review_code` | `review_code` | **直接重叠** | **保留命名 + 实化**（10 项清单 + BLOCKING 硬 gate） |
| `evaluate_prd_feasibility` | （无直接对应；可行性输出融入 `design_tech_plan.feasibility`）| 部分吸收 | 历史决策已并入 design_tech_plan |
| `analyze_technical_debt` | （Phase 1 不含；属 Phase 2/3 范围） | Phase 1 不要 | 派发未提，挂起（v0.2 §10 Phase 4 路径） |
| `propose_refactor` | （Phase 1 不含；属 Phase 2/3 范围） | Phase 1 不要 | 派发未提，挂起 |
| `record_tech_decision` | （Phase 1 隐含使用：ADR-0001 写入 / 每个技术选型自动写 ADR） | 工具复用 | 保留为内部辅助工具（非顶层 6 能力之一） |

PM 派发 6 能力中**全新（无 stub 对应）的有 5 个**：
| PM 派发能力 | 现有 stub 对应 | 是否新增 |
|---|---|---|
| `kickoff_project` | 无 | ✅ 全新（v0.2 §四 能力 0 已规划，未落代码）|
| `design_tech_plan` | 无（吸收 4 个旧 stub）| ✅ 全新命名 |
| `breakdown_tasks` | 无 | ✅ 全新（v0.2 §四 能力 2 已规划） |
| `dispatch_to_legion_balanced` | 无 | ✅ 全新（v0.2 §四 能力 3，复用 ProdMind 现有 dispatch_to_legion 加负载均衡封装）|
| `daily_brief` | 无 | ✅ 全新（v0.2 §四 能力 5）|
| `review_code` | `review_code` | ⚠️ 保留命名，重写实现 |

PM 派发的接收确认段落（task-001 §三 现状速查最后一行）已**明确**：8 stub 与 6 能力命名几乎完全不重叠，**仅 review_code 保留**。这是指挥官的现成判断，scout 仅作旁证。

---

## 7. 与 PM 派发的冲突点（必须 PM 仲裁的）

| # | 冲突点 | 历史立场 | PM 派发立场 | 仲裁优先级 |
|---|------|---------|------------|----------|
| 7-A | **ADR 表存储位置** | v0.2 §11.3 已结案 = **prodmind dev.db 共享**（含完整 Prisma schema）；CTO-READ-ACCESS-SPEC.md §四 已铺好"自有表写权限"路径 | PM 派发 §五·风险 #2 重新挂为待决"独立 SQLite vs 与 ProdMind 共享 dev.db" | 🔴 **高**（影响能力 0 第 4 步 ADR-0001 写入路径 + 能力 1 的 design_tech_plan ADR 写入）|
| 7-B | **军团 appeal 升级阈值** | HANDOFF-TO-PM.md 抛给 PM = "建议 1 次（避免拉锯）" | 派发 §二 能力 4 仅说"appeal 通道可用"，未给阈值 | 🟡 中（实现 review_code 时需要硬编码阈值）|
| 7-C | **dev.db 读访问的 SQLite URI `mode=ro` 方案** | CTO-READ-ACCESS-SPEC.md §二 完整规格 + 8 个只读工具 + 审计日志 | PM 派发完全沉默（PRD 文档链接给的是飞书 docx，未提 dev.db） | 🟡 中（design_tech_plan 实现时需要选定 PRD 数据源 = 飞书 docx 还是 dev.db 还是两者） |
| 7-D | **EngineerProfile 表是否 Phase 1 落地** | v0.2 §6.5 / §11 列为 Phase 2/3 起点 | 派发能力 3 `dispatch_to_legion_balanced` 要"按军团能力 × 负荷"分派，**隐含需要 EngineerProfile 数据**，但派发未要求建表 | 🟡 中（Phase 1 可降级为 hardcoded 军团能力 dict + Phase 2 落表） |
| 7-E | **跨项目技术债盘点** | v0.1 §10.5 / v0.2 §11 仍 open；v0.3 / 派发均未答 | 派发不含 analyze_technical_debt 能力 | 🟢 低（Phase 1 不实现，挂到 Phase 2+） |
| 7-F | **"程小远的一天"剧本中的范围** vs 派发的 6 能力 Day-1 全启用 | v0.3 Part D §4 建议 Phase 1 MVP **跑通能力 0+1+2+3 + Day-1 启用 4 + 5 daily-brief**（标注为半越权，PM 决策） | 派发把全部 6 能力都列为 Phase 1 全量、P0 | 🟢 低（PM 派发已覆盖 v0.3 半越权建议；执行按 PM 派发的全 6 能力推进，但开发顺序可参考 v0.3 建议）|
| 7-G | **v0.3 Part C §5 提到的"军团 auto-loop.sh hook"**（收到 BLOCKING 暂停 feature）| v0.3 / HANDOFF 列为 CTO 承接事项 | 派发 §五·风险 #3 提到"军团调度的 mailbox/outbox 协议（与现有 L1 军团 inbox.jsonl 兼容）"但未明确要改 auto-loop.sh | 🟡 中（review_code 阶段需明确） |
| 7-H | **plugin.yaml `provides_tools` 列表**（仍是 8 stub 旧命名） | `plugin.yaml:18-27` 当前 = 8 个 v0.1 命名 | 派发暗示需替换为 6 能力命名 | 🟢 低（实现时直接改）|
| 7-I | **aicto profile 的 `HERMES_SYSTEM_PROMPT`** | 派发 §三接收确认指出**当前是 AIHR 的 prompt**（"你是团队里的 HR"）| 派发明确要修 | 🟢 低（已识别）|
| 7-J | **SOUL.md 命名"AICTO" vs "程小远"** | 派发 §三接收确认指出 SOUL.md 当前叫 "AICTO" | 派发明确要改为"程小远" | 🟢 低（已识别）|

**冲突点小结**：4 个真正需要 PM 仲裁的（7-A / 7-B / 7-C / 7-D），3 个执行细节（7-G / 7-H / 7-I / 7-J），1 个 Phase 边界（7-E）。其余基本是历史立场和派发立场一致或已被派发明确覆盖。

---

## 8. 历史决策给 Phase 1 的可复用资产

按"可直接搬用"的颗粒度列出：

### 8.1 文档模板 / 纪律条款

| 资产 | 来源 | 用法 |
|------|------|------|
| **反幻觉 5 条纪律**（不声称未做 / 识别飞书引用回复 / 承认缺失 / 数据驱动 / stub 透明） | `hermes-plugin/__init__.py:38-50` | 直接搬入 SOUL.md |
| **PM × CTO 维度正交协作宪法** | `PM-CTO-BOUNDARY-MATRIX.md` 全文 | 搬入 SOUL.md 作 CTO 行为约束（特别是 §三越权红线 + §六自检表）|
| **CTO 自检表**（产出前 4 项检查） | `PM-CTO-BOUNDARY-MATRIX.md` §六 | 搬入每个工具的 docstring 头部作 reminder |
| 30 天睡得着的核心价值主张 | `PRODUCT-SPEC.md` §1.4 | SOUL.md 性格定位 |

### 8.2 JSON 契约 / Schema

| 资产 | 来源 | 用法 |
|------|------|------|
| `kickoff_project` 输出 schema（project / legion_system / initial_tasks_dispatched / adr_id / feishu_notification_sent） | v0.2 §四 能力 0 | 直接落 `schemas.py` |
| `design_tech_plan` 完整 input/output JSON 契约（含 mermaid / data_model / api_contracts / third_party_deps）| v0.3 Part B 能力 1 | 直接落 schema；Phase 1 MVP 简化版 = feasibility + time_estimate + tech_stack.selected + risks + missing_info + feishu_doc_url |
| `breakdown_tasks` 输出 schema（tasks[] + dependency_graph + Given/When/Then 验收）| v0.2 §四 能力 2 | 直接落 schema |
| `dispatch_to_legion_balanced` 输出 schema（assignments[] + mailbox_msg_id）| v0.2 §四 能力 3 | 直接落 schema |
| `review_code` 输出 schema（verdict / comments[] / test_coverage / tech_debt_introduced）| v0.1 §2.4 / v0.2 §四 能力 4 | 直接落 schema |
| **10 项审查清单** | v0.2 §四 能力 4 表格 | review_code 实现的核心 prompt |

### 8.3 Prisma Schema（5 张 CTO 自有表）

| 资产 | 来源 | 用法 |
|------|------|------|
| `ADR` schema（含 supersedes 链）| v0.2 §6.1 | Phase 1 必需（ADR-0001 写入）|
| `TechRisk` schema（7 维度 + earlyWarningSignal）| v0.2 §6.2 | Phase 2（design_tech_plan.risks 落库）|
| `TechDebt` schema | v0.2 §6.3 | Phase 2 |
| `CodeReview` schema（含 blocker/suggestion 计数）| v0.2 §6.4 | Phase 1 必需（review_code 写入）|
| `EngineerProfile` schema | v0.2 §6.5 | Phase 1 可选（dispatch_to_legion_balanced 推荐用，可降级为 hardcoded）|

### 8.4 实现路径 / 算法

| 资产 | 来源 | 用法 |
|------|------|------|
| **8 步项目启动流程**（创建目录 → git init → Project → ADR → 拉军团 → 通讯 → 派任务 → 飞书通知）| v0.2 §四 能力 0 + v0.3 Part B 能力 0 | kickoff_project 实现骨架 |
| **4 级失败分类矩阵**（Tech / Permission / Intent / Unknown）+ exception 关键词匹配规则 | v0.2 §四 能力 0 失败分类与升级路径 | kickoff_project 的 try/except 实现规则 |
| **`_readonly_connect()` / `_cto_own_connect()` 函数对** | CTO-READ-ACCESS-SPEC.md §二·A / §四 | tools.py 顶部辅助函数 |
| **8 个只读工具签名** + 2 个综合工具签名 | CTO-READ-ACCESS-SPEC.md §三 | design_tech_plan / breakdown_tasks 实现的依赖 |
| **路径白名单**（本地只允许 `~/Documents/prodmind/.planning/`）| CTO-READ-ACCESS-SPEC.md §二·C | 安全约束 |
| **审计日志路径**：`~/.hermes/profiles/aicto/logs/read-audit.log` | CTO-READ-ACCESS-SPEC.md §七 | 部署侧 |
| **review_code 评论密度算法**（BLOCKING / NON-BLOCKING / SKIP NIT + 单 PR ≤ 5 + 单文件 ≤ 2 BLOCKING）| v0.3 Part B 能力 4 | review_code 实现的核心节制规则 |
| **design_tech_plan 内部推理链**（Read PRD → Extract → Check ADR history → Query EngineerProfile → Run feasibility matrix → Generate stack candidates → Score → Write ADR → Render 飞书 doc）| v0.3 Part B 能力 1 | design_tech_plan skill 文件骨架 |
| **军团 auto-loop.sh 收到 BLOCKING 暂停 feature 钩子** | v0.3 Part C §5 | 跨军团 hook（属于军团 workflow 改造，非 AICTO 内部）|
| **AICTO 飞书 app 的 tenant_editable 依赖**（commit `fc86969`）| CTO-READ-ACCESS-SPEC.md §二·B | 部署前确认 |

### 8.5 UX 元素

| 资产 | 来源 | 用法 |
|------|------|------|
| **项目启动飞书卡片**（含 [查看 ADR] / [加入军团群] / [暂停项目] 按钮） | v0.3 Part B 能力 0 | kickoff_project 飞书通知 |
| Hermes profile 隔离部署清单（端口 / app_id / SOUL / cron） | `CLAUDE.md` §部署 + `README.md` | profile config 模板 |

### 8.6 Phase 划分参考

| 资产 | 来源 | 用法 |
|------|------|------|
| **MVP → 成熟 4 阶段路径**（M1 = feasibility + ADR / M2 = + TechRisk / M3 = + CodeReview / M4 = + TechDebt）| v0.1 §7 + v0.2 §八 | Phase 2/3/4 演进参考（PM 派发 Phase 1 把 v0.2 的 6 能力都点亮）|
| **质量门槛（Go/No-Go）**：结构化 JSON / 0 hallucination / ADR ≥ 90% / 生产零影响 / 真实派单 ack | v0.2 §九 | Phase 1 验收 checklist |

---

## 9. 反向问题（建议指挥官汇总后通过 dispatch 反向澄清 PM）

按优先级排列：

1. **🔴 ADR 表存储位置**：v0.2 §11.3 已经结案为"放 prodmind dev.db 共享"，PM 派发 §五·风险 #2 是否表示推翻此决策另起独立 SQLite？还是只是默认沿用历史？  
   *影响：能力 0 第 4 步 ADR-0001 写入路径、能力 1 的 design_tech_plan ADR 写入、CTO-READ-ACCESS-SPEC.md §四 `_cto_own_connect()` 是否可用*

2. **🟡 BLOCKING appeal 升级阈值**：HANDOFF-TO-PM.md 建议 1 次后即升级 lead，PM 派发未明确。是否采纳"1 次"作为 Phase 1 默认值？  
   *影响：review_code 里 appeal 计数器和升级触发逻辑*

3. **🟡 design_tech_plan 的 PRD 数据源**：派发顶部给的是飞书 PRD 文档链接（`https://ucnrf25nllyh.feishu.cn/docx/ZeMedrjG1ogqhnxsxZuc5dF0nfe`），但 CTO-READ-ACCESS-SPEC.md 的 PRD 读取方案是 dev.db + 飞书 docx 双源。design_tech_plan 实现时是否需要同时支持两种来源？  
   *影响：design_tech_plan 的 input schema 是 prd_id（dev.db）+ prd_markdown（直接传文本）+ prd_doc_token（飞书 docx）三选一还是只取派发的飞书 docx 直读？*

4. **🟡 EngineerProfile 表 Phase 1 是否落地**：能力 3 `dispatch_to_legion_balanced` 需要"军团能力 × 负荷"数据。Phase 1 是否要建 EngineerProfile 表（v0.2 §6.5）？还是先用 hardcoded 的军团能力 dict + Phase 2 再落表？  
   *影响：dispatch_to_legion_balanced 的实现复杂度*

5. **🟢 Dogfood 第一个 PRD 项目**：派发顶部给的飞书 PRD 文档是"AI CTO 程小远"自身（即 Phase 1 全量任务本身），还是另有第一个真实 dogfood 项目？HANDOFF-TO-PM.md 把这个挂为 PM 决策项。  
   *影响：能力 0/1 的端到端验收用例选哪个*

6. **🟢 跨项目技术债盘点**：v0.1 §10.5 起 open，PM 派发不含 `analyze_technical_debt` 能力。Phase 1 不实现可否，挂 Phase 2+？  
   *影响：仅 Phase 范围确认*

7. **🟢 飞书机器人在哪些工作群可见**：HANDOFF-TO-PM.md 提到 lead 需手工把 AICTO app 加进至少 1 个群。Phase 1 部署前是否已有可发消息的目标群？  
   *影响：daily_brief 和 escalate 的目标群配置*

---

## 10. 侦察结论（一句话）

**Phase 1 的产品-技术骨架在 v0.2/v0.3 早就铺好了**：6 能力的 schema、10 项审查清单、4 级失败分类、PM-CTO 边界、`mode=ro` 读权限、5 张自有表 schema、反幻觉纪律、飞书卡片 UX、appeal 通道全部可直接搬用。PM 派发主要做了**命名收口**（v0.1 八工具 → v0.2 六能力的命名替换）+ **优先级压缩**（一次点亮全 6 能力，Day-1 启用 BLOCKING 硬 gate）。**真正需要 PM 仲裁的只有 4 个冲突点**（7-A / 7-B / 7-C / 7-D），其余基本是落地动作（改 SOUL / 改 plugin.yaml / 改 system_prompt）。

---

**侦察完成 / scout-history / 2026-04-25**
