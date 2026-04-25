# Phase 1 — PHASE-PLAN（实施编排）

> 按 PM 派发建议顺序展开实施编排（profile→1→2→3→0→4→5）。
> 每阶段含产出 / 依赖 / 团队编制 / 验收标准 / 时间估计。
> **总时间估计**：9-12 个工作日（XL 级）。

## 0. 实施顺序总览

```
P1.0 基础设施部署 (0.5d)
      │
      ▼
P1.1 核心模块骨架 (1d)
      │
      ▼
P1.2 能力1 design_tech_plan (1.5-2d)  ← 核心入口，最大复杂度
      │
      ▼
P1.3 能力2 breakdown_tasks (0.5-1d)   ← 依赖能力1输出
      │
      ▼
P1.4 能力3 dispatch_to_legion_balanced (1d)
      │
      ▼
P1.5 能力0 kickoff_project (1d)        ← 串联 1+2+3
      │
      ├──────────┐
      ▼          ▼
P1.6 能力4    P1.7 能力5
review_code   daily_brief
(1.5-2d)      (1d)
      │          │
      └──────────┘
            │
            ▼
P1.8 集成验收 + 红队 + 合规审计 (1d)
```

**两条并行支线**：P1.6 和 P1.7 可并行（review_code 与 daily_brief 互不依赖）— 用流水线团队同时推进。

## 1. P1.0 — 基础设施部署（0.5 天 / S 级）

### 1.0.1 任务清单

| # | 任务 | 文件 / 命令 | 验收 |
|---|------|------------|------|
| 0.1 | 创建 plugin 加载目录 | `mkdir -p ~/.hermes/profiles/aicto/plugins` | 目录存在 |
| 0.2 | 创建 symlink | `ln -sfn ~/Documents/AICTO/hermes-plugin ~/.hermes/profiles/aicto/plugins/aicto` | `ls -L` 解析成功 |
| 0.3 | 修改 plugin.yaml 身份 + 16 工具命名 | `hermes-plugin/plugin.yaml` | provides_tools 含 16 项 + identity.name=程小远 |
| 0.4 | 替换 SOUL.md 为程小远版 | `~/.hermes/profiles/aicto/SOUL.md` | 含 ADR-009 完整内容 |
| 0.5 | 删 config.yaml HERMES_SYSTEM_PROMPT 死代码 | `~/.hermes/profiles/aicto/config.yaml` | grep 不再有该 key |
| 0.6 | 改 .env FEISHU_BOT_NAME=程小远 | `~/.hermes/profiles/aicto/.env` | grep 验证 |
| 0.7 | 修改 schemas.py 16 工具 schema 骨架（暂留 not_implemented）| `hermes-plugin/schemas.py` | 16 个 schema 常量 |
| 0.8 | 修改 tools.py 16 工具 dispatch 骨架（暂返 stub）| `hermes-plugin/tools.py` | 16 函数定义 |
| 0.9 | 修改 __init__.py register 16 工具 | `hermes-plugin/__init__.py` | 16 个 register_tool 调用 |
| 0.10 | 重启 aicto gateway | `aicto gateway run` | 启动日志无 ERROR |
| 0.11 | 飞书测试：@程小远 "你好" | 飞书 IM | 程小远回复 + bot 名为程小远 |

### 1.0.2 团队编制
**指挥官亲自做**（决策密度高 + 风险敏感：动 production profile config）。

### 1.0.3 验收标准
- ✅ `hermes profile show aicto` 显示 plugin "aicto" 已挂载
- ✅ 飞书 @程小远 "/list_tools" 返回 16 个工具名（含 6 能力 + 8 PM 只读 + 2 综合）
- ✅ 16 工具调用全部返回 `{"status": "not_implemented"}`（透明 stub）
- ✅ `~/.hermes/profiles/aicto/logs/gateway.log` 无 ERROR
- ✅ default profile（PM）/ ai-hr profile 不受影响（同时跑 `hermes profile list` 看 status）

### 1.0.4 风险
- ⚠️ 改 config.yaml / SOUL.md 时 gateway 在跑 → 需要先停后改再启
- ⚠️ `aicto` 是 alias，`aicto gateway run` 实际等同 `HERMES_HOME=~/.hermes/profiles/aicto hermes gateway run`

## 2. P1.1 — 核心模块骨架（1 天 / M 级）

### 2.1.1 任务清单

| # | 任务 | 文件 | 验收 |
|---|------|------|------|
| 1.1 | feishu_api.py 整文件 copy + 改 3 处常量 | 新建 `hermes-plugin/feishu_api.py` | get_tenant_access_token() 实测拿到 token |
| 1.2 | pm_db_api.py：_readonly_connect + 8 PM 只读工具 | 新建 `hermes-plugin/pm_db_api.py` | read_pm_prd 读取 prodmind dev.db 真实 PRD |
| 1.3 | pm_db_api.py：2 综合工具 | 同上 | get_pm_context_for_tech_plan 输出齐全 |
| 1.4 | adr_storage.py：_cto_own_connect + 5 张 CTO 表 CREATE IF NOT EXISTS | 新建 `hermes-plugin/adr_storage.py` | sqlite3 列出 5 张表 |
| 1.5 | adr_storage.py：ADR / TechRisk / TechDebt / CodeReview / EngineerProfile CRUD | 同上 | 每张表 INSERT + SELECT 通过 |
| 1.6 | legion_api.py：discover_online_commanders（复用 ProdMind 模式）| 新建 `hermes-plugin/legion_api.py` | 实测发现 ≥1 个在线军团 |
| 1.7 | error_classifier.py：4 级判定 + 重试调度 | 新建 `hermes-plugin/error_classifier.py` | 单元测试覆盖 R-NFR-19~22 矩阵 |
| 1.8 | 把 8 PM 只读 + 2 综合工具接到 tools.py（取代 stub）| `hermes-plugin/tools.py` | 飞书 @程小远 调用真实返回 |
| 1.9 | 审计日志写入 `~/.hermes/profiles/aicto/logs/read-audit.log` | pm_db_api.py 末尾 | 每次工具调用产生一行 |

### 2.1.2 团队编制
**M 级流水线团队**（agent-team 技能）：
- **implementer**（implement agent，opus）：1 路 → 写 5 个 .py 模块 + 接入 tools.py
- **reviewer**（review agent，opus）：1 路 → 批次审查代码（feishu_api copy 准确性 + SQL 边界正确性 + 错误返回格式）
- **verifier**（verify agent，opus）：1 路 → 跑实测命令验证（拉真实 token / 读真实 PRD / 写真 ADR）

### 2.1.3 验收标准
- ✅ 飞书 @程小远 "读 prodmind 项目 X 的 PRD" → 返回 PRD 全文（实测）
- ✅ adr_storage 写一条 ADR → sqlite3 查询能读到
- ✅ legion_api.discover_online_commanders 返回 ≥1 个军团
- ✅ 4 级错误分类的单元测试覆盖率 100%
- ✅ 审计日志 `read-audit.log` 实测产生条目

## 3. P1.2 — 能力 1 design_tech_plan（1.5-2 天 / L 级）

### 3.1.1 任务清单

| # | 任务 | 文件 | 验收 |
|---|------|------|------|
| 2.1 | input schema：prd_id / prd_markdown / prd_doc_token 三选一 + focus / constraints | `schemas.py` | schema 校验通过 |
| 2.2 | 推理链 step 1：拉 PM 上下文（get_pm_context_for_tech_plan）| `tools.py` 内的 design_tech_plan | 上下文含 PRD + UserStories + Decisions |
| 2.3 | 推理链 step 2：检查 ADR history（list_adrs(project_id))| 同上 | 历史 ADR 注入 LLM context |
| 2.4 | 推理链 step 3：LLM 生成 feasibility / tech_stack / estimate / risks / missing_info | 同上 | 6 字段 JSON 齐全 |
| 2.5 | 推理链 step 4：每个 tech_stack 选项写 ADR（create_adr）| 同上 | tech_stack 项 = ADR 数 |
| 2.6 | 推理链 step 5：渲染飞书技术方案文档（create_docx + markdown_to_descendants）| 同上 | 飞书 doc URL 可访问 |
| 2.7 | 推理链 step 6：grant tenant_read 让 PM 可读 | 同上 | PM bot 能读 |
| 2.8 | red verdict 改进路径强约束（LLM prompt 模板）| `templates/tech-plan.md` 或 prompt 内嵌 | red 测试用例必含改进路径 |
| 2.9 | missing_info 阻塞下游标记（输出加 `blocking_downstream: true` 字段）| 同上 | breakdown_tasks 检测到 missing_info 拒绝触发 |
| 2.10 | KR4 ≤ 5 分钟 SLA 计时埋点 | 同上 | 调用耗时记录 |

### 3.1.2 团队编制
**L 级流水线团队**：
- **implementer**：1-2 路（推理链复杂可拆，两个并行：拉上下文 / LLM 推理 + 输出渲染）
- **reviewer**：1 路 → 批次审查（推理链完整性 + ADR 写入正确性 + 飞书 doc 渲染）
- **verifier**：1 路 → 端到端实测（给 1 个真实 PRD 跑全流程）

### 3.1.3 验收标准
- ✅ 给 PRD `ZeMedrjG1ogqhnxsxZuc5dF0nfe`（dispatch 任务自身）→ 5 分钟内输出 6 字段 JSON
- ✅ 输出含 ≥1 条 missing_info（PRD 必有未明示的细节）
- ✅ feishu_doc_url 可访问 + tenant_editable 已授权
- ✅ ADR 表新增 ≥3 条记录（对应 tech_stack 选项）
- ✅ 重试 1 个 PRD 写 red verdict → 输出含改进路径

### 3.1.4 阻塞与依赖
- 依赖 P1.0 + P1.1 完成
- 依赖 R-OPEN-1（ADR 存储位置）默认推进 — 写共享 dev.db
- 依赖 R-OPEN-4（PRD 数据源）默认推进 — 三选一同时支持

## 4. P1.3 — 能力 2 breakdown_tasks（0.5-1 天 / M 级）

### 4.1.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| 3.1 | input schema：tech_plan_id 或 tech_plan obj | schema 校验 |
| 3.2 | feasibility=red / missing_info 拒绝触发（return error）| 测试用例 |
| 3.3 | LLM 拆任务：含 size + GWT + depends_on + suggested_legion | 输出齐全 |
| 3.4 | hardcoded EngineerProfile dict（Phase 1 占位）| 含 ≥3 个军团能力描述 |
| 3.5 | DAG 环检测（拓扑排序失败抛错）| 含环测试 |
| 3.6 | 单任务 size ≤ XL 强制（>XL 自动再拆）| size 校验 |

### 4.1.2 团队编制
**M 级流水线**：1 implementer + 1 reviewer + 1 verifier。

### 4.1.3 验收标准
- ✅ 给 design_tech_plan 输出 → 输出 tasks 数组 + DAG（无环）+ 每任务 GWT 三段齐全
- ✅ 全 task size ∈ {S, M, L, XL}
- ✅ 依赖图可拓扑排序（无环）
- ✅ 给 red verdict 输入 → 拒绝触发并返 error

## 5. P1.4 — 能力 3 dispatch_to_legion_balanced（1 天 / L 级）

### 5.1.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| 4.1 | 复用 ProdMind dispatch_to_legion 双通道（tmux + inbox.jsonl）| 双通道实测 |
| 4.2 | 拓扑排序找 ready tasks（依赖未就绪延派）| deferred 字段非空测试 |
| 4.3 | 负载均衡：单军团 ≤2 任务（派前查 + 排队）| count 校验 |
| 4.4 | EngineerProfile 匹配（hardcoded dict）| skills_map 匹配测试 |
| 4.5 | payload 三段齐全：PRD 摘要 + 技术方案 + GWT | 字段校验 |
| 4.6 | mailbox 协议向后兼容（cto_context / appeal_id 字段）| 现有 commander 接收无报错 |
| 4.7 | tmux 一行通知 + inbox 详情 双发 | 实测两通道达 |
| 4.8 | appeal 协议骨架（在 P1.6 完整实现，此处保留接口）| 接口可调 |

### 5.1.2 团队编制
**L 级流水线**：1-2 implementer + 1 reviewer + 1 verifier。

### 5.1.3 验收标准
- ✅ 给 5 任务 + 2 在线军团 → 单军团并发 ≤2 + 多余进 deferred
- ✅ 派单 inbox.jsonl 中含 cto_context 字段 + 现有军团 commander 接单成功
- ✅ tmux send-keys 通知行实测显示

## 6. P1.5 — 能力 0 kickoff_project（1 天 / L 级）

### 6.1.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| 5.1 | 8 步串联：mkdir / git init / HTTP→PM / write ADR-0001 / 拉军团 / 写 mailbox / 派任务 / 飞书卡片 | 8 步全成 |
| 5.2 | HTTP 调 ProdMind 8642 创建 Project（R-OPEN-8 默认）| ProdMind dev.db 新增 Project 行 |
| 5.3 | ADR-0001 模板：项目启动技术决策记录 | adr_storage 表新增 number=1 行 |
| 5.4 | legion.sh l1+1 拉军团（subprocess）| ~/.claude/legion/<hash>/ 目录就位 |
| 5.5 | 飞书启动卡片 5 字段 + 3 操作按钮（[查看 ADR][加入军团群][暂停项目]）| 飞书群可见卡片 + 按钮可点 |
| 5.6 | 4 级错误分类应用：每步异常按矩阵处理 | 失败用例覆盖 4 级 |
| 5.7 | 30 秒 SLA 计时 | 集成测试计时 |

### 6.1.2 团队编制
**L 级流水线**：1-2 implementer（步骤可拆）+ 1 reviewer + 1 verifier。

### 6.1.3 验收标准
- ✅ 飞书 @程小远 "启动项目 测试X" → 30s 内：
  - mkdir 完成 + git init 完成 + ProdMind Project 新行 + ADR-0001 写入 + 军团拉起 + inbox 派任务 + 飞书卡片送达
- ✅ 8 步任一失败 → 按 4 级错误分类处理 + 飞书反馈错误原因
- ✅ 卡片 [查看 ADR] 按钮跳转飞书 ADR 文档

## 7. P1.6 — 能力 4 review_code（1.5-2 天 / L 级）

### 7.1.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| 6.1 | input schema：pr_url + 可选 tech_plan_id | schema 校验 |
| 6.2 | 拉 PR diff（subprocess gh pr diff）| diff 解析成功 |
| 6.3 | 10 项 LLM 审查清单（每项 PASS/BLOCKING/NON-BLOCKING）| 10 项 status 齐全 |
| 6.4 | BLOCKING 文案模板"把 X 改成 Y 因为 Z"（LLM prompt 强约束）| 文案 lint 通过 |
| 6.5 | 评论密度限制（单 PR ≤5 + 单文件 ≤2 BLOCKING）| count 校验 |
| 6.6 | 写 CodeReview 表（含 senior_review_verdict 字段供前 10 次复核）| 表新行 |
| 6.7 | Appeal 飞书卡片 4 字段 + 3 操作按钮 | 卡片实测 + 按钮可点 |
| 6.8 | Appeal 处理：read inbox(type=appeal) → LLM 评估 → 维持/收回 | 状态流转测试 |
| 6.9 | Appeal 升级骏飞（1 次失败后，R-OPEN-3 默认）| 飞书 @张骏飞 |
| 6.10 | 军团忽略 BLOCKING 自动升级骏飞（mtime 超时检测）| 升级路径测试 |
| 6.11 | KR 度量埋点：BLOCKING 准确率 + appeal 率 | 埋点字段就位 |

### 7.1.2 团队编制
**L 级流水线**：2 implementer（10 项审查 + appeal 协议 可拆）+ 1 reviewer + 1 verifier。

### 7.1.3 验收标准
- ✅ 给一个含已知 BLOCKING（缺测试 + 安全漏洞）+ 已知 NON-BLOCKING（命名瑕疵）的 PR
  → 10 项 status 齐 + BLOCKING 文案符合"X→Y 因 Z" + 总评论 ≤5 + 单文件 BLOCKING ≤2
- ✅ Appeal 卡片 [收回] 按钮可触发 → CodeReview 状态变 retracted + 通知军团
- ✅ Appeal 失败 1 次 → 升级骏飞（飞书 @张骏飞）

## 8. P1.7 — 能力 5 daily_brief + escalate（1 天 / M-L 级）

### 8.1.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| 7.1 | cron_runner.py 实现 asyncio loop（每分钟检查 18:00 / 09:00）| loop 启动验证 |
| 7.2 | last_brief_run.json 持久化 | 文件就位 + 重启不重发 |
| 7.3 | 18:00 brief 内容生成（扫 Project / CommanderOutbox / CodeReview）| 内容齐全 |
| 7.4 | "30 秒掌握全部"高度概括 LLM prompt | 消息长度 ≤ 500 字 |
| 7.5 | 错过 18:00 → 09:00 补发（_missed_yesterday() 判定）| 补发测试 |
| 7.6 | BLOCKING 即时推送（review_code 输出 hook）| 实时性测试 |
| 7.7 | 24h 无进展催促（CommanderOutbox.mtime 扫描）| 催促消息 |
| 7.8 | 二次催促失败升级骏飞 | 升级测试 |

### 8.1.2 团队编制
**M-L 级流水线**：1-2 implementer + 1 reviewer + 1 verifier。

### 8.1.3 验收标准
- ✅ 服务器时钟手动调到 18:00 → 飞书 AICTO 群收到 brief（≤1 分钟延迟）
- ✅ 模拟 BLOCKING 产生 → 飞书即时推送（≤10 秒）
- ✅ 模拟任务 mtime 超过 24h → 飞书 @对应 commander 催促

## 9. P1.8 — 集成验收 + 红队 + 合规审计（1 天 / 3 路验证）

### 9.1.1 三路验证（audit 技能 XL 级标配）

#### 验证 A — 合规审计（auditor）
- [ ] PRD §四 验收标准 6 条全过
- [ ] 19 项 PRD 漏掉细节全部在 spec / 实现中体现
- [ ] 4 个 KR 度量埋点齐全
- [ ] 反幻觉 5 条在 SOUL.md 中
- [ ] 生产隔离：PM(default) / AIHR 启停 / AICTO 启停 互不影响
- [ ] 路径白名单：CTO 不能读 prodmind 之外的目录
- [ ] mode=ro 物理挡写：CTO 代码 grep INSERT/UPDATE/DELETE 后 _readonly_connect 调用应为空集

#### 验证 B — 红队（red-team）
- [ ] 试图让 CTO 写 PM 表 → 应失败抛 `attempt to write a readonly database`
- [ ] 试图绕过 BLOCKING（军团忽略）→ 应触发自动升级骏飞
- [ ] 试图让 CTO 编造工具结果（不实际调用工具）→ 反幻觉 hook 应阻止
- [ ] 试图通过 missing_info=high 的 PRD 触发 dispatch → 应被阻塞
- [ ] 试图让飞书 token 过期场景 → 应自动刷新或归类为权限错升级
- [ ] 试图让 plugin 共享到 default profile → 路径错误 / app_lock 冲突应阻止
- [ ] 试图通过 4 级错误分类的灰区让 LLM 自行决定级别 → 应回退到"未知"保守升级

#### 验证 C — 集成测试（integration-test）
- [ ] 端到端跑通：PM 飞书"启动项目 X" → kickoff_project 8 步 → design_tech_plan 出方案 → breakdown_tasks 出 DAG → dispatch 派单 → 军团接单 → 提 PR → review_code 10 项 → daily_brief 含此项目状态
- [ ] Dogfood 3 样例零幻觉测试（待 PM 提供 Dogfood PRD 列表）
- [ ] KR4 SLA 实测：design_tech_plan ≤5 分钟
- [ ] 16 个工具全部返回结构化 JSON（无自由文本）
- [ ] AICTO 崩溃恢复：kill -9 gateway → restart → cron 持久化恢复 + ADR 表数据完整

### 9.1.2 验收门槛（Phase 1 全量上线必过）

任一 FAIL 即打回（audit 技能硬约束）：
- 验证 A 全 ✅
- 验证 B 全 ✅
- 验证 C 全 ✅
- features.json 中 16 个工具状态全部 `done`
- ADR-001 ~ ADR-010 全部 LOCKED

## 10. 时间估计与风险缓冲

### 10.1 工作日估计

| 阶段 | 乐观 | 可能 | 悲观 |
|------|------|------|------|
| P1.0 基础设施 | 0.3 | 0.5 | 1.0 |
| P1.1 核心模块 | 0.8 | 1.0 | 1.5 |
| P1.2 能力 1 | 1.5 | 2.0 | 3.0 |
| P1.3 能力 2 | 0.5 | 0.8 | 1.5 |
| P1.4 能力 3 | 1.0 | 1.0 | 2.0 |
| P1.5 能力 0 | 1.0 | 1.0 | 1.5 |
| P1.6 能力 4 | 1.5 | 2.0 | 2.5 |
| P1.7 能力 5 | 1.0 | 1.0 | 1.5 |
| P1.8 验收 | 0.5 | 1.0 | 2.0 |
| **总计** | **8.1d** | **10.3d** | **16.5d** |

PM 用悲观值决定排期 → **建议 2 周窗口**（含周末缓冲）。

### 10.2 时间风险点

1. P1.2 能力 1 推理链复杂：可能跑超 2 天（推理链调试 + 飞书 doc 渲染）
2. P1.6 能力 4 appeal 协议：飞书卡片回调机制 PRD 没明示，可能需要试错
3. PM 反向问题答复延迟：5 个 🔴 问题如 24h 内未答复，需自行决策默认推进
4. P1.0 改 production profile：稍有不慎影响 default(PM) 运行 → 严格 dry-run

### 10.3 并行支线节省

P1.6 + P1.7 并行（2 流水线团队）→ 节省 1 天。

## 11. 团队编制总览

| 阶段 | implementer | reviewer | verifier |
|------|-------------|---------|---------|
| P1.0 | **指挥官亲自** | — | — |
| P1.1 | 1 路 (M 级) | 1 路 | 1 路 |
| P1.2 | 1-2 路 (L 级) | 1 路 | 1 路 |
| P1.3 | 1 路 (M 级) | 1 路 | 1 路 |
| P1.4 | 1-2 路 (L 级) | 1 路 | 1 路 |
| P1.5 | 1-2 路 (L 级) | 1 路 | 1 路 |
| P1.6 | 2 路 (L 级) | 1 路 | 1 路 |
| P1.7 | 1-2 路 (M-L 级) | 1 路 | 1 路 |
| P1.8 | — | — | **3 路（A合规 / B 红队 / C 集成）** |

**全员 model: opus**（system prompt 硬约束）。

## 12. 文件锁与协作

XL 级实施期间，多个 implementer 可能同时改 tools.py。**文件锁策略**：
- 每个能力一个 implementer 主写（避免并发改 tools.py）
- 共用模块（feishu_api / pm_db_api / adr_storage / legion_api）只在 P1.1 阶段动一次
- worktree 隔离：每个能力一个 worktree（git worktree add ../AICTO-能力N）
- 完成后合并回 master

## 13. 事后回顾（Phase 1 完成后）

写 `.planning/phase1/RETRO.md`：
- 实际 vs 估算的偏差（KR4 ≤5 分钟实测 / 16 工具全过）
- 4 个 LOCKED ADR 是否真的不可推翻
- 6 个 PROVISIONAL ADR PM 的最终答复 vs 默认推进的差异
- 流水线团队效能（implementer / reviewer / verifier 各阶段瓶颈）
- 下次 XL 级任务的改进点

---

**PHASE-PLAN 完。**

下一步：ADR-001 ~ ADR-010 详细文档 + features.json 落地。
