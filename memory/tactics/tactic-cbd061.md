---
id: tactic-cbd061
domain: python
score: 0
created: 2026-04-05
last_cited: never
source: L1-暴风军团
summary: 破坏性清理必须先备份再删除，不可先删后写
---

rmtree/rm -rf 清理目录后再写入新内容，如果写入失败则数据全丢。正确模式：shutil.move 将旧目录移到 .bak 位置 → 写入新内容 → 验证成功后删除 .bak。同理适用于数据库迁移、配置文件替换等场景。额外收益：.bak 目录自然形成回滚点。
