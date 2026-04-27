---
id: rootcause-hook-python-spawn
domain: architecture
type: rootcause
score: 0
created: 2026-04-04
source: eval-sniper (opus)
project: novel-to-video-standalone
summary: PostToolUse hook每次调用启动3-9个python3子进程,N agent并发时30-90个进程争CPU
keywords: [hook, python3, 子进程, 性能, 延迟, 并发, 合并, 单进程]
---

## 五个为什么
1. 为什么 hook 有延迟? -> 每次启动多个 python3 -c 子进程
2. 为什么需要多个子进程? -> JSON 解析/文件操作/时间计算各自独立 spawn
3. 为什么不合并? -> 增量叠加开发,没人做架构整合（渐进式腐化）
4. 为什么用 bash+python 混合? -> hook 协议要求 bash 入口,但可以 exec python3 跳转
5. 为什么并发时特别严重? -> 10 agent x 9 python3 = 90 个进程争 CPU

## 结构性根因
"bash 壳 + N 个独立 python3 一次性子进程" 的架构模式

## 定点清除方案
将 post-tool-use.sh 改为: `exec python3 ~/.claude/scripts/hooks/post_tool_use.py`
所有逻辑在单个 python3 进程内以函数调用完成。

## 防复发
hook 文件头部加约束注释: `# CONSTRAINT: max 1 python3 process per invocation`
