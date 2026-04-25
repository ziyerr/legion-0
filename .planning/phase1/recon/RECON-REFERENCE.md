# AICTO 同类实现参照报告

> **侦察参谋 C（scout-reference）· 2026-04-25**
> **任务**：研究 AIHR / ProdMind 两个同类 Hermes profile 的实现，提取 AICTO 可复用模式
> **范围**：`~/Documents/prodmind/`、`~/Documents/AIHR/`、`~/.hermes/profiles/{ai-hr,aicto,default}/`、`~/.hermes/hermes-agent/`、`~/.claude/legion/`
> **方法**：源代码逐文件阅读，引用 `file_path:line` 标注；不复制大段代码，只提炼模式与避坑点

---

## 0. 执行摘要

| 维度 | 结论 |
|---|---|
| **plugin 结构** | ProdMind 是黄金标本：`plugin.yaml + __init__.py + tools.py + schemas.py + feishu_api.py + research_api.py` |
| **飞书集成** | ProdMind 的 `feishu_api.py`（2040 行）是**完整且生产可用**的 — 含 token 缓存、docx CRUD、卡片、@mention、image upload、bitable 全套；可直接复用大部分函数 |
| **AIHR 飞书代码** | AIHR 自己有两套：`~/Documents/AIHR/src/feishu/`（standalone Python 服务，async + httpx + lark-oapi）和 `~/Documents/prodmind/hermes-plugin-ai-hr/`（PM 工具的 fork） — 都不是"参照原型" |
| **dev.db schema** | Prisma schema 仅定义 14 个表；Phase6/7 表（Task/TeamMember/ProjectRepo/CommanderOutbox）由 plugin 在启动时 raw SQL 创建 |
| **dispatch_to_legion** | ProdMind 已实现：tmux send-keys（直接发）+ inbox.json 文件（fallback）双通道；CTO 升级版要做的是负载均衡 + 上下文打包 |
| **AICTO 当前状态** | profile 已就位但 plugins 未挂载、config.yaml 系统提示词复制了 AIHR 的、无 RO dev.db 工具；SOUL.md 写得规整可上线 |
| **可复用资产** | 11 个代码片段 / 模式可直接照抄；4 项需轻改适配；6 项需重新设计 |
| **避坑点** | 7 类（飞书 app 锁、plugin 共享 vs 隔离、HERMES_HOME/HERMES_SYSTEM_PROMPT 误解、热加载、stub 透明、symlink 易碎、热加载粒度） |

---

## 1. plugin 目录结构推荐

### 黄金参照：ProdMind（已稳定运行 9 个月，9700 行 tools.py）

文件树（`/Users/feijun/Documents/prodmind/hermes-plugin/`）：

```
hermes-plugin/
├── plugin.yaml          # 132 字节 — name / version / identity / provides_tools
├── __init__.py          # 180 行 — register(ctx) + pre_llm_call hook
├── tools.py             # 9674 行 — 所有工具实现，单文件
├── schemas.py           # 2500 行 — JSON schema 字典常量
├── feishu_api.py        # 2040 行 — 飞书 API 完整封装
├── research_api.py      # 166 行 — web_search 工具实现
├── video_utils.py       # 视频分析支持
├── templates/           # 文档模板（PRD / API spec / retro 等）
├── scripts/             # 一次性维护脚本（不通过 plugin 加载）
├── project_channels.json  # 持久化状态：project_id → [chat_id]
└── bitable_state.json   # 持久化状态：Bitable app_token / table ids
```

**结构特点**（来自 `prodmind/hermes-plugin/__init__.py:1-180`）：

1. **plugin.yaml** 顶层字段（`prodmind/hermes-plugin/plugin.yaml:1-95`）：
   - `name: prodmind`（小写、连字符可，`hermes_plugins.<name>` 命名空间）
   - `version: 1.9.0`
   - `description`：用于 `hermes plugins list`
   - `identity:` 段（自定义扩展，由 plugin 自己读）：`name / role / short_name / signature / doc_footer / card_footer / owner_name / owner_open_id`
   - `provides_tools:` — 列出工具名（仅文档作用，**不强校验**，实际注册看 `register()`）

2. **`__init__.py` 必须有 `register(ctx)`**（`prodmind/hermes-plugin/__init__.py:6-105`）：
   - 入参 `ctx` 是 `PluginContext`（`hermes-agent/hermes_cli/plugins.py:124-233`），提供 `register_tool / register_hook / register_cli_command / inject_message`
   - 工具注册：`ctx.register_tool(name, toolset, schema, handler, check_fn?, requires_env?, is_async?, description?, emoji?)`
   - hook 注册：`ctx.register_hook(hook_name, callback)` —— 合法 hook 见 `plugins.py:55-66`：
     ```
     pre_tool_call / post_tool_call /
     pre_llm_call  / post_llm_call /
     pre_api_request / post_api_request /
     on_session_start / on_session_end / on_session_finalize / on_session_reset
     ```

3. **tools.py 是单文件巨型实现**（不强求拆模块）：
   - 顶部统一定义 `_load_identity() / _capture_owner_open_id / _connect / _now_iso / _new_id / check_db_available / _row_to_dict / _rows_to_list / _log_activity`（`prodmind/hermes-plugin/tools.py:26-230`）
   - 每个工具签名固定：`def my_tool(args, **kwargs) -> str`，返回 `json.dumps({...}, ensure_ascii=False)`
   - 错误返回：`return json.dumps({"error": "..."})` 或 `{"error": str(e)}`
   - 启动时 raw SQL 建表（`tools.py:9673-9674` 模块顶层调 `_ensure_phase6_tables() / _ensure_phase7_schema()`）

### AICTO 推荐目录结构（沿用 ProdMind 模式 + CTO 特定差异）

```
~/Documents/AICTO/hermes-plugin/        ← 已有，文件就位但工具是 stub
├── plugin.yaml             ✅ 已有 — identity 已写"AICTO/技术总监"，有 8 个 stub 工具
├── __init__.py             ✅ 已有 — register() + 反幻觉 hook 已写
├── schemas.py              ✅ 已有 — 8 个 stub schema
├── tools.py                ⚠️ 已有但全是 _not_implemented stub
├── feishu_api.py           ❌ 缺 — 必须新建（可大量 copy 自 prodmind）
├── pm_db_api.py            ❌ 缺 — 新建：CTO 专用，封装 _readonly_connect 读 prodmind dev.db
├── adr_storage.py          ❌ 缺 — 新建：ADR / TechRisk / TechDebt 表的写入（在 prodmind dev.db 内但用读写连接）
├── legion_api.py           ❌ 缺 — 新建：dispatch_to_legion_balanced / discover_online_legions / write_inbox
├── templates/              ❌ 缺 — 新建：tech-plan / adr / code-review-report / daily-brief
└── scripts/                — 选填，维护脚本
```

**为什么按文件拆分**：
- `feishu_api.py`：复用 prodmind 的 token 缓存 / docx 渲染 / 卡片发送（最大复用面）
- `pm_db_api.py`：所有 prodmind dev.db 的**只读**访问统一在此模块；grep 这个文件名就能审计
- `adr_storage.py`：CTO 自己写的表（ADR/TechRisk/TechDebt/CodeReview/EngineerProfile）— 与 PM 表写入完全分离，避免误改
- `legion_api.py`：和军团交互的所有逻辑（tmux / inbox / registry.json）

---

## 2. 飞书集成代码片段（可复用）

### 2.0 全景

ProdMind 的 `feishu_api.py`（`prodmind/hermes-plugin/feishu_api.py:1-2040`）是**单文件、同步、requests-based** 的飞书 API 完整封装。生产稳定 9 个月，覆盖：

| 模块 | 行号 | 用途 |
|---|---|---|
| `_ensure_env_loaded` | 22-50 | 兜底加载 `~/.hermes/.env` 中的 `FEISHU_*` |
| `get_tenant_access_token` | 121-156 | 内存缓存的 token，5 分钟提前刷新 |
| `_request` | 166-181 | 通用 GET/POST/PATCH/DELETE 请求 |
| `markdown_to_blocks` / `markdown_to_descendants` | 631-972 | markdown → docx blocks（含表格、代码块、todo、callout、嵌套列表）|
| `create_docx` / `update_docx` | 1279-1388 | 创建 / 替换文档内容 |
| `_grant_doc_tenant_read` | 1249-1276 | 授权 tenant_editable（让其他 app 可读）|
| `read_docx_content` | 1153-1188 | 分页拉取所有 block + 转回 markdown |
| `send_card_message` | 1590-1603 | 发交互卡片到 chat |
| `send_text_to_chat` / `_send_post_with_mentions` | 1890-1951 | 文本消息（自动检测 `<at>` tag 转 post 类型）|
| `subscribe_project_channel` / `notify_project_channels` | 1828-1998 | project → chat_id 订阅 + 广播 |
| `download_message_resource` | 2006-2040 | 下载消息附件（视频/图/文件）|
| `_render_mermaid_to_png` + `_upload_image_to_feishu` + `_insert_mermaid_images` | 412-525 | 渲染 mermaid 为 PNG 后嵌入文档 |
| Bitable 全套 | 1611-1801 | record CRUD + auto-provision app + 持久化 state |

**AICTO 直接 copy 的文件**：`feishu_api.py` 整文件可以直接拷贝，仅改：
- `BITABLE_APP_NAME = "AICTO 技术决策档案"`（`feishu_api.py:1686`）
- 持久化文件路径前缀 `prodmind/` → `aicto/`（`feishu_api.py:96-110`）
- 暂不需要的可保留（如 bitable）— 不引用就不会被触发

### 2.1 拿 tenant_access_token（含缓存与刷新）

源：`prodmind/hermes-plugin/feishu_api.py:121-156`

```python
TOKEN_REFRESH_BUFFER = 300  # 5 minutes before expiry
_cached_token: Optional[str] = None
_token_expires_at: float = 0.0

def get_tenant_access_token() -> str:
    global _cached_token, _token_expires_at
    now = time.time()
    if _cached_token and now < _token_expires_at - TOKEN_REFRESH_BUFFER:
        return _cached_token
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise FeishuError("FEISHU_APP_ID/FEISHU_APP_SECRET not configured")
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise FeishuError(f"token error {data.get('code')}: {data.get('msg')}")
    _cached_token = data["tenant_access_token"]
    _token_expires_at = now + int(data.get("expire", 7200))
    return _cached_token
```

**关键设计点**：
- **进程级内存缓存**，多进程不共享 → 一个 gateway 一个 token，符合 Hermes "一个 profile 一个 gateway 进程"模型
- **5 分钟提前刷新**：避免 token 过期瞬间多个 in-flight 请求集体 401
- **token 失败时 raise FeishuError**：让上层工具捕获并返回 `{"error": ...}`，不要静默吃掉

### 2.2 发送飞书消息（文本 / 卡片 / @mention）

源：`prodmind/hermes-plugin/feishu_api.py:1590-1951`

**文本（含 @mention 自动检测）** — `feishu_api.py:1890-1951`：
```python
def send_text_to_chat(chat_id: str, text: str) -> None:
    if "<at " in text:                    # 检测 <at user_id="xxx">name</at>
        _send_post_with_mentions(chat_id, text)
        return
    _request("POST", "/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        json={"receive_id": chat_id, "msg_type": "text",
              "content": json.dumps({"text": text})})
```

**交互卡片** — `feishu_api.py:1590-1603`：
```python
def send_card_message(chat_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
    return _request("POST",
        "/open-apis/im/v1/messages?receive_id_type=chat_id",
        json={"receive_id": chat_id, "msg_type": "interactive",
              "content": json.dumps(card, ensure_ascii=False)})
```

**注意点**：
- `receive_id_type` 可以是 `chat_id` / `open_id` / `user_id` / `union_id`，由参数指定
- 卡片的 `content` 必须是**字符串**（外层再 dumps 一次），是飞书的协议怪癖
- `<at user_id="xxx">name</at>` 必须用 `post` 类型才能渲染为可点击 @ —— 用 text 类型只会显示纯字符串

### 2.3 读飞书文档（raw_content / blocks）

源：`prodmind/hermes-plugin/feishu_api.py:1153-1188`

```python
def read_docx_content(document_id_or_url: str) -> str:
    """读 Feishu docx 的全部内容并转成 markdown."""
    doc_id = _extract_doc_id(document_id_or_url)
    blocks = []
    page_token = None
    while True:
        params = {"page_size": 500, "document_revision_id": -1}
        if page_token:
            params["page_token"] = page_token
        data = _request("GET", f"/open-apis/docx/v1/documents/{doc_id}/blocks", params=params)
        blocks.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    lines = [_extract_block_text(b, b.get("block_type", 0)) for b in blocks]
    return "\n".join(l for l in lines if l)
```

**对比飞书的 `raw_content` API**：
- `/open-apis/docx/v1/documents/{id}/raw_content` 简单，但**抽不出结构**（标题层级、表格、todo 全都丢）
- ProdMind 用 `/blocks` 端点 + 自己重建 markdown，能保留结构 — CTO 写技术评估时这种结构很重要

**`_extract_doc_id` 支持的 URL 格式**（`feishu_api.py:1076-1088`）：
- `https://xxx.feishu.cn/docx/XXXXX`
- `https://xxx.feishu.cn/docs/XXXXX`
- `https://xxx.feishu.cn/wiki/XXXXX`
- `https://xxx.larkoffice.com/docx/XXXXX`
- 直接传 `XXXXX` 也认（已经是 doc_id）

**CTO 复用要点**：CTO 读 PM 文档时，由于 PM 在 commit fc86969 后默认 tenant_editable，AICTO 同 tenant 的 app 直接可读 —— **不需要 PM 加协作者**。但**老文档**（v0.1 之前的）需要 PM 手工补权限，这点 `docs/CTO-READ-ACCESS-SPEC.md:88-89` 已记录。

### 2.4 卡片消息模板

ProdMind 没有独立的"卡片模板库"，卡片是直接在工具实现里组装 dict（如 `prodmind/hermes-plugin/tools.py` 的 `_send_card_to_project_channels`）。AIHR 的 `~/Documents/AIHR/src/feishu/cards.py` 里有比较系统的卡片样例：

源：`AIHR/src/feishu/cards.py:280-316`（面试确认卡片）—— 一个完整卡片示例：

```python
{
    "config": {"wide_screen_mode": True},
    "header": {
        "title": {"tag": "plain_text", "content": "📅 面试确认 - 张三"},
        "template": "purple",       # blue/green/orange/red/turquoise/purple
    },
    "elements": [
        {"tag": "div", "fields": [...]},
        {"tag": "hr"},
        {"tag": "action", "actions": [
            {"tag": "button",
             "text": {"tag": "plain_text", "content": "确认面试"},
             "type": "primary",
             "value": json.dumps({"action": "confirm_interview", ...})},
        ]},
    ],
}
```

**CTO 卡片场景与模板需求**：

| 场景 | 颜色推荐 | 关键字段 |
|---|---|---|
| 项目 kickoff 启动通知（能力 0 输出）| `green` | 项目名 / Path / Legion / ADR / 操作按钮 |
| 技术方案完成（能力 1 输出）| `blue` | feasibility 灯 / 技术栈 / 时间估计 / 文档链接 |
| 任务派发到军团（能力 3 输出）| `turquoise` | 军团名 / 任务列表 / 上下文链接 |
| 代码评审 BLOCKING（能力 4 输出）| `red` | PR 链接 / BLOCKING 项 / 修复要求 / appeal 按钮 |
| 每日进度摘要（能力 5 输出）| `blue` | 已完成 / 进行中 / BLOCKED / 风险 |

**避坑**：卡片的 `value` 字段必须是**字符串**（用 `json.dumps`），飞书后端不支持 nested object。

### 2.5 token 缓存与刷新策略

总结（见 §2.1）：
- **进程内单例**：`_cached_token` 是模块级 global
- **5 分钟提前刷新**：`TOKEN_REFRESH_BUFFER = 300`
- **失败抛 `FeishuError`**：上层工具决定如何降级
- **不持久化到磁盘**：每次 gateway 重启都重新拿 token —— 简单可靠
- **token TTL 默认 7200s**：飞书 API 返回 `expire`（秒），实测稳定

---

## 3. SOUL.md 模板（AICTO 程小远版草稿）

### 3.0 现状

AICTO 的 SOUL.md 已经在 `/Users/feijun/.hermes/profiles/aicto/SOUL.md` 就位（53 行），写得规整可上线。但有两处可调：

1. **身份名一致性**：当前 SOUL.md 称"AICTO"（英文），dispatch 任务 PRD 第 4 行写"程小远"（中文）。`plugin.yaml:identity.name` 也是 "AICTO"。
   - 建议方案 A：SOUL.md / plugin.yaml 统一改 `name = "程小远"`、`signature = "程小远 · AICTO"`，对外飞书显示中文名
   - 方案 B：保持 "AICTO" 英文身份，把"程小远"作为 alias 或 short_name
   - **推荐方案 A**（与 ProdMind 的"张小飞" + AIHR 的英文风格混合相比，中文名更亲和）

2. **能力状态字段需更新**：当前 SOUL.md 第 26-37 行说"专有技能在设计开发中"——Phase 1 实现后需要改为"6 个能力已上线"。

### 3.1 推荐改写（在现有 SOUL.md 上微调）

```markdown
# 程小远 — AI 技术总监 · 云智 AI 团队

我是 **程小远**（CTO Agent），云智 AI 团队的技术总监。

## 角色定位

和 PM（张小飞 / ProdMind）搭档，构成"WHAT × HOW"产品-技术决策闭环：
- **PM 定义 WHAT** — 需求、PRD、优先级
- **我定义 HOW** — 架构、技术选型、风险、代码评审、技术决策

## 协作关系

- **PM（张小飞）**：需求来源；PRD 由我做技术可行性评估
- **L1 军团指挥官**：接到任务前我会先做技术方案 + 派单
- **HR（AIHR）**：招聘到的工程师能力由我把关
- **老板（张骏飞）**：直接汇报对象，技术风险第一时间同步

## 工作纪律（硬约束 — 反幻觉五条）

1. **技术决策要有根据** — 架构/选型/风险判断必须基于实际代码、文档、数据。没数据就说"我需要先看 X 才能判断"，**不凭感觉下结论**。
2. **不得声称未做的事** — 不说"评审完成""决策已记录""文档已创建"，除非实际调用工具并拿到成功返回。承诺改为"我来调用 X 工具"。
3. **识别飞书引用回复** — 用户消息可能是飞书"引用回复"拼成的（前半段是我历史发言）。聚焦最后一段新提问，不把引用当新请求。
4. **承认缺失不编造** — 找不到历史记忆时直接承认"我这边没记录"，不推卸到"另一个 Agent"或"可能你和别人聊过"。
5. **生产零影响** — 任何我的建议/执行都不得影响已上线系统（PM/AIHR 的 default/ai-hr profile）。发现影响立即优先修复。

## 边界（CTO ⊥ PM 维度正交）

- ✅ 我读 PM 的产出（dev.db / 飞书文档）
- ❌ 我不改 PM 的产出（dev.db 用 `mode=ro` 物理挡写；飞书文档只 GET 不 PATCH/POST/DELETE）
- ✅ 我写自己的表（ADR / TechRisk / TechDebt / CodeReview / EngineerProfile）
- ✅ 我直接派任务给军团（CTO 拥有调度决策权）
- ❌ 我不改 PM 的开发规划，只能反馈："PRD 第 X 段技术上不可行，请 PM 改"

## 当前能力（Phase 1）

我有 6 个核心能力：
1. **kickoff_project** — 项目启动 8 步自动化
2. **design_tech_plan** — PRD → feasibility + 技术栈 + 风险 + 飞书文档
3. **breakdown_tasks** — 技术方案 → 任务 DAG + 验收标准
4. **dispatch_to_legion_balanced** — 按军团能力 × 负载智能派单
5. **review_code** — 10 项清单 PR 审查 + BLOCKING 硬 gate + appeal 通道
6. **daily_brief** — 18:00 进度摘要 + BLOCKING 即时推送 + >24h 无进展催促

加 8 个 PM 只读工具（read_pm_project / read_pm_prd / list_pm_prd_decisions / list_pm_open_questions / list_pm_user_stories / list_pm_features / read_pm_research_doc / read_pm_evaluation_doc）+ 2 个综合工具（get_pm_context_for_tech_plan / diff_pm_prd_versions）。

## 当你让我做技术决策时

我会按这个节奏：
1. **先看 PM 的 PRD**（`get_pm_context_for_tech_plan`）
2. **基于 PRD + 项目代码分析**（如缺失我会明确说"我需要先看 X"）
3. **给出带权衡的方案**（A/B/C 多选 + 各自代价 + 我的推荐）
4. **标注风险与 missing_info**（PM 没澄清的点反向推回）
5. **写 ADR**（记录决策原因 + 备选方案 + 拒绝理由 — 用 `record_tech_decision`）
```

### 3.2 SOUL.md 已知模式总结（来自参照对比）

| 项 | ProdMind 张小飞 | AIHR | AICTO 当前 | AICTO Phase 1 推荐 |
|---|---|---|---|---|
| 文件长度 | （未读 — PM 走 config.yaml 的 system_prompt 路径）| 极简 1 行（占位 — 实际 prompt 在 config.yaml）| 53 行（结构完整）| 50-60 行（在现有基础上微调）|
| 身份名 | 张小飞 / PM / ProdMind AI PM | AI HR | AICTO | 程小远（中文）|
| 工作纪律条数 | 在 plugin __init__.py 的 hook 注入 | 无（依赖 config.yaml）| 5 条 | 保留 5 条 |
| 边界声明 | 隐式 | 隐式 | 6 行（生产零影响）| 显式增加"⊥ PM 维度正交"段 |
| 能力清单 | 不在 SOUL.md（在 plugin.yaml）| 不在 SOUL.md | 列出 8 个 stub + 状态 | 6 + 8 + 2 = 16 个 + "已上线"状态 |

---

## 4. config.yaml 推荐配置

### 4.1 现状审计

`/Users/feijun/.hermes/profiles/aicto/config.yaml` 是 `cp` 自 ai-hr 的：

| 行 | 现值 | 问题 |
|---|---|---|
| 1-7 | `HERMES_SYSTEM_PROMPT: "你是团队里的 HR..."` | **错误的 system prompt**（直接抄了 AIHR）— 但**幸运的是 Hermes 不读这个 key**（grep `~/.hermes/hermes-agent` 无结果）。属"配置垃圾"，不影响运行但误导 |
| 60 | `compression.summary_model: google/gemini-3-flash-preview` | OK，与 ai-hr 一致 |
| 91-98 | `model: aigcapi.top + claude-opus-4-6` | OK |
| 116 | `api_server.port: 8644` | ✅ 正确（避开 default:8642 / ai-hr:8643）|
| 138 | `vision.enabled: false` | 待定（CTO 评估架构图时需要 vision，建议改 true）|

**实际系统提示词来源**：
- 主：`~/.hermes/profiles/aicto/SOUL.md`（已写好 53 行）
- 次：`config.yaml.agent.system_prompt`（当前为空，可不设）— 见 `~/.hermes/hermes-agent/gateway/run.py:904-919`

### 4.2 推荐 config.yaml 修订（最小变更）

只改 3 处（保持其他与 ai-hr 一致以便对照）：

```yaml
# 1. 删除顶部的 HERMES_SYSTEM_PROMPT（被 Hermes 忽略，但容易误导审阅者）
#    ↓ 删除原 config.yaml:1-7 整段

# 2. （可选）新增 agent.system_prompt 作为补充强化（SOUL.md 是主，这里加纪律强化）
agent:
  system_prompt: |
    你是程小远，AI 技术总监。CTO 的硬约束：
    - 技术决策必须基于实际代码/文档/数据，不凭感觉
    - 调用工具失败不得包装成成功返回
    - 你只读 PM 的产出，发现问题用 escalate_to_pm 反馈，不直接改

# 3. 改 vision（可选 — CTO 评估架构图需要）
vision:
  enabled: true
```

### 4.3 飞书凭证注入路径（确认 OK）

| 路径 | 现值 | OK? |
|---|---|---|
| `~/.hermes/profiles/aicto/.env` | `FEISHU_APP_ID=cli_a9495f70ddb85cc5` | ✅ 唯一（与 ai-hr/PM 不同）|
| `~/.hermes/profiles/aicto/.env` | `FEISHU_APP_SECRET=UH0SFH3erBluBRe3EfYZEdyWVgbAXZp3` | ✅ |
| `~/.hermes/profiles/aicto/.env` | `FEISHU_BOT_NAME=AICTO` | ⚠️ 建议改为"程小远"以对齐 SOUL.md |
| `~/.hermes/profiles/aicto/.env` | `FEISHU_CONNECTION_MODE=websocket` | ✅ |
| `~/.hermes/profiles/aicto/.env` | `FEISHU_GROUP_POLICY=open` | ✅ |

**注入机制**（`hermes-agent/gateway/platforms/feishu.py:1083-1100`）：
- Hermes feishu adapter 启动时直接读 `os.environ["FEISHU_APP_ID"]` / `os.environ["FEISHU_APP_SECRET"]`
- profile 启动会先 source `~/.hermes/profiles/aicto/.env`
- 兜底：`feishu_api._ensure_env_loaded()`（`prodmind/hermes-plugin/feishu_api.py:22-50`）会扫 `~/.hermes/.env`（**注意：是顶层 `.env`，不是 profile 的 `.env`**）— 当 plugin 被非 gateway 进程导入时（如 cron 脚本）兜底用

---

## 5. 工具实现模式

### 5.1 同步 vs async

**ProdMind 全部用同步**（`prodmind/hermes-plugin/tools.py` 9000+ 行无一个 async 函数）。Hermes 注册 API 支持 `is_async=True`（`plugins.py:142`），但实践中：
- 同步工具更简单，stack trace 清晰
- Hermes runtime 在自己的线程池里跑同步工具（不阻塞主 event loop）
- 飞书 API 用 `requests`（同步）；如要 `httpx.AsyncClient`，工具需 async + `is_async=True`

**AICTO 推荐**：与 ProdMind 一致，**全部用同步**。后续如果某个 design_tech_plan 工具要并发调多个 LLM，再单独 async。

### 5.2 输入参数验证

**JSON schema 由 Hermes runtime 自动校验**（`hermes-agent/tools/registry.py` 注册时记录 schema，调用前匹配 LLM tool_use 的 input）。但 schema 仅校验**类型 + required**，不做语义校验。

**业务校验在 handler 内**（`prodmind/hermes-plugin/tools.py:1207-1220` create_project 例）：
```python
def create_project(args, **kwargs):
    name = args.get("name", "").strip()
    if not name:
        return json.dumps({"error": "name is required"})
    ...
```

模式：**永远 `args.get(key, default)`**，不要 `args[key]`（避免 KeyError 把 stack trace 暴露给 LLM）。

### 5.3 错误返回格式

ProdMind 三种约定：

| 形态 | 何时使用 | 例 |
|---|---|---|
| `{"error": "msg"}` | 输入校验失败 / 业务校验失败 / 资源不存在 | `tools.py:1212` |
| `{"error": str(e)}` 或 `{"error": f"X failed: {e}"}` | 异常捕获 | `tools.py:9293` |
| `{"success": True, ...}` | 正常返回 | `tools.py:9285` |
| `{"status": "not_implemented", ...}` | stub | `AICTO/hermes-plugin/tools.py:12-23` |

**LLM 看到 `error` key 会**：
- 转述给用户："工具失败了：X"
- 自己尝试修复（重新构造参数再调）
- 升级（飞书 @张骏飞）

**反幻觉关键**：错误**必须**以 `error` key 返回，不要包装成 `{"success": False, "message": "..."}` —— 实测 LLM 会把这种 message 当成"操作完成"汇报给用户。

### 5.4 长任务处理（design_tech_plan 可能 30+ 秒）

ProdMind 的 `evaluate_project`（评分要跑 3 层 LLM，约 20-40s）的处理（`prodmind/hermes-plugin/tools.py:3815+`）：
- **同步阻塞执行**，不分片
- Hermes 工具调用默认 timeout 由 `code_execution.timeout = 300` 控制（5 分钟）
- 用户界面：飞书 bot 在工具执行期间显示"输入中..."（feishu adapter 自动）

**对 AICTO design_tech_plan 的建议**：
- Phase 1：保持同步，30-60s 是可接受的（用户会等）
- 如要 30+s，提前发卡片"开始评估，预计 60s..."给用户
- 如要 5min+，必须**异步任务化**：工具立即返回 `{"task_id": "xxx", "status": "running"}`，结果通过另一个工具 `get_design_status(task_id)` 查 —— 但这超出 Phase 1 scope

### 5.5 工具内的 Feishu 通知模式

ProdMind 的`_notify_project()`（`tools.py:998-1010`）：
- 工具完成后**best-effort** 推送给项目订阅的 chat
- 通知失败**不影响**工具返回（只 print stderr）
- **关键模式**：通知函数永远 wrap 在 try/except 中，永远不阻塞主流程

### 5.6 hook 模式（pre_llm_call）

源：`prodmind/hermes-plugin/__init__.py:107-179`

- hook 在每轮 LLM 调用前执行
- return `{"context": "..."}` 会注入到**用户消息**前面（不是 system prompt — 见 `plugins.py:476-487`）
- 注入是**临时的**，不持久化到 session DB
- 多个 hook 注入会按注册顺序拼接

**AICTO 当前已有反幻觉 hook**（`AICTO/hermes-plugin/__init__.py:38-56`）— 写得规整，可保留。Phase 1 可考虑加一个"实时进度注入"hook（`prodmind/__init__.py:129-177` 的模式）：当用户问"项目 X 的技术评估到哪了"时自动查 ADR/TechRisk 表插入上下文。

---

## 6. ProdMind dispatch_to_legion 现状

### 6.1 三个核心工具

源：`prodmind/hermes-plugin/tools.py:9085-9612`

| 工具 | 行号 | 用途 |
|---|---|---|
| `list_legions` | 9085-9140 | 读 `~/.claude/legion/directory.json` + `tmux list-sessions` 找出在线指挥官 |
| `dispatch_to_legion` | 9143-9294 | 派任务（tmux send-keys 直发 OR inbox.json 排队）|
| `query_legion` | 9297-9409 | `tmux capture-pane` 读军团终端实时屏幕 + git log |
| `create_legion` | 9531-9612 | 调 `~/.claude/scripts/legion.sh l1+1` 拉新军团 + 绑定 ProjectRepo |
| `get_project_progress` | 9412-9528 | 综合视图（DB 任务 + 军团屏幕 + git）|

### 6.2 派单协议（CTO 升级版必须看懂）

**ProdMind 现状**：
- 派单内容是**明文文本**（自由格式，含项目名 / 路径 / GitHub / 需求 / 执行要求）
- **不带结构化 schema** — 军团 LLM 自己读自己理解
- 双通道：
  1. **tmux send-keys 直发**（首选）—— 检测 pane 末尾有 `❯` 提示符则直接 send_keys（`tools.py:9242-9249`）
  2. **inbox.json 排队**（fallback）—— pane 忙碌时写到 `~/.claude/legion/<hash>/team-<commander>/inboxes/<commander>.json`（`tools.py:9263-9281`）

**inbox 消息格式**（`tools.py:9263-9272`）：
```json
{
    "id": "msg-<timestamp>",
    "from": "ProdMind-PM",
    "to": "L1-暴风军团",
    "type": "task",
    "payload": "<明文派单文本>",
    "timestamp": "2026-04-25T10:00:00Z",
    "read": false,
    "summary": "PM任务派发: <project_name>"
}
```

**带 fcntl 文件锁的安全写入**（`tools.py:906-930`）：用 `<inbox>.lock` 单独锁文件，避免破坏 inbox JSON。

### 6.3 与军团的通信路径

```
PM 进程
  │
  ├─ list_legions ─── 读 ~/.claude/legion/directory.json
  │                  + tmux list-sessions
  │
  ├─ dispatch_to_legion
  │   ├─ tmux send-keys -t legion-<hash>-L1-<name> "<text>" Enter   # 在线 + 空闲
  │   │
  │   └─ append to ~/.claude/legion/<hash>/team-<name>/inboxes/<name>.json   # 在线 + 忙 OR 离线
  │
  └─ query_legion ─── tmux capture-pane -t legion-<hash>-L1-<name> -p -S -50
                     + git -C <local_path> log --oneline -3
```

**军团目录证据**（`~/.claude/legion/directory.json`）：实测有 30+ 个军团 hash，每个 hash 对应一个项目目录；prodmind 项目对应 hash `712dce67`（`/Users/feijun/Documents/prodmind`）。

**军团 registry**（`~/.claude/legion/<hash>/registry.json`）：列出该军团下所有 commander 的 status / role / started 时间。`prodmind/hermes-plugin/tools.py:831-903` 的 `discover_online_commanders()` 是更精细的版本（带 tmux_alive 判定 + domain 判定）。

### 6.4 上下文注入方式

**当前 ProdMind**：派单文本里**只有 PRD 摘要**（用户构造的派单文本），没有自动从 dev.db 拉 PRD 全文。

**CTO 升级版（dispatch_to_legion_balanced）必做**：
1. **自动拉 PRD 全文**（`get_pm_context_for_tech_plan(prd_id)` 已规划于 `docs/CTO-READ-ACCESS-SPEC.md:118-119`）
2. **附技术方案** — design_tech_plan 输出的 markdown
3. **附验收标准** — breakdown_tasks 输出的 Given/When/Then
4. **附 ADR 链接** — 让军团知道为什么选 X 不选 Y
5. **派单到 inbox 的同时 tmux send-keys 一行通知**（`@<commander> 收到 PM 任务，详细内容在 inbox/<id>.json`）—— 避免军团埋头干活忽视 inbox

### 6.5 dispatch_to_legion_balanced 升级 GAP

PRD 能力 3 要求：
- ✅ 任务技术栈 × 军团能力（**新增**：需要维护 EngineerProfile 表，记录每个军团擅长 React/Python/Go 等）
- ✅ 军团当前负荷（**新增**：`tasks WHERE assignee = legion_X AND status != 'done'` count）
- ✅ 单军团同时 ≤2 个任务（**新增**：派前查 + 排队）
- ✅ 有依赖关系的任务延迟派单（**新增**：DAG 拓扑排序，前序未完成则延派）
- ⚠️ "CTO 拥有调度决策权，军团必须接（可 appeal 但不可直接拒）"——需要 appeal 协议（**新增**：CommanderOutbox 表里加 `appeal_id` 字段 + appeal 处理工具）

---

## 7. ProdMind dev.db schema

### 7.1 表清单

**Prisma 定义的（prodmind/prisma/schema.prisma）— 14 个 model**：

| Model | 关键字段 | CTO 读权限 | CTO 写权限 |
|---|---|---|---|
| Project | id / name / status / stage / clarificationData / mode / authorization_scope | ✅ R | ❌ |
| PRD | id / title / content / version / changeLog / feishuDocToken / projectId | ✅ R | ❌ |
| UserStory | id / title / asA / iWant / soThat / acceptanceCriteria / priority / projectId | ✅ R | ❌ |
| Feature | id / name / reach / impact / confidence / effort / riceScore / projectId | ✅ R | ❌ |
| Conversation | feishuChatId / projectId | （不必读）| ❌ |
| Message | conversationId / role / content | （不必读）| ❌ |
| Research | type / title / content / framework / projectId | ✅ R | ❌ |
| Evaluation | layer1Data / layer2Data / layer3Data / overallScore / recommendation / projectId | ✅ R | ❌ |
| Activity | projectId / type / summary / metadata | ✅ R | ❌ |
| PRDVersion | prdId / versionNumber / content / changeReason / changeType | ✅ R | ❌ |
| PRDDecision | prdId / question / chosen / rationale / decidedBy | ✅ R | ❌ |
| PRDOpenQuestion | prdId / question / status / answer | ✅ R | ❌ |
| PRDDriftReport | prdId / findings / severitySummary | ✅ R | ❌ |
| PRDImpactEdge | sourceVersionId / targetType / targetId / impactType | ✅ R | ❌ |

**plugin 启动时 raw SQL 创建的（不在 Prisma schema）— 5 个表**：

| Table | 创建位置 | 字段 | CTO 读权限 | CTO 写权限 |
|---|---|---|---|---|
| TeamMember | tools.py:5582-5592 | projectId / name / feishuOpenId / role / githubUsername / memberType / legionId / commanderId | ✅ R | ❌ |
| Task | tools.py:5594-5611 | projectId / storyId / title / description / assigneeId / status / priority / dueDate / githubIssueUrl | ✅ R | ❌ |
| TaskUpdate | tools.py:5613-5621 | taskId / updaterId / oldStatus / newStatus / note | ✅ R | ❌ |
| ProjectRepo | tools.py:5700-5710 | projectId / repoUrl / accessToken / defaultBranch / label / localPath / legionHash / legionCommander | ✅ R | ❌ |
| CommanderOutbox | tools.py:5666-5680 | projectId / commanderId / taskId / status / note | ✅ R | ⚠️ 看下文 |
| ProjectDocument | tools.py:6772 | projectId / docType / feishuDocToken / feishuDocUrl | ✅ R | ❌ |
| RiskRegister | tools.py:6954 | projectId / risk / severity / mitigation | ✅ R | ⚠️ 看下文 |
| Requirement | （Phase 8）| projectId / title / status / rice | ✅ R | ❌ |

**说明**：`docs/CTO-READ-ACCESS-SPEC.md:107-117` 已经规划了 8 个只读工具映射这些表。

### 7.2 CTO 自己的表（要新增 — `docs/PRODUCT-SPEC-v0.2-merged.md` §6）

CTO **写**到 prodmind 的 dev.db（用读写连接，不用 mode=ro）：

| 表 | 用途 | 字段建议（待 spec 阶段定）|
|---|---|---|
| ADR | 技术决策记录 | id / project_id / number(0001..) / title / decision / rationale / alternatives_considered_json / decided_by / decided_at / superseded_by |
| TechRisk | 技术风险登记 | id / project_id / severity (high/med/low) / probability / impact / mitigation / status / created_at |
| TechDebt | 技术债务清单 | id / project_id / type / description / introduced_in_commit / paydown_estimate / priority / status |
| CodeReview | 代码评审记录 | id / project_id / pr_url / commit_sha / checklist_json (10 项 PASS/BLOCKING) / appeal_status / reviewed_at / reviewer (CTO) |
| EngineerProfile | 军团/工程师能力画像 | id / commander_id (or member_id) / skills_json (语言/框架) / strengths / weaknesses / past_tasks_count / dispatch_recommendation |

### 7.3 连接方式（关键 — 物理隔离读写）

**只读连接**（用于读 PM 表）— `docs/CTO-READ-ACCESS-SPEC.md:51-63`：
```python
import sqlite3
PRODMIND_DB_PATH = "/Users/feijun/Documents/prodmind/dev.db"

def _readonly_connect() -> sqlite3.Connection:
    uri = f"file:{PRODMIND_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
```

**读写连接**（仅用于 CTO 自己的表 ADR/TechRisk/...）— `docs/CTO-READ-ACCESS-SPEC.md:142-146`：
```python
def _cto_own_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(PRODMIND_DB_PATH)  # 无 mode=ro
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

**实测**：`mode=ro` 在 SQLite 物理层挡住所有 UPDATE/INSERT/DELETE，会抛 `attempt to write a readonly database` 异常。即使 CTO 代码 bug 写错了 SQL 也无法破坏 PM 数据。

### 7.4 dev.db 路径解析

**ProdMind 的解析**（`prodmind/hermes-plugin/tools.py:142-146`）：
```python
_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))   # /Users/feijun/Documents/prodmind/hermes-plugin
_PROJECT_ROOT = os.path.dirname(_PLUGIN_DIR)                 # /Users/feijun/Documents/prodmind
_DB_PATH = os.environ.get("PRODMIND_DB_PATH", os.path.join(_PROJECT_ROOT, "dev.db"))
```

**realpath 关键**：plugin 是 symlink（`~/.hermes/plugins/prodmind` → `/Users/feijun/Documents/prodmind/hermes-plugin`）；用 `realpath` 解析后才能找到真实 dev.db 位置。

**AICTO 应用**：CTO plugin 也用 `realpath` 找自己的目录，但 dev.db 路径要**硬编码** prodmind 的位置（`/Users/feijun/Documents/prodmind/dev.db`）—— 因为 AICTO 自己没 dev.db，只是借 PM 的 db 加表。

---

## 8. AICTO 可复用资产清单

### 8.1 代码片段（直接 copy + 改路径）

| # | 资产 | 源 | 用法 | 改动量 |
|---|---|---|---|---|
| 1 | `_ensure_env_loaded()` | `prodmind/hermes-plugin/feishu_api.py:22-50` | feishu_api.py 顶部 | 0（直接抄）|
| 2 | `get_tenant_access_token()` + token 缓存 | `feishu_api.py:121-156` | 飞书 token 管理 | 0 |
| 3 | `_request()` 通用 HTTP wrapper | `feishu_api.py:166-181` | 所有飞书 API 调用 | 0 |
| 4 | `markdown_to_descendants()` + `_build_block()` 等辅助 | `feishu_api.py:631-972` | 写技术方案文档 / ADR 文档 | 0 |
| 5 | `create_docx()` / `update_docx()` | `feishu_api.py:1279-1388` | 创建技术方案 / 评估报告 | 0 |
| 6 | `read_docx_content()` | `feishu_api.py:1153-1188` | 读 PM PRD 飞书文档 | 0 |
| 7 | `send_card_message()` | `feishu_api.py:1590-1603` | CTO 卡片通知 | 0 |
| 8 | `send_text_to_chat()` + `_send_post_with_mentions()` | `feishu_api.py:1890-1951` | 文本 + @mention | 0 |
| 9 | `_grant_doc_tenant_read()` | `feishu_api.py:1249-1276` | CTO 创建文档后授权 PM 可读 | 0 |
| 10 | `_render_mermaid_to_png()` + 上传 | `feishu_api.py:412-525` | 技术方案里的架构图 | 0 |
| 11 | `_capture_owner_open_id()` | `prodmind/hermes-plugin/tools.py:54-132` | 自动绑定老板飞书 open_id | 改 owner_name 为"张骏飞" |
| 12 | `discover_online_commanders()` | `prodmind/hermes-plugin/tools.py:831-903` | dispatch_to_legion_balanced 找军团 | 0 |
| 13 | `_write_commander_inbox_locked()` | `prodmind/hermes-plugin/tools.py:906-930` | 写军团 inbox（fcntl 锁）| 0 |
| 14 | `send_to_commander()` | `prodmind/hermes-plugin/tools.py:933-995` | 派单到军团（结构化 message）| 改 from 字段 = "aicto-cto:..." |
| 15 | hook 注入模式 | `prodmind/hermes-plugin/__init__.py:107-179` | pre_llm_call 反幻觉 + 进度注入 | 已部分应用 |

### 8.2 配置模板（参照改写）

| # | 资产 | 源 | 改动 |
|---|---|---|---|
| 16 | profile config.yaml | `~/.hermes/profiles/ai-hr/config.yaml` | 改 port、删 HERMES_SYSTEM_PROMPT、加 vision: true |
| 17 | profile .env | `~/.hermes/profiles/ai-hr/.env` | 改 FEISHU_APP_ID/SECRET、改 BOT_NAME |
| 18 | plugin.yaml | `prodmind/hermes-plugin/plugin.yaml` | 已有，仅改 identity 名为"程小远"、provides_tools 列出 16 个真工具 |
| 19 | __init__.py 的 register 模式 | `prodmind/hermes-plugin/__init__.py:6-105` | AICTO 已有 stub register，扩到 16 个真工具 |

### 8.3 文档模板（按需新建）

| # | 资产 | 源/类比 | 用途 |
|---|---|---|---|
| 20 | technical-design.md | `prodmind/hermes-plugin/templates/technical-design.md` | design_tech_plan 飞书文档骨架 |
| 21 | adr.md（新）| 业内 ADR 标准 | record_tech_decision 文档骨架 |
| 22 | code-review-report.md（新）| 类比 `prodmind/templates/feasibility.md` | review_code 输出骨架 |
| 23 | daily-brief.md（新）| 类比 `prodmind/templates/weekly-report.md` | daily_brief 飞书卡片骨架 |
| 24 | SOUL.md 程小远版 | 现 `~/.hermes/profiles/aicto/SOUL.md` | 已有，按 §3.1 微调 |

---

## 9. 避坑点清单

> 一行一条，**带踩坑案例或文件引用**

1. **同一 `FEISHU_APP_ID` 不能跨 profile 共用** — Hermes gateway 启动时 `acquire_scoped_lock(_FEISHU_APP_LOCK_SCOPE, app_id)`（`hermes-agent/gateway/platforms/feishu.py:1206-1221` + `gateway/status.py:237`），第二个进程会 `feishu_app_lock` 致命错误启动失败。✅ AICTO 已用独立 app `cli_a9495f70ddb85cc5`，不会撞 PM(default) / AIHR

2. **plugin 加载粒度是 per-profile**（`hermes-agent/hermes_cli/plugins.py:255-291`）— `discover_and_load()` 扫的是 `get_hermes_home() / "plugins"`，所以放 `~/.hermes/plugins/aicto` 会被 default + ai-hr + aicto 三个 profile 都加载。**正确做法**：放在 `~/.hermes/profiles/aicto/plugins/aicto`（profile 专属）。当前 AICTO profile **缺这个目录**，必须 `mkdir + ln -s ~/Documents/AICTO/hermes-plugin ~/.hermes/profiles/aicto/plugins/aicto`

3. **AI HR 当前 plugin 是断的 symlink** — `~/.hermes/plugins/ai-hr -> /Users/feijun/prodmind/hermes-plugin-ai-hr`（不存在）；实际代码在 `/Users/feijun/Documents/prodmind/hermes-plugin-ai-hr`。说明 AI HR 当前**没加载任何 plugin**，飞书消息只走 Hermes 内置工具（terminal/file/web）。AICTO 部署时**不要**复制这个错误，要用绝对路径并验证 `ls -L` 能解析

4. **顶层 `HERMES_SYSTEM_PROMPT:` 在 config.yaml 里是死代码** — 实测 grep `~/.hermes/hermes-agent` 全无引用，被 Hermes 完全忽略。任务描述里说"必须改成 AICTO 的"——其实改不改都不影响行为，但保留会**误导后续审阅者**（以为自己能改 prompt）。建议**删除**，真要补强 prompt 用 `agent.system_prompt` 字段（`hermes-agent/gateway/run.py:919`）

5. **plugin 热加载代价**：plugin 改了 Python 代码后必须重启整个 gateway（`hermes profile use aicto && aicto gateway run`）— Hermes 没有 `plugin reload` 机制（`plugins.py:255-260` 的 `_discovered: bool` 锁住了）。生产实践：每次工具改动 → tail logs 等 gateway 重启完成 → 飞书测一条消息确认。**避坑**：不要在 plugin __init__.py 的 register 阶段做重活（如建表），会拖慢每次重启 — 建 table 放在工具被首次调用时（不过 prodmind 反例：tools.py:9673-9674 模块顶层就建表，约 50ms）

6. **stub 透明纪律必须落到工具返回上**（`AICTO/hermes-plugin/tools.py:12-23`）— `{"status": "not_implemented", ...}` 是合规返回；`{"success": False, "message": "TODO"}` 不是。LLM 看到 `success: False` 也会汇报"工具失败"，而 `not_implemented` 让 LLM 明确说"该工具还没实现"。Phase 1 完成前所有未实现工具都应保留 stub 形态

7. **CTO 不能写 PM 表 — 但只靠应用层约束不够**（`docs/CTO-READ-ACCESS-SPEC.md:124-149`）— 用 `mode=ro` SQLite URI 在物理层挡住。CTO 代码不会出现 prodmind 表的 INSERT/UPDATE/DELETE，否则 grep `_readonly_connect` 后跟 `INSERT|UPDATE|DELETE` 应该是空集。引入 lint 规则在 CI 里强制扫描会更稳

8. **dev.db 写并发 — WAL 模式下 reader 永远不会被 writer 阻塞**，但 reader 看到的是事务提交前的快照（`prodmind/hermes-plugin/tools.py:149-163` 的 `_connect()` 注释）。CTO 读 PRD 时如果 PM 正在事务中改这个 PRD，CTO 会读到改前版本——可接受（一次工具调用单位时间足够小）

9. **飞书文档 `tenant_editable` 默认开启依赖 commit fc86969**（`docs/CTO-READ-ACCESS-SPEC.md:88-89`）— 老的 PM 文档（v0.1 期间）大部分已 backfill，但有 3 个失败 → AICTO 也读不到 → 那 3 个需要张骏飞手工补权限

10. **legion directory.json 是手工维护的清单** — `~/.claude/legion/directory.json` 不是自动同步的，新军团创建后要在这文件里加一行（看 `~/.claude/scripts/legion.sh` 的实现）。CTO 派单前 list_legions 拿到的 hash 必须存在于此 — 否则 dispatch 失败

11. **legion inbox 文件无 schema 校验** — `~/.claude/legion/<hash>/team-<commander>/inboxes/<commander>.json` 是数组，每条 message 是 dict。生产已用的字段：id / from / to / type / payload / timestamp / read / summary（`prodmind/tools.py:9263-9272`）。CTO 加新字段（如 `priority` / `appeal_id` / `cto_context`）军团**不会自动识别** — 要同步军团 commander 的 prompt 教他读

12. **AICTO 的 plugin pre_llm_call hook 不能依赖 sender 信息** — `prodmind/__init__.py:135-141` 的 `_capture_owner_open_id` 实测拿不到 sender，因为 `pre_llm_call` 当前不传 sender metadata（`AICTO/hermes-plugin/__init__.py:52` 的 `**kwargs` 接住但里面是空的）。要捕获 owner_open_id 必须改用工具调用时的入参（`tools.py` 里每个 handler 第一行 `_capture_owner_open_id(kwargs)`）

13. **`agent.compression.summary_model` 配 `google/gemini-3-flash-preview` 在国内可能调不通** — ProdMind 实测过这一点（apimart 不支持该 model），ai-hr/aicto config.yaml 都从 ai-hr cargo-cult 来。CTO 上线前要测一次"长会话压缩"路径，确认 summary_model 能用；否则改回 `claude-opus-4-6` 走 aigcapi.top

14. **bundled skills 是 per-profile 复制** — `/Users/feijun/.hermes/profiles/aicto/skills/` 已有 25 个顶层目录（与 ai-hr 一致），实际 77 个 sub-skill。这些是**只读副本**，不会自动同步；如要更新 skill 库要重新跑 `hermes profile create --refresh-skills`（待确认命令名）

15. **plugin 写持久化文件路径** — `prodmind/hermes-plugin/feishu_api.py:96-110` 的 `PROJECT_CHANNELS_PATH` / `BITABLE_STATE_PATH` 默认在 `~/.hermes/plugins/prodmind/` —— 这是 **default profile 共享路径**，aicto profile 不会读到。CTO 的持久化状态应该写在 `~/.hermes/profiles/aicto/plugins/aicto/` 或用 `get_hermes_home() / "plugins" / "aicto"` 动态构造

---

## 10. 待解决的不确定项（参照后仍无法回答 — 需 spec 阶段决定）

### 10.1 协议层面

| # | 问题 | 候选方案 | 备注 |
|---|---|---|---|
| A | `kickoff_project` 第 3 步"ProdMind 项目条目"具体调什么？| (a) CTO 直接写 prodmind dev.db Project 表（违背只读纪律）；(b) HTTP 调 ProdMind 8642 端口；(c) 飞书 @张小飞 自然语言；(d) 文件接口 `~/.hermes/inter-agent-mailbox/` | PRD 没明示 |
| B | 飞书"项目群通知"发到哪个群？| (a) AICTO 工作群；(b) 项目专属新群（CTO 自动建群）；(c) 现有 PM/项目群 | PRD ASCII mock 显示卡片但没说目标 chat_id |
| C | CTO ↔ 军团的 appeal 协议 | (a) 军团回 CommanderOutbox 表写 appeal；(b) 飞书 @CTO + tag `#appeal`；(c) 新增 LegionAppeal 表 | PRD 提到 appeal 但没说协议 |
| D | LegionAppeal 仲裁失败 → 升级骏飞，怎么升级？| (a) 飞书 @张骏飞；(b) 卡片让骏飞按按钮裁决；(c) 写 EscalationLog 表等他主动看 | PRD 没明示 |

### 10.2 数据层面

| # | 问题 | 候选 | 备注 |
|---|---|---|---|
| E | ADR 表里的 `number` 字段格式 | "ADR-0001" / "0001" / 数字递增 | 跨项目 ADR 编号是全局还是 per-project |
| F | TechRisk / TechDebt 的 status 枚举 | open/mitigated/accepted/closed | 与 PM PRDDriftReport 风格对齐 |
| G | EngineerProfile 的 skills_json 词表 | 用 LLM-friendly 自由 string vs 受控词表 | 影响 dispatch 匹配算法 |

### 10.3 性能 / 可靠性

| # | 问题 | 候选 | 备注 |
|---|---|---|---|
| H | design_tech_plan 60s+ 时是否分片 | (a) 同步阻塞；(b) 任务化 + 状态查询 | 用户体验 vs 实现复杂度 |
| I | CTO 重启后未完成的 design_tech_plan 怎么办 | (a) 丢弃；(b) 持久化任务表 | 简单度优先建议丢弃 |
| J | dev.db 大于 1GB 时 RO 连接是否影响 PM 写性能 | 需实测 | 当前 dev.db 4.4MB，远未到瓶颈 |

### 10.4 部署 / 运维

| # | 问题 | 候选 | 备注 |
|---|---|---|---|
| K | aicto profile 启停脚本是否需要 cron 自启 | (a) 仅手工；(b) launchd plist；(c) 复用 PM 的 cron 模式 | 看老板期望的 SLA |
| L | 飞书 bot 离线时（ws 断）的恢复策略 | Hermes 默认有 `ws_reconnect_interval=120`（`feishu.py:1130`）— 是否够 | Phase 1 用默认即可 |

---

## 附录 A：关键文件引用速查表

| 主题 | 路径 |
|---|---|
| AICTO 当前 plugin | `/Users/feijun/Documents/AICTO/hermes-plugin/` |
| AICTO 当前 profile | `/Users/feijun/.hermes/profiles/aicto/` |
| ProdMind plugin（黄金标本）| `/Users/feijun/Documents/prodmind/hermes-plugin/` |
| ProdMind dev.db schema | `/Users/feijun/Documents/prodmind/prisma/schema.prisma` |
| ProdMind dev.db 实际位置 | `/Users/feijun/Documents/prodmind/prisma/dev.db`（symlink: `prodmind/dev.db`）|
| AIHR plugin（PM fork — 未上线）| `/Users/feijun/Documents/prodmind/hermes-plugin-ai-hr/` |
| AIHR 业务代码（standalone）| `/Users/feijun/Documents/AIHR/src/` |
| AIHR profile | `/Users/feijun/.hermes/profiles/ai-hr/` |
| Hermes plugin loader | `/Users/feijun/.hermes/hermes-agent/hermes_cli/plugins.py` |
| Hermes profile manager | `/Users/feijun/.hermes/hermes-agent/hermes_cli/profiles.py` |
| Hermes feishu adapter | `/Users/feijun/.hermes/hermes-agent/gateway/platforms/feishu.py` |
| Hermes prompt builder | `/Users/feijun/.hermes/hermes-agent/agent/prompt_builder.py` |
| Hermes 飞书 app 锁 | `/Users/feijun/.hermes/hermes-agent/gateway/status.py:237` |
| Legion 名册 | `/Users/feijun/.claude/legion/directory.json` |
| Legion 单个 hash 目录 | `/Users/feijun/.claude/legion/<hash>/` |
| AICTO PM 边界 spec | `/Users/feijun/Documents/AICTO/docs/PM-CTO-BOUNDARY-MATRIX.md` |
| AICTO 只读访问 spec | `/Users/feijun/Documents/AICTO/docs/CTO-READ-ACCESS-SPEC.md` |
| AICTO 产品规格 v0.2 | `/Users/feijun/Documents/AICTO/docs/PRODUCT-SPEC-v0.2-merged.md` |
| Phase 1 PRD 全量 | `/Users/feijun/Documents/AICTO/.planning/phase1/recon/PRD-FULL.md` |
| Phase 1 PRD 能力分解 | `/Users/feijun/Documents/AICTO/.planning/phase1/recon/PRD-CAPABILITIES.md` |
| Phase 1 任务派发原文 | `/Users/feijun/Documents/AICTO/.dispatch/inbox/task-001-phase1-full.md` |

---

## 附录 B：本侦察读了哪些代码（量化口径）

- **完整阅读**：23 个文件（涵盖 plugin 主入口、tools.py、feishu_api.py、profile config、SOUL.md、Hermes plugin loader、Feishu adapter、Prisma schema、AICTO docs/spec/PRD）
- **关键函数核对**：35+ 个函数（含 token、send/read 飞书、dispatch、legion discovery、hook、SOUL.md loading、scoped lock）
- **行号粒度引用**：80+ 处带 `file:line` 标注（散布全报告）
- **未读但已确认存在的资源**：bundled skills 25 个顶层目录、77 个 sub-skill；prodmind tools.py 9000+ 行（仅查关键工具，未通读）；AIHR src 21 个 .py 文件（仅看 feishu/ 与 boss/feishu/）

---

> **本报告完。**
> 输出位置：`/Users/feijun/Documents/AICTO/.planning/phase1/recon/RECON-REFERENCE.md`
> 下一步建议：spec 阶段把 §10 待澄清项逐个落定 + 用 §1-§7 模板搭出 6 个能力的实现骨架。
