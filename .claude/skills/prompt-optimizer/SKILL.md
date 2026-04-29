---
name: prompt-optimizer
description: Prompt 结构化优化器。创建 teammate prompt、调用 LLM、写新 skill 时使用，把模糊指令变成结构化（role + context + constraints + output_format + 反例），提升执行稳定性、防歧义、防 prompt injection。模糊 prompt 是军团质量波动的头号来源。
---

# Prompt Optimizer — 提示词结构化优化器

## 核心原则

**模糊 prompt = 军团执行质量的二阶方差放大器。** 同一个"模糊需求"每次给不同 teammate 都会产出不一样的结果，而且你无法复现 bug、无法回归、无法 A/B 测试哪个 prompt 更好。

结构化 prompt 的目标：把 "我要你做个登录页" 变成：
- **Role**：你是一个熟练前端工程师
- **Context**：项目用 Next.js App Router + Tailwind + 已有设计系统（文件路径）
- **Task**：实现 `/login` 路由组件
- **Constraints**：表单字段 [email, password]、失败态必须有文案、按 WCAG AA 对比度
- **Output Format**：一个 tsx 文件 + 必要的 test 文件
- **Reference**：参考现有 `/register` 实现风格

用了 prompt-optimizer，teammate 的执行稳定性 / 可回归性 / 可审计性都会提升一个数量级。

## 前置条件

**不需要任何 MCP**。本 skill 是"认知工具"，Claude 读到 skill 后会自动按 7 问 checklist 评估并结构化 prompt。

曾调研过几个社区 MCP 实现（2026-04 检查）：
- `@prompt-optimizer/mcp-server` — 不存在
- `mcp-prompt-optimizer` — 存在但是付费云服务（需 promptoptimizer.xyz API key）
- `Nouman159/prompt-optimizer-mcp` — GitHub 源码，需自行构建
- linshenkx/prompt-optimizer — Web app，非 MCP 形态

结论：**直接用 skill 本身**最可靠。若未来出现稳定免费 MCP 版本可再接入（接入后把上方这段改掉即可）。

## 触发条件

**必须**用 prompt-optimizer 的场景：

| 场景 | 为何必要 |
|------|---------|
| **创建 teammate prompt**（TeamCreate / Agent 的 prompt 字段） | 指挥官写完 prompt 后过一遍优化器，catch 歧义 |
| **LLM 业务调用 prompt**（`call_claude_stream(prompt=...)` 之类） | 生产 prompt 影响每个用户，必须严谨 |
| **新 skill SKILL.md** | skill 是"提示词产品"本身，更要结构化 |
| **审查收到的 prompt**（review 阶段） | 反过来检查已有 prompt 是否有漏洞 |
| **prompt injection 防御** | 优化器能识别注入面并加守护层 |

**推荐**用（非必须）：

- 写新 agent system prompt
- 写 CLAUDE.md 的新规则段
- 做 A/B test 比较两个 prompt 效果

**跳过**场景：

- 一次性 throwaway 查询（杀鸡用牛刀）
- prompt 已经多轮打磨过（避免无休止优化）
- 时效性强的场景（优化多轮 = 延迟几秒）
- prompt < 30 字的极短指令（本身就没什么可优化空间）

## 结构化 checklist（无 MCP 时人工用）

对着你的 prompt 过一遍 7 问：

1. **Role**：告诉 LLM 它是谁（「你是」后面那句话）？
2. **Context**：它需要的背景、文件路径、现有约定、业务状态？
3. **Task**：具体要做什么？动词开头，一句话能说清。
4. **Constraints**：
   - 硬约束（必须 / 禁止）
   - 软偏好（建议 / 倾向）
   - 边界（什么**不**做）
5. **Input / Output**：输入格式？输出格式（JSON/Markdown/纯文本/函数签名）？
6. **Reference**：类似示例的文件位置，或 few-shot example。
7. **Reject conditions**：什么情况下它应该回"做不了/拒绝"而不是硬撑？

任何一问答不上来 → prompt 有漏洞，补强。

## 使用流程

### L1 指挥官创建 teammate 时

```
[L1 思考 prompt 初稿]
    ↓
[过 prompt-optimizer]
    ↓ 结构化后（7 问都答了）
TeamCreate(... prompt: <优化后 prompt>)
    ↓
teammate 输出质量显著更稳
```

### 开发者写业务 LLM 调用时

```python
# 改前
prompt = f"帮我把 {topic} 写成脚本"

# 过 prompt-optimizer 后
prompt = f"""
你是一个短视频脚本编剧，目标受众是中文抖音用户。
任务：基于给定话题，产出一条 30-60 秒口播视频脚本。
约束：
- 开头 3 秒内必须抓注意力（疑问 / 冲突 / 数据）
- 不使用「大家好」这类俗套开头
- 输出纯文本脚本，不含 [旁白]/[镜头] 等舞台指令
- 如果话题敏感（政治/暴力），返回 "REJECT: <原因>"
话题：{topic}
"""
```

### 写新 skill 时

SKILL.md 是"给未来的自己和 teammate 的 prompt"。每次写完必须：

1. 对照 7-question checklist
2. 用反例测试（「如果 teammate 误解成 X，会怎样？」）
3. 确保 description 字段能让 skill-matching 准确命中

## 与其他 skill 协同

- **skill-creator**：创建新 skill 时，skill-creator 调用 prompt-optimizer 审 SKILL.md
- **claw-roundtable-skill**：圆桌讨论前，主持 prompt 过一遍优化器
- **recon**：侦察参谋 prompt 过优化器，确保"参谋 A 技术方案/参谋 B 风险/参谋 C 约束"各司其职无重叠
- **audit**：审计者的攻击 prompt 过优化器，保证攻击面覆盖完整
- **self-improving-agent**：学习完成的 skill experiences 里，prompt 版本变迁是主记录对象

## 反模式

- ❌ **结构化过度** — 10 行 prompt 写成 200 行，淹没核心。原则：结构 × 精简。
- ❌ **所有东西都过优化器** — 杀鸡用牛刀。看 prompt 实际价值再决定。
- ❌ **优化完一次就永久不改** — prompt 要和业务同步演进，定期回看。
- ❌ **信不过原始 prompt 就全删重写** — 增量改进 > 推倒重来。保留原意图。
- ❌ **只看"优化器说好"就 ship** — 最终还是要业务场景里跑一次验证输出质量。

## 度量（你怎么知道优化有效）

- **执行重试率下降**：同一 prompt 跑 10 次，产出一致性 ↑
- **歧义 question 下降**：teammate 不再问"你说的 X 是指...?"
- **红队 prompt injection 通过率下降**：防御层到位
- **回归 bug 率下降**：prompt 改动可追溯
