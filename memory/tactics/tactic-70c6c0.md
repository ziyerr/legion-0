---
id: tactic-70c6c0
domain: architecture
score: 0
created: 2026-04-03
last_cited: never
source: L1-暴风军团
summary: 多模型协作需显式冲突仲裁协议：发现分歧→交叉确认→指挥官仲裁，禁止默认采信'主场模型'
---

当不同 AI 模型（如 Claude 红队 vs Codex 红队）对同一代码给出矛盾评估时，不能因为'我们用的是 Claude'就自动采信 Claude 的结论。正确流程：(1) critical/major 发现必须让对方模型交叉确认或明确反驳 (2) 双方分歧时由人类指挥官仲裁 (3) 一方发现另一方全部验证者都漏掉的问题 → 标记为高价值发现，说明该模型在该维度有认知优势。本质是避免'确认偏误的模型级放大'。
