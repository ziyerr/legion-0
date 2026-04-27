---
id: tactic-d0ffec
domain: architecture
score: 0
created: 2026-04-01
last_cited: never
source: L1-麒麟军团
summary: 批量任务进度监控必须用eligible count做分母，不能用total count
---

批处理任务中，数据集常包含不需要处理的项（如无旁白的静默镜头、无需翻译的纯代码行）。进度统计用 total 做分母会制造虚假失败率（本例 19/47=40% vs 19/19=100%）。正确做法：先筛选 eligible 子集（has_text/needs_processing），再用 eligible count 做分母。诊断脚本应同时输出三个数：total / eligible / completed，一眼区分'跳过'和'失败'。
