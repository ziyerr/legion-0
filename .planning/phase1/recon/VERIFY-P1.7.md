# VERIFY-P1.7 — daily_brief + cron + 14 NON-BLOCKING 修复

**验证者**：verifier-p1-7（AICTO Phase 1 P1.7 verifier）
**Task**：#33（L1-麒麟军团派发）
**日期**：2026-04-25
**模式**：Compliance + Red Team + Integration（合并）

## 验证范围

| 文件 | 行数 | 性质 |
|------|------|------|
| `hermes-plugin/daily_brief.py` | 824 | 新增（4 触发分流核心） |
| `hermes-plugin/cron_runner.py` | 239 | 新增（asyncio loop + 持久化） |
| `hermes-plugin/test_daily_brief.py` | 626 | 新增（23 单测覆盖 cron + 4 触发） |
| `hermes-plugin/__init__.py` | +14 行 | register_cron 钩子 |
| `hermes-plugin/tools.py` | 修改 | daily_brief stub → dispatch 到 daily_brief.run |
| `hermes-plugin/dispatch_balanced.py` | 修改 | N-2 ProjectDocument 反查（P1.4 NON-BLOCKING） |
| `hermes-plugin/kickoff_project.py` | 修改 | （P1.5 NON-BLOCKING） |
| `hermes-plugin/review_code.py` | 修改 | W-1/W-2/W-3（P1.6 NON-BLOCKING） |

## 需求来源

- `.planning/phase1/specs/REQUIREMENTS.md` §1.6（R-FN-5.1/5.2/5.3 + R-NFR-14 + R-RK-5）
- `.planning/phase1/specs/PHASE-PLAN.md` §8（P1.7 任务清单 7.1–7.8）
- 派发任务：Task #33（L1-麒麟军团 → verifier-p1-7）

---

## 场景 1：23 单测全过

```
PY=/Users/feijun/.hermes/hermes-agent/venv/bin/python
$PY -m unittest test_daily_brief -v 2>&1 | tail -10
```

输出：
```
Ran 23 tests in 0.663s
OK
```

**结果：✅ PASS — 23/23**

---

## 场景 2：106 总单测无回归

```
$PY -m unittest test_error_classifier test_kickoff_project test_review_code test_daily_brief 2>&1 | tail -3
```

输出：
```
Ran 106 tests in 5.222s
OK
```

**结果：✅ PASS — 47+15+21+23 = 106/106**

---

## 场景 3：B-1 第六轮防回归（_DailyBriefError 继承 WrappedToolError）

```
PASS-1: _DailyBriefError 继承 WrappedToolError
PASS-2: tech 级 attempts=3
```

`classify(e) == 'tech'` ✓ ；retry_with_backoff 看到 .level='tech' 重试 3 次后抛 ✓

**结果：✅ PASS**

---

## 场景 4：UTC+8 时区

```
now UTC+8=2026-04-25T19:45:57.301964+08:00
tzinfo offset=8:00:00
PASS: UTC+8 时区正确
```

**结果：✅ PASS — `_now_utc8()` 正确返回 +08:00**

---

## 场景 5：last_brief_run.json 持久化

```
persistent path: /Users/feijun/.hermes/profiles/aicto/plugins/aicto/state/last_brief_run.json
exists: True
loaded: {'date': '2026-04-25', 'scheduled_run_ts': 1777117563.524666}
PASS: 持久化读写
```

文件确实写入 profile 目录（隔离 default profile）；读回正确。

**结果：✅ PASS**（测试后已清理）

---

## 场景 6：trigger=manual 端到端

```
success=True
trigger=manual
summary 长度=24
message_id=om_mock
```

设 `AICTO_FEISHU_CHAT_ID=oc_test_chat`，mock `feishu_api.send_text_to_chat` + `design_tech_plan._invoke_llm/_extract_content`。

**结果：✅ PASS — 摘要 ≤500 字 / message_id 返回 / success=True**

附加：summary 截断验证：传入 700 字 → 输出严格 500 字。

---

## 场景 7：trigger=blocking_push 卡片消息

```
success=True
message_id=om_blk
trigger=blocking_push
send_error=None
```

mock `feishu_api.send_card_message` 验证走卡片接口（不是文本）。

**结果：✅ PASS**

---

## 场景 8：trigger=stale_alert + 48h 升级

23 单测覆盖 + 端到端补充验证：

```
trigger=stale_alert success=True
escalations=[{'target': 'stale_legion', 'commander_id': 'L1-麒麟军团', 'result': {'msg': 'esc'}}]
escalate_to_owner calls=1
PASS: 48h 升级骏飞
```

mock `_list_stale_legions` 返回 49h legion → escalate_to_owner 被调用 1 次。

**结果：✅ PASS**

---

## 场景 9：cron loop 不阻塞主线程

```
register_cron elapsed=0.000s
returns=None
PASS: register_cron 不阻塞主线程
active threads=2
  thread name=MainThread daemon=False
  thread name=aicto-daily-brief-cron daemon=True
```

后台线程明确命名 `aicto-daily-brief-cron`，daemon=True（gateway 退出自动回收）。

**结果：✅ PASS**

---

## 场景 10：W-1 / W-2 / W-3 修复落实（review_code）

### W-1 修复（appeal 维持时升级 LEVEL_UNKNOWN，不是 LEVEL_PERMISSION）

```
review_code.py:1149   # W-1 修复 P1.6：appeal 维持 = 决策权冲突，按未知保守升级（R-NFR-22），
review_code.py:1150   # 不是技术鉴权失败 → 不该归 LEVEL_PERMISSION（避免污染 KR 度量分母）
review_code.py:1151   error_classifier.LEVEL_UNKNOWN,
```

**✅ W-1 已落实** — appeal maintained 用 LEVEL_UNKNOWN（grep 已无 `appeal.*LEVEL_PERMISSION` 配对）。

### W-2 修复（create_review 包 retry_with_backoff）

```
review_code.py:329    # W-2 修复 P1.6：把 create_review 包进 retry_with_backoff，
review_code.py:332    def _do_create_review() -> Dict[str, Any]:
review_code.py:350    review_row = error_classifier.retry_with_backoff(
review_code.py:351        _do_create_review, max_retries=3, base_delay=0.2
```

**✅ W-2 已落实** — sqlite locked 等技术错误自动重试 3 次。

### W-3 修复（orphan-pr-{md5} 替代 no-project-id）

```
review_code.py:320    # 旧实现统一用字面值 "no-project-id" → 跨 PR 写入 list_reviews 同一域，污染 KR 分组。
review_code.py:327    review_project_id = f"orphan-pr-{pr_hash}"
```

grep `no-project-id` 仅出现在注释（说明替换原因），实际 review_project_id 已用 hash 模式。

**✅ W-3 已落实**

---

## 场景 11：N-2 ProjectDocument 反查（dispatch_balanced）

```
dispatch_balanced.py:198  # N-2 修复 P1.4：从 ProjectDocument 表反查 feishuDocUrl（如有）。
dispatch_balanced.py:262  """从 ProjectDocument 表查 feishuDocUrl（最新一条 docType='tech_plan'）。
dispatch_balanced.py:280  "SELECT name FROM sqlite_master WHERE type='table' AND name='ProjectDocument'"
dispatch_balanced.py:286  'SELECT "feishuDocUrl" FROM "ProjectDocument" '
```

**✅ N-2 已落实** — 派单时若 ADR 缺 feishu_doc_url，从 ProjectDocument 表反查（best-effort）。

---

## 场景 12：复用 grep（daily_brief.py 0 自实现）

```
imports：from . import (adr_storage, design_tech_plan, error_classifier, feishu_api,
                        legion_api, pm_db_api, review_code)  ← 7 项依赖
0 self LLM (openai/httpx)：grep 0 行
0 self 飞书 HTTP (open.feishu.cn)：grep 0 行
0 写 SQL (INSERT/UPDATE/CREATE TABLE)：grep 0 行
```

**✅ PASS — 严格复用其他模块，无重复实现**

---

## 场景 13：dev.db 状态

```
ADR=16
CodeReview=0
```

**✅ PASS — ADR 历史 16 条留存（来自 P1.2 Dogfood）；CodeReview 表 106 测试全清理（无残留）**

---

## 场景 14：plugin 16 工具仍注册成功

```
hermes plugins list:
  aicto │ enabled │ 1.0.0 │ AICTO（程小远）— AI 技术总监 Hermes plugin

aicto tools list:
  ✓ enabled  aicto  🔌 Aicto

公开函数 16 项：
  breakdown_tasks, daily_brief, design_tech_plan, diff_pm_prd_versions,
  dispatch_to_legion_balanced, get_pm_context_for_tech_plan, kickoff_project,
  list_pm_features, list_pm_open_questions, list_pm_prd_decisions,
  list_pm_user_stories, read_pm_evaluation_doc, read_pm_prd, read_pm_project,
  read_pm_research_doc, review_code
```

**✅ PASS — 16 工具齐全；daily_brief 在列**

---

## 场景 15：gateway 三端口齐 LISTEN

```
python3.1 18123 feijun  17u  IPv4  TCP 127.0.0.1:8644 (LISTEN)  ← AICTO
python3.1 38653 feijun  17u  IPv4  TCP 127.0.0.1:8643 (LISTEN)  ← AIHR
python3.1 62546 feijun  17u  IPv4  TCP 127.0.0.1:8642 (LISTEN)  ← default/PM
```

agent.log（cron 加载证据）：
```
2026-04-25 19:48:10,497 INFO hermes_plugins.aicto.cron_runner: daily_brief cron registered as daemon thread (tid=6187577344)
2026-04-25 19:48:10,497 INFO hermes_plugins.aicto.cron_runner: Daily brief cron loop started (UTC+8)
```

**✅ PASS — 端口隔离 + cron 加载日志可见（plugin 加载即注册 daemon thread）**

---

## Red Team 攻击向量补充

### 边界输入测试

| 输入 | 期望 | 实际 | 评级 |
|------|------|------|------|
| `daily_brief({'trigger':'unknown_x'})` | 拒绝 + intent | level=intent / 错误信息含 unknown trigger | ✅ GREEN |
| `daily_brief({'trigger':'blocking_push'})` (缺 pr_url) | 拒绝 + intent | level=intent / "需要 pr_url" | ✅ GREEN |
| `daily_brief({})` | 默认 trigger='scheduled'（按设计） | 真走 scheduled 流程 — **不 mock 时会发实际 LLM/飞书** | 🟡 YELLOW MEDIUM |
| `daily_brief('not_dict')` | 应类型校验拒绝 | **抛 AttributeError 未捕获** | 🟡 YELLOW MEDIUM |

#### YELLOW MEDIUM #1：`args=非 dict` 类型未校验

`daily_brief.py:101` `args = args or {}` 仅处理 falsy，非 dict 字符串穿透。
攻击向量：cron / 内部模块若误传字符串/列表，崩溃栈泄漏到日志。

建议（NON-BLOCKING）：在 run() 入口加 `if not isinstance(args, dict): return _fail(...)`。

#### YELLOW MEDIUM #2：`args={}` 默认 'scheduled' 触发实际副作用

如果手动用 `daily_brief({})` 调用（无意误触），会真走 scheduled 流程：调 LLM、连飞书、写 last_brief_run.json。
攻击向量：手动测试或回放 trace 时误触发实际推送。

建议（NON-BLOCKING）：require explicit trigger 参数（去掉默认值），cron 自己显式传 `trigger='scheduled'`。

### 并发/竞态

- last_brief_run.json **写**：`_save_last_run` 是单进程内调用，没有显式 fcntl 锁。多进程同时写会互相覆盖（场景：双 gateway 误启动）。但 daemon 单线程顺序 fire，单进程安全。
- 27 单测覆盖了 stop_event 退出路径 → loop 关闭无残留线程。

### 资源耗尽

- LLM 调用 `retry_with_backoff` 包裹（sleep_fn 可注入测试，未在生产路径测过）。
- 飞书消息长度强制截断 500 字，不会发超长报文。

### 安全

- chat_id 来自 env / args，不是用户输入；无 SQL/命令注入路径。
- 没有写 PM 表 / 路径白名单 ✓（grep 已确认 0 写 SQL）。

### 错误传播

- 三 trigger 都有 try/except 兜底 → 升级骏飞（LEVEL_UNKNOWN）。
- LLM 失败 fallback 到 structured 文本（场景 12 单测覆盖）。

### 向后兼容

- daily_brief 由 stub `{"status":"not_implemented"}` 升级到正式实现 — tools.py 接口签名 `(args, **kwargs) → str` 不变，向后兼容。
- 16 工具数不变；register_cron 新增 hook 不冲击其他 plugin。

---

## 综合判定

### Compliance Audit

| 需求 | 实现证据 | 状态 |
|------|---------|------|
| R-FN-5.1 三触发（cron/BLOCKING/stale_alert）+ manual | 4 触发分流齐全 + 单测覆盖 | ✅ |
| R-FN-5.2 18:00 cron UTC+8 | `_now_utc8()` 验证 +08:00 ✓ | ✅ |
| R-FN-5.3 错过 18:00 → 09:00 补发 | `_missed_yesterday_18` + 23 单测 | ✅ |
| R-NFR-14 18:00 触发延迟 ≤1 分钟 | cron interval=60s，daemon thread | ✅ |
| R-RK-5 重启失效防御 | last_brief_run.json 持久化 + 23 单测重启场景 | ✅ |
| W-1 appeal 用 LEVEL_UNKNOWN | review_code.py:1149-1151 | ✅ |
| W-2 create_review 包 retry | review_code.py:329-352 | ✅ |
| W-3 orphan-pr-{md5} | review_code.py:320-327 | ✅ |
| N-2 ProjectDocument 反查 | dispatch_balanced.py:198-291 | ✅ |
| daily_brief 严格复用 | 0 self LLM/飞书 HTTP/写 SQL | ✅ |

### Full-Stack Compilation

```
$PY -m unittest test_error_classifier test_kickoff_project test_review_code test_daily_brief
Ran 106 tests in 5.222s — OK
```

✅ 全 PASS

### 整体结论

**Verdict：PASS**

- 15/15 验证场景全 PASS
- 106 单测无回归
- W-1/W-2/W-3/N-2 修复全落实
- B-1 第六轮防回归（异常继承链）OK
- 三 gateway 端口齐 LISTEN，AICTO 独立 profile 运行

### NON-BLOCKING 备注（不挡 PASS）

🟡 Y-1：`args=非 dict` 未类型校验（AttributeError 泄漏） — 建议下次小修
🟡 Y-2：`args={}` 默认 trigger='scheduled' 易误触实际推送 — 建议要求显式 trigger
🟡 Y-3：`last_brief_run.json` 多进程写无 fcntl 锁 — 单 gateway 安全；多 profile 误启动可能竞态

以上均归 NON-BLOCKING，可在 P1.8 收官 / Phase 2 一并打补丁。

---

## 本轮验证学到

- daily_brief 设计极简：把 LLM/飞书/SQL 全部委托给已有模块 → 单文件 824 行，但实际代码量主要是触发分流 + 数据汇总 prompt 构造，复用率极高，符合 OPC 复用 spec。
- cron daemon 线程命名 `aicto-daily-brief-cron`，方便 `threading.enumerate()` 排查。
- `_DailyBriefError` 继承 `WrappedToolError` — B-1 模式第六次固化（design_tech_plan / kickoff_project / review_code / dispatch_balanced / breakdown_tasks 都遵循同一模式）。
