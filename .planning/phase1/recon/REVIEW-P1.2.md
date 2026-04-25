# P1.2 批次审查报告

> 审查者：reviewer / L1-麒麟军团  
> 审查时间：2026-04-25  
> 审查范围：design_tech_plan 模块 + prompt 模板 + tools.py dispatch 接入（共 3 文件 / +1136 行新增）  
> 审查依据：REQUIREMENTS.md §1.2 / ARCHITECTURE.md §1+§4 / PHASE-PLAN.md §3 / PRD-CAPABILITIES.md 能力 1 / ADR-006 / ADR-010 / review-checklist.md

## 0. 验证手段（反幻觉的反幻觉）

每个结论基于以下**实跑命令**：

| 验证项 | 手段 | 结果 |
|------|------|------|
| 模块可加载 | `python3 importlib.util.spec_from_file_location` 在 hermes-agent venv | ✅ 5 模块全 OK |
| 8 军团 hardcoded | `dtp.HARDCODED_LEGION_PROFILES` 取出 commander_name list | ✅ 麒麟/凤凰/赤龙/昆仑/青龙/星辰/鲲鹏/暴风（8 全到位）|
| input intent 校验 | `dtp.run({})` / `dtp.run({"prd_markdown":"   "})` | ✅ 返 `{"error":...,"level":"intent","kr4_compliant":true}` |
| 错误顶层 key | 同上 | ✅ `error` key（非 `success: False`）|
| `_enforce_hard_rules` 全分支 | 6 个 case：red 无路径 / 非法 fe / estimate 缺失 / estimate 乱序 / tech_stack 缺 alt / 非 dict | ✅ 6/6 PASS |
| `_parse_llm_json` 容错 | 4 case：fenced / prefixed / empty / invalid | ✅ 4/4 PASS（空和 invalid 抛 `_DesignTechPlanError(level=tech)` 触发 retry 意图）|
| 端到端实跑（prd_markdown 路径，简单 PRD）| AIGC_API_KEY + claude-opus-4-6 | ❌ 56.79s 后失败：LLM 抽风返回 invalid JSON，**未触发 retry**（详见 BLOCKING-1）|
| 端到端实跑（prd_id 路径，AI CTO PRD）| 同上 | ✅ 67.9s 完成 / 7 tech_stack / 7 ADR / 6 missing_info / blocking_downstream=true / 飞书 doc URL |
| ADR 真落表 | sqlite3 dev.db: `SELECT * FROM ADR ORDER BY created_at DESC LIMIT 7` | ✅ 7 行新增 / project_id 正确 / number 1-7 per-project / decided_by="AICTO (程小远)" |
| 飞书 doc 真可读 | `feishu_api.read_docx_content('https://docs.feishu.cn/docx/LTlid...')` | ✅ 3971 字符 / 含表格 / mermaid 渲染挂在末尾 |
| KR4 SLA 计时 | 67.9s vs 300s | ✅ kr4_compliant=true |
| 审计日志真有产出 | `tail read-audit.log` | ✅ 端到端跑后 2 行新记录（get_pm_context + read_pm_project）|

## 1. 总评

| 模块 | 行数 | 评级 | 关键发现 |
|------|------|------|---------|
| design_tech_plan.py | 1049 | **BLOCKING** | 6 步推理链完整 / ADR 写入 1:1 / 飞书 doc 端到端通；但 `_DesignTechPlanError` 未继承 `WrappedToolError` 致 LLM 抽风**永不重试**（实跑复现）|
| templates/tech-plan-prompt.md | 87 | **PASS** | 8 条硬纪律齐 / 反幻觉强约束到位 / 输出 schema 6 字段 + improvement_path |
| tools.py（dispatch 接入）| 124 | **PASS** | 仅 1 处实接（`_design_tech_plan.run`）/ 5 stub 透明 / phase 标记准确 |

**1 BLOCKING / 4 NON-BLOCKING / 综合结论：BLOCKED**

主路径功能性已上线（happy path 67.9s 端到端通），但 BLOCKING-1 是 **R-NFR-19 / ADR-006 "技术级错误自动重试 3 次" 的硬约束失效**，必须在 P1.2 关闸前修。

## 2. BLOCKING 项

### B-1 · design_tech_plan.py:322-328 — `_DesignTechPlanError` 未继承 `WrappedToolError`，致 retry_with_backoff **永不重试** LLM 抽风

**X**：
```python
class _DesignTechPlanError(Exception):
    def __init__(self, message: str, level: str = error_classifier.LEVEL_UNKNOWN):
        super().__init__(message)
        self.level = level
```

**Y**：
```python
class _DesignTechPlanError(error_classifier.WrappedToolError):
    """模块专用异常，继承 WrappedToolError 让 retry_with_backoff 直接读 .level。"""
    def __init__(self, message: str, level: str = error_classifier.LEVEL_UNKNOWN):
        super().__init__(message, level=level)
```

**Z**：
- `error_classifier.retry_with_backoff` 对 `WrappedToolError` 走 short-circuit `e.level` 判定；对其他 `BaseException` 走 `classify(e)` 关键词匹配。
- 当前 `_DesignTechPlanError` 是 `Exception` 子类 → 走关键词路径。
- `_parse_llm_json` 在 LLM 返回 invalid JSON 时刻意构造 `_DesignTechPlanError(message="LLM returned invalid JSON: ...", level=LEVEL_TECH)` 想触发 retry。
- 但 `classify("designtechplanerror llm returned invalid json: ...")` 在 `_TECH_KEYWORDS / _PERMISSION_KEYWORDS / _INTENT_KEYWORDS` 中无任何关键词命中 → 返回 `LEVEL_UNKNOWN` → `retry_with_backoff` 立即 `raise` 不重试。
- **实跑复现**（`prd_markdown` 简单 PRD）：56.79s 单次返回 `{"error": "LLM returned invalid JSON: Expecting ',' delimiter at column 2629", "level": "tech", ...}`，attempts=1 而非 3。
- **隔离单测复现**：
  ```python
  calls = []
  def fail_fn():
      calls.append(1)
      raise dtp._DesignTechPlanError("LLM returned invalid JSON: x", level=ec.LEVEL_TECH)
  try: ec.retry_with_backoff(fail_fn, max_retries=3, base_delay=0.01)
  except: pass
  # len(calls) == 1（应为 3）
  ```
- **影响**：违反 R-NFR-19 / ADR-006 "技术级错误自动重试 3 次"。LLM 偶发 JSON 抽风（典型场景：超长 token 截断、罕见字符）会一次失败而非靠重试拉回。
- **修复验证**：把 `_DesignTechPlanError` 改继承 `WrappedToolError` 后同样的隔离测试 attempts=3 ✅。
- **附加效益**：修复后 `_invoke_llm_via_openai` 抛的 `_DesignTechPlanError(level=LEVEL_PERMISSION)`（缺 API key）也会被 `retry_with_backoff` 正确识别为 permission 立即上抛（不重试），与 step-1 的 escalate 处理一致。

## 3. NON-BLOCKING 项（建议修但不阻塞 merge）

### N-1 · design_tech_plan.py:134-137 + 185-188 — `except _DesignTechPlanError` 不调 `escalate_to_owner`

**X**：Step 1 / Step 4 的 `except _DesignTechPlanError as e: return _fail(...)` 仅返错，不升级。

**Y**：
```python
except _DesignTechPlanError as e:
    if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
        error_classifier.escalate_to_owner(e.level, e, {"phase": "stepN", ...})
    return _fail(str(e), level=e.level, elapsed=...)
```

**Z**：Step 1 的"非 _DesignTechPlanError 异常"分支已正确按 R-NFR-20 升级 permission/unknown 级骏飞，但 _DesignTechPlanError 分支跳过升级。如 `_load_from_feishu` 把飞书 401/403 包成 `_DesignTechPlanError(level=permission)` 抛出，则用户拿到错返但骏飞收不到通知 — 违反 R-NFR-20 "权限 → 立即升级骏飞"。修了 B-1 后此问题更突出（permission 不重试直接抛 _DesignTechPlanError）。

### N-2 · design_tech_plan.py:251-255 — ADR 写入异常 catch 太宽 + 不分类

**X**：
```python
except Exception as e:
    msg = f"adr write failed for {item.get('component')}: {e}"
    print(f"[design_tech_plan] {msg}")
    adr_write_errors.append(msg)
```

**Y**：捕获后 `level = error_classifier.classify(e)`；`if level == permission: error_classifier.escalate_to_owner(...)`，仍累计 `adr_write_errors` 不阻塞主流程。

**Z**：与 spec "ADR 写入失败 → 仅 log + adr_write_errors（不阻塞）" 一致，但典型 permission 错（如 dev.db readonly 误用、磁盘满）应该静默兜底 + 升级骏飞。当前完全静默 = 反幻觉纪律 R-NFR-1 边界（"不静默吞"）。

### N-3 · design_tech_plan.py:705-722 — `_invoke_llm_via_openai` 不传 `response_format={"type":"json_object"}`

**X**：`client.chat.completions.create(...)` 缺 `response_format`。

**Y**：`response_format={"type": "json_object"}`（OpenAI 协议兼容；如 aigcapi.top 不支持则忽略此 key 或要 try/except 兜底）。

**Z**：当前靠 prompt 强约束 + `_parse_llm_json` 容错（去围栏 + 提 `{...}`）兜底已工作，但 belt-and-suspenders 双保险更稳，且能减少抽风频率（B-1 实测案例可能因此规避）。SUGGEST 改 NON-BLOCKING：先加 try/except 包一层，aigcapi.top 拒绝时降级。

### N-4 · design_tech_plan.py:684-702 — 每次 LLM 调用都 `from agent.auxiliary_client import call_llm`

**X**：`_invoke_llm` 内 import；retry 3 次时重复 import 3 次。

**Y**：模块顶层 `try: from agent.auxiliary_client import call_llm; _HAS_AUX_CLIENT = True except ImportError: _HAS_AUX_CLIENT = False`，调用处分支判断。

**Z**：性能影响微小（Python import 有缓存），但符合 PEP 8 "imports at top of file"。修了 B-1 后 retry 触发，重复 import 次数翻倍。

### N-5 · design_tech_plan.py:496-507 — `_resolve_project_name` 多一次 DB round-trip

**X**：`get_pm_context_for_tech_plan` 已经读了 PRD 行（含 `projectId`），但没读 Project.name；`_resolve_project_name` 又开一次连接读 Project。

**Y**：在 `pm_db_api.get_pm_context_for_tech_plan` 内同时 `JOIN Project` 拿 name，或在返回 payload 加 `project_name` 字段；design_tech_plan 直接读不再 round-trip。

**Z**：审计日志多一行 `read_pm_project` 调用（实测见 read-audit.log:08:15:42 那行）；KR4 SLA 影响 < 100ms，但工程规整度可改善。

## 4. 一致性检查

### 与 REQUIREMENTS.md §1.2 R-FN-1.1~1.8 对齐

| ID | 需求 | 实现状态 |
|----|------|---------|
| R-FN-1.1 | 三选一 input + focus + constraints | ✅ `_step1_load_prd_context` 三分支 + `args.get("focus")` / `args.get("constraints")` |
| R-FN-1.2 | 6 字段 JSON 输出 | ✅ feasibility / improvement_path / tech_stack / estimate / risks / missing_info + summary + feishu_doc_url |
| R-FN-1.3 | red 必含 improvement_path | ✅ prompt 硬纪律 #1 + `_enforce_hard_rules` 兜底（实跑 enforcement test ENF-1 PASS）|
| R-FN-1.4 | missing_info → blocking_downstream | ✅ `blocking_downstream = (feasibility=='red') or bool(missing_info)` |
| R-FN-1.5 | 每个 tech_stack 写一条 ADR | ✅ Step 5 for-loop；实测 7 tech_stack ↔ 7 ADR 行 |
| R-FN-1.6 | 飞书 doc 含 mermaid + 表格 + API contract | ✅ `create_docx` + markdown_to_descendants（含表格）+ mermaid 自动插图；实测可读回 3971 字符 |
| R-FN-1.7 | KR4 ≤ 300s SLA | ✅ 埋点 elapsed_seconds + kr4_compliant；实测 67.9s |
| R-FN-1.8 | 6 步推理链 | ✅ Step 1/2/3/4/5/6 全部到位（虽 Step 3 hardcoded，按 R-OPEN-6 PM 已决）|

### 与 ARCHITECTURE.md §1 数据流对齐

- ✅ §1 数据流：PM 派发 PRD → 程小远拉上下文 → ADR history → LLM → 写 ADR → 飞书 doc
- ✅ §4.4 hardcoded 8 军团（与 RECON 6.5 一致）
- ✅ §6 4 级错误分类应用（intent / permission / unknown 全分支可见，tech 级 retry 因 B-1 失效）

### 与 PHASE-PLAN.md §3.1.1 任务清单对齐

| # | 任务 | 状态 |
|---|------|------|
| 2.1 | input schema | ✅ schemas.DESIGN_TECH_PLAN（5 字段，prd_id/prd_markdown/prd_doc_token/focus/constraints）|
| 2.2 | step 1 拉 PM 上下文 | ✅ `_load_from_dev_db` |
| 2.3 | step 2 ADR history | ✅ `adr_storage.list_adrs(project_id)` |
| 2.4 | step 3 LLM 6 字段 | ✅ `_step4_llm_design`（实测 7 字段含 summary + improvement_path）|
| 2.5 | step 4 写 ADR | ✅ Step 5 真落表（数量验证 7=7）|
| 2.6 | step 5 飞书 doc | ✅ `create_docx` + markdown_to_descendants |
| 2.7 | step 6 grant tenant_read | ✅ create_docx 内自动调用 |
| 2.8 | red verdict 改进路径 | ✅ prompt 硬纪律 #1 + enforce 兜底 |
| 2.9 | missing_info 阻塞标记 | ✅ blocking_downstream 字段 |
| 2.10 | KR4 SLA 埋点 | ✅ elapsed_seconds + kr4_compliant |

### 与 ADR 决策对齐

- ✅ ADR-006 4 级错误分类：intent / permission / unknown 路径全部接入 — **但 tech 级 retry 因 B-1 实质失效**
- ✅ ADR-010 PRD 数据源三选一：dev.db 主链路 + markdown / feishu 备路径
- ✅ ADR-002 ADR 存共享 dev.db：实测 7 行落 prodmind/dev.db ADR 表

## 5. 反幻觉的反幻觉（高阶验证）

| 项 | 实施者声称 | 我实跑验证 |
|----|-----------|----------|
| 6 步推理链全到位 | ✅ | 代码逐行 + 实跑 prd_id 路径 7 ADR + 飞书 doc 全到位 |
| KR4 SLA ≤ 300s | ✅ | 实测 67.9s（happy path）|
| ADR 写入 dev.db | ✅ | sqlite3 SELECT 真有 7 行 |
| 飞书 doc 可访问 | ✅ | feishu_api.read_docx_content 回读 3971 字符 |
| missing_info → blocking_downstream | ✅ | 实测 6 missing_info → blocking_downstream=true |
| 错误顶层 error key | ✅ | 实测 4 个 error 路径 JSON 均含 `"error"` 顶层 |
| LLM 抽风 retry 3 次 | ❌ | **实测复现 attempts=1，未触发重试** — 见 BLOCKING-1 |

## 6. 综合结论

```
判定：BLOCKED
1 BLOCKING / 5 NON-BLOCKING / 3 文件 1 阻塞 2 通过

修复 B-1 后即可放行。修复方法：把 _DesignTechPlanError 改继承 error_classifier.WrappedToolError，
super().__init__(message, level=level)。修复路径仅 6 行 diff。

happy path 已 P1.2 验收标准全过：
- ✅ 给 PRD `5257375f-...` → 67.9s 内输出 6+1 字段 JSON（包含 summary）
- ✅ 输出含 6 条 missing_info（PRD 必有未明示的细节）
- ✅ feishu_doc_url 可访问 + tenant 可读 + mermaid 已渲染
- ✅ ADR 表新增 7 条记录（对应 tech_stack 7 项，1:1 对齐）
- 待补：red verdict 用例需 P1.2 验证者用一个 PRD 子集复现
```

NON-BLOCKING 5 条建议在 Phase 1 收官前批量修复（不阻塞 P1.3 推进）；
B-1 修后建议立刻补一个隔离单测固化 retry 行为，防回归。

---

**审查方法学**：本批次审查由 grep / regex 静态扫描 + 单元级模拟 + 端到端实跑（含 LLM + 飞书 + ADR 落表）+ sqlite3 真表查询 + 飞书 API 读取回环五种手段交叉验证。所有结论附实跑证据，无任何评级仅基于"看代码"。
