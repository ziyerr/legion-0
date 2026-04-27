#!/bin/bash
# ============================================================================
# tactic-cite.sh — 战法引用记账
# ============================================================================
# 用法: tactic-cite.sh <tactic-id> [cited-by]
# 示例: tactic-cite.sh tactic-38d8a1 L1-青龙军团
#
# 更新 frontmatter 中的 score (+1)、last_cited、cited_by
# ============================================================================

set -euo pipefail

TACTIC_ID="${1:?用法: tactic-cite.sh <tactic-id> [cited-by]}"
CITED_BY="${2:-${CLAUDE_LEGION_TEAM_ID:-unknown}}"
TODAY=$(date +%Y-%m-%d)

GLOBAL_DIR="$HOME/.claude/memory/tactics"

# 查找战法文件
TACTIC_FILE=""
for candidate in "$GLOBAL_DIR/${TACTIC_ID}.md" "$GLOBAL_DIR/${TACTIC_ID}"; do
    if [[ -f "$candidate" ]]; then
        TACTIC_FILE="$candidate"
        break
    fi
done

if [[ -z "$TACTIC_FILE" ]]; then
    echo "ERROR: 找不到战法 $TACTIC_ID"
    echo "可用文件:"
    ls "$GLOBAL_DIR"/tactic-*.md "$GLOBAL_DIR"/tactic_*.md 2>/dev/null | head -5
    exit 1
fi

# 更新 frontmatter
python3 << PYEOF
import re

fpath = "$TACTIC_FILE"
cited_by = "$CITED_BY"
today = "$TODAY"

with open(fpath) as f:
    content = f.read()

# 解析 frontmatter
fm_match = re.match(r'^(---\n)(.*?)(\n---)', content, re.DOTALL)
if not fm_match:
    print(f"ERROR: {fpath} 没有 frontmatter")
    exit(1)

fm = fm_match.group(2)
body = content[fm_match.end():]

# 更新 score
score_match = re.search(r'^score:\s*(\d+)', fm, re.MULTILINE)
if score_match:
    old_score = int(score_match.group(1))
    new_score = old_score + 1
    fm = re.sub(r'^score:\s*\d+', f'score: {new_score}', fm, flags=re.MULTILINE)
else:
    fm += f'\nscore: 1'
    new_score = 1

# 更新 last_cited
if re.search(r'^last_cited:', fm, re.MULTILINE):
    fm = re.sub(r'^last_cited:.*$', f'last_cited: {today}', fm, flags=re.MULTILINE)
else:
    fm += f'\nlast_cited: {today}'

# 更新 cited_by
if re.search(r'^cited_by:', fm, re.MULTILINE):
    fm = re.sub(r'^cited_by:.*$', f'cited_by: {cited_by}', fm, flags=re.MULTILINE)
else:
    fm += f'\ncited_by: {cited_by}'

result = f'---\n{fm}\n---{body}'
with open(fpath, 'w') as f:
    f.write(result)

print(f"OK: {fpath} score {new_score} (cited by {cited_by})")
PYEOF
