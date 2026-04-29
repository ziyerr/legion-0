# RoundTable 故障排查报告

**排查时间**: 2026-03-23  
**排查人**: 旺财 🐕

---

## 🔍 问题现象

运行 RoundTable 时出现错误：
```
ERROR:root:Expert execution failed: ModuleNotFoundError
ERROR:root:Expert execution failed: ModuleNotFoundError
ERROR:root:Expert execution failed: ModuleNotFoundError
⚠️ 降级到标准单一模型配置
```

最终输出：`⚠️ 所有专家执行失败...`

---

## ✅ 已验证正常的组件

| 组件 | 状态 | 说明 |
|------|------|------|
| `asyncio` | ✅ OK | Python 内置模块 |
| `agency_agents_loader` | ✅ OK | 可正常加载 170 个专家 |
| `roundtable_engine_v2` | ✅ OK | 引擎模块可导入 |
| `requirement_analyzer` | ✅ OK | 需求分析器正常 |
| `EXPERT_PROFILES` | ✅ OK | 包含 finance-investment-analyst |

---

## ❌ 核心问题

### 问题 1: `openclaw.tools` 模块不可用

**错误位置**: `roundtable_engine_v2.py` 第 385 行

```python
from openclaw.tools import sessions_spawn
```

**错误类型**: `ModuleNotFoundError: No module named 'openclaw'`

**原因分析**:
- `openclaw` 是 OpenClaw 运行时环境的内部模块
- 在独立 Python 脚本中无法直接导入
- 该模块只在 OpenClaw Agent 会话上下文中可用

**影响**:
- 专家 Agent 无法创建 (`sessions_spawn` 调用失败)
- 所有专家执行都返回 `ModuleNotFoundError`
- RoundTable 降级到单一模型模式

---

## 🔧 解决方案

### 方案 A: 在 OpenClaw 会话中运行（推荐）

RoundTable 设计为在 OpenClaw Agent 会话中运行，而不是独立 Python 脚本。

**正确用法**:
```
RoundTable 讨论一下：稀有金属板块走势分析
```

通过 OpenClaw 消息系统触发，`openclaw.tools` 会自动可用。

### 方案 B: 修改代码使用工具调用

将 `openclaw.tools.sessions_spawn` 改为通过 OpenClaw 工具系统调用。

**修改位置**: `roundtable_engine_v2.py` 第 385-420 行

**修改前**:
```python
from openclaw.tools import sessions_spawn
session_result = await sessions_spawn(**spawn_kwargs)
```

**修改后**:
需要通过 OpenClaw 的 `sessions_spawn` 工具直接调用，而不是在 Python 代码中导入。

### 方案 C: 使用备用执行路径

在 `openclaw` 不可用时，降级为直接调用 LLM API。

**伪代码**:
```python
try:
    from openclaw.tools import sessions_spawn
    # 原有逻辑
except ModuleNotFoundError:
    # 降级方案：直接调用 LLM
    from some_llm_client import call_llm
    content = await call_llm(prompt, model=model_id)
```

---

## 📋 修复步骤

### 立即可行的方案

1. **通过消息触发 RoundTable**（不需要改代码）
   - 在飞书/企业微信中发送：`RoundTable 讨论一下：xxx`
   - OpenClaw 会自动处理，`openclaw.tools` 会可用

2. **修复代码**（需要开发）
   ```bash
   cd ~/.openclaw-autoclaw/skills/roundtable-skill
   # 编辑 roundtable_engine_v2.py
   # 添加降级逻辑
   ```

---

## 🎯 建议

1. **短期**: 通过消息系统触发 RoundTable（方案 A）
2. **中期**: 添加降级逻辑，支持独立运行（方案 C）
3. **长期**: 重构为纯工具调用，不依赖 `openclaw` 模块导入

---

## 📞 联系人

如有疑问，请联系：
- 开发者：Krislu
- 排查人：旺财 (财经顾问) 🐕
