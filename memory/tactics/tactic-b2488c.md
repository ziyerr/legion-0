---
id: tactic-b2488c
domain: architecture/concurrency
score: 0
created: 2026-03-26
last_cited: never
source: L1-苍穹军团
summary: 实时事件流(SSE/WebSocket)中嵌入金融写操作时，必须用 DB UNIQUE 约束做幂等保证，不能仅���应用层检查
---

SSE/WebSocket 消息流天然存在重发（网络重连、客户端重试）。如果消息处理函数中包含写操作（转账、扣费、状态变更），仅靠应用层 if-not-exists 检查会在并发下产生竞态。正确做法：DB 层 UNIQUE 约束（transaction_id + idempotency_key），写操作用 INSERT ... ON CONFLICT DO NOTHING，让数据库保证幂等。应用层检查作为快速路径优化，不作为正确性保证。
