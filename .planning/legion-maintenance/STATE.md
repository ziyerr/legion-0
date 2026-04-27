# Legion System Maintenance State

更新时间：2026-04-27

## 已完成

- `legion_api.send_to_commander` 增加 `legion_hash` 项目级消歧。
- mixed commander 增加 `mixed/inbox/<commander>.jsonl` 双写。
- `legion_command_center` 支持传入 `legion_hash`。
- 新增 `legion_system_maintenance`，支持 `scan`、`follow_up_active`、`record_summary`。
- `legion_system_maintenance` 继续补全 `ack_status` 与 `escalate_overdue_acks`，区分真实 ACK 和普通 heartbeat。
- 已真实向 4 个在线/活动 L1 投递 AICTO 跟进指令：`ip-creator`、`CartCast`、`agent-sdk-research`、`feijun`。
- 已写入军团长期数据治理总结记忆：`mem-70e1e164eaf8`。

## 真实扫描结果

- 项目/军团目录：31。
- 在线 commanders：25。
- active commanders：43。
- running/blocked/failed/planned attention tasks：23。
- outbox messages：2560。
- inbox messages：857。
- mixed memory records：51。
- duplicate commander groups：6。
- findings：12。

## 当前观察

- 真实投递均成功，tmux 通知均成功。
- `ip-creator` mixed L1 已写入 `mixed/inbox/l1-ip-creator-幻影军团.jsonl`。
- ACK 追踪已复扫：4 条 CTO 指令全部收到 L1 回执，`ack_status` summary = `{"acked": 4}`。
- 已写入 ACK 闭环记忆：`mem-976c527c46ee`。
- 结论：真实通讯链路已闭环；后续需要把 ACK 扫描纳入定时维护。

## ACK 追踪进展

- 已实现：从 `cto_memory` 的 `cto-directive` 记录恢复待回执指令。
- 已实现：读取 classic `team-*/outbox.jsonl` 与 mixed inbox，按 `directive_id` / `in_reply_to` / `AICTO-REPORT` 判断 ACK。
- 已实现：超时未 ACK 可生成或发送 `directive_type=escalate` 升级提醒。
- 已修复：无时区 Legion 时间戳按 UTC 解析，避免把真实 ACK 误判为超时。
- 已修复：排除 `from=AICTO-CTO` 的原始指令，避免把自己发出的消息误算为 ACK。

## 验证

- 专项测试 `test_cto_operating_model`：9/9 OK。
- 全量测试 `python -m unittest discover -p 'test_*.py' -v`：122/122 OK。
- Hermes 注册 smoke：22 tools，包含 `legion_system_maintenance` 和 `legion_command_center`。
