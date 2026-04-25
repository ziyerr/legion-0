# REVIEW-P1.5 — kickoff_project（能力 0）批量审查报告

> **审查者**：reviewer-P1.5（Sonnet 4.5）
> **审查时间**：2026-04-25
> **审查范围**：
> - `hermes-plugin/kickoff_project.py`（1287 行）
> - `hermes-plugin/test_kickoff_project.py`（791 行）
> - `hermes-plugin/tools.py`（dispatch 接入，148 行）
> **依据**：REQUIREMENTS §1.1（R-FN-0.1~0.6）/ PHASE-PLAN §6 / PRD-CAPABILITIES 能力 0 / ADR-008 / pm-clarification-20250425-1505+1515 / B-1 防回归（reviewer-P1.2）

---

## 0. 综合评级

| 维度 | 状态 |
|---|---|
| 8 步完整性 | ✅ 8/8 串联 + 步骤记录 + step_results 8 键齐全 |
| 30s SLA | ✅ 实测 1.56s（15 测试用例总耗时） |
| 4 级错误分类覆盖 | ⚠️ 步骤 1/2/4 完整，步骤 6 缺 `escalate_to_owner`（一致性瑕疵） |
| 降级三策（PM/legion/飞书） | ✅ PM 离线 + legion.sh 失败 + 飞书失败均不阻塞 |
| 复用纪律 | ✅ 0 重定义军团/飞书/ADR primitives；5 个 import 全部命中 |
| 反幻觉 | ✅ 错误顶层 `error` key + `level` + `step_failed` + degraded 状态明确 + local-uuid 显式 |
| 实测 15 用例 | ✅ ALL PASS（1.563s / 0 残留目录 / 0 残留 ADR 行） |
| **path traversal 输入校验** | ❌ **SEVERE — `project_name` 未约束，可逃逸 `~/Documents/`** |

**统计**：1 SEVERE / 3 WARN / 2 SUGGEST
**结论**：**REJECTED — 1 BLOCKING（path-traversal）必修后放行**

---

## 1. BLOCKING 问题（SEVERE — 必修）

### S-1：`project_name` 路径穿越（path traversal）

| 项 | 内容 |
|---|---|
| **位置** | `kickoff_project.py:127, 154` |
| **现象** | 入参校验（line 127）只判 `非空 + isinstance str + strip()`，未约束字符集；line 154 直接 `os.path.expanduser(f"~/Documents/{project_name}")` 拼接路径 |
| **影响** | 调用方传 `project_name='../../../tmp/EVIL'` → `os.path.abspath(git_path)='/tmp/EVIL'` → mkdir / git init / 写 ADR-0001 全在沙箱外。同样可命中 `/Users/feijun/.ssh/foo`、`/Users/feijun/Library/...`。已实跑确认（probe 输出：`'../../../tmp/EVIL_TEST' → '/tmp/EVIL_TEST'`） |
| **改成什么** | 加正则白名单：`^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿\-]{0,63}$`（首字符必须字母数字下划线或汉字，其后允许连字符，禁 `/` `..` 控制字符空格起首点）。校验失败抛 LEVEL_INTENT 给 PM 选项 |
| **理由** | CTO 拥有 mkdir + git init + 写 ADR 的副作用，写错位置会污染用户 fs；PM agent 可能因 LLM 幻觉传出非法名（hermes 上游不保证 schema 校验深度）；R-NFR-30 已为 design_tech_plan 设了路径白名单，kickoff 写路径权力更大反而无校验 — 不一致 |
| **修复参考** | `schemas.py:KICKOFF_PROJECT.project_name` 同步加 `"pattern": "^[A-Za-z0-9_\\u4e00-\\u9fff][A-Za-z0-9_\\u4e00-\\u9fff\\-]{0,63}$"`，**双层防御**（schema + 运行时）|

> 这是 **8 步副作用工具** 的输入卫生硬纪律，必修。

---

## 2. WARN 问题（应修，非阻塞）

### W-1：step 6（mailbox）缺 `escalate_to_owner`，与 step 1/2/4 不一致

| 项 | 内容 |
|---|---|
| **位置** | `kickoff_project.py:282-307` |
| **现象** | step 1/2/4 在 `_KickoffProjectError` / `Exception` 分支都有 `if e.level in (LEVEL_PERMISSION, LEVEL_UNKNOWN): escalate_to_owner(...)`；step 6 两个分支都没有 |
| **影响** | 假如 `legion_api.mailbox_protocol_serialize` 因未来变更产生 PERMISSION/UNKNOWN，骏飞收不到升级通知（违反 R-NFR-22 "保守升级"约束） |
| **改成什么** | 仿 step 1/2/4 在 line 295 和 line 305 加：`if level in (LEVEL_PERMISSION, LEVEL_UNKNOWN): error_classifier.escalate_to_owner(level, e, {"phase": "step6_build_mailbox", "project_id": project_id})` |
| **理由** | 当前实现 mailbox_protocol_serialize 抛 `LegionError`（intent 级），看似不会触发 — 但 **代码一致性 = 防未来回归**；模块头注释承诺"4 级分类全 8 步覆盖"，step 6 是漏 |

### W-2：step 4（ADR 写）未走 `retry_with_backoff`

| 项 | 内容 |
|---|---|
| **位置** | `kickoff_project.py:706-726` |
| **现象** | `adr_storage.create_adr(...)` 直接调用，无 retry。step 2（git init）和 step 3（PM HTTP）都包了 `retry_with_backoff(_do_X, max_retries=3, base_delay=0.5)` |
| **影响** | sqlite "database is locked"（多 profile 并发写共享 dev.db）按 PM 澄清 R-OPEN-2 是**技术级**（"退避重试，3 次仍失败→权限级升级骏飞"）。当前代码会被 `except Exception` 兜底分类为 tech 级 fail，但**不重试**直接失败 — 与 PM 仲裁不符 |
| **改成什么** | 把 `adr = adr_storage.create_adr(...)` 包成 `_do_adr_write` 闭包，外面 `error_classifier.retry_with_backoff(_do_adr_write, max_retries=3, base_delay=0.2)`（base_delay 比 git init 短，sqlite 锁通常很快释放） |
| **理由** | PM 澄清明确"sqlite locked → 退避重试"。kickoff 目标 30s SLA + 0.2/0.4/0.8s 的退避完全留得起 |

### W-3：step 5 success 分支字段不一致

| 项 | 内容 |
|---|---|
| **位置** | `kickoff_project.py:788-801` vs `850-866` |
| **现象** | `legion.sh` 成功 + discover 找到 commander 时返回的 step_record 没有 `online_legion_count` 字段；fallback 分支有。两条返回路径字段集不一致 |
| **影响** | 下游观测/度量埋点拿 `step_results["5_legion"]["online_legion_count"]` 时偶发 KeyError；测试 `TestHappyPath` 没断言这个字段所以漏掉 |
| **改成什么** | 在 line 800 之前 `commanders = [...]` 后，把 `len(commanders)` 写进 success step_record |
| **理由** | step_record schema 一致性 = 下游可写少一行 if/else |

---

## 3. SUGGEST 问题（可选优化）

### G-1：step 3 PM HTTP 持续 5xx 后静默降级，骏飞看不到 PM 重伤

| 项 | 内容 |
|---|---|
| **位置** | `kickoff_project.py:548-567` |
| **现象** | `retry_with_backoff` 用尽后 → `_step3_degraded(...)`。日志写入 `kickoff_pm_degraded.log` 并尝试通知 PM 飞书，但**不通知骏飞** |
| **建议** | 区分两种降级：(a) 单次 `ConnectionError`（PM 离线 — 静默降级 OK）；(b) 重试 3 次后仍失败（PM 在线但持续报错 = 重伤）。后者额外调一次 `error_classifier.escalate_to_owner(LEVEL_UNKNOWN, e, {"phase": "step3_pm_persistent_5xx"})` 让骏飞介入。理由：当前设计将所有"非 ConnectionError"都吞成 degraded，等于把 R-NFR-22 的"保守升级"在这一步关闭。 |

### G-2：placeholder task 没回显用户 `description`

| 项 | 内容 |
|---|---|
| **位置** | `kickoff_project.py:935-959` |
| **现象** | `_step7_dispatch_initial` 构造的占位任务 `description` 是模板文本，不携带用户 `args["description"]` |
| **建议** | 在任务正文里附一句 `f"PM 给的项目梗概：{description or '（未提供）'}"`，让军团 standby 时知道在等什么。理由：PM 简介是**最便宜的语境**，丢了可惜。 |

---

## 4. 各审查 section 详情

### 4.1 8 步完整性 ✅

| Step | 实现 | 状态 |
|---|---|---|
| 1 mkdir | `_step1_mkdir` 已存在→intent / PermErr→permission / OSError→tech | ✅ 4 级齐 |
| 2 git init | `_step2_git_init` subprocess + `retry_with_backoff(max_retries=3)` | ✅ 重试齐 |
| 3 PM HTTP | `_step3_create_pm_project` ConnErr/Timeout/5xx/404 全降级；retry 3 次；`projectId` 缺失也降级 | ✅ ADR-008 协议对齐 |
| 4 ADR-0001 | `_step4_write_adr` `number` 不传 → `_next_adr_number` 兜底 = 1；3 alternatives（chosen=True 的方案 = 8 步串联）；`decided_by="AICTO"` | ✅ |
| 5 legion | `_step5_provision_legion` legion.sh + discover_online_commanders 兜底 + skill 启发式 | ✅ |
| 6 mailbox | `_step6_build_mailbox` 走 `legion_api.mailbox_protocol_serialize`（不重写）+ cto_context 注入 | ✅ |
| 7 dispatch | `_step7_dispatch_initial` placeholder task 走 `dispatch_balanced.run`（不直接调 wrapper） | ✅ |
| 8 飞书 | `_step8_send_kickoff_card` + `build_kickoff_card`（5 字段 + 3 按钮 + green template + button.value json.dumps） | ✅ |

### 4.2 飞书卡片 schema ✅

逐字段对照 PRD-CAPABILITIES 能力 0 ASCII mock：
- 5 字段：项目名 / Path / Legion / ADR / 状态 ✅
- 3 按钮：[查看 ADR](primary) [加入军团群](default) [暂停项目](danger) ✅
- 文案"等 PM 发 PRD 启动首批任务" ✅
- `template="green"` ✅
- 全部 button.value 是 `json.dumps(...)` 字符串（飞书协议怪癖）✅

### 4.3 复用纪律 ✅

```
imports（kickoff_project.py:52-58）:
  adr_storage  ← create_adr
  dispatch_balanced  ← run（底层实现，绕过 tools.py wrapper）✅
  error_classifier  ← LEVEL_*/classify/retry_with_backoff/escalate_to_owner/WrappedToolError
  feishu_api  ← send_card_message / send_text_to_chat
  legion_api  ← discover_online_commanders / mailbox_protocol_serialize / Commander
```

实测命令：
```
$ grep "重定义检查" → 0 命中
$ grep -E "(def discover_online_commanders|def mailbox_protocol_serialize|def send_card_message|INSERT INTO.*ADR)" kickoff_project.py
  9:  4. INSERT INTO ADR ... ◄── ADR-002   # 仅文档注释，无 SQL 重写
```

### 4.4 B-1 防回归（reviewer-P1.2 第四轮固化）✅

```python
class _KickoffProjectError(error_classifier.WrappedToolError):  # 继承 WrappedToolError ✅
    def __init__(self, message, level=LEVEL_UNKNOWN):
        super().__init__(message, level=level)
```

测试 `TestImportSyntax.test_inheritance_chain_b1` 验证：
- `issubclass(_KickoffProjectError, WrappedToolError)` ✅
- `classify(err)` 直接返回 `.level`（短路，不走关键词匹配）✅
- `retry_with_backoff` 用 `if e.level != LEVEL_TECH: raise` 短路 ✅

### 4.5 反幻觉 ✅

- 错误顶层 `error` key（line 1267 `body = {"error": message, ...}`）✅
- `step_failed` 字段标识失败步骤 ✅
- `step_results` 中 `degraded` 状态显式存储 ✅
- PM 不在线 → `project_id = f"local-{uuid.uuid4()}"` 显式前缀 ✅，warning 文本"PM 需手动补建"明示 ✅
- 测试 `TestPMReturnsNoProjectId` 断言 `project_id.startswith("local-")` ✅

### 4.6 测试不污染 ✅

- 副作用 mock：`requests.post` / `subprocess.run` / `legion_api.discover_online_commanders` / `feishu_api.send_card_message` / `dispatch_balanced.run` 全部隔离
- 真实落盘场景：`TestRealMkdirAndGitInit` 选择性 mock（仅 mock legion.sh，git init 真跑）
- tearDown 清理：`shutil.rmtree(self.test_path, ignore_errors=True)` + `DELETE FROM ADR WHERE id=?`
- 实跑后核查：
  - `ls ~/Documents/ | grep AICTO_kickoff` → 0 残留 ✅
  - `SELECT COUNT(*) FROM ADR WHERE title LIKE '%项目启动%' AND decided_by='AICTO'` → 0 残留 ✅

### 4.7 实跑 15 测试用例 ✅

```
$ /Users/feijun/.hermes/hermes-agent/venv/bin/python3 hermes-plugin/test_kickoff_project.py
test_adr_actually_written_to_sqlite ... ok
test_blank_project_name ... ok
test_invalid_priority ... ok
test_missing_project_name ... ok
test_card_5_fields_3_buttons ... ok
test_pm_offline_degrade ... ok
test_happy_path_all_8_steps ... ok
test_inheritance_chain_b1 ... ok
test_module_imports ... ok
test_module_referenced_dependencies ... ok
test_legion_sh_fail_fallback_idle_legion ... ok
test_pm_returns_no_project_id_degrades ... ok
test_existing_dir_returns_intent_level ... ok
test_real_mkdir_and_git_init_create_git_dir ... ok
test_happy_path_under_sla ... ok

Ran 15 tests in 1.563s — OK
```

15/15 PASS，1.56s 全跑完，30s SLA 余量充足。

### 4.8 ADR-008 协议对齐 ✅

| 字段 | 规约（PM 澄清 2026-04-25） | 实现 |
|---|---|---|
| 端点 | `POST http://localhost:8642/api/tools/create_project` | line 73 ✅ |
| 请求体 | `{"name": "项目名", "description": "描述"}` | line 493 ✅ |
| 响应 | `{"projectId": "uuid", ...}` | line 570 `payload.get("projectId")` ✅ |
| 离线降级 | "本地记录 + 飞书通知 PM 手动补建" | `_step3_degraded` 写 `kickoff_pm_degraded.log` + send_text_to_chat ✅ |
| 默认 chat_id | `oc_1d531eb5d70e3a415f728260f1bf7a7a` | line 68 `DEFAULT_AICTO_CHAT_ID` ✅ |

---

## 5. 文件级评级

| 文件 | 评级 | 摘要 |
|---|---|---|
| `kickoff_project.py` | **REJECTED** | 1 SEVERE（path-traversal）+ 3 WARN + 2 SUGGEST |
| `test_kickoff_project.py` | APPROVED | 15 用例全过；mock 完整；清理无残留；建议补 1 个 path-traversal 拒绝用例（修 SEVERE-1 时一并加）|
| `tools.py`（kickoff 接入部分）| APPROVED | dispatch 一行委托给 `kickoff_project.run`；docstring 准确；无副作用 |

---

## 6. 复审建议

修 SEVERE-1 即可放行。WARN-1/2/3 + SUGGEST-1/2 可在同一 PR 顺手修，也可记 TechDebt 后续 P1.6 一并清理。

修复后建议**不再发起重审**（≤3 SEVERE + WARN 是机械修复），直接进 verifier 实跑场景：
- path-traversal 拒绝（intent 级 + step_failed=0_validate_args）
- step 4 sqlite locked 重试（mock `_cto_own_connect` 抛 OperationalError 前 2 次 + 第 3 次 OK）
- step 6 mailbox PERMISSION 升级（mock LegionError 改为 PermissionError）

---

**审查者签字**：reviewer-P1.5（Sonnet 4.5）
**完成时间**：2026-04-25
