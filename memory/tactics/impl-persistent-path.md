---
id: impl-persistent-path
domain: architecture
type: implementation
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: LEGION_DIR从/tmp/迁移到~/.claude/legion/,军团数据重启不丢失
keywords: [持久化, /tmp, ~/.claude, 重启, 迁移, LEGION_DIR, REGISTRY_DIR]
---

## 实施内容
7 处修改跨 5 个文件，将所有 `/tmp/claude-legion/` 引用替换为 `$HOME/.claude/legion/`。

## 变更点
1. legion.sh:45 -- REGISTRY_DIR
2. legion.sh:2323 -- Python heredoc 内嵌路径
3. legion-commander.py:28 -- 默认 LEGION_DIR
4-6. 3 个 hook 的默认 LEGION_DIR

## 注意事项
- 已运行的军团环境变量已固化，需等解散后新建才生效
- Python 代码中用 `Path.home() / ".claude" / "legion"` 而非 `$HOME`（Python 不展开 shell 变量）
