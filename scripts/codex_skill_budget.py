#!/usr/bin/env python3
"""Audit and compact Codex skill metadata descriptions.

Codex currently renders all loaded skill names and descriptions into a fixed
startup metadata budget. Long frontmatter descriptions can be truncated even
when the full skill body remains available. This tool keeps the frontmatter
short while preserving the detailed instructions inside each skill body.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_BUDGET_CHARS = 5440
DEFAULT_MAX_DESCRIPTION_CHARS = 90
DEFAULT_ROOTS = (
    Path("~/.agents/skills"),
    Path("~/.codex/skills"),
    Path("~/.codex/plugins/cache"),
)


COMPACT_DESCRIPTIONS = {
    "Presentations": "Create/edit/render/export PowerPoint decks and slides.",
    "Spreadsheets": "Create/edit/analyze spreadsheets with formulas, charts, and tables.",
    "authentication": "Add Better Auth login, email verification, resets, protected routes, accounts.",
    "brainstorming": "Explore requirements and design before creative feature or behavior changes.",
    "browser": "Use in-app browser for localhost/file testing, screenshots, clicks, typing.",
    "chronicle": "Use screen and recent history to disambiguate the user's current context.",
    "crawl": "Crawl websites into local markdown for docs, knowledge bases, or analysis.",
    "dispatching-parallel-agents": "Use parallel agents for independent subtasks without shared write state.",
    "documents": "Create/edit DOCX with artifact rendering and visual QA.",
    "executing-plans": "Execute a written implementation plan with checkpointed review.",
    "extract": "Extract clean text/markdown from specific URLs via Tavily.",
    "find-skills": "Discover/install skills when user asks how to add a capability.",
    "finishing-a-development-branch": "Finish dev work: verify, merge/PR, or clean up a branch.",
    "gh-address-comments": "Address GitHub PR review comments and unresolved review threads.",
    "gh-fix-ci": "Debug and fix failing GitHub Actions checks for PRs.",
    "github": "Inspect GitHub repos, issues, and PRs before workflow-specific tasks.",
    "gmail": "Search, summarize, triage, draft, forward, label, archive, or delete Gmail.",
    "gmail-inbox-triage": "Triage Gmail into urgent, reply, waiting, and FYI buckets.",
    "hf-cli": "Use hf CLI to download, upload, and manage Hugging Face Hub assets.",
    "high-agency": "Sustain owner-level agency for long, complex, quality-sensitive tasks.",
    "huggingface-community-evals": "Run local HF model evals with inspect-ai/lighteval; not HF Jobs.",
    "huggingface-datasets": "Use HF Dataset Viewer API for splits, rows, filters, parquet, and stats.",
    "huggingface-gradio": "Build or edit Gradio Python web UIs, chatbots, layouts, and events.",
    "huggingface-jobs": "Run HF Jobs workloads: UV/Docker, GPU, secrets, cost, timeouts, persistence.",
    "huggingface-llm-trainer": "Train/fine-tune LLMs with TRL on HF Jobs; SFT, DPO, GRPO, GGUF.",
    "huggingface-paper-publisher": "Publish/manage Hugging Face paper pages and linked models/datasets.",
    "huggingface-papers": "Read HF/arXiv papers and fetch metadata, repos, spaces, and linked assets.",
    "huggingface-trackio": "Track ML training metrics with Trackio dashboards, alerts, and JSON output.",
    "huggingface-vision-trainer": "Train vision models: detection, classification, SAM/SAM2 on HF Jobs.",
    "imagegen": "Generate/edit bitmap images, visual assets, mockups, sprites, or photo outputs.",
    "openai-docs": "Use official OpenAI docs for API, model, ChatGPT, and prompt guidance.",
    "plugin-creator": "Scaffold Codex plugins with plugin.json, folders, and baseline files.",
    "proactive-agent": "Act proactively with WAL, working buffer, and compaction recovery patterns.",
    "pua": "Escalate after repeated failures or user frustration; exhaustive Chinese PUA style.",
    "ralph-loop": "Run agent-driven development loops from user stories to acceptance tests.",
    "receiving-code-review": "Handle code review feedback with verification before implementation.",
    "requesting-code-review": "Request/review code before merging or after major implementation.",
    "research": "Run cited terminal research with structured output for broad web questions.",
    "roundtable": "Run multi-persona debate for complex decisions; trigger 圆桌会议 or roundtable.",
    "search": "Search the web with Tavily for relevant pages and snippets.",
    "self-improving-agent": "Learn from skill runs via semantic, episodic, and working memory.",
    "skill-creator": "Create/update Codex skills with clear triggers, files, and validation.",
    "skill-installer": "List or install Codex skills from curated sources or GitHub repos.",
    "stripe-subscriptions": "Add Stripe subscriptions, plan gating, webhooks, and billing portal.",
    "subagent-driven-development": "Execute plans with independent subtasks in this session.",
    "systematic-debugging": "Find root cause before fixing bugs, failures, or unexpected behavior.",
    "tavily-best-practices": "Build production Tavily search/extract/crawl/research integrations.",
    "test-driven-development": "Write failing tests first for features, bugfixes, and refactors.",
    "transformers-js": "Run Transformers.js NLP, vision, audio, or multimodal models in JS/TS.",
    "ui-ux-designer": "Design UI/UX, interaction flows, user experience, and design systems.",
    "using-git-worktrees": "Create isolated git worktrees for feature work or plan execution.",
    "using-superpowers": "Start conversations by discovering and invoking relevant skills.",
    "verification-before-completion": "Verify with fresh evidence before claiming work is complete.",
    "web-design-guidelines": "Audit UI/UX, accessibility, and web design guideline compliance.",
    "writing-plans": "Turn specs or requirements into implementation plans before coding.",
    "writing-skills": "Create, edit, and validate agent skills before deployment.",
    "yeet": "Commit local changes, push, and open a draft PR via GitHub/gh.",
    "孔子": "Use Confucius/孔子 perspective for ethics, governance, and decision critique.",
    "曹操": "Use Cao Cao/曹操 perspective for strategy, power, and execution debate.",
    "特朗普": "Use Trump/特朗普 perspective for negotiation, media, and risk framing.",
    "苏格拉底": "Use Socrates/苏格拉底 perspective for questioning arguments and contradictions.",
    "莎士比亚": "Use Shakespeare/莎士比亚 perspective for motives, tragedy, and rhetoric.",
    "诸葛亮": "Use Zhuge Liang/诸葛亮 perspective for strategy, governance, and planning.",
    "马斯克": "Use Elon Musk/马斯克 perspective for first principles, tech, and startup bets.",
}


@dataclass(frozen=True)
class SkillBudgetConfig:
    max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS
    budget_chars: int = DEFAULT_BUDGET_CHARS


@dataclass(frozen=True)
class SkillFile:
    path: Path
    name: str
    description: str


@dataclass(frozen=True)
class SkillBudgetReport:
    skills: tuple[SkillFile, ...]
    total_description_chars: int
    max_description_chars: int
    overlong_skills: tuple[SkillFile, ...]
    budget_chars: int

    @property
    def skill_count(self) -> int:
        return len(self.skills)

    @property
    def ok(self) -> bool:
        return not self.overlong_skills and self.total_description_chars <= self.budget_chars


def discover_skill_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        expanded = root.expanduser()
        if expanded.is_file() and expanded.name == "SKILL.md":
            candidates = [expanded]
        elif expanded.exists():
            candidates = sorted(expanded.rglob("SKILL.md"))
        else:
            candidates = []
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(candidate)
    return files


def read_skill_file(path: Path) -> SkillFile:
    text = path.read_text(encoding="utf-8")
    frontmatter, _ = _split_frontmatter(text)
    name = _read_frontmatter_field(frontmatter, "name")
    description = _read_description(frontmatter)
    return SkillFile(path=path, name=name, description=_squash(description))


def audit_skills(roots: Iterable[Path], config: SkillBudgetConfig) -> SkillBudgetReport:
    skills = tuple(read_skill_file(path) for path in discover_skill_files(roots))
    overlong = tuple(
        skill for skill in skills if len(skill.description) > config.max_description_chars
    )
    total = sum(len(skill.description) for skill in skills)
    return SkillBudgetReport(
        skills=skills,
        total_description_chars=total,
        max_description_chars=config.max_description_chars,
        overlong_skills=overlong,
        budget_chars=config.budget_chars,
    )


def apply_compact_descriptions(files: Sequence[Path]) -> int:
    changed = 0
    for path in files:
        skill = read_skill_file(path)
        compact = COMPACT_DESCRIPTIONS.get(skill.name)
        if compact is None and len(skill.description) > DEFAULT_MAX_DESCRIPTION_CHARS:
            compact = _fallback_description(skill.name)
        if not compact or compact == skill.description:
            continue
        _write_description(path, compact)
        changed += 1
    return changed


def _fallback_description(name: str) -> str:
    fallback = f"Use for {name} tasks; see skill body for detailed triggers."
    return fallback[:DEFAULT_MAX_DESCRIPTION_CHARS]


def _split_frontmatter(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML frontmatter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], lines[index + 1 :]
    raise ValueError("unterminated YAML frontmatter")


def _read_frontmatter_field(lines: Sequence[str], field: str) -> str:
    prefix = f"{field}:"
    for line in lines:
        if line.startswith(prefix):
            return _strip_yaml_scalar(line[len(prefix) :].strip())
    return ""


def _read_description(lines: Sequence[str]) -> str:
    start, end = _description_range(lines)
    if start is None:
        return ""
    value = lines[start].split(":", 1)[1].strip()
    if value.startswith(("|", ">")):
        return " ".join(line.strip() for line in lines[start + 1 : end])
    return _strip_yaml_scalar(value)


def _write_description(path: Path, description: str) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} missing YAML frontmatter")
    for close_index in range(1, len(lines)):
        if lines[close_index].strip() == "---":
            break
    else:
        raise ValueError(f"{path} has unterminated YAML frontmatter")

    frontmatter = lines[1:close_index]
    body = lines[close_index:]
    start, end = _description_range(frontmatter)
    escaped = description.replace("\\", "\\\\").replace('"', '\\"')
    replacement = [f'description: "{escaped}"\n']
    if start is None:
        insert_at = _field_insert_index(frontmatter, "name")
        new_frontmatter = frontmatter[:insert_at] + replacement + frontmatter[insert_at:]
    else:
        new_frontmatter = frontmatter[:start] + replacement + frontmatter[end:]

    new_text = "".join([lines[0], *new_frontmatter, *body])
    path.write_text(new_text, encoding="utf-8")


def _description_range(lines: Sequence[str]) -> tuple[int | None, int | None]:
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if not value.startswith(("|", ">")):
            return index, index + 1
        end = index + 1
        while end < len(lines):
            next_line = lines[end]
            if _is_top_level_key(next_line):
                break
            end += 1
        return index, end
    return None, None


def _field_insert_index(lines: Sequence[str], field: str) -> int:
    prefix = f"{field}:"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index + 1
    return 0


def _is_top_level_key(line: str) -> bool:
    return re.match(r"^[A-Za-z0-9_-]+:\s*", line) is not None


def _strip_yaml_scalar(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _format_report(report: SkillBudgetReport) -> str:
    lines = [
        (
            f"skills={report.skill_count} "
            f"description_chars={report.total_description_chars} "
            f"budget_chars={report.budget_chars} "
            f"max_description={max((len(skill.description) for skill in report.skills), default=0)} "
            f"over_{report.max_description_chars}={len(report.overlong_skills)}"
        )
    ]
    for skill in sorted(
        report.overlong_skills, key=lambda item: len(item.description), reverse=True
    )[:20]:
        lines.append(f"{len(skill.description):4d}  {skill.name:<35}  {skill.path}")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=[],
        help="Skill root to scan. Defaults to ~/.agents/skills, ~/.codex/skills, and plugin cache.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite known skill descriptions to compact trigger-oriented text.",
    )
    parser.add_argument(
        "--budget-chars",
        type=int,
        default=DEFAULT_BUDGET_CHARS,
        help="Maximum aggregate description characters allowed.",
    )
    parser.add_argument(
        "--max-description-chars",
        type=int,
        default=DEFAULT_MAX_DESCRIPTION_CHARS,
        help="Maximum description length per skill.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    roots = args.root or list(DEFAULT_ROOTS)
    config = SkillBudgetConfig(
        max_description_chars=args.max_description_chars,
        budget_chars=args.budget_chars,
    )

    if args.apply:
        changed = apply_compact_descriptions(discover_skill_files(roots))
        print(f"changed={changed}")

    report = audit_skills(roots, config)
    print(_format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
