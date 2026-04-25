"""AICTO Phase 1 tool implementations — 16 tools dispatch.

Phase 1 实施进度（详见 .planning/phase1/specs/PHASE-PLAN.md）：

- ✅ P1.1（已完成）：8 PM 只读工具 + 2 综合工具 → 接入 pm_db_api 真实实现
- ✅ P1.2（已完成）：design_tech_plan → 接入 design_tech_plan.run（6 步推理链 + KR4 SLA）
- ✅ P1.3（已完成）：breakdown_tasks → 接入 breakdown_tasks.run（4 步推理链 + DAG）
- ✅ P1.4（已完成）：dispatch_to_legion_balanced → 接入 dispatch_balanced.run（5 步推理链 + 双通道）
- ✅ P1.5（已完成）：kickoff_project → 接入 kickoff_project.run（8 步串联 + 30s SLA）
- 🚧 P1.6 ~ P1.7：2 个核心能力（review_code / daily_brief）—— 仍为 stub

stub 透明纪律：未实现的工具必须明确返回 not_implemented，不得伪造成功。
违反此纪律 = 反幻觉 5 条违规（详见 SOUL.md / __init__.py hook）。
"""
import json

from . import breakdown_tasks as _breakdown_tasks
from . import design_tech_plan as _design_tech_plan
from . import dispatch_balanced as _dispatch_balanced
from . import kickoff_project as _kickoff_project
from . import pm_db_api


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
    """能力 4：10 项审查 + BLOCKING 硬 gate + appeal 通道。计划 P1.6 阶段实现。"""
    return _not_implemented("review_code", args, phase="P1.6")


def daily_brief(args, **kwargs):
    """能力 5：18:00 摘要 + BLOCKING 即时 + 24h 催促。计划 P1.7 阶段实现。"""
    return _not_implemented("daily_brief", args, phase="P1.7")


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
