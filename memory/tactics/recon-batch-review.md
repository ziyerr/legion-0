---
id: recon-batch-review
domain: collaboration
type: recon
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: CC的SendMessage是异步单向的,配对制假设的实时通信不成立,改为批次审查
keywords: [配对, 审查, 批次, 里程碑, SendMessage, 异步, 通信模型]
---

## 问题背景
agent-team SKILL.md 的配对制假设审查者能"等待"实现者通知并实时反馈。但 CC 的 subagent SendMessage 是异步单向的——审查者无法阻塞等待。

## 调研过程
CC 源码确认: `SendMessageTool.ts:handleMessage()` 写入 recipient inbox，无回调通知机制。
`useInboxPoller` 是 1 秒轮询，不是事件驱动。审查者要么空转消耗上下文，要么退出。

## 关键发现
1. SendMessage 是"写信"不是"打电话"——没有实时交互
2. 审查者无法"订阅"实现者的产出——只能轮询或由指挥官中转
3. 配对制的"写一个查一个"在 CC 架构下是虚假并行

## 推荐方案
M 级: 批次审查——实现者写完所有文件 -> 指挥官启动审查者 -> 审查者逐文件 review
L/XL 级: 里程碑审查——每完成一个域/模块 -> 指挥官启动审查者
所有协调经过指挥官中转，不假设点对点实时通信。
