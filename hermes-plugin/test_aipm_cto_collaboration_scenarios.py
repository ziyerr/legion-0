"""AIPM ↔ AICTO collaboration scenario tests.

These tests validate the cross-project handoff behavior instead of only
checking individual helper functions.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "hermes-plugin"
PKG_NAME = "aicto"


def _bootstrap_package():
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]
    spec = importlib.util.spec_from_file_location(
        PKG_NAME,
        str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    module.__path__ = [str(PLUGIN_DIR)]
    sys.modules[PKG_NAME] = module
    return module


def _load_submodule(name: str):
    full_name = f"{PKG_NAME}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    _bootstrap_package()
    spec = importlib.util.spec_from_file_location(
        full_name,
        str(PLUGIN_DIR / f"{name}.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_load_submodule("error_classifier")
_load_submodule("pm_db_api")
_load_submodule("feishu_api")
_load_submodule("adr_storage")
_load_submodule("cto_memory")
aipm_cto_collaboration = _load_submodule("aipm_cto_collaboration")
design_tech_plan = _load_submodule("design_tech_plan")


def _complete_metadata(**overrides):
    metadata = {
        "requirement_id": "REQ-COLLAB-001",
        "requirement_title": "飞书任务卡确认按钮",
        "atomic_object": "feishu.task_card.confirm_button",
        "acceptance_criteria": "Given 任务卡待确认 / When AIPM 点击确认 / Then AICTO 才进入技术方案",
        "user_original_request": "用户要求任何开发任务必须先确认需求再派给军团。",
        "aipm_design_intent": "AIPM 将确认动作设计为飞书任务卡按钮，并保留确认记录。",
        "user_alignment_verdict": "已确认与用户诉求一致",
        "feishu_user_confirmation": "https://feishu.example/message/confirmed",
        "who": "AIPM、AICTO、L1 指挥官",
        "what": "确认需求后触发 AICTO 技术评估",
        "why": "避免未经确认的需求进入军团执行",
        "when": "用户需求收集完成并形成原子 PRD 后",
        "where": "飞书任务卡与 AICTO Hermes 插件",
        "how_business": "AIPM 确认后交给 AICTO；AICTO 门禁通过后才生成技术方案",
        "create": "无",
        "delete": "无",
        "query": "读取 PRD 元数据、用户确认记录、任务卡状态",
        "update": "把任务状态从 draft 改为 ready_for_aicto",
        "display": "显示确认按钮、阻塞原因、验收交付状态",
        "compute": "校验 PRD 元数据是否满足门禁",
        "transmit": "向 AICTO 发送 AIPM_REQUIREMENT_READY 事件",
    }
    metadata.update(overrides)
    return metadata


def _pm_context():
    return {
        "project_id": "project-aicto",
        "project_name": "AICTO",
        "prd_title": "飞书任务卡确认按钮",
        "prd_content": "# 飞书任务卡确认按钮\n\n用户要求任何开发任务必须先确认需求再派给军团。",
        "prd_id_resolved": "prd-collab-001",
        "user_stories": [],
        "features": [],
        "decisions": [],
        "open_questions": [],
    }


def _green_tech_plan():
    return {
        "feasibility": "green",
        "improvement_path": None,
        "summary": "需求已确认，可复用现有 AICTO Hermes 插件链路实现。",
        "tech_stack": [
            {
                "component": "requirement_gate",
                "choice": "AICTO Hermes plugin",
                "reason": "现有插件已承载门禁、ADR 和飞书输出。",
                "alternatives_considered": [
                    {"option": "独立服务", "rejected_reason": "会增加跨系统部署和状态同步成本。"},
                    {"option": "直接改 AIPM PRD", "rejected_reason": "违反 AIPM/AICTO 独立项目边界。"},
                ],
            }
        ],
        "estimate": {"optimistic": 1, "likely": 2, "pessimistic": 3, "unit": "days"},
        "risks": [],
        "missing_info": [],
    }


class TestAipmCtoCollaborationScenarios(unittest.TestCase):
    def test_scenario_unclear_prd_blocks_before_technical_plan_and_returns_to_aipm(self):
        metadata = _complete_metadata()
        metadata.pop("transmit")

        with mock.patch.object(
            design_tech_plan,
            "_step1_load_prd_context",
            return_value=_pm_context(),
        ), mock.patch.object(design_tech_plan, "_step4_llm_design") as llm_design:
            result = json.loads(
                design_tech_plan.run(
                    {
                        "prd_markdown": _pm_context()["prd_content"],
                        "requirement_metadata": metadata,
                        "dry_run_aipm_clarification": True,
                        "record_memory": False,
                    }
                )
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["blocking_downstream"])
        self.assertEqual(result["requirement_gate"]["gate_status"], "fail")
        self.assertEqual(
            result["aipm_clarification"]["aicto_state"],
            "blocked_waiting_aipm_prd_update",
        )
        self.assertEqual(result["aipm_clarification"]["next_owner"], "AIPM")
        self.assertTrue(result["aipm_clarification"]["notification"]["dry_run"])
        self.assertIn("更新原子 PRD 元数据", result["aipm_clarification"]["message"])
        llm_design.assert_not_called()

    def test_scenario_user_alignment_conflict_forces_aipm_feishu_confirmation(self):
        metadata = _complete_metadata(
            user_alignment_verdict="AIPM 尚未与用户确认，设计方向可能与用户诉求相悖"
        )

        with mock.patch.object(
            design_tech_plan,
            "_step1_load_prd_context",
            return_value=_pm_context(),
        ), mock.patch.object(design_tech_plan, "_step4_llm_design") as llm_design:
            result = json.loads(
                design_tech_plan.run(
                    {
                        "prd_markdown": _pm_context()["prd_content"],
                        "requirement_metadata": metadata,
                        "dry_run_aipm_clarification": True,
                        "record_memory": False,
                    }
                )
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["blocking_downstream"])
        self.assertTrue(result["requirement_gate"]["requires_user_feishu_confirmation"])
        self.assertEqual(
            result["aipm_clarification"]["aicto_state"],
            "blocked_waiting_aipm_user_confirmation",
        )
        self.assertTrue(result["aipm_clarification"]["requires_user_confirmation"])
        self.assertIn("用户对齐风险", result["aipm_clarification"]["message"])
        self.assertIn("飞书中向用户确认", result["aipm_clarification"]["message"])
        llm_design.assert_not_called()

    def test_scenario_clarified_prd_enters_technical_plan_without_aipm_clarification(self):
        with mock.patch.object(
            design_tech_plan,
            "_step1_load_prd_context",
            return_value=_pm_context(),
        ), mock.patch.object(
            design_tech_plan,
            "_step4_llm_design",
            return_value=_green_tech_plan(),
        ) as llm_design, mock.patch.object(
            design_tech_plan.adr_storage,
            "list_adrs",
            return_value=[],
        ), mock.patch.object(
            design_tech_plan.adr_storage,
            "create_adr",
            return_value={"id": "adr-001", "display_number": 1},
        ), mock.patch.object(
            design_tech_plan.feishu_api,
            "create_docx",
            return_value={"document_id": "doc-001", "url": "https://feishu.example/doc/doc-001"},
        ), mock.patch.object(
            design_tech_plan.aipm_cto_collaboration,
            "request_requirement_clarification",
        ) as request_clarification:
            result = json.loads(
                design_tech_plan.run(
                    {
                        "prd_markdown": _pm_context()["prd_content"],
                        "requirement_metadata": _complete_metadata(),
                        "record_memory": False,
                    }
                )
            )

        self.assertTrue(result["success"])
        self.assertFalse(result["blocking_downstream"])
        self.assertEqual(result["requirement_gate"]["gate_status"], "pass")
        self.assertEqual(result["feishu_doc_url"], "https://feishu.example/doc/doc-001")
        self.assertEqual(result["adr_ids"], ["adr-001"])
        self.assertEqual(result["tech_stack"][0]["adr_id"], "adr-001")
        llm_design.assert_called_once()
        request_clarification.assert_not_called()

    def test_scenario_acceptance_delivery_blocks_if_review_evidence_missing(self):
        result = json.loads(
            aipm_cto_collaboration.run(
                {
                    "action": "deliver_acceptance_to_aipm",
                    "project_name": "AICTO",
                    "scope": "飞书任务卡确认按钮",
                    "summary": "L1/L2 已完成实现和测试，但缺少独立评审验收记录。",
                    "evidence": [
                        {"source": "l1_report", "ref": "delivery-001", "detail": "legion delivery report"},
                        {"source": "unittest", "ref": "133 tests OK", "detail": "test output"},
                    ],
                    "dry_run": True,
                    "record_memory": False,
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["blocking_downstream"])
        self.assertEqual(result["next_owner"], "AICTO")
        self.assertEqual(result["handoff_status"], "blocked_missing_acceptance_evidence")
        self.assertEqual(result["missing_evidence"], ["review/acceptance result"])

    def test_scenario_acceptance_delivery_hands_product_validation_to_aipm(self):
        result = json.loads(
            aipm_cto_collaboration.run(
                {
                    "action": "deliver_acceptance_to_aipm",
                    "project_name": "AICTO",
                    "prd_id": "prd-collab-001",
                    "scope": "飞书任务卡确认按钮",
                    "summary": "军团开发、构建测试和评审验收均已通过。",
                    "evidence": [
                        {"source": "l1_report", "ref": "delivery-001", "detail": "legion delivery report"},
                        {"source": "pytest", "ref": "133 tests OK", "detail": "test/build output"},
                        {"source": "review", "ref": "review-001", "detail": "acceptance result passed"},
                    ],
                    "target_chat_id": "oc_aipm_chat",
                    "dry_run": True,
                    "record_memory": False,
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["blocking_downstream"])
        self.assertEqual(result["next_owner"], "AIPM")
        self.assertEqual(result["handoff_status"], "delivered_to_aipm")
        self.assertEqual(result["notification"]["target_chat_id"], "oc_aipm_chat")
        self.assertIn("产品验收", "\n".join(result["aipm_required_actions"]))
        self.assertIn("开发验收交付", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
