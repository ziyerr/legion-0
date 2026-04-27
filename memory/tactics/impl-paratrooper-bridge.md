---
id: impl-paratrooper-bridge
domain: collaboration
type: implementation
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: Codex伞兵通过_bridge_to_inbox将结果直写CC team inbox,全军可见
keywords: [codex, 伞兵, 桥接, inbox, GPT, 跨模型, bridge]
---

## 实施内容
codex-team.sh 新增 `_bridge_to_inbox()` 函数，4 个命令（review/adversarial/rescue/second-opinion）执行后自动将结果写入 CC team leader 的 inbox。

## 技术细节
- codex exec 输出保存到文件 → 读取结果 → flock + read-modify-write 写入 inbox
- 消息 `from: "codex-{task_type}"`, `color: "yellow"` 区分来源
- 依赖 `CLAUDE_CODE_TEAM_NAME` 环境变量，未设置时静默跳过（向后兼容）

## 效果
伞兵从孤立 stdout → 融入 CC 消息流。useInboxPoller 1 秒内拾取，所有 teammate 可见。
