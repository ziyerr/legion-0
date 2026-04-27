#!/bin/bash
# ============================================================================
# team-status.sh — Claude Agent 团队状态监控面板
# ============================================================================
# 用法:
#   team-status.sh <log_dir>          # 单次打印
#   watch -n2 -c team-status.sh <dir> # 实时刷新（推荐配合 watch 使用）
# ============================================================================

LOG_DIR="${1:-/tmp/claude-team}"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

# 状态图标
icon_for_status() {
  case "$1" in
    completed) echo -e "${GREEN}✓${NC}" ;;
    running)   echo -e "${YELLOW}⟳${NC}" ;;
    failed)    echo -e "${RED}✗${NC}" ;;
    pending)   echo -e "${GRAY}○${NC}" ;;
    *)         echo -e "${GRAY}?${NC}" ;;
  esac
}

color_for_status() {
  case "$1" in
    completed) echo -e "${GREEN}" ;;
    running)   echo -e "${YELLOW}" ;;
    failed)    echo -e "${RED}" ;;
    pending)   echo -e "${GRAY}" ;;
    *)         echo -e "${GRAY}" ;;
  esac
}

# 计算耗时
elapsed() {
  local start_file="$1"
  local end_file="$2"
  if [[ ! -f "$start_file" ]]; then
    echo "--"
    return
  fi
  local start_ts end_ts
  start_ts=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$(cat "$start_file")" +%s 2>/dev/null || echo "0")
  if [[ -f "$end_file" ]]; then
    end_ts=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$(cat "$end_file")" +%s 2>/dev/null || echo "0")
  else
    end_ts=$(date +%s)
  fi
  if [[ "$start_ts" -eq 0 ]]; then
    echo "--"
    return
  fi
  local diff=$((end_ts - start_ts))
  local min=$((diff / 60))
  local sec=$((diff % 60))
  if [[ $min -gt 0 ]]; then
    printf "%dm%02ds" $min $sec
  else
    printf "%ds" $sec
  fi
}

# 日志行数（粗略进度指标）
log_lines() {
  local log_file="$1"
  if [[ -f "$log_file" ]]; then
    wc -l < "$log_file" | tr -d ' '
  else
    echo "0"
  fi
}

# ── 头部 ──
TEAM_NAME=$(basename "$LOG_DIR")
NOW=$(date '+%H:%M:%S')

echo -e "${BOLD}${CYAN}┌─────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}${CYAN}│  Claude Agent Team: ${TEAM_NAME}${NC}"
echo -e "${BOLD}${CYAN}│  ${GRAY}刷新时间: ${NOW}${NC}"
echo -e "${BOLD}${CYAN}├─────────────────────────────────────────────┤${NC}"

# ── 统计 ──
total=0
completed=0
running=0
failed=0
pending=0

for status_file in "$LOG_DIR"/agent-*.status; do
  [[ -f "$status_file" ]] || continue
  s=$(cat "$status_file" 2>/dev/null || echo "pending")
  ((total++))
  case "$s" in
    completed) ((completed++)) ;;
    running)   ((running++)) ;;
    failed)    ((failed++)) ;;
    pending)   ((pending++)) ;;
  esac
done

# 进度条
if [[ $total -gt 0 ]]; then
  pct=$((completed * 100 / total))
  bar_len=30
  filled=$((pct * bar_len / 100))
  empty=$((bar_len - filled))
  bar="${GREEN}"
  for ((j=0; j<filled; j++)); do bar+="█"; done
  bar+="${GRAY}"
  for ((j=0; j<empty; j++)); do bar+="░"; done
  bar+="${NC}"
  echo -e "${BOLD}│${NC}  进度: ${bar} ${BOLD}${pct}%${NC} (${completed}/${total})"
else
  echo -e "${BOLD}│${NC}  ${GRAY}无 agent 数据${NC}"
fi

echo -e "${BOLD}│${NC}  ${GREEN}完成:${completed}${NC}  ${YELLOW}运行:${running}${NC}  ${RED}失败:${failed}${NC}  ${GRAY}等待:${pending}${NC}"
echo -e "${BOLD}${CYAN}├─────────────────────────────────────────────┤${NC}"

# ── 各 agent 详情 ──
i=0
for status_file in "$LOG_DIR"/agent-*.status; do
  [[ -f "$status_file" ]] || continue

  # 提取 agent 编号
  fname=$(basename "$status_file" .status)
  idx="${fname#agent-}"

  status=$(cat "$status_file" 2>/dev/null || echo "pending")
  icon=$(icon_for_status "$status")
  color=$(color_for_status "$status")

  # 耗时
  time_str=$(elapsed "$LOG_DIR/${fname}.start" "$LOG_DIR/${fname}.end")

  # 日志行数
  lines=$(log_lines "$LOG_DIR/${fname}.log")

  # 最后一行日志（截断）
  last_line=""
  if [[ -f "$LOG_DIR/${fname}.log" ]]; then
    last_line=$(tail -1 "$LOG_DIR/${fname}.log" 2>/dev/null | head -c 50)
  fi

  echo -e "${BOLD}│${NC} ${icon} ${color}${BOLD}Agent-${idx}${NC}  ${color}${status}${NC}  ${GRAY}⏱${time_str}  📝${lines}行${NC}"
  if [[ -n "$last_line" && "$status" == "running" ]]; then
    echo -e "${BOLD}│${NC}   ${GRAY}└ ${last_line}${NC}"
  fi

  ((i++))
done

echo -e "${BOLD}${CYAN}└─────────────────────────────────────────────┘${NC}"

# ── 全部完成提示 ──
if [[ $total -gt 0 && $running -eq 0 && $pending -eq 0 ]]; then
  echo ""
  if [[ $failed -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}🎉 全部完成！${NC}"
  else
    echo -e "  ${YELLOW}${BOLD}⚠ 完成，但有 ${failed} 个失败${NC}"
  fi
  echo -e "  ${GRAY}查看日志: ls ${LOG_DIR}/agent-*.log${NC}"
  echo -e "  ${GRAY}合并结果: bash ~/.claude/scripts/team-merge.sh ${LOG_DIR}${NC}"
fi
