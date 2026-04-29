# RoundTable Skill - 多专家 Agent 深度讨论系统

[![Version](https://img.shields.io/badge/version-0.9.0-blue.svg)](https://github.com/openclaw/roundtable-skill)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)

> 模拟真实圆桌会议，5 轮渐进式讨论产生可执行方案

---

## 📋 技能说明

**RoundTable** 是一个多专家 Agent 讨论系统，模拟真实的圆桌会议场景。每个 Agent 从不同专业角度（技术、安全、体验等）提供独立观点，经过 5 轮深度讨论后形成更完善的方案。用户无须提前创建子 Agent，它利用 Sessions_Spawn 根据项目需求自动创建临时的子 Agent，每个 Agent 都会扮演不同的角色，得到不同的 Prompt，配置不同的模型，进行圆桌讨论，以期实现多维度专业角度的审视和合规，消除单一 agent 的技能盲区。适用于复杂项目前期的头脑风暴或项目后期的优化和合规审查。该技能会消耗成倍 Token 和时间，应根据需求选择。用户还可以参与补充意见以增强讨论。

配置有多模型的用户会获得更好的效果。该 Skill 打包了 Agency-Agent 的 146 个垂直领域专家的 Prompt，使得每个子 agent 都具备专业领域的思维方式。

---

## 🎯 适用场景

### ✅ 推荐使用
- 复杂项目前期的头脑风暴
- 技术方案设计和架构决策
- 产品方案讨论和 MVP 定义
- 项目后期的优化和合规审查
- 需要多方观点的复杂问题
- 需要深度分析的技术方案
- 需要权衡利弊的架构决策

### ❌ 不推荐使用
- 简单问题查询
- 需要立即回答的场景
- 单一专业领域可解决的问题

---

## ⚠️ 资源消耗

| 资源 | 消耗 | 说明 |
|------|------|------|
| **Token** | 成倍消耗 | 15 次子 Agent 调用（3 专家 × 5 轮） |
| **时间** | 15-30 分钟 | 每轮 3-8 分钟，并行执行 |
| **模型** | 多模型更佳 | 配置多模型的用户会获得更好的效果 |

**建议**：根据需求选择，复杂项目值得投入，简单问题使用普通对话即可。

---

## 👤 用户参与

用户可以参与讨论以增强效果：

### 补充意见
在 R5 轮之前，用户可以提出补充意见，系统会再开 5 轮讨论。

### 超时机制
- 用户补充意见超时：3 分钟
- 子 Agent 执行超时：300 秒/次（重试 2 次）

---

## 🚀 快速开始

### 基础用法

**中文**:
```
请你 RoundTable 讨论一下：智能待办应用技术方案
```

**英文**:
```
Please RoundTable this topic: Smart Todo App Technical Architecture
```

**代码方式**:
```python
from roundtable_engine import RoundTableEngine

# 创建引擎
engine = RoundTableEngine("智能客服系统技术方案")

# 运行（自动发送确认和进度通知）
success = await engine.run("user_channel")
```

---

## 👥 参与 Agent

### Agent 池配置

| 配置项 | 值 |
|--------|-----|
| **Agent 来源** | agency-agents-zh（146 个 Agent） |
| **选择策略** | 根据议题关键词智能匹配 |
| **调用方式** | sessions_spawn（runtime="subagent"） |
| **执行模式** | 并行执行（max 3 个/轮） |

### 模型自动匹配

| 专家角色 | 首选模型 | 备选模型 |
|---------|---------|---------|
| **工程专家** | `bailian/qwen3-coder-next` | `bailian/qwen3-coder-plus` |
| **体验专家** | `bailian/kimi-k2.5` | `bailian/glm-4.7` |
| **测试专家** | `bailian/qwen3.5-plus` | `bailian/qwen3-coder-next` |
| **Host** | `bailian/qwen3-max-2026-01-23` | `bailian/qwen3.5-plus` |

**匹配优先级**:
1. 用户显式指定 → 使用用户指定
2. 根据角色自动匹配 → 使用首选模型
3. 首选不可用 → 使用备选模型

详见：`MODEL_CONFIG.md`

### 专家角色示例

| 角色 | Agent ID | 职责 |
|------|---------|------|
| **工程专家** | engineering/engineering-frontend-developer | 技术栈选型、架构设计 |
| **体验专家** | design/design-ux-architect | 用户画像、交互设计 |
| **测试专家** | testing/testing-api-tester | 测试策略、覆盖率目标 |
| **安全专家** | engineering/engineering-security-engineer | 安全审计、风险评估 |
| **产品专家** | product/product-manager | 需求分析、MVP 定义 |

---

## 📬 通知机制

### 1. 确认请求

```
🔄 RoundTable 多 Agent 深度讨论

讨论主题：智能客服系统技术方案

📋 讨论说明：
- 参与 Agent：工程专家 + 体验专家 + 测试专家
- 讨论轮次：5 轮深度讨论（R1-R5）
- 预计耗时：15-30 分钟
- 输出内容：完整技术方案 + 多方观点 + 行动建议

⚠️ 请注意：
- RoundTable 适合需要深度分析的场景
- 如果您需要快速回答，请使用普通对话
- 讨论过程中您可以随时查看进度

请确认您的需求：
回复"确认"开始 RoundTable 深度讨论
回复"快速"获取简要方案（<1 分钟）
```

### 2. 进度更新（每轮完成）

```
📊 RoundTable 进度更新

当前：R2 轮完成（2/5）
进度：████████░░░░░░░░ 40%
已完成：工程专家，体验专家，测试专家
已耗时：8.5 分钟
预计剩余：12-20 分钟

点击查看当前讨论内容 →
```

### 3. 完成通知

```
✅ RoundTable 讨论完成

主题：智能客服系统技术方案
总耗时：23.5 分钟
讨论轮次：R1-R5（完整 5 轮）
输出内容：技术方案 + 安全建议 + 体验优化

📄 查看完整报告：
http://localhost:8080

[打开报告] [下载 PDF] [分享给团队]
```

---

## 📊 输出物

### 最终决策报告
- 讨论概要（各专家观点总结表）
- 最终决策（已确定事项 + 分歧裁决）
- 技术方案（技术栈表格 + 架构）
- 8 周行动计划（周级任务表）
- 风险提醒（Top 3 风险表）

### 过程文档
- R1-R4 完整讨论记录
- 每轮修改对比表
- 风险演进追踪

### 可执行性验证
- [ ] R1 包含至少 1 个对比表格
- [ ] R2 包含至少 3 处引用标注
- [ ] R3 包含至少 5 个风险 + 3 个缺陷
- [ ] R4 包含修改对比表格
- [ ] R5 包含周级计划表（至少 8 周）
- [ ] R5 包含 Top 3 风险表

**通过率目标**: 90%+

---

## 👤 用户参与

用户可以参与讨论以增强效果：

### 补充意见
在 R5 轮之前，用户可以提出补充意见，系统会再开 5 轮讨论。

### 超时机制
- 用户补充意见超时：3 分钟
- 子 Agent 执行超时：300 秒/次（重试 2 次）

---

## 📬 通知机制

```
roundtable-skill/
├── README.md                   # 本文件
├── SKILL.md                    # 技能说明
├── PACKAGE.md                  # 打包说明
├── LICENSE                     # MIT 许可证
├── requirements.txt            # Python 依赖
├── __init__.py                 # 模块导出
├── clawhub.json                # ClawHub 配置
├── roundtable_engine.py        # 执行引擎
├── roundtable_notifier.py      # 通知模块
├── agent_selector.py           # Agent 选择器
├── prompts/
│   ├── framework.md            # 提示词框架
│   └── README.md               # 提示词说明
├── templates/
│   ├── software-development.md # 软件开发模板
│   ├── product-planning.md     # 产品规划模板
│   └── business-research.md    # 商业研究模板
├── examples/
│   └── full-test-20260319.md   # 测试范本 ⭐
└── roundtable-viewer/          # 前端查看器
    ├── index.html
    ├── data.json
    └── assets/
```

---

## 🔧 安装步骤

### 1. 复制到 Skills 目录

```bash
cp -r roundtable-skill \
      ~/.openclaw/workspace/skills/
```

### 2. 验证安装

```bash
cd ~/.openclaw/workspace/skills/roundtable-skill
python3 -c "import roundtable_engine; print('✅ 模块加载成功')"
```

### 3. 前置要求

- Python 3.8+
- OpenClaw 环境
- 依赖安装：`pip install -r requirements.txt`

---

## ⚙️ 配置说明

### 统一配置

```python
# 所有轮次统一配置
TIMEOUT_SECONDS = 300  # 超时时间（5 分钟）
MAX_RETRIES = 2        # 超时重试次数
MODE = "quality"       # 质量优先
```

### 多模型配置（推荐）

配置多模型的用户会获得更好的效果。在 `openclaw.json` 中配置：

```json
{
  "models": {
    "providers": {
      "bailian": {
        "models": [
          { "id": "qwen3.5-plus", "name": "Qwen 3.5 Plus" },
          { "id": "qwen-max", "name": "Qwen Max" }
        ]
      }
    }
  }
}
```

---

## 📊 测试范本

完整测试报告见 `examples/full-test-20260319.md`，包含：

- 🤖 子 Agent 模型配置
- 📋 每个 Agent 的角色和提示词
- 🎯 测试主题和背景
- 📊 完整讨论记录
- ✅ 可执行性验证

---

## 🔗 相关链接

- GitHub: `https://github.com/openclaw/roundtable-skill` *(仓库)*
- ClawHub: `https://clawhub.com/skills/roundtable-skill` *(待上线)*
- 文档：`https://docs.openclaw.ai/skills/roundtable` *(待上线)*

---

## 📝 更新日志

### 0.9.0 (2026-03-19) - 基于真实测试优化
- ✅ 完整 5 轮流程（R1-R5）
- ✅ 强制批判深度（5 风险 +3 缺陷）
- ✅ 方案动态演进（R4 标注修改）
- ✅ 分歧明确裁决（R5 必须裁决）
- ✅ 产出可直接执行（周级计划 + 风险预案）
- ✅ 触发词识别（RoundTable/圆桌会议/圆桌讨论等）
- ✅ 真实子 Agent 调用（sessions_spawn）
- ✅ 上下文传递（每轮注入完整历史）

### 0.1.0 (2026-03-17) - 初始版本
- ✅ 基础 RoundTable 框架
- ✅ 3 专家角色定义
- ✅ 5 轮讨论流程
- ✅ 前端查看器

---

## 📄 许可

MIT License - 详见 [LICENSE](LICENSE) 文件

---

*RoundTable - 让决策更完善，让讨论更深入*
