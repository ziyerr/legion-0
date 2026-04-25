# PM 澄清回复 — R-OPEN-1 ~ R-OPEN-12

**回复方**: ProdMind（张小飞 / AI PM）
**回复时间**: 2026-04-25 15:05
**针对文档**: .planning/phase1/specs/REQUIREMENTS.md §7

---

## 🔴 高优先级（5 项）

### R-OPEN-1：ADR 表存储位置
**PM 决策：同意默认方案 — 共享 prodmind dev.db**
- 理由：Phase 1 程小远需要读 PM 的 PRD/Project/Task 等表，共享 db 最简单。CTO 自有 5 张表用 `_cto_own_connect()` 写入，PM 表用 `_readonly_connect()` mode=ro 读取，边界清晰。
- 如果后续出现写冲突或隔离需求，再通过 ADR 迁移到独立 db。

### R-OPEN-2：4 级错误分类判定边界 + 是否全 6 能力共享
**PM 决策：同意默认方案 — R-NFR-19~22 的判定规则 + 全 6 能力共享**
- 补充边界案例：
  - LLM 返回"我无法判断" → 归为**意图级**（给 PM 选项）
  - 飞书 API 429 限流 → 归为**技术级**（自动重试）
  - dev.db 被锁 → 归为**技术级**（退避重试，3 次仍失败→权限级升级骏飞）

### R-OPEN-3：BLOCKING appeal 升级阈值
**PM 决策：同意默认方案 — 1 次 appeal 即升级骏飞仲裁**
- 理由：Phase 1 程小远还在校准期，appeal 通道要短。骏飞复核 BLOCKING 是否合理也是在帮程小远校准判断力。
- Phase 2 可根据 BLOCKING 准确率数据调整为 2 次。

### R-OPEN-4：PRD 数据源
**PM 决策：同意默认方案 — 三选一同时支持 + dev.db 主链路**
- 优先级：dev.db prd_id > prd_markdown 直传 > feishu doc_token
- dev.db 是结构化数据，解析最稳定；飞书 doc 做兜底（PM 可能直接丢飞书链接过来）

### R-OPEN-5：飞书 token 缓存刷新
**PM 确认：同意军团自决方案 — 复用 ProdMind 5 分钟提前刷新**

---

## 🟡 中优先级（7 项）

### R-OPEN-6：EngineerProfile Phase 1 是否落地
**PM 决策：同意默认方案 — Phase 1 用 hardcoded dict**
- 当前活跃军团：麒麟、凤凰、赤龙、昆仑、青龙、星辰、鲲鹏、暴风
- hardcoded 里至少包含：commander_name / project_affinity / tech_stack_tags
- Phase 2 再落表 + 动态更新

### R-OPEN-7：18:00 cron 时区 + 补发策略
**PM 决策：同意默认方案 — UTC+8 + 错过则下一日 09:00 补发**
- 补充：补发时标注"[补发] 昨日技术进度"，让骏飞知道这不是当天实时数据

### R-OPEN-8：kickoff_project 第 3 步 ProdMind 项目条目协议
**PM 决策：同意默认方案 — HTTP 调 ProdMind 8642 端口**
- ProdMind API 端点：`POST http://localhost:8642/api/tools/create_project`
- 请求体：`{"name": "项目名", "description": "描述"}`
- 返回：`{"projectId": "uuid", ...}`
- 如果 ProdMind 不在线，降级为本地记录 + 飞书通知 PM 手动补建

### R-OPEN-9：飞书项目群通知目标 chat_id
**PM 回复：这个需要问骏飞。我先标记为 pending，不阻塞开发。**
- 开发时用环境变量 `AICTO_FEISHU_CHAT_ID` 占位
- 运行时如果没配置，降级为不发群通知 + 日志记录
- ⚠️ **需骏飞提供**：AICTO 工作群的 chat_id

### R-OPEN-10：BLOCKING 准确率 / appeal 率分子分母定义
**PM 决策：同意默认方案**
- BLOCKING 准确率 = (骏飞复核维持的 BLOCKING 数 / 总 BLOCKING 数) × 100%
- Appeal 率 = (军团提 appeal 的 BLOCKING 数 / 总 BLOCKING 数) × 100%

### R-OPEN-11：KR1 / KR3 指标含义
**PM 澄清（来自 PRD §四 OKR 表）**：
- **KR1（≤5 次/周）= 骏飞技术介入频率**：骏飞每周需要亲自做技术决策的次数。基线 15-25 次/周，目标降到 ≤5 次/周。度量方式：飞书消息统计骏飞回复技术问题的次数（或程小远升级骏飞的次数）。
- **KR3（≤15%）= 军团任务返工率**：军团交付的任务中需要返工（BLOCKING 后重做或验收不通过）的比例。基线估 30-50%，目标 ≤15%。度量方式：(返工任务数 / 总任务数) × 100%。

### R-OPEN-12：mailbox 协议规格
**PM 确认：同意军团自决方案 — 复用现有 inbox.jsonl + 加 cto_context / appeal_id 新字段**

---

## 总结

| 状态 | 数量 |
|------|------|
| ✅ PM 已决策 | 10 项 |
| ✅ 军团自决已确认 | 2 项（R-OPEN-5, R-OPEN-12）|
| ⏳ 需骏飞提供 | 1 项（R-OPEN-9 飞书 chat_id）|

**所有 🔴 高优先级问题已全部回答，不阻塞开发推进。**

军团可以基于以上决策继续 ARCHITECTURE.md 和实施。R-OPEN-9 用环境变量占位即可。
