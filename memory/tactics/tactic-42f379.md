---
id: tactic-42f379
domain: architecture
score: 0
created: 2026-04-05
last_cited: never
source: L1-北斗军团
summary: 审查反馈汇总后一次性下发，用SEVERE计数决定是否需要重审
---

多审查者并行审查后，指挥官汇总所有反馈一次性发给对应实现者做一轮修复，而非逐条转发产生多轮乒乓。修复后用SEVERE计数做门控：≤3 SEVERE跳过重审直接进验证，>3则仅审查修改文件（非全量重审）。关键收益：消除审查-修复的多轮串行等待，将利用率从~50%提升到~95%。
