# ADR-001：工具命名替换（8 stub → 16 工具）

**状态**：🔒 LOCKED
**时间**：2026-04-25
**决策者**：L1-麒麟军团指挥官
**适用阶段**：Phase 1 全程

## Context

AICTO Phase 0（2026-04-23）创建了 8 个 stub 工具（v0.1 命名）：
`review_architecture / assess_technical_risk / recommend_tech_stack / review_code / evaluate_prd_feasibility / analyze_technical_debt / propose_refactor / record_tech_decision`

PM 在 2026-04-25 派发 Phase 1，要求 6 能力命名：
`kickoff_project / design_tech_plan / breakdown_tasks / dispatch_to_legion_balanced / review_code / daily_brief`

仅 `review_code` 命名重叠。其余 7 个 stub 与 6 能力完全不对应。

## Decision

**替换** 8 stub 工具为 PM 派发 6 能力 + 8 PM 只读工具 + 2 综合工具 = 16 工具。

### 工具清单

| # | 名称 | 类型 | 来源 |
|---|------|------|------|
| 1 | kickoff_project | 6 能力 | PM 派发 |
| 2 | design_tech_plan | 6 能力 | PM 派发 |
| 3 | breakdown_tasks | 6 能力 | PM 派发 |
| 4 | dispatch_to_legion_balanced | 6 能力 | PM 派发 |
| 5 | review_code | 6 能力 | PM 派发（与旧 stub 重叠保留命名）|
| 6 | daily_brief | 6 能力 | PM 派发 |
| 7-14 | read_pm_project / read_pm_prd / list_pm_prd_decisions / list_pm_open_questions / list_pm_user_stories / list_pm_features / read_pm_research_doc / read_pm_evaluation_doc | PM 只读 | CTO-READ-ACCESS-SPEC §三 |
| 15-16 | get_pm_context_for_tech_plan / diff_pm_prd_versions | 综合 | CTO-READ-ACCESS-SPEC §三 |

### 旧 stub 处置

- `review_architecture / assess_technical_risk / recommend_tech_stack / evaluate_prd_feasibility` → 4 个旧 stub 的功能融入 design_tech_plan 内部推理链
- `record_tech_decision` → 内部辅助工具（被 design_tech_plan 自动调用，不暴露顶层）
- `analyze_technical_debt / propose_refactor` → Phase 1 不实现，保留命名供 Phase 2/3 使用

## Alternatives Considered

| 方案 | 拒绝理由 |
|-----|---------|
| 保留 8 stub + 新增 6 能力 | 命名冲突（review_code）+ 用户混淆"该调哪个" |
| 保留 8 stub 命名做映射（如 evaluate_prd_feasibility 当 design_tech_plan）| 语义错位 + LLM 调用时不知道工具实际能力 |
| 完全不改 8 stub，只在内部映射 | PM 派发文档要求 6 能力命名（验收依此名）|

## Consequences

### 正面
- ✅ 与 PM 派发完全对齐，验收无歧义
- ✅ 工具名 = 能力描述（自解释）
- ✅ 无并发命名冲突

### 负面
- ⚠️ Phase 0 文档（PRODUCT-SPEC v0.1）的工具命名需标注"已废弃，参 v0.2"
- ⚠️ 如有外部调用方使用旧命名（实际上没有，所有 stub 都是 not_implemented），需迁移

## Verification

- [ ] `plugin.yaml:provides_tools` 含 16 项新命名
- [ ] `schemas.py` 含 16 个 schema 常量
- [ ] `__init__.py:register()` 16 次调用 register_tool
- [ ] 飞书 @程小远 "/list_tools" 返回 16 项
- [ ] 旧命名（如 review_architecture）调用返回 `{"error": "tool not found"}`
