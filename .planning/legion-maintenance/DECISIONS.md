# Legion System Maintenance Decisions

## DEC-001：发送必须支持 legion_hash 消歧

- 决策：`legion_api.send_to_commander` 增加 `legion_hash` 参数。
- 理由：真实扫描发现 `L1`、`L1-ip-creator-幻影军团`、`L1-惊雷军团`、`L1-猎鹰军团` 等 commander_id 在多个项目重复。
- 影响：跨项目通讯不再依赖 commander_id 全局唯一。

## DEC-002：mixed inbox 必须双写

- 决策：对 mixed commander 同时写新版 inbox、旧版 team inbox、`mixed/inbox/<commander>.jsonl`。
- 理由：ip-creator 等项目的 L1/L2 主要通过 Legion Core mixed inbox 通讯；只写 classic inbox 会出现“投递成功但 L1 不处理”的假象。

## DEC-003：AICTO 维护军团系统本体

- 决策：新增 `legion_system_maintenance` 工具。
- 理由：长期 outbox/events/memory 无法处理是系统问题，不是单个项目交付问题；必须由 AICTO 作为 CTO 做持续治理。
- 影响：AICTO 能扫描、摘要、写记忆、跟进活动/阻塞任务。

## DEC-004：ACK 用事实回执判定，不用 heartbeat

- 决策：`ack_status` 只把 `directive_id`、`in_reply_to`、`AICTO-REPORT` 或包含原 message/directive 的记录视为 ACK。
- 理由：真实测试中 L1 可能持续 heartbeat，但 heartbeat 不能证明处理了 CTO 指令。
- 影响：未 ACK 的 CTO 指令会进入 `pending/overdue`，可由 `escalate_overdue_acks` 升级。
