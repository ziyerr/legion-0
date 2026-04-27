import tempfile
import unittest
from pathlib import Path

from scripts.codex_skill_budget import (
    SkillBudgetConfig,
    apply_compact_descriptions,
    audit_skills,
    discover_skill_files,
    read_skill_file,
)


class CodexSkillBudgetTests(unittest.TestCase):
    def test_audit_reports_overlong_descriptions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "demo" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text(
                "---\n"
                "name: demo\n"
                "description: This description is intentionally too long for the test budget.\n"
                "---\n"
                "# Demo\n",
                encoding="utf-8",
            )

            report = audit_skills([root], SkillBudgetConfig(max_description_chars=30, budget_chars=120))

            self.assertEqual(report.skill_count, 1)
            self.assertEqual(len(report.overlong_skills), 1)
            self.assertFalse(report.ok)

    def test_apply_compact_descriptions_preserves_body_and_other_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "member" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text(
                "---\n"
                "name: 马斯克\n"
                "aliases: [马斯克, Elon Musk]\n"
                "description: |\n"
                "  很长的描述第一行。\n"
                "  很长的描述第二行。\n"
                "domain: technology\n"
                "---\n"
                "# Body stays here\n",
                encoding="utf-8",
            )

            changed = apply_compact_descriptions(discover_skill_files([root]))

            self.assertEqual(changed, 1)
            updated = skill.read_text(encoding="utf-8")
            self.assertIn("aliases: [马斯克, Elon Musk]", updated)
            self.assertIn("domain: technology", updated)
            self.assertIn("# Body stays here", updated)

            parsed = read_skill_file(skill)
            self.assertLessEqual(len(parsed.description), 90)
            self.assertIn("马斯克", parsed.description)
            self.assertIn("Elon Musk", parsed.description)


if __name__ == "__main__":
    unittest.main()
