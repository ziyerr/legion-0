---
name: agent-team
description: 批次审查制团队编排。实现者完成后启动审查者，按复杂度分级支持批次审查和里程碑审查两种模型。S/M/L/XL四种编制。
---

# Agent Team — 批次审查制精英团队编排

## 核心原则

1. **批次审查制** — 实现者完成后，指挥官再启动审查者，符合异步通信模型
2. **质量唯一退出条件** — 没有轮次上限，循环到所有门禁通过
3. **按复杂度分级** — 不一刀切，S 级不需要团队，XL 级全员出动
4. **文件隔离** — 每个实现者有明确的文件范围，不交叉
5. **模型适配** — 实现者/验证者必须 opus（编码需最强推理），参谋/审查者允许 sonnet（只读任务不需要 Opus 级编码能力，降低 API 争抢提高有效并发）
6. **思考深度分级** — 审查者 `max`（找缺陷需最深推理），实现者 `high`（编码执行足够）

## 专用 Agent（.Codex/agents/）

项目已定义 7 个专用 agent，创建 teammate 时**必须通过 `subagent_type` 指定**，继承其系统提示、工具集和 model:

| 角色 | subagent_type | 说明 |
|------|--------------|------|
| **实现者** | `implement` | 有 Edit/Write 权限，内置编码规范和审查通信协议 |
| **审查者** | `review` | 只读，内置审查清单和反馈格式，不可修改文件 |
| **验证者** | `verify` | 只读+可执行命令，内置合规/红队/集成三模式 |
| **参谋/侦察** | `explore` | 只读，代码探索和调研 |
| **架构师/规划** | `Plan` | 只读，需求分析和实现方案设计 |
| **产品参谋** | `product-counselor` | 只读，产品设计和业务逻辑分析 |
| **狙击手（定点清除）** | `sniper` | 只读，问题复发时追溯根因，定点清除 |
| **UI 设计师** | `ui-designer` | 只读，基于设计系统输出视觉规范，由产品参谋按需召唤 |
| **伞兵（外援）** | — | Codex/GPT 差异模型视角，通过 `codex-team.sh` 空降 |

> 实现者(implement)和验证者(verify)固定 opus。参谋(explore/plan)和审查者(review)默认 sonnet，指挥官可按需升级为 opus。
> 专用 agent 已内置初始化协议（读需求/读 AGENTS.md/读审查清单等），prompt 只需提供任务上下文。

### 伞兵（外援）使用方式

伞兵（Codex/GPT）不通过 TeamCreate 创建，而是通过 Bash 调用 `codex-team.sh` 空降战场：

```bash
# 空降审查（伞兵提供第二意见）
bash .Codex/scripts/codex-team.sh review --base main gui/src/components/Foo.tsx

# 空降红队（差异模型视角的对抗性审查）
bash .Codex/scripts/codex-team.sh adversarial --base main

# 空降救援（团队卡壳时，伞兵独立调查）
bash .Codex/scripts/codex-team.sh rescue "video_gen 在并发 >5 时死锁，已排查 timeout 和 mutex"

# 空降参谋（对技术方案征求不同视角）
bash .Codex/scripts/codex-team.sh second-opinion "DAG 调度器用 petgraph 还是自研拓扑排序？"
```

**核心原则：差异模型的价值在于不同视角。** Codex（GPT）和 Codex 的认知框架不同，同一段代码可能关注不同的风险点。正因为它是"劲敌"，它的不同意见最有价值。

**使用场景（M 级及以上全部强制）：**
- M 级验证阶段 → 伞兵 review 与 Codex verify 交叉验证
- L/XL 级验证阶段 → 伞兵 adversarial 作为独立红队成员
- 审查出现分歧 → 伞兵 second-opinion 打破平局
- 实现者卡壳超 30 分钟 → 伞兵 rescue 提供新思路
- 关键架构决策 → 伞兵 second-opinion 提供对照视角

**铁律：M 级及以上，伞兵必须进场。不计成本，以最大规模换取效率和质量。**

## 思考深度配置（effort level）

创建 teammate 时，在 prompt 最开头加入 effort 切换指令：

| 角色 | model | effort | 说明 |
|------|-------|--------|------|
| **实现者** | opus | high | 编码需最强推理 |
| **审查者** | sonnet | high | 只读审查，sonnet 足够 |
| **参谋** | sonnet | high | 只读探索 |
| **验证者** | opus | high | 需运行命令验证 |

## 复杂度与编制

| 复杂度 | 总人数 | 编制 | 触发条件 |
|--------|--------|------|----------|
| **S 级** | 0 | 指挥官直接做 | 单文件 bug/配置 |
| **M 级** | 3-4 | 1-2 实现者 + 1 审查者（实现者完成后创建） | 2~5 文件，单域 |
| **L 级** | 6-8 | 2-3 实现者 + 1-2 审查者 + 1 验证 | 跨域，5+ 文件 |
| **XL 级** | 10-14 | 3-4 实现者 + 2-3 审查者 + 3 验证 | 10+ 文件，架构变更 |

## 审查工作模型：流水线制

**核心原则：不计成本，用并行替代串行等待。实现者全速推进，条件满足即刻启动审查。**

```
流水线制（所有级别统一）：

阶段1 — 全速实现（并行，零等待）
  所有实现者同时工作，各自负责文件范围
  每完成一个文件 → 自验证（cargo check / tsc --noEmit）
  全部完成 → SendMessage 给指挥官报告文件列表 + 自验证结果
  ※ 不停下来等审查，全速推进到自己范围内的所有文件

阶段2 — 流式审查（条件触发，即刻启动）
  任一实现者报告完成 → 指挥官立即创建审查者（不等其他实现者）
  多个审查者并行工作（不计成本，每个域一个审查者）
  L/XL 级：加 1 路交叉审查者审高危文件（第二意���）

阶段3 — 集中修复（一轮修复）
  指挥官汇总所有审查反馈 → 一次性发给对应实现者
  实现者一轮修复所有问题 → 自验证 → 报告
  指挥官判定无害 → 自主放行，直接进验证（见「指挥官自主放行权」）
  修复项多且高危 → 简短重审（仅审查修改的文件，非全量）

阶段4 — 最终验证（并行）
  部署验证者（按复杂度 1-3 路）
```

**与旧模型对比：**
```
旧：impl→停→等审查→修→impl→停→等审查→修  （串行，利用率~50%）
新：impl全速→审查即刻→一轮��复→验证        （流水线，利用率~95%）
```

### 角色职责

**实现者（Implementer）— subagent_type: `implement`：**
- 按 spec 全速编写代码，不停下来等审查
- 每完成一个文件 → 自验证（stack-verify.sh check）
- 全部完成后 → SendMessage 给指挥官报告

**审查者（Reviewer）— subagent_type: `review`：**
- **由指挥官在��应实现者完成后立即创建**
- 批量审查该实现者的所有文件（不是一个一个来）
- 审查完成 → SendMessage 给指挥官（APPROVED 或具体反馈）

### 通信协议

实现者完成：
```
SendMessage → 指挥官: "域A完成 [文件列表]，自验证全PASS"
```

指挥官即刻启动审查者：
```
Agent(subagent_type: "review", prompt: "审查以下文件: [文件列表]...")
```

审查者反馈：
```
SendMessage → 指挥官: "Foo.tsx:42 [SEVERE] unwrap; Bar.tsx APPROVED — 共2 SEVERE / 1 WARN"
```

指挥官汇总后一次性转达：
```
SendMessage → 实现者: "审查反馈汇总: [全部问题]，一轮修复后报告"
```

## 指挥官编排流程

### 步骤 1：分析任务，判断复杂度

```
S 级：单文件 → 自己做
M 级：2-5 文件，单域 → 流水线小团队
L 级：跨域 5+ 文件 → 流水线 + 交叉审查
XL 级：10+ 文件 → 最大规模流水线 + 多路交叉审查
拿不准 → 往高走
```

### 步骤 2：设计编制

L 级示例：
```
域 A（前端）: 前端实现者(implement)
  - 负责: gui/src/components/*, gui/src/pages/*
  - 完成后指挥官启动前端审查者(review)

域 B（后端）: 后端实现者(implement)
  - 负责: gui/src-tauri/src/commands/*, gui/src-tauri/src/utils/*
  - 完成后指挥官启动后端审查者(review)

独立: Python 实现者(implement)（M级子任务，批次审查）
  - 负责: scripts/*
```

### 步骤 3：创建 teammates

**关键：先创建实现者，待实现者完成后再创建审查者。审查者需要知道变更的文件列表。**
**必须使用 `subagent_type` 指定专用 agent，不得创建通用 teammate。**

实现者创建示例（使用 Agent 工具）：
```
Agent(
  subagent_type: "implement",
  name: "fe-impl",
  model: "opus",
  prompt: """
    首先执行：/effort high

    你是前端实现者。

    任务：实现「具体需求」。
    负责文件范围：gui/src/components/*, gui/src/pages/*
    ONLY 修改你负责的文件。

    完成所有文件后 → SendMessage 给指挥官报告变更文件列表
  """
)
```

审查者创建示例（实现者完成后再创建，使用 Agent 工具）：
```
Agent(
  subagent_type: "review",
  name: "fe-reviewer",
  model: "opus",
  prompt: """
    首先执行：/effort max

    你是前端审查者。

    【上下文 — 理解需求才能判断代码对不对】
    用户需求：{指挥官填写}
    设计决策：{指挥官填写}
    如有 .planning/ 目录，先读 .planning/REQUIREMENTS.md 和 .planning/DECISIONS.md。

    审查以下文件：{实现者完成的文件列表}
    逐文件读代码 → 对照审查清单检查 → SendMessage 给指挥官反馈结果
  """
)
```

### 步骤 4：监控与干预

指挥官在实现阶段：
- 通过 TaskList 跟踪进度
- 实现者完成后 → 立即启动审查者
- 审查者反馈问题 → 转达给实现者 → 实现者修正 → 再次启动审查者（或同一审查者继续）
- 如果审查-修正循环超 3 轮 → 指挥官介入仲裁

### 任务队列与工作窃取（对齐 CC tryClaimNextTask）

指挥官维护 `.planning/task-queue.json`，idle teammate 自动领取任务：

```json
{
  "tasks": [
    {"id": "t1", "type": "review", "files": ["Foo.tsx"], "status": "pending", "assignee": null},
    {"id": "t2", "type": "implement", "files": ["Bar.rs"], "status": "claimed", "assignee": "be-impl"}
  ]
}
```

**指挥官职责：** 拆分任务 → 写入 task-queue.json
**Teammate 职责：** 完成当前任务后 → 读 task-queue.json → 领取 pending 任务 → 更新 status+assignee

工作窃取规则：
1. Teammate 完成后主动检查队列（而非等指挥官分配）
2. 只领取与自己角色匹配的任务（implement 领 implement 类型）
3. 领取后 30 分钟未完成 → 自动释放回 pending
4. 指挥官定期扫描 task-queue.json 检查超时任务

### 上下文接棒机制（Anthropic 研究：重置 > 压缩）

**teammate 不应硬撑到上下文耗尽。** 长时运行的 teammate 质量会随上下文增长而下降（"上下文焦虑"导致过早收尾）。

接棒流程：
1. teammate 上下文超 50% 或工具调用超 200 次 → 指挥官主动介入
2. 让当前 teammate 写 `.planning/STATE.json`（Schema 化 JSON，不是自由文本）：
   ```json
   {
     "snapshot_by": "teammate 名称",
     "timestamp": "ISO时间",
     "completed": [{"file": "路径", "change": "做了什么"}],
     "pending": [{"task": "描述", "reason": "为什么没做"}],
     "failed_attempts": [{"action": "尝试了什么", "error": "失败原因"}],
     "verification": {"stack_verify": "PASS/FAIL", "details": ""}
   }
   ```
3. 当前 teammate 退出（SendMessage 通知指挥官后自然结束）
4. 指挥官创建**同类型专用 agent** 的新 teammate，prompt 中加入：`先读 .planning/STATE.json 了解前任进度，接续 pending 任务，注意 failed_attempts 避免重蹈覆辙`
5. 新 teammate 天然拥有干净的上下文窗口，从 STATE.json 恢复进度

**Manus 洞察：**
- **Schema 化 > 自由文本** — JSON 字段固定，不会遗漏关键信息
- **保留失败轨迹** — `failed_attempts` 帮新 teammate 避免重复犯错
- **上下文窗口只是临时工作区** — .planning/ 才是持久记忆

### 步骤 5：验证阶段

所有审查完成后，进入对抗性验证（使用 `subagent_type: "verify"`，读 .Codex/skills/audit/SKILL.md）：

验证者创建示例：
```
Agent(
  subagent_type: "verify",
  name: "auditor-compliance",
  model: "opus",
  prompt: """
    你是合规审计员。
    验证模式：Compliance Audit
    验证范围：{指挥官填写变更文件列表}
    需求文档：.planning/REQUIREMENTS.md
    验证完成后 SendMessage 通知指挥官
  """
)
```

按复杂度部署验证者数量：
- M 级：1 个验证者 `verify`（合规+红队合一）
- L 级：2 个验证者 `verify`（合规 + 红队）
- XL 级：3 个验证者 `verify`（合规 + 红队 + 集成）

## XL 级流水线编制示例

```
指挥官 L1（不写代码，只协调 + 采集 metrics）
│
├── 侦察阶段（3 路参谋并行）
│   ├── 参谋-技术 → Agent(subagent_type: "explore")
│   ├── 参谋-风险 → Agent(subagent_type: "explore")
│   └── 参谋-内部 → Agent(subagent_type: "explore")
│
├── 阶段1 — 全速实现（并行，零等待）
│   ├── 实现者 A → 域 A（全速，不停等审查）
│   ├── 实现者 B → 域 B（全速）
│   └── 实现者 C → 域 C（全速）
│
├── 阶段2 — 流式审查（A完成→立即启动审查A，不等B/C）
│   ├── 审查者 A → 审查域 A（A完成后即刻创建）
│   ├── 审查者 B → 审查域 B（B完成后即刻创建）
│   ├── 审查者 C → 审查域 C（C完成后即刻创建）
│   └── 交叉审查者 → 高危文件二次审查（不计成本，第二意见）
│
├── 阶段3 — 集中修复（指挥官汇总反馈，实现者一轮修复）
│
└── 阶段4 — 最终验证（并行）
    ├── 合规审计员 → Agent(subagent_type: "verify")
    ├── 红队员     → Agent(subagent_type: "verify")
    └── 集成测试员 → Agent(subagent_type: "verify")

总计：指挥官 1 + 参谋 3 + 实现者 3 + 审查者 4 + 验证 3 = 14 人
```

## 质量门禁

```
门禁 1: 流水线审查 — 每个文件必须被审查者 APPROVED
门禁 2: 编译通过 — stack-verify.sh full
门禁 3: 对抗性验证 — 合规 + 红队 + 集成（按级别）

任一门禁 FAIL → 打回 → 修复 → 重新验证
```

### 指挥官自主放行权

指挥官确认变更无害时，可跳过部分门禁直接推进，不必等待审查/验证完成。

**放行条件（满足任一即可）：**

| 条件 | 可跳过 | 说明 |
|------|--------|------|
| 纯配置/文案/注释修改 | 门禁 1+3 | 只需编译通过（门禁 2） |
| 审查 0 SEVERE + 修复项 ≤3 WARN | 重审 | 直接进验证 |
| M 级任务 + 全文件 APPROVED + 编译 PASS | 门禁 3 | 指挥官自验证替代独立验证者 |
| 同一模式的重复修复（已有成功先例） | 门禁 1 | 指挥官比对先例，自主放行 |

**不可放行（铁门，无论如何不跳过）：**
- 涉及安全/权限/数据删除的变更
- XL 级任务的门禁 3
- 审查发现 ≥1 SEVERE 未修复

**放行时记录（写入 metrics）：**
```json
{ "gate_override": true, "reason": "纯配置修改，编译通过", "skipped": ["review", "audit"] }
```

## 输出格式

```markdown
## 团队执行报告

**任务**: [描述]
**复杂度**: S/M/L/XL
**编制**: [N] 人（[N] 实现者 + [N] 审查者 + [N] 验证）

### 侦察阶段
- 参谋数：N 路
- 关键发现：...

### 流水线执行
#### 阶段1 — 实现
| 域 | 实现者 | 文件 | 自验证 |
|----|--------|------|--------|
| A  | fe-impl | [文件列表] | PASS |

#### 阶段2 — 审查
| 域 | 审查者 | SEVERE | WARN | SUGGEST | 判定 |
|----|--------|--------|------|---------|------|
| A  | fe-reviewer | 2 | 1 | 0 | REJECTED |

#### 阶段3 — 修复
- 修复轮次：1（目标值，超过1需复盘原因）
- 修复项：[具体列表]

### 验证阶段
- 合规审计：PASS/FAIL
- 红队攻击：PASS/FAIL
- 集成测试：PASS/FAIL（XL 级）

### Metrics（数据驱动，指挥官必填）
→ 见下方 metrics 规范，写入 .planning/metrics.json

### 最终判定：PASS / FAIL
```

## 数据驱动：Metrics 采集

**每个任务完成后，指挥官必须写 `.planning/metrics.json`（追加到数组）。**

这是验证「不计成本换质量」假设的唯一方式。没有数据，一切优化都是猜测。

### Schema

```json
{
  "task_id": "简短标识",
  "timestamp": "ISO时间",
  "complexity": "S|M|L|XL",

  "scale": {
    "team_size": 8,
    "impl_count": 3,
    "reviewer_count": 3,
    "verifier_count": 2,
    "recon_routes": 2,
    "files_changed": 6
  },

  "timing": {
    "total_minutes": 45,
    "impl_minutes": 20,
    "review_minutes": 10,
    "fix_minutes": 5,
    "audit_minutes": 10
  },

  "quality": {
    "review_issues": { "severe": 3, "warn": 2, "suggest": 1 },
    "fix_cycles": 1,
    "audit_issues": { "severe": 0, "warn": 1 },
    "defect_by_layer": {
      "hook": 2,
      "review": 5,
      "audit": 1
    }
  }
}
```

### 关键指标解读

| 指标 | 健康值 | 警报值 | 含义 |
|------|--------|--------|------|
| `fix_cycles` | 1 | ≥3 | 流水线制目标为1轮修复；多轮说明需求不清或实现者能力不足 |
| `audit_issues.severe` | 0 | ≥2 | 审计发现严重问题 = 审查层失效，需复盘审查者质量 |
| `review_minutes / impl_minutes` | <0.5 | >1.0 | 审查耗时超过实现 = 审查者可能在做实现者的工作 |
| `defect_by_layer.audit` | 0-1 | ≥3 | 逃逸到审计的缺陷越多，前两层越弱 |

### 用数据验证假设

每 5 个任务后，指挥官读 `.planning/metrics.json` 回答：
1. 加人是否缩短了 `total_minutes`？（规模↔效率）
2. 多路审查是否降低了 `audit_issues`？（规模↔质量）
3. `fix_cycles` 是否稳定在 1？（流水线制有效性）
4. 哪一层捕获缺陷最多？（资源分配是否合理）

### 冲突防范（步骤 2 之前执行）

**XL 级 → 强制 worktree 隔离：**
```
Agent(isolation: "worktree", ...)
```
XL 级改动大（10+ 文件）、耗时长、风险高。在独立 worktree 中工作，物理上不可能与其他团队冲突。完成后 merge 回主分支。

**S/M/L 级 -> 文件 Claim：**

分配实现者**之前**，先 claim 要修改的文件：

```bash
# 检查文件是否被 claim
bash .Codex/scripts/claims.sh check gui/src/App.tsx

# claim 文件（冲突时自动报错）
bash .Codex/scripts/claims.sh claim gui/src/App.tsx L1-青龙军团 "添加导航入口"

# 列出所有 claim
bash .Codex/scripts/claims.sh list

# 释放（任务完成后）
bash .Codex/scripts/claims.sh release L1-青龙军团
```

内置保护：
- **flock 文件锁** -- 并发读写安全
- **30 分钟自动过期** -- 崩溃后 claim 不会永久占用
- **每次操作自动 GC** -- 读取时清理过期 claim

**原则：先 claim 再分配。发现冲突先协调再动手——不协调就开工必然竞争死循环。**

### 步骤 6: 指挥官沉淀（任务完成后）

1. **释放 claim** — `bash .Codex/scripts/claims.sh release L1-xxx`
2. **更新简报** — `.Codex/commander/briefings/{自己的L1名}.md`：
   - 旧经验过时 → 直接修改（自己的或别人的）
   - 新增：复杂度校准、编排实效、高风险模块
   - 保持精简（≤50行），过时的删除

## Gotchas

1. **必须用 subagent_type** — 禁止创建通用 teammate，所有角色都有对应的专用 agent
2. **审查者不是摆设** — review agent 内置审查清单，必须逐条对照
3. **审查者在实现者完成后创建** — 不要同时创建，避免审查者空转浪费上下文
4. **1 个审查者最多 cover 2 个域** — 超过会成为瓶颈
5. **指挥官不写代码** — L/XL 级时指挥官只协调，把精力留给仲裁和集成
6. **拿不准复杂度往高走** — M 还是 L？按 L 执行
7. **接棒用同类型 agent** — 新 teammate 必须使用与前任相同的 subagent_type
8. **所有协调经过指挥官** — 实现者和审查者不直接通信，指挥官中转一切
