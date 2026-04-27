#!/usr/bin/env python3
"""
智能记忆召回脚本 (F101)

接受用户查询，从 MEMORY.md 索引中用 LLM 选择 ≤5 个最相关记忆文件，返回内容。

用法:
  python3 memory-recall.py "查询内容"
  echo "查询内容" | python3 memory-recall.py

环境变量:
  MEMORY_DIR  — 记忆目录路径（默认自动检测项目对应目录）
  MAX_RECALL  — 最多召回记忆数（默认 5）
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def find_memory_dir() -> Path:
    """定位当前项目对应的 Claude Code 记忆目录"""
    override = os.environ.get("MEMORY_DIR")
    if override:
        return Path(override)

    # Claude Code 的记忆路径规则: ~/.claude/projects/-{cwd_with_dashes}/memory/
    cwd = os.getcwd()
    safe_path = cwd.replace("/", "-")
    return Path.home() / ".claude" / "projects" / safe_path / "memory"


def parse_memory_index(memory_dir: Path) -> list[dict]:
    """解析 MEMORY.md 索引，提取记忆文件列表及其描述"""
    index_file = memory_dir / "MEMORY.md"
    if not index_file.exists():
        return []

    entries = []
    text = index_file.read_text(encoding="utf-8")

    # 匹配 markdown 链接: - [filename.md](filename.md) - description
    pattern = re.compile(r"-\s*\[([^\]]+\.md)\]\([^)]+\)\s*-\s*(.+)")
    for m in pattern.finditer(text):
        filename = m.group(1)
        description = m.group(2).strip()
        filepath = memory_dir / filename
        if filepath.exists():
            entries.append({
                "file": filename,
                "description": description,
                "path": str(filepath),
            })

    return entries


def parse_frontmatter(filepath: str) -> dict:
    """提取记忆文件的 YAML frontmatter"""
    try:
        text = Path(filepath).read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return {}

    if not text.startswith("---"):
        return {}

    end = text.find("---", 3)
    if end == -1:
        return {}

    fm = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def select_memories_with_llm(query: str, entries: list[dict], max_recall: int) -> list[str]:
    """用 claude CLI 从候选记忆中选择最相关的"""
    if not entries:
        return []

    # 构建候选列表
    candidates = "\n".join(
        f"  {i+1}. [{e['file']}] {e['description']}"
        for i, e in enumerate(entries)
    )

    prompt = (
        f"你是记忆召回系统。根据用户查询，从候选记忆列表中选择最相关的记忆（最多 {max_recall} 个）。\n\n"
        f"用户查询: {query}\n\n"
        f"候选记忆:\n{candidates}\n\n"
        f'请只返回一个 JSON 数组，包含你选择的记忆文件名（按相关度从高到低排序）。\n'
        f'例如: ["feedback_team_execution.md", "project_overview.md"]\n\n'
        f"规则:\n"
        f"- 只选与查询直接相关的记忆，不相关的不要选\n"
        f"- 最多选 {max_recall} 个\n"
        f"- 只输出 JSON 数组，不要其他文字"
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--max-turns", "1"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return _fallback_keyword_match(query, entries, max_recall)

        output = result.stdout.strip()
        # 提取 JSON 数组（LLM 可能会包裹在 markdown code block 中）
        json_match = re.search(r'\[.*?\]', output, re.DOTALL)
        if json_match:
            selected = json.loads(json_match.group())
            # 验证返回的文件名都在候选列表中
            valid_files = {e["file"] for e in entries}
            return [f for f in selected if f in valid_files][:max_recall]

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"[memory-recall] LLM 调用失败，降级到关键词匹配: {e}", file=sys.stderr)

    return _fallback_keyword_match(query, entries, max_recall)


def _fallback_keyword_match(query: str, entries: list[dict], max_recall: int) -> list[str]:
    """LLM 不可用时的关键词匹配降级方案"""
    query_lower = query.lower()
    scored = []
    for e in entries:
        score = 0
        text = (e["file"] + " " + e["description"]).lower()
        for word in query_lower.split():
            if len(word) >= 2 and word in text:
                score += 1
        if score > 0:
            scored.append((score, e["file"]))

    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:max_recall]]


def read_memory_content(memory_dir: Path, filename: str) -> str:
    """读取记忆文件内容（去掉 frontmatter）"""
    filepath = memory_dir / filename
    try:
        text = filepath.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return ""

    # 跳过 frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].strip()

    return text


def main():
    # 获取查询
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    elif not sys.stdin.isatty():
        query = sys.stdin.read().strip()
    else:
        print("用法: memory-recall.py <查询>", file=sys.stderr)
        sys.exit(1)

    if not query:
        print("错误: 查询内容为空", file=sys.stderr)
        sys.exit(1)

    max_recall = int(os.environ.get("MAX_RECALL", "5"))
    memory_dir = find_memory_dir()

    if not memory_dir.exists():
        print(f"记忆目录不存在: {memory_dir}", file=sys.stderr)
        sys.exit(1)

    # 1. 解析索引
    entries = parse_memory_index(memory_dir)
    if not entries:
        print("MEMORY.md 中未找到记忆条目", file=sys.stderr)
        sys.exit(0)

    # 2. 也扫描索引中未列出但目录中存在的记忆文件
    indexed_files = {e["file"] for e in entries}
    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue
        if md_file.name not in indexed_files:
            fm = parse_frontmatter(str(md_file))
            entries.append({
                "file": md_file.name,
                "description": fm.get("description", md_file.stem.replace("_", " ")),
                "path": str(md_file),
            })

    # 3. LLM 选择最相关记忆
    selected = select_memories_with_llm(query, entries, max_recall)

    if not selected:
        print("未找到与查询相关的记忆", file=sys.stderr)
        sys.exit(0)

    # 4. 输出召回的记忆内容
    output_parts = []
    for filename in selected:
        content = read_memory_content(memory_dir, filename)
        if content:
            output_parts.append(f"=== {filename} ===\n{content}")

    if output_parts:
        print("\n\n".join(output_parts))
    else:
        print("召回的记忆文件均为空", file=sys.stderr)


if __name__ == "__main__":
    main()
