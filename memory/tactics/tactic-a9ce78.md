---
id: tactic-a9ce78
domain: architecture
score: 0
created: 2026-03-31
last_cited: never
source: L1-破晓军团
summary: 大规模架构升级按依赖层自底向上组织变更：基础设施→核心模块→编排层→配置，而非按功能特性切分
---

本次 34 文件重构按 5 层推进：①基础设施(Mixin/Skills/ORM 10文件) → ②Agent核心升级(7文件) → ③编排层(3文件) → ④记忆/成长系统(3文件) → ⑤配置文件(11文件)。每层完成后上层才能引用，避免循环依赖和前向引用。如果按功能切分（如先做发现模块全栈、再做内容模块全栈），会导致共享 Mixin 被反复修改、Agent 间接口不稳定。实战验证：4 个 teammate 并行时按层切分可以减少文件冲突，按功能切分则 base.py/registry.py 会成为热点冲突文件。
