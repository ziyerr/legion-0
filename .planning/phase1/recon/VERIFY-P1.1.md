# P1.1 集成验证报告

**验证人**：verifier (L1-麒麟军团 Task #15)
**验证时间**：2026-04-25 15:25 (Asia/Shanghai)
**验证方法**：对抗性实测，全程亲跑命令、贴出输出，不依赖 implementer 自报
**Effort 等级**：max

---

## 验证总览

| # | 场景 | 期望 | 实测 | 结果 |
|---|------|------|------|------|
| 1 | feishu token 真实拉取 | `t-xxx...` 前缀 | `t-g1044peu` (42 字节) | ✅ PASS |
| 2a | pm_db_api 读真实 PRD | `{"success":true,"prd":{...}}` | `{"success":true,"prd":{"id":"4f3e135a...","title":"AI HR - OPC..."}}` | ✅ PASS |
| 2b | mode=ro 物理挡 INSERT | 抛 `attempt to write a readonly database` | `OperationalError: attempt to write a readonly database` | ✅ PASS |
| 2c | mode=ro 物理挡 UPDATE/DELETE/CREATE/DROP（红队加测） | 全挡 | 4/4 全挡 | ✅ PASS |
| 3a | adr_storage create + list | CREATE 返 `number=1, display_number='ADR-0001'`；LIST 返 1 条 | `number=1, display_number='ADR-0001', id='54325165-...'`；LIST 返 1 条 | ✅ PASS |
| 3b | 5 张 CTO 表存在 | ADR/TechRisk/TechDebt/CodeReview/EngineerProfile 全有 | 5/5 全在 | ✅ PASS |
| 3c | 测试数据清理 | DELETE 后 0 条 | 0 条 remaining | ✅ PASS |
| 4a | discover_online_commanders | ≥1 commander，含 L1-麒麟军团 | 10 commanders，**含 L1-麒麟军团** | ✅ PASS |
| 4b | mailbox_protocol_serialize 含 8 保留字段 + 扩展 | id/from/to/type/payload/timestamp/read/summary + cto_context + priority | 全部 10 字段齐全 | ✅ PASS |
| 5a | error_classifier 单测 | 47 tests OK | `Ran 47 tests in 0.013s OK` | ✅ PASS |
| 5b | PM 补充 4 边界（含 readonly database） | intent / tech / tech / permission | intent / tech / tech / permission 全对 | ✅ PASS |
| 5c | 红队边界（空/None/emoji/长串/SQL）| 不崩溃，落 unknown | 5/5 落 unknown，"connection refused" 落 tech | ✅ PASS |
| 6a | aicto plugin 1.0.0 enabled | 列表含 enabled | `aicto enabled 1.0.0 (local)` | ✅ PASS |
| 6b | aicto gateway 运行 | running | `Gateway is running` | ✅ PASS |
| 6c | 三端口都 LISTEN | 8642 PM / 8643 AI HR / 8644 AICTO | 三端口齐全（PID: 8642→36703, 8643→49636, 8644→81740） | ✅ PASS |
| 7a | read-audit.log 存在含 ≥1 条 JSON | 至少一行 | 19 行 JSON，最新 `read_pm_prd` 调用记录正确 | ✅ PASS |
| 7b | gateway.log 含 "Gateway running" 且无新 ERROR | 1 条 + 无致命 | 5 条 "Gateway running" 出现，最新启动 15:18:31 干净 | ✅ PASS（见说明） |

**总计**：17 项实测，**17/17 通过**，**0 个 FAIL**。

---

## 关键证据片段

### 证据 1：feishu 真实 token
```
TOKEN_PREFIX: t-g1044peu
TOKEN_LEN: 42
```
证明 `feishu_api.get_tenant_access_token()` 真的调通了飞书 API 拿到真实 token，不是 mock。

### 证据 2：mode=ro 是 SQLite 物理挡，不是软挡
四类写操作（INSERT/UPDATE/DELETE/CREATE/DROP）全部抛 `OperationalError: attempt to write a readonly database`：
```
PASS: UPDATE blocked — OperationalError: attempt to write a readonly database
PASS: DELETE blocked — OperationalError: attempt to write a readonly database
PASS: CREATE TABLE blocked — OperationalError: attempt to write a readonly database
PASS: DROP TABLE blocked — OperationalError: attempt to write a readonly database
```
证明 `_readonly_connect()` 用了真正的 `mode=ro` URI，写入由 SQLite C 层物理拒绝，不是 Python 层判断（无法绕过）。

### 证据 3：ADR 端到端
```
CREATE: {'id': '54325165-5a7d-46e2-a86c-fd5db317b910', 'project_id': 'verify-p1-1', 'number': 1,
         'title': '验证 ADR 实测', 'status': 'accepted',
         'decision': '测试 adr_storage.create_adr 端到端',
         ...
         'created_at': '2026-04-25T07:25:00.379Z',
         'display_number': 'ADR-0001'}
LIST: [...同上 1 条...]
```
完整字段齐全，display_number 格式 `ADR-XXXX` 符合规范，时间戳 UTC ISO8601 +Z，project_id 隔离正确。

### 证据 4：5 张 CTO 表已建
```
ADR
CodeReview
EngineerProfile
TechDebt
TechRisk
```
5 张全部出现在 `prodmind/dev.db` 中（共享读，自有写）。

### 证据 5：discover 找到 10 commander 含 L1-麒麟军团
```
Found 10 commanders
  - L1-昆仑军团 (alive=True)
  - L1-麒麟军团 (alive=True)   ← 自己（可见证明 discover 正常）
  - L1-昆仑军团 (alive=True)
  - L1-暴风军团 (alive=True)
  - L1-白虎军团 (alive=True)
```

### 证据 6：mailbox 协议序列化字段齐全
```json
{
  "id": "msg-1777101916526",
  "from": "AICTO-CTO",
  "to": "L1-麒麟军团",
  "type": "task",
  "payload": "[VERIFY] P1.1 verifier dry-run",
  "timestamp": "2026-04-25T07:25:16Z",
  "read": false,
  "summary": "验证序列化",
  "cto_context": {"tech_plan_id": "verify-tp-1"},
  "priority": "normal"
}
```
8 保留字段（id/from/to/type/payload/timestamp/read/summary）+ 2 扩展字段（cto_context/priority）全到位。timestamp 是 UTC `Z` 格式（合规）。

### 证据 7：error_classifier 47 测试全过
```
Ran 47 tests in 0.013s
OK
```
PM 补充 4 边界单独再测：
```
我无法判断 -> intent (expect intent)            ← PM 反馈点
rate limit 429 -> tech (expect tech)
database is locked -> tech (expect tech)        ← PM 反馈点
readonly database -> permission (expect permission)  ← 与场景 2 闭环
PASS: PM 补充 4 边界全部正确分类
```

### 证据 8：plugin 状态 + 三端口隔离
```
aicto enabled 1.0.0 (local) ← Phase 1 全量描述正确
✓ Gateway is running

# 三端口
TCP 127.0.0.1:8642 (LISTEN)  PID 36703  ← default profile (PM/张小飞)
TCP 127.0.0.1:8643 (LISTEN)  PID 49636  ← ai-hr profile
TCP 127.0.0.1:8644 (LISTEN)  PID 81740  ← aicto profile（gateway.pid 一致）
```
profile 隔离生效，符合 CLAUDE.md「生产保护」硬约束。

### 证据 9：read-audit.log 在工作
最近 10 条全是真实读操作，最末一条对应本次场景 2a 的 `read_pm_prd`：
```
{"ts": "2026-04-25T07:24:52Z", "tool": "read_pm_prd", "args": {"prd_id": "4f3e135a-..."}, "rows_returned": 1}
```
共 19 条 JSON 行，每行格式正确。

---

## 红队加测发现（无 FAIL，但有观察项）

### 观察 1：error_classifier 对边界输入的鲁棒性
- `''` / `None` / 10000 字符长串 / 100 个 emoji / SQL 注入字符串 → 全部安全落 `unknown`，**未崩溃**
- `'connection refused'` → `tech`（合理，建议保留）
- 评级：**强**

### 观察 2：_readonly_connect 防写绕过强度
- 4 类 DDL/DML 全部 OperationalError，由 SQLite C 层 enforce
- 即使绕过 Python 层（如直接拼 SQL），底层仍然拒
- 评级：**强**（mode=ro 是 SQLite URI 级别保护，不可绕）

### 观察 3：gateway.log 历史 ERROR 说明
- 共 28 条 ERROR，今天 8 条
- 全部是 **Lark websocket 网络抖动**（keepalive timeout / SSL EOF）— **非 P1.1 plugin 代码错误**
- 最新启动（15:18:31）后日志干净，"Gateway running with 2 platform(s)" 正常
- 评级：**可接受**（不归 P1.1 范围）

---

## 失败项详情

**无失败项**。

---

## 综合结论

**PASS** ✅

7 大场景 17 项实测全数通过，红队对边界/绕过/异常均未撕开口子。P1.1 五个模块（feishu_api / pm_db_api / adr_storage / legion_api / error_classifier）端到端**真实可用**：
- feishu API 真调通，token 真拿到
- pm_db_api 真读 PRD，mode=ro 物理挡写
- adr_storage create/list 端到端跑通，5 张表齐
- legion_api 真发现 10 commander，mailbox 协议字段完整
- error_classifier 47 单测 + 4 PM 补充边界 + 红队边界全过

profile 隔离三端口（8642/8643/8644）齐 LISTEN，符合「生产保护」硬约束。审计日志在写入。

**可以放行 P1.1。**

---

## 测试数据清理确认

| 数据 | 操作 | 结果 |
|------|------|------|
| ADR `verify-p1-1` 项目下的测试 ADR | `DELETE FROM ADR WHERE project_id='verify-p1-1'` | ✅ remaining=0 |
| 军团 mailbox | 仅 dry-run 序列化，**未实际 send** | ✅ 无副作用 |
| read-audit.log | 19 条记录，含本次验证调用 | ✅ 正常累积，无需清理 |

