---
name: audit
description: 对抗性验证协议。按复杂度部署1-3路独立验证（合规审计+红队攻击+集成测试），任一 FAIL 即打回。不跑验证不许说完成。
---

# 对抗性验证协议

## 核心原则

**不跑验证命令不许说完成。不贴输出不算验证。**

验证是基于证据的理性判断（rational judgment），不是走过场。每个判定必须有命令输出或代码引用支撑。

## 三层验证架构

代码吞吐量爆炸时，验证必须分布式。三层各管各的，不重复：

```
Layer 1: Quality Gate hook（自动，每次编辑后）
  → stack-verify.sh check 异步检查语法/类型
  → 抓：编译错误、语法错误、类型错误
  → 不需要人，不阻塞

Layer 2: 配对审查（实时，agent-team 流程中完成）
  → 审查者(subagent_type: "review")读代码检查逻辑/设计/安全
  → 抓：逻辑错误、设计缺陷、安全漏洞
  → 写一个查一个，缺陷在产生瞬间被捕获

Layer 3: 最终审计（本 skill，全部完成后）
  → 部署验证者(subagent_type: "verify")
  → 只做 Layer 1+2 无法覆盖的：跨模块集成 + 全栈编译 + 端到端
  → 不重审单文件逻辑（信任配对审查已覆盖）
```

**最终审计的职责边界：**

| 审 | 不审（前两层已覆盖） |
|----|---------------------|
| 跨模块接口匹配 | 单文件语法/类型（hook 已查） |
| 全栈编译通过 | 单文件逻辑正确性（配对已查） |
| 端到端主流程可用 | 代码风格/命名（配对已查） |
| 需求完整性（逐条对照） | — |
| 安全攻击面（红队） | — |

## 验证规模（按复杂度分级）

| 复杂度 | 验证方式 | 验证者数 | Codex 参与 | 说明 |
|--------|---------|----------|-----------|------|
| **S 级** | 指挥官自验 | 0 | 否 | `stack-verify.sh full` 即可 |
| **M 级** | 合规 + 红队（合一） + **伞兵审查** | 1+1 | **强制** | verify agent + 伞兵 review 交叉验证 |
| **L 级** | 合规 + 红队 + **伞兵红队** | 2+1 | **强制** | Codex 红队 + 伞兵对抗性审查 |
| **XL 级** | 合规 + 红队 + 集成 + **伞兵红队** | 3+1 | **强制** | 最大规模验证，伞兵作为独立红队成员 |

### 伞兵红队成员

伞兵（Codex/GPT）作为军团正式外援参与验证。**差异模型的价值在于不同的认知框架** — 同一段代码，Codex 和 GPT 关注不同的风险点，交叉验证覆盖更全面。

L/XL 级验证时，在部署 Codex verify agent 的同时，空降伞兵对抗性审查：

```bash
# 伞兵空降，与 Codex verify agent 并行执行
bash .Codex/scripts/codex-team.sh adversarial --base main
```

**伞兵红队报告处理规则：**
- 伞兵发现的 critical/major → 必须在 Codex 验证者报告中交叉确认或明确反驳
- 伞兵与 Codex 验证者意见不同 → 指挥官仲裁，不可忽略任一方
- 伞兵发现 Codex 全部验证者都没注意到的问题 → 高价值发现，记入战法库

## 验证者部署（统一使用 subagent_type: "verify"）

所有验证者使用专用 agent `verify.md`，该 agent 已内置：
- 初始化协议（读需求/设计决策/改动范围/项目规则）
- 三种验证模式（Compliance / Red Team / Integration）
- 审美评分（前端改动自动触发）
- 认知偏见对抗清单
- 结构化报告格式
- 攻击面参考清单（references/attack-surface.md）

**指挥官只需在 prompt 中指定验证模式和上下文，verify agent 自行执行完整流程。**

## 指挥官编排流程

### S 级（自验）

指挥官直接运行：
```bash
bash ~/.Codex/scripts/stack-verify.sh full
```
贴输出，确认通过即可。

### 指挥官职责：准备上下文

创建验证者前，指挥官必须准备：
1. 用户原始需求（一段话概括）
2. 关键设计决策（为什么这样做而不是那样做）
3. 改动文件清单（git diff --name-only 或列出）

如有 `.planning/` 目录，让验证者直接读取。没有的话，在 prompt 中写明。

### M 级（1 个验证者）

```
Agent(
  subagent_type: "verify",
  name: "auditor",
  model: "opus",
  prompt: """
    首先执行：/effort max

    验证模式：Combined（合规审计 + 红队攻击）

    【上下文】
    用户需求：{指挥官填写}
    设计决策：{指挥官填写}
    改动文件：{指挥官填写}
    如有 .planning/ 目录，先读 REQUIREMENTS.md 和 DECISIONS.md。

    两种模式的报告合并输出。
    任一维度 FAIL → 整体 FAIL。
    完成后 SendMessage 通知指挥官。
  """
)
```

### L 级（2 个验证者，并行创建）

合规审计员：
```
Agent(
  subagent_type: "verify",
  name: "auditor-compliance",
  model: "opus",
  prompt: """
    首先执行：/effort max

    验证模式：Compliance Audit

    【上下文】
    用户需求：{指挥官填写}
    设计决策：{指挥官填写}
    改动文件：{指挥官填写}
    如有 .planning/ 目录，先读 REQUIREMENTS.md 和 DECISIONS.md。

    独立判定，不参考其他验证员。
    完成后 SendMessage 通知指挥官。
  """
)
```

红队员：
```
Agent(
  subagent_type: "verify",
  name: "auditor-redteam",
  model: "opus",
  prompt: """
    首先执行：/effort max

    验证模式：Red Team
    你的目标是破坏这段代码。

    【上下文】
    用户需求：{指挥官填写}
    改动文件：{指挥官填写}
    如有 .planning/ 目录，先读 REQUIREMENTS.md 了解正常预期行为。

    独立判定，不参考其他验证员。
    完成后 SendMessage 通知指挥官。
  """
)
```

### XL 级（3 个验证者，并行创建）

在 L 级基础上加集成测试员：
```
Agent(
  subagent_type: "verify",
  name: "auditor-integration",
  model: "opus",
  prompt: """
    首先执行：/effort max

    验证模式：Integration Test

    【上下文】
    用户需求：{指挥官填写}
    改动文件：{指挥官填写}
    系统架构：前端(React/TS) → Tauri Command(Rust) → Python HTTP(FastAPI)
    如有 .planning/ 目录，先读 REQUIREMENTS.md。

    独立判定，不参考其他验证员。
    完成后 SendMessage 通知指挥官。
  """
)
```

## 指挥官裁决

收到所有验证报告后：

```
任一 FAIL → 整体 FAIL → 打回修复 → 修复后重新验证（全量重验）
全部 PASS → 整体 PASS → 可以说"完成"
有 UNCERTAIN → 向用户确认后再判定
```

## 综合验证报告格式

```markdown
## 对抗性验证报告

### 验证规模
- 级别：S/M/L/XL
- 验证员：N 路

### 合规审计：PASS/FAIL
（摘要关键发现）

### 红队攻击：PASS/FAIL
- 严重漏洞：N 个
- 中等漏洞：N 个
（摘要关键发现）

### 集成测试：PASS/FAIL（XL 级）
（摘要关键发现）

### 审美评分：PASS/WARN/FAIL（仅前端改动）
- 加权总分: X.X/10

### 最终判定：PASS / FAIL
```

## 战法沉淀（验证全过后执行）

验证全过（最终判定 PASS）后，指挥官问自己三个问题：

1. **意外踩坑？** → 有 → 写战法到 `~/.Codex/memory/tactics/`
2. **非常规有效路径？** → 有 → 写战法
3. **技能缺口？** → 有 → 记录到 `.planning/SKILL-GAPS.md`

没有新经验就不写 — 不为写而写。

## Gotchas

1. **必须用 subagent_type: "verify"** — 禁止创建通用 teammate 做验证
2. **"should pass" 不是证据** — 必须跑命令并贴输出
3. **红队不是走过场** — verify agent 已内置攻击面清单，会构造具体攻击场景
4. **三路验证员必须独立** — 不能互相参考，避免确认偏见
5. **修复后必须全量重验** — 修一个可能引入新问题
6. **agent 说 success 不可信** — 指挥官独立验证，贴原始输出
7. **验证细节在 verify agent 里** — 本 skill 只管编排，不重复验证方法论
