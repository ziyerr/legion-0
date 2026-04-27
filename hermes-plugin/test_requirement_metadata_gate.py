"""requirement_metadata_gate tests."""
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
    mod = importlib.util.module_from_spec(spec)
    mod.__path__ = [str(PLUGIN_DIR)]
    sys.modules[PKG_NAME] = mod
    return mod


def _load_submodule(name: str):
    full = f"{PKG_NAME}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    _bootstrap_package()
    spec = importlib.util.spec_from_file_location(
        full,
        str(PLUGIN_DIR / f"{name}.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


_load_submodule("error_classifier")
_load_submodule("pm_db_api")
_load_submodule("feishu_api")
_load_submodule("adr_storage")
_load_submodule("cto_memory")
aipm_cto_collaboration = _load_submodule("aipm_cto_collaboration")
requirement_metadata_gate = _load_submodule("requirement_metadata_gate")
design_tech_plan = _load_submodule("design_tech_plan")


def _complete_metadata():
    return {
        "requirement_id": "REQ-AICTO-001",
        "requirement_title": "新增任务卡确认按钮",
        "atomic_object": "任务卡 footer.confirm_button",
        "acceptance_criteria": "Given 有待确认任务 / When 点击确认 / Then 状态变为 confirmed",
        "user_original_request": "用户要求任务卡确认后才允许进入开发。",
        "aipm_design_intent": "AIPM 将确认动作设计为飞书任务卡 footer 按钮。",
        "user_alignment_verdict": "已确认与用户诉求一致",
        "feishu_user_confirmation": "https://feishu.example/message/abc",
        "who": "AIPM",
        "what": "确认任务卡进入 AICTO 技术评估",
        "why": "避免需求未经确认直接派给军团",
        "when": "AIPM 在飞书提交任务卡后",
        "where": "飞书任务卡 footer",
        "how_business": "AIPM 点击确认后，AICTO 才进入 design_tech_plan",
        "create": "无",
        "delete": "无",
        "query": "读取任务卡状态和操作者",
        "update": "把任务状态从 draft 改为 confirmed",
        "display": "显示确认按钮、确认后显示已确认",
        "compute": "校验操作者是否为需求负责人",
        "transmit": "发送 confirmed 事件给 AICTO",
    }


class TestRequirementMetadataGate(unittest.TestCase):
    def test_template_contains_all_required_dimensions(self):
        result = json.loads(
            requirement_metadata_gate.run({"action": "template", "title": "按钮需求"})
        )

        self.assertTrue(result["success"])
        template = result["markdown_template"]
        for label in ["需求ID", "需求标题", "用户原始诉求", "AIPM设计思路", "飞书用户确认记录", "Who/谁", "增", "删", "查", "改", "显", "算", "传"]:
            self.assertIn(label, template)

    def test_missing_dimensions_fail_with_clarification(self):
        result = json.loads(
            requirement_metadata_gate.run(
                {
                    "action": "validate",
                    "requirement_metadata": {
                        "requirement_id": "REQ-1",
                        "requirement_title": "只有标题",
                    },
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["passes"])
        self.assertEqual(result["gate_status"], "fail")
        self.assertIn("原子对象", result["missing_required_sections"])
        self.assertGreater(len(result["clarification_request"]), 1)

    def test_explicit_none_passes_for_not_applicable_dimensions(self):
        metadata = _complete_metadata()
        for key in ["create", "delete"]:
            self.assertEqual(metadata[key], "无")

        result = json.loads(
            requirement_metadata_gate.run(
                {"action": "validate", "requirement_metadata": metadata}
            )
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["passes"])
        self.assertEqual(result["gate_status"], "pass")
        self.assertIn("增", result["explicit_none_sections"])
        self.assertIn("删", result["explicit_none_sections"])

    def test_unknown_values_fail(self):
        metadata = _complete_metadata()
        metadata["transmit"] = "待定"

        result = json.loads(
            requirement_metadata_gate.run(
                {"action": "validate", "requirement_metadata": metadata}
            )
        )

        self.assertFalse(result["passes"])
        self.assertIn("传", result["blank_or_unknown_sections"])

    def test_user_alignment_conflict_requires_aipm_user_confirmation(self):
        metadata = _complete_metadata()
        metadata["user_alignment_verdict"] = "AIPM 尚未和用户确认，设计可能与用户诉求相悖"

        result = json.loads(
            requirement_metadata_gate.run(
                {"action": "validate", "requirement_metadata": metadata}
            )
        )

        self.assertFalse(result["passes"])
        self.assertTrue(result["requires_user_feishu_confirmation"])
        self.assertIn("用户一致性判断", result["conflict_or_unconfirmed_sections"])
        self.assertEqual(result["aipm_clarification_protocol"]["next_owner"], "AIPM")

    def test_markdown_sections_can_satisfy_gate(self):
        result = json.loads(
            requirement_metadata_gate.run(
                {
                    "action": "validate",
                    "prd_markdown": """
# 新增任务卡确认按钮

需求ID：REQ-AICTO-001
需求标题：新增任务卡确认按钮
原子对象：任务卡 footer.confirm_button
验收标准：Given 有待确认任务 / When 点击确认 / Then 状态变为 confirmed
用户原始诉求：用户要求任务卡确认后才允许进入开发
AIPM设计思路：AIPM 将确认动作设计为飞书任务卡 footer 按钮
用户一致性判断：已确认与用户诉求一致
飞书用户确认记录：https://feishu.example/message/abc
Who/谁：AIPM
What/做什么：确认任务卡进入 AICTO 技术评估
Why/为什么：避免需求未经确认直接派给军团
When/何时：AIPM 在飞书提交任务卡后
Where/哪里：飞书任务卡 footer
How/业务流程：AIPM 点击确认后，AICTO 才进入 design_tech_plan
增：无
删：无
查：读取任务卡状态和操作者
改：把任务状态从 draft 改为 confirmed
显：显示确认按钮、确认后显示已确认
算：校验操作者是否为需求负责人
传：发送 confirmed 事件给 AICTO
""",
                }
            )
        )

        self.assertTrue(result["passes"])


class TestDesignTechPlanRequirementGate(unittest.TestCase):
    def test_design_tech_plan_blocks_before_llm_when_gate_fails(self):
        with mock.patch.object(
            design_tech_plan,
            "_step1_load_prd_context",
            return_value={
                "project_id": "p1",
                "project_name": "AICTO",
                "prd_title": "裸需求",
                "prd_content": "帮我加一个按钮",
                "prd_id_resolved": "prd1",
                "user_stories": [],
                "features": [],
                "decisions": [],
                "open_questions": [],
            },
        ), mock.patch.object(design_tech_plan, "_step4_llm_design") as llm:
            result = json.loads(
                design_tech_plan.run(
                    {
                        "prd_markdown": "帮我加一个按钮",
                        "dry_run_aipm_clarification": True,
                        "record_memory": False,
                    }
                )
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["blocking_downstream"])
        self.assertEqual(result["requirement_gate"]["gate_status"], "fail")
        self.assertEqual(result["aipm_clarification"]["next_owner"], "AIPM")
        self.assertEqual(result["tech_stack"], [])
        llm.assert_not_called()


class TestAipmCtoCollaboration(unittest.TestCase):
    def test_workflow_contract_keeps_projects_independent(self):
        result = json.loads(
            aipm_cto_collaboration.run({"action": "workflow_contract"})
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["contract"]["independent_projects"])
        self.assertIn("AIPM/ProdMind", result["contract"]["projects"])
        self.assertIn("AICTO", result["contract"]["projects"])

    def test_clarification_request_targets_aipm(self):
        result = json.loads(
            aipm_cto_collaboration.run(
                {
                    "action": "request_requirement_clarification",
                    "project_name": "AICTO",
                    "prd_id": "prd1",
                    "requirement_id": "REQ-1",
                    "missing_info": ["缺少用户确认记录"],
                    "requires_user_confirmation": True,
                    "dry_run": True,
                    "record_memory": False,
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["next_owner"], "AIPM")
        self.assertTrue(result["blocking_downstream"])
        self.assertIn("飞书中向用户确认", result["message"])

    def test_acceptance_delivery_requires_evidence(self):
        result = json.loads(
            aipm_cto_collaboration.run(
                {
                    "action": "deliver_acceptance_to_aipm",
                    "project_name": "AICTO",
                    "dry_run": True,
                    "record_memory": False,
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["handoff_status"], "blocked_missing_acceptance_evidence")
        self.assertTrue(result["blocking_downstream"])

    def test_acceptance_delivery_passes_with_full_evidence(self):
        result = json.loads(
            aipm_cto_collaboration.run(
                {
                    "action": "deliver_acceptance_to_aipm",
                    "project_name": "AICTO",
                    "summary": "军团已完成开发并通过测试验收",
                    "evidence": [
                        {"source": "l1_report", "ref": "delivery-1", "detail": "legion delivery report"},
                        {"source": "test", "ref": "unittest", "detail": "128 tests OK"},
                        {"source": "review", "ref": "acceptance", "detail": "acceptance passed"},
                    ],
                    "dry_run": True,
                    "record_memory": False,
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["handoff_status"], "delivered_to_aipm")
        self.assertEqual(result["next_owner"], "AIPM")


if __name__ == "__main__":
    unittest.main(verbosity=2)
