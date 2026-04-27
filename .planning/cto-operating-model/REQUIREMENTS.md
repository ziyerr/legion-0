# AICTO CTO Operating Model Requirements

## 背景

AICTO 必须成为能管理多项目开发军团的真实 CTO，而不是人格概念。它需要专业知识、方法论、证据门、运行工具、长期记忆和 L1/L2 协作协议。

## 需求

1. AICTO 必须有可调用的 CTO 专业运行模型，覆盖能力矩阵、运行闭环、权威来源、军团协议和证据门。
2. AICTO 的 approve/reject/authorize/block/escalate 不能无事实依据发生。
3. AICTO 必须能把组织契约、技术决策、授权、军团汇报、风险和经验写入独立长期记忆。
4. L1 必须直接向 AICTO 汇报、请求授权和提交 appeal；AICTO 必须能通过工具向 L1 下达指令。
5. 文档和运行时工具必须一致，不能只有文档没有工具。

## 验收

- `cto_operating_model` 注册为 Hermes tool。
- `cto_operating_model(action=decision_gate)` 能识别缺失 evidence。
- `cto_operating_model(action=bootstrap_memory)` 能写入 `cto_memory`。
- `legion_command_center` 对批准、拒绝、授权、阻断、升级强制 evidence。
- 全量单元测试通过。
