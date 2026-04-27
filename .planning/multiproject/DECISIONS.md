# AICTO 多项目军团管理决策

## D-MP-1 `[LOCKED]` 默认禁止跨项目借兵
原因：AICTO 的职责是管理多个项目的军团。若默认从全局在线军团池随机挑选，会造成上下文污染、责任不清和项目间资源串线。

## D-MP-2 `[LOCKED]` 项目归属匹配优先使用名称标准化
原因：当前 Legion registry 的项目名与 PM Project.name 不一定完全一致，但存在稳定别名关系，例如 `AI HR - OPC 团队成员` ↔ `AIHR`、`AI CTO - 程小远` ↔ `AICTO`。

## D-MP-3 `[LOCKED]` 组合态工具只读
原因：读取 PM DB、Legion registry/inbox 足够支撑管理判断；启动/停止军团、改 Hermes profile 属于共享状态变更，必须另走明确任务。

## D-MP-4 `[LOCKED]` 跨项目借兵必须显式标记
原因：临时借兵有现实价值，但必须在 assignment 与 mailbox `cto_context.project_route` 中留证，便于追责和复盘。
