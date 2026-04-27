---
id: security-state-bypass
domain: debugging
type: security
score: 0
created: 2026-04-04
source: eval-verify (opus)
project: novel-to-video-standalone
summary: 文件存在+大小检查不够,必须验证JSON schema否则垃圾内容可绕过
keywords: [绕过, schema, 验证, STATE.json, 接棒, 文件检查, 红队]
---

## 攻击向量
stop-hook.sh 的 STATE.json 强制只检查: 文件存在 + 大小>=50字节。
攻击者写入 60 字节垃圾（如 `AAAA...A`）即可绕过。

## 防御评级: 弱

## 推荐加固
在大小检查后增加 schema 验证:
```bash
python3 -c "
import json
d = json.load(open('$STATE_FILE'))
assert 'completed' in d or 'pending' in d, 'Missing required fields'
"
```
