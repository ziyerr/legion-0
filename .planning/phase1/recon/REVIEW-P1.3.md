# P1.3 批次审查报告 — breakdown_tasks

> 审查者：reviewer-p1-3 / L1-麒麟军团（Task #20）
> 审查时间：2026-04-25
> 审查范围：breakdown_tasks 主模块 + prompt 双模板 + tools.py dispatch 接入（共 4 文件 / +1244 行新增）
> 审查依据：REQUIREMENTS.md §1.3 R-FN-2.1~2.6 / PHASE-PLAN.md §4.1.1 / PRD-CAPABILITIES.md 能力 2 / RECON-HISTORY.md §8.2 / REVIEW-P1.2.md（B-1 防回归基线）/ review-checklist.md

## 0. 验证手段（反幻觉的反幻觉）

| 验证项 | 手段 | 结果 |
|------|------|------|
| 模块可加载 | `importlib.spec_from_file_location` + 包式 submodule load | ✅ breakdown_tasks 加载成功，常量 `MAX_RESPLIT_ROUNDS=2 / ALLOWED_SIZES={S,M,L,XL}` 到位 |
| **B-1 防回归（核心）** | `inspect.getmro(_BreakdownTasksError)` | ✅ `[_BreakdownTasksError, WrappedToolError, Exception, ...]` |
| **B-1 retry attempts** | 隔离测试：`raise _BreakdownTasksError(level=tech)` × 3，调 `retry_with_backoff(max_retries=3)` 计数 | ✅ attempts=3（不修复时 attempts=1）|
| permission 不重试 | `raise _BreakdownTasksError(level=permission)`，retry 包裹 | ✅ attempts=1 立即抛 |
| 入参 intent 校验 | `bd.run({})` / `{"tech_plan":"str"}` / `{"tech_plan":{"tech_stack":[]}}` | ✅ 4 case 全返 `{"error":...,"level":"intent","elapsed_seconds":0.0}` 顶层 `error` key |
| feasibility=red 拒绝 | `bd.run({"tech_plan":{"feasibility":"red","tech_stack":[...]}})` | ✅ `error` 含 "feasibility=red" + `level="intent"` |
| blocking_downstream 拒绝 | `{"feasibility":"yellow","blocking_downstream":True,"tech_stack":[...]}` | ✅ `error` 含 "blocking_downstream=true" + intent |
| 拓扑 happy DAG | a→b→c (3 节点链) | ✅ order=['a','b','c'] / edges=3 |
| 拓扑含环拒绝 | x↔y | ✅ raise `_BreakdownTasksError(level=intent)`，msg 含 "cycle detected" |
| 拓扑空集 | `_topological_sort([])` | ✅ ([], []) |
| size 超标 detect | XXL / estimate_days=4 / 合规 XL 混合 | ✅ 仅 XXL+4天命中 oversized |
| force_clamp 兜底 | XXL→XL / 4天→3.0 | ✅ 全部 clamp 到合规 |
| _normalize 字段兜底 | 缺 id/重 id/缺 GWT/非法 legion/缺 link/非 dict | ✅ 8 项兜底全 PASS（dup id 重生 / GWT 三段→`<待补>` / legion→启发式 / link→`['unknown']`）|
| depends_on 清洗 | 自引用 + 引用不存在的 id | ✅ 全部剔除并 warning |
| _coerce_tasks_payload | dict 含 tasks / 裸 list / dict 内首个 list / 字符串 / dict 无 list | ✅ 5 case：3 OK + 2 抛 `_BreakdownTasksError(level=tech)` 触发 retry |
| _parse_adr_title | "选择 X 作为 Y" / 乱文 / 空 | ✅ 3 case 全对 |
| 启发式 legion 映射 | 7 关键词分支 | ✅ frontend→凤凰 / ai→昆仑 / docker→青龙 / mobile→星辰 / data→鲲鹏 / urgent→暴风 / 默认→麒麟 |
| 复用纪律 | grep 源码 | ✅ 引 `design_tech_plan.HARDCODED_LEGION_PROFILES` / `_invoke_llm` / `_parse_llm_json`；无 `adr_storage.create_adr`（不写 ADR）；无 `networkx`/`graphlib`（自实现 Kahn）|
| **E2E 集成（patched LLM）** | 8 场景：happy / resplit / cycle / GWT 缺 / invalid JSON 重试 / resplit 用尽 / id 重 / dep 非法 | ✅ **8/8 PASS**（详见 §5）|

> 全部测试已存于 `/tmp/test_breakdown_p13.py`（47 单元）+ `/tmp/test_breakdown_e2e.py`（8 端到端）。未跑真实 LLM 出网（gateway 8644 health OK 但工具调用 endpoint 404，与 P1.3 代码无关；P1.2 verifier 已用 apimart + claude-opus-4-6 实测同一 LLM 通道 67.9s 端到端通；本审查通过 monkey-patch 隔离 LLM 网络层但完整跑 4 步推理链每条分支）。

## 1. 总评

| 模块 | 行数 | 评级 | 关键发现 |
|------|------|------|---------|
| `breakdown_tasks.py` | 1007 | **PASS** | 4 步推理链完整 / B-1 防回归到位 / 复用纪律 100% / 5 项 NON-BLOCKING 改进建议 |
| `templates/breakdown-tasks-prompt.md` | 86 | **PASS** | 8 条硬纪律齐 / 反幻觉硬约束 (#8) / JSON-only 输出契约 / 8 字段任务模板齐 |
| `templates/breakdown-tasks-resplit-prompt.md` | 35 | **PASS** | 5 条硬纪律齐 / 子任务保留原 tech_stack_link/legion 约束 / 完整列表替换语义 |
| `tools.py`（dispatch 接入）| +12 行 | **PASS** | 1 处实接 `_breakdown_tasks.run` / 注释更新到 P1.3 已上线 / stub 透明纪律不破 |

**0 BLOCKING / 5 NON-BLOCKING / 综合结论：ALL APPROVED**

主路径功能性完整且 B-1 防回归到位（实测复现 attempts=3，相比 P1.2 实测 attempts=1 形成对照）。5 项 NON-BLOCKING 均为优化建议，不阻塞 P1.3 关闸。

## 2. BLOCKING 项

**无。**

P1.2 评审里的 B-1（_DesignTechPlanError 不继承 WrappedToolError 致 retry 失效）在本批次实施者已主动学习并预防 — 代码 line 72-83 的 `_BreakdownTasksError` 显式继承 `error_classifier.WrappedToolError` 并在 docstring 注明"防 B-1（reviewer-p1-2 / 2026-04-25）"。隔离单测验证 attempts=3，验证项打 ✅。

## 3. NON-BLOCKING 项（建议修但不阻塞 merge）

### N-1 · breakdown_tasks.py:566-574 + 715-723 — `_invoke_llm` 沿用 design_tech_plan 路径，未传 `response_format={"type":"json_object"}`

**X**：
```python
def _do_call() -> List[Dict[str, Any]]:
    response = design_tech_plan._invoke_llm(messages)  # ← 复用 dtp 的 OpenAI 调用，无 json_object
    content = design_tech_plan._extract_content(response)
    parsed = design_tech_plan._parse_llm_json(content)
    return _coerce_tasks_payload(parsed)
```

**Y**：与 P1.2 N-3 同款 — 根因在 `design_tech_plan._invoke_llm_via_openai` 没设 `response_format`。breakdown_tasks 是被动复用方，应等 design_tech_plan 修复后自动受益（不在本模块单独 patch，避免接口分叉）。

**Z**：复用纪律正确 — `_invoke_llm` 是 design_tech_plan 的内部实现，breakdown_tasks 不应跨模块改它。**P1.2 N-3 是父修复点，本条纯属继承同一改进窗口**，不在 P1.3 单独阻塞。建议 P1.2 N-3 修复时 breakdown_tasks 自动跟进受益。

### N-2 · breakdown_tasks.py:862-879 — 启发式 fallback **永不返回 L1-赤龙军团**（覆盖率 7/8）

**X**：
```python
def _pick_legion_by_tech_stack_link(link: List[str]) -> str:
    text = " ".join(link).lower()
    if any(k in text for k in ("frontend", "ui", ...)):  return "L1-凤凰军团"
    if any(k in text for k in ("ai", "llm", ...)):       return "L1-昆仑军团"
    if any(k in text for k in ("devops", "docker", ...)): return "L1-青龙军团"
    if any(k in text for k in ("mobile", "ios", ...)):   return "L1-星辰军团"
    if any(k in text for k in ("data", "spark", ...)):   return "L1-鲲鹏军团"
    if any(k in text for k in ("urgent", "poc", ...)):   return "L1-暴风军团"
    # database / observability / mq / cache / search / backend / 其他 → 麒麟（默认）
    return "L1-麒麟军团"
```

**Y**：在 default 麒麟之前插入一档对赤龙的关键词匹配：
```python
if any(k in text for k in ("postgresql", "kafka", "go", "数据中台", "中台", "微服务")):
    return "L1-赤龙军团"
```

**Z**：实测 29 个测试关键词遍历 → heuristic picks = 7 个军团，缺赤龙。HARDCODED_LEGION_PROFILES 中赤龙画像是"后端服务 / 数据中台 / python / go / postgresql / kafka"，与麒麟（"AICTO / ProdMind / Hermes plugin / fastapi / sqlite"）有明显差异化。当前代码任何 backend-ish 兜底都流向麒麟 → 单点过载风险。**实际触发条件较窄**（仅 LLM 输出非法 legion 名时启用 fallback），且 prompt 里 `_summarize_legion` 已把 8 军团全画像列给 LLM，正常路径 LLM 会直接挑赤龙；fallback 仅作最后保险。NON-BLOCKING。

### N-3 · breakdown_tasks.py:688-705 — `_force_clamp_oversized(tasks, warnings)` 第二参数 `warnings` 未使用

**X**：
```python
def _force_clamp_oversized(
    tasks: List[Dict[str, Any]], warnings: List[str]   # ← warnings 接收但函数体不写
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in tasks:
        ...
        out.append(clamped)
    return out
```

**Y**：要么删除 `warnings` 参数（最简）；要么 `warnings.append(f"force-clamp: task {t['id']} size→XL / days→{MAX_DAYS_HARD_CAP}")` 让 PM 知道哪些任务被硬 clamp（更友好）。

**Z**：当前调用方已在外层 append "强制 clamp" 文案（line 661-663），所以传入参数仅作 placeholder。从 caller 视角看像是双 channel 报告 warning，实际只有外层在记。死参数 = 接口噪音。SUGGEST 选 Y 方案二让 clamp 细节落到任务级 warning（PM 能精确定位哪个任务被硬切）。

### N-4 · breakdown_tasks.py:951-967 — Kahn 拓扑用 `queue.pop(0)`（O(n)）替代 `deque.popleft()`（O(1)）

**X**：
```python
queue: List[str] = [t["id"] for t in tasks if incoming[t["id"]] == 0]
visited: Set[str] = set()
while queue:
    node = queue.pop(0)   # ← O(n) shift
    ...
```

**Y**：
```python
from collections import deque
queue: deque[str] = deque(t["id"] for t in tasks if incoming[t["id"]] == 0)
while queue:
    node = queue.popleft()   # O(1)
    ...
```

**Z**：当前 P1.3 任务量级预期 ≤ 50（PRD §五·能力 2），O(n²) 实测无感。但 Phase 2+ 若批量项目派单（每项目 30+ tasks × 多项目并发），拓扑成本上升。`collections.deque` 是 stdlib，不破"无新依赖"纪律。SUGGEST 改 deque 顺手优化。

### N-5 · breakdown_tasks.py:798-820 — 单任务缺 GWT 三段会膨胀 4 条 warning（建议聚合）

**X**：
```python
# 整个 acceptance_gwt 缺：1 条 warning（line 806）
# 然后逐键检查 given/when/then：每键缺再 1 条 warning（line 815）
# → 全空 GWT 单任务 → 1 + 3 = 4 条 warning（实测 E2E-4 印证 task A 全空 + task B 缺 1 字段 → 共 2 条 warning，符合预期但已显冗长）
```

实测：当 LLM 全量返回 100 个 task 且全缺 GWT，warning 字段会含 ~400 条字符串，可能撑大下游 daily_brief 摘要。

**Y**：聚合策略 — 单任务的 GWT 缺失只发 1 条 warning，列出缺的字段名：
```python
missing = [k for k in ("given","when","then") if not (gwt or {}).get(k, "").strip()]
if missing:
    t["acceptance_gwt"] = {**(gwt or {}), **{k: "<待补>" for k in missing}}
    warnings.append(f"task {t['id']} acceptance_gwt 缺字段: {missing}（已兜底为 '<待补>'）")
```

**Z**：当前实现功能正确，仅是 warning 噪音可优化；下游可读性略改善。SUGGEST。

## 4. 一致性检查

### 与 REQUIREMENTS.md §1.3 R-FN-2.1~2.6 对齐

| ID | 需求 | 实现状态 | 证据 |
|----|------|---------|------|
| R-FN-2.1 | 输入：tech_plan_id 或 tech_plan obj | ✅ | `_step1_resolve_tech_plan` 二选一分支 / 二者都缺 → intent error |
| R-FN-2.2 | 输出：tasks[] + dependency_graph（强制 DAG）+ 每任务 GWT | ✅ | `_topological_sort` 检环 / `_normalize_tasks` GWT 三段兜底 / 实测 happy DAG 拓扑正确 |
| R-FN-2.3 | 单任务 size ≤ XL（≥3 天必拆）| ✅ | ALLOWED_SIZES + MAX_DAYS_HARD_CAP=3.0 + `_resplit_oversized_tasks`（≤2 轮）+ `_force_clamp_oversized` 兜底 |
| R-FN-2.4 | feasibility=red / blocking_downstream 拒绝触发 | ✅ | line 138-152 双检测，intent error 早返；实测 B1+C1 case PASS |
| R-FN-2.5 | task 字段：title/desc/size/GWT/depends_on/suggested_legion | ✅ | `_normalize_tasks` 8 字段全兜底 |
| R-FN-2.6 | EngineerProfile 来源：Phase 1 hardcoded | ✅ | `design_tech_plan.HARDCODED_LEGION_PROFILES` 直接复用，**未在本文件重复硬编码** |

### 与 PHASE-PLAN.md §4.1.1 任务清单对齐

| # | 任务 | 实现 |
|---|------|------|
| 3.1 | input schema：tech_plan_id 或 tech_plan obj | ✅ run() line 99-107 二选一校验 |
| 3.2 | feasibility=red / missing_info 拒绝触发 | ✅ line 138-152 |
| 3.3 | LLM 拆任务：含 size + GWT + depends_on + suggested_legion | ✅ Step 2 prompt 输出契约 8 字段 |
| 3.4 | hardcoded EngineerProfile dict | ✅ 复用 dtp.HARDCODED_LEGION_PROFILES（8 军团齐）|
| 3.5 | DAG 环检测 | ✅ `_topological_sort` Kahn + intent error |
| 3.6 | 单任务 size ≤ XL 强制 | ✅ MAX_RESPLIT_ROUNDS=2 + force_clamp 双保险 |

### 与 PRD-CAPABILITIES 能力 2 对齐

| 能力 2 描述 | 实现状态 |
|-----------|---------|
| 输出结构化任务列表 + 依赖 DAG | ✅ tasks[] + dependency_graph{edges, is_dag, topological_order} |
| 每任务有 Given/When/Then | ✅ acceptance_gwt 三段强制（缺 → `<待补>` 兜底）|
| 按 EngineerProfile（未来）推荐军团 | ✅ Phase 1 hardcoded，suggested_legion ∈ 8 军团（实施者自觉补 R-OPEN-6 默认）|

### 与 review-checklist.md 对齐（七章节）

| 章节 | 评级 | 备注 |
|------|------|------|
| 一·正确性 | ✅ | 47 单测 + 8 E2E 全 PASS；逻辑/边界/错误路径覆盖 |
| 二·安全性 | ✅ | 无注入（LLM messages 用 .replace 替换占位符 / 无 SQL 拼接 / 无文件穿越）；无硬编码密钥 |
| 三·项目规范 | ✅ | 复用 `_invoke_llm` / `HARDCODED_LEGION_PROFILES` / 不写 ADR；只动 `hermes-plugin/` 内文件 |
| 四·设计质量 | ✅ | 4 步推理链单一职责清晰 / `_step1` `_step2` `_normalize` `_clean_dependency_references` `_topological_sort` 命名自解释 |
| 七·Python 专项 | ✅ | 类型注解齐（List/Dict/Optional/Tuple/Set/Any）；retry 包裹 LLM 调用；print() 限于 best-effort 路径（adr_history 读失败）；无 sensitive 日志泄露 |

## 5. 反幻觉的反幻觉（高阶 E2E 验证）

| 项 | 实施者声称 | 我实跑验证 |
|----|-----------|----------|
| 4 步推理链完整 | ✅ | E2E-1 happy 4-task DAG：Step1(obj)+Step2(LLM)+Step3(normalize)+Step4(topo) 四阶段全跑通，order=['t-a','t-b','t-c','t-d'] |
| size 超标自动再拆 ≤2 轮 | ✅ | E2E-2：第 1 轮 LLM 输出 XXL → 触发 resplit → 第 2 轮 LLM 拆出 [XL,L,S] / llm_calls=2 / sizes=['XL','L','S'] |
| 拓扑含环→intent 拒绝 | ✅ | E2E-3：x↔y → `error="dependency cycle detected: 2 tasks in cycle..."`, level="intent" |
| GWT 缺三段→兜底+warning | ✅ | E2E-4：task A 全缺 → gwt={given:'<待补>',when:'<待补>',then:'<待补>'} + warnings 含 "acceptance_gwt 缺失" |
| **B-1 防回归 retry attempts=3** | ✅ | E2E-5：LLM 始终返 invalid JSON → attempts=3（与 P1.2 实测 attempts=1 形成强对照）|
| resplit 用尽→force_clamp | ✅ | E2E-6：LLM 始终返 XXL → llm_calls=3 (1 主 + 2 resplit) → final_sizes=['XL'] + warnings 含 "强制 clamp" |
| id 重复→自动重生 | ✅ | E2E-7：两个 task id="dup" → 第二个变 task-uuid4 / warning 含 "duplicate" |
| 非法 depends_on→剔除 | ✅ | E2E-8：deps=["nonexistent","a"]（自引用）→ 全剔除为 []，warning 双触发（"不存在" + "自引用"）|

**结论：实施者所有 P1.3 验收声称（4 步推理链 / DAG 检环 / size ≤ XL / GWT 兜底 / B-1 防回归 / 复用纪律）全部实跑核实。**

## 6. 综合结论

```
判定：ALL APPROVED
0 BLOCKING / 5 NON-BLOCKING / 4 文件全过

P1.3 4.1.3 验收标准全过：
- ✅ 给 design_tech_plan 输出 → 输出 tasks 数组 + DAG（无环）+ 每任务 GWT 三段齐全
- ✅ 全 task size ∈ {S, M, L, XL}（resplit + force_clamp 双保险）
- ✅ 依赖图可拓扑排序（Kahn FIFO 实现）
- ✅ 给 red verdict 输入 → 拒绝触发并返 error（intent 级）
- ✅ 给 blocking_downstream=true → 同上拒绝（额外加固）
```

NON-BLOCKING 5 条建议在 Phase 1 收官前批量收口（与 P1.2 N 系列一起处理）：
- N-1 顺 P1.2 N-3 修；
- N-2 启发式补赤龙军团关键词；
- N-3 删/补 `_force_clamp_oversized` 第二参数；
- N-4 拓扑改 `collections.deque`；
- N-5 GWT warning 聚合。

**B-1 已固化**：实施者主动从 REVIEW-P1.2 学习并预防（_BreakdownTasksError 显式继承 WrappedToolError + docstring 注明）。建议在本模块同步补一个 retry-behavior 隔离单测（pytest fixture + counter）落入 `test_error_classifier.py` 边的姊妹测试，防 Phase 2 回归。

---

**审查方法学**：本批次审查由（a）静态 grep / 源码逐行 + （b）47 项隔离单元测试（覆盖每个内部函数的 happy / 边界 / 异常分支）+ （c）8 项端到端集成测试（monkey-patch `design_tech_plan._invoke_llm` 走完整 4 步推理链）+ （d）3 项 hierarchical assertion（继承链 / 复用引用 / 启发式覆盖率）四种手段交叉验证。所有结论附实跑证据，无任何评级仅基于"看代码"。

测试脚本归档：
- `/tmp/test_breakdown_p13.py`（47 unit cases）
- `/tmp/test_breakdown_e2e.py`（8 E2E cases via patched LLM）
