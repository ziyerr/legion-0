---
id: recon-cross-project-comm
domain: collaboration
type: recon
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: CC SendMessage不支持跨team,但可直写目标inbox文件实现跨项目通信
keywords: [跨项目, xmsg, inbox, 直写, 名册, directory.json, 首席L1]
---

## 问题背景
CC SendMessage 的 `handleMessage()` 固定用 `getTeamName()`——只能发给同 team 成员。不同项目在不同 team 中，无法原生跨项目通信。

## 调研过程
分析 CC inbox 路径: `~/.claude/teams/{teamName}/inboxes/{agentName}.json`
验证: `writeToMailbox(recipientName, message, teamName)` 技术上接受 teamName 参数，但 SendMessage 工具不暴露。

## 关键发现
1. 绕过 SendMessage，直接文件操作写入目标项目的 inbox——useInboxPoller 照样拾取
2. 全局军团名册 `~/.claude/legion/directory.json` 支持按项目名查找
3. 多 L1 时发给首席 L1（registry 第一个 commanding 的），不广播避免重复执行
4. 消息携带 `reply_to` 回信地址，支持双向通信

## 推荐方案
`legion.sh xmsg <项目名> "消息"` — 查名册 -> 找首席 L1 -> 直写 inbox -> 1 秒内拾取。
