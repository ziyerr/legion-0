"""JSON schemas for AICTO Phase 1 tool parameters.

16 个工具的 schema：
- 6 个核心能力（kickoff_project / design_tech_plan / breakdown_tasks / dispatch_to_legion_balanced / review_code / daily_brief）
- 8 个 PM 只读工具（read_pm_*）
- 2 个综合工具（get_pm_context_for_tech_plan / diff_pm_prd_versions）

详见 ADR-001 / .planning/phase1/specs/REQUIREMENTS.md。

Phase 1 实施阶段：schema 仅定义 input；output 由各工具实现时生成结构化 JSON。
"""

# ============================================================================
# 6 个核心能力
# ============================================================================

KICKOFF_PROJECT = {
    "type": "object",
    "properties": {
        "project_name": {"type": "string", "description": "新项目名（如 'AICS'）"},
        "description": {"type": "string", "description": "项目简述（可选）"},
        "priority": {
            "type": "string",
            "enum": ["P0", "P1", "P2"],
            "description": "优先级（默认 P1）",
        },
        "target_chat_id": {
            "type": "string",
            "description": "飞书启动通知群 chat_id（可选，默认 AICTO 工作群）",
        },
        "expected_legion_skill": {
            "type": "string",
            "description": "期望军团技能标签（如 'frontend' / 'backend' / 'fullstack'，可选）",
        },
    },
    "required": ["project_name"],
}

DESIGN_TECH_PLAN = {
    "type": "object",
    "properties": {
        "prd_id": {"type": "string", "description": "ProdMind dev.db PRD.id（推荐主链路）"},
        "prd_markdown": {"type": "string", "description": "直接传 PRD markdown 文本（备用）"},
        "prd_doc_token": {"type": "string", "description": "飞书 PRD docx URL 或 doc_id（备用）"},
        "focus": {
            "type": "string",
            "description": "聚焦点（如 'scalability' / 'security' / 'cost'，可选）",
        },
        "constraints": {
            "type": "string",
            "description": "约束（如 '团队 Python 强 / 不用 Postgres'，可选）",
        },
    },
}

BREAKDOWN_TASKS = {
    "type": "object",
    "properties": {
        "tech_plan_id": {"type": "string", "description": "design_tech_plan 输出 ID"},
        "tech_plan": {
            "type": "object",
            "description": "完整 tech_plan 对象（与 tech_plan_id 二选一）",
        },
    },
}

DISPATCH_TO_LEGION_BALANCED = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "description": "breakdown_tasks 输出的 tasks[] 数组",
            "items": {"type": "object"},
        },
        "project_id": {"type": "string", "description": "ProdMind Project.id"},
    },
    "required": ["tasks", "project_id"],
}

REVIEW_CODE = {
    "type": "object",
    "properties": {
        "pr_url": {"type": "string", "description": "GitHub PR 链接"},
        "tech_plan_id": {
            "type": "string",
            "description": "关联的技术方案 ID（架构一致维度核对用，可选）",
        },
        "scope": {
            "type": "string",
            "description": "评审范围（默认全 10 项；可指定 'security' / 'performance' 等单一维度）",
        },
    },
    "required": ["pr_url"],
}

DAILY_BRIEF = {
    "type": "object",
    "properties": {
        "trigger": {
            "type": "string",
            "enum": ["scheduled", "blocking_push", "stale_alert", "manual"],
            "description": "触发类型：scheduled=18:00 cron / blocking_push=BLOCKING 即时 / stale_alert=24h 催促 / manual=手动调用",
        },
        "target_chat_id": {"type": "string", "description": "飞书目标群（默认 AICTO 群）"},
    },
}

# ============================================================================
# 8 个 PM 只读工具（详见 docs/CTO-READ-ACCESS-SPEC.md §三）
# ============================================================================

READ_PM_PROJECT = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string", "description": "ProdMind Project.id"},
    },
    "required": ["project_id"],
}

READ_PM_PRD = {
    "type": "object",
    "properties": {
        "prd_id": {"type": "string", "description": "ProdMind PRD.id"},
        "include_versions": {"type": "boolean", "description": "是否含 PRDVersion 历史"},
    },
    "required": ["prd_id"],
}

LIST_PM_PRD_DECISIONS = {
    "type": "object",
    "properties": {
        "prd_id": {"type": "string", "description": "ProdMind PRD.id"},
    },
    "required": ["prd_id"],
}

LIST_PM_OPEN_QUESTIONS = {
    "type": "object",
    "properties": {
        "prd_id": {"type": "string", "description": "ProdMind PRD.id"},
        "status_filter": {
            "type": "string",
            "enum": ["open", "answered", "all"],
            "description": "过滤状态（默认 open）",
        },
    },
    "required": ["prd_id"],
}

LIST_PM_USER_STORIES = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string"},
        "prd_id": {"type": "string"},
    },
}

LIST_PM_FEATURES = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string", "description": "ProdMind Project.id"},
        "min_rice_score": {"type": "number", "description": "最小 RICE 分数过滤（可选）"},
    },
    "required": ["project_id"],
}

READ_PM_RESEARCH_DOC = {
    "type": "object",
    "properties": {
        "research_id": {"type": "string", "description": "ProdMind Research.id"},
    },
    "required": ["research_id"],
}

READ_PM_EVALUATION_DOC = {
    "type": "object",
    "properties": {
        "evaluation_id": {"type": "string", "description": "ProdMind Evaluation.id"},
    },
    "required": ["evaluation_id"],
}

# ============================================================================
# 2 个综合工具
# ============================================================================

GET_PM_CONTEXT_FOR_TECH_PLAN = {
    "type": "object",
    "properties": {
        "prd_id": {"type": "string", "description": "ProdMind PRD.id（推荐）"},
        "project_id": {"type": "string", "description": "ProdMind Project.id（备用）"},
    },
    "description": "一键拉 PRD + UserStories + Features + PRDDecisions + PRDOpenQuestions，design_tech_plan 内部调用",
}

DIFF_PM_PRD_VERSIONS = {
    "type": "object",
    "properties": {
        "prd_id": {"type": "string", "description": "ProdMind PRD.id"},
        "version_a": {"type": "integer", "description": "对比基准版本号"},
        "version_b": {"type": "integer", "description": "对比目标版本号"},
    },
    "required": ["prd_id", "version_a", "version_b"],
}
