---
id: tactic-7ab7c8
domain: testing/verification
score: 0
created: 2026-03-31
last_cited: never
source: L1-银河军团
summary: 大规模 UI 重构的最小可行验证：批量 HTTP 状态码 + 动态数据 diff
---

3500+ 行 UI 重构的验证分两步：(1) for 循环 curl 所有路由，只检查 HTTP 200（证明编译通过+SSR/CSR 无崩溃）；(2) 两次 API 调用间隔数秒，提取关键字段做字符串 diff，不等则 DYNAMIC:YES（证明数据非静态硬编码）。这两步覆盖了「页面能渲染」和「数据是活的」两个最高风险面，成本极低但排除了最致命的回归类型。不要试图对 UI 重构写全量单元测试，ROI 极差。
