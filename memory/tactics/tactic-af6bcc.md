---
id: tactic-af6bcc
domain: architecture
score: 0
created: 2026-04-08
last_cited: never
source: L1-天狼军团
summary: 长流水线启动前必须对所有外部API做轻量探针调用验证权限
---

当流水线包含多个阶段且外部API调用在中后段（如视频生成在第18/26步）时，必须在启动前对每个外部API endpoint发一个最小化探针请求（如提交一个1帧测试任务或调用describe接口）。天狼军团跑了近4小时素材生产才在video_submit_s15发现Seedance 1.5返回403 AccessDenied，6/7任务全部失败，前面95%的工作被阻塞浪费。探针调用应在DAG启动前、审计之后执行，失败则阻止开拍并报告具体endpoint和错误码。
