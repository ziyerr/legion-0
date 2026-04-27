"""AICTO Phase 1 tool implementations — 24 tools dispatch.

Phase 1 实施进度（详见 .planning/phase1/specs/PHASE-PLAN.md）：

- ✅ P1.1（已完成）：8 PM 只读工具 + 2 综合工具 → 接入 pm_db_api 真实实现
- ✅ P1.2（已完成）：design_tech_plan → 接入 design_tech_plan.run（6 步推理链 + KR4 SLA）
- ✅ P1.3（已完成）：breakdown_tasks → 接入 breakdown_tasks.run（4 步推理链 + DAG）
- ✅ P1.4（已完成）：dispatch_to_legion_balanced → 接入 dispatch_balanced.run（5 步推理链 + 双通道）
- ✅ P1.5（已完成）：kickoff_project → 接入 kickoff_project.run（8 步串联 + 30s SLA）
- ✅ P1.6（已完成）：review_code → 接入 review_code.run（5 步 + 10 项 + BLOCKING 硬 gate + appeal）
- ✅ P1.7（已完成）：daily_brief → 接入 daily_brief.run（4 触发 + cron + 24h 催促）
- ✅ P1.8（已完成）：legion_portfolio_status → 多项目军团组合态 + 项目归属健康检查
- ✅ P1.9（已完成）：CTO 独立记忆 + L1 指挥中枢
- ✅ P1.10（已完成）：cto_operating_model → CTO 专业知识/方法/证据门/军团协议运行时工具
- ✅ P1.11（已完成）：legion_system_maintenance → 军团系统维护 + 长期数据治理
- ✅ P1.12（已完成）：requirement_metadata_gate → AICTO 需求元数据硬门禁
- ✅ P1.13（已完成）：aipm_cto_collaboration → AIPM/AICTO 独立项目协作协议

stub 透明纪律：未实现的工具必须明确返回 not_implemented，不得伪造成功。
违反此纪律 = 反幻觉 5 条违规（详见 SOUL.md / __init__.py hook）。
"""
import json

from . import breakdown_tasks as _breakdown_tasks
from . import aipm_cto_collaboration as _aipm_cto_collaboration
from . import cto_memory as _cto_memory
from . import cto_operating_model as _cto_operating_model
from . import daily_brief as _daily_brief
from . import design_tech_plan as _design_tech_plan
from . import dispatch_balanced as _dispatch_balanced
from . import kickoff_project as _kickoff_project
from . import legion_command_center as _legion_command_center
from . import legion_system_maintenance as _legion_system_maintenance
from . import pm_db_api
from . import portfolio_manager as _portfolio_manager
from . import requirement_metadata_gate as _requirement_metadata_gate
from . import review_code as _review_code


def _not_implemented(name: str, args: dict, phase: str = "TBD") -> str:
    """Canonical stub — 未实现工具统一返回此结构."""
    return json.dumps(
        {
            "status": "not_implemented",
            "tool": name,
            "phase": phase,
            "message": f"AICTO.{name} 还未实现（计划在 {phase} 阶段落地）。",
            "received_args": args,
            "next_step": (
                "本工具是 Phase 1 全量开发的一部分。"
                "查看 .planning/phase1/specs/PHASE-PLAN.md 了解实施进度。"
            ),
        },
        ensure_ascii=False,
    )


# ============================================================================
# 6 个核心能力（PM 派发）—— P1.2 ~ P1.7 阶段陆续实现
# ============================================================================

def kickoff_project(args, **kwargs):
    """能力 0：项目启动自动化（8 步串联，30s SLA）。

    P1.5 已上线。8 步推理链委托给 kickoff_project.run（独立模块）：
      mkdir → git init → PM HTTP → ADR-0001 → 拉军团 → mailbox → 派任务 → 飞书卡片
    详见 .planning/phase1/specs/PHASE-PLAN.md §6 + REQUIREMENTS.md §1.1。
    """
    return _kickoff_project.run(args, **kwargs)


def design_tech_plan(args, **kwargs):
    """能力 1：PRD → feasibility + 技术栈 + 风险 + 飞书文档（KR4 ≤5 分钟 SLA）。

    P1.2 已上线。6 步推理链委托给 design_tech_plan.run（独立模块）。
    详见 .planning/phase1/specs/PHASE-PLAN.md §3 + ARCHITECTURE.md §1。
    """
    return _design_tech_plan.run(args, **kwargs)


def breakdown_tasks(args, **kwargs):
    """能力 2：技术方案 → 任务 DAG + Given/When/Then。

    P1.3 已上线。4 步推理链委托给 breakdown_tasks.run（独立模块）。
    详见 .planning/phase1/specs/PHASE-PLAN.md §4 + REQUIREMENTS.md §1.3。
    """
    return _breakdown_tasks.run(args, **kwargs)


def dispatch_to_legion_balanced(args, **kwargs):
    """能力 3：智能调度（负载均衡 + DAG 拓扑延派 + 双通道派单）。

    P1.4 已上线。5 步推理链委托给 dispatch_balanced.run（独立模块）。
    详见 .planning/phase1/specs/PHASE-PLAN.md §5 + REQUIREMENTS.md §1.4。
    """
    return _dispatch_balanced.run(args, **kwargs)


def review_code(args, **kwargs):
    """能力 4：10 项审查 + BLOCKING 硬 gate + appeal 通道。

    P1.6 已上线。5 步推理链委托给 review_code.run（独立模块）：
      gh pr diff → tech_plan/PRD 上下文 → LLM 10 项 → 评论密度兜底 →
      写 CodeReview 表 + 飞书 BLOCKING 卡片
    详见 .planning/phase1/specs/PHASE-PLAN.md §7 + REQUIREMENTS.md §1.5。
    """
    return _review_code.run(args, **kwargs)


def daily_brief(args, **kwargs):
    """能力 5：18:00 摘要 + BLOCKING 即时 + 24h 催促 + 09:00 补发。

    P1.7 已上线。4 触发分流委托给 daily_brief.run（独立模块）：
      scheduled / blocking_push / stale_alert / manual
    cron 调度由 cron_runner.daily_brief_loop 在 plugin register 时启动后台 thread。
    详见 .planning/phase1/specs/PHASE-PLAN.md §8 + REQUIREMENTS.md §1.6。
    """
    return _daily_brief.run(args, **kwargs)


def legion_portfolio_status(args, **kwargs):
    """多项目军团组合管理：项目 ↔ 军团归属、在线容量、积压、风险告警。

    P1.8 已上线。默认只读：不启动/停止军团，不写 PM 表。
    该工具是 AICTO 管理多个项目开发军团的事实看板，也为 dispatch 的项目归属过滤
    提供同一套匹配规则。
    """
    return _portfolio_manager.run(args, **kwargs)


def cto_memory_record(args, **kwargs):
    """程小远独立长期记忆写入。

    JSONL 存储，不绑定 Hermes state.db；用于组织契约、项目决策、授权、军团汇报、
    经验教训等可迁移记忆。
    """
    return _cto_memory.record(args, **kwargs)


def cto_memory_query(args, **kwargs):
    """查询程小远独立长期记忆。"""
    return _cto_memory.query(args, **kwargs)


def legion_command_center(args, **kwargs):
    """AICTO ↔ L1 指挥中枢。

    支持收集 L1 outbox 汇报、向 L1 下 CTO 指令、对授权/方案请求做决策。
    """
    return _legion_command_center.run(args, **kwargs)


def cto_operating_model(args, **kwargs):
    """AICTO CTO 专业运行模型。

    将 CTO 能力矩阵、运行手册、权威来源、证据门、L1/L2 协作协议和基础记忆
    作为工具暴露，保证 CTO 行为可审计、可升级、可执行。
    """
    return _cto_operating_model.run(args, **kwargs)


def legion_system_maintenance(args, **kwargs):
    """军团系统维护与长期数据治理。

    扫描真实军团目录、mixed registry、events/outbox/memory，发现重复 commander、
    长期数据未总结、blocked/running 任务堆积，并可向 L1 发起事实跟进。
    """
    return _legion_system_maintenance.run(args, **kwargs)


def requirement_metadata_gate(args, **kwargs):
    """AICTO 需求元数据硬门禁。

    所有进入 AICTO 的需求必须具备原子 PRD 元数据、5W1H，以及
    「增删查改显算传」全量描述；不涉及必须显式写「无」，不得省略。
    """
    return _requirement_metadata_gate.run(args, **kwargs)


def aipm_cto_collaboration(args, **kwargs):
    """AIPM ↔ AICTO 独立项目协作协议。

    支持返回工作流契约、AICTO 主动请求 AIPM 澄清需求，以及 AICTO 将
    军团开发/测试验收包交付给 AIPM 做产品验收和用户汇报。
    """
    return _aipm_cto_collaboration.run(args, **kwargs)


# ============================================================================
# 8 个 PM 只读工具（P1.1 已实现，dispatch 到 pm_db_api）
# ============================================================================

def read_pm_project(args, **kwargs):
    """读 ProdMind Project 行（mode=ro）。"""
    return pm_db_api.read_pm_project(args, **kwargs)


def read_pm_prd(args, **kwargs):
    """读 ProdMind PRD 行（含 PRDVersion 可选）。"""
    return pm_db_api.read_pm_prd(args, **kwargs)


def list_pm_prd_decisions(args, **kwargs):
    """列 PRDDecision 行。"""
    return pm_db_api.list_pm_prd_decisions(args, **kwargs)


def list_pm_open_questions(args, **kwargs):
    """列 PRDOpenQuestion 行（CTO 评估时重点看）。"""
    return pm_db_api.list_pm_open_questions(args, **kwargs)


def list_pm_user_stories(args, **kwargs):
    """列 UserStory 行（acceptanceCriteria / asA / iWant / soThat）。"""
    return pm_db_api.list_pm_user_stories(args, **kwargs)


def list_pm_features(args, **kwargs):
    """列 Feature 行（含 RICE 评分）。"""
    return pm_db_api.list_pm_features(args, **kwargs)


def read_pm_research_doc(args, **kwargs):
    """读 Research 行（市场 / 用户调研）。"""
    return pm_db_api.read_pm_research_doc(args, **kwargs)


def read_pm_evaluation_doc(args, **kwargs):
    """读 Evaluation 行（三层评估）。"""
    return pm_db_api.read_pm_evaluation_doc(args, **kwargs)


# ============================================================================
# 2 个综合工具（P1.1 已实现）
# ============================================================================

def get_pm_context_for_tech_plan(args, **kwargs):
    """一键拉 PRD + UserStories + Features + PRDDecisions + PRDOpenQuestions。"""
    return pm_db_api.get_pm_context_for_tech_plan(args, **kwargs)


def diff_pm_prd_versions(args, **kwargs):
    """对比两个 PRDVersion 的 content diff。"""
    return pm_db_api.diff_pm_prd_versions(args, **kwargs)
