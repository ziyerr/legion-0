---
id: tactic-c57407
domain: architecture
score: 0
created: 2026-04-10
last_cited: never
source: L1-烽火军团
summary: 文件重组时必须同步更新所有引用路径，否则产生静默失效
---

将 degradation-policy 从 .claude/skills/ 移入 .claude/thought-weapons/ 后，CLAUDE.md 中的旧路径引用未同步更新导致指向不存在的文件。重组操作的标准流程：1) grep 全局搜索旧路径的所有引用 2) 批量替换为新路径 3) 验证所有引用目标文件存在。这比'移动文件+事后想起来改引用'可靠得多。
