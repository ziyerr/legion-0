#!/bin/bash
# ============================================================================
# team-merge.sh — 合并 Agent 团队的 worktree 分支
# ============================================================================
# 用法:
#   team-merge.sh [log_dir]    # 扫描 worktree 分支并逐个合并
#   team-merge.sh --list       # 仅列出待合并的分支
#   team-merge.sh --clean      # 清理所有 agent worktree
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ACTION="merge"
LOG_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list) ACTION="list" ;;
    --clean) ACTION="clean" ;;
    -h|--help)
      echo "用法: team-merge.sh [--list|--clean] [log_dir]"
      exit 0
      ;;
    *) LOG_DIR="$1" ;;
  esac
  shift
done

# 找到所有 claude worktree 分支
echo -e "${BOLD}${CYAN}扫描 worktree 分支...${NC}"
echo ""

WORKTREES=()
while IFS= read -r line; do
  wt_path=$(echo "$line" | awk '{print $1}')
  wt_branch=$(echo "$line" | sed 's/.*\[//' | sed 's/\]//')
  # 跳过主工作区
  if [[ "$wt_path" == "$(git rev-parse --show-toplevel)" ]]; then
    continue
  fi
  WORKTREES+=("$wt_path|$wt_branch")
  echo -e "  ${GREEN}${wt_branch}${NC} → ${wt_path}"
done < <(git worktree list 2>/dev/null)

if [[ ${#WORKTREES[@]} -eq 0 ]]; then
  echo -e "  ${YELLOW}无 worktree 分支${NC}"
  echo ""
  echo -e "  ${BOLD}提示${NC}: 如果未使用 -w (worktree) 模式，所有修改已在当前分支。"
  exit 0
fi

echo ""

if [[ "$ACTION" == "list" ]]; then
  echo -e "${BOLD}共 ${#WORKTREES[@]} 个 worktree 分支${NC}"
  exit 0
fi

if [[ "$ACTION" == "clean" ]]; then
  echo -e "${YELLOW}清理所有 agent worktree...${NC}"
  for entry in "${WORKTREES[@]}"; do
    IFS='|' read -r wt_path wt_branch <<< "$entry"
    echo -e "  删除 ${RED}${wt_branch}${NC} (${wt_path})"
    git worktree remove "$wt_path" --force 2>/dev/null || true
    git branch -D "$wt_branch" 2>/dev/null || true
  done
  echo -e "${GREEN}清理完成${NC}"
  exit 0
fi

# ── 合并流程 ──
CURRENT_BRANCH=$(git branch --show-current)
echo -e "${BOLD}当前分支: ${CYAN}${CURRENT_BRANCH}${NC}"
echo ""

MERGED=0
CONFLICTS=0

for entry in "${WORKTREES[@]}"; do
  IFS='|' read -r wt_path wt_branch <<< "$entry"
  echo -e "${BOLD}合并 ${CYAN}${wt_branch}${NC} ...${NC}"

  # 检查是否有提交
  commits=$(git log "${CURRENT_BRANCH}..${wt_branch}" --oneline 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$commits" -eq 0 ]]; then
    echo -e "  ${YELLOW}无新提交，跳过${NC}"
    continue
  fi
  echo -e "  ${GREEN}${commits} 个新提交${NC}"

  # 尝试合并
  if git merge "$wt_branch" --no-edit 2>/dev/null; then
    echo -e "  ${GREEN}✓ 合并成功${NC}"
    ((MERGED++))
    # 清理 worktree
    git worktree remove "$wt_path" --force 2>/dev/null || true
    git branch -d "$wt_branch" 2>/dev/null || true
  else
    echo -e "  ${RED}✗ 冲突！手动解决后运行: git merge --continue${NC}"
    git merge --abort 2>/dev/null || true
    ((CONFLICTS++))
  fi
  echo ""
done

echo -e "${BOLD}${CYAN}────────────────────────────────────${NC}"
echo -e "  合并: ${GREEN}${MERGED}${NC}  冲突: ${RED}${CONFLICTS}${NC}  总计: ${#WORKTREES[@]}"
