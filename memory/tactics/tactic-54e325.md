---
id: tactic-54e325
domain: python
score: 0
created: 2026-04-02
last_cited: never
source: L1-天狼军团
summary: FastAPI POST 端点即使所有字段可选，body 仍不能为 null，必须传 {} 并带 Content-Type: application/json
---

FastAPI 用 Pydantic model 做 body 解析时，即使 model 所有字段都有默认值，不传 body 会触发 422 'Field required'。正确做法：curl -X POST -H 'Content-Type: application/json' -d '{}'。指挥官第二次调用因缺 body 被拒，第三次加 {} 才成功。这在 CLI 脚本和自动化中是高频陷阱。
