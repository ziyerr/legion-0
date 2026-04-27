#!/bin/bash
# ============================================================================
# legion-sync.sh — 军团协议分发工具
# ============================================================================
# 将最新的 agent 定义和执行纪律同步到目标项目。
#
# 用法：
#   legion-sync.sh /path/to/project          # 同步到指定项目
#   legion-sync.sh --all                     # 同步到所有已注册项目
#   legion-sync.sh --check /path/to/project  # 仅检查，不修改
#   legion-sync.sh --list                    # 列出所有已注册项目的同步状态
# ============================================================================

set -euo pipefail

# 参考源：从 $SOURCE_PROJECT/.claude/agents/ 复制 agent 定义到目标项目
# 默认用 $HOME（$HOME/.claude/agents/ 即 legion-0 全局 agent 库）
# 可通过 LEGION_SOURCE_PROJECT env var 覆盖为具体项目
SOURCE_PROJECT="${LEGION_SOURCE_PROJECT:-$HOME}"
DIRECTORY_FILE="$HOME/.claude/legion/directory.json"

# 需要同步的 agent 文件
AGENTS=(implement.md review.md verify.md explore.md plan.md)

_check_project() {
  local project_path="$1"
  local project_name=$(basename "$project_path")
  local status="OK"
  local details=""

  # Check agents/
  local agent_count=0
  if [[ -d "$project_path/.claude/agents" ]]; then
    agent_count=$(ls "$project_path/.claude/agents/"*.md 2>/dev/null | wc -l | tr -d ' ')
  fi
  if [[ "$agent_count" -lt 5 ]]; then
    status="MISSING"
    details="agents: $agent_count/5"
  fi

  # Check CLAUDE.md for execution discipline
  if ! grep -q "流水线" "$project_path/CLAUDE.md" 2>/dev/null; then
    if [[ "$status" == "OK" ]]; then
      status="WARN"
      details="CLAUDE.md: 无执行纪律"
    else
      details="$details, CLAUDE.md: 无执行纪律"
    fi
  fi

  echo "$status|$project_name|$project_path|$details"
}

_sync_agents() {
  local target="$1"
  local adapted=0

  mkdir -p "$target/.claude/agents"

  for agent in "${AGENTS[@]}"; do
    local src="$SOURCE_PROJECT/.claude/agents/$agent"
    if [[ ! -f "$src" ]]; then
      echo "  SKIP $agent (source not found)"
      continue
    fi

    cp "$src" "$target/.claude/agents/$agent"
    adapted=$((adapted + 1))
  done

  # Adapt project context if target has CLAUDE.md with project info
  local target_name=$(basename "$target")
  if [[ -f "$target/CLAUDE.md" ]]; then
    # Read first line to get project description
    local desc=$(head -1 "$target/CLAUDE.md" | sed 's/^# //')
    echo "  Copied $adapted agents (adapt project context in agents manually if needed)"
    echo "  Project: $desc"
  else
    echo "  Copied $adapted agents"
  fi
}

_sync_discipline() {
  local target="$1"

  if [[ ! -f "$target/CLAUDE.md" ]]; then
    echo "  SKIP: no CLAUDE.md"
    return
  fi

  if grep -q "流水线" "$target/CLAUDE.md" 2>/dev/null; then
    echo "  SKIP: 执行纪律已存在"
    return
  fi

  echo "  WARN: CLAUDE.md 缺少执行纪律，需手动添加（项目结构各异，不能盲目复制）"
}

case "${1:-}" in
  --check)
    shift
    result=$(_check_project "$1")
    IFS='|' read -r status name path details <<< "$result"
    echo "$status  $name  $details"
    ;;

  --list)
    if [[ ! -f "$DIRECTORY_FILE" ]]; then
      echo "No directory file found"
      exit 1
    fi
    echo "=== 军团协议同步状态 ==="
    printf "%-10s %-25s %s\n" "状态" "项目" "详情"
    printf "%-10s %-25s %s\n" "----" "----" "----"
    python3 -c "
import json
with open('$DIRECTORY_FILE') as f:
    d = json.load(f)
for l in d.get('legions', []):
    print(l['path'])
" | while read -r path; do
      result=$(_check_project "$path")
      IFS='|' read -r status name _ details <<< "$result"
      printf "%-10s %-25s %s\n" "$status" "$name" "$details"
    done
    ;;

  --all)
    if [[ ! -f "$DIRECTORY_FILE" ]]; then
      echo "No directory file found"
      exit 1
    fi
    python3 -c "
import json
with open('$DIRECTORY_FILE') as f:
    d = json.load(f)
for l in d.get('legions', []):
    print(l['path'])
" | while read -r path; do
      echo "=== $(basename "$path") ==="
      _sync_agents "$path"
      _sync_discipline "$path"
      echo ""
    done
    ;;

  "")
    echo "Usage: legion-sync.sh <project_path|--all|--check <path>|--list>"
    exit 1
    ;;

  *)
    target="$1"
    if [[ ! -d "$target" ]]; then
      echo "Error: $target is not a directory"
      exit 1
    fi
    echo "=== Syncing to $(basename "$target") ==="
    _sync_agents "$target"
    _sync_discipline "$target"
    echo "=== Done ==="
    ;;
esac
