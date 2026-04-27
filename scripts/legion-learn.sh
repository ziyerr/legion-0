#!/bin/bash
# ============================================================================
# legion-learn.sh — 跨会话学习记录系统
# ============================================================================
# 用法：source 后使用函数，或直接 bash 执行子命令
#   source ~/.claude/scripts/legion-learn.sh
#   legion_learn "failure|discovery|pattern" "标题" "详细描述" "tag1,tag2" ["skill名"]
#   legion_learn_search "关键词" [--tag "标签"]
#   legion_learn_stats
#
# 直接执行：
#   bash ~/.claude/scripts/legion-learn.sh learn "failure" "标题" "描述" "tag1,tag2"
#   bash ~/.claude/scripts/legion-learn.sh search "关键词" [--tag "标签"]
#   bash ~/.claude/scripts/legion-learn.sh stats
# ============================================================================

LEARNINGS_DIR="${HOME}/.claude/legion"
LEARNINGS_FILE="${LEARNINGS_DIR}/learnings.jsonl"
LEARNINGS_LOCK="${LEARNINGS_DIR}/learnings.jsonl.lock"

# Ensure directory exists
mkdir -p "$LEARNINGS_DIR"

# --- Helpers ---

_has_jq() {
  command -v jq >/dev/null 2>&1
}

_json_escape() {
  # Escape string for JSON value (handles quotes, backslashes, newlines)
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\t'/\\t}"
  echo "$s"
}

_write_with_lock() {
  # Write a line to the JSONL file with atomic mkdir-based locking
  # (mkdir is atomic on POSIX, works on both macOS and Linux)
  local line="$1"
  local lockdir="${LEARNINGS_LOCK}.d"
  local retries=0

  while ! mkdir "$lockdir" 2>/dev/null; do
    retries=$((retries + 1))
    if [[ $retries -gt 50 ]]; then
      echo "ERROR: Could not acquire lock after 5s" >&2
      return 1
    fi
    sleep 0.1
  done

  echo "$line" >> "$LEARNINGS_FILE"
  rmdir "$lockdir" 2>/dev/null
}

# --- Functions ---

legion_learn() {
  local type="${1:?用法: legion_learn \"failure|discovery|pattern\" \"标题\" \"描述\" \"tags\" [\"skill\"]}"
  local key="${2:?缺少标题}"
  local insight="${3:?缺少描述}"
  local tags_raw="${4:-}"
  local skill="${5:-unknown}"

  # Validate type
  case "$type" in
    failure|discovery|pattern) ;;
    *)
      echo "ERROR: type must be 'failure', 'discovery', or 'pattern'" >&2
      return 1
      ;;
  esac

  local timestamp
  timestamp=$(date '+%Y-%m-%dT%H:%M:%S%z')
  local unix_ts
  unix_ts=$(date '+%s')
  local commander="${LEGION_COMMANDER:-unknown}"

  # Build tags JSON array
  local tags_json="[]"
  if [[ -n "$tags_raw" ]]; then
    local IFS=','
    local tag_arr=()
    for t in $tags_raw; do
      # Trim whitespace
      t=$(echo "$t" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      [[ -n "$t" ]] && tag_arr+=("\"$(_json_escape "$t")\"")
    done
    if [[ ${#tag_arr[@]} -gt 0 ]]; then
      local joined
      joined=$(printf ",%s" "${tag_arr[@]}")
      tags_json="[${joined:1}]"
    fi
  fi

  # Escape values for JSON
  local e_key e_insight e_commander e_skill
  e_key=$(_json_escape "$key")
  e_insight=$(_json_escape "$insight")
  e_commander=$(_json_escape "$commander")
  e_skill=$(_json_escape "$skill")

  local json_line="{\"id\":\"learn-${unix_ts}\",\"timestamp\":\"${timestamp}\",\"commander\":\"${e_commander}\",\"skill\":\"${e_skill}\",\"type\":\"${type}\",\"key\":\"${e_key}\",\"insight\":\"${e_insight}\",\"confidence\":\"medium\",\"tags\":${tags_json}}"

  _write_with_lock "$json_line"

  echo "✓ Learning recorded: [${type}] ${key}"
}

legion_learn_search() {
  local keyword="${1:?用法: legion_learn_search \"关键词\" [--tag \"标签\"]}"
  shift
  local tag_filter=""

  # Parse --tag option
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --tag)
        tag_filter="${2:?--tag 需要参数}"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done

  if [[ ! -f "$LEARNINGS_FILE" ]]; then
    echo "No learnings recorded yet."
    return
  fi

  local results
  # First filter by keyword
  results=$(grep -i "$keyword" "$LEARNINGS_FILE" 2>/dev/null || true)

  # Then filter by tag if specified
  if [[ -n "$tag_filter" && -n "$results" ]]; then
    results=$(echo "$results" | grep -i "\"$tag_filter\"" 2>/dev/null || true)
  fi

  if [[ -z "$results" ]]; then
    echo "No learnings found matching '${keyword}'${tag_filter:+ with tag '${tag_filter}'}."
    return
  fi

  # Show last 20 matches
  local count
  count=$(echo "$results" | wc -l | tr -d ' ')
  echo "Found ${count} match(es) (showing last 20):"
  echo ""

  local display
  display=$(echo "$results" | tail -20)

  if _has_jq; then
    echo "$display" | while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      echo "$line" | jq -r '"  [\(.type)] \(.key)\n    \(.insight)\n    tags: \(.tags | join(", "))  skill: \(.skill)  time: \(.timestamp)\n"' 2>/dev/null || echo "  $line"
    done
  else
    echo "$display" | while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      # Basic extraction without jq
      local ltype lkey linsight
      ltype=$(echo "$line" | sed 's/.*"type":"\([^"]*\)".*/\1/')
      lkey=$(echo "$line" | sed 's/.*"key":"\([^"]*\)".*/\1/')
      linsight=$(echo "$line" | sed 's/.*"insight":"\([^"]*\)".*/\1/')
      printf "  [%s] %s\n    %s\n\n" "$ltype" "$lkey" "$linsight"
    done
  fi
}

legion_learn_stats() {
  if [[ ! -f "$LEARNINGS_FILE" ]]; then
    echo "No learnings recorded yet."
    return
  fi

  local total
  total=$(wc -l < "$LEARNINGS_FILE" | tr -d ' ')
  echo "=== Learning Stats ==="
  echo "Total records: ${total}"
  echo ""

  # Count by type
  echo "By type:"
  local cnt
  for t in failure discovery pattern; do
    cnt=$(grep -c "\"type\":\"${t}\"" "$LEARNINGS_FILE" 2>/dev/null) || cnt=0
    printf "  %-12s %s\n" "${t}:" "$cnt"
  done
  echo ""

  # Count by tag (top 10)
  echo "By tag (top 10):"
  if _has_jq; then
    # Use jq to extract all tags
    jq -r '.tags[]?' "$LEARNINGS_FILE" 2>/dev/null | sort | uniq -c | sort -rn | head -10 | while read -r cnt tag; do
      printf "  %-20s %s\n" "${tag}:" "$cnt"
    done
  else
    # Fallback: grep-based tag extraction
    grep -oE '"tags":\[[^]]*\]' "$LEARNINGS_FILE" 2>/dev/null | \
      grep -oE '"[^"]*"' | grep -v '^"tags"' | \
      sed 's/"//g' | sort | uniq -c | sort -rn | head -10 | \
      while read -r cnt tag; do
        printf "  %-20s %s\n" "${tag}:" "$cnt"
      done
  fi
  echo ""

  # Recent 5 entries
  echo "Recent 5:"
  local recent
  recent=$(tail -5 "$LEARNINGS_FILE")
  if _has_jq; then
    echo "$recent" | while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      echo "$line" | jq -r '"  [\(.type)] \(.key) — \(.timestamp)"' 2>/dev/null || echo "  $line"
    done
  else
    echo "$recent" | while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      local ltype lkey lts
      ltype=$(echo "$line" | sed 's/.*"type":"\([^"]*\)".*/\1/')
      lkey=$(echo "$line" | sed 's/.*"key":"\([^"]*\)".*/\1/')
      lts=$(echo "$line" | sed 's/.*"timestamp":"\([^"]*\)".*/\1/')
      printf "  [%s] %s — %s\n" "$ltype" "$lkey" "$lts"
    done
  fi
}

# --- CLI mode (when executed directly, not sourced) ---

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    learn)
      shift
      legion_learn "$@"
      ;;
    search)
      shift
      legion_learn_search "$@"
      ;;
    stats)
      legion_learn_stats
      ;;
    *)
      echo "用法:"
      echo "  legion-learn.sh learn \"type\" \"标题\" \"描述\" \"tags\" [\"skill\"]"
      echo "  legion-learn.sh search \"关键词\" [--tag \"标签\"]"
      echo "  legion-learn.sh stats"
      echo ""
      echo "或 source 后使用函数："
      echo "  source legion-learn.sh"
      echo "  legion_learn / legion_learn_search / legion_learn_stats"
      exit 1
      ;;
  esac
fi
