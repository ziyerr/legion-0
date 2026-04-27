---
id: recon-cc-collaboration
domain: architecture
type: recon
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: Claude Code是操作系统,军团是应用层,不重造CC已有的通信/锁/任务管理
keywords: [claude-code, CC, SendMessage, useInboxPoller, teammate, swarm, 协作, 通信]
---

## 问题背景
军团体系 56% 代码(2341行)在重造 CC 已内置的能力（消息路由、文件锁、任务板）。

## 调研过程
深入阅读 CC 源码 `/Users/feijun/claude-code-copy/src/`:
- `utils/teammateMailbox.ts`: 文件级 inbox，proper-lockfile，read-after-lock
- `hooks/useInboxPoller.ts`: 1s 轮询，idle 立即提交，busy 排队
- `tools/SendMessageTool`: P2P 直写 recipient inbox，无中央路由
- `utils/swarm/backends/PaneBackendExecutor.ts`: tmux teammate 带 --agent-id --team-name

## 关键发现
1. CC 没有 Commander 路由器——全部 P2P 直写，零延迟
2. CC 用 `proper-lockfile`（独立 .lock 文件），不是 flock
3. CC inbox 路径: `~/.claude/teams/{team}/inboxes/{agent}.json`（全局，不分项目）
4. CC 的 `TEAM_LEAD_NAME = 'team-lead'` 是角色信箱（但只支持单 leader）
5. CC 的 `ENABLE_AGENT_SWARMS` 通过 `--agent-teams` flag 或环境变量启用

## 推荐方案
CC = 操作系统（通信/锁/任务/进程管理），军团 = 应用层（决策/审计/学习/方法论）。
Commander 从"路由器+大脑"瘦身为"纯大脑"（纠察/战评/度量）。
新启动的 teammate 通过 `CLAUDE_CODE_TEAM_NAME` + `CLAUDE_CODE_AGENT_NAME` 注册到 CC team。
