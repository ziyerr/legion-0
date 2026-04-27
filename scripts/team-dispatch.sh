#!/bin/bash
# ============================================================================
# team-dispatch.sh — Claude Agent 团队可视化编排器
# ============================================================================
# 用法:
#   team-dispatch.sh [选项] -t "角色:任务描述" [-t "角色:任务描述"] ...
#   team-dispatch.sh [选项] -f tasks.json
#
# 选项:
#   -t "角色:任务"    添加一个 agent（可重复多次）
#   -f file.json     从 JSON 文件加载任务列表
#   -m model         指定模型（sonnet/opus/haiku），默认 sonnet
#   -p mode          权限模式（auto/default/plan），默认 auto
#   -w               启用 worktree 隔离（推荐多人改同文件时用）
#   -n name          团队名称，用于 tmux window 命名
#   -d dir           工作目录，默认当前目录
#   --dry-run        只打印计划，不执行
#   --no-tee         不保存日志到文件
#   -h               显示帮助
#
# 示例:
#   team-dispatch.sh -n "视频审核" -w \
#     -t "Rust后端:实现 sync_videos() 函数" \
#     -t "前端:增强视频审核UI" \
#     -t "流水线:DAG添加video_review步骤"
#
#   team-dispatch.sh -f ~/.claude/teams/video-review.json
# ============================================================================

set -euo pipefail

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── 默认值 ──
TASKS=()
ROLES=()
MODEL="sonnet"
PERM_MODE="auto"
USE_WORKTREE=false
TEAM_NAME="agents-$(date +%H%M%S)"
WORK_DIR="$(pwd)"
DRY_RUN=false
NO_TEE=false
LOG_DIR="/tmp/claude-team"
JSON_FILE=""
USE_RALPH=false
RALPH_MAX_ITER=10
RALPH_VERIFY=""

# ── 帮助 ──
usage() {
  sed -n '2,/^# ====$/p' "$0" | sed 's/^# //' | sed 's/^#//'
  exit 0
}

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t)
      shift
      IFS=':' read -r role task <<< "$1"
      if [[ -z "$task" ]]; then
        task="$role"
        role="agent-${#TASKS[@]}"
      fi
      ROLES+=("$role")
      TASKS+=("$task")
      ;;
    -f)
      shift; JSON_FILE="$1"
      ;;
    -m) shift; MODEL="$1" ;;
    -p) shift; PERM_MODE="$1" ;;
    -w) USE_WORKTREE=true ;;
    -n) shift; TEAM_NAME="$1" ;;
    -d) shift; WORK_DIR="$1" ;;
    --dry-run) DRY_RUN=true ;;
    --no-tee) NO_TEE=true ;;
    --ralph) USE_RALPH=true ;;
    --ralph-iter) shift; RALPH_MAX_ITER="$1" ;;
    --ralph-verify) shift; RALPH_VERIFY="$1" ;;
    -h|--help) usage ;;
    *) echo -e "${RED}未知参数: $1${NC}"; usage ;;
  esac
  shift
done

# ── 从 JSON 加载任务 ──
if [[ -n "$JSON_FILE" ]]; then
  if [[ ! -f "$JSON_FILE" ]]; then
    echo -e "${RED}任务文件不存在: $JSON_FILE${NC}"
    exit 1
  fi
  # JSON 格式: {"team": "名称", "model": "sonnet", "tasks": [{"role": "xx", "prompt": "xx"}]}
  if command -v jq &>/dev/null; then
    _team=$(jq -r '.team // empty' "$JSON_FILE" 2>/dev/null)
    [[ -n "$_team" ]] && TEAM_NAME="$_team"
    _model=$(jq -r '.model // empty' "$JSON_FILE" 2>/dev/null)
    [[ -n "$_model" ]] && MODEL="$_model"
    _perm=$(jq -r '.permission_mode // empty' "$JSON_FILE" 2>/dev/null)
    [[ -n "$_perm" ]] && PERM_MODE="$_perm"
    _wt=$(jq -r '.worktree // false' "$JSON_FILE" 2>/dev/null)
    [[ "$_wt" == "true" ]] && USE_WORKTREE=true
    _dir=$(jq -r '.work_dir // empty' "$JSON_FILE" 2>/dev/null)
    [[ -n "$_dir" ]] && WORK_DIR="$_dir"
    _ralph=$(jq -r '.ralph // false' "$JSON_FILE" 2>/dev/null)
    [[ "$_ralph" == "true" ]] && USE_RALPH=true
    _ralph_iter=$(jq -r '.ralph_max_iter // empty' "$JSON_FILE" 2>/dev/null)
    [[ -n "$_ralph_iter" ]] && RALPH_MAX_ITER="$_ralph_iter"
    _ralph_verify=$(jq -r '.ralph_verify // empty' "$JSON_FILE" 2>/dev/null)
    [[ -n "$_ralph_verify" ]] && RALPH_VERIFY="$_ralph_verify"

    while IFS=$'\t' read -r role prompt; do
      ROLES+=("$role")
      TASKS+=("$prompt")
    done < <(jq -r '.tasks[] | [.role, .prompt] | @tsv' "$JSON_FILE")
  else
    echo -e "${RED}需要 jq 来解析 JSON 文件。安装: brew install jq${NC}"
    exit 1
  fi
fi

# ── 校验 ──
if [[ ${#TASKS[@]} -eq 0 ]]; then
  echo -e "${RED}未指定任务。使用 -t 或 -f 添加任务。${NC}"
  usage
fi

# ── 准备日志目录 ──
TEAM_LOG_DIR="${LOG_DIR}/${TEAM_NAME}"
mkdir -p "$TEAM_LOG_DIR"

# ── 获取 tmux 信息 ──
if [[ -z "${TMUX:-}" ]]; then
  echo -e "${YELLOW}未检测到 tmux 环境，将创建新 session...${NC}"
  tmux new-session -d -s "claude-team" -c "$WORK_DIR"
  SESSION="claude-team"
else
  SESSION=$(tmux display-message -p '#{session_name}')
fi

# ── 打印计划 ──
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║          Claude Agent 团队编排器                     ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}团队名称${NC}  : ${GREEN}${TEAM_NAME}${NC}"
echo -e "  ${BOLD}Agent 数${NC}  : ${GREEN}${#TASKS[@]}${NC}"
echo -e "  ${BOLD}模型${NC}      : ${GREEN}${MODEL}${NC}"
echo -e "  ${BOLD}权限模式${NC}  : ${GREEN}${PERM_MODE}${NC}"
echo -e "  ${BOLD}Worktree${NC}  : ${GREEN}${USE_WORKTREE}${NC}"
echo -e "  ${BOLD}Ralph Loop${NC}: ${GREEN}${USE_RALPH}${NC}$(${USE_RALPH} && echo -e " (最多${RALPH_MAX_ITER}轮${RALPH_VERIFY:+, 验证: ${RALPH_VERIFY}})")"
echo -e "  ${BOLD}工作目录${NC}  : ${GREEN}${WORK_DIR}${NC}"
echo -e "  ${BOLD}日志目录${NC}  : ${GREEN}${TEAM_LOG_DIR}${NC}"
echo ""
echo -e "  ${BOLD}任务分配:${NC}"
for i in "${!TASKS[@]}"; do
  echo -e "    ${YELLOW}[$((i+1))]${NC} ${BOLD}${ROLES[$i]}${NC}"
  echo -e "        ${TASKS[$i]}"
done
echo ""

if $DRY_RUN; then
  echo -e "${YELLOW}[DRY RUN] 以上为执行计划，未实际启动。${NC}"
  exit 0
fi

# ── 创建状态文件 ──
STATUS_FILE="${TEAM_LOG_DIR}/status.json"
echo '{"team":"'"$TEAM_NAME"'","started":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","agents":[' > "$STATUS_FILE"
for i in "${!TASKS[@]}"; do
  [[ $i -gt 0 ]] && echo ',' >> "$STATUS_FILE"
  echo '{"id":'"$i"',"role":"'"${ROLES[$i]}"'","status":"pending","start_time":null,"end_time":null}' >> "$STATUS_FILE"
done
echo ']}' >> "$STATUS_FILE"

# ── 创建 tmux window + 分屏 ──
tmux new-window -t "$SESSION" -n "$TEAM_NAME" -c "$WORK_DIR"
WINDOW="$TEAM_NAME"

# 创建监控面板（面板0）
tmux send-keys -t "$SESSION:$WINDOW.0" "watch -n2 -c 'bash ~/.claude/scripts/team-status.sh $TEAM_LOG_DIR'" Enter

for i in "${!TASKS[@]}"; do
  # 为每个 agent 创建新面板
  tmux split-window -t "$SESSION:$WINDOW" -c "$WORK_DIR"
  PANE_IDX=$((i + 1))

  # 构建 claude 命令
  AGENT_LOG="${TEAM_LOG_DIR}/agent-${i}.log"
  AGENT_STATUS="${TEAM_LOG_DIR}/agent-${i}.status"

  # 写入初始状态
  echo "pending" > "$AGENT_STATUS"

  # 构建 wrapper 脚本（处理状态追踪）
  AGENT_SCRIPT="${TEAM_LOG_DIR}/run-agent-${i}.sh"
  cat > "$AGENT_SCRIPT" << AGENTEOF
#!/bin/bash
echo "running" > "$AGENT_STATUS"
echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${TEAM_LOG_DIR}/agent-${i}.start"
echo -e "\033[1;36m[$((i+1))/${#TASKS[@]}] ${ROLES[$i]}\033[0m"
echo -e "\033[0;33m任务: ${TASKS[$i]}\033[0m"
echo "────────────────────────────────────"
AGENTEOF

  if $USE_RALPH; then
    # ── Ralph Loop 模式：用 ralph-loop.sh 包装 ──
    RALPH_ARGS="-m $MODEL -p $PERM_MODE -n $RALPH_MAX_ITER --label '${ROLES[$i]}' -c"
    $USE_WORKTREE && RALPH_ARGS+=" -w"
    [[ -n "$RALPH_VERIFY" ]] && RALPH_ARGS+=" --verify '$RALPH_VERIFY'"

    cat >> "$AGENT_SCRIPT" << AGENTEOF

PROMPT=\$(cat <<'PROMPTEOF'
${TASKS[$i]}

完成所有任务后，请输出: <done>COMPLETE</done>
PROMPTEOF
)

bash ~/.claude/scripts/ralph-loop.sh $RALPH_ARGS "\$PROMPT" 2>&1 | tee "$AGENT_LOG"
EXIT_CODE=\${PIPESTATUS[0]}

echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${TEAM_LOG_DIR}/agent-${i}.end"
# 检查 ralph-loop 的完成状态
RALPH_STATUS=\$(find /tmp/ralph-loop -name status -newer "$AGENT_STATUS" -exec cat {} \; 2>/dev/null | tail -1)
if [[ "\$RALPH_STATUS" == "completed" || \$EXIT_CODE -eq 0 ]]; then
  echo "completed" > "$AGENT_STATUS"
  echo -e "\n\033[1;32m✓ ${ROLES[$i]} Ralph Loop 完成\033[0m"
else
  echo "failed" > "$AGENT_STATUS"
  echo -e "\n\033[1;31m✗ ${ROLES[$i]} Ralph Loop 未完成 (\$RALPH_STATUS)\033[0m"
fi
AGENTEOF

  else
    # ── 普通模式：单次 claude -p 执行 ──
    cat >> "$AGENT_SCRIPT" << AGENTEOF

CLAUDE_CMD="claude -p"
CLAUDE_CMD+=" --model $MODEL"
CLAUDE_CMD+=" --permission-mode $PERM_MODE"
AGENTEOF

    if $USE_WORKTREE; then
      cat >> "$AGENT_SCRIPT" << 'AGENTEOF'
CLAUDE_CMD+=" --worktree"
AGENTEOF
    fi

    cat >> "$AGENT_SCRIPT" << AGENTEOF

PROMPT=\$(cat <<'PROMPTEOF'
${TASKS[$i]}
PROMPTEOF
)

if $NO_TEE; then
  eval \$CLAUDE_CMD "\$PROMPT"
  EXIT_CODE=\$?
else
  eval \$CLAUDE_CMD "\$PROMPT" 2>&1 | tee "$AGENT_LOG"
  EXIT_CODE=\${PIPESTATUS[0]}
fi

echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${TEAM_LOG_DIR}/agent-${i}.end"
if [[ \$EXIT_CODE -eq 0 ]]; then
  echo "completed" > "$AGENT_STATUS"
  echo -e "\n\033[1;32m✓ ${ROLES[$i]} 完成\033[0m"
else
  echo "failed" > "$AGENT_STATUS"
  echo -e "\n\033[1;31m✗ ${ROLES[$i]} 失败 (exit \$EXIT_CODE)\033[0m"
fi
AGENTEOF
  fi

  chmod +x "$AGENT_SCRIPT"

  # 在面板中执行
  tmux send-keys -t "$SESSION:$WINDOW.$PANE_IDX" "bash $AGENT_SCRIPT" Enter
done

# 整理布局
tmux select-layout -t "$SESSION:$WINDOW" tiled

# 监控面板保持小一点（最上方）
tmux select-pane -t "$SESSION:$WINDOW.0"

echo -e "${GREEN}${BOLD}团队已启动！${NC}"
echo -e "  tmux window: ${CYAN}${SESSION}:${WINDOW}${NC}"
echo -e "  监控面板: ${CYAN}面板0（左上角 watch）${NC}"
echo -e "  查看状态: ${CYAN}bash ~/.claude/scripts/team-status.sh ${TEAM_LOG_DIR}${NC}"
echo -e "  合并结果: ${CYAN}bash ~/.claude/scripts/team-merge.sh ${TEAM_LOG_DIR}${NC}"
echo ""
