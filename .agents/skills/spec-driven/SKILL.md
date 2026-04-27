---
name: spec-driven
description: Spec驱动开发。中型及以上任务必须维护 .planning/ 目录作为团队共享真相源，包含需求、决策、状态、阶段计划。
---

# Spec 驱动开发

## Overview

代码是决策的产物，不是起点。先把需求和决策写清楚，再动手。

## .planning/ 目录结构

```
.planning/
├── PROJECT.md        # 项目愿景（一次写，全员读）
├── REQUIREMENTS.md   # 需求列表（每个任务更新）
├── DECISIONS.md      # 已锁定的决策（LOCKED 标记不可推翻）
├── STATE.md          # 当前进度/阻塞（实时更新）
├── features.json     # 功能追踪（JSON 格式，Anthropic 推荐）
└── phases/
    ├── 01-CONTEXT.md # 阶段讨论结果
    ├── 01-PLAN.md    # 阶段执行计划
    └── 01-VERIFY.md  # 验收结果
```

### features.json 格式（Anthropic 最佳实践：JSON > Markdown）

Anthropic 研究发现模型"不太会不恰当地修改 JSON 文件"，比 Markdown 更可靠。用于追踪功能点的实现状态：

```json
{
  "task": "任务描述",
  "created": "2026-03-29",
  "features": [
    {
      "id": "F001",
      "name": "功能名称",
      "status": "pending|in_progress|done|failed",
      "assignee": "teammate 名称",
      "files": ["file1.ts", "file2.rs"],
      "verified": false,
      "notes": ""
    }
  ]
}
```

**规则：**
- 状态只能前进（pending → in_progress → done），不能删除条目
- 失败的标记 `"status": "failed"` 并写 notes，不要删掉重来
- 每个 teammate 只改自己 assignee 的条目

## 规则

1. **接到任务后** → 先写/更新 REQUIREMENTS.md，逐条列出需求点
2. **讨论阶段的决策** → 写入 DECISIONS.md 并标记 `[LOCKED]`，执行阶段不可推翻
3. **teammate 收到任务时** → 必须先读 .planning/ 下的相关文件，不依赖口头描述
4. **每完成一个 task** → 更新 STATE.md（当前进度、已完成、待完成）
5. **对话长度超过 50% 上下文** → /compact 后读 STATE.md 恢复认知

## 什么时候用

- 中型及以上任务（改 5+ 文件、跨前后端、需要多 teammate 协作）
- 小任务（改几行/修 bug）可以跳过，直接执行

## Gotchas

1. **LOCKED 决策不可在执行阶段推翻** — 如果发现决策有问题，必须回到讨论阶段重新锁定
2. **STATE.md 是上下文保鲜的关键** — 对话被压缩后，STATE.md 是你恢复认知的唯一途径
3. **不要把重要信息只留在对话里** — 写到文件中，对话会被压缩但文件不会
