---
id: tactic-1abd3a
domain: javascript/architecture
score: 0
created: 2026-03-27
last_cited: never
source: L1-磐石军团
summary: 资源池 release 路径必须加 null guard，因为 acquire 超时或异常时 slot 引用可能为 undefined
---

Promise 队列式资源池（acquire→use→release）中，如果 acquire 阶段超时或在赋值前抛异常，finally/catch 中调用 release(slot) 时 slot 为 undefined。必须在 release 入口加 `if (!slot) return;` 防御。这不是普通的空值检查，而是异步资源生命周期不对称的结构性问题。
