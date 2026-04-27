# Legion System Maintenance Requirements

## 背景

用户明确要求 AICTO 不只管理项目开发，还要维护军团体系本身，解决长期数据无法有效处理的问题，用 AICTO 弥补军团系统短板。

## 需求

1. AICTO 必须能扫描真实 `~/.claude/legion`，不是只读 PM 项目表。
2. AICTO 必须识别重复 `commander_id`，多项目通讯必须支持 `legion_hash` 消歧。
3. AICTO 必须识别长期数据治理问题：outbox/events 多、memory 少、blocked/running/planned 任务堆积。
4. AICTO 必须能把军团系统扫描结果写入独立 CTO 记忆。
5. AICTO 必须能向活动/阻塞任务责任 L1 发起可回执跟进，并要求事实证据。
6. AICTO 必须能追踪 CTO 指令是否被 L1 ACK/AICTO-REPORT 回执，超时未回执必须可升级。

## 验收

- `send_to_commander` 支持 `legion_hash`。
- mixed L1 指挥官能收到 mixed inbox JSONL。
- `legion_system_maintenance(action=scan)` 返回真实军团健康态。
- `legion_system_maintenance(action=record_summary)` 写入 `cto_memory`。
- 真实跟进指令至少投递到正在开发中的项目 L1。
- `legion_system_maintenance(action=ack_status)` 能识别已 ACK、pending、overdue。
- `legion_system_maintenance(action=escalate_overdue_acks)` 默认 dry-run，并可真实发送升级指令。
