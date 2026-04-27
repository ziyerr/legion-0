---
id: tactic-c56068
domain: security/api
score: 0
created: 2026-04-01
last_cited: never
source: L1-昆仑��团
summary: 金融端点安全三板斧：值域校验 → 归属校验 → 原子扣款
---

涉及金额/积分/配额的 API 端点，三步缺一不可：1) 值域校验：金额 > 0、精度合法、不超上限；2) 归属校验：操作者确实拥有该资源（不能用 A 的余额给 B 转账）；3) 原子扣款：UPDATE ... WHERE balance >= amount RETURNING balance，一条 SQL 完成检查+扣减，不拆为 SELECT+UPDATE（竞态窗口）。三步顺序不可颠倒——先验值域（最便宜），再验归属（需查DB），最后原子写入（最贵）。
