---
id: impl-legion-directory
domain: collaboration
type: implementation
score: 0
created: 2026-04-04
source: L1-青龙军团
project: novel-to-video-standalone
summary: ~/.claude/legion/directory.json全局名册,军团启动时自动注册,支持xmsg按项目名通信
keywords: [名册, directory, 跨项目, 发现, xmsg, 注册]
---

## 实施内容
legion.sh 启动时调用 `_register_to_directory()`，将项目 hash/名称/路径/CC team 写入全局名册。
`legion.sh xmsg <项目名> "消息"` 查名册自动解析 hash，找首席 L1 投递。

## 文件格式
```json
{
  "legions": [
    {"hash": "6df23ccc", "project": "novel-to-video-standalone", "cc_team": "legion-6df23ccc", "last_active": "..."}
  ]
}
```

## 使用方式
- `legion.sh xmsg list` -- 列出所有已注册项目
- `legion.sh xmsg CartCast "消息"` -- 按项目名发送
