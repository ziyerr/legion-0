---
id: tactic-f43fa7
domain: python
score: 0
created: 2026-04-08
last_cited: never
source: L1-凤凰军团
summary: LLM生成的正则表达式必须经过语法校验+ReDoS样本检测后才能执行
---

当LLM（如剧本结构分析）输出正则表达式供代码动态编译执行时，必须做两层防护：1) re.compile() 捕获语法错误；2) 用短重复字符样本（如 'a'*50）实测匹配耗时，超过阈值（200ms）判定为灾难性回溯并拒绝。仅做语法校验不够，合法正则仍可能触发指数级回溯。此外，优先用 re.finditer() 替代 re.split()，因为 split 遇到捕获组会将匹配文本插入结果列表，导致下游索引错乱——LLM 生成的正则几乎必然包含捕获组。
