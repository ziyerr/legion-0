# Phase 1 — ARCHITECTURE（架构决策）

> 本文档落锤"怎么做"。所有重大决策附 ADR 编号链接。
> 任何决策变更需先发 ADR 修订，再改本文档。

## 0. 总体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     云智 OPC 三 Agent 拓扑                         │
│                                                                 │
│   PM (default:8642)    CTO (aicto:8644)    HR (ai-hr:8643)      │
│   张小飞                 程小远                AIHR              │
│      │                     │                     │              │
│      └──────共享──────►  prodmind/dev.db  ◄──────┘              │
│             读写            (单 SQLite)        只读              │
│                              │                                  │
│        CTO 用 mode=ro 读 PM 表 + 写自有 5 张表                    │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴────────────────┐
              │                                │
       飞书 IM (3 独立 bot)              L1 军团（tmux + inbox.jsonl）
              │                                │
              └────── 程小远 dispatch ─────────┘
```

**核心架构原则**（来自历史决策 + 侦察吸收）：
1. **profile 物理隔离**：每 agent 独立 HERMES_HOME / state.db / 飞书 app / 端口
2. **数据共享 + 物理只读**：dev.db 单实例，CTO 用 SQLite URI `mode=ro` 物理挡写 PM 表
3. **plugin 复用**：飞书 / dispatch / token 缓存等基础能力复用 ProdMind 黄金标本
4. **协议向后兼容**：mailbox 沿用现有 inbox.jsonl schema，CTO 加新字段不破坏现有 commander
5. **生产零影响**：AICTO 任何启停 / 崩溃不影响 default(PM) / ai-hr profile

## 1. 数据流（端到端）

```
[PM 派发新 PRD]
       │
       ▼
PM 调 create_project (HTTP 8642)             ◄── R-OPEN-8 默认 (b)
       │
       ▼
程小远 kickoff_project (8 步)
   1. mkdir ~/Documents/<project>           # 本地 fs
   2. git init                              # 本地 fs
   3. POST 8642 /create-project             # ProdMind HTTP 调用 ◄── ADR-008
   4. INSERT INTO ADR (number=0001)         # _cto_own_connect 写 prodmind/dev.db ◄── ADR-002
   5. legion.sh l1+1 → 拉军团               # subprocess
   6. 写 inbox.jsonl + tmux send-keys       # mailbox + 通知 ◄── ADR-005
   7. 派首批任务到军团 inbox                  # 同上
   8. send_card_message AICTO 群             # 飞书卡片 ◄── ADR-009
       │
       ▼
[军团接到任务，开发中... 完成后提交 PR]
       │
       ▼
程小远 review_code (PR webhook 或飞书触发)
   ├─ 读 PR diff (gh CLI)
   ├─ 读 tech_plan (read_pm_prd / get_pm_context)  # mode=ro 读
   ├─ LLM 生成 10 项 status                          # opus-4-6
   ├─ INSERT INTO CodeReview                        # _cto_own_connect 写
   ├─ if BLOCKING: send_card 到军团群（appeal 卡片）
   └─ if 军团忽略 BLOCKING: 升级骏飞                 # ADR-006

[每日 18:00] cron loop 触发
   ├─ 扫描 Project / CommanderOutbox / CodeReview
   ├─ 生成飞书群消息（30 秒概览）
   └─ send_text_to_chat AICTO 群
```

## 2. 进程模型

| 进程 | 端口 | HERMES_HOME | 状态 |
|------|------|-------------|------|
| PM gateway（生产）| 8642 | ~/.hermes/profiles/default/ | running |
| AIHR gateway | 8643 | ~/.hermes/profiles/ai-hr/ | running |
| **AICTO gateway**（本项目）| **8644** | **~/.hermes/profiles/aicto/** | **running**（plugin 待挂载）|

**AICTO gateway 单进程职责**：
- 飞书 ws 连接（独立 bot `cli_a949...`）
- LLM 路由（aigcapi.top + claude-opus-4-6）
- 16 个工具的同步执行（tools.py）
- 内置 cron loop（plugin 自管，详见 §8）

**进程间通信**：
- AICTO ↔ PM：HTTP（kickoff_project 调用）+ 共享 dev.db（CTO mode=ro 读 + 自有表写）
- AICTO ↔ 军团：tmux send-keys（直发）+ inbox.jsonl（fallback）
- AICTO ↔ 骏飞 / PM 飞书 IM：飞书 app `cli_a949...` ws

## 3. Plugin 目录结构（最终）

```
/Users/feijun/Documents/AICTO/hermes-plugin/
├── plugin.yaml             # 改：identity.name = "程小远"; provides_tools = 16 个真工具
├── __init__.py             # 改：register() 注册 16 工具 + pre_llm_call hook 保留
├── schemas.py              # 改：16 个工具 JSON schema（替换 8 stub schema）
├── tools.py                # 改：16 工具 dispatch 入口（每工具 ≤30 行，调下面专用模块）
├── feishu_api.py           # 新建：整文件 copy 自 prodmind/feishu_api.py + 改 3 处常量 ◄── ADR-004
├── pm_db_api.py            # 新建：CTO 专用，封装 8 个 PM 只读工具 + 2 个综合工具
├── adr_storage.py          # 新建：5 张 CTO 自有表的写入（_cto_own_connect 路径）◄── ADR-002
├── legion_api.py           # 新建：dispatch_to_legion_balanced + appeal 协议 ◄── ADR-005
├── error_classifier.py     # 新建：4 级错误分类的判定 + 重试调度 ◄── ADR-006
├── cron_runner.py          # 新建：18:00 daily_brief 内置 cron + last_run_ts 持久化 ◄── ADR-007
├── templates/              # 新建：技术方案 / ADR / 代码评审 / daily-brief 飞书 doc 模板
└── scripts/                # 选填：维护脚本（不通过 plugin register）
```

**部署侧** symlink：

```bash
mkdir -p /Users/feijun/.hermes/profiles/aicto/plugins
ln -sfn /Users/feijun/Documents/AICTO/hermes-plugin /Users/feijun/.hermes/profiles/aicto/plugins/aicto
```

← per-profile 隔离（不放 `~/.hermes/plugins/` 否则被三个 profile 共享）。

**当前缺失**（部署待补）：plugins 目录 + symlink，详见 PHASE-PLAN §1。

## 4. 核心模块设计

### 4.1 feishu_api.py（复用率 ~95%）

**整文件 copy 自 `~/Documents/prodmind/hermes-plugin/feishu_api.py`**（2040 行），仅改 3 处：

| 行号 | 旧 | 新 |
|------|-----|-----|
| `BITABLE_APP_NAME` (1686) | "ProdMind 项目档案" | "AICTO 技术决策档案" |
| `PROJECT_CHANNELS_PATH` (96) | `~/.hermes/plugins/prodmind/...` | `~/.hermes/profiles/aicto/plugins/aicto/...` |
| `BITABLE_STATE_PATH` (110) | 同上 | 同上 |

**保留不改**（即使暂不用也不删）：mermaid 渲染、bitable、image upload — 不引用就不会触发。

**关键 API**（详见 RECON §2.1-2.5）：
- `get_tenant_access_token()` — 进程内缓存 + 5min 提前刷新
- `read_docx_content(doc_id_or_url)` — 用 /blocks 端点保留结构
- `create_docx() / update_docx()` — 写技术方案 / ADR doc
- `_grant_doc_tenant_read()` — 创建后授权 PM 同 tenant 可读
- `send_card_message() / send_text_to_chat()` — 卡片 / 文本 + @mention
- `_send_post_with_mentions()` — `<at user_id="xxx">name</at>` 自动转 post 类型

### 4.2 pm_db_api.py

**职责**：CTO 读 PM 数据的唯一入口，所有 SQL 通过 `_readonly_connect()` 走 `mode=ro`。

```python
import sqlite3
PRODMIND_DB_PATH = "/Users/feijun/Documents/prodmind/dev.db"

def _readonly_connect():
    uri = f"file:{PRODMIND_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn

# 8 个只读工具（R-TL-7~14）
def read_pm_project(args): ...
def read_pm_prd(args): ...
def list_pm_prd_decisions(args): ...
# ...

# 2 个综合工具（R-TL-15/16）
def get_pm_context_for_tech_plan(args):
    """一键拉 PRD + UserStories + Features + PRDDecisions + PRDOpenQuestions"""
    ...
def diff_pm_prd_versions(args):
    """对比两个 PRDVersion 的 content diff"""
    ...
```

**审计日志**：每次工具调用末尾写一行到 `~/.hermes/profiles/aicto/logs/read-audit.log`：
```
{"ts": "2026-04-25T18:00:01Z", "tool": "read_pm_prd", "args": {"prd_id": "..."}, "rows_returned": 1}
```

### 4.3 adr_storage.py

**职责**：5 张 CTO 自有表的 SQL CRUD（ADR / TechRisk / TechDebt / CodeReview / EngineerProfile）。

```python
def _cto_own_connect():
    conn = sqlite3.connect(PRODMIND_DB_PATH)  # 无 mode=ro
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def _ensure_cto_tables():
    """启动时建表（CREATE TABLE IF NOT EXISTS），仅建 5 张 CTO 表，不碰 PM 表"""
    ...

# ADR
def create_adr(project_id, number, title, decision, rationale, alternatives_considered, decided_by) -> str: ...
def list_adrs(project_id) -> List[Dict]: ...
def supersede_adr(adr_id, new_adr_id) -> None: ...

# TechRisk / TechDebt / CodeReview / EngineerProfile 同模式
```

**ADR number 格式**（待 R-OPEN 仲裁，默认）：
- per-project 递增："ADR-0001"、"ADR-0002"... 在同一 project_id 内递增
- 跨项目独立编号
- 字段定义：`number INTEGER NOT NULL` + 显示时格式化为 `f"ADR-{number:04d}"`

### 4.4 legion_api.py

**职责**：dispatch_to_legion_balanced 实现 + appeal 协议。

```python
def discover_online_commanders():
    """读 ~/.claude/legion/directory.json + tmux list-sessions 找在线军团"""
    # 复用 prodmind/tools.py:831-903 模式

def dispatch_to_legion_balanced(args):
    tasks = args["tasks"]
    legions = discover_online_commanders()
    
    # 1. 拓扑排序 — 找出 ready tasks（depends_on 全部 done）
    ready_tasks = topological_ready(tasks)
    
    # 2. 负载均衡 — 每军团当前 task count ≤2
    load_map = {l: count_legion_load(l) for l in legions}
    
    # 3. EngineerProfile 匹配（Phase 1 hardcoded）
    skills_map = HARDCODED_LEGION_SKILLS  # 见 §10 扩展点
    
    # 4. 派单（双通道）
    assignments = []
    for task in ready_tasks:
        legion = pick_best_legion(task, legions, load_map, skills_map)
        if not legion:
            assignments.append({"task_id": task.id, "deferred": True, "reason": "all legions full"})
            continue
        payload = build_payload(task)  # PRD 摘要 + 技术方案 + GWT
        send_to_commander(legion, payload)  # tmux + inbox 双通道
        assignments.append({"task_id": task.id, "legion_id": legion.id, "payload_summary": "..."})
        load_map[legion.id] += 1
    
    return {"assignments": assignments, "deferred": [t for t in tasks if t.id in deferred_ids]}

def send_to_commander(legion, payload):
    """复用 prodmind/tools.py:933-995 模式 — tmux send-keys + inbox.jsonl 双通道"""
    # 1. 写 inbox.jsonl（带 fcntl 锁）
    write_inbox(legion.commander_id, {
        "id": f"msg-{int(time.time()*1000)}",
        "from": "AICTO-CTO",
        "to": legion.commander_id,
        "type": "task",
        "payload": payload,
        "cto_context": {                      # ◄── 新增字段（向后兼容）
            "tech_plan_id": payload.tech_plan_id,
            "adr_links": payload.adr_links,
            "feishu_doc_url": payload.feishu_doc_url,
        },
        "timestamp": now_iso(),
        "read": False,
        "summary": f"AICTO 派发: {payload.title}",
    })
    # 2. tmux send-keys 一行通知（"@<commander> 收到 AICTO 任务，详细内容在 inbox/"）
    if tmux_alive(legion):
        tmux_send_keys(legion, f"@{legion.commander_id} AICTO 派任务，inbox/<id> 查看")
```

**Appeal 协议**（R-FN-4.8 / R-OPEN-3 默认 1 次）：

```
军团收到 BLOCKING → 不同意 → 写 inbox.jsonl 给 AICTO（type=appeal, appeal_id=<auto>）
                                              │
                                              ▼
AICTO appeal_handler 读 inbox → LLM 评估
                                  │
                  ┌───────────────┴────────────────┐
                  ▼                                ▼
            收回 BLOCKING                      维持 BLOCKING
                  │                                │
            UPDATE CodeReview                  appeal_count >= 1?
            SET status='retracted'                │
                  │                       ┌───────┴────────┐
                  ▼                       ▼                ▼
            通知军团（飞书 @）          升级骏飞（飞书      继续维持
                                       @张骏飞 + 卡片仲裁）
```

## 5. 协议规范

### 5.1 工具协议（来自 RECON §5）

| 维度 | 规范 |
|------|------|
| 函数签名 | `def tool_name(args, **kwargs) -> str` |
| 同步/异步 | 全部同步（与 ProdMind 一致）|
| 输入校验 | `args.get(key, default)`，不用 `args[key]` |
| schema 校验 | Hermes runtime 自动校验类型 + required |
| 业务校验 | 在 handler 顶部，失败返 `{"error": "..."}` |
| 输出格式 | `json.dumps({...}, ensure_ascii=False)` |

### 5.2 错误协议（R-NFR-19~22 + ADR-006）

| 形态 | 何时使用 |
|------|---------|
| `{"error": "msg"}` | 输入 / 业务校验失败 |
| `{"error": str(e), "level": "tech\|permission\|intent\|unknown"}` | 异常捕获 |
| `{"success": True, ...}` | 正常返回（仅顶层工具）|
| `{"status": "not_implemented", ...}` | stub（Phase 1 完成前所有未实现工具保留此形态）|

**反幻觉硬约束**：错误**必须**用 `error` key，不许包装成 `{"success": False, "message": "..."}`（LLM 会当成"操作完成"）。

### 5.3 mailbox 协议（向后兼容现有 inbox.jsonl）

**保留字段**（不动现有 schema）：
```json
{"id", "from", "to", "type", "payload", "timestamp", "read", "summary"}
```

**新增字段**（CTO 加，老 commander 忽略）：
```json
{
  "cto_context": {                  # AICTO 派单时附加
    "tech_plan_id": "...",
    "adr_links": ["ADR-0001", "ADR-0002"],
    "feishu_doc_url": "https://..."
  },
  "appeal_id": "appeal-...",        # appeal 类型消息
  "appeal_count": 1,                # 当前 appeal 轮次
  "priority": "high|normal|low"     # 派单优先级（由 dispatch_to_legion_balanced 写入）
}
```

**新 type**：
- `task`（PM 现用，CTO 复用）
- `appeal`（CTO 新增）
- `appeal_response`（CTO 新增）
- `escalation`（CTO 新增 — 升级骏飞）

### 5.4 ADR JSON schema（5 张表写入参数）

```python
# create_adr 参数
{
    "project_id": str,            # 关联 ProdMind Project.id
    "number": int,                # per-project 递增（DB 层 max(number)+1）
    "title": str,                 # "选择 PostgreSQL 作为 OLTP 主存"
    "decision": str,              # "使用 PostgreSQL 14+，开启 logical replication"
    "rationale": str,             # 长文本，含权衡过程
    "alternatives_considered": [  # 备选方案
        {"option": "MySQL", "rejected_reason": "..."},
        {"option": "MongoDB", "rejected_reason": "..."}
    ],
    "decided_by": str,            # "AICTO" 或 "AICTO + 张骏飞"
    "supersedes": Optional[str],  # 旧 ADR id（如有）
}
```

## 6. 4 级错误分类判定矩阵（R-NFR-19~22 详细）

| 错误来源 | 异常关键词 / HTTP code | 默认级别 | 处理动作 |
|---------|----------------------|---------|---------|
| 网络 | ConnectionError / Timeout / ConnectTimeout / ReadTimeout | 技术 | 重试 3 次（1s/2s/4s 退避）|
| HTTP 5xx | 500/502/503/504 | 技术 | 重试 3 次 |
| HTTP 401/403 | 飞书 token 失效（先尝试刷新 token 再重试 1 次）/ 永久权限拒绝 | 权限 | 飞书 @张骏飞 |
| HTTP 429 | rate limit | 技术 | 退避 60s 重试 1 次 |
| LLM API | 模型暂时拒答 / 超 context | 技术 | 重试 1 次 + 截断输入 |
| LLM 拒答 | 永久拒答（policy 拒绝）| 意图 | 给 PM 2-3 候选选项 |
| dev.db 写挡 | `attempt to write a readonly database` | 权限 | 内部 bug，立即升级骏飞（CTO 误写 PM 表）|
| dev.db 业务 | UNIQUE / FOREIGN KEY 违反 | 意图 | 给候选选项（如 number 已存在）|
| git push | 拒绝 / 冲突 | 权限 | 升级骏飞（要求人工解冲突）|
| 飞书 401 / app 锁 | `feishu_app_lock` failed | 权限 | 升级骏飞 |
| 输入校验 | required 缺失 / 类型错 | 意图 | 给 PM 候选选项 |
| 未识别异常 | stack trace 无关键词 | 未知 | 升级骏飞 + 完整 stack |

**适用范围**：全 6 能力共享此矩阵（R-OPEN-2 默认，待 PM 仲裁）。

## 7. SOUL.md 改写方案（ADR-009）

替换 `~/.hermes/profiles/aicto/SOUL.md` 为 RECON §3.1 的"程小远版"草稿。关键变更：

1. 身份：AICTO → **程小远**（中文人格化名字）
2. 工作纪律：5 条反幻觉迁入 SOUL.md（PRD §三要求）
3. 边界声明：显式增加"⊥ PM 维度正交"段
4. 能力清单：从"8 stub 设计中"改为 16 工具上线（见 RECON §3.1）
5. 工作节奏：5 步流程明文化（先看 PM PRD → 项目分析 → 带权衡方案 → 标注风险 → 写 ADR）

**注意**：`~/.hermes/profiles/aicto/config.yaml` 的 `HERMES_SYSTEM_PROMPT` 是死代码（Hermes 不读），可删可留。决定**删**避免误导审阅者。

## 8. cron 实现（ADR-007）

**方案**：plugin 自管 asyncio loop + last_run_ts 持久化文件，**不**用 launchd / crontab。

**理由**：
- launchd plist 在用户层，AICTO 重装/迁移要重配（不便携）
- crontab 与 Hermes profile 不绑定（PM/HR/CTO 都建 cron 会乱）
- plugin 自管 = 与 gateway 进程同生命周期，零额外依赖

**实现**：

```python
# cron_runner.py
import asyncio, time, json, pathlib

LAST_RUN_PATH = pathlib.Path.home() / ".hermes/profiles/aicto/plugins/aicto/state/last_brief_run.json"

async def daily_brief_loop():
    while True:
        now = time.localtime()  # 服务器本地时区，默认 UTC+8
        if now.tm_hour == 18 and now.tm_min == 0:
            if not _ran_today():
                run_daily_brief()
                _mark_ran(now)
        # 错过 18:00：09:00 检查 last_run_ts，如昨天 18:00 没跑则补发
        if now.tm_hour == 9 and now.tm_min == 0:
            if _missed_yesterday():
                run_daily_brief(make_up=True)
                _mark_ran(now)
        await asyncio.sleep(60)  # 每分钟检查一次

def register_cron(ctx):
    """plugin __init__.py 调用，启动 background loop"""
    asyncio.get_event_loop().create_task(daily_brief_loop())
```

**hook**：在 `__init__.py` 的 `register(ctx)` 末尾调 `register_cron(ctx)`。

**故障恢复**：gateway 重启后从 `last_brief_run.json` 读取上次运行时间，决定是否补发。

## 9. 部署拓扑（最终态）

```
~/.hermes/profiles/aicto/
├── config.yaml              # 改：删 HERMES_SYSTEM_PROMPT，可选加 agent.system_prompt
├── .env                     # 改：FEISHU_BOT_NAME=程小远（其他保留）
├── SOUL.md                  # 改：程小远版（ADR-009）
├── state.db                 # 自动创建（Hermes 自管）
├── sessions/                # 自动
├── plugins/                 # ◄── 新建（部署关键）
│   └── aicto -> /Users/feijun/Documents/AICTO/hermes-plugin    # symlink
├── skills/                  # 已有 77 bundled skills
├── cache/                   # 自动
└── logs/                    # 新建：read-audit.log / cron.log

~/Documents/AICTO/hermes-plugin/
├── plugin.yaml              # 改 identity.name = 程小远 / 16 工具
├── __init__.py              # 改 register() 含 cron 启动
├── schemas.py               # 改 16 工具 schema
├── tools.py                 # 改 16 工具 dispatch
├── feishu_api.py            # 新建
├── pm_db_api.py             # 新建
├── adr_storage.py           # 新建
├── legion_api.py            # 新建
├── error_classifier.py      # 新建
├── cron_runner.py           # 新建
├── templates/               # 新建
│   ├── tech-plan.md
│   ├── adr.md
│   ├── code-review-report.md
│   └── daily-brief.md
└── state/                   # 新建（持久化状态）
    └── last_brief_run.json
```

## 10. 扩展点（Phase 2+ 预留）

| 扩展点 | Phase 1 处理 | Phase 2+ 演进 |
|-------|-------------|--------------|
| EngineerProfile 表 | hardcoded dict | 落表 + LLM 自动维护 skills_json |
| TechDebt 工具 | 不实现（v0.1 命名废弃）| Phase 2 实现 analyze_technical_debt + propose_refactor |
| 跨项目技术债盘点 | 不做 | Phase 2/3（v0.1 §10.5 仍 open）|
| 飞书 bitable | feishu_api.py 保留代码不调用 | Phase 2 用作 ADR 看板 |
| 长任务异步化 | 同步阻塞 | Phase 2 加 task_id + get_status 工具 |
| 多项目群通知 | 单 AICTO 群 | Phase 2 按 project chat_id 分发 |
| KR 度量看板 | 仅埋点 | Phase 2 飞书卡片日报 |

## 11. 实施依赖图

```
ADR-001 工具命名替换  ──┐
                      ├──► tools.py / schemas.py / plugin.yaml 改
ADR-002 ADR 表存储位置  ┘
                      ├──► adr_storage.py 实现
ADR-003 plugin 目录    ──► 部署 symlink + 5 新模块
ADR-004 飞书 API 复用  ──► feishu_api.py 整文件 copy
ADR-005 dispatch 协议  ──► legion_api.py 实现 + appeal
ADR-006 4 级错误分类   ──► error_classifier.py + 嵌入 6 工具
ADR-007 cron 实现      ──► cron_runner.py + __init__.py 启动
ADR-008 PM HTTP 协议   ──► kickoff_project 第 3 步
ADR-009 SOUL.md 改写   ──► profile/SOUL.md 替换
ADR-010 PRD 数据源     ──► design_tech_plan input schema
```

实际实施顺序见 PHASE-PLAN.md。

## 12. 关键 ADR 索引

| ADR | 主题 | 状态 |
|-----|------|------|
| ADR-001 | 工具命名替换：8 stub → 16 工具（6 + 8 + 2）| LOCKED |
| ADR-002 | ADR 表存储位置：共享 prodmind dev.db（默认）| PROVISIONAL（待 PM Q-1 仲裁）|
| ADR-003 | plugin 目录结构 + symlink 部署 | LOCKED |
| ADR-004 | 飞书 API 整文件复用 ProdMind | LOCKED |
| ADR-005 | dispatch 协议向后兼容 + appeal | LOCKED |
| ADR-006 | 4 级错误分类边界（默认）| PROVISIONAL（待 PM Q-2 仲裁）|
| ADR-007 | 18:00 cron plugin 自管 + 持久化 | LOCKED |
| ADR-008 | kickoff_project 第 3 步用 HTTP | PROVISIONAL（待 PM Q-8 仲裁）|
| ADR-009 | SOUL.md 程小远化 + 5 条纪律迁入 | LOCKED |
| ADR-010 | PRD 数据源三选一（dev.db 主）| PROVISIONAL（待 PM Q-4 仲裁）|

LOCKED = 实现阶段不可推翻；PROVISIONAL = 默认推进，PM 答复后可改。

---

**ARCHITECTURE 完。**

下一步：PHASE-PLAN.md（实施编排）+ ADR 详细文档 + features.json。
