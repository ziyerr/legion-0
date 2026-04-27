---
id: review-thread-safety-pattern
domain: architecture
type: review
score: 0
created: 2026-04-04
source: eval-review (sonnet)
project: novel-to-video-standalone
summary: ThreadPoolExecutor线程中的全局变量和read-modify-write必须加threading.Lock
keywords: [线程安全, ThreadPoolExecutor, Lock, 全局变量, read-modify-write, 并发]
---

## 问题模式
当 Python 代码使用 `ThreadPoolExecutor` 将函数提交到线程池时，被提交的函数如果读写全局 dict/set 或做 JSON 文件的 read-modify-write，会产生竞态。

## 检测方法
1. 找到 `ThreadPoolExecutor.submit(func, ...)` 的所有 `func`
2. 追踪 func 调用链中所有 `global` 声明和文件读写
3. 检查这些访问点是否有 `threading.Lock` 保护

## 推荐修复
```python
_lock = threading.Lock()
def func_in_thread():
    with _lock:
        data = read_json(path)
        data[key] += 1
        write_json(path, data)
```
