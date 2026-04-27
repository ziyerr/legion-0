---
id: tactic-2d43e1
domain: architecture
score: 0
created: 2026-04-10
last_cited: never
source: L1-长歌军团
summary: 验证阶段被限额/中断打断后，必须完整重读所有变更文件再验收，禁止凭中断前的部分记忆签收
---

本次 Commander 在最终验收 Read webhook route.ts 时触发限额中断，重新登录后直接宣布 5 个修复全部通过并列出行号，但无法确认是否重新读取了文件。正确做法：限额恢复后必须重新 Read 所有变更文件（本例 3 个），逐条对照审查清单的修复项确认落地，用实际 Read 输出作为验收证据，不能用上下文缓存或'我之前读过'替代实际验证。这与 verification-before-completion 原则一致：evidence before assertions。
