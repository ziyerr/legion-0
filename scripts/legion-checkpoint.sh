#!/bin/bash
# ============================================================================
# legion-checkpoint.sh — 跨会话断点保存/恢复系统
# ============================================================================
# 用法：
#   legion-checkpoint.sh save "描述文字"
#   legion-checkpoint.sh resume [checkpoint文件]
#   legion-checkpoint.sh list
# ============================================================================

set -euo pipefail

CHECKPOINT_DIR="${HOME}/.claude/legion/checkpoints"
PLANNING_DIR=".planning"

# Ensure checkpoint directory exists
mkdir -p "$CHECKPOINT_DIR"

# --- Helpers ---

_extract_phase() {
  local state_file="${PLANNING_DIR}/STATE.md"
  if [[ -f "$state_file" ]]; then
    # Try to extract phase from frontmatter or first heading
    local phase
    phase=$(grep -i -m1 'phase\|阶段\|状态' "$state_file" 2>/dev/null | sed 's/.*[：:]\s*//' | head -1)
    if [[ -n "$phase" ]]; then
      echo "$phase"
      return
    fi
  fi
  echo "unknown"
}

_extract_section() {
  # Extract content under a heading from a markdown file
  # Usage: _extract_section "file" "heading_pattern"
  local file="$1"
  local pattern="$2"
  if [[ ! -f "$file" ]]; then
    return
  fi
  awk -v pat="$pattern" '
    BEGIN { found=0 }
    $0 ~ pat { found=1; next }
    found && /^##? / { found=0 }
    found { print }
  ' "$file" | sed '/^$/d'
}

_extract_completed() {
  local state_file="${PLANNING_DIR}/STATE.md"
  if [[ -f "$state_file" ]]; then
    _extract_section "$state_file" "已完成\|[Cc]ompleted\|[Dd]one"
  fi
}

_extract_in_progress() {
  local state_file="${PLANNING_DIR}/STATE.md"
  if [[ -f "$state_file" ]]; then
    _extract_section "$state_file" "进行中\|[Ii]n.?[Pp]rogress\|[Cc]urrent"
  fi
}

_extract_remaining() {
  local state_file="${PLANNING_DIR}/STATE.md"
  if [[ -f "$state_file" ]]; then
    _extract_section "$state_file" "剩余\|[Rr]emaining\|[Tt]odo\|待办"
  fi
}

_extract_recent_decisions() {
  local decisions_file="${PLANNING_DIR}/DECISIONS.md"
  if [[ -f "$decisions_file" ]]; then
    # Extract last 5 decision entries (sections starting with ##)
    awk '/^## /{count++} count>0{print}' "$decisions_file" | tail -50 | head -40
  fi
}

_sanitize_desc() {
  # Convert description to filesystem-safe string
  echo "$1" | sed 's/[^a-zA-Z0-9_\-\x80-\xff]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//' | cut -c1-60
}

# --- Commands ---

cmd_save() {
  local desc="${1:?用法: legion-checkpoint.sh save \"描述文字\"}"
  local branch
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  local phase
  phase=$(_extract_phase)
  local timestamp
  timestamp=$(date '+%Y%m%d-%H%M%S')
  local iso_time
  iso_time=$(date '+%Y-%m-%dT%H:%M:%S%z')
  local safe_desc
  safe_desc=$(_sanitize_desc "$desc")
  local filename="${timestamp}-${safe_desc}.md"
  local filepath="${CHECKPOINT_DIR}/${filename}"
  local workdir
  workdir=$(pwd)

  # Collect git status
  local git_status
  git_status=$(git status --porcelain 2>/dev/null || echo "(not a git repo)")

  # Collect planning info
  local completed in_progress remaining decisions
  completed=$(_extract_completed)
  in_progress=$(_extract_in_progress)
  remaining=$(_extract_remaining)
  decisions=$(_extract_recent_decisions)

  # Write checkpoint file
  cat > "$filepath" <<CHECKPOINT
---
branch: ${branch}
phase: ${phase}
created: ${iso_time}
description: ${desc}
workdir: ${workdir}
---

## Git 状态
${git_status:-（无变更）}

## 已完成
${completed:-（无记录）}

## 进行中
${in_progress:-（无记录）}

## 决策记录
${decisions:-（无记录）}

## 剩余工作
${remaining:-（无记录）}

## 恢复指令
新会话恢复时：
1. cd ${workdir}
2. git checkout ${branch}
3. 读 .planning/ 了解完整需求
4. 从"进行中"项接续
CHECKPOINT

  # Update latest symlink (rm + ln for portability, no ln -sf on some BSD)
  rm -f "${CHECKPOINT_DIR}/latest"
  ln -s "$filepath" "${CHECKPOINT_DIR}/latest"

  echo "✓ Checkpoint saved: ${filename}"
  echo "  Path: ${filepath}"
}

cmd_resume() {
  local target="${1:-}"
  if [[ -z "$target" ]]; then
    # Use latest symlink
    if [[ -L "${CHECKPOINT_DIR}/latest" ]]; then
      target=$(readlink "${CHECKPOINT_DIR}/latest")
    else
      echo "ERROR: No latest checkpoint found. Specify a checkpoint file." >&2
      exit 1
    fi
  elif [[ ! "$target" = /* ]]; then
    # Relative path — prepend checkpoint dir
    target="${CHECKPOINT_DIR}/${target}"
  fi

  if [[ ! -f "$target" ]]; then
    echo "ERROR: Checkpoint not found: ${target}" >&2
    exit 1
  fi

  echo "=== Checkpoint: $(basename "$target") ==="
  echo ""
  cat "$target"
}

cmd_list() {
  if [[ ! -d "$CHECKPOINT_DIR" ]]; then
    echo "No checkpoints found."
    return
  fi

  local count=0
  # List .md files sorted by name (which includes timestamp) in reverse order
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    local basename_f
    basename_f=$(basename "$f")
    # Extract date and description from filename: YYYYMMDD-HHMMSS-desc.md
    local date_part desc_part branch_part
    date_part=$(echo "$basename_f" | cut -c1-15) # YYYYMMDD-HHMMSS
    desc_part=$(echo "$basename_f" | sed 's/^[0-9]\{8\}-[0-9]\{6\}-//;s/\.md$//')
    branch_part=$(grep -m1 '^branch:' "$f" 2>/dev/null | sed 's/branch: //' || echo "?")
    printf "  %s  [%s]  %s\n" "$date_part" "$branch_part" "$desc_part"
    count=$((count + 1))
  done < <(ls -1r "${CHECKPOINT_DIR}"/*.md 2>/dev/null)

  if [[ $count -eq 0 ]]; then
    echo "No checkpoints found."
  else
    echo ""
    echo "Total: ${count} checkpoint(s)"
  fi
}

# --- Main ---

case "${1:-}" in
  save)
    shift
    cmd_save "$@"
    ;;
  resume)
    shift
    cmd_resume "$@"
    ;;
  list)
    cmd_list
    ;;
  *)
    echo "用法:"
    echo "  legion-checkpoint.sh save \"描述文字\"   — 保存断点"
    echo "  legion-checkpoint.sh resume [文件]      — 恢复断点"
    echo "  legion-checkpoint.sh list               — 列出所有断点"
    exit 1
    ;;
esac
