---
id: product-agent-dashboard
domain: collaboration
type: product
score: 0
created: 2026-04-04
source: eval-counselor (opus)
project: novel-to-video-standalone
summary: AI agent执行监控面板的标准设计: 全局态势+活跃列表+团队动态+卡死检测
keywords: [监控, 面板, 仪表盘, agent, 卡死检测, 进度, 可视化]
---

## 设计模式
AI agent 团队执行监控面板的四个核心功能:

1. **全局态势卡片**: 活跃项目数/运行中/完成/失败 -- 一眼看全局
2. **活跃任务列表**: 每个任务的阶段+进度条+耗时+最后活跃 -- 点击展开详情
3. **团队动态流**: 实时协作消息,按角色颜色区分 -- 类聊天记录
4. **卡死检测**: running>=5分钟橙色警告, >=10分钟红色 -- 支持取消/重试

## 数据源策略
优先用已有 API,评估覆盖度后只补缺口。典型覆盖度 80-90%,只需新增 1 个聚合 endpoint。

## Scope 决策标准
做: 实时监控、一键干预（取消/重试）
不做: 历史甘特图、成本报表、DAG 拓扑编辑（独立需求,不在监控范围）
