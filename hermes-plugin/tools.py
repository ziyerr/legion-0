"""AICTO Phase 1 tool implementations — 16 tools 骨架.

P1.0 阶段（2026-04-25）：所有 16 工具保持 stub 形态返回 `{"status": "not_implemented"}`，
逐阶段（P1.1 ~ P1.7）替换为真实实现。

stub 透明纪律：未实现的工具必须明确返回 not_implemented，不得伪造成功。
违反此纪律 = 反幻觉 5 条违规（详见 SOUL.md / __init__.py hook）。
"""
import json


def _not_implemented(name: str, args: dict, phase: str = "TBD") -> str:
    """Canonical stub — 16 工具未实现版本统一返回此结构."""
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
# 6 个核心能力（PM 派发）
# ============================================================================

def kickoff_project(args, **kwargs):
    """能力 0：项目启动自动化（8 步串联）。计划 P1.5 阶段实现。"""
    return _not_implemented("kickoff_project", args, phase="P1.5")


def design_tech_plan(args, **kwargs):
    """能力 1：PRD → feasibility + 技术栈 + 风险 + 飞书文档。计划 P1.2 阶段实现。"""
    return _not_implemented("design_tech_plan", args, phase="P1.2")


def breakdown_tasks(args, **kwargs):
    """能力 2：技术方案 → 任务 DAG + Given/When/Then。计划 P1.3 阶段实现。"""
    return _not_implemented("breakdown_tasks", args, phase="P1.3")


def dispatch_to_legion_balanced(args, **kwargs):
    """能力 3：智能调度（负载均衡 + DAG 拓扑延派）。计划 P1.4 阶段实现。"""
    return _not_implemented("dispatch_to_legion_balanced", args, phase="P1.4")


def review_code(args, **kwargs):
    """能力 4：10 项审查 + BLOCKING 硬 gate + appeal 通道。计划 P1.6 阶段实现。"""
    return _not_implemented("review_code", args, phase="P1.6")


def daily_brief(args, **kwargs):
    """能力 5：18:00 摘要 + BLOCKING 即时 + 24h 催促。计划 P1.7 阶段实现。"""
    return _not_implemented("daily_brief", args, phase="P1.7")


# ============================================================================
# 8 个 PM 只读工具
# ============================================================================

def read_pm_project(args, **kwargs):
    """读 ProdMind Project 行（mode=ro）。计划 P1.1 阶段实现。"""
    return _not_implemented("read_pm_project", args, phase="P1.1")


def read_pm_prd(args, **kwargs):
    """读 ProdMind PRD 行（含 PRDVersion 可选）。计划 P1.1 阶段实现。"""
    return _not_implemented("read_pm_prd", args, phase="P1.1")


def list_pm_prd_decisions(args, **kwargs):
    """列 PRDDecision 行。计划 P1.1 阶段实现。"""
    return _not_implemented("list_pm_prd_decisions", args, phase="P1.1")


def list_pm_open_questions(args, **kwargs):
    """列 PRDOpenQuestion 行（CTO 评估时重点看）。计划 P1.1 阶段实现。"""
    return _not_implemented("list_pm_open_questions", args, phase="P1.1")


def list_pm_user_stories(args, **kwargs):
    """列 UserStory 行（acceptanceCriteria / asA / iWant / soThat）。计划 P1.1 阶段实现。"""
    return _not_implemented("list_pm_user_stories", args, phase="P1.1")


def list_pm_features(args, **kwargs):
    """列 Feature 行（含 RICE 评分）。计划 P1.1 阶段实现。"""
    return _not_implemented("list_pm_features", args, phase="P1.1")


def read_pm_research_doc(args, **kwargs):
    """读 Research 行（市场 / 用户调研）。计划 P1.1 阶段实现。"""
    return _not_implemented("read_pm_research_doc", args, phase="P1.1")


def read_pm_evaluation_doc(args, **kwargs):
    """读 Evaluation 行（三层评估）。计划 P1.1 阶段实现。"""
    return _not_implemented("read_pm_evaluation_doc", args, phase="P1.1")


# ============================================================================
# 2 个综合工具
# ============================================================================

def get_pm_context_for_tech_plan(args, **kwargs):
    """一键拉 PRD + UserStories + Features + PRDDecisions + PRDOpenQuestions。计划 P1.1 阶段实现。"""
    return _not_implemented("get_pm_context_for_tech_plan", args, phase="P1.1")


def diff_pm_prd_versions(args, **kwargs):
    """对比两个 PRDVersion 的 content diff。计划 P1.1 阶段实现。"""
    return _not_implemented("diff_pm_prd_versions", args, phase="P1.1")
