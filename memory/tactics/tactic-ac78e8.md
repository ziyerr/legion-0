---
id: tactic-ac78e8
domain: typescript/browser
score: 0
created: 2026-03-28
last_cited: never
source: L1-沧海军团
summary: HTML5 video 切换 src 后必须等 loadeddata 事件再调用 play()
---

视频元素更换 src 后直接调用 play() 会导致 Promise rejection（Chrome/WebKit 均复现）。正确做法：监听 loadeddata 事件，在回调中恢复 play 状态和 seek 位置。一次性监听用 { once: true } 避免泄漏。
