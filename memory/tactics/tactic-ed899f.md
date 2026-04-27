---
id: tactic-ed899f
domain: architecture
score: 0
created: 2026-03-31
last_cited: never
source: L1-鲲鹏军团
summary: 并行修复多个外部集成时，按故障模式分组而非按优先级分组
---

将故障平台按修复手段分类（API可修 / HTTP可刮 / DOM需解析 / 需浏览器登录），同类分配给同一个agent。同类修复共享调试模式——api-fixer修好google_trends的fallback模式后直接复用到youtube_api，http-fixer修好producthunt的RSS思路后直接迁移到viewstats。按优先级混分则每个agent都要切换上下文，效率显著更低。
