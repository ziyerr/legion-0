---
id: tactic-1eed7b
domain: architecture
score: 0
created: 2026-03-31
last_cited: never
source: L1-赤龙军团
summary: 浏览器自动化方案选型用四维适用性矩阵：精度需求×UI变频×当前稳定度×降级成本
---

评估 Playwright→Computer Use 等自动化迁移时，逐目标打分：(1) API精度需求高（如签名计算、精确JS注入）→不适合视觉驱动；(2) UI变动频繁且选择器脆弱→高度适合视觉驱动；(3) 当前方案已稳定运行→仅作降级备选，不主动迁移；(4) 需同时评估延迟容忍度，Computer Use 每步截图往返有固有延迟，高频交互场景不适用。
