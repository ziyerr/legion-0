---
id: tactic-60acf9
domain: architecture/spec-driven
score: 0
created: 2026-04-05
last_cited: never
source: L1-烈焰军团
summary: DB migration 改名/删列时，spec 必须附带旧列名的全局 grep 扫描结果作为 blast radius 清单
---

migration 008 将 bounty_show_up → onsite_bounty 并删除 bounty_hire，但 spec 只列出了部分引用点（B1-B4），实现者照 spec 字面执行，遗漏了 confirm-hire 路径对旧列名的引用。修复：spec 设计阶段必须运行 `grep -rn 'old_column_name' apps/` 并将所有命中行逐一列入 spec，不能假设实现者会自行发现 spec 外的引用。这比 '实现者应该更仔细' 的期望更可靠。
