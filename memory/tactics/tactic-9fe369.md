---
id: tactic-9fe369
domain: python/shell
score: 0
created: 2026-04-03
last_cited: never
source: L1-黑曜军团
summary: curl 管道到 JSON 解析器前必须先校验 HTTP 状态码和响应体非空
---

curl | python3 json.load(sys.stdin) 在服务不可达时返回空字符串，产生 JSONDecodeError(line 1 column 1 char 0) 而非明确的连接错误，导致误判为数据格式问题而非服务不可用。正确做法：先用 curl -sf -w '%{http_code}' 捕获状态码，非 2xx 时直接报错退出不进入 JSON 解析；或分两步：response=$(curl -sf URL) && echo "$response" | python3 -c 'import json,sys; ...'，让 curl 失败时 && 短路。
