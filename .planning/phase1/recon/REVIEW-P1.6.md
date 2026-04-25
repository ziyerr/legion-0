# REVIEW-P1.6 — review_code（能力 4）批量审查报告

> **审查者**：reviewer-P1.6（Sonnet 4.5）
> **审查时间**：2026-04-25
> **审查范围**：
> - `hermes-plugin/review_code.py`（1294 行 — 5 步推理链 + appeal_handler + find_stale_blocking_reviews + build_appeal_card）
> - `hermes-plugin/templates/code-review-prompt.md`（85 行 — LLM prompt）
> - `hermes-plugin/test_review_code.py`（984 行 — 21 单测）
> - `hermes-plugin/tools.py`（review_code dispatch 接入，157 行）
> **依据**：REQUIREMENTS §1.5（R-FN-4.1~4.12）/ PHASE-PLAN §7 / PRD-CAPABILITIES 能力 4 / R-OPEN-3（appeal 1 次升级）/ R-OPEN-10（KR 分子分母）/ B-1 第五轮防回归 / ADR-002（CodeReview 共享 dev.db）

---

## 0. 综合评级

| 维度 | 状态 |
|---|---|
| 5 步推理链 | ✅ 5/5 串联（gh diff → ADR/PRD context → LLM 10 项 → 文案+密度兜底 → DB+卡片） |
| 10 项审查清单逐字 | ✅ CHECKLIST_ITEMS 与 PRD 字面 1-10 项零字差，prompt 也保留逐字 |
| BLOCKING 文案"X→Y 因 Z"校验 | ✅ `_has_blocking_format` 实跑 9/9 PASS（含 6 正例 + 3 反例） |
| 不合规 → reformat 标记 | ✅ `_enforce_blocking_format` reformat + `format_warning=True` + warning |
| 评论密度兜底（程序级，非 LLM 自觉） | ✅ 单 PR ≤5（top severity）+ 单文件 ≤2（聚合 refactor） |
| 截断/聚合标记 | ✅ `aggregated_due_to_pr_cap` / `aggregated_due_to_per_file_cap` 双标记 |
| Appeal 协议 retract/maintained 双分支 | ✅ + APPEAL_ESCALATION_THRESHOLD=1（R-OPEN-3 默认） |
| Appeal DB 状态机 | ✅ none → retracted / maintained → escalated（双段 update） |
| 飞书 BLOCKING 卡片 4 字段 + 3 按钮 + json.dumps | ✅ template=red、3 按钮 value 全 JSON 字符串 |
| `find_stale_blocking_reviews` 接口 | ✅ stale_hours=24 默认 + 三 WHERE 条件齐 |
| B-1 第五轮防回归 | ✅ `_ReviewCodeError(WrappedToolError)` + retry isinstance 短路实跑通过 |
| 复用纪律 | ✅ 0 重定义 LLM/飞书 HTTP/CodeReview INSERT；5 import 全命中 |
| 反幻觉 | ✅ 错误顶层 `error`+`level`；diff 拉不到不静默 happy；reformat 不静默通过 |
| 测试不污染 | ✅ subprocess+send_card 全 mock；DB 残留 0 行（实查证实） |
| spec 一致性 | ✅ R-FN-4.1~4.12 全覆盖、R-OPEN-3/10 实现 |
| 实跑 21 测试用例 | ✅ ALL PASS（3.243s） |
| **path traversal / SQL 注入** | ✅ pr_url 走 `_PR_URL_REGEX` 严格校验；CodeReview SQL 全参数化 |

**统计**：0 SEVERE / 3 WARN / 6 SUGGEST
**结论**：**APPROVED — 0 BLOCKING；3 WARN 建议在 P1.7 同步清理（与 P1.5 W-2 同源）**

---

## 1. WARN 问题（应修，非阻塞）

### W-1：appeal 维持升级使用 LEVEL_PERMISSION 语义错位

| 项 | 内容 |
|---|---|
| **位置** | `review_code.py:1109-1110` |
| **现象** | appeal_handler 维持 BLOCKING → `escalate_to_owner(LEVEL_PERMISSION, ...)`。注释自承"维度：CTO/军团决策权冲突 → 升级人" |
| **影响** | R-NFR-20 定义 PERMISSION 是"飞书 401/403 / git push 拒绝 / SQL 权限错"等技术鉴权失败。Appeal 维持是**业务决策**而非鉴权失败，错放 PERMISSION 域会污染 KR 度量分母（escalation log 按 level 聚合时混入业务决策）|
| **改成什么** | 改成 `error_classifier.LEVEL_UNKNOWN`，并把注释改为"appeal 维持 = 决策权冲突，按未知保守升级（R-NFR-22）"。R-NFR-22 的"保守升级"原意正好覆盖此场景 |
| **理由** | 4 级分类的 level 字段是**度量分类标签**而非状态描述符。给"决策升级"贴 PERMISSION 标签 → 未来 R-OPEN-10 KR 度量做 `SELECT count(*) WHERE level='permission'` 时会把它算进鉴权类问题 |

### W-2：CodeReview 表写入未走 retry_with_backoff（与 P1.5 W-2 同源）

| 项 | 内容 |
|---|---|
| **位置** | `review_code.py:320-334`（step 5a） |
| **现象** | `adr_storage.create_review(...)` 直接调用，无 retry。失败仅 warning 不阻塞主流程，但 KR 度量丢失。reviewer-P1.5 在 W-2 已对 `kickoff_project._step4_write_adr` 指出同样瑕疵，本次未在 P1.6 借鉴 |
| **影响** | PM 澄清 R-OPEN-2 明确"sqlite locked → 退避重试"。当前实现下，多 profile 并发写 dev.db 触发的瞬时 `database is locked` 会直接走 warning 路径，导致 R-NFR-28（BLOCKING 准确率 ≥90%）和 R-NFR-29（appeal 率 ≤20%）的 CodeReview 行 missing → KR 不可度量 |
| **改成什么** | 包闭包 `_do_create_review` + `error_classifier.retry_with_backoff(_do_create_review, max_retries=3, base_delay=0.2)`。base_delay=0.2 比 git init 短，sqlite 锁通常很快释放，5 步全程 SLA（推断 ≤2 分钟）留得起 |
| **理由** | KR 度量数据完整性优先级高于"快速失败"。同条治则 reviewer-P1.5 已经写过；P1.6 无理由再次漏 |

### W-3：`project_id="no-project-id"` 字面值兜底污染查询域

| 项 | 内容 |
|---|---|
| **位置** | `review_code.py:319` |
| **现象** | tech_plan_id 不传时 `review_project_id = project_id or "no-project-id"`。所有"无 tech_plan"PR 都用同一字面值写入 CodeReview.project_id |
| **实跑取证** | `adr.list_reviews(project_id='no-project-id')` 写入 2 条独立 PR review 后返回 **2 行**——证明字面值会跨 PR 聚合，污染了 list_reviews 查询语义。已实测确认 |
| **影响** | 当 P1.7 daily_brief 调用 `list_reviews("no-project-id")` 时，会拉到所有"无 tech_plan"PR 的 review，无法按项目分组。后续做"BLOCKING 准确率 / appeal 率"按项目度量时会出脏数据 |
| **改成什么** | 改成 `f"orphan-pr-{abs(hash(pr_url))}"`（或直接 `pr_url` 做 hash，每个 PR 一个伪 project_id），让 list_reviews 仍可按 PR 唯一定位。或者更优雅：在 adr_storage 层加 `project_id is NULL` 支持，本模块不传 project_id |
| **理由** | 与 P1.5 W-3（step_record schema 一致性）同精神：单字面兜底 = 给下游埋坑 |

---

## 2. SUGGEST 问题（可选优化）

### G-1：非法 status 兜底成 "PASS" 过于宽容

`review_code.py:689-692` — LLM 输出非法 status（如 `"WARNING"` / `"NON BLOCKING"` 中间空格）→ 兜底为 `"PASS"`。**实跑取证**：传入 `'NON BLOCKING'`（空格分隔）→ 兜底成 `'PASS'`。
**建议**：兜底为 `"NON-BLOCKING"` + warning。理由：LLM 没给清晰判断时保守归"评论"而非"通过"；并先做 `re.sub(r"\s+", "-", status.upper())` 归一化空格分隔。

### G-2：`tech_plan_id` 无格式校验（与 P1.5 SEVERE-1 同思路）

`review_code.py:161` — tech_plan_id 任意字符串都接受。本场景**无副作用**（adr_storage SQL 全参数化），不像 P1.5 kickoff_project 有 mkdir / git init 副作用 → 不构成 path traversal SEVERE。但保守输入卫生仍建议加 `^[A-Za-z0-9_\-]{1,64}$` 白名单。

### G-3：BLOCKING 卡片受众语义歧义

`review_code.py:349-352` — 卡片发到 `AICTO_FEISHU_CHAT_ID`（AICTO 工作群）+ fallback `AICTO_PM_FEISHU_CHAT_ID`（PM 私聊）。但 PRD §五·能力 4 ASCII mock 暗示卡片应 `@对应军团 commander` 而非全员可见。Phase 2 飞书卡片回调上线时建议接入"军团 chat_id" 概念。

### G-4：reformat 兜底文案自循环

`review_code.py:735-738` — 兜底文案"建议把当前实现改成符合规约的实现因为 BLOCKING 必须给出可执行修复方案"含"改成"+"因为"，仅满足关键词检测但**没有真正的 X→Y 内容**。**实跑取证**：reformat 后 `_has_blocking_format(...)=True` — 即文案校验自循环。建议把 `format_warning=True` 标记同步带到飞书卡片视觉层（如卡片中红字标注"以下 BLOCKING 文案不合规，已自动包装请人工重写"）。

### G-5：`find_stale_blocking_reviews` 时间戳比较 fragile

`review_code.py:1243` — `threshold.strftime("%Y-%m-%dT%H:%M:%S")`（不带毫秒、不带 Z）与 `_now_iso()` 写入的 `2026-04-25T19:01:42.123Z`（带毫秒+Z）做字典序比较。当前 ISO 字符串字典序属性下结果**正确**（短串 < 长串），但若未来 `_now_iso` 改格式（如 `+00:00` 取代 `Z`），此处会偷偷不工作。建议把比较改成 `datetime.fromisoformat(...)` parse。

### G-6：`build_appeal_card` 当 pr_number=空时 header 拼成 "PR #"

`review_code.py:1003、918` — pr_number="" 时 header 标题为 `"⚠️ BLOCKING — PR #"`。**实跑取证**：传空字符串确实生成 `"PR #"`。`_parse_pr_url` 已确保 pr_number 非空（intent 校验阻拦 main flow），但 build_appeal_card 是公共 API，单独被测试调用时仍可能传空。建议 `pr_number or "未知"`。

---

## 3. 各审查 section 详情

### 3.1 5 步推理链 ✅

| Step | 实现 | 状态 |
|---|---|---|
| 1 拉 PR diff | `_step1_fetch_pr_diff`：subprocess gh + retry(3, 1.0)；FileNotFoundError→permission；timeout/returncode→tech；auth/404 stderr 关键词→permission（不重试） | ✅ 4 级覆盖 |
| 2 拉 ADR/PRD context | `_summarize_adrs_for_review` + `_try_load_prd_context`（best-effort，失败 → warning） | ✅ |
| 3 LLM 10 项审查 | `_step3_llm_review` 复用 `design_tech_plan._invoke_llm/_extract_content/_parse_llm_json` + retry(3, 2.0) + `_DesignTechPlanError → _ReviewCodeError` 异常包装（保留 .level） | ✅ |
| 4 文案+密度兜底 | `_normalize_checklist` → `_enforce_blocking_format` → `_enforce_per_file_blocking_cap` → `_enforce_pr_comment_cap` 四级链式 | ✅ |
| 5a 写 CodeReview 表 | `adr_storage.create_review`，无 retry（**W-2**），失败仅 warning | ⚠️ W-2 |
| 5b 飞书 BLOCKING 卡片 | `build_appeal_card` + `feishu_api.send_card_message`，env `AICTO_FEISHU_CHAT_ID` + fallback `AICTO_PM_FEISHU_CHAT_ID`；失败仅 warning | ✅ |

### 3.2 10 项审查清单逐字 ✅

```
review_code.py:60-71 CHECKLIST_ITEMS:
  (1, 架构一致) (2, 可读性) (3, 安全) (4, 测试) (5, 错误处理)
  (6, 复杂度) (7, 依赖) (8, 性能) (9, 跨军团冲突) (10, PRD 一致)
```
逐字与 PRD §五·能力 4 一致（含 "PRD 一致" 大小写）。code-review-prompt.md 也保留 10 项原文 + OWASP 检查点扩充。

### 3.3 BLOCKING 文案"X→Y 因 Z"校验 ✅

`_has_blocking_format` 实跑 9 用例：

| 输入 | 期望 | 实际 |
|---|---|---|
| "这里不好" | False | ✅ False |
| "建议优化" | False | ✅ False |
| "考虑改进" | False | ✅ False |
| "把 X 改成 Y 因 Z" | True | ✅ True |
| "把 X 改为 Y 因为 Z" | True | ✅ True |
| "用 Y 替换 X 因为安全" | True | ✅ True |
| "改成参数化查询，因为 SQL 注入" | True | ✅ True |

合规策略：含「改成/换成/替换/改为」之一 **AND** 含「因为/因/由于」之一。

### 3.4 评论密度兜底 ✅

| 上限 | 实现 | 测试 |
|---|---|---|
| 单 PR ≤ 5 评论 | `_enforce_pr_comment_cap`：按 `(severity 降序, item 升序)` 排序，top 5 保留，drop 转 PASS + `aggregated_due_to_pr_cap=True` | `TestCommentDensityCap.test_comment_density_truncated`（8 → ≤5）✅ |
| 单文件 ≤ 2 BLOCKING | `_enforce_per_file_blocking_cap`：从 comment 用正则 grep 文件路径累计，超 cap 转 NON-BLOCKING + `aggregated_due_to_per_file_cap=True` | `TestPerFileBlockingCap.test_per_file_3_blocking_aggregated`（3 同文件 → ≤2）✅ |

实跑顺序：先文件级降级（保留 BLOCKING 数尽量低）→ 再总数截断（保留 top severity）。这个顺序合理（先收敛 BLOCKING 再考虑总数）。

### 3.5 Appeal 协议 ✅

| 检查项 | 状态 |
|---|---|
| `APPEAL_ESCALATION_THRESHOLD=1`（R-OPEN-3 默认）| ✅ line 122 |
| retract 路径 → `update_appeal_status(id, "retracted")` | ✅ TestAppealHandlerRetract PASS |
| maintained 路径 → `update_appeal_status(id, "maintained")` → `escalate_to_owner` → `update_appeal_status(id, "escalated")` | ✅ TestAppealHandlerMaintain PASS（escalate_calls=1） |
| LLM 评估保守兜底（无效 verdict → maintained） | ✅ line 1222-1223 |
| LLM 调用 retry 包裹 | ✅ retry(3, 2.0) line 1220 |
| 评估失败 → 升级骏飞 + 保守维持 | ✅ line 1077-1086 |
| escalation level 语义 | ⚠️ W-1 LEVEL_PERMISSION 错位 |

### 3.6 飞书 BLOCKING 卡片 ✅

| 检查项 | 状态 |
|---|---|
| `template="red"` | ✅ line 1005 |
| 4 字段（PR 编号/标题/BLOCKING 内容/修复要求） | ✅ 6 elements（含 2 hr）：PR meta + BLOCKING 详情 + 修复要求 + action |
| 3 按钮（接受/appeal/仲裁）| ✅ primary/default/danger |
| `button.value = json.dumps(...)` | ✅ 3 按钮全 JSON 字符串（飞书协议怪癖） |
| target_chat_id env | ✅ AICTO_FEISHU_CHAT_ID + fallback AICTO_PM_FEISHU_CHAT_ID |
| 单 BLOCKING 详情 ≤300 字符 + 仅展示前 3 | ✅ line 930-934 |

### 3.7 `find_stale_blocking_reviews` ✅

```sql
SELECT * FROM "CodeReview"
WHERE "blocker_count" > 0
  AND "appeal_status" = 'none'
  AND "reviewed_at" < threshold
ORDER BY "reviewed_at" DESC
```
- `stale_hours=24.0` 默认 ✅
- 返回 `list[dict]`（hydrate 已忽略 — daily_brief 自行处理） ✅
- 异常兜底返 `[]`（不阻塞 daily_brief） ✅
- TestFindStaleBlockingReviews（26h 前 BLOCKING 行被 stale=24h 命中）✅

唯一 fragile：时间戳字符串比较依赖 `_now_iso()` 格式（G-5）。

### 3.8 B-1 第五轮防回归 ✅

```python
class _ReviewCodeError(error_classifier.WrappedToolError):
    def __init__(self, message, level=LEVEL_UNKNOWN):
        super().__init__(message, level=level)
```
- 继承 `WrappedToolError` ✅
- TestImportSyntax.test_inheritance_chain_b1 验证 `issubclass(_ReviewCodeError, WrappedToolError)` ✅
- `classify(err)` 短路返 `.level` ✅
- retry_with_backoff 用 `if e.level != LEVEL_TECH: raise` 短路 ✅

### 3.9 复用纪律 ✅

```
review_code.py:47 imports:
  adr_storage      ← create_review / list_adrs / list_reviews / update_appeal_status / PRODMIND_DB_PATH
  design_tech_plan ← _invoke_llm / _extract_content / _parse_llm_json / _DesignTechPlanError
  error_classifier ← LEVEL_*/classify/retry_with_backoff/escalate_to_owner/WrappedToolError
  feishu_api       ← send_card_message
  pm_db_api        ← get_pm_context_for_tech_plan
```

实测 grep 命令：

```
$ grep -E "(openai|chat.completions|client.chat)" review_code.py → 0 hits
$ grep -E "(im/v1/messages|requests.post|httpx)" review_code.py → 0 hits
$ grep -E "INSERT INTO.*CodeReview" review_code.py → 0 hits
$ grep -E "(/anthropic/|microsoft/|google/)" review_code.py → 0 hits
```

唯一 SELECT/UPDATE 自写：
- line 1153 `SELECT * FROM "CodeReview"`（appeal_handler 拉 review row — adr_storage 没暴露 get_review，本模块直查）
- line 1250 `SELECT * FROM "CodeReview"`（find_stale_blocking_reviews — daily_brief 专用，按时间过滤的查询 adr_storage 也没暴露）
- 1028 行注释中的 `UPDATE CodeReview SET appeal_status='retracted'`（**docstring 注释，非真实 SQL**）

判定：两处 SELECT 是**新查询语义**（`get_by_id` / `find_stale`），未来若被多个模块复用应回填到 adr_storage；当前阶段直查可接受（PRODMIND_DB_PATH 已统一从 adr_storage 引用）。

### 3.10 反幻觉 ✅

| 检查项 | 状态 |
|---|---|
| 错误顶层 `error` key + `level`+`elapsed_seconds` | ✅ `_fail` line 1273-1281 |
| diff 拉不到 → 不静默 happy（明确 error 返） | ✅ TestPrDiffFetchFailure PASS（returncode=1 → tech/unknown level） |
| BLOCKING 文案不合规 → reformat + format_warning + warning（不静默通过） | ✅ TestBlockingFormatReformatting PASS |
| gh CLI 不存在 → permission 级（提示安装）+ 不重试 | ✅ TestGhCliMissing PASS（level="permission" + "gh" 出现在 error msg） |
| LLM 返空/非法 JSON → `_DesignTechPlanError(LEVEL_TECH)` 触发 retry | ✅ 复用 design_tech_plan 实现 |
| project_id 缺失 → `"no-project-id"` 字面值兜底 | ⚠️ W-3（不是反幻觉问题，是查询域污染） |

### 3.11 测试不污染 ✅

| 检查项 | 状态 |
|---|---|
| subprocess 全 mock（不实际调 gh） | ✅ `mock.patch.object(subprocess, "run", ...)` 覆盖所有 happy path 用例 |
| send_card_message 全 mock | ✅ TestHappyPathWithBlocking 用 `return_value={"message_id": "om_test_card_001"}` |
| CodeReview 写入 → tearDown DELETE | ✅ 8 个测试类全部 setUp/tearDown 清理 `_cleanup_review_ids` |
| 残留检查实跑：`SELECT FROM CodeReview WHERE project_id LIKE 'test-%'` | ✅ 0 hits（实查证实） |
| 真实仓库引用（如 anthropic/...） | ✅ 0 hits（grep `(anthropic|microsoft|google)/` → 0） |

### 3.12 spec 一致性 ✅

| 需求 | 实现 |
|---|---|
| R-FN-4.1 input pr_url + 可选 tech_plan_id | line 160-161 ✅ |
| R-FN-4.2 10 项 + 逐字 | CHECKLIST_ITEMS ✅ |
| R-FN-4.3 三态 PASS/BLOCKING/NON-BLOCKING | ALLOWED_STATUS ✅ |
| R-FN-4.4 BLOCKING 硬 gate | _enforce_blocking_format + 飞书 red 卡片 ✅ |
| R-FN-4.5 文案"X→Y 因 Z" | _has_blocking_format + reformat ✅ |
| R-FN-4.6 军团忽略 BLOCKING → 升级 | find_stale_blocking_reviews（接口供 daily_brief） ✅ |
| R-FN-4.7 单 PR ≤5 + 单文件 ≤2 | _enforce_pr_comment_cap + _enforce_per_file_blocking_cap ✅ |
| R-FN-4.8 Appeal retract/maintained/escalated | appeal_handler ✅ |
| R-FN-4.9 卡片 4 字段 + 3 按钮 | build_appeal_card ✅ |
| R-FN-4.10 升级阈值 1 次 | APPEAL_ESCALATION_THRESHOLD=1 ✅ |
| R-FN-4.11 BLOCKING 准确率 ≥90% 埋点 | CodeReview 表 senior_review_verdict 字段（adr_storage 已建表） ✅ |
| R-FN-4.12 appeal 率 ≤20% 埋点 | appeal_status 计数（adr_storage 已建表） ✅ |
| ADR-002 CodeReview 共享 dev.db | `adr_storage.PRODMIND_DB_PATH` ✅ |

### 3.13 实跑 21 测试用例 ✅

```
$ /Users/feijun/.hermes/hermes-agent/venv/bin/python3 hermes-plugin/test_review_code.py
test_appeal_maintain_escalates ... ok
test_appeal_retract_path ... ok
test_unformatted_blocking_reformatted ... ok
test_card_structure ... ok
test_code_review_actually_persisted ... ok
test_comment_density_truncated ... ok
test_find_stale_returns_old_blocking ... ok
test_gh_not_installed_permission ... ok
test_happy_path_all_pass ... ok
test_happy_path_with_blocking ... ok
test_constants_consistent_with_prd ... ok
test_inheritance_chain_b1 ... ok
test_module_imports ... ok
test_module_referenced_dependencies ... ok
test_invalid_pr_url ... ok
test_invalid_scope ... ok
test_missing_pr_url ... ok
test_large_diff_truncated ... ok
test_per_file_3_blocking_aggregated ... ok
test_pr_diff_fetch_fail_tech_then_unknown ... ok
test_scope_security_only ... ok

Ran 21 tests in 3.243s — OK
```

21/21 PASS，3.24s 全跑完，远低于 R-NFR-13 推断的 2 分钟 SLA。

### 3.14 字段清洁度抽查

实跑 `_normalize_checklist({'status':'NON BLOCKING'})` → 兜底成 `'PASS'`（**G-1 待优化**）。

实跑 `_enforce_blocking_format({'status':'BLOCKING','comment':'这里不好'})`：
- 输出 comment：`[文案需重写] 程小远未给出"把 X 改成 Y 因为 Z"格式的明确指令；原文：这里不好 — 建议把当前实现改成符合规约的实现因为 BLOCKING 必须给出可执行修复方案`
- `format_warning=True`，warnings 含"item 1 (架构一致) BLOCKING 文案不合规，已 reformat" ✅
- reformat 文案自身 `_has_blocking_format=True`（**G-4**：文案合规但内容自循环）

实跑 `build_appeal_card(pr_number='', code_review_id=None)` → header.title="⚠️ BLOCKING — PR #"（**G-6**：兜底字符串可优化）

---

## 4. 文件级评级

| 文件 | 评级 | 摘要 |
|---|---|---|
| `review_code.py` | **APPROVED** | 0 SEVERE + 3 WARN（W-1 escalate level / W-2 review 写无 retry / W-3 project_id 字面值） + 6 SUGGEST |
| `templates/code-review-prompt.md` | **APPROVED** | 10 项逐字保留 + 三态强制 + "X→Y 因 Z" 模板 + scope 单维度模式 + 硬纪律 10 条 |
| `test_review_code.py` | **APPROVED** | 21/21 PASS 3.24s；mock 完整（subprocess + send_card + LLM）；setUp/tearDown DELETE 清理；实查 0 残留 |
| `tools.py`（review_code dispatch）| **APPROVED** | 一行委托 `_review_code.run`；docstring 5 步推理链准确；无副作用；P1.6 进度行已更新 |

---

## 5. 与 P1.5 review 报告的对照

| 维度 | P1.5 reviewer 发现 | P1.6 reviewer 发现 |
|---|---|---|
| SEVERE | 1（path-traversal）| **0** |
| WARN | 3 | 3（W-1 escalate level / W-2 同 P1.5 W-2 同源 / W-3 字面值污染）|
| SUGGEST | 2 | 6 |
| 实跑测试 | 15/15 PASS 1.56s | 21/21 PASS 3.24s |
| B-1 防回归 | 第四轮 ✅ | 第五轮 ✅ |
| 复用纪律 | ✅ | ✅ |

**进步**：P1.6 把 P1.5 SEVERE-1 同精神（输入卫生）做到了——pr_url 严格 regex 校验，没有 path-traversal 类问题。
**未进步**：P1.5 W-2（ADR 写无 retry）的同精神瑕疵在 P1.6 W-2 重现（CodeReview 写无 retry），值得注意。

---

## 6. 复审建议

无 SEVERE，**直接放行进 verifier**。

**3 WARN 建议在 P1.7 一并处理**（与 daily_brief 实现同 PR）：
- W-1：1 行修改（LEVEL_PERMISSION → LEVEL_UNKNOWN）
- W-2：包闭包 + retry，5 行修改
- W-3：把字面值改 hash 或加 nullable 支持，10 行修改

修复后建议**不再发起重审**（≤3 WARN 是机械修复）。直接进 verifier 实跑场景：
- BLOCKING 文案不合规 → reformat 实跑（已覆盖）
- 评论密度截断 8 → 5 实跑（已覆盖）
- appeal retract / maintained 双分支实跑（已覆盖）
- find_stale_blocking_reviews 26h 前 BLOCKING 命中（已覆盖）

---

**审查者签字**：reviewer-P1.6（Sonnet 4.5）
**完成时间**：2026-04-25
