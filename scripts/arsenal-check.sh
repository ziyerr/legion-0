#!/bin/bash
# ============================================================================
# arsenal-check.sh — 武器库巡检脚本
# ============================================================================
# 用法:
#   arsenal-check.sh quick     — 快速巡检（完整性 + 索引刷新）
#   arsenal-check.sh full      — 完整巡检（+ 查重候选 + score 统计）
#   arsenal-check.sh snapshot  — 保存当前战法文件快照（供 stop-hook diff 用）
#   arsenal-check.sh diff      — 与快照比对，检测新增战法
# ============================================================================

set -euo pipefail

GLOBAL_DIR="$HOME/.claude/memory/tactics"
# Claude Code per-project memory 约定：~/.claude/projects/<cwd-sanitized>/memory/
# cwd-sanitized = 当前目录把 / 替换为 -
PROJECT_MEMORY_DIR="${PROJECT_MEMORY_DIR:-$HOME/.claude/projects/$(pwd | sed 's|/|-|g')/memory}"
INDEX_FILE="$GLOBAL_DIR/INDEX.md"
MEMORY_FILE="$PROJECT_MEMORY_DIR/MEMORY.md"
SNAPSHOT_FILE="/tmp/arsenal-snapshot-$$.md5"
SESSION_SNAPSHOT="/tmp/arsenal-session-snapshot.md5"

MODE="${1:-quick}"

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── 快照管理 ──
take_snapshot() {
    ls -1 "$GLOBAL_DIR"/tactic-*.md "$GLOBAL_DIR"/tactic_*.md 2>/dev/null | sort | md5 > "$SESSION_SNAPSHOT"
    echo "snapshot saved → $SESSION_SNAPSHOT"
}

diff_snapshot() {
    if [[ ! -f "$SESSION_SNAPSHOT" ]]; then
        echo "NO_SNAPSHOT"
        return
    fi
    current=$(ls -1 "$GLOBAL_DIR"/tactic-*.md "$GLOBAL_DIR"/tactic_*.md 2>/dev/null | sort | md5)
    saved=$(cat "$SESSION_SNAPSHOT")
    if [[ "$current" != "$saved" ]]; then
        # 找出新增文件
        saved_list=$(mktemp)
        current_list=$(mktemp)
        # 从快照时的文件列表恢复（这里只能比对 md5 变化，无法精确列出新文件）
        echo "CHANGED"
        rm -f "$saved_list" "$current_list"
    else
        echo "UNCHANGED"
    fi
}

# ── 完整性检查 ──
check_integrity() {
    local issues=0

    echo "=== 完整性检查 ==="

    # 全局库: INDEX.md ↔ 实际文件
    if [[ -f "$INDEX_FILE" ]]; then
        for f in "$GLOBAL_DIR"/tactic-*.md "$GLOBAL_DIR"/tactic_*.md; do
            [[ -f "$f" ]] || continue
            local bn=$(basename "$f")
            if ! grep -qF "$bn" "$INDEX_FILE"; then
                echo -e "${RED}NOT_INDEXED (全局): $bn${NC}"
                issues=$((issues + 1))
            fi
        done
    else
        echo -e "${RED}MISSING: $INDEX_FILE${NC}"
        issues=$((issues + 1))
    fi

    # 项目库: MEMORY.md ↔ tactic_*.md
    if [[ -f "$MEMORY_FILE" ]]; then
        for f in "$PROJECT_MEMORY_DIR"/tactic_*.md; do
            [[ -f "$f" ]] || continue
            local bn=$(basename "$f")
            if ! grep -qF "$bn" "$MEMORY_FILE"; then
                echo -e "${RED}NOT_INDEXED (项目): $bn${NC}"
                issues=$((issues + 1))
            fi
        done

        # 反向：MEMORY.md 引用的 tactic_*.md 是否都存在
        # 格式: [name](filename.md) — 提取括号内的文件名
        python3 -c "
import re, os, sys
with open('$MEMORY_FILE') as f:
    content = f.read()
refs = re.findall(r'\]\((tactic_[^)]+\.md)\)', content)
for ref in sorted(set(refs)):
    fpath = os.path.join('$PROJECT_MEMORY_DIR', ref)
    if not os.path.exists(fpath):
        print(f'BROKEN_REF (项目): {ref}')
        sys.exit(1)
" 2>/dev/null && true || issues=$((issues + 1))
    fi

    if [[ $issues -eq 0 ]]; then
        echo -e "${GREEN}全部通过${NC}"
    fi
    return $issues
}

# ── Score 统计 ──
score_stats() {
    echo "=== Score 统计 ==="
    local total=0 scored=0 stale=0

    for f in "$GLOBAL_DIR"/tactic-*.md "$GLOBAL_DIR"/tactic_*.md; do
        [[ -f "$f" ]] || continue
        total=$((total + 1))
        local score=$(sed -n 's/^score: *//p' "$f" 2>/dev/null)
        [[ "${score:-0}" -gt 0 ]] && scored=$((scored + 1))
    done

    echo "总计: $total | 被引用(score>0): $scored | 未引用: $((total - scored))"
    if [[ $total -gt 0 ]]; then
        local pct=$((scored * 100 / total))
        echo "引用率: ${pct}%"
    fi
}

# ── 查重候选（基于 summary 关键词重叠） ──
dedup_candidates() {
    echo "=== 查重候选（关键词重叠） ==="

    # 提取所有 summary，做简单的关键词交叉比对
    python3 << 'PYEOF'
import os, re
from collections import defaultdict

global_dir = os.path.expanduser("~/.claude/memory/tactics")
# 同 bash 版逻辑：cwd 路径 `/` 替换为 `-` 作为 Claude Code project key
project_dir = os.environ.get("PROJECT_MEMORY_DIR") or os.path.expanduser(
    f"~/.claude/projects/{os.getcwd().replace('/', '-')}/memory"
)

def extract_summary(fpath):
    with open(fpath) as f:
        content = f.read()
    m = re.search(r'^summary:\s*(.+)$', content, re.MULTILINE)
    if m: return m.group(1).strip()
    m = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
    if m: return m.group(1).strip()
    return ""

def keywords(text):
    """提取中文+英文关键词（去除停用词）"""
    stops = {'的','了','在','是','和','与','用','不','必须','需要','a','the','is','to','and','for','must','be'}
    words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z_]{3,}', text.lower()))
    return words - stops

entries = []

for fname in os.listdir(global_dir):
    if not fname.startswith('tactic') or not fname.endswith('.md') or fname == 'INDEX.md':
        continue
    fpath = os.path.join(global_dir, fname)
    s = extract_summary(fpath)
    if s:
        entries.append(('全局', fname, s, keywords(s)))

for fname in os.listdir(project_dir):
    if not fname.startswith('tactic_') or not fname.endswith('.md'):
        continue
    fpath = os.path.join(project_dir, fname)
    s = extract_summary(fpath)
    if s:
        entries.append(('项目', fname, s, keywords(s)))

# 跨库比对（同库重复在入库时就该避免）
candidates = []
for i in range(len(entries)):
    for j in range(i+1, len(entries)):
        if entries[i][0] == entries[j][0]:
            continue  # 同库跳过（用完整巡检时再查）
        overlap = entries[i][3] & entries[j][3]
        if len(overlap) >= 3:  # 3个以上关键词重叠
            score = len(overlap)
            candidates.append((score, entries[i], entries[j], overlap))

candidates.sort(key=lambda x: -x[0])

if not candidates:
    print("无跨库查重候选")
else:
    for score, a, b, overlap in candidates[:10]:
        print(f"[重叠{score}词] {a[0]}:{a[1]} ↔ {b[0]}:{b[1]}")
        print(f"  共同词: {', '.join(list(overlap)[:8])}")
        print()
PYEOF
}

# ── 索引重建 ──
rebuild_index() {
    echo "=== 重建全局 INDEX.md ==="
    python3 << 'PYEOF'
import os, re
from collections import defaultdict

tactics_dir = os.path.expanduser("~/.claude/memory/tactics")
entries = []

for fname in sorted(os.listdir(tactics_dir)):
    if not fname.startswith('tactic') or not fname.endswith('.md') or fname == 'INDEX.md':
        continue
    fpath = os.path.join(tactics_dir, fname)
    with open(fpath) as f:
        content = f.read()

    meta = {}
    fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()

    entries.append({
        'file': fname,
        'id': meta.get('id', fname.replace('.md','')),
        'domain': meta.get('domain', 'uncategorized'),
        'summary': meta.get('summary', meta.get('description', '(no summary)')),
        'source': meta.get('source', ''),
        'created': meta.get('created', ''),
        'score': int(meta.get('score', '0')),
    })

by_domain = defaultdict(list)
for e in entries:
    by_domain[e['domain']].append(e)

lines = []
lines.append("# Global Tactics Index")
lines.append("")
lines.append("跨项目通用的工程模式和教训。每条战法从具体项目中提炼而来，可复用于任何战场。")
lines.append(f"")
lines.append(f"**总计: {len(entries)} 条**")
lines.append("")

for domain in sorted(by_domain.keys()):
    items = sorted(by_domain[domain], key=lambda x: -x['score'])  # score 高的排前面
    lines.append(f"### {domain} ({len(items)})")
    for e in items:
        src = f" — {e['source']}" if e['source'] else ""
        dt = f" ({e['created']})" if e['created'] else ""
        score_badge = f" [★{e['score']}]" if e['score'] > 0 else ""
        lines.append(f"- [{e['id']}]({e['file']}): {e['summary']}{score_badge}{src}{dt}")
    lines.append("")

index_path = os.path.join(tactics_dir, "INDEX.md")
with open(index_path, 'w') as f:
    f.write('\n'.join(lines))

print(f"INDEX.md 已重建: {len(entries)} 条, {len(by_domain)} 个 domain")
PYEOF
}

# ── 主流程 ──
case "$MODE" in
    quick)
        check_integrity || true
        rebuild_index
        ;;
    full)
        check_integrity || true
        score_stats
        dedup_candidates
        rebuild_index
        echo ""
        echo "=== 巡检完成 ==="
        ;;
    snapshot)
        take_snapshot
        ;;
    diff)
        diff_snapshot
        ;;
    *)
        echo "用法: arsenal-check.sh {quick|full|snapshot|diff}"
        exit 1
        ;;
esac
