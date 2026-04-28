import asyncio
import importlib
import subprocess
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "claw-roundtable-skill"
CODEX_BRIDGE = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "claw-roundtable-skill" / "SKILL.md"


class RoundTableSkillTests(unittest.TestCase):
    def setUp(self):
        self._old_path = list(sys.path)
        sys.path.insert(0, str(SKILL_DIR))

    def tearDown(self):
        sys.path[:] = self._old_path

    def test_roundtable_health_base_check_passes(self):
        completed = subprocess.run(
            [sys.executable, str(SKILL_DIR / "roundtable_health.py")],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("OK files", completed.stdout)
        self.assertIn("OK agents", completed.stdout)
        self.assertIn("OK analyze", completed.stdout)

    def test_roundtable_engine_fails_fast_when_runtime_missing(self):
        module = importlib.import_module("roundtable_engine_v2")
        previous_openclaw = sys.modules.get("openclaw", None)
        previous_openclaw_tools = sys.modules.get("openclaw.tools", None)
        had_openclaw = "openclaw" in sys.modules
        had_openclaw_tools = "openclaw.tools" in sys.modules
        sys.modules["openclaw"] = None
        sys.modules.pop("openclaw.tools", None)
        try:
            engine = module.RoundTableEngineV2(
                "低复杂度：API 设计",
                complexity="low",
                custom_experts=["engineering-code-reviewer"],
            )
            result = asyncio.run(engine.run("test"))
        finally:
            if had_openclaw:
                sys.modules["openclaw"] = previous_openclaw
            else:
                sys.modules.pop("openclaw", None)
            if had_openclaw_tools:
                sys.modules["openclaw.tools"] = previous_openclaw_tools
            else:
                sys.modules.pop("openclaw.tools", None)

        self.assertFalse(result)
        self.assertEqual(engine.state, module.DiscussionState.FAILED)

    def test_roundtable_analyzer_works_with_skill_path(self):
        module = importlib.import_module("roundtable_engine_v2")

        result = module.analyze_requirement("圆桌会议 讨论 Legion 架构、安全、用户体验")

        self.assertIn("architecture", result["detected_types"])
        self.assertTrue(result["recommended_experts"])


    def test_roundtable_runtime_defaults_to_codex_backend(self):
        tools = importlib.import_module("openclaw.tools")

        info = tools.runtime_available()

        self.assertEqual(info["backend"], "codex")
        self.assertIn("codex", Path(info["command"]).name)

    def test_codex_bridge_skill_exposes_roundtable_to_agents_skills(self):
        content = CODEX_BRIDGE.read_text(encoding="utf-8")

        self.assertIn("name: claw-roundtable-skill", content)
        self.assertIn("roundtable_health.py --require-runtime", content)
        self.assertIn("Legion Core `mixed campaign --corps`", content)


if __name__ == "__main__":
    unittest.main()
