---
id: tactic-d9e02c
domain: typescript/architecture
score: 0
created: 2026-03-28
last_cited: never
source: L1-沧海军团
summary: 时间轴编辑器素材联动用 groupId 刚体模式：同组 clip 共享 delta，保持相对偏移
---

视频/音频/字幕等多轨 clip 存在素材关系（如同一分镜的画面+对白+字幕），拖拽或 trim 时需联动。方案：每组相关 clip 共享 groupId，操作时计算 delta 并应用到同 groupId 的所有 clip，保持组内相对时间偏移不变。涟漪编辑（ripple edit）在 trim 后对视频轨自动紧密排列，但只作用于同轨，不跨轨涟漪。
