"""AICTO（程小远）— AI 技术总监 Hermes plugin.

云智 OPC 团队的技术决策伙伴，与 ProdMind（PM 张小飞）、AIHR 同 Hermes profile 拓扑。
PM 定义 WHAT，CTO 决定 HOW。

Phase 1 全量（2026-04-25 实施中）：
- 6 个核心能力（kickoff_project / design_tech_plan / breakdown_tasks /
  dispatch_to_legion_balanced / review_code / daily_brief）
- 8 个 PM 只读工具（read_pm_*）+ 2 个综合工具 + 1 个多项目军团组合管理工具
- CTO 独立记忆 + L1 指挥中枢 + CTO 专业运行模型 + 军团系统维护
- 需求元数据硬门禁（原子 PRD + 5W1H + 增删查改显算传）
- AIPM/AICTO 独立项目协作协议（澄清请求 + 验收交付）
- 端口 8644，独立飞书 app cli_a949...，独立 state.db

实施进度详见 .planning/phase1/specs/PHASE-PLAN.md。
"""

from . import schemas, tools


def register(ctx):
    """Register all 24 AICTO tools with Hermes."""

    _TOOLS = [
        # 6 个核心能力（PM 派发）
        ("kickoff_project",                schemas.KICKOFF_PROJECT,                tools.kickoff_project),
        ("design_tech_plan",               schemas.DESIGN_TECH_PLAN,               tools.design_tech_plan),
        ("breakdown_tasks",                schemas.BREAKDOWN_TASKS,                tools.breakdown_tasks),
        ("dispatch_to_legion_balanced",    schemas.DISPATCH_TO_LEGION_BALANCED,    tools.dispatch_to_legion_balanced),
        ("review_code",                    schemas.REVIEW_CODE,                    tools.review_code),
        ("daily_brief",                    schemas.DAILY_BRIEF,                    tools.daily_brief),

        # 8 个 PM 只读工具（CTO-READ-ACCESS-SPEC §三）
        ("read_pm_project",                schemas.READ_PM_PROJECT,                tools.read_pm_project),
        ("read_pm_prd",                    schemas.READ_PM_PRD,                    tools.read_pm_prd),
        ("list_pm_prd_decisions",          schemas.LIST_PM_PRD_DECISIONS,          tools.list_pm_prd_decisions),
        ("list_pm_open_questions",         schemas.LIST_PM_OPEN_QUESTIONS,         tools.list_pm_open_questions),
        ("list_pm_user_stories",           schemas.LIST_PM_USER_STORIES,           tools.list_pm_user_stories),
        ("list_pm_features",               schemas.LIST_PM_FEATURES,               tools.list_pm_features),
        ("read_pm_research_doc",           schemas.READ_PM_RESEARCH_DOC,           tools.read_pm_research_doc),
        ("read_pm_evaluation_doc",         schemas.READ_PM_EVALUATION_DOC,         tools.read_pm_evaluation_doc),

        # 2 个综合工具
        ("get_pm_context_for_tech_plan",   schemas.GET_PM_CONTEXT_FOR_TECH_PLAN,   tools.get_pm_context_for_tech_plan),
        ("diff_pm_prd_versions",           schemas.DIFF_PM_PRD_VERSIONS,           tools.diff_pm_prd_versions),

        # 多项目军团组合管理
        ("legion_portfolio_status",         schemas.LEGION_PORTFOLIO_STATUS,        tools.legion_portfolio_status),

        # CTO 独立记忆 + L1 指挥中枢 + 专业运行模型
        ("cto_memory_record",               schemas.CTO_MEMORY_RECORD,              tools.cto_memory_record),
        ("cto_memory_query",                schemas.CTO_MEMORY_QUERY,               tools.cto_memory_query),
        ("legion_command_center",           schemas.LEGION_COMMAND_CENTER,          tools.legion_command_center),
        ("cto_operating_model",             schemas.CTO_OPERATING_MODEL,            tools.cto_operating_model),
        ("legion_system_maintenance",       schemas.LEGION_SYSTEM_MAINTENANCE,      tools.legion_system_maintenance),
        ("requirement_metadata_gate",        schemas.REQUIREMENT_METADATA_GATE,      tools.requirement_metadata_gate),
        ("aipm_cto_collaboration",          schemas.AIPM_CTO_COLLABORATION,         tools.aipm_cto_collaboration),
    ]

    for name, schema, handler in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="aicto",
            schema=schema,
            handler=handler,
            emoji="🏗️",
        )

    # ------------------------------------------------------------------------
    # Hook: 反幻觉 + CTO 纪律注入（每轮 LLM 必读）
    # 5 条纪律已在 SOUL.md 嵌入（PRD §三要求），此处再做强化注入避免被忽略
    # ------------------------------------------------------------------------
    _ANTI_HALLUCINATION_NUDGE = (
        "\n[程小远 · CTO 纪律 · 每轮必读]\n"
        "1. 不得声称未做的事：不说\"评审完成\"、\"决策已记录\"、\"文档已创建\"，"
        "除非实际调用工具并收到成功返回。承诺动作改为\"我来调用 X 工具\"。\n"
        "2. 识别飞书引用回复：用户消息可能是引用回复拼接，前段是你历史发言。"
        "聚焦最后一段新提问。\n"
        "3. 承认缺失不编造：找不到记录直接说没记录，不推卸到\"另一个 Agent\"。\n"
        "4. 技术决策要有根据：建议、评审、风险评估必须基于实际代码/文档/数据。"
        "没数据时说\"我需要先看 X 才能判断\"。\n"
        "5. stub 工具透明：当前 Phase 1 实施中，部分工具返回 not_implemented。"
        "收到此返回必须告诉用户\"该工具未实现\"，不得编造结果。\n"
        "6. 边界：CTO ⊥ PM 维度正交。我读 PM 的产出（dev.db / 飞书 doc）但不改。"
        "我写自己的表（ADR / TechRisk / TechDebt / CodeReview / EngineerProfile）。\n"
        "7. 权力：程小远是开发军团最高技术指挥官。L1 必须直接听 CTO 指挥、向 CTO 汇报，"
        "需求/授权/方案不确定时向 CTO 请求决策；CTO 对开发中项目拥有技术决策权。\n"
        "8. 记忆：重大组织契约、授权、技术决策、军团汇报必须进入 cto_memory_* 独立 JSONL 记忆，"
        "保持可迁移、可升级、可审计。\n"
        "9. CTO 专业运行模型：重大技术判断先用 cto_operating_model 检查能力矩阵、运行手册和 evidence gate；"
        "approve/reject/authorize/block/escalate 不允许无证据。\n"
        "10. 军团维护：用 legion_system_maintenance 持续扫描真实 registry/events/outbox/memory，"
        "把长期数据不可处理、重复 commander、未 ACK、blocked/running 积压转成可追踪风险和跟进指令。\n"
        "11. 需求入口硬门禁：所有到 AICTO 的需求必须是原子级 PRD 元数据，"
        "明确需求ID/标题/原子对象/验收标准、5W1H、以及「增删查改显算传」。"
        "不涉及必须写「无」，缺省/空白/待定都不得进入技术方案、任务拆解或军团派单。\n"
        "12. AIPM/AICTO 独立协作：AIPM 负责用户需求、产品设计、PRD、用户确认和最终汇报；"
        "AICTO 负责技术门禁、军团指挥、开发推进、测试验收和向 AIPM 交付验收包。"
        "需求不明细/与用户相悖/未与用户确认时，AICTO 必须主动请求 AIPM 在飞书中向用户确认。\n"
    )

    def _pre_llm_aicto_nudge(user_message: str = "", **kwargs):
        """Inject CTO discipline into every LLM turn."""
        return {"context": _ANTI_HALLUCINATION_NUDGE}

    ctx.register_hook("pre_llm_call", _pre_llm_aicto_nudge)

    # ------------------------------------------------------------------------
    # P1.7：daily_brief cron — 18:00 UTC+8 自动推送 + 09:00 补发漏跑
    # 设 env AICTO_DAILY_BRIEF_DISABLED=1 可关闭（开发环境免打扰）
    # ------------------------------------------------------------------------
    try:
        from . import cron_runner

        cron_runner.register_cron(ctx)
    except Exception as e:  # noqa: BLE001 — cron 失败不阻塞工具注册
        import logging

        logging.getLogger(__name__).warning(
            "AICTO daily_brief cron register failed: %s (tool 仍可手动调用)", e
        )
