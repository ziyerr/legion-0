#!/usr/bin/env python3
"""Legion project self-check.

This keeps project Legion files usable after initialization:
- skills entries must be real directories with readable SKILL.md files
- agent definitions must be readable markdown files
- oversized CLAUDE.md and agent markdown files are compacted with backups
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path


CLAUDE_TARGET_CHARS = int(os.environ.get("LEGION_CLAUDE_TARGET_CHARS", "2500"))
CLAUDE_TRIGGER_CHARS = int(os.environ.get("LEGION_CLAUDE_TRIGGER_CHARS", str(CLAUDE_TARGET_CHARS * 3 // 2)))
AGENT_TARGET_CHARS = int(os.environ.get("LEGION_AGENT_TARGET_CHARS", "2500"))
AGENT_TRIGGER_CHARS = int(os.environ.get("LEGION_AGENT_TRIGGER_CHARS", str(AGENT_TARGET_CHARS)))

DISCIPLINE_BLOCK = """# >>> legion-init execution-discipline/v2 >>>
# 指挥官自主权（全局第一原则）

所有 L1 指挥官在所有项目中默认拥有流程决策的完全自主权。

**流程决策（要不要组团 / 侦察 / spec / 审查 / 放行 / 升级复杂度 / 选技能 / 选 teammate 配置）→ 直接判断执行，不向用户确认。**

## 军团核心原则：规模优先

军团目标是不计资源消耗成本，通过最大化有效军团规模协作提升效率和质量。

1. **资源成本不是降级理由** — token、时间、进程数、tmux 窗口数、模型调用成本不得作为降级理由。
2. **默认向上扩编** — 非平凡任务优先用 `--corps` 扩编 L2，并并行组织侦察 / 实现 / 审查 / 验证 / 审计 / 产品 / UI。
3. **最大有效规模，不是盲目重复** — 扩编必须带来互补视角或并行吞吐。
4. **质量门前置且独立** — 实现与 review / verify / audit 分离。
5. **上下文即资产** — L2 是否解散取决于上下文是否仍有价值。

## 四种例外：只有这些情形才停下问用户

1. **不可逆破坏** — rm -rf、force push 主分支、drop table、覆盖未提交代码、删除分支、删除未备份数据
2. **需求本身模糊** — 有多种合理解释，无法通过读代码 / 读 memory 消除歧义
3. **跨项目 / 共享状态变更** — 影响他人、跨 repo、改 CI/CD 管线、改全局配置 / hooks / 技能 / 全局 AGENTS.md / 全局 CLAUDE.md
4. **关键决策成本高** — 走到死胡同需要大成本返工的岔路口

## 句式纪律

禁止流程确认（“可以吗 / 要不要先 recon / 需要我组团吗 / 可以进入下一步吗”）。允许汇报已发生动作；命中例外时说“命中第 N 种例外：[情形]，请你决定：[A / B]”。

## 作战纪律

S 级单文件可轻量；M 级 2-5 文件需侦察/实现/审查；L 级跨域需多路侦察、流水线与独立验证；XL 级架构变更用最大有效规模。铁律：不跑验证不许完成；禁止降级核心目标；复杂度拿不准向上；功能开发先经产品参谋。

项目级 AGENTS.md / CLAUDE.md 可以覆盖本规则；需要更严格人工确认时写“禁用自主权第一原则”。
# <<< legion-init execution-discipline/v2 <<<"""


def normalize(value: str) -> str:
    value = "\n".join(line.rstrip() for line in value.splitlines())
    return re.sub(r"\n{3,}", "\n\n", value).strip()


class ProjectSelfCheck:
    def __init__(self, project: Path, backup_label: str, quiet: bool) -> None:
        self.project = project
        self.backup_root = project / ".claude" / "backups" / backup_label / time.strftime("%Y%m%d-%H%M%S")
        self.quiet = quiet
        self.changed = 0
        self.warnings: list[str] = []

    def log(self, message: str) -> None:
        if not self.quiet:
            print(message)

    def backup_file(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        rel = path.relative_to(self.project)
        dst = self.backup_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            target = os.readlink(path)
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            os.symlink(target, dst)
        else:
            shutil.copy2(path, dst)

    def move_to_backup(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        rel = path.relative_to(self.project)
        dst = self.backup_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dst))
        self.changed += 1
        self.log(f"⚠ 已备份并移开冲突路径: {rel}")

    @staticmethod
    def strip_marker_blocks(value: str) -> str:
        start_token = "# >>> legion-init execution-discipline"
        end_token = "# <<< legion-init execution-discipline"
        while True:
            start = value.find(start_token)
            if start == -1:
                return value
            end = value.find(end_token, start + 1)
            if end == -1:
                return value[:start].rstrip()
            line_end = value.find("\n", end)
            line_end = len(value) if line_end == -1 else line_end + 1
            value = value[:start] + value[line_end:]

    @staticmethod
    def strip_history_wrapper(value: str) -> str:
        value = normalize(value)
        if value.startswith("---"):
            value = value[3:].lstrip()
        heading = "# 历史 CLAUDE.md（已压缩）"
        if value.startswith(heading):
            value = value[len(heading):].lstrip()
        return value

    @staticmethod
    def strip_legacy_discipline_sections(value: str) -> str:
        lines = value.splitlines()
        cleaned: list[str] = []
        skip = False
        legacy_heads = (
            "# 指挥官自主权（全局第一原则）",
            "# ⛔ 执行纪律",
            "# 作战执行纪律",
            "## 军团核心原则：规模优先",
        )
        project_heads = ("# Project", "# 项目", "# AI", "## 项目", "## 技术栈", "## Architecture", "## Coding Rules")
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(head) for head in legacy_heads):
                skip = True
                continue
            if skip and stripped.startswith("#") and any(stripped.startswith(head) for head in project_heads):
                skip = False
            if not skip:
                cleaned.append(line)
        return "\n".join(cleaned)

    @staticmethod
    def compact_markdown(value: str, budget: int, notice: str) -> str:
        value = normalize(value)
        if not value or budget <= 0:
            return ""
        if len(value) <= budget:
            return value

        sections: list[list[str]] = []
        current: list[str] = []
        for line in value.splitlines():
            if line.startswith("#") and current:
                sections.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append(current)

        summary_lines = [notice]
        for section in sections:
            non_empty = [line for line in section if line.strip()]
            if not non_empty:
                continue
            summary_lines.extend(["", non_empty[0]])
            kept = 0
            for line in non_empty[1:]:
                if line.startswith("#"):
                    continue
                summary_lines.append(line)
                kept += 1
                if kept >= 3:
                    break

        summary = normalize("\n".join(summary_lines))
        if len(summary) <= budget:
            return summary
        clipped = summary[: max(0, budget - 20)].rstrip()
        if "\n" in clipped:
            clipped = clipped.rsplit("\n", 1)[0].rstrip()
        return clipped + "\n…"

    def render_claude(self, text: str) -> str:
        legacy = self.strip_marker_blocks(text)
        legacy = self.strip_history_wrapper(legacy)
        legacy = self.strip_legacy_discipline_sections(legacy)
        legacy = normalize(legacy)
        sep = "\n\n---\n\n"
        if not legacy:
            return DISCIPLINE_BLOCK + "\n"
        prefix = DISCIPLINE_BLOCK + sep + "# 历史 CLAUDE.md（已压缩）\n\n"
        budget = CLAUDE_TARGET_CHARS - len(prefix) - 1
        compacted = self.compact_markdown(
            legacy,
            budget,
            "（历史 CLAUDE.md 已自动压缩；完整原文见 .claude/backups/）",
        )
        return (prefix + compacted).rstrip() + "\n"

    def check_claude(self) -> None:
        path = self.project / "CLAUDE.md"
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        if len(text) <= CLAUDE_TRIGGER_CHARS:
            return
        rendered = self.render_claude(text)
        if rendered == text:
            return
        self.backup_file(path)
        path.write_text(rendered, encoding="utf-8")
        self.changed += 1
        self.log(f"✓ CLAUDE.md 超过 {CLAUDE_TRIGGER_CHARS} 字符，已智能压缩到 {len(rendered)} 字符")

    @staticmethod
    def split_frontmatter(text: str) -> tuple[str, str]:
        if not text.startswith("---\n"):
            return "", text
        end = text.find("\n---\n", 4)
        if end == -1:
            return "", text
        return text[: end + 5].rstrip() + "\n\n", text[end + 5 :].lstrip()

    def compact_agent_file(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        if len(text) <= AGENT_TRIGGER_CHARS:
            return
        frontmatter, body = self.split_frontmatter(text)
        marker = "<!-- legion-agent-compressed/v1 -->\n"
        budget = AGENT_TARGET_CHARS - len(frontmatter) - len(marker) - 1
        compacted_body = self.compact_markdown(
            body,
            budget,
            "（Agent 定义已自动压缩；完整原文见 .claude/backups/）",
        )
        rendered = (frontmatter + marker + compacted_body).rstrip() + "\n"
        if rendered == text:
            return
        self.backup_file(path)
        path.write_text(rendered, encoding="utf-8")
        self.changed += 1
        self.log(f"✓ Agent 定义已压缩: {path.relative_to(self.project)}")

    def check_agents(self) -> None:
        candidates = [
            self.project / ".claude" / "agents",
            self.project / ".agents" / "agents",
            self.project / "agents",
        ]
        for agents_dir in candidates:
            if not agents_dir.exists():
                continue
            for path in sorted(agents_dir.rglob("*.md")):
                if path.is_symlink() or not path.is_file():
                    self.move_to_backup(path)
                    continue
                if path.stat().st_size == 0:
                    self.warnings.append(f"空 Agent 文件: {path.relative_to(self.project)}")
                    continue
                self.compact_agent_file(path)

    def check_skills(self) -> None:
        skills_dir = self.project / ".claude" / "skills"
        if not skills_dir.exists():
            return
        for entry in sorted(skills_dir.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                self.move_to_backup(entry)
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file() or skill_md.stat().st_size == 0:
                self.move_to_backup(entry)

    def check_tools(self) -> None:
        for tool in ("bash", "python3", "find", "cp"):
            if shutil.which(tool) is None:
                self.warnings.append(f"缺少必要工具: {tool}")
        if shutil.which("tmux") is None:
            self.warnings.append("缺少 tmux，军团窗口运行不可用")

    def run(self) -> int:
        self.check_tools()
        self.check_skills()
        self.check_agents()
        self.check_claude()
        for warning in self.warnings:
            self.log(f"⚠ {warning}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=".")
    parser.add_argument("--backup-label", default="legion-self-check")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    return ProjectSelfCheck(project, args.backup_label, args.quiet).run()


if __name__ == "__main__":
    raise SystemExit(main())
