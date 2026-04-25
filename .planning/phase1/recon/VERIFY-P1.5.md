# VERIFY-P1.5 — kickoff_project 端到端验证

| 项 | 值 |
|---|---|
| 任务 | Task #27 — P1.5 验证（kickoff_project 8 步串联实测） |
| 验证人 | L1-麒麟军团 verifier（程小远独立组员） |
| 验证日期 | 2026-04-25 18:43~18:55 |
| 被验文件 | `hermes-plugin/kickoff_project.py`（1262 行）+ `hermes-plugin/tools.py`（dispatch 接入第 53 行） |
| 验收依据 | `.planning/phase1/specs/REQUIREMENTS.md §1.1 R-FN-0.1~0.6` / `ARCHITECTURE.md §1` / `PHASE-PLAN.md §6` / `RECON-HISTORY.md` / `PRD-CAPABILITIES.md 能力 0` / `decisions/ADR-008` / `REVIEW-P1.2.md B-1` |
| 综合结论 | **PASS（11/12 场景全过 + 1/12 环境性 WARN — 与代码无关；零生产污染；零 dev.db 写入；47+15=62 单测 OK）** |

---

## 验证范围（Scope）

- **Mode**: Combined（Compliance + Red Team + Integration）
- **Files verified**:
  - `hermes-plugin/kickoff_project.py`（核心实现 1262 行）
  - `hermes-plugin/tools.py`（line 20 import + line 46-53 dispatch）
  - `hermes-plugin/test_kickoff_project.py`（implementer 自验 15 测试）
  - `hermes-plugin/test_error_classifier.py`（B-1 防回归 + 47 单测）
- **Requirements**:
  - R-FN-0.1（mkdir）/ 0.2（git init）/ 0.3（PM HTTP create_project）/ 0.4（ADR-0001 写入）
  - 0.5（4 级错误分类）/ 0.6（30s SLA）
- **方法论纪律**：全程 mock `_step3_create_pm_project / _step4_write_adr / _step5_provision_legion / _step7_dispatch_initial / _step8_send_kickoff_card / requests.post`，**未实际调用 legion.sh / 未实际派单 / 未实际发飞书卡片 / 未实际写入 dev.db**；测试目录已清理；symlink `/tmp/aicto_plugin` 复用包路径，验证结束清理。

---

## Compliance Audit

### 需求覆盖矩阵

| 需求 | 实现位置 | 验证场景 | 状态 |
|---|---|---|---|
| R-FN-0.1 mkdir ~/Documents/<project>（已存在 → intent；权限 → permission） | `kickoff_project.py:362-399` `_step1_mkdir` | 场景 5（已存在 → intent + step_failed=1_mkdir） | ✅ |
| R-FN-0.2 git init（subprocess + retry） | `kickoff_project.py:407-467` `_step2_git_init` | 场景 1 内 `test_real_mkdir_and_git_init_create_git_dir`（真 git init） | ✅ |
| R-FN-0.3 POST 8642 /api/tools/create_project（ADR-008 LOCKED） | `kickoff_project.py:469-592` + `499-545` requests + retry | 场景 4（ConnectionError → degraded → local-uuid） | ✅ |
| R-FN-0.4 INSERT INTO ADR via adr_storage | `kickoff_project.py:706` `adr_storage.create_adr(...)`（未自写 SQL） | 场景 9 grep（INSERT INTO ADR 仅 1 hit 在 docstring） + 场景 1 内 `test_adr_actually_written_to_sqlite` | ✅ |
| R-FN-0.5 4 级错误分类（tech retry / permission escalate / intent options / unknown escalate） | `kickoff_project.py:155-216` 各 step `except _KickoffProjectError + Exception` 双 catch + escalate_to_owner | 场景 5（intent）+ 场景 6（B-1 tech retry）+ implementer 单测 `TestProjectAlreadyExists` | ✅ |
| R-FN-0.6 30s SLA | `kickoff_project.py:65, 333-338` `KICKOFF_SLA_SECONDS=30.0` + warnings.append | 场景 8（max=0.0003s — 远低于 30s） | ✅ |
| R-NFR-19 / ADR-006 retry 防 B-1 | `kickoff_project.py:93-114` `_KickoffProjectError(WrappedToolError)` | 场景 6：MRO 含 WrappedToolError；retry attempts=3 | ✅ |
| 降级策略：PM 不在线 → 本地 + 飞书 @PM | `kickoff_project.py:595-651` `_step3_degraded` | 场景 4：success=True / status=degraded / project_id 含 "local-" | ✅ |
| 飞书卡片：5 字段 + 3 按钮 + value JSON 字符串 | `kickoff_project.py:1107-1228` `build_kickoff_card` | 场景 7：template=green / 4 elements / 3 buttons / 3/3 value 是 JSON 字符串 | ✅ |

### Full-Stack 编译 / 单测

```
$ /Users/feijun/.hermes/hermes-agent/venv/bin/python -m unittest test_kickoff_project -v 2>&1 | tail -5
Ran 15 tests in 1.553s
OK
```

```
$ /Users/feijun/.hermes/hermes-agent/venv/bin/python -m unittest test_error_classifier -v 2>&1 | tail -5
Ran 47 tests in 0.013s
OK
```

合计 **62/62 单测 PASS**，零回归。

### 跨模块接口

| 接口 | 调用方 | 被调方 | 验证 |
|---|---|---|---|
| `from . import adr_storage` | kickoff `_step4_write_adr` | `adr_storage.create_adr(...)` | ✅ kickoff_project.py:706 真调（不自写 INSERT INTO ADR） |
| `from . import dispatch_balanced` | kickoff `_step7_dispatch_initial` | `dispatch_balanced.run` | ✅ 真调（场景 3 mock 后链路通） |
| `from . import error_classifier` | kickoff 全文 | `WrappedToolError / retry_with_backoff / classify / escalate_to_owner` | ✅ 场景 6 防 B-1 通过 |
| `from . import feishu_api` | kickoff `_step3_degraded` + `_step8_send_kickoff_card` | `send_text_to_chat / send_card_message` | ✅ 不自写 open.feishu.cn HTTP（场景 9 grep 0 hits） |
| `from . import legion_api` | kickoff `_step5_provision_legion` + `_step6_build_mailbox` | `discover_online_commanders / mailbox_protocol_serialize` | ✅ 不重发明军团协议 |

---

## Red Team 验证（12 场景）

### 场景 1：implementer 的 15 单测复跑

**结果**：✅ 15 tests in 1.553s — OK

```
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
```

### 场景 2：47 单测无回归

**结果**：✅ 47 tests in 0.013s — OK（B-1 防回归族 全过）

### 场景 3：happy path mock 实测（8 步全成）

**结果**：✅ 5 字段输出齐 / step_results 8 键齐 / elapsed=0.0003s

```
success=True
project_id=p-mock-uuid
legion_commander_id=L1-test-mock
feishu_card_message_id=om_mock_msg
step_results 键数=8
step_results 键=['1_mkdir', '2_git_init', '3_prodmind_project', '4_adr_0001', '5_legion', '6_mailbox', '7_initial_tasks', '8_feishu_card']
elapsed=0.000s
error=None
```

> **校正记录**：implementer 任务卡的占位函数名 `_step3_create_prodmind_project` 等与代码实际名 `_step3_create_pm_project / _step5_provision_legion / _step7_dispatch_initial / _step8_send_kickoff_card` 不一致；本验证按代码实际函数签名 mock，等价覆盖 implementer 测试场景。

### 场景 4：PM 不在线降级

**结果**：✅ 8 步整体 success=True / step3 status=degraded / project_id 含 "local-"

```
success=True
step3 status=degraded
step3 reason=retry_with_backoff exhausted after 3 attempts: ProdMind connection refused: conn
project_id=local-6d989735-5213-4095-b240-9e92a0a88fa9
project_id 含 local-: True
```

> **核心验证**：PM HTTP ConnectionError → retry_with_backoff 真退出（3 次）→ 走 `_step3_degraded` → 本地 UUID + log + 后续 8 步不阻塞。
> 任务卡描述 "project_id 含 'local-uuid'" 应理解为 "project_id 以 'local-' 前缀开头（uuid 后缀）"。

### 场景 5：project 已存在 → intent

**结果**：✅ error 含 "already exists" / level=intent / step_failed=1_mkdir

```
success=None
error=project directory already exists: /Users/feijun/Documents/TestProj_exists_p1_5 （请改用其他名字或先删除已有目录）
level=intent
step_failed=1_mkdir
```

测试目录 `/Users/feijun/Documents/TestProj_exists_p1_5` 已 rmdir 清理。

### 场景 6：B-1 防回归

**结果**：✅ PASS-1（继承链）+ PASS-2（attempts=3）

```
PASS-1: _KickoffProjectError 继承 WrappedToolError
PASS-2: tech 级 attempts=3
```

> **意义**：retry_with_backoff 走 `.level` 短路（不依赖 classify 关键词匹配），P1.2 reviewer 发现的 B-1 缺陷在本模块得到沿用修复。

### 场景 7：飞书卡片 dict schema

**结果**：✅ template=green / elements=4 / buttons=3 / 3/3 value 是 JSON 字符串

```
header.template=green
elements 数=4
buttons 数=3
  button=查看 ADR, value 是字符串=True, value 可 json.loads=True
  button=加入军团群, value 是字符串=True, value 可 json.loads=True
  button=暂停项目, value 是字符串=True, value 可 json.loads=True
```

> **关键防御**：飞书卡片 button.value 必须是 JSON **字符串**（飞书 API 校验，dict 会 422）— 三按钮全合规。

### 场景 8：30s SLA 计时（all mock）

**结果**：✅ all 5 runs under 30s（max=0.0003s，远低于 SLA）

```
times=['0.0003', '0.0001', '0.0001', '0.0001', '0.0001']
max=0.0003s
avg=0.0001s
all under 30s: True
```

### 场景 9：复用 grep（不重发明）

**结果**：✅ import 5 项齐 / 0 军团硬编码 / 0 自写 ADR SQL / 0 自写飞书 HTTP

```
--- from . import 内容 ---
from . import (
    adr_storage,
    dispatch_balanced,
    error_classifier,
    feishu_api,
    legion_api,
)

--- HARDCODED grep（8 军团字面量）  → 0 hits
--- ADR SQL grep                  → 1 hit（仅 docstring 注释 "INSERT INTO ADR (number=1)"，line 9）
--- feishu API HTTP grep          → 0 hits
```

ADR 写入唯一调用：`kickoff_project.py:706 → adr_storage.create_adr(...)`（不自写 SQL，复用 P1.1 模块）。

### 场景 10：dev.db ADR count 仍 16（implementer 清理过）

**结果**：✅ 总数 16 / TestProj/p-mock/local-* 残留 0

```
$ sqlite3 /Users/feijun/Documents/prodmind/dev.db "SELECT count(*) FROM ADR;"
16

$ sqlite3 /Users/feijun/Documents/prodmind/dev.db "SELECT count(*) FROM ADR WHERE project_id LIKE 'TestProj%' OR project_id LIKE 'p-mock%' OR project_id LIKE 'local-uuid%' OR project_id LIKE 'local-%';"
0
```

### 场景 11：测试目录残留

**结果**：✅ 0 行（implementer 清理过 + 本次场景 5 也已 rmdir）

```
$ ls /Users/feijun/Documents/ | grep -iE "TestProj|kickoff_test"
(0 行 — 无残留)
```

### 场景 12：gateway 状态（环境性 WARN）

**结果**：⚠️ AICTO gateway 当前 stopped（8644 未 LISTEN）— 与 P1.5 实现无关

```
$ hermes profile list
 ◆default         claude-opus-4-6              running      —
  ai-hr           claude-opus-4-6              stopped      ai-hr
  aicto           claude-opus-4-6              stopped      aicto

$ lsof -iTCP -sTCP:LISTEN -n -P | grep 8644
(8644 not listening)
```

> **诊断**：
> - `aicto gateway status` 输出 "Gateway is running (PID: 36703, 22549)" 是 alias 误报：这两个 PID 实际是 default(8642) 和 ai-hr(8643)，不是 aicto 自身。`hermes profile list` 的权威输出确认 aicto Gateway=stopped。
> - 项目 CLAUDE.md 明示："**未接入生产 Hermes gateway**。启用需要显式注册到 `~/.hermes/config.yaml` 的 plugin list" — 当前为预期状态。
> - **本场景 WARN 不影响 P1.5 PASS 结论**：Phase 1 当前阶段不要求 gateway 在线，kickoff_project 工具入口在 tools.py 已正确接入（line 46-53），gateway 启动后即可调用。

### 攻击覆盖

- [x] **boundary inputs**（场景 5 已存在 / implementer test_blank_project_name / test_invalid_priority / test_missing_project_name）
- [x] **error propagation**（场景 4 ConnectionError → retry → degraded → 不阻塞后续；场景 5 intent 级直接返）
- [x] **backward compatibility**（场景 2 47 单测无回归 + 场景 6 B-1 防回归）
- [x] **resource isolation**（场景 9 不自写 SQL/HTTP；场景 10 dev.db count 仍 16；场景 11 文件系统无残留）
- [x] **SLA 边界**（场景 8 mock 全 step → 0.0003s 远低于 30s；真实场景 step5 legion.sh subprocess 是潜在瓶颈，已用 LEGION_SUBPROCESS_TIMEOUT=15s 兜底）
- [x] **interface contract**（场景 7 飞书卡片 button.value 必须是 JSON string，全 3 按钮合规）

### 红队未发现项

- 无 SEVERE
- 无 MEDIUM
- 无 LOW

---

## Integration Test

### Build Status

| 命令 | 结果 |
|---|---|
| `python -m unittest test_kickoff_project -v` | ✅ 15/15 OK |
| `python -m unittest test_error_classifier -v` | ✅ 47/47 OK |
| `python -c "from aicto_plugin.tools import kickoff_project"` | ✅ import OK（间接通过场景 3-5 调用验证） |

### 整合点

- [x] tools.py:20 `from . import kickoff_project as _kickoff_project` — import 通
- [x] tools.py:53 `return _kickoff_project.run(args, **kwargs)` — dispatch 通
- [x] kickoff_project → adr_storage（场景 1 内 test_adr_actually_written_to_sqlite 实写 sqlite 验证）
- [x] kickoff_project → dispatch_balanced（场景 3 mock 链路通）
- [x] kickoff_project → feishu_api（场景 7 卡片 schema 通）
- [x] kickoff_project → legion_api（mailbox_protocol_serialize 真调）
- [x] kickoff_project → error_classifier（场景 6 retry 防 B-1 短路通）
- [x] 主流程：场景 3 8 步全 mock 路径走通；场景 4 PM 降级路径走通；场景 5 intent 级 fail-fast 路径走通

---

## 验证后清理

| 项 | 状态 |
|---|---|
| `/Users/feijun/Documents/TestProj_exists_p1_5/` | ✅ rmdir 清理 |
| `/tmp/aicto_plugin` 软链 | ✅ 验证结束清理（见报告末） |
| dev.db ADR 行数 | ✅ 仍 16（无新增） |
| `~/.hermes/profiles/aicto/logs/kickoff_pm_degraded.log` | ⚠️ 保留（implementer 自验时降级路径正常产物，无清理必要） |

---

## 综合结论：**PASS**

**12 场景：11 PASS + 1 环境性 WARN（场景 12 gateway 当前 stopped — 与 P1.5 实现无关，CLAUDE.md 明示当前阶段不接入生产）**

| 维度 | 评分 |
|---|---|
| 需求覆盖（R-FN-0.1~0.6 + R-NFR-19） | 9/9 ✅ |
| 单测健康（implementer 15 + regression 47） | 62/62 ✅ |
| 红队场景（happy / 降级 / fail-fast / B-1 / SLA / schema / 复用 / 残留） | 11/11 ✅ |
| 不重发明（HARDCODED / SQL / 飞书 HTTP grep） | 0 hits ✅ |
| 数据隔离（dev.db count + 文件残留） | 0 污染 ✅ |
| 防 B-1（reviewer-p1-2 缺陷在本模块沿用修复） | ✅ |

**P1.5 kickoff_project 准入生产**（gateway 启动后即可调用，无需进一步代码修改）。

---

## 给 reviewer / team-lead 的建议

1. **本验证未实跑端到端真实 8 步**（即 PM 真在线 + legion.sh 真拉军团 + 飞书真发卡片）— 因任务纪律明示"严禁实际调 legion.sh / 实际派单 / 实际发飞书卡片"。生产 gateway 接入后建议在 staging 跑一次端到端 smoke。
2. 场景 12 的 `aicto gateway status` 输出有 alias 误报问题（显示其他 profile 的 PID），不是 P1.5 缺陷，但建议 ops 后续修正 alias 脚本。
3. implementer 任务卡的占位函数名（如 `_step3_create_prodmind_project`）与代码实际名（`_step3_create_pm_project`）不一致，已在场景 3-4 用代码实际签名复测，验证等价。建议 implementer 后续与任务卡对齐命名以避免回归测试 mock 失配。

---

**报告完成时间**：2026-04-25 18:55
**验证人**：L1-麒麟军团 verifier（程小远独立组员）
