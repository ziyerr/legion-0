"""JSON schemas for AICTO Phase 1 tool parameters.

24 个工具的 schema：
- 6 个核心能力（kickoff_project / design_tech_plan / breakdown_tasks / dispatch_to_legion_balanced / review_code / daily_brief）
- 8 个 PM 只读工具（read_pm_*）
- 2 个综合工具（get_pm_context_for_tech_plan / diff_pm_prd_versions）
- 1 个组合管理工具（legion_portfolio_status）
- 5 个 CTO 指挥/记忆/运行模型/军团维护工具（cto_memory_record / cto_memory_query / legion_command_center / cto_operating_model / legion_system_maintenance）
- 1 个需求元数据门禁工具（requirement_metadata_gate）
- 1 个 AIPM/AICTO 协作协议工具（aipm_cto_collaboration）

详见 ADR-001 / .planning/phase1/specs/REQUIREMENTS.md。

Phase 1 实施阶段：schema 仅定义 input；output 由各工具实现时生成结构化 JSON。
"""

# ============================================================================
# 6 个核心能力
# ============================================================================

KICKOFF_PROJECT = {
    "type": "object",
    "properties": {
        "project_name": {
            "type": "string",
            "description": "新项目名（如 'AICS'）— 仅允许 [A-Za-z0-9_一-鿿-]，长度 1-64，禁 / \\ .. 控制字符",
            "pattern": r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿\-]{0,63}$",
        },
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
        "requirement_metadata": {
            "type": "object",
            "description": "原子 PRD 元数据。必须包含需求ID/标题/原子对象/验收标准、5W1H、增删查改显算传；不涉及必须显式写「无」。",
        },
        "aipm_target_chat_id": {
            "type": "string",
            "description": "需求门禁失败时，主动通知 AIPM 的飞书 chat_id；默认读 AICTO_PM_FEISHU_CHAT_ID。",
        },
        "dry_run_aipm_clarification": {
            "type": "boolean",
            "description": "需求门禁失败时只生成 AIPM 澄清消息，不实际发送飞书。",
        },
        "record_memory": {
            "type": "boolean",
            "description": "是否记录 AICTO 长期记忆，默认 true。",
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
        "allow_cross_project_borrow": {
            "type": "boolean",
            "description": "默认 false。仅在明确允许跨项目借兵时，才把任务派给非本项目军团。",
        },
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

# ============================================================================
# 多项目军团组合管理
# ============================================================================

LEGION_PORTFOLIO_STATUS = {
    "type": "object",
    "properties": {
        "project_id": {
            "type": "string",
            "description": "可选。只看某个 ProdMind Project.id 的军团状态。",
        },
        "project_name": {
            "type": "string",
            "description": "可选。按项目名模糊过滤。",
        },
        "include_inactive_projects": {
            "type": "boolean",
            "description": "是否包含 archived/completed/done 项目，默认 false。",
        },
        "include_inactive_legions": {
            "type": "boolean",
            "description": "是否包含无 active commander 的历史 legion，默认 false。",
        },
        "stale_hours": {
            "type": "number",
            "description": "AICTO 派单未读超过多少小时算 stale，默认 24。",
        },
        "max_projects": {
            "type": "integer",
            "description": "最多返回多少个项目，默认 50。",
        },
    },
}

CTO_MEMORY_RECORD = {
    "type": "object",
    "properties": {
        "scope": {
            "type": "string",
            "enum": ["system", "project", "legion", "interaction"],
            "description": "记忆作用域。不填时按 project_id/legion_id 自动推断。",
        },
        "kind": {
            "type": "string",
            "enum": [
                "organization_contract",
                "requirement_insight",
                "tech_decision",
                "authorization",
                "directive",
                "legion_report",
                "risk",
                "lesson",
                "handoff",
            ],
        },
        "title": {"type": "string"},
        "content": {"type": "string"},
        "project_id": {"type": "string"},
        "project_name": {"type": "string"},
        "legion_id": {"type": "string"},
        "source": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "importance": {"type": "integer"},
        "links": {"type": "array", "items": {"type": "string"}},
        "metadata": {"type": "object"},
    },
    "required": ["kind"],
}

CTO_MEMORY_QUERY = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": ["system", "project", "legion", "interaction"]},
        "kind": {"type": "string"},
        "project_id": {"type": "string"},
        "legion_id": {"type": "string"},
        "tag": {"type": "string"},
        "text": {"type": "string"},
        "since_ts": {"type": "string"},
        "limit": {"type": "integer"},
    },
}

LEGION_COMMAND_CENTER = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["collect_reports", "send_directive", "decide_authorization"],
            "description": "collect_reports 收集 L1 汇报；send_directive 发送 CTO 指令；decide_authorization 给 L1 授权/方案请求下裁决。",
        },
        "project_id": {"type": "string"},
        "project_name": {"type": "string"},
        "legion_hash": {
            "type": "string",
            "description": "目标 legion hash；多项目存在重复 commander_id 时必须传，避免误投。",
        },
        "commander_id": {"type": "string"},
        "directive_id": {"type": "string"},
        "directive_type": {
            "type": "string",
            "enum": [
                "execute",
                "pause",
                "resume",
                "request_plan",
                "approve_plan",
                "reject_plan",
                "clarify_requirement",
                "authorize",
                "block",
                "escalate",
            ],
        },
        "title": {"type": "string"},
        "content": {"type": "string"},
        "priority": {"type": "string", "enum": ["high", "normal", "low"]},
        "requires_ack": {"type": "boolean"},
        "requires_plan": {"type": "boolean"},
        "constraints": {"type": "string"},
        "evidence": {
            "type": "array",
            "description": "可追溯事实证据；approve/reject/authorize/block/escalate 必填。",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "ref": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
        "request_id": {"type": "string"},
        "verdict": {
            "type": "string",
            "enum": ["approved", "rejected", "needs_plan", "needs_pm_clarification", "escalated"],
        },
        "rationale": {"type": "string"},
        "since_ts": {"type": "string"},
        "limit": {"type": "integer"},
        "include_heartbeats": {"type": "boolean"},
        "record_memory": {"type": "boolean"},
    },
    "required": ["action"],
}

CTO_OPERATING_MODEL = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "capability_matrix",
                "runbook",
                "decision_gate",
                "source_basis",
                "legion_protocol",
                "bootstrap_memory",
            ],
            "description": "返回 AICTO CTO 能力矩阵、运行手册、证据门、来源依据、军团协议或写入基础记忆。",
        },
        "capability": {"type": "string"},
        "decision_type": {
            "type": "string",
            "enum": [
                "technical_plan",
                "authorization",
                "release",
                "security_exception",
                "cross_project_borrow",
                "ai_agent_tooling",
                "l1_directive",
            ],
        },
        "project_id": {"type": "string"},
        "project_name": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "ref": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "record_memory": {"type": "boolean"},
        "force": {"type": "boolean"},
    },
}

LEGION_SYSTEM_MAINTENANCE = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "scan",
                "follow_up_active",
                "record_summary",
                "ack_status",
                "escalate_overdue_acks",
            ],
            "description": "scan 扫描军团系统；follow_up_active 跟进活动/阻塞任务；record_summary 写入长期数据治理总结；ack_status 检查 CTO 指令回执；escalate_overdue_acks 升级超时未 ACK 指令。",
        },
        "project": {"type": "string", "description": "可选，按项目名过滤 follow_up_active。"},
        "commander_id": {"type": "string"},
        "dry_run": {"type": "boolean", "description": "follow_up_active 默认 true；false 时真实发送。"},
        "max_targets": {"type": "integer"},
        "max_projects": {"type": "integer"},
        "include_idle": {"type": "boolean"},
        "ack_timeout_minutes": {"type": "number"},
        "lookback_hours": {"type": "number"},
    },
}

REQUIREMENT_METADATA_GATE = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["validate", "template"],
            "description": "validate 校验需求元数据；template 返回 AICTO 可接受的原子 PRD 模板。",
        },
        "prd_markdown": {
            "type": "string",
            "description": "待校验的 PRD markdown 文本。",
        },
        "prd_content": {
            "type": "string",
            "description": "prd_markdown 的别名，兼容已有上下文字段。",
        },
        "requirement_metadata": {
            "type": "object",
            "description": "结构化需求元数据，优先于 markdown 解析。",
        },
        "title": {"type": "string", "description": "template action 使用的标题。"},
        "requirement_id": {
            "type": "string",
            "description": "template action 使用的需求 ID。",
        },
    },
}

AIPM_CTO_COLLABORATION = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "workflow_contract",
                "request_requirement_clarification",
                "deliver_acceptance_to_aipm",
            ],
            "description": "workflow_contract 返回 AIPM/AICTO 协作契约；request_requirement_clarification 请求 AIPM 澄清/向用户确认；deliver_acceptance_to_aipm 交付 AICTO 技术验收包给 AIPM。",
        },
        "project_id": {"type": "string"},
        "project_name": {"type": "string"},
        "prd_id": {"type": "string"},
        "requirement_id": {"type": "string"},
        "title": {"type": "string"},
        "scope": {"type": "string"},
        "summary": {"type": "string"},
        "missing_info": {"type": "array", "items": {"type": "string"}},
        "missing_required_sections": {"type": "array", "items": {"type": "string"}},
        "conflict_notes": {"type": "array", "items": {"type": "string"}},
        "conflict_or_unconfirmed_sections": {"type": "array", "items": {"type": "string"}},
        "requires_user_confirmation": {"type": "boolean"},
        "aipm_clarification_protocol": {"type": "object"},
        "evidence": {
            "type": "array",
            "description": "AICTO 向 AIPM 交付验收时必须提供：军团交付/测试构建/评审验收证据。",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "ref": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
        "target_chat_id": {
            "type": "string",
            "description": "AIPM 飞书 chat_id；默认读 AICTO_PM_FEISHU_CHAT_ID。",
        },
        "dry_run": {
            "type": "boolean",
            "description": "只生成消息，不实际发送飞书。",
        },
        "record_memory": {
            "type": "boolean",
            "description": "是否写 AICTO 长期记忆，默认 true。",
        },
    },
}
