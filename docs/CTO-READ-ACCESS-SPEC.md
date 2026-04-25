# CTO 读取 PM 文档的技术方案 · spec

> 2026-04-23 · Claude Code 产出（CTO 技术实现范畴，符合维度正交纪律）
>
> 回应 team lead 2026-04-23 要求："AICTO 应该能够随时查阅 AIPM 的文档，然后理解需求目标和范围"
>
> **正交纪律重申**：CTO 对 PM 产出**只读、不改**。发现 PRD 问题只能生成反馈报告让 PM 改，不能绕过 PM 直接改。

---

## 一、读什么（PM 的产出物清单）

### A. 结构化数据（dev.db 里）

| 表 | 字段 | CTO 读它做什么 |
|----|-----|--------------|
| Project | 全字段 | 判断项目 mode / authorization_scope / stage，定项目边界 |
| PRD | content / version / changeLog / feishuDocToken | 理解需求、版本演化、查 decisions |
| PRDVersion | 全字段 | 追溯版本演化（为什么从 v2→v3） |
| PRDDecision | 全字段 | 看 PM 已定的 decisions，避免在 CTO 侧重复/冲突 |
| PRDOpenQuestion | 全字段 | 看 PM 还没澄清的点，技术评估里要 flag |
| UserStory | 全字段 | 看具体用户故事，定原子任务粒度 |
| Feature | 全字段 + rice* | 看 priority / effort estimate，对齐军团调度 |
| Research | content / summary | 看 PM 做的市场/用户调研，技术选型时作为 context |
| Evaluation | 全字段 | 看 PM 的 Go/No-Go 评估，技术可行性评估时参考 |
| Requirement | 全字段（Phase 8）| 看需求池，做跨项目技术一致性 |
| Activity | 全字段 | 看 PM 在项目上做了什么动作、频率 |

### B. 非结构化文档（飞书 docx 里）

| 文档类型 | 来源字段 | CTO 读它做什么 |
|---------|---------|--------------|
| PRD 正文 | `PRD.feishuDocToken` | 看 PRD 完整内容（PM 在 dev.db 只存 summary，完整内容在 docx）|
| 项目 Research 总结 | `Project.researchDocToken` | PM 自动维护的 research 汇总 |
| 项目 Evaluation 报告 | `Evaluation.evaluationDocToken` | PM 的评估详版 |
| 其他 ProjectDocument | `ProjectDocument.feishuDocToken` | 未来 PM 产出的其他文档 |

### C. 本地文件系统（补充兜底）

- `~/Documents/prodmind/.planning/*.md` — PM 的 spec 草稿（可能比 dev.db 里的 version 更新）
- `~/Documents/<project-name>/CLAUDE.md` — 项目特定约束

---

## 二、怎么读（技术路径）

### A. dev.db 共享读 · 只读模式（关键技术）

**CTO 直连 prodmind 的 dev.db 文件**，用 SQLite URI 强制只读：

```python
# CTO plugin: ~/Documents/AICTO/hermes-plugin/tools.py
import sqlite3

PRODMIND_DB_PATH = "/Users/feijun/Documents/prodmind/dev.db"

def _readonly_connect() -> sqlite3.Connection:
    """只读连接到 prodmind 的 dev.db — 物理上禁止任何 UPDATE/INSERT/DELETE。"""
    uri = f"file:{PRODMIND_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
```

**关键设计**：
- `mode=ro` 让 SQLite 层拒绝写操作 —— 即使 CTO 代码出 bug 写了 SQL update，也会被挡住（`attempt to write a readonly database`）
- SQLite WAL 模式允许多进程并发读 —— 不会和 PM 的写冲突
- 如果 PM 在写事务中，CTO 读到的是事务前快照（WAL 的 reader 语义）—— 可接受

### B. 飞书 docx 读 · 用 AICTO 自己的 app token

CTO 用自己的飞书 app（`cli_a9495f70ddb85cc5`）调飞书 open API 读文档：

```python
def read_pm_feishu_doc(doc_token: str) -> str:
    """读 PM 创建的飞书文档。依赖 bug 修复 fc86969 后文档默认 tenant_editable，
    CTO 的 app 在同 tenant 下可读。"""
    token = _get_aicto_tenant_access_token()
    resp = _request(
        "GET",
        f"/open-apis/docx/v1/documents/{doc_token}/raw_content",
        headers={"Authorization": f"Bearer {token}"}
    )
    return resp["data"]["content"]
```

**关键依赖**：
- 权限 bug 修复（commit `fc86969`）让**新建**文档都 tenant_editable → 同 tenant 的 AICTO app 能读 ✅
- **老文档**（v0.1 方案文档、真实Talk 几份）中 3 个 backfill 失败的 —— AICTO 也读不到 → 那 3 个需要 team lead 手工补权限（已记 backlog）

### C. 本地文件读 · 走 Python open()

纯本地，无 API 调用：
```python
def read_prodmind_planning(filename: str) -> str:
    path = f"/Users/feijun/Documents/prodmind/.planning/{filename}"
    with open(path) as f:
        return f.read()
```

**安全**：路径白名单（只允许 `~/Documents/prodmind/.planning/` 下），不能逃逸到 `~/Documents/prodmind/.env` 等敏感位置。

---

## 三、8 个只读工具（新增到 AICTO 工具集）

| 工具 | 源 | 说明 |
|-----|----|------|
| `read_pm_project(project_id)` | dev.db Project | 全字段，含 mode/scope/stage |
| `read_pm_prd(prd_id, version?)` | dev.db PRD + PRDVersion | 当前版或指定版本 |
| `list_pm_prd_decisions(prd_id)` | PRDDecision | PM 已定的所有 decision |
| `list_pm_open_questions(prd_id)` | PRDOpenQuestion | PM 还没澄清的问题 — CTO 评估时重点看 |
| `list_pm_user_stories(project_id)` | UserStory | 含 rice priority |
| `list_pm_features(project_id, status?)` | Feature | 可按 status filter |
| `read_pm_research_doc(project_id)` | Research + 飞书 docx | 返回 markdown 正文 |
| `read_pm_evaluation_doc(project_id)` | Evaluation + 飞书 docx | 返回 markdown 正文 |

补充 2 个综合工具：
- `get_pm_context_for_tech_plan(prd_id)` — 一次性返回做技术方案需要的所有 PM context（PRD + decisions + open_questions + rice-sorted features + research summary）
- `diff_pm_prd_versions(prd_id, from_v, to_v)` — 看 PM 改了什么，CTO 可以 re-evaluate

---

## 四、权限边界（技术层强制 + 应用层约束）

### 技术层强制
- `mode=ro` SQLite URI — 物理挡写
- 飞书 API 只用 GET 方法，不 POST/PATCH/DELETE PM 的文档
- 本地文件只 open(mode='r')

### 应用层约束
- AICTO SOUL.md 里明确："你只能读 PM 的产出，发现问题必须通过 `escalate_to_pm(feedback)` 反馈，不能自己改"
- AICTO 工具文档里明确每个只读工具的边界
- 代码评审（未来）：任何 CTO 侧代码 PR 中含 UPDATE/INSERT/DELETE PM 表的 SQL 都自动 BLOCKING

### 例外：CTO 可以写自己的表
CTO 完全拥有读写权限的表（v0.2 §6 定义）：
- ADR / TechRisk / TechDebt / CodeReview / EngineerProfile

这些表也在 prodmind dev.db 里，但**连接方式不同**：
```python
def _cto_own_connect() -> sqlite3.Connection:
    """读写连接 — 只用于 CTO 自己的表（ADR 等），不要用这个改 PM 表"""
    conn = sqlite3.connect(PRODMIND_DB_PATH)  # 无 mode=ro
    conn.row_factory = sqlite3.Row
    return conn
```

代码里通过**函数名分离**：`_readonly_connect` vs `_cto_own_connect` —— 让 grep 能一眼看出哪些地方有写权限。

---

## 五、变更订阅（主动化 · Phase 2）

当前 Phase 1：CTO 每次主动读（query-on-demand）。

Phase 2 增强：PM 更新 PRD 时自动通知 CTO

**实现路径**：
- ProdMind 的 `update_prd` 工具里加 hook：发出 `prd_updated(prd_id, version)` 事件
- 事件进 Hermes 的 event bus（Phase 1 事件引擎 spec 已有）
- CTO profile 订阅此事件，触发 `re_evaluate_if_tech_plan_exists(prd_id)`

**Phase 1 简化**：CTO 每次在做 review 前重新读最新版，不依赖 push。

---

## 六、性能 / 缓存

### 预期负载
- CTO 做一次 `design_tech_plan` 读 `get_pm_context_for_tech_plan` 一次：约 5-10 次 SQL + 1-3 次飞书 API
- 平均响应时间：< 2s（SQLite 本地读微秒级，飞书 API 200-500ms）
- 全天 query：假设 30-50 次，完全不在负载上

### 缓存
- dev.db 不加缓存（读太快）
- 飞书文档可加 short TTL 缓存（60s）— 避免同一次 design_tech_plan 多次读同一个 doc

### 并发
- SQLite WAL 允许多 reader —— PM 和 CTO 同时读安全
- 飞书 API 有 rate limit（20 req/s/app）—— CTO 一天不到 200 次远低于上限

---

## 七、安全考虑

### 数据泄漏
- AICTO 的 memory / session log 里不存储 PM 的敏感数据（用户 open_id / 飞书 app secret 不被 serialize）
- 读到的 PRD 内容只在 current session context 里用，不主动持久化
- ADR / TechRisk 里 CTO 可引用 PRD 片段，但要注明 `source=PRD[id=x, version=y]`

### 审计
- 每次 CTO 读 PM 数据记一行到 `~/.hermes/profiles/aicto/logs/read-audit.log`：timestamp / tool / args
- Team lead 可以任何时候审这份日志，看 CTO 做了什么

### 身份隔离
- AICTO 用自己的 app (`cli_a9495f7...`)，不共用 PM 的凭证
- AICTO 和 PM 在飞书是**两个独立 bot**，用户看到的消息署名分明

---

## 八、实施路径（Phase 1 包含）

当 PM 接棒产出产品设计后，Claude Code 承接技术实现时的顺序：

| # | 动作 | 属 |
|---|------|---|
| 1 | 在 AICTO tools.py 加 `_readonly_connect()` 辅助函数 | 基础设施 |
| 2 | 实现 8 个只读工具（§三） | CTO 工具集 |
| 3 | 工具单元测试：每个工具跑 "SELECT from PRD limit 1" 这种 smoke test | 质量门槛 |
| 4 | 尝试 `_readonly_connect().execute("UPDATE PRD ...")` 必须抛异常 | 权限边界验证 |
| 5 | 在 SOUL.md 加"你只能读 PM 表"纪律 | 人格注入 |
| 6 | `get_pm_context_for_tech_plan` 组合工具（为 `design_tech_plan` 铺路）| 集成 |

每个步骤单独 commit，commit message 标 `feat(aicto-read-access): ...`。

---

## 九、对 v0.2 §七 "dev.db 共享表" 的补充

v0.2 §七 已经写了权限矩阵（PM R/W、CTO R），但没说具体工具 —— 本 spec 补齐了。

PM 侧没什么要改：PM 的 `update_prd` / `create_user_story` 这些工具不变，只是**新增了 CTO 这个 reader**。PM 可以继续按自己节奏写，CTO 在旁边读。

实施后，写进 `PRODUCT-SPEC-v0.2-merged.md` §七 末尾的"实施细节"引用本 spec。
