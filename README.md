# AICTO

> AI 技术总监 · 云智 AI 团队 OPC 成员 · 与 ProdMind (AI PM) 搭档构成产品-技术决策闭环

详细定位见 [CLAUDE.md](./CLAUDE.md)。

---

## 快速开始（Profile 隔离部署）

AICTO 作为**独立 Hermes profile**运行，不共用 default（避免影响生产 PM）。和 AIHR 的部署模式一致。

### 1. 创建 profile

```bash
hermes profile create aicto
hermes profile alias aicto
```

### 2. 配置独立 profile

编辑 `hermes profile show aicto` 显示的 config.yaml 路径：

- `api_server.port`: `8643`（避开 default 的 `8642`）
- `plugins`: `/Users/feijun/Documents/AICTO/hermes-plugin`
- `feishu.app_id` / `feishu.app_secret`: 独立的 AICTO 飞书 bot（不要复用 PM 的 app）

### 3. 启动独立 gateway

```bash
nohup aicto gateway run > /tmp/aicto-gateway.log 2>&1 &
hermes profile list  # 应看到 aicto running
```

### 4. 查健康

```bash
curl http://127.0.0.1:8643/health
```

### 停/重启

```bash
kill $(pgrep -f "aicto gateway run")
nohup aicto gateway run > /tmp/aicto-gateway.log 2>&1 &
```

> 注：profile 隔离确保 AICTO 的启停、崩溃、版本变更**完全不影响 default profile 的 PM bot**，符合用户「生产零影响」硬约束。

---

## 目录结构

```
AICTO/
├── README.md              快速开始（本文档）
├── CLAUDE.md              AI agent 定位 + 协作拓扑（必读）
├── hermes-plugin/         Hermes plugin 入口
│   ├── plugin.yaml        身份 + 8 个工具声明
│   ├── __init__.py        register() + pre_llm_call 反幻觉 hook
│   ├── schemas.py         工具参数 JSON schema
│   └── tools.py           工具实现（Phase 0: 全部 stub）
├── .planning/             Spec-driven 工作目录
│   └── STATE.md           当前阶段
└── docs/
    └── ROLES.md           AICTO 角色职责拆解
```

---

## 8 个工具（Phase 0 全部 stub）

| 工具 | 作用 |
|------|------|
| `review_architecture` | 架构评审 |
| `assess_technical_risk` | 技术风险评估 |
| `recommend_tech_stack` | 技术栈选型建议 |
| `review_code` | 代码评审 |
| `evaluate_prd_feasibility` | PRD 技术可行性评估 |
| `analyze_technical_debt` | 技术债务分析 |
| `propose_refactor` | 重构方案 |
| `record_tech_decision` | 技术决策记录 |

调用任何 stub 工具会返回 `{"status": "not_implemented", ...}` —— LLM 侧有纪律提醒必须诚实告知用户，不得伪装成功。

---

## 状态

- ✅ 2026-04-23 初始化：目录结构 + plugin 骨架 + 8 工具 stub + 反幻觉 hook
- ⏳ 待驱动：第一个实际实现（推荐 `evaluate_prd_feasibility` 作为和 PM 的第一个协作点）
- ⏳ 未接入生产 gateway（等显式启用信号）
