"""portfolio_manager / dispatch project routing tests.

运行：
    cd /Users/feijun/Documents/AICTO
    /Users/feijun/.hermes/hermes-agent/venv/bin/python3 \
        hermes-plugin/test_portfolio_manager.py
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
legion_api = _load_submodule("legion_api")
portfolio_manager = _load_submodule("portfolio_manager")
_load_submodule("design_tech_plan")
dispatch_balanced = _load_submodule("dispatch_balanced")


def _commander(commander_id: str, legion_project: str):
    return legion_api.Commander(
        legion_hash=legion_project.lower().replace(" ", "-")[:8] or "hash0000",
        legion_project=legion_project,
        commander_id=commander_id,
        task="1级指挥官",
        started_at="2026-04-27T10:00:00Z",
        tmux_alive=True,
        tmux_session=f"legion-test-{commander_id}",
        inbox_path=Path(f"/tmp/aicto-test/{commander_id}.json"),
    )


def _task(task_id: str = "T1"):
    return {
        "id": task_id,
        "title": "实现项目能力",
        "size": "M",
        "depends_on": [],
        "acceptance_gwt": {
            "given": "项目已有 PRD",
            "when": "军团完成实现",
            "then": "验收通过",
        },
        "tech_stack_link": ["python"],
    }


class TestPortfolioRouting(unittest.TestCase):
    def test_rank_prefers_project_bound_legion(self):
        commanders = [
            _commander("L1-AICTO", "AICTO"),
            _commander("L1-CartCast", "CartCast"),
        ]
        with mock.patch.object(
            portfolio_manager,
            "_load_one_pm_project",
            return_value={"project_id": "p1", "name": "AI CTO - 程小远"},
        ):
            ranked, affinity, warnings = portfolio_manager.rank_commanders_for_project(
                project_id="p1",
                commanders=commanders,
            )

        self.assertEqual([c.commander_id for c in ranked], ["L1-AICTO"])
        self.assertGreaterEqual(
            affinity["L1-AICTO"]["project_match_score"],
            portfolio_manager.PROJECT_MATCH_THRESHOLD,
        )
        self.assertTrue(affinity["L1-CartCast"]["cross_project_borrowed"])
        self.assertEqual(warnings, [])

    def test_rank_blocks_cross_project_borrow_by_default(self):
        commanders = [_commander("L1-CartCast", "CartCast")]
        with mock.patch.object(
            portfolio_manager,
            "_load_one_pm_project",
            return_value={"project_id": "p1", "name": "AI CTO - 程小远"},
        ):
            ranked, _affinity, warnings = portfolio_manager.rank_commanders_for_project(
                project_id="p1",
                commanders=commanders,
            )

        self.assertEqual(ranked, [])
        self.assertIn("no project-bound legion", warnings[0])

    def test_build_portfolio_matches_project_to_legion(self):
        projects = [
            {
                "project_id": "p1",
                "name": "AI CTO - 程小远",
                "status": "development",
                "stage": "prd_done",
                "mode": "undecided",
                "updated_at": "2026-04-27T00:00:00Z",
                "created_at": "2026-04-27T00:00:00Z",
                "pm_context": {
                    "prd_count": 1,
                    "feature_count": 2,
                    "user_story_count": 3,
                    "open_question_count": 0,
                },
                "cto_state": {
                    "adr_count": 1,
                    "open_risk_count": 0,
                    "open_debt_count": 0,
                    "blocking_review_count": 0,
                },
            }
        ]
        legions = [
            {
                "legion_hash": "aicto001",
                "legion_project": "AICTO",
                "path": "/Users/feijun/Documents/AICTO",
                "last_active": "2026-04-27T00:00:00Z",
                "commander_count": 1,
                "active_commander_count": 1,
                "online_commander_count": 1,
                "pending_ai_cto_tasks": 0,
                "stale_pending_tasks": 0,
                "commanders": [],
            }
        ]
        with mock.patch.object(portfolio_manager, "_load_pm_projects", return_value=projects), \
             mock.patch.object(portfolio_manager, "_load_legion_projects", return_value=legions):
            payload = portfolio_manager.build_portfolio({})

        self.assertEqual(payload["summary"]["project_count"], 1)
        self.assertEqual(payload["projects"][0]["health"], "green")
        self.assertEqual(payload["projects"][0]["legions"][0]["legion_project"], "AICTO")


class TestDispatchProjectGuard(unittest.TestCase):
    def _patch_dispatch_context(self, commanders, project_name="AI CTO - 程小远"):
        return [
            mock.patch.object(
                dispatch_balanced.pm_db_api,
                "read_pm_project",
                return_value=json.dumps(
                    {"success": True, "project": {"id": "p1", "name": project_name}},
                    ensure_ascii=False,
                ),
            ),
            mock.patch.object(
                dispatch_balanced.pm_db_api,
                "get_pm_context_for_tech_plan",
                return_value=json.dumps(
                    {
                        "success": True,
                        "prd_id": "prd1",
                        "prd": {"title": "PRD", "content": "PRD content"},
                    },
                    ensure_ascii=False,
                ),
            ),
            mock.patch.object(dispatch_balanced.adr_storage, "list_adrs", return_value=[]),
            mock.patch.object(
                dispatch_balanced.legion_api,
                "discover_online_commanders",
                return_value=commanders,
            ),
            mock.patch.object(
                dispatch_balanced.portfolio_manager,
                "_load_one_pm_project",
                return_value={"project_id": "p1", "name": project_name},
            ),
        ]

    def test_dispatch_blocks_wrong_project_legion_by_default(self):
        commanders = [_commander("L1-CartCast", "CartCast")]
        patches = self._patch_dispatch_context(commanders)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             mock.patch.object(dispatch_balanced.legion_api, "send_to_commander") as send:
            result = json.loads(dispatch_balanced.run({"project_id": "p1", "tasks": [_task()]}))

        self.assertIn("error", result)
        self.assertIn("no project-bound legion", result["error"])
        send.assert_not_called()

    def test_dispatch_allows_explicit_cross_project_borrow(self):
        commanders = [_commander("L1-CartCast", "CartCast")]
        patches = self._patch_dispatch_context(commanders)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             mock.patch.object(
                 dispatch_balanced.legion_api,
                 "send_to_commander",
                 return_value={
                     "message_id": "msg-1",
                     "inbox_path": "/tmp/inbox.json",
                     "tmux_session": "legion-test",
                     "tmux_notified": True,
                 },
             ):
            result = json.loads(
                dispatch_balanced.run(
                    {
                        "project_id": "p1",
                        "tasks": [_task()],
                        "allow_cross_project_borrow": True,
                    }
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["assignments"][0]["legion_id"], "L1-CartCast")
        self.assertTrue(result["assignments"][0]["cross_project_borrowed"])
        self.assertEqual(result["all_online_legion_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
