# AICTO CTO Operating Model Decisions

## DEC-001：把 CTO 方法论做成运行时工具

- 决策：新增 `cto_operating_model`，而不是只写 `CLAUDE.md`。
- 理由：AICTO 在飞书/Hermes 中需要可调用、可测试、可审计的能力；文档不能强制 LLM 行为。
- 影响：工具总数从 20 增加到 21。

## DEC-002：确认类动作强制 evidence

- 决策：`approve_plan`、`authorize`、`reject_plan`、`block`、`escalate` 和 `approved/rejected/escalated` 授权裁决必须带 evidence。
- 理由：用户明确要求所有确认都必须是事实，不能是表面信息或幻觉。
- 影响：缺少 evidence 的 CTO 指令会返回 error，不写入 L1 inbox。

## DEC-003：专业知识来源只采用可核验公开框架

- 决策：基础模型采用 DORA、Google SRE、Team Topologies、NIST SSDF、NIST AI RMF、OWASP LLM Top 10、GitLab DRI。
- 理由：这些框架覆盖交付、可靠性、组织拓扑、安全开发、AI 风险和责任人机制。
- 影响：AICTO 运行模型文档和工具均携带 source basis。
