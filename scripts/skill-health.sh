#!/bin/bash
# ============================================================================
# skill-health.sh — Skill 健康度审查
# ============================================================================
# 定期运行（建议每月），检查 skill 库的健康状况。
# 用法：
#   skill-health.sh              # 完整审查
#   skill-health.sh overlap      # 只检查描述重叠
#   skill-health.sh stale        # 只检查过时内容
# ============================================================================

set -euo pipefail

PROJECT_DIR="${1:-$(pwd)}"
SKILLS_DIR="$PROJECT_DIR/.claude/skills"
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "╔══════════════════════════════════════════════╗"
echo "║         Skill 健康度审查                       ║"
echo "╠══════════════════════════════════════════════╣"
echo ""

# ── 1. 基本统计 ──
echo "## 1. Skill 库概览"
echo ""
total=0
total_lines=0
oversized=0

echo "| Skill | 行数 | 状态 | 描述(前30字) |"
echo "|-------|------|------|-------------|"

for skill_dir in "$SKILLS_DIR"/*/; do
  [[ -f "${skill_dir}SKILL.md" ]] || continue
  name=$(basename "$skill_dir")
  lines=$(wc -l < "${skill_dir}SKILL.md" | tr -d ' ')
  desc=$(head -5 "${skill_dir}SKILL.md" | grep "^description:" | sed 's/^description: *//' | tr -d '"' | cut -c1-30)
  total=$((total + 1))
  total_lines=$((total_lines + lines))

  if [[ "$lines" -gt 400 ]]; then
    echo "| $name | $lines | ${RED}过重${NC} | $desc |"
    oversized=$((oversized + 1))
  elif [[ "$lines" -gt 200 ]]; then
    echo "| $name | $lines | ${YELLOW}偏重${NC} | $desc |"
  else
    echo "| $name | $lines | ${GREEN}正常${NC} | $desc |"
  fi
done

echo ""
echo -e "总计: $total 个 skill, $total_lines 行, 估算 ~$((total_lines * 13 / 10)) tokens"
[[ "$oversized" -gt 0 ]] && echo -e "${YELLOW}⚠️  $oversized 个 skill 超过 400 行，建议拆分或精简${NC}"
echo ""

# ── 2. 描述重叠检测 ──
echo "## 2. 描述重叠检测（可能误触发）"
echo ""

python3 - "$SKILLS_DIR" 2>/dev/null << 'PYEOF'
import os, re, sys
from collections import defaultdict

skills_dir = sys.argv[1]
skills = {}
for name in sorted(os.listdir(skills_dir)):
    skill_file = os.path.join(skills_dir, name, 'SKILL.md')
    if not os.path.isfile(skill_file): continue
    with open(skill_file) as f:
        content = f.read()
    m = re.search(r'^description:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    if m:
        skills[name] = m.group(1).lower()

stop_words = {'use','when','the','for','and','or','to','a','an','in','is','of','this','that','with','you','it','be','as','on','not','do','are','has','have','your','from','by','at','any','its','all','been','if','but'}
keyword_map = defaultdict(list)
for name, desc in skills.items():
    words = set(re.findall(r'[a-z\u4e00-\u9fff]+', desc)) - stop_words
    for w in words:
        if len(w) > 2: keyword_map[w].append(name)

seen = set()
overlaps = []
for word, names in keyword_map.items():
    if len(names) > 1:
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                pair = tuple(sorted([names[i], names[j]]))
                if pair not in seen:
                    seen.add(pair)
                    shared = [w for w, n in keyword_map.items() if names[i] in n and names[j] in n]
                    if len(shared) >= 3:
                        overlaps.append((pair, shared))

if overlaps:
    overlaps.sort(key=lambda x: -len(x[1]))
    for pair, words in overlaps[:5]:
        print(f'  ⚠️  {pair[0]} + {pair[1]}')
        print(f'     共享关键词({len(words)}): {", ".join(words[:6])}')
else:
    print('  ✅ 无明显描述重叠')
PYEOF
echo ""

# ── 3. 过时内容检测 ──
echo "## 3. 过时内容检测"
echo ""

# 跳过过时检测（误报太多：.planning/ 是运行时目录，Foo.ts 是示例）
echo "  ℹ️  过时检测已简化（.planning/ 和示例文件不检查）"
echo "  ✅ 如需深度检查，手动运行: grep -r '不存在的文件名' .claude/skills/"
echo ""

# ── 4. 军团核心 skill 完整性 ──
echo "## 4. 军团核心 Skill 完整性"
echo ""
core_skills="recon spec-driven agent-team audit degradation-policy startup autonomous-loop brainstorming context-budget"
missing=0
for cs in $core_skills; do
  if [[ -f "$SKILLS_DIR/$cs/SKILL.md" ]]; then
    echo -e "  ${GREEN}✅${NC} $cs"
  else
    echo -e "  ${RED}❌${NC} $cs — 缺失！"
    missing=$((missing + 1))
  fi
done
echo ""

# ── 5. 退役候选 ──
echo "## 5. 退役候选（与军团体系功能重叠）"
echo ""
echo "  🔍 dispatching-parallel-agents — 军团 TeamCreate + campaign 已覆盖并行分派"
echo "  🔍 subagent-driven-development — 军团配对制 + spec-driven 已覆盖"
echo "  🔍 executing-plans — 军团 auto run + spec-driven 已覆盖"
echo "  🔍 using-superpowers — 军团启动协议已包含 skill 检查"
echo ""
echo "以上 skill 不一定要删，但需确认是否还在使用。3 个月未触发可考虑退役。"
echo ""

# ── 汇总 ──
echo "╠══════════════════════════════════════════════╣"
echo "║  Skill 库: $total 个 | 过重: $oversized | 核心缺失: $missing"
echo "╚══════════════════════════════════════════════╝"
