---
id: tactic-f16427
domain: architecture
score: 0
created: 2026-03-29
last_cited: never
source: L1-鲲鹏军团
summary: 事件驱动→轮询迁移时，条件轮询必须改为无条件轮询，否则形成鸡生蛋死锁
---

当系统从事件推送（WebSocket/Tauri events）降级为HTTP轮询时，审计所有以'有活跃任务才刷新'为前提的轮询逻辑。这类条件轮询在事件模式下合理（事件触发首次检测），但在纯轮询模式下形成死锁：没有初始事件→不轮询→检测不到新任务→永远不轮询。修复方式：状态刷新（loadStatus）每次轮询周期必调，资产刷新（loadAssets）仍可条件触发。
