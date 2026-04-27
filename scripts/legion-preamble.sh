#!/bin/bash
# legion-preamble.sh — 轻量状态注入，skill/agent 启动时调用
# 输出 key=value 对，后续逻辑基于这些变量分支
# 用法: eval "$(bash ~/.claude/scripts/legion-preamble.sh)"
#   或: bash ~/.claude/scripts/legion-preamble.sh  (仅查看)

set -euo pipefail

# Git 状态
BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
UNCOMMITTED=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
LAST_COMMIT=$(git log -1 --oneline 2>/dev/null || echo "no commits")

# Checkpoint
LATEST_CHECKPOINT=""
if [ -L ~/.claude/legion/checkpoints/latest ]; then
  LATEST_CHECKPOINT=$(readlink ~/.claude/legion/checkpoints/latest 2>/dev/null || echo "")
fi

# Learnings
LEARNINGS_COUNT=0
if [ -f ~/.claude/legion/learnings.jsonl ]; then
  LEARNINGS_COUNT=$(wc -l < ~/.claude/legion/learnings.jsonl | tr -d ' ')
fi

# Active commanders
ACTIVE_COMMANDERS=0
if [ -f ~/.claude/legion/*/registry.json ] 2>/dev/null; then
  ACTIVE_COMMANDERS=$(grep -c '"commanding"' ~/.claude/legion/*/registry.json 2>/dev/null || echo "0")
fi

# File locks
LOCK_COUNT=0
for lockfile in ~/.claude/legion/*/locks.json; do
  if [ -f "$lockfile" ]; then
    count=$(grep -c '"file"' "$lockfile" 2>/dev/null || echo "0")
    LOCK_COUNT=$((LOCK_COUNT + count))
  fi
done 2>/dev/null

# Planning state
PLANNING_STATE="none"
if [ -f .planning/STATE.md ]; then
  PLANNING_STATE="active"
fi

# Skills count
SKILLS_COUNT=$(ls .claude/skills/*/SKILL.md 2>/dev/null | wc -l | tr -d ' ')

# Output
echo "PREAMBLE_BRANCH=${BRANCH}"
echo "PREAMBLE_UNCOMMITTED=${UNCOMMITTED}"
echo "PREAMBLE_LAST_COMMIT=${LAST_COMMIT}"
echo "PREAMBLE_CHECKPOINT=${LATEST_CHECKPOINT:-none}"
echo "PREAMBLE_LEARNINGS=${LEARNINGS_COUNT}"
echo "PREAMBLE_COMMANDERS=${ACTIVE_COMMANDERS}"
echo "PREAMBLE_LOCKS=${LOCK_COUNT}"
echo "PREAMBLE_PLANNING=${PLANNING_STATE}"
echo "PREAMBLE_SKILLS=${SKILLS_COUNT}"
