---
id: tactic-80f12f
domain: bash
score: 0
created: 2026-04-01
last_cited: never
source: L1-昆仑军团
summary: Bash `local` 只能在函数体内使用，case 分支内联逻辑时必须去掉 local 或包一层函数
---

将独立函数的逻辑内联到脚本顶层 case 分支时，原函数中的 `local var=...` 会报 'local: can only be used in a function'。修复方式二选一：(1) 把 case 分支体包进一个函数再调用；(2) 去掉 local，改用子 shell `(...)` 隔离变量作用域。集成测试必须覆盖 CLI 入口路径，不能只测底层函数。
