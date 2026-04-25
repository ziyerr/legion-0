# VERIFY-P1.4 — dispatch_to_legion_balanced 端到端验证

| 项 | 值 |
|---|---|
| 任务 | Task #24 — P1.4 验证（dispatch_to_legion_balanced 实测） |
| 验证人 | L1-麒麟军团 verifier（程小远独立组员） |
| 验证日期 | 2026-04-25 18:17~18:20 |
| 被验文件 | `hermes-plugin/dispatch_balanced.py`（717 行）+ `hermes-plugin/tools.py`（patch 接入） |
| 验收依据 | `.planning/phase1/specs/REQUIREMENTS.md §1.4 R-FN-3.1~3.9` / `ARCHITECTURE.md §4.4 §5.3` / `PHASE-PLAN.md §5` / `RECON-REFERENCE.md §6` / `PRD-CAPABILITIES.md 能力 3` / `REVIEW-P1.2.md B-1` |
| 综合结论 | **PASS（10/10 主场景 + 7/7 红队场景全过；零生产污染；零 dev.db 写入；47 单测 OK）** |

---

## 验证范围（Scope）

- **Mode**: Combined（Compliance + Red Team + Integration）
- **Files verified**:
  - `hermes-plugin/dispatch_balanced.py`（核心实现）
  - `hermes-plugin/tools.py`（dispatch_to_legion_balanced 接入）
  - `hermes-plugin/legion_api.py`（mailbox 协议复用 — 真调用验证）
  - `hermes-plugin/test_error_classifier.py`（B-1 防回归 + 47 单测）
- **Requirements**:
  - R-FN-3.1（在线军团发现）/ 3.2（双通道派单）/ 3.3（单军团并发 ≤2）/ 3.4（DAG 拓扑延派）/
  - 3.5（payload 三段：PRD/技术方案/GWT）/ 3.6（cto_context 字段）/ 3.7（CTO 决策权）
- **方法论纪律**：全程 mock `discover_online_commanders` + `send_to_commander`，**未实际派单到任何在线军团**（含 L1-麒麟军团本身）；**dev.db 零写入**；**symlink 复用包路径，测试结束清理**。

---

## Compliance Audit

### 需求覆盖矩阵

| 需求 | 实现位置 | 验证场景 | 状态 |
|---|---|---|---|
| R-FN-3.1 在线军团发现（filter 状态 + alive 优先） | `dispatch_balanced.py:122-148` 调 `legion_api.discover_online_commanders` | 场景 1/2/3 | ✅ |
| R-FN-3.2 双通道派单（inbox 强保障 + tmux best-effort） | `dispatch_balanced.py:386-393` 委托 `legion_api.send_to_commander`（不重写） | 场景 5（kwargs schema）+ 真调 `mailbox_protocol_serialize` | ✅ |
| R-FN-3.3 单军团并发 ≤2 | `dispatch_balanced.py:47, 484, 474` `MAX_CONCURRENT_TASKS_PER_LEGION=2` + load_map | 场景 1（每军团 2/2）+ 场景 2（10 任务 × 3 军团 → 6 派 4 deferred） | ✅ |
| R-FN-3.4 DAG 拓扑延派（depends_on 非空 → 延派） | `dispatch_balanced.py:275-322` `_step3_split_ready_deferred` | 场景 1（T3 deps T1 → deferred）+ 场景 4a（A→B→C 链：仅 A 派） | ✅ |
| R-FN-3.5 payload 三段（PRD ≤500 + 技术 ≤1000 + GWT） | `dispatch_balanced.py:541-646` `_build_payload` | 场景 5/7（payload 三段标题齐全；PostgreSQL/Redis ADR 渲染 markdown 表） | ✅ |
| R-FN-3.6 cto_context 字段（project/task/tech_plan/adr_links） | `dispatch_balanced.py:649-670` `_build_cto_context` | 场景 5：cto_context.{project_id,task_id,tech_plan_id,adr_links,size,tech_stack_link} 齐 | ✅ |
| R-FN-3.7 CTO 决策权（无需军团确认） | `dispatch_balanced.py:642-644` payload 元信息明示 + 直接派不等待 ack | 派单流程不阻塞等待回执（场景 1 一次性返回） | ✅ |
| R-FN-3.8 单 task 派失败不阻塞整批（warning + deferred） | `dispatch_balanced.py:394-421` LegionError + Exception 双 catch | 场景 RT-5：LegionError → assignments=0 / deferred=1 / warnings 含错误信息 | ✅ |
| R-FN-3.9 EngineerProfile 复用 `HARDCODED_LEGION_PROFILES` | `dispatch_balanced.py:39, 350` 通过 design_tech_plan 模块引用 | 场景 8：grep 8 军团名 zero hits in code body；HARDCODED 唯一引用在 line 350 | ✅ |
| R-NFR-19 / ADR-006 retry 防 B-1 | `dispatch_balanced.py:71-85` `_DispatchBalancedError` 继承 WrappedToolError | 场景 6：MRO=[..., WrappedToolError, Exception]；retry attempts=3 | ✅ |

### Full-Stack 编译

```
$ /Users/feijun/.hermes/hermes-agent/venv/bin/python -m unittest test_error_classifier -v
Ran 47 tests in 0.013s
OK
```

```
$ python -c "from aicto_plugin.tools import dispatch_to_legion_balanced, breakdown_tasks, design_tech_plan, kickoff_project, review_code, daily_brief, read_pm_project"
import OK: 6 capabilities + 1 PM tool resolved
```

### 跨模块接口

| 边界 | 状态 | 证据 |
|---|---|---|
| `tools.dispatch_to_legion_balanced` ↔ `dispatch_balanced.run` | ✅ 匹配 | `tools.py:67-73` 仅一行 dispatch；签名 `(args, **kwargs) -> str` 对齐 |
| `dispatch_balanced` ↔ `legion_api.discover_online_commanders` | ✅ 匹配 | 返回 `List[Commander]`；`Commander` 含 `.commander_id / .tmux_alive / .started_at` 全用 |
| `dispatch_balanced` ↔ `legion_api.send_to_commander` | ✅ 匹配 | kwargs：`commander_id, payload, msg_type, summary, cto_context, priority` 全为合法签名 |
| `dispatch_balanced` ↔ `legion_api.mailbox_protocol_serialize` | ✅ 匹配 | 真调用 schema 测试：`id/from/to/type/payload/timestamp/read/summary/cto_context/priority` 全齐 |
| `dispatch_balanced` ↔ `design_tech_plan.HARDCODED_LEGION_PROFILES` | ✅ 匹配 | `dict[commander_name, {tech_stack_tags...}]`；profiles_by_name 构造正确 |
| `dispatch_balanced` ↔ `pm_db_api.read_pm_project / get_pm_context_for_tech_plan` | ✅ 匹配 | 返回 JSON 字符串；解析 `error / project / prd` 字段 |
| `dispatch_balanced` ↔ `adr_storage.list_adrs` | ✅ 匹配 | 返回 list[dict]；用 `id / display_number / title / decision` |
| `dispatch_balanced` ↔ `error_classifier.{classify, escalate_to_owner, WrappedToolError}` | ✅ 匹配 | 4 级分类 + 升级骏飞机制对齐 |

---

## Red Team

### 攻击向量覆盖矩阵

| 维度 | 状态 | 场景 |
|---|---|---|
| 边界输入（empty list / 类型错 / 缺必填） | ✅ | RT-1/2/3/4：全部正确返 `intent` 级失败，message 清晰 |
| 错误传播（send 失败） | ✅ | RT-5：`LegionError("inbox write failed")` → 单 task 进 deferred + warning，不阻塞整批 |
| 资源耗尽（满载军团） | ✅ | 场景 2：10 任务 × 3 军团（cap=2）→ 6 派 4 deferred；场景 RT-7：suggested 满载自动转替补 |
| 业务规则正确性（DAG 延派） | ✅ | 场景 4a：A→B→C 链仅 A 派；场景 4b：全 ready 全派 |
| 业务规则正确性（suggested_legion 优先） | ✅ | RT-6：tech_stack 不匹配但 suggested 强 hint，正确选中 L1-B 而非 L1-A |
| 协议向后兼容（mailbox schema） | ✅ | 真调 `mailbox_protocol_serialize`，全字段齐 + 不破老 schema |
| 并发/幂等 | ⚠️ N/A | Phase 1 单进程内调度（load_map 内存态）；Phase 2 跨进程同步是 design_tech_plan 范围 |
| 安全（路径遍历 / 注入） | ✅ | payload 是写 inbox markdown 字符串；`commander_id` 在 `legion_api._resolve_commander` 校验；本模块未直接拼路径 |
| 向后兼容（dev.db 零写） | ✅ | 场景 10 + 后置：ADR count 仍 16（与 P1.3 baseline 一致） |

### Findings

| 严重级 | 描述 | 文件:行 | 影响 |
|---|---|---|---|
| **零 SEVERE** | — | — | — |
| **零 MEDIUM** | — | — | — |
| **GREEN LOW（备忘 — 不阻 P1.4 收尾）** | `assignment.msg_id` 字段拿的是 `send_result.get("message_id")`（key 名匹配）但赋给字段名 `msg_id` — 有点名字漂移；建议下个迭代统一为 `message_id`，下游军团解析方便 | `dispatch_balanced.py:430` | 仅命名一致性，不影响功能 |
| **GREEN LOW（设计已记 — RECON 已说明）** | Phase 1 `tech_plan_id == project_id`（design_tech_plan 输出未含独立 plan_id；恢复用 ADR list 重组）；Phase 2 改 schema 时再分离 | `dispatch_balanced.py:660-664` | 已在代码注释 + cto_context 文档说明，下游军团知晓 |

---

## Integration Test

### 10 场景执行结果

| # | 场景 | 命令证据 | 结果 |
|---|---|---|---|
| 1 | mock happy path（5 tasks 含依赖 × 2 军团） | success=True / assignments=4 / deferred=1（T3 depends T1）/ load={A:2, B:2} / send 调用 4 次 | ✅ PASS |
| 2 | 负载均衡（10 ready × 3 军团） | assignments=6 / load={A:2, B:2, C:2} / deferred=4（单军团 ≤2 严格） | ✅ PASS |
| 3 | 空军团 | error="no online legion available..." / level=tech | ✅ PASS |
| 4a | DAG 拓扑（A→B→C 链）| assigned=['A'] / deferred=['B','C']（reason 含 depends_on） | ✅ PASS |
| 4b | DAG 全 ready | assigned=3 / deferred=0 | ✅ PASS |
| 5 | mailbox 协议字段（priority/cto_context/summary/msg_type） | priority=high（XL→high）/ cto_context.{project_id, task_id, tech_plan_id, adr_links, tech_stack_link, size, suggested_legion, feishu_doc_url} 全齐 / summary="AICTO 派发[TestProj]: task X" | ✅ PASS |
| 6 | B-1 防回归 | MRO 含 WrappedToolError / classify=tech / retry attempts=3 | ✅ PASS |
| 7 | payload 三段 | payload 含 "## 一、PRD 摘要" / "## 二、技术方案（CTO ADR 决策）" / "## 三、验收标准（Given/When/Then）" + ADR markdown 表渲染 | ✅ PASS |
| 8 | 复用纪律 grep | 8 军团名 zero hits in dispatch_balanced.py 代码体（仅 docstring 提"8 军团"作为 profile 描述）；HARDCODED_LEGION_PROFILES 通过 design_tech_plan 模块引用 line 350 | ✅ PASS |
| 9 | 47 单测 + import OK | `Ran 47 tests in 0.013s OK`；7 工具 import OK | ✅ PASS |
| 10 | dev.db 零写 | ADR count=16（与 P1.3 baseline 一致） | ✅ PASS |

### 红队补充场景（独立判断追加）

| # | 场景 | 结果 |
|---|---|---|
| RT-1 | tasks 空列表 | level=intent / msg="tasks must be a non-empty list" → ✅ |
| RT-2 | tasks 非 list（"string"） | level=intent → ✅ |
| RT-3 | project_id 空字符串 | level=intent → ✅ |
| RT-4 | 缺 project_id | level=intent → ✅ |
| RT-5 | send_to_commander 抛 LegionError | assignments=0 / deferred=1 / warnings 含 "inbox write failed" → ✅ |
| RT-6 | suggested_legion 优先（tech 不匹配也强选）| 派给 L1-B 而非 L1-A → ✅ |
| RT-7 | suggested 满载自动转替补 | T1/T2→B（满）/ T3→A → ✅ |
| RT-Schema | 真调 `mailbox_protocol_serialize` | id/from=AICTO-CTO/to/type/payload/timestamp/cto_context/priority 全齐 → ✅ |

---

## 关键证据片段

### 场景 1 完整返回（节选）

```json
{
  "success": true,
  "assignments": [
    {"task_id": "T1", "legion_id": "L1-测试军团-A", "priority": "normal", ...},
    {"task_id": "T2", "legion_id": "L1-测试军团-B", "priority": "normal", ...},
    {"task_id": "T4", "legion_id": "L1-测试军团-A", "priority": "low", ...},
    {"task_id": "T5", "legion_id": "L1-测试军团-B", "priority": "normal", ...}
  ],
  "deferred": [
    {"task_id": "T3", "reason": "depends_on 未就绪（共 1 个前置任务尚未完成）：['T1']", ...}
  ],
  "online_legion_count": 2,
  "ready_count": 4
}
```

### 场景 5 cto_context（XL → high priority）

```json
{
  "project_id": "p-test",
  "tech_plan_id": "p-test",
  "adr_links": ["adr-1", "adr-2"],
  "feishu_doc_url": null,
  "task_id": "T1",
  "tech_stack_link": ["backend"],
  "size": "XL",
  "suggested_legion": null
}
```
priority=`high`（XL→high SLA 映射正确）。

### 场景 6 B-1 MRO

```
MRO=['_DispatchBalancedError', 'WrappedToolError', 'Exception', 'BaseException', 'object']
PASS-1: classify=tech
PASS-2: tech 级 attempts=3 （而非 1，B-1 修复有效）
```

### 场景 7 payload markdown 实例

```markdown
# AICTO 派单 · task X

> 项目：**TestProj** | size=XL | priority=high | task_id=`T1`

## 一、PRD 摘要

**PRD-X**

PRD body content

## 二、技术方案（CTO ADR 决策）

| 组件 | 选择 | ADR |
|------|------|-----|
| 数据库 | PostgreSQL | ADR-001 |
| 缓存 | Redis | ADR-002 |

## 三、验收标准（Given/When/Then）

- **Given**: g
- **When**: w
- **Then**: t
```

三段标题齐全 + ADR table 渲染清晰 + 数据缺失时降级 fallback 文案完整（场景 1 中 ADR 为空时正确显示"暂无 ADR — 程小远建议先调 design_tech_plan 落决策"）。

### 生产保护证据

```
$ ls -la ~/.claude/legion/99a20b81/team-L1-麒麟军团/inboxes/L1-麒麟军团.json
-rw-r--r-- 1 feijun staff 2 Apr 25 15:19 .../L1-麒麟军团.json
```

L1-麒麟军团 inbox 最后修改 15:19，远早于本验证 18:17 起始，**全程零真实派单到生产军团**。

```
$ sqlite3 /Users/feijun/Documents/prodmind/dev.db "SELECT count(*) FROM ADR;"
16    # = P1.3 baseline，零写入
```

---

## Verdict

**PASS** — Task #24 验收通过。

### 通过依据

1. **10/10 主场景 + 7/7 红队补充场景全过**（含 4 个边界 + 1 个错误传播 + 2 个 suggested_legion 行为）
2. **9 个跨模块接口全匹配**（含真调 mailbox_protocol_serialize schema 验证）
3. **B-1 防回归 PASS**（MRO 含 WrappedToolError；retry 真重试 3 次）
4. **47 单测无回归**
5. **零生产污染**（mock 全程；L1-麒麟军团 inbox 未触；dev.db ADR=16）
6. **复用纪律严格**（8 军团名零 hardcode；HARDCODED_LEGION_PROFILES 通过 design_tech_plan 引用）

### 仅备忘（不阻收尾）

- **GREEN LOW**：`assignment.msg_id` 命名漂移建议统一为 `message_id`（与 send_to_commander 返回 key 对齐）— 留 Phase 2 优化
- **GREEN LOW**：Phase 1 `tech_plan_id == project_id` 是当前 design_tech_plan 输出限制 — 已注释说明，Phase 2 schema 升级时再拆分

P1.4 可签收，可进入 P1.5（kickoff_project）。

---

## 本轮学到的（实践认识论）

1. **mock 边界要看实际 send 返回字段**：legion_api 返回 `message_id`（不是 `msg_id`），dispatch_balanced 用 `.get("message_id")`，但又赋值给 `msg_id` 字段名 — 测试 mock 需要按真签名 key 命名才能映射到对应字段（虽然本测对此字段不敏感）
2. **`from . import` 测试要 symlink**：plugin 子模块用相对 import，`cd plugin_dir && python -c "import x"` 直接报 `ImportError: attempted relative import with no known parent package`；正确姿势是 `ln -sfn plugin /tmp/aicto_plugin && cd /tmp && python -c "from aicto_plugin import ..."`
3. **mock send_to_commander 时务必 mock 全 5 个依赖**（discover/send/read_pm_project/get_pm_context_for_tech_plan/list_adrs），否则 ctx 拉取走真实路径 — 未必失败但会有不可控副作用
4. **生产污染验证用 mtime**：派单后立刻 `ls -la inbox.json`，对比测试启动时间 — 比 grep "have we sent" 更直接

