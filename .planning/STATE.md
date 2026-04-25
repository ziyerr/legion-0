# AICTO — STATE

## 当前阶段
**Phase 0 · 初始化**

## 已完成（2026-04-23）
- 目录结构（`hermes-plugin/`、`.planning/`、`docs/`）
- `plugin.yaml`：身份 + 8 工具声明
- `__init__.py`：`register()` + `pre_llm_call` 反幻觉 hook
- `schemas.py`：8 个工具 JSON schema
- `tools.py`：8 个 stub 函数，统一返回 `{"status": "not_implemented"}`
- `CLAUDE.md`、`README.md`、`docs/ROLES.md`

## 进行中
无

## 待完成（按优先级）
1. 实现第一个具体工具（推荐 `evaluate_prd_feasibility` — 和 PM 的第一个协作点）
2. 决定是否和 ProdMind 共享 `dev.db`（读取 PRD 做评估）
3. 决定上线接入策略（是否注册到 `~/.hermes/config.yaml`）

## 下一步触发点
产品方案 v0.1 已产出 → `docs/PRODUCT-SPEC.md`（10 章，含 8 能力详述、PM/军团协作契约、ADR 设计、MVP 4 阶段路径、5 个开放问题）。

等老板决策以下之一后进入 M1：
1. 5 个开放问题的立场（见 PRODUCT-SPEC §10 — ADR 放哪、CTO 人格名字、军团直连策略、评审强度、跨项目债盘点）
2. M1 时间窗口（`evaluate_prd_feasibility` + `record_tech_decision` + ADR 表）
3. AICTO profile 接入 prodmind dev.db 的授权（读 PRD/Project，写 ADR/TechRisk/TechDebt/CodeReview）

## 上线状态
**未接入任何 Hermes profile**。当前只是本地目录 + 插件骨架，不影响 default gateway（PM bot）运行。

### 启用路径（Profile 隔离）

```bash
hermes profile create aicto
hermes profile alias aicto

# 编辑 ~/.hermes-aicto/config.yaml（或 profile show 给的路径）：
# - api_server.port: 8643（避开 default 的 8642）
# - plugins: /Users/feijun/Documents/AICTO/hermes-plugin
# - 飞书 app_id/secret: 独立 AICTO bot

nohup aicto gateway run > /tmp/aicto-gateway.log 2>&1 &
hermes profile list  # 确认 aicto running
```

### 为什么要 profile 隔离（不是装到 default）

- default profile（prodmind/PM）= 生产系统，硬约束"零影响"
- AICTO 独立 profile = 独立 state.db/sessions/plugins/飞书 app，启停崩溃完全不波及 PM
- 参考：AIHR 已经是 profile 模式运行（当前 stopped），云智 AI 团队每个员工都应该 = 独立 profile

## 纪律提醒
按用户 2026-04-23 硬约束"生产系统零影响"，任何把 AICTO 接入现网的动作都必须：
1. 先在 worktree 里验证
2. 先和 PM 协作场景跑通端到端
3. 只有产品场景确认才注册到生产
