# Legion-0 — Claude Code 军团制协同作战体系

在 [Claude Code](https://claude.com/claude-code) 之上实现**多指挥官 + 多 agent 并行作战**的编排层。所有 teammate 在 tmux 独立 window 运行，用户全程可见、可介入、可审批。

> **定位**：不是替代 Claude Code，是给它加一层"军团制工作流"——把一次性聊天升级为有指挥、有分工、有审计的并行作战。

## 核心能力

- **指挥官制** — L1 指挥官调度多个 teammate（参谋 / 实现 / 审查 / 验证）
- **tmux 可视化** — 所有 teammate 在独立 window 运行，禁用不可见的后台 agent
- **邮箱通信** — 指挥官间通过 JSON inbox + 文件锁协同，支持联合指挥
- **战役编排** — 一条 JSON 计划批量部署跨域并行任务（campaign）
- **战法库** — 跨项目沉淀教训，`memory/tactics/INDEX.md` 索引可搜
- **Skill / Agent 体系** — 按复杂度分级（S/M/L/XL）自动选规模
- **规模优先** — 不以 token / 时间 / 进程数成本为降级理由，默认最大化有效军团协作规模
- **自洽模式** — 自治循环 + 指挥官自主权第一原则，少打扰用户

## 核心原则

Legion 的默认作战原则是：**不计资源消耗成本，通过最大化有效军团规模协作，实现效率和质量的最大化提升。**

这意味着 L1 不需要询问“要不要组团 / 要不要侦察 / 要不要审查 / 要不要扩编”。默认前台结构保持稳定的 Claude/Codex 双 L1：S 级任务由接收任务的 L1 自己处理；M 级及以上才用 `--corps` 组织专业 L2，并行推进侦察、实现、审查、验证、审计、产品、UI 等分支。成本不是降级理由；只有不可逆破坏、需求歧义、跨项目共享状态、高返工风险这四类例外需要停下请示。

“最大化规模”不是盲目重复。同一批军团必须覆盖不同文件范围、不同风险假设、不同验证方式或不同专业分支，形成互补吞吐和独立质量门。

## 快速开始

### 最懒一行部署（推荐新电脑用）

```bash
curl -fsSL https://raw.githubusercontent.com/ziyerr/legion-0/master/bootstrap.sh | bash
```

自动 clone + install + 依赖检查 + 打印下一步。不装 OS 级依赖（不改系统配置、不需 sudo），依赖缺失时打印安装命令让你手动执行。重复执行 = 升级到最新。

### 手动安装（看得清每一步）

```bash
# 方式 A：直接 clone 到 ~/.claude/（推荐，首次安装）
git clone https://github.com/ziyerr/legion-0 ~/.claude
cd ~/.claude && ./install.sh

# 方式 B：clone 到别处，symlink 连回 ~/.claude/
git clone https://github.com/ziyerr/legion-0 ~/code/legion
cd ~/code/legion && ./install.sh   # 自动建 symlink
```

### 自定义安装路径

```bash
CLAUDE_HOME=~/my-legion curl -fsSL .../bootstrap.sh | bash
# 或手动
CLAUDE_HOME=~/my-legion git clone ... ~/my-legion && ~/my-legion/install.sh
```

### 依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `claude` | **≥ 2.1.118** | Claude Code CLI（低于此版本有授权弹窗崩溃 bug） |
| `tmux`   | ≥ 3.0 | teammate 可视化 |
| `jq`     | — | JSON 处理（邮箱 / 注册表） |
| `python3`| ≥ 3.9 | `legion-commander.py` 等脚本 |
| `node`   | — | npm 安装 Claude CLI 必需 |
| `git`    | — | 模板同步 + auto-push |

macOS：`brew install tmux jq python3 node git && npm i -g @anthropic-ai/claude-code`

### 首次启动

```bash
claude                              # 进入 Claude Code，自动加载全局 agents/skills
# 或
~/.claude/scripts/legion 0           # 配置 legion 裸命令，并在当前项目展开军团体系初始化
legion h                             # 初始化后启动 Claude/Codex 双 L1，并进入分屏
# 或
~/.claude/scripts/legion.sh l1 磐石  # 显式启动 L1-磐石军团（新 tmux session）
```

## 常用命令

| 命令 | 用途 |
|------|------|
| `legion 0` | 配置/更新全局 `legion` 入口，并初始化当前项目军团体系 |
| `legion h` | 自动补齐配置和项目初始化，当前窗口进入 Claude L1，Codex L1 在后台独立 session 启动；默认不创建基础 L2 |
| `legion.sh l1 <名>` | 启动 / 恢复 L1 指挥官（新 tmux session） |
| `legion.sh l1+1 <名>` | 强制创建全新军团 |
| `legion codex l1 [名]` | 通过短命令启动 Codex L1 指挥官；不写名则载入在线军团，没有在线军团才新增 |
| `legion claude h` | 推荐启动项目军团：当前窗口 Claude L1，后台 Codex L1，双方 peer-sync |
| `legion.sh claude l1 <名>` | 显式启动 / 恢复 Claude L1 指挥官 |
| `legion.sh codex l1 <名>` | 显式启动 / 恢复 Codex L1 指挥官 |
| `codex l1 <名>` | 通过 Codex shim 启动 / 恢复 Codex L1 指挥官 |
| `legion.sh dou` | 新增一个 Terminal 窗口跑 Codex L1，当前窗口切换为 Claude L1 |
| `legion.sh duo` | 打开两个独立 Terminal 窗口，分别启动 Codex L1 和 Claude L1 |
| `legion.sh duo --terminal vscode` | 在当前 VS Code 集成终端里启动 tmux 双 L1 作战面 |
| `legion.sh status` | 所有 team 状态（按指挥官分组） |
| `legion.sh sitrep` | 综合态势（status + board + locks + inbox） |
| `legion.sh inbox [ID]` | 查看汇报 |
| `legion.sh msg <TEAM_ID> "内容"` | 下达指令 |
| `legion.sh gate <TEAM_ID> block/approve` | 审批门控制 |
| `legion.sh campaign '<JSON>'` | 部署战役（批量 team） |
| `legion.sh joint "<战略目标>"` | 启动联合指挥 |
| `legion.sh war-room` | 进入作战室（多军团分屏视图） |
| `legion.sh watch` | 实时活动流（tail 所有通信） |
| `legion.sh auto bg "需求"` | 一键后台自治循环（去睡觉模式） |
| `legion host` | 等价于默认 Claude host 启动：当前窗口 Claude L1，Codex L1 后台独立 session |
| `legion aicto` | 查看外部 Hermes AICTO profile 状态和启动指引；不创建本地 L0 commander |
| `legion view` | 显式打开分屏操作视图；不会由 `legion h` / `legion claude h` 自动创建 |
| `legion.sh mixed campaign plan.json` | 统一 Legion Core 混编调度；在 L1 内自动识别当前 L1，S 默认留在 L1，M/L/XL 路由到 L2 |
| `legion.sh mixed campaign plan.json --corps` | 强制军团级专业分支调度（自动创建 L2 兵种指挥官） |
| `legion mixed aicto-reports` | 查看写给外部 Hermes AICTO 的 durable report 队列 |
| `legion mixed report-aicto <subject> "summary" --from L1-xxx --kind problem` | L1 主动向外部 AICTO 汇报非任务类问题 |
| `legion mixed readiness L1-xxx --wait` | L1 按当前 readiness `order_id` / nonce / freshness 边界等待直属 L2 完成启动自检 |
| `python3 .claude/skills/claw-roundtable-skill/roundtable_health.py` | 检查圆桌会议 skill 的文件、专家库、需求分析和 OpenClaw runtime |

## Codex 混编调度

`mixed` 子命令提供统一 Legion Core：同一个 registry / taskboard / event log 下，按任务角色选择 Claude 或 Codex worker，并把每个 worker 放进 tmux window 中可视化运行。

### 混编运行时契约

混编运行时只有一套权威状态面：

- `mixed-registry.json` 负责 commander / task / dependency / lifecycle / scope ownership / readiness order。
- `inbox/*.jsonl` 负责可持久化消息负载；tmux 只负责可见通知，不是事实来源。
- `events.jsonl` 负责审计轨迹；registry / inbox / events 的写入必须走文件锁，不能并发裸写。
- `runs/<task>/result.md` 负责 worker 交付结果；没有结构化 result 的退出码 0 不是完成证据。
- tmux session/window 负责实时可见性；状态命令只能读取，修复漂移必须走显式 `reconcile` / `repair`。

AICTO 是独立 Hermes 项目 `/Users/feijun/Documents/AICTO`，是项目开发军团的最高技术指挥官；Legion Core 不是 AICTO 本体，只是 Claude/Codex 军团运行时底座。Claude L1 与 Codex L1 各自管理本 provider 的 team tree，并通过 durable inbox/events/results 接收外部 AICTO 的指令、向 AICTO 汇报。双 L1 启动后 Legion Core 会延迟 1 秒互发 `peer-sync`，确认双方协作关系。AICTO 下发的 S 级任务默认由接收任务的 L1 自己完成；M 级及以上才通过 `--corps` 进入专业 L2。L2 可以直接带本专业 worker；跨专业或多切片继续使用 `--corps`。

L1 上线或恢复时会主动向同项目其他在线 L1 写入 `peer-online` inbox 消息，并向外部 AICTO 写入 `aicto-reports.jsonl`。任务进入 `completed` / `failed` / `blocked` 等终态时，Legion Core 自动追加 AICTO report；L1 遇到非任务类问题时用 `legion mixed report-aicto ...` 手动追加。这个 report 队列是外部 Hermes AICTO/plugin 的 durable outbox，不会创建本地 Legion L0。

消息顺序是 inbox-before-tmux：`mixed msg` / `mixed broadcast` 先写 durable inbox，再尝试 tmux 通知；tmux 失败只记录 `delivered_tmux=false`，不能抹掉 inbox。发给 L1/L2 指挥官的 tmux 通知使用非侵入 `display-message`，不把长消息塞进提示符。

readiness 是当前订单协议，不是全历史 free-text 扫描。默认 dual-L1 启动没有基础 L2，也不会下发 L2 readiness-order；常规 M+ 扩编通过 `TASK-ASSIGNED` 激活 L2，只有显式 legacy base-L2 或 L1 明确发起 readiness-order 时才写入直属 L2 roster。回报必须来自注册的直属活跃 child，且回显当前 `order_id` / nonce，并晚于 freshness 边界。任意 `--sender` 字符串、错误父级、非直属 child、失活/无 tmux 的 child、历史 `READY:init-complete` 都不能满足当前订单。

`mixed status` / `mixed inbox` / `mixed readiness` / `legion view` 是读路径，不得初始化或修改 registry/events。需要把缺失 tmux window、死亡 session、阻塞依赖改写到 registry 时，使用显式 `mixed reconcile`；替换失败任务并释放下游时，使用显式 `mixed repair <failed-task> --replacement <replacement-task>`，并保留原失败任务的单调终态。

交付型任务必须声明非空 `scope`，scope 必须是项目相对路径，禁止绝对路径、空路径和 `..` 越界。Legion Core 会在 registry lock 内规范化 scope，并阻止活动交付任务之间的文件/目录重叠；任务进入 `completed` / `failed` / `blocked` 终态后释放占用。复杂或跨 provider 的战役先跑 `--dry-run`，dry-run 只能预览，不得写 registry、events 或 run 目录。

worker 完成结果必须是整个 `result.md` 的严格 JSON 对象，字段固定为 `status`、`summary`、`files_touched`、`verification`、`findings`、`risks`。任何额外 prose、缺字段、非法 nested verification/finding、或只靠进程退出码的“成功”，都不满足下游 dependency。Claude 和 Codex 都遵守同一结果 schema。

默认 provider 分工保留 Claude-only 时代的长上下文产出优势，同时把 Codex 用在独立质量门：

| branch / role | 默认 provider | sandbox / 权限 |
|---------------|---------------|----------------|
| `backend` / `frontend` / `implement` / `product` / `ui` | Claude | 写入型交付，适合长上下文实现/产品/UI |
| `explore` / `review` / `verify` / `audit` / `security` | Codex | 默认 read-only，适合侦察、审查、验证、安全、对抗性质量门 |
| 显式指定 Codex 的写入型 `implement` / `rescue` / UI 交付 | Codex | 必须使用 `sandbox: "workspace-write"`，否则不得承担写入交付 |

最终放行必须同时消费独立 review / verify / audit、patrol gate、retrospector/after-action learning 和 no-omission parity matrix。`legion-patrol.sh status` 要能看到未解决巡查通知、gate 文件、mixed registry commander、tmux 活性和相关 events；`retrospector.sh quick/full` 要读取 legacy observations、inspector/daemon evidence、`.planning`、mixed registry/events、failed/blocked/latest result artifacts，并把候选学习写回 release evidence。没有这些证据，不能把文档契约当成 runtime PASS。

L1 指挥官也可以显式选择 provider：

```bash
# Claude Code L1（等价于旧 legion.sh l1，但语义更明确）
~/.claude/scripts/legion.sh claude l1 青龙军团

# Codex L1
~/.claude/scripts/legion.sh codex l1 玄武军团
# Codex L1 默认带 --dangerously-bypass-approvals-and-sandbox，保留本机默认模型

# 推荐短入口
~/.claude/scripts/legion codex l1 玄武军团

# 如果你想直接输入 legion codex l1，把 Legion scripts 放到 PATH 前面
export PATH="$HOME/.claude/scripts:$PATH"
legion codex l1 玄武军团

# 不写军团名：优先载入当前项目在线 Codex L1；如果没有在线 L1，就随机新增一个
legion codex l1

# 兼容入口
~/.claude/scripts/codex l1 玄武军团

# 如果你想直接输入 codex l1，把 Legion scripts 放到 PATH 前面
codex l1 玄武军团

# 这个 codex shim 只拦截 l1 / l1+1；codex exec、codex -C、codex --version 会转发给真实 Codex CLI

# 推荐项目军团启动：当前窗口进入 Claude L1，Codex L1 后台独立 tmux session
~/.claude/scripts/legion.sh claude h

# 在另一个窗口打开已在线 Codex L1；不写名字会复用当前项目已有 Codex L1
~/.claude/scripts/legion.sh codex l1

# 兼容入口：当前窗口变成 Claude L1，新 Terminal 窗口启动 Codex L1
~/.claude/scripts/legion.sh dou

# 一键双 L1：两个独立 Terminal 窗口，一个 Codex L1，一个 Claude L1
~/.claude/scripts/legion.sh duo

# VS Code 集成终端：当前终端内打开 tmux 作战面，含 codex / claude 两个 window
~/.claude/scripts/legion.sh duo --terminal vscode

# duo 也支持自定义两个 L1 的名字
~/.claude/scripts/legion.sh duo --codex 玄武 --claude 青龙
~/.claude/scripts/legion.sh duo --terminal vscode --codex 玄武 --claude 青龙

# 仅生成 Codex L1 prompt / launch 脚本 / registry，不启动 tmux
~/.claude/scripts/legion.sh codex l1 玄武军团 --dry-run

# 查看 duo 会在两个 Terminal 窗口里执行什么，不真正打开窗口
~/.claude/scripts/legion.sh dou --dry-run
~/.claude/scripts/legion.sh duo --dry-run
~/.claude/scripts/legion.sh duo --terminal vscode --dry-run
```

Codex L1 启动后会收到统一控制面提示：创建下属 worker 时通过 `legion.sh mixed campaign`，并在计划里用 `"provider": "claude"` 或 `"provider": "codex"` 明确调度哪类军团成员。Claude L1 通过 `legion.sh claude h` 或 `legion.sh claude l1 <名>` 启动时也会登记到同一个 mixed registry，因此同项目里的 Claude L1 和 Codex L1 可以互相看见，围绕同一份任务态势协同。默认启动不会把两个 L1 塞进同一个 `legion-view` 分屏；它们是两个独立 tmux session，需要合并观察时才显式运行 `legion view`。

```bash
# 一键启动双 L1；当前窗口 Claude L1，Codex L1 后台独立 session，默认不创建基础 L2
legion host
# 只后台启动则加：
legion host --no-attach

# 查看外部 Hermes AICTO profile 状态/启动指引；不创建本地 L0 commander
legion aicto

# 需要显式双 L1 子命令；默认仍只 attach Claude L1，不打开 combined view
legion host --dual-only
legion mixed dual-host --no-attach

# 需要旧单 L1 host 行为，可显式调用 mixed 子命令：
legion mixed host --host-only

# 只预演，不启动 tmux
legion host --dry-run

# 指定双 L1 名字
legion host --claude-name Claude主帅 --codex-name Codex主帅

# 显式分屏作战面：需要合并观察时手动打开
legion view
legion view --host L1-主持官
legion view --reuse          # 复用已有分屏 session；默认会重建 wrapper 以刷新任务 L2
legion view --dry-run        # 只打印将执行的 tmux 脚本

# L1 之间或 L1/L2 之间发消息：写入 mixed inbox；目标 tmux 在线时只显示非侵入通知
legion mixed msg L1-codex-xxxx "请同步审计边界" --from L1-claude-xxxx

# commander 之间的 mixed message 不会塞进任何输入框；实际内容从 inbox 读取
legion mixed inbox L1-主持官

# 查看 / 手动写入外部 Hermes AICTO 汇报队列
legion mixed aicto-reports
legion mixed report-aicto L1-主持官 "依赖服务不可用，任务暂时阻塞" --from L1-主持官 --kind problem

# 广播给所有活跃 L2
legion mixed broadcast "所有 L2 汇报当前状态" --from L1-主持官 --l2-only

# 只广播给某个 L1 的直属 L2
legion mixed broadcast "直属 L2 汇报初始化" --from L1-主持官 --l2-only --parent L1-主持官

# 检查 / 等待直属 L2 启动就绪；只有收到 readiness-order 或 M+ 扩编后才需要
legion mixed readiness L1-主持官
legion mixed readiness L1-主持官 --expect L2-implement-xxxx,L2-audit-xxxx --wait --timeout 180

# 查看某个 commander 的 mixed inbox
legion mixed inbox L2-audit-xxxx

# 查看示例计划
~/.claude/scripts/legion.sh mixed example

# 只登记任务，不启动 worker
~/.claude/scripts/legion.sh mixed campaign plan.json --dry-run

# S 级任务：在 L1 pane 内自动归属当前 L1，不创建 L2
~/.claude/scripts/legion.sh mixed campaign plan.json
tmux a -t legion-mixed-<project_hash>-<project_name>

# 显式 S 级 L1 直达（需要可追踪任务窗口时使用）
~/.claude/scripts/legion.sh mixed campaign plan.json --complexity s --direct

# M+ 军团级调度：按 branch 自动创建 L2 专业指挥官，再由专业指挥官带 worker
~/.claude/scripts/legion.sh mixed campaign plan.json --corps
```

计划格式：

```json
[
  {
    "id": "explore-architecture",
    "provider": "codex",
    "role": "explore",
    "task": "梳理仓库架构和改动入口",
    "scope": ["README.md", "scripts/", "agents/", "skills/"]
  },
  {
    "id": "implement-feature",
    "provider": "claude",
    "role": "implement",
    "task": "按侦察结论实现功能",
    "scope": ["scripts/new-feature.sh", "README.md"],
    "depends_on": ["explore-architecture"]
  },
  {
    "id": "codex-review",
    "provider": "codex",
    "role": "review",
    "task": "审查实现 diff，报告 correctness / security / testing 问题",
    "depends_on": ["implement-feature"]
  }
]
```

`provider` 可填 `claude`、`codex` 或省略。省略时，`review / verify / audit / explore` 默认走 Codex，`plan / implement / product-counselor / ui-designer` 默认走 Claude。显式让 Codex 执行写入型交付任务时，计划必须写明 `"sandbox": "workspace-write"`；Codex 的 read-only 质量门不要升级写权限。

`depends_on` 是真实调度门，不只是提示词。启动战役时，只有依赖为空或依赖已 `completed` 的任务会进入 tmux；依赖还在运行的任务保持 `planned`。当前置任务通过 worker 结果或 `mark` 被标为 `completed` 后，Legion Core 会自动解锁下一批 ready 任务。如果前置任务 `failed` 或 `blocked`，所有依赖它的后续任务会被标记为 `blocked`，不会继续放飞。

### 军团级专业分支

层级路由规则：L1 发起 campaign 时，`mixed campaign` 会从 `CLAUDE_CODE_AGENT_NAME` / `CLAUDE_LEGION_TEAM_ID` 自动识别当前 L1。S 级任务默认留在 L1，不为形式感创建二级窗口；M/L/XL 任务通过 `--corps` 创建 L2 专业指挥官并最大化有效协作规模。L2 发起同专业 campaign 时默认直接带本专业 worker；跨专业或需要再分层时使用 `--corps`。

`--corps` 用于强制军团级集群作战：L1 只管战略、优先级和验收，任务按 `branch` 路由到 L2 专业指挥官。比如后端实现交给 `backend` 分支指挥官，审计交给 `audit` 分支指挥官，避免 L1 直接指挥每个 worker。

动态扩编出来的 L2 默认是 campaign 生命周期：名下任务全部成功完成且没有要求保留上下文时，Legion Core 会发送 `DISBAND:init-complete`，关闭对应 tmux session，并把 L2 标记为 `completed`。`legion view` 默认只显示双 L1 和仍持有未结束任务的动态 L2；已完成但因上下文保留而留存的 L2 不会挤占默认作战面。如果该 L2 的上下文还要继续保留，在任务里声明：

```json
{
  "id": "frontend-impl",
  "branch": "frontend",
  "task": "实现前端改动，完成后保留上下文等待下一轮 UI 调整。",
  "retain_context": true
}
```

也可以用 `"context_policy": "retain"` 强制保留。失败或阻塞时默认保留诊断上下文。默认 `legion h` 不再创建 host 生命周期基础 L2；只有显式 legacy base-L2 路径或 M+ campaign L2 会出现在二级层。

L2 是执行单位，不是完整 L1 主持人。L1 / Legion Core 激活 L2 时会通过 `TASK-ASSIGNED` 写明目标、scope、依赖和必要上下文；L2 只需要确认自己是谁、父级是谁、任务是什么、如何完成、需要哪些项目经验/工具/技能和最小预研。不要让每个 L2 重复完整协议、全量态势、全武器库、全历史战法初始化，除非该任务本身要求做这种全局审计。

```json
[
  {
    "id": "backend-api",
    "branch": "backend",
    "role": "implement",
    "task": "实现后端 API",
    "scope": ["src/api/"]
  },
  {
    "id": "audit-api",
    "branch": "audit",
    "role": "audit",
    "task": "审计后端 API diff",
    "depends_on": ["backend-api"]
  }
]
```

默认分工：

| branch / role | 默认 provider | 适用场景 |
|---------------|---------------|----------|
| `backend` / `frontend` / `implement` / `product` / `ui` | Claude | 实现、产品、UI、需要长上下文的产出 |
| `explore` / `review` / `verify` / `audit` / `security` | Codex | 侦察、审查、验证、安全、对抗性质量门 |

`branch` 也会参与默认角色推导：例如只写 `"branch": "audit"` 时，任务默认按 `role=audit/provider=codex` 运行；只写 `"branch": "backend"` 时，任务默认按 `role=implement/provider=claude` 运行。若显式填写 `role` 或 `provider`，显式值优先。

L2 指挥官同样在 tmux 中可见，并写入 `mixed-registry.json` 和 `events.jsonl`。这保证 `legion.sh claude l1 青龙` 与 `legion.sh codex l1 玄武` 同时存在时，双方看到的是同一套战场态势。

自动模式下，所有 worker 的结构化结果都会被消费：`completed`、`blocked`、`failed` 会写回 registry，即使进程退出码为 0 也不会误判。Claude worker 也必须输出合法结构化 JSON；纯文本“完成了”会被标记为 `failed`。tmux / CLI 启动失败会记录为 `failed`，已 `completed` 或 `failed` 的 L2 指挥官不会被新 `--corps` 战役继续复用。

## 目录结构

```
~/.claude/
├── CLAUDE.md            # 全局第一原则（指挥官自主权）
├── README.md            # 本文件
├── install.sh           # 一键部署
├── settings.json        # Claude Code 全局设置
│
├── agents/              # Agent 定义（L2 teammate 模板）
│   ├── explore.md       #   只读侦察参谋
│   ├── plan.md          #   架构师
│   ├── implement.md     #   实现者
│   ├── review.md        #   审查者
│   ├── verify.md        #   对抗性验证者
│   ├── product-counselor.md  # 产品参谋
│   ├── ui-designer.md   #   UI 设计师
│   └── sniper.md        #   狙击手（定点清除）
│
├── skills/              # Skill 定义（工作流 / 方法论）
│   ├── recon/           #   竞争性侦察
│   ├── spec-driven/     #   spec 驱动开发
│   ├── agent-team/      #   团队编排
│   ├── audit/           #   对抗性验证总协议
│   ├── roundtable/      #   圆桌议事
│   ├── degradation-policy/  # 降级原则
│   └── ...
│
├── commands/            # Claude Code 斜杠命令
│   ├── commit.md        #   /commit
│   ├── create-pr.md     #   /create-pr
│   ├── review-pr.md     #   /review-pr
│   └── ...
│
├── scripts/             # 运行时脚本
│   ├── legion.sh        #   军团主入口（109K，核心）
│   ├── legion_core.py   #   Claude + Codex 混编调度核心
│   ├── legion-mixed.sh  #   混编调度 wrapper
│   ├── legion-init.sh   #   军团初始化
│   ├── legion-mailbox.sh    # 邮箱工具库
│   ├── legion-commander.py  # 指挥官 Python 后端
│   ├── stack-verify.sh  #   验证工具链
│   └── hooks/           #   Claude Code hooks
│
├── commander/           # 指挥官模板（L1 启动时复用）
├── memory/              # 全局战法库
│   └── tactics/         #   跨项目可复用的战法 + INDEX.md
├── plans/               # 计划模板
│
└── <运行时目录，gitignore 排除，clone 后由 install.sh 重建>
    ├── legion/          #   各军团运行时状态
    ├── sessions/        #   会话数据
    ├── projects/        #   项目级 memory
    ├── cache/ backups/ file-history/ shell-snapshots/ ...
```

## 项目级定制

在具体项目的 `.claude/` 下可覆盖全局定义：

```
<项目>/.claude/
├── agents/              # 项目定制 agent（优先级高于全局）
├── skills/              # 项目定制 skill
├── settings.local.json  # 项目级权限放行（gitignore）
└── ...
```

配合项目根 `CLAUDE.md`，可声明：
- 技术栈 / 架构约束
- 项目特定红线（如 "禁止 Agent + run_in_background"）
- 复杂度升级规则（如"改动 Seedance API 自动升 L 级"）

## 工作流

```
用户需求
    ↓
[三步深挖] 苏格拉底 + 第一性原理 + 奥卡姆剃刀
    ↓
[recon] 按复杂度 1-3 路参谋并行侦察
    ↓
[roundtable] 多视角辩论（L/XL 级或决策分叉时）
    ↓
[spec-driven] .planning/ 目录立案
    ↓
[agent-team] 流水线部署实现者 + 审查者
    ↓
[audit] 对抗性验证（合规 + 红队 + 集成）
    ↓
通过 → 汇报完成
```

圆桌会议 skill 分两层有效性：基础健康通过表示可以做需求分析和专家匹配；`--require-runtime` 通过才表示可以真实启动多专家子 Agent。当前缺少 `openclaw.tools.sessions_spawn` 时，不得声称“圆桌已完成”，应改用 Legion Core 的 `mixed campaign --corps` 编排 L2 进行等价多专家讨论。

圆桌是全军种共享武器，但不再要求每个 L2 启动都跑圆桌健康。L1 启动会记录基础健康；L2 只有在被分配圆桌/架构/高成本决策任务时才运行 `roundtable_health.py --require-runtime` 并在任务汇报里说明结果。Claude 侧使用 `.claude/skills/claw-roundtable-skill`；Codex 侧通过 `.agents/skills/claw-roundtable-skill` 桥接入口发现同一套项目圆桌包。

```bash
python3 .claude/skills/claw-roundtable-skill/roundtable_health.py
python3 .claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime
```

## 故障排查

| 症状 | 处理 |
|------|------|
| 授权弹窗后 CLI 崩溃 `q.toolUseContext.getAppState is not a function` | 升级到 2.1.118+ |
| `legion.sh` 无响应 | `tmux list-sessions` 检查 session 存在；`legion.sh status` 看注册表 |
| teammate 不出现在 tmux | `legion.sh status` 查 `[failed]`；看 `~/.claude/legion/<ID>/logs/` |
| 战法找不到 | `ls ~/.claude/memory/tactics/INDEX.md` 确认索引；没有的话 `legion.sh l1` 启动自检会自动重建 |
| Skill 列表看起来没加载 | 重启 `claude`（skill listing 启动时加载） |
| Codex 提示 `Exceeded skills context budget` | 运行 `python3 scripts/codex_skill_budget.py --apply` 压缩全局 skill frontmatter 描述，然后重启 Codex |
| 权限弹窗频繁 | 项目内 `.claude/settings.local.json` 预放行路径（示例见 `docs/settings.local.example.json`，如无则手写） |

## 设计原则

1. **可视化 > 后台** — 所有并行工作必须用 `TeamCreate` + tmux，禁用 `Agent` + `run_in_background`
2. **自主权第一** — 流程决策（要不要组团/侦察/审查）指挥官全权，只在不可逆破坏 / 需求模糊 / 跨项目共享状态 / 高成本返工时停下问用户
3. **完成前必过审计** — 不跑 `/audit` 不许说完成
4. **降级必须有理由** — 影响核心目标的降级（fallback / try-except / skip）默认禁止
5. **经验沉淀** — 跨项目可复用的教训写进 `memory/tactics/`，不是每次重学

## 贡献

- 上游：https://github.com/ziyerr/legion-0
- 本地提交会通过 `post-commit` hook 自动 `git push` 到 origin（保持与 upstream 同步）
- 修改 `agents/` / `skills/` / `commands/` 时，`pre-commit` hook 会自动同步模板

## 维护

个人维护项目，未开放外部 PR。Fork / Issue 欢迎。

## License

TBD（作者未声明；当前作为个人项目维护）
