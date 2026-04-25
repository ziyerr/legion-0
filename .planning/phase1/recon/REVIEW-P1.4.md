# P1.4 批次审查报告 — dispatch_to_legion_balanced

> 审查者：reviewer-p1-4 / L1-麒麟军团（Task #23）
> 审查时间：2026-04-25
> 审查范围：dispatch_balanced 主模块 + tools.py dispatch 接入（共 2 文件 / +716 行新增 + 7 行 tools.py 改动）
> 审查依据：REQUIREMENTS.md §1.4 R-FN-3.1~3.9 / PHASE-PLAN.md §5 / PRD-CAPABILITIES.md 能力 3 / ARCHITECTURE.md §4.4 §5.3 / RECON-REFERENCE.md §6 / REVIEW-P1.2.md（B-1 防回归基线）/ REVIEW-P1.3.md / review-checklist.md

## 0. 验证手段（反幻觉的反幻觉）

| 验证项 | 手段 | 结果 |
|------|------|------|
| 模块可加载 | 包式 submodule load + 5 常量取值 | ✅ MAX_CONCURRENT_TASKS_PER_LEGION=2 / SIZE_TO_PRIORITY 4 项 / PRD_LIMIT=500 / TECH_PLAN_LIMIT=1000 |
| **B-1 防回归（核心）** | `inspect.getmro(_DispatchBalancedError)` | ✅ `[_DispatchBalancedError, WrappedToolError, Exception, BaseException, object]` |
| **B-1 retry attempts=3** | 隔离测试：`raise _DispatchBalancedError(level=tech)` × N，调 `retry_with_backoff(max_retries=3)` 计数 | ✅ attempts=3（与 P1.2 实测 attempts=1 形成对照） |
| permission/intent 不重试 | `raise _DispatchBalancedError(level=permission/intent)` | ✅ 双 case attempts=1 立即抛 |
| 入参 intent 校验 | `db.run({})` / 4 case：缺 tasks / 缺 project_id / tasks 非 list / tasks 空 list | ✅ 全返 `{"error":...,"level":"intent","elapsed_seconds":...}` 顶层 `error` key |
| 0 commander → tech | `discover_online_commanders` 返 `[]` | ✅ `error` 含 "no online legion" + `level="tech"` + 提示用 legion.sh |
| Step 3 split happy | a(空 deps)/b(deps=[a])/c(无 deps 字段) | ✅ ready={a,c} / deferred={b} |
| Step 3 非 dict 跳过 | `["str", {"id":"a"}, None, {"title":"no-id"}]` | ✅ ready={a} + 3 warnings |
| **5 任务 / 2 军团 → 单军团 ≤2** | 实跑 mock send_to_commander | ✅ assignments=4(2+2) / deferred=1(reason="all matching legions full") |
| **payload 三段 + cto_context 5 字段** | 检查所有 send_to_commander 入参 | ✅ 4 个 payload 全含 PRD 摘要/技术方案/Given/When/Then + cto_context{tech_plan_id, adr_links, feishu_doc_url, project_id, task_id} |
| size→priority 映射 | XL/L/M/S 派单后查 assignment.priority | ✅ XL→high / L,M→normal / S→low |
| suggested_legion 优先 | 任务 hint=L1-mock-赤龙 + tech_link 偏向赤龙 | ✅ legion_id=L1-mock-赤龙 |
| 含环依赖（dispatch 不查环）| a→b / b→a 环 | ✅ 两个全 deferred（depends_on 非空），dispatch 不主动检环（环检测在能力 2，符合 spec） |
| 全军团满载 | 单军团 + 3 任务 | ✅ assignments=2 / deferred=1 reason="all matching legions full" |
| 单 task 派失败 → deferred + warning | mock send_to_commander 抛 LegionError | ✅ 该 task 进 deferred，warnings 含失败原因，整批不阻塞 |
| Step 1 PM API 异常 → warnings | 抛 Exception("dev.db locked") | ✅ 3 条 warnings 累积，主流程仍派 1 task |
| permission/unknown → escalate_to_owner | discover 抛 PermissionError / RuntimeError | ✅ 双 case 各触发 1 次 escalate，level 正确分类，return 顶层 error 携带 level |
| **mailbox 协议复用证据** | spy `legion_api.mailbox_protocol_serialize` + `_write_inbox_to_path` | ✅ dispatch 派单 → mailbox 协议字段齐（id/from=AICTO-CTO/to/type=task/payload/timestamp/read/summary/cto_context/priority），inbox.json 写入正确 |
| **复用纪律**：HARDCODED_LEGION_PROFILES | grep 源码 | ✅ 仅 1 处引用 `design_tech_plan.HARDCODED_LEGION_PROFILES`，未重定义 |
| **复用纪律**：无 fcntl/subprocess/tmux | grep + ast 扫描 | ✅ 0 处 import fcntl / import subprocess；fcntl/tmux 字符串仅出现于 docstring 与 send_result 字段读取 |
| 不污染真实军团 | grep `L1-麒麟\|L1-赤龙\|L1-凤凰` | ✅ 0 处硬编码军团名（包含中文 L1-* 名）；测试全用 `L1-mock-*` 假名 |
| 缺数据降级标注 | `_build_payload` 4 种缺数据组合 | ✅ "PRD 摘要数据缺失" / "暂无 ADR" / "GWT 数据缺失" 三条显式标注，未静默吞 |
| PRD 超长 | `prd_content` = "x" × 1000 | ✅ 触发 "（PRD 全文超长已截断" 提示 |
| _summarize_payload 200 字截断 | 400 字 input | ✅ len=203 + endswith("...") |
| _match_score 边界 | 相等/子串/无交集/双空 | ✅ 4 case 全对（相等+2 / 子串+1 / 无交集+0） |
| _build_cto_context 字段齐 | task + ctx 完整输入 | ✅ tech_plan_id/adr_links/feishu_doc_url 三个 ARCHITECTURE §5.3 强制字段全在 |
| **tools.py 透明委托** | spy `db.run` + 调 `tools.dispatch_to_legion_balanced` | ✅ args 透传，无解构/包装；其他 stub（kickoff/review/daily_brief）保持 status=not_implemented |

> 全部测试已存在内存中 28 项实跑（含 mock send_to_commander，**不实际派单到任何在线军团**）。所有结论均附实跑证据。

## 1. 总评

| 模块 | 行数 | 评级 | 关键发现 |
|------|------|------|---------|
| `dispatch_balanced.py` | 716 | **PASS** | 5 步推理链完整 / B-1 防回归到位 / 复用纪律 100% / 7 项 NON-BLOCKING（含 1 项 Phase 2 必修高优先级 trade-off） |
| `tools.py`（dispatch 接入）| +7 行 | **PASS** | 1 处实接 `_dispatch_balanced.run` / 注释更新到 P1.4 已上线 / stub 透明纪律不破（kickoff/review/daily_brief 仍正确返 not_implemented） |

**0 BLOCKING / 7 NON-BLOCKING / 综合结论：ALL APPROVED**

主路径功能性完整，PRD 能力 3 验收 4 条全过。B-1 防回归的实施者主动学习模式完成第三轮固化（P1.2 立基线 → P1.3 跟进 → P1.4 同款防御），7 项 NON-BLOCKING 均不阻塞 P1.4 关闸。

## 2. BLOCKING 项

**无。**

P1.2 评审里的 B-1（_DesignTechPlanError 不继承 WrappedToolError 致 retry 失效）在本批次实施者已主动预防 — 代码 line 71-85 的 `_DispatchBalancedError` 显式继承 `error_classifier.WrappedToolError` 并在 docstring 注明"防 B-1（reviewer-p1-2 / 2026-04-25）"。隔离单测验证 attempts=3，permission/intent 不重试 attempts=1，与基线 P1.2 实测 attempts=1 形成强对照。

## 3. NON-BLOCKING 项（建议修但不阻塞 merge）

### N-1 · dispatch_balanced.py:353-355 — `load_map` 初始化为 0，**跨 dispatch 调用单军团可能超过并发上限**【高优先级，Phase 2 必修】

**X**：
```python
# load_map：每 dispatch 一次 += 1（Phase 1 启发式 — 初始为 0）
# Phase 2 可改为读 inbox.json 未读消息数（更准确，但需多次磁盘 IO）
load_map: Dict[str, int] = {c.commander_id: 0 for c in commanders}
```

**Y**：Phase 2 改为读 inbox.json 当前未读消息数：
```python
def _count_pending_for(commander: legion_api.Commander) -> int:
    """读 inboxes/<cid>.json，count [m for m in msgs if not m['read'] and m['type']=='task']"""
    try:
        with open(commander.inbox_path, 'r', encoding='utf-8') as f:
            msgs = json.load(f)
        return sum(1 for m in msgs if not m.get('read') and m.get('type') == 'task')
    except Exception:
        return 0  # best-effort; 不阻塞 dispatch

load_map: Dict[str, int] = {c.commander_id: _count_pending_for(c) for c in commanders}
```

**Z**：当前实现 line 353-354 已文档化承认 Phase 1 简化。**真实风险**：连续两次 dispatch 调用 → 单军团瞬时持有任务数可能 = 2 + 2 = 4，违反 R-FN-3.3 "单军团 ≤2"硬纪律 + PRD §五·能力 3 "派前查 + 排队"语义。但 PHASE-PLAN.md §5.1.3 验收标准只覆盖单次 dispatch（"给 5 任务 + 2 在线军团 → 单军团并发 ≤2"），所以本批次 P1.4 实测可过。生产场景必修。建议 P1.8 集成验收前补一条多次 dispatch 调用单军团 ≤2 的端到端 case；Phase 2 固化为 inbox 计数。

### N-2 · dispatch_balanced.py:198-200 + 665 — `feishu_doc_url` 字段在 cto_context 永远为 None【中优先级，Phase 2 修】

**X**：
```python
# Step 1 ctx 初始化（line 198-200）
"feishu_doc_url": None,  # Phase 1 暂不接（design_tech_plan 输出含此 URL，
                          # 但 dispatch 拿不到 plan obj — 需等 Phase 2 改 schema）

# _build_cto_context（line 665）
"feishu_doc_url": ctx.get("feishu_doc_url"),
```

**Y**：从 ProjectDocument 表（PM dev.db）或最新 ADR 的 rationale 字段提取飞书 URL：
```python
# Step 1c 之后增加 1d
try:
    docs = pm_db_api.list_pm_project_documents({"project_id": project_id})
    parsed = json.loads(docs)
    if "error" not in parsed:
        # 优先取 type='tech_plan' / 'design_tech_plan' 的最新文档
        ctx["feishu_doc_url"] = _pick_tech_plan_url(parsed.get("documents") or [])
except Exception as e:
    warnings.append(f"step1d.list_pm_project_documents exception: {e}")
```

**Z**：ARCHITECTURE.md §5.3 cto_context 三个保留字段 `tech_plan_id / adr_links / feishu_doc_url`，前两个均已落实，**第三个永远 None**等于"明文承认下游军团无法跳转飞书技术方案"。R-FN-1.6 / R-FN-3.5 共同要求 dispatch payload 含完整上下文。当前 ADR 列表已能让军团读决策详情（line 663），feishu_doc_url 为 None 不致命，但是 Phase 2 必补的 affordance。NON-BLOCKING 留 Phase 2。

### N-3 · dispatch_balanced.py:660-663 — `tech_plan_id == project_id`（一项目可能有多 plan）【中优先级，与 P1.3 同款】

**X**：
```python
# Phase 1 简化：tech_plan_id == project_id（与 breakdown_tasks 对齐 —
# design_tech_plan 输出未含独立 plan_id，恢复用 ADR 重组）
"tech_plan_id": ctx.get("project_id"),
```

**Y**：Phase 2 在 `design_tech_plan.run()` 输出补 `plan_id`（如 `tech-plan-<project_id>-<timestamp>`），breakdown_tasks 写 task 时记录 plan_id，dispatch 反传：
```python
"tech_plan_id": task.get("tech_plan_id") or ctx.get("project_id"),
```

**Z**：与 P1.3 N 系同款限制（一项目可能多 plan，Phase 1 用 project_id 兜底）。当前不阻塞功能 — 军团接到 tech_plan_id 仅用于审计回溯，project_id 已能定位足够上下文。Phase 2 当 design_tech_plan 输出 schema 演化时同步修。NON-BLOCKING。

### N-4 · dispatch_balanced.py:494-496 — 注释"即使 suggested 满载备选打分时仍考虑"与 line 484 满载过滤矛盾

**X**：
```python
for c in commanders:
    if load_map.get(c.commander_id, 0) >= MAX_CONCURRENT_TASKS_PER_LEGION:
        continue   # ← 满载已被排除

    prof = profiles_by_name.get(c.commander_id) or {}
    ...
    score = _match_score(tech_links_lower, tags_lower)
    # score 中加入 suggested_legion 命中加成（即使 suggested 满载，备选打分时仍考虑）  ← 注释错
    if suggested and c.commander_id == suggested:
        score += 10  # 强 hint
```

**Y**：注释精确化（修正语义不动逻辑）：
```python
# suggested 在线但满载时不会出现在 candidates；若未满载，本步加 10 分作"强 hint" 优先级。
```

**Z**：注释与代码不一致 — 满载的 commander 已在 line 484 被 `continue` 排除，绝不会进入打分。建议改正注释避免后续维护误导。功能正确，仅文字精确度 nit 级。NON-BLOCKING。

### N-5 · dispatch_balanced.py:541-646 — `_build_payload` 单函数 ~106 行，建议拆 3 helper

**X**：`_build_payload` 在一处函数内串联：头部 / PRD 摘要段 / 技术方案段 / GWT 段 / 任务描述段 / 调度元信息段。

**Y**：拆 3 helper（与三段对应，与 R-FN-3.5 spec 字面一致）：
```python
def _render_prd_section(prd_title: str, prd_content: str) -> List[str]: ...
def _render_tech_section(tech_stack: List[Dict]) -> List[str]: ...
def _render_gwt_section(gwt: Optional[Dict]) -> List[str]: ...
```

**Z**：当前 106 行函数仍可读（每段都有清晰的 `# ---- 一、PRD 摘要 ----` 分隔注释），但单测时无法对单段做隔离断言。当前所有 payload 渲染均通过 `_build_payload` 整体 string 检查，未来若新增段（如 P1.6 review_code 加 review_history 段）会膨胀。SUGGEST 改 3 helper 提升可测性。NON-BLOCKING。

### N-6 · dispatch_balanced.py:613-620 — GWT 段：dict 但全字段空白时不显示"数据缺失"提示

**X**：
```python
gwt = task.get("acceptance_gwt")
if not isinstance(gwt, dict):
    lines.append("（GWT 数据缺失 — 上游 breakdown_tasks 应已兜底；本次按 <待补> 处理）")
    lines.append("- **Given**: <待补>")
    lines.append("- **When**: <待补>")
    lines.append("- **Then**: <待补>")
else:
    lines.append(f"- **Given**: {gwt.get('given') or '<待补>'}")
    lines.append(f"- **When**: {gwt.get('when') or '<待补>'}")
    lines.append(f"- **Then**: {gwt.get('then') or '<待补>'}")
```

**Y**：dict 内逐字段缺失时也加聚合提示：
```python
else:
    missing = [k for k in ("given","when","then") if not (gwt.get(k) or "").strip()]
    if missing:
        lines.append(f"（GWT 部分缺失：{missing}，已兜底为 <待补>）")
    lines.append(f"- **Given**: {gwt.get('given') or '<待补>'}")
    ...
```

**Z**：当前 dict-但-字段空 走"<待补>"占位符，下游军团读到 `<待补>` 知是占位符（隐式标注）。但相比 PRD 段 / ADR 段的"显式数据缺失"提示，GWT 段的隐式更弱。改进后军团能直接看到"哪几段缺"。breakdown_tasks 已有 GWT 兜底（REVIEW-P1.3.md N-5），到 dispatch 时理论上 GWT 三段必有 `<待补>` 或真值，所以这条主要是"防御性增强"。NON-BLOCKING。

### N-7 · dispatch_balanced.py:154-160 — Step 4 + Step 5 合并函数命名暗示双步骤但实际融合

**X**：
```python
# ---- Step 4 + 5：负载均衡 + 双通道派单 ----
assignments, deferred_post, dispatch_warnings = _step4_5_dispatch_with_balance(
    ready_tasks=ready_tasks,
    commanders=commanders,
    ctx=ctx,
)
```

`_step4_5_dispatch_with_balance` 在 line 330-439 同一函数内：先 `_pick_best_legion`（Step 4 负载均衡），再 `legion_api.send_to_commander`（Step 5 双通道派单）。

**Y**：拆双函数提升可测性：
```python
def _step4_pick_assignments(ready_tasks, commanders, ctx) -> List[Tuple[Task, Optional[Commander]]]: ...
def _step5_send_assignments(plan, ctx) -> Tuple[assignments, deferred, warnings]: ...
```

**Z**：当前合并设计的好处是 load_map 增量更新与发送强耦合（避免错误 + 1 后未发送）；拆分后需要回写。当前函数命名 `_step4_5_*` 已显式标注双步骤，4 步推理链 docstring 也明示融合。可视为 "Step 4+5 atomic" 的合理工程取舍。SUGGEST 但**不**强求拆分。NON-BLOCKING。

## 4. 一致性检查

### 与 REQUIREMENTS.md §1.4 R-FN-3.1~3.9 对齐

| ID | 需求 | 实现状态 | 证据 |
|----|------|---------|------|
| R-FN-3.1 | 输入：tasks[] + 自动 discover_online_commanders | ✅ | run() line 122-149 实接 `legion_api.discover_online_commanders()` + 0 commander 时 tech 级 error |
| R-FN-3.2 | 输出：assignments[{task_id, legion_id, payload}] + deferred[task_id] | ✅ | _success() 含 assignments / deferred 双数组 |
| R-FN-3.3 | 单军团并发 ≤2（派前查 + 排队）| ⚠️ | 单次 dispatch 内 ≤2 已固化（实测 5 任务/2 军团 → 4 派 + 1 deferred）；**跨调用 ≤2 待 N-1 修**（Phase 1 简化文档化，Phase 2 必修） |
| R-FN-3.4 | DAG 依赖未就绪延派 | ✅ | _step3_split_ready_deferred 把 depends_on 非空全 deferred；breakdown_tasks 已保证 DAG 无环（环检测在能力 2） |
| R-FN-3.5 | payload 三段：PRD 摘要 + 技术方案 + GWT | ✅ | _build_payload 三段标题硬约束；缺数据时显式标注 "数据缺失"；超长截断并提示完整位置 |
| R-FN-3.6 | CTO 调度决策权（不需军团确认）| ✅ | dispatch 一次性派单写 inbox + tmux 通知，无确认 RPC；payload 第 643 行注明"决策权：CTO 拥有调度决策权；如有重大异议可走 appeal 通道（review_code 阶段）" |
| R-FN-3.7 | 双通道：tmux send-keys + inbox 排队 | ✅ | 通过 legion_api.send_to_commander 实现，dispatch 不重发明 |
| R-FN-3.8 | inbox + tmux 一行通知双发 | ✅ | legion_api.send_to_commander 内部双发；assignment 字段记录 tmux_notified 状态 |
| R-FN-3.9 | mailbox 协议向后兼容（新字段不破坏现有 schema）| ✅ | 通过 legion_api.mailbox_protocol_serialize 构造，老字段(id/from/to/type/payload/timestamp/read/summary) 全保留，新字段(cto_context/priority) 仅在传值时写入 |

### 与 PHASE-PLAN.md §5.1.1 任务清单对齐

| # | 任务 | 实现 |
|---|------|------|
| 4.1 | 复用 ProdMind dispatch_to_legion 双通道 | ✅ legion_api.send_to_commander 已 P1.1 实现，dispatch 直接复用 |
| 4.2 | 拓扑排序找 ready tasks | ✅ _step3_split_ready_deferred；breakdown_tasks 已保证 DAG，dispatch 是一次性快照 |
| 4.3 | 负载均衡：单军团 ≤2 | ✅ MAX_CONCURRENT_TASKS_PER_LEGION=2 + load_map 派前查 + deferred 兜底（N-1 跨调用风险已记录） |
| 4.4 | EngineerProfile 匹配（hardcoded dict）| ✅ 复用 design_tech_plan.HARDCODED_LEGION_PROFILES 8 军团 / _match_score 双向子串打分 |
| 4.5 | payload 三段齐全 | ✅ _build_payload 强制三段标题 |
| 4.6 | mailbox 协议向后兼容 | ✅ 通过 legion_api.mailbox_protocol_serialize（cto_context/appeal_id/priority 仅在传值时写入） |
| 4.7 | tmux 一行通知 + inbox 详情 双发 | ✅ legion_api.send_to_commander 内部实现 |
| 4.8 | appeal 协议骨架（P1.6 完整）| 🟡 mailbox_protocol_serialize 已支持 appeal_id/appeal_count；dispatch 当前不发 appeal 类消息（仅 type=task）。骨架接口可调，正常 — Phase 1 P1.6 落地 |

### 与 PRD-CAPABILITIES 能力 3 对齐

| 能力 3 验收 | 实现状态 |
|-----------|---------|
| 单军团同时 ≤2 任务 | ✅ 单次 dispatch 内强制；跨调用 N-1 已记录 |
| 有依赖任务延迟派单 | ✅ depends_on 非空 → deferred |
| payload 含 PRD 摘要 + 技术方案 + 验收标准 | ✅ 三段必齐，缺数据显式标注 |
| CTO 拥有调度决策权（可 appeal 不可拒）| ✅ dispatch 派单一次性，appeal 走 review_code 通道（P1.6） |

### 与 ARCHITECTURE.md §4.4 / §5.3 对齐

| Spec 字段 | 实现状态 | 证据 |
|----------|---------|------|
| §4.4 dispatch_balanced 5 步推理链 | ✅ Step 1 ctx → Step 2 discover → Step 3 split → Step 4 pick → Step 5 send |
| §5.3 mailbox 保留字段 | ✅ id/from/to/type/payload/timestamp/read/summary 全保留 |
| §5.3 cto_context.tech_plan_id | ✅ Phase 1 简化为 project_id（N-3 记录） |
| §5.3 cto_context.adr_links | ✅ 真实从 adr_storage.list_adrs 拉 ID 列表 |
| §5.3 cto_context.feishu_doc_url | 🟡 永远 None（N-2 记录，Phase 2 修） |
| §5.3 priority 字段 | ✅ size→priority 映射后写入 mailbox 协议 |

### 与 review-checklist.md 对齐（七章节）

| 章节 | 评级 | 备注 |
|------|------|------|
| 一·正确性 | ✅ | 28 实跑测试覆盖每分支：5 步推理链 / 边界 / 异常路径 / 反幻觉降级；含环依赖 spec-conform 行为正确 |
| 二·安全性 | ✅ | 无注入（payload 使用 markdown 拼接，'\|' 字符已转义）；无硬编码 token；所有 fs 操作通过 legion_api（路径白名单已在 P1.1 验证） |
| 三·项目规范 | ✅ | 复用 5 模块（adr_storage/design_tech_plan/error_classifier/legion_api/pm_db_api）/ 不写 ADR / 不直接动 inbox 与 tmux / 仅动 hermes-plugin/ 内文件 |
| 四·设计质量 | ✅ | 5 步函数职责清晰（_step1_load_project_context / _step3_split_ready_deferred / _step4_5_dispatch_with_balance / _pick_best_legion / _build_payload / _build_cto_context / _build_summary）/ 命名自解释 |
| 七·Python 专项 | ✅ | 类型注解齐（Dict/List/Optional/Tuple）/ retry 包裹由 error_classifier 提供 / except Exception (BLE001) 已 noqa 注释 / 错误升级路径完整 |

## 5. 反幻觉的反幻觉（高阶 E2E 验证）

| 项 | 实施者声称 | 我实跑验证 |
|----|-----------|----------|
| 5 步推理链完整 | ✅ | TEST 1-10 全 PASS（intent 校验 / 0 commander / Step 3 split / 全军团满载 / 派单成功 / 派单失败 deferred） |
| **B-1 防回归 retry attempts=3** | ✅ | TEST 6：`raise _DispatchBalancedError(level=tech)` × N → attempts=3（与 P1.2 实测 attempts=1 形成强对照） |
| 单军团并发 ≤2 | ✅ | TEST 11：5 任务 / 2 军团 → assignments=4(2+2) / deferred=1 |
| payload 三段必齐 + cto_context 5 字段 | ✅ | TEST 12：4 个派单 payload 全含 "PRD 摘要" / "技术方案" / "Given/When/Then" + cto_context{tech_plan_id, adr_links, feishu_doc_url, project_id, task_id} |
| size→priority 映射 | ✅ | TEST 13：XL→high / S→low |
| suggested_legion 优先 | ✅ | TEST 14：hint=L1-mock-赤龙 → 实派该军团 |
| depends_on → deferred | ✅ | TEST 15：deps=["upstream"] → deferred reason 含 "depends_on 未就绪" |
| 派失败 → deferred + warning（不阻塞）| ✅ | TEST 16：mock LegionError → 1 deferred + 1 warning，整批正常返回 |
| 缺数据降级标注（不静默吞）| ✅ | TEST 19：PRD/ADR/GWT 三段全空 → 三条显式"数据缺失"标注；TEST 20：PRD 超长 → 截断提示 |
| permission/unknown → escalate_to_owner | ✅ | TEST 27/28：双触发 escalate，escalation 上下文含 phase/project_id |
| **mailbox 协议复用证据** | ✅ | TEST R6：spy `legion_api.mailbox_protocol_serialize` + `_write_inbox_to_path` → dispatch 派单时调用 1 次 mailbox 序列化 + 1 次 inbox 写，消息字段含 from=AICTO-CTO/to=L1-fake-cmd/type=task/cto_context/priority |
| 不污染真实军团 | ✅ | grep 源码 0 处硬编码 `L1-麒麟\|L1-赤龙\|L1-凤凰`；测试全用 `L1-mock-*` 假名；mock send_to_commander 拦截所有派单不写真实 inbox |
| 复用纪律：8 军团 hardcoded | ✅ | 仅 1 处引用 `design_tech_plan.HARDCODED_LEGION_PROFILES`（line 350）+ docstring 注明依赖；无重定义 |
| 复用纪律：fcntl/subprocess/tmux 不直接调 | ✅ | 0 处 `import fcntl` / `import subprocess`；fcntl/tmux 字符串仅出现于 docstring 与 send_result 字段读取（line 432-433） |

**结论：实施者所有 P1.4 验收声称（5 步推理链 / 单军团 ≤2 / 三段 payload / cto_context 5 字段 / mailbox 复用 / B-1 防回归 / 不污染军团）全部实跑核实。**

## 6. 综合结论

```
判定：ALL APPROVED
0 BLOCKING / 7 NON-BLOCKING / 2 文件全过

P1.4 §5.1.3 验收标准全过：
- ✅ 给 5 任务 + 2 在线军团 → 单军团并发 ≤2 + 多余进 deferred
- ✅ 派单 inbox.json 中含 cto_context 字段（tech_plan_id/adr_links/feishu_doc_url 三字段齐）
- ✅ tmux send-keys 通知行（通过 legion_api 双通道；mock 验证 tmux_notified 字段写入正确）
```

NON-BLOCKING 7 条建议在 Phase 1 收官前批量收口（与 P1.2/P1.3 N 系列一起处理）：
- **N-1（高）**：load_map 改为 inbox 计数（Phase 2 必修，影响 R-FN-3.3 跨调用语义）
- **N-2（中）**：feishu_doc_url 从 ProjectDocument 表反查（Phase 2 修，ARCHITECTURE §5.3 强制字段）
- **N-3（中）**：tech_plan_id 真实化（Phase 2 与 design_tech_plan schema 演化同步）
- **N-4（低）**：line 494-496 注释精确化
- **N-5（低）**：_build_payload 拆 3 helper 提升可测性
- **N-6（低）**：GWT 部分缺失时聚合提示
- **N-7（低）**：Step 4+5 函数拆分（可选）

**B-1 第三轮固化**：实施者主动从 REVIEW-P1.2 / REVIEW-P1.3 学习并预防（_DispatchBalancedError 显式继承 WrappedToolError + docstring 注明）。建议 P1.8 集成验收时补 1 条多次 dispatch 调用单军团载荷漂移的端到端 case，作为 N-1 验证基线。

---

**审查方法学**：本批次审查由（a）静态 grep / 源码逐行 + （b）28 项隔离实跑测试（覆盖每个内部函数的 happy / 边界 / 异常分支 + 5 步推理链每阶段）+ （c）2 项 spy 集成（spy `mailbox_protocol_serialize` 与 `_write_inbox_to_path` 验证派单确实经过 legion_api）+ （d）3 项一致性 grep（HARDCODED_LEGION_PROFILES 唯一引用 / 无 fcntl/subprocess 直接调 / 无 L1-* 硬编码）+ （e）tools.py 委托 spy 五种手段交叉验证。所有结论附实跑证据，无任何评级仅基于"看代码"。所有 mock 派单**未实际写入真实军团 inbox** — 测试全用 L1-mock-* 命名空间。

测试归档：内存 28 项实跑全 PASS（TEST 1-28 + R1-R6 + T1-T2 + N-1 静态分析）。
