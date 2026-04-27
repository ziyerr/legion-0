---
id: impl-commander-slim
domain: architecture
type: implementation
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: Commander从路由器瘦身为纯大脑(删1939行-47%),通信层交给CC原生
keywords: [commander, 瘦身, 路由, 删除, CC, 纯大脑, 纠察, 战评]
---

## 实施内容
将 legion-commander.py 从 4053→2114 行，删除所有 CC 已替代的功能。

## 删除的功能（CC 替代）
- 消息路由 route_messages/deliver_to (~400行) → CC SendMessage P2P
- 文件锁 handle_lock_request/release/gc_locks (~120行) → CC mtime 乐观并发
- 任务板 handle_task_update (~50行) → CC TaskCreate/Update/List
- ACK 追踪 check_ack_timeouts (~80行) → CC P2P 投递更可靠
- 扩编限流 check_spawn_allowed (~60行) → 协议层约束

## 保留的功能（CC 无替代）
纠察官 inspector_patrol、战评官 after_action_review、度量 record_metric、
observations.jsonl 收集、gc_dead_commanders、gc_broadcast、gc_inboxes、
commissar_broadcast、心跳 write_heartbeat

## 同步瘦身的文件
- post-tool-use.sh: 538→359 (删邮箱扫描)
- pre-tool-use.sh: 294→112 (删文件锁)
- stop-hook.sh: 155→122 (删旧 inbox 检查)
- legion-mailbox.sh: 679→27 (废弃壳)
- legion-watcher.sh: 287→4 (废弃壳)
- legion-env.sh: 71→5 (废弃壳)

## 验证结果
语法 5/5 PASS，10 个函数确认删除，11 个独有函数确认保留。
