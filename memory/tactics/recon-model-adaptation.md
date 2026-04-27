---
id: recon-model-adaptation
domain: collaboration
type: recon
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: 只读agent(参谋/审查)用Sonnet就够,写代码agent(实现/验证)必须Opus,节省API争抢
keywords: [sonnet, opus, model, 适配, rate-limit, API, 并发, agent]
---

## 问题背景
"全员 Opus" 铁律导致 API rate limit 成为规模化瓶颈。XL 级 13 agent 全 Opus 远超配额。

## 调研过程
岗位能力测评: 7 个岗位实战拉练，sonnet 岗位（explore/review/plan）平均 92.3 分，opus 岗位平均 96.3 分。差距仅 4 分但 sonnet 省一半 API 消耗。
CC 源码确认: Agent 工具的 model 参数支持 sonnet/opus/haiku。

## 关键发现
1. 参谋(explore)、审查者(review)、架构师(plan) 只做读和分析，不需要 Opus 级编码能力
2. 实现者(implement)、验证者(verify) 需要写代码/运行命令，必须 Opus
3. Sonnet 岗位平均 92.3 分 vs Opus 96.3 分——ROI 极高（省 50% API，只损失 4 分）

## 推荐方案
agent frontmatter 中: explore/review/plan 设 `model: sonnet`，implement/verify 设 `model: opus`。
CLAUDE.md 铁律从"全员 Opus"改为"模型适配"。
