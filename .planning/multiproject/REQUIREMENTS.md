# AICTO 多项目军团管理需求

## 目标
AICTO 必须能同时管理多个项目的开发军团，而不是只把任务派给任意在线军团。

## 需求
- R-MP-1：提供项目 × 军团组合态看板，覆盖 PM 项目、Legion 项目、在线 commander、积压派单、stale 派单、BLOCKING review。
- R-MP-2：dispatch 默认必须做项目归属过滤，禁止把 A 项目任务派给 B 项目军团。
- R-MP-3：允许显式 `allow_cross_project_borrow=true` 跨项目借兵，但返回结果必须标记 `cross_project_borrowed=true`。
- R-MP-4：项目归属匹配必须支持 PM 项目名与 legion 项目名的标准化匹配，例如 `AI CTO - 程小远` ↔ `AICTO`。
- R-MP-5：组合态工具只读，不启动/停止军团，不写 PM 表，不改 Hermes profile。
- R-MP-6：返回结果必须给出健康状态与推荐动作，能指导 AICTO 下一步是补 ADR、处理 BLOCKING、恢复军团还是新建军团。

## 验收
- dispatch 遇到无本项目军团时默认失败且不调用 `send_to_commander`。
- dispatch 显式跨项目借兵时可以派出，并在 assignment 与 cto_context 中保留归属信息。
- `legion_portfolio_status` 能返回每个项目的 `health / alerts / recommended_actions / legions`。
