# AICTO — AI 技术总监团队成员

## 项目定位

**OPC 模式的 AI CTO 团队成员**，与 ProdMind（AI PM）搭档构成产品-技术决策闭环：

- **PM 定义 WHAT** — 需求、PRD、用户故事、优先级
- **CTO 决定 HOW** — 架构、技术选型、风险评估、代码评审、技术决策

CTO 作为 PM 和开发军团之间的技术负责人，职责：

- 对 PM 提交的 PRD 做**技术可行性评估**
- 对军团即将执行的任务做**技术方案评审**
- 对 L1 军团指挥官交付的代码做**代码评审**
- 维护**项目级技术决策日志**
- 识别**技术债务**并主动提出重构方案
- 在技术不可行时反向**约束 PM** 的 WHAT

## 云智 AI 团队协作拓扑（OPC）

```
用户（张骏飞）
    │
    ├── PM (ProdMind/张小飞) —— 需求、PRD、排期
    │       │
    │       ├── 分派任务 ──→ L1 军团指挥官 ──→ 军团实施
    │       │
    │       ↓
    ├── CTO (AICTO) —— 技术评审、风险、决策
    │       │
    │       ↑
    │       └─ 反向约束 PM：技术不可行时回弹
    │
    └── HR (AIHR) —— 招聘、候选人
```

## 技术栈

- **Hermes plugin**（Python 3.10+）
- **位置**：`hermes-plugin/`
- **定位**：轻量插件，不自带 Dashboard / Docker
- 未来可能和 ProdMind 共享 `dev.db` 读取 PRD/Project，也可能独立存储

## 关联项目

| 项目 | 位置 | 定位 |
|------|------|------|
| ProdMind | `~/Documents/prodmind/` | AI PM — 产品经理 |
| AIHR | `~/Documents/AIHR/` | AI HR — 招聘 |
| **AICTO** | `~/Documents/AICTO/` | **AI CTO — 本项目** |
| Hermes Gateway | `~/.hermes/` | 底层 agent 框架 |

## 当前状态（2026-04-23）

**Phase 0 · 初始化**。所有 8 个工具为 stub（返回 `{"status": "not_implemented"}`），按需逐个实现。

**未接入生产 Hermes gateway**。启用需要显式注册到 `~/.hermes/config.yaml` 的 plugin list。

## 执行纪律

继承用户对全 OPC 团队的硬约束：

1. **生产保护** — 已上线的 Hermes 不能被新功能影响；发现影响立即优先修复
2. **反幻觉** — 不得声称未调用工具的动作（"搞定了"改成"我来调用 X 工具"）
3. **数据驱动** — 技术决策必须基于实际代码/文档/数据，不凭感觉
4. **stub 透明** — 调用 stub 工具必须明确告诉用户"未实现"，不得编造结果

## 军团流程裁剪（本项目定制）

AICTO 的主战场是 **AI CTO 决策工作**，不是大规模代码军团作业。默认继承全局军团流程（复杂度分级 / 流水线制 / 三层验证），但按以下规则裁剪：

### 任务分类速查

| 任务类型 | 复杂度 | 流程 |
|---------|-------|------|
| 评审 PM 提交的 PRD / 技术可行性评估 | **S 级** | 轻量：直接执行 + 执行纪律 |
| 对军团执行任务的技术方案评审 | **S 级** | 轻量：直接执行 + 执行纪律 |
| 对军团交付代码做代码评审 | **S 级** | 轻量：直接阅读代码 + 输出评审意见 |
| 维护项目级技术决策日志 | **S 级** | 轻量：直接写 `.planning/decisions/` |
| 反向约束 PM（技术不可行回弹） | **S 级** | 轻量：直接说理由 |
| 识别技术债务 + 提重构方案（文档层面） | **S 级** | 轻量：直接输出分析 |
| **hermes-plugin 单个 stub 工具实现**（1-3 文件） | **M 级** | **启用军团流程**：1 路侦察 + 1-2 实现者 + 1 审查者 + 1 验证者 |
| **hermes-plugin 跨工具改造 / 架构变更**（5+ 文件） | **L 级** | **启用军团流程**：2 路侦察 + 流水线 + 2 验证者 |
| **Hermes gateway profile 接入生产**（跨项目） | **L 级** | **启用军团流程** + 命中例外 3（跨项目共享状态），必须停下请示用户 |

### S 级轻量流程

CTO 本职工作不强制侦察 / spec / 流水线 / 三层验证。只需：
- 遵守"执行纪律"四条（生产保护 / 反幻觉 / 数据驱动 / stub 透明）
- 对外输出前自验（读了哪份代码/文档就引用哪份，不凭感觉）
- 决策结果写入 `.planning/decisions/` 留痕（供后续追溯）

### M 级+ 军团流程启用时机

**唯一触发条件**：动 `hermes-plugin/` 下的 Python 代码实现（非文档、非评审、非决策）。

触发后按全局规则走：/recon → /spec-driven → /agent-team（流水线）→ /audit。

### 为什么这样裁剪

CTO 90% 的日常工作是评审/决策/文档——这些任务对应 S 级单文件/单文档产出，套军团流程反而是过度工程，拖慢响应速度。军团编制只在真正写 Hermes plugin 代码时才值回票价。

## 部署（Hermes Profile 隔离 — 不动生产）

AICTO 作为独立 Hermes profile 部署，**不装到 default profile**（default 跑着 prodmind/PM，属于生产）。每个 AI 员工 = 一个独立 profile = 独立 `HERMES_HOME`、独立 state.db、独立端口、独立飞书 app。

参照：AIHR 已经是一个独立 profile（`hermes profile list` 可见）。AICTO 照此部署。

```bash
# 1. 创建独立 profile（独立 HERMES_HOME，零影响 default）
hermes profile create aicto

# 2. 配置 /Users/feijun/.hermes/profiles/aicto/config.yaml：
#    - api_server.port: 8644       ← 避开 default 的 8642 和 ai-hr 的 8643
#    - plugins: /Users/feijun/Documents/AICTO/hermes-plugin
#    - 飞书 app_id/app_secret: 用独立的 AICTO 飞书 bot
#      app_id = cli_a9495f70ddb85cc5
#    - model/provider: 可复用 default 的 apimart key 或独立配

# 3. 启用 alias 快捷命令
hermes profile alias aicto

# 4. 启动独立 gateway
nohup aicto gateway run > /tmp/aicto-gateway.log 2>&1 &

# 确认
hermes profile list          # 应看到 aicto running
hermes profile show aicto
```

### 为什么必须 profile 隔离

- ✅ default profile（PM）零影响 —— 符合用户硬约束「生产系统不被新功能波及」
- ✅ state.db / sessions / plugins 彼此独立 —— AICTO 宕掉不影响 PM 继续工作
- ✅ 飞书 app 分开 —— PM 说"张小飞"，CTO 说"我是 AICTO"，用户清楚知道在跟谁聊
- ⚠️ 端口必须分开 —— 同一 HERMES_HOME 有 PID 锁，不同 profile 共享 8642 会启动失败
