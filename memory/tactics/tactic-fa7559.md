---
id: tactic-fa7559
domain: mobile/architecture
score: 0
created: 2026-04-03
last_cited: never
source: L1-黑曜军团
summary: Capacitor iosScheme 必须与 androidScheme 对齐设���为 https，否则 iOS 端默认 capacitor:// 协议导致 CORS 拦截
---

Capacitor 项目中 capacitor.config.ts 的 server.iosScheme 必须显式设为 "https"，与 androidScheme 对齐。否则 iOS 端 webview 使用默认的 capacitor:// 协议，导致所有 fetch 请求被 CORS 策略拦截（origin mismatch）。Android 端不受影响因为 androidScheme 默认就是 https。排查时表现为"iOS 端网络请求全部失败，Android 正常"。
