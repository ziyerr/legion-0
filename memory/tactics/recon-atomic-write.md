---
id: recon-atomic-write
domain: architecture
type: recon
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: write_json用temp+fsync+rename原子写入,不用flock truncate-then-lock反模式
keywords: [atomic, write, rename, fsync, flock, truncate, 竞态, 并发, write_json]
---

## 问题背景
`write_json` 的 `open("w")` 在 `flock` 之前已经 truncate 文件，并发写入导致数据丢失。

## 调研过程
分析 CC 源码 `utils/file.ts:362`: `writeFileSyncAndFlush_DEPRECATED` 使用 temp+rename 模式。
对比 POSIX 语义: `os.rename` 在同一文件系统上是原子操作（APFS 确认）。

## 关键发现
1. `open("w") + flock` 反模式: truncate 发生在 flock 之前，窗口期数据丢失
2. `temp + fsync + rename` 正确模式: reader 要么看到旧文件要么看到新文件，永远不会半写
3. tmp 路径需要加 PID + thread_id 防多线程冲突: `path.with_suffix(f'.tmp.{pid}.{tid}')`
4. rename 后 read_json 不再需要 flock（原子替换保证一致性）

## 推荐方案
```python
def write_json(path, data):
    tmp_path = path.with_suffix(f'.tmp.{os.getpid()}.{threading.get_ident()}')
    with open(tmp_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.rename(str(tmp_path), str(path))
```
