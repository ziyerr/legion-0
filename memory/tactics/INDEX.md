# Global Tactics Index

跨项目通用的工程模式和教训。每条战法从具体项目中提炼而来，可复用于任何战场。

**总计: 35 条**

### architecture (17)
- [tactic-c1805c](tactic-c1805c.md): 多层知识库的'重复'先验证抽象层级再决定合并——同层合并，跨层保留并加索引 [★1] — L1-青龙军团 (2026-04-04)
- [tactic-017946](tactic-017946.md): 媒体处理管道的端到端测试必须覆盖到最终用户可访问的URL，不能止步于处理完成 — L1-烽火军团 (2026-04-07)
- [tactic-18949a](tactic-18949a.md): 架构升级用覆盖度矩阵(模块×能力层)做完整性校验，防止某模块被遗漏 — L1-破晓军团 (2026-03-31)
- [tactic-1c6260](tactic-1c6260.md): 重试/恢复系统从DB读供应商分配时，必须校验供应商当前健康状态，否则失败供应商制造任务黑洞 — L1-白虎军团 (2026-04-09)
- [tactic-1eed7b](tactic-1eed7b.md): 浏览器自动化方案选型用四维适用性矩阵：精度需求×UI变频×当前稳定度×降级成本 — L1-赤龙军团 (2026-03-31)
- [tactic-2d43e1](tactic-2d43e1.md): 验证阶段被限额/中断打断后，必须完整重读所有变更文件再验收，禁止凭中断前的部分记忆签收 — L1-长歌军团 (2026-04-10)
- [tactic-42f379](tactic-42f379.md): 审查反馈汇总后一次性下发，用SEVERE计数决定是否需要重审 — L1-北斗军团 (2026-04-05)
- [tactic-469dc4](tactic-469dc4.md): 双路侦察报告回传后，先用结构化决策矩阵收敛关键决策点，再进入 spec 设计，避免分析瘫痪 — L1-凤凰军团 (2026-03-30)
- [tactic-70c6c0](tactic-70c6c0.md): 多模型协作需显式冲突仲裁协议：发现分歧→交叉确认→指挥官仲裁，禁止默认采信'主场模型' — L1-暴风军团 (2026-04-03)
- [tactic-831152](tactic-831152.md): DAG 调度器中条件捷径（pre_check/readiness probe）必须叠加失败传播守卫，不可绕过依赖图 — L1-苍穹军团 (2026-03-31)
- [tactic-a9ce78](tactic-a9ce78.md): 大规模架构升级按依赖层自底向上组织变更：基础设施→核心模块→编排层→配置，而非按功能特性切分 — L1-破晓军团 (2026-03-31)
- [tactic-af6bcc](tactic-af6bcc.md): 长流水线启动前必须对所有外部API做轻量探针调用验证权限 — L1-天狼军团 (2026-04-08)
- [tactic-d0ffec](tactic-d0ffec.md): 批量任务进度监控必须用eligible count做分母，不能用total count — L1-麒麟军团 (2026-04-01)
- [tactic-dd24c0](tactic-dd24c0.md): 系统替代评估必须多维度打分且取最低分决定，不能取平均 — L1-赤龙军团 (2026-03-28)
- [tactic-dea8b9](tactic-dea8b9.md): 质量门控必须区分全损(0%)与部分不达标(>0%<阈值)，全损走 bug 升级而非重试 — L1-天狼军团 (2026-03-30)
- [tactic-ed899f](tactic-ed899f.md): 并行修复多个外部集成时，按故障模式分组而非按优先级分组 — L1-鲲鹏军团 (2026-03-31)
- [tactic-f16427](tactic-f16427.md): 事件驱动→轮询迁移时，条件轮询必须改为无条件轮询，否则形成鸡生蛋死锁 — L1-鲲鹏军团 (2026-03-29)

### architecture/ai (1)
- [tactic-422805](tactic-422805.md): 多步AI引导对话用Redis存临时态、DB存终态，避免半成品污染持久层 — L1-深渊军团 (2026-04-01)

### architecture/concurrency (1)
- [tactic-b2488c](tactic-b2488c.md): 实时事件流(SSE/WebSocket)中嵌入金融写操作时，必须用 DB UNIQUE 约束做幂等保证，不能仅���应用层检查 — L1-苍穹军团 (2026-03-26)

### architecture/spec-driven (1)
- [tactic-60acf9](tactic-60acf9.md): DB migration 改名/删列时，spec 必须附带旧列名的全局 grep 扫描结果作为 blast radius 清单 — L1-烈焰军团 (2026-04-05)

### bash (1)
- [tactic-80f12f](tactic-80f12f.md): Bash `local` 只能在函数体内使用，case 分支内联逻辑时必须去掉 local 或包一层函数 — L1-昆仑军团 (2026-04-01)

### javascript/architecture (1)
- [tactic-1abd3a](tactic-1abd3a.md): 资源池 release 路径必须加 null guard，因为 acquire 超时或异常时 slot 引用可能为 undefined — L1-磐石军团 (2026-03-27)

### mobile/architecture (1)
- [tactic-fa7559](tactic-fa7559.md): Capacitor iosScheme 必须与 androidScheme 对齐设���为 https，否则 iOS 端默认 capacitor:// 协议导致 CORS 拦截 — L1-黑曜军团 (2026-04-03)

### python (4)
- [tactic-390716](tactic-390716.md): loop.run_in_executor() 无内置超时，必须用 asyncio.wait_for() 包裹 — L1-暴风军团 (2026-03-27)
- [tactic-54e325](tactic-54e325.md): FastAPI POST 端点即使所有字段可选，body 仍不能为 null，必须传 {} 并带 Content-Type: application/json — L1-天狼军团 (2026-04-02)
- [tactic-cbd061](tactic-cbd061.md): 破坏性清理必须先备份再删除，不可先删后写 — L1-暴风军团 (2026-04-05)
- [tactic-f43fa7](tactic-f43fa7.md): LLM生成的正则表达式必须经过语法校验+ReDoS样本检测后才能执行 — L1-凤凰军团 (2026-04-08)

### python/shell (1)
- [tactic-9fe369](tactic-9fe369.md): curl 管道到 JSON 解析器前必须先校验 HTTP 状态码和响应体非空 — L1-黑曜军团 (2026-04-03)

### rootcause (1)
- [rootcause-1775829771-feishu-indentation-level](rootcause-1775829771-feishu-indentation-level.md): 飞书 docx descendants API 创建时不接受 bullet/ordered.style.indentation_level，任何值都会失败（99992402 或 4000501），枚举字面量也不行——必须完全省略 — sniper (2026-04-10)

### security/api (1)
- [tactic-c56068](tactic-c56068.md): 金融端点安全三板斧：值域校验 → 归属校验 → 原子扣款 — L1-昆仑��团 (2026-04-01)

### testing/verification (1)
- [tactic-7ab7c8](tactic-7ab7c8.md): 大规模 UI 重构的最小可行验证：批量 HTTP 状态码 + 动态数据 diff — L1-银河军团 (2026-03-31)

### typescript/architecture (1)
- [tactic-d9e02c](tactic-d9e02c.md): 时间轴编辑器素材联动用 groupId 刚体模式：同组 clip 共享 delta，保持相对偏移 — L1-沧海军团 (2026-03-28)

### typescript/browser (1)
- [tactic-ac78e8](tactic-ac78e8.md): HTML5 video 切换 src 后必须等 loadeddata 事件再调用 play() — L1-沧海军团 (2026-03-28)

### uncategorized (2)
- [tactic_evaluate_quality必须检查完整性](tactic_evaluate_quality必须检查完整性.md): 所有 skill 的 evaluate_quality 不能只检查"已有产物的质量"，必须同时检查"产物数 vs 预期数"，失败项直接 score=0
- [tactic_穿插时间轴必须在TTS完成后重新计算](tactic_穿插时间轴必须在TTS完成后重新计算.md): narration_interleave 的产出依赖 tts_narration 的完整音频集，TTS 重跑后穿插必须重新计算，否则旁白覆盖率极低
