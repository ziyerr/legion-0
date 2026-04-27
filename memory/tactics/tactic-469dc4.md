---
id: tactic-469dc4
domain: architecture
score: 0
created: 2026-03-30
last_cited: never
source: L1-凤凰军团
summary: 双路侦察报告回传后，先用结构化决策矩阵收敛关键决策点，再进入 spec 设计，避免分析瘫痪
---

L1-凤凰军团在并行双路侦察（前端+后端）完成后，进入 spec 设计阶段时 churn 了 4m42s。原因是两份侦察报告信息量大但未被收敛，直接进入 spec 设计导致决策空间爆炸。正确做法：侦察报告回传后，先用 3-5 条 bullet 提炼「关键约束 + 可复用资产 + 必须新建的模块」，形成决策矩阵，再进入 spec 阶段。这比直接带着全量侦察数据写 spec 效率高得多。
