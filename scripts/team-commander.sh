#!/bin/bash
# ============================================================================
# team-commander.sh — 指挥官：Agent 间实时协调与分阶段编排
# ============================================================================
# 核心能力:
#   1. 分阶段执行（Phase DAG）：阶段内并行，阶段间串行
#   2. 实时通讯：上阶段产物（git diff）自动注入下阶段 prompt
#   3. 指挥官面板：实时监控 + 自动触发下一阶段
#   4. 联调阶段：合并多 agent 产物后启动集成测试
#
# 用法:
#   team-commander.sh -f phases.json         # 从 JSON 加载分阶段任务
#   team-commander.sh -f phases.json --dry-run
#
# JSON 格式:
#   {
#     "team": "名称",
#     "model": "sonnet",
#     "phases": [
#       {
#         "name": "并行开发",
#         "parallel": true,
#         "ralph": true,
#         "agents": [
#           {"role": "前端", "prompt": "...", "verify": "npm run build"},
#           {"role": "后端", "prompt": "...", "verify": "cargo check"}
#         ]
#       },
#       {
#         "name": "联调测试",
#         "inject_diff": true,    <-- 自动注入上阶段的 git diff
#         "agents": [
#           {"role": "集成测试", "prompt": "基于以上修改进行联调测试"}
#         ]
#       }
#     ]
#   }
# ============================================================================

set -euo pipefail

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

# ── 默认值 ──
JSON_FILE=""
DRY_RUN=false
LOG_DIR="/tmp/claude-commander"
POLL_INTERVAL=5

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) shift; JSON_FILE="$1" ;;
    --dry-run) DRY_RUN=true ;;
    --log-dir) shift; LOG_DIR="$1" ;;
    --poll) shift; POLL_INTERVAL="$1" ;;
    -h|--help)
      sed -n '2,/^# ====$/p' "$0" | sed 's/^# //' | sed 's/^#//'
      exit 0
      ;;
    *) echo -e "${RED}未知参数: $1${NC}"; exit 1 ;;
  esac
  shift
done

if [[ -z "$JSON_FILE" || ! -f "$JSON_FILE" ]]; then
  echo -e "${RED}请提供阶段定义文件: -f phases.json${NC}"
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo -e "${RED}需要 jq。安装: brew install jq${NC}"
  exit 1
fi

# ── 解析 JSON ──
TEAM_NAME=$(jq -r '.team // "commander"' "$JSON_FILE")
MODEL=$(jq -r '.model // "sonnet"' "$JSON_FILE")
PERM_MODE=$(jq -r '.permission_mode // "auto"' "$JSON_FILE")
PHASE_COUNT=$(jq '.phases | length' "$JSON_FILE")
WORK_DIR=$(jq -r '.work_dir // empty' "$JSON_FILE")
[[ -z "$WORK_DIR" ]] && WORK_DIR="$(pwd)"

RUN_ID="${TEAM_NAME}-$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${LOG_DIR}/${RUN_ID}"
mkdir -p "$RUN_DIR"

# 保存基准 commit（用于计算 diff）
BASE_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "none")
echo "$BASE_COMMIT" > "$RUN_DIR/base_commit"

# ── 打印计划 ──
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║       Claude Commander — 分阶段协调指挥官                 ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}团队${NC}    : ${GREEN}${TEAM_NAME}${NC}"
echo -e "  ${BOLD}阶段数${NC}  : ${GREEN}${PHASE_COUNT}${NC}"
echo -e "  ${BOLD}模型${NC}    : ${GREEN}${MODEL}${NC}"
echo -e "  ${BOLD}工作目录${NC}: ${GREEN}${WORK_DIR}${NC}"
echo -e "  ${BOLD}日志${NC}    : ${GREEN}${RUN_DIR}${NC}"
echo ""

for phase_idx in $(seq 0 $((PHASE_COUNT - 1))); do
  PHASE_NAME=$(jq -r ".phases[$phase_idx].name" "$JSON_FILE")
  PHASE_PARALLEL=$(jq -r ".phases[$phase_idx].parallel // true" "$JSON_FILE")
  PHASE_RALPH=$(jq -r ".phases[$phase_idx].ralph // false" "$JSON_FILE")
  PHASE_INJECT=$(jq -r ".phases[$phase_idx].inject_diff // false" "$JSON_FILE")
  AGENT_COUNT=$(jq ".phases[$phase_idx].agents | length" "$JSON_FILE")

  MODE_TAG=""
  [[ "$PHASE_PARALLEL" == "true" ]] && MODE_TAG+=" 并行"
  [[ "$PHASE_RALPH" == "true" ]] && MODE_TAG+=" Ralph"
  [[ "$PHASE_INJECT" == "true" ]] && MODE_TAG+=" +上阶段Diff"

  echo -e "  ${BOLD}${YELLOW}阶段 $((phase_idx+1)): ${PHASE_NAME}${NC}${GRAY}${MODE_TAG}${NC}"

  for agent_idx in $(seq 0 $((AGENT_COUNT - 1))); do
    ROLE=$(jq -r ".phases[$phase_idx].agents[$agent_idx].role" "$JSON_FILE")
    PROMPT=$(jq -r ".phases[$phase_idx].agents[$agent_idx].prompt" "$JSON_FILE")
    echo -e "    ${CYAN}•${NC} ${BOLD}${ROLE}${NC}: ${PROMPT:0:70}..."
  done
  echo ""
done

if $DRY_RUN; then
  echo -e "${YELLOW}[DRY RUN] 以上为执行计划${NC}"
  exit 0
fi

# ── tmux 设置 ──
if [[ -z "${TMUX:-}" ]]; then
  tmux new-session -d -s "commander" -c "$WORK_DIR"
  SESSION="commander"
else
  SESSION=$(tmux display-message -p '#{session_name}')
fi
tmux new-window -t "$SESSION" -n "$TEAM_NAME" -c "$WORK_DIR"
WINDOW="$TEAM_NAME"

# 面板0 = 指挥官日志
COMMANDER_LOG="$RUN_DIR/commander.log"
touch "$COMMANDER_LOG"
tmux send-keys -t "$SESSION:$WINDOW.0" "tail -f $COMMANDER_LOG" Enter

# ── 日志函数 ──
log() {
  local level="$1"; shift
  local msg="$*"
  local ts=$(date '+%H:%M:%S')
  local color=""
  case "$level" in
    INFO) color="$GREEN" ;;
    WARN) color="$YELLOW" ;;
    ERROR) color="$RED" ;;
    PHASE) color="$CYAN" ;;
    *) color="$NC" ;;
  esac
  echo -e "${GRAY}[${ts}]${NC} ${color}${BOLD}[${level}]${NC} ${msg}" >> "$COMMANDER_LOG"
  # 也打印到 stdout（指挥官自己的终端）
  echo -e "${GRAY}[${ts}]${NC} ${color}${BOLD}[${level}]${NC} ${msg}"
}

# ── 收集阶段产物（git diff） ──
collect_phase_diff() {
  local phase_name="$1"
  local diff_file="$RUN_DIR/phase-${phase_name}.diff"
  local summary_file="$RUN_DIR/phase-${phase_name}.summary"

  # 获取自 base_commit 以来的所有变更
  local current_commit=$(git rev-parse HEAD 2>/dev/null || echo "none")
  if [[ "$current_commit" != "$BASE_COMMIT" && "$BASE_COMMIT" != "none" ]]; then
    git diff "$BASE_COMMIT" --stat > "$summary_file" 2>/dev/null || true
    git diff "$BASE_COMMIT" > "$diff_file" 2>/dev/null || true
  else
    # 没有 commit，看 working tree 变更
    git diff --stat > "$summary_file" 2>/dev/null || true
    git diff > "$diff_file" 2>/dev/null || true
  fi

  echo "$diff_file"
}

# ── 启动单个 agent ──
start_agent() {
  local phase_idx=$1
  local agent_idx=$2
  local pane_idx=$3
  local extra_context="$4"

  local role=$(jq -r ".phases[$phase_idx].agents[$agent_idx].role" "$JSON_FILE")
  local prompt=$(jq -r ".phases[$phase_idx].agents[$agent_idx].prompt" "$JSON_FILE")
  local verify=$(jq -r ".phases[$phase_idx].agents[$agent_idx].verify // empty" "$JSON_FILE")
  local phase_ralph=$(jq -r ".phases[$phase_idx].ralph // false" "$JSON_FILE")
  local ralph_iter=$(jq -r ".phases[$phase_idx].ralph_max_iter // 5" "$JSON_FILE")

  local agent_id="p${phase_idx}_a${agent_idx}"
  local agent_status="$RUN_DIR/${agent_id}.status"
  local agent_log="$RUN_DIR/${agent_id}.log"
  local agent_script="$RUN_DIR/run-${agent_id}.sh"

  echo "pending" > "$agent_status"

  # 构建完整 prompt（注入上阶段 diff）
  local full_prompt="$prompt"
  if [[ -n "$extra_context" ]]; then
    full_prompt+="

---
## 上阶段完成的修改（供参考和联调）
\`\`\`diff
$(head -200 "$extra_context" 2>/dev/null || echo '无变更')
\`\`\`
请基于以上已有的修改进行你的工作。确保与上阶段的产物兼容。"
  fi

  # 写入执行脚本
  cat > "$agent_script" << 'SCRIPTHEAD'
#!/bin/bash
SCRIPTHEAD

  cat >> "$agent_script" << SCRIPTBODY
echo "running" > "$agent_status"
echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RUN_DIR/${agent_id}.start"
echo -e "\033[1;36m${role}\033[0m"
echo "────────────────────────────────"
SCRIPTBODY

  if [[ "$phase_ralph" == "true" ]]; then
    # Ralph Loop 模式
    local ralph_args="-m $MODEL -p $PERM_MODE -n $ralph_iter --label '${role}' -c"
    [[ -n "$verify" ]] && ralph_args+=" --verify '$verify'"

    cat >> "$agent_script" << SCRIPTBODY
PROMPT=\$(cat <<'PROMPTEOF'
${full_prompt}

完成所有任务后，请输出: <done>COMPLETE</done>
PROMPTEOF
)
bash ~/.claude/scripts/ralph-loop.sh $ralph_args "\$PROMPT" 2>&1 | tee "$agent_log"
EXIT_CODE=\${PIPESTATUS[0]}
SCRIPTBODY
  else
    # 单次执行模式
    cat >> "$agent_script" << SCRIPTBODY
PROMPT=\$(cat <<'PROMPTEOF'
${full_prompt}
PROMPTEOF
)
claude -p --model $MODEL --permission-mode $PERM_MODE "\$PROMPT" 2>&1 | tee "$agent_log"
EXIT_CODE=\${PIPESTATUS[0]}
SCRIPTBODY
  fi

  cat >> "$agent_script" << SCRIPTBODY

echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RUN_DIR/${agent_id}.end"
if [[ \$EXIT_CODE -eq 0 ]]; then
  echo "completed" > "$agent_status"
  echo -e "\n\033[1;32m✓ ${role} 完成\033[0m"
else
  echo "failed" > "$agent_status"
  echo -e "\n\033[1;31m✗ ${role} 失败\033[0m"
fi
SCRIPTBODY

  chmod +x "$agent_script"

  # 在 tmux 面板中启动
  tmux send-keys -t "$SESSION:$WINDOW.$pane_idx" "cd $WORK_DIR && bash $agent_script" Enter

  log INFO "启动 Agent [${role}] → 面板 $pane_idx"
}

# ── 等待阶段内所有 agent 完成 ──
wait_for_phase() {
  local phase_idx=$1
  local agent_count=$2

  log INFO "等待阶段 $((phase_idx+1)) 的 ${agent_count} 个 agent 完成..."

  while true; do
    local completed=0
    local failed=0
    local running=0

    for agent_idx in $(seq 0 $((agent_count - 1))); do
      local agent_id="p${phase_idx}_a${agent_idx}"
      local status=$(cat "$RUN_DIR/${agent_id}.status" 2>/dev/null || echo "pending")
      case "$status" in
        completed) ((completed++)) ;;
        failed) ((failed++)) ;;
        running) ((running++)) ;;
      esac
    done

    # 更新指挥官面板状态
    local total=$((completed + failed + running + (agent_count - completed - failed - running)))

    if [[ $((completed + failed)) -ge $agent_count ]]; then
      if [[ $failed -gt 0 ]]; then
        log WARN "阶段 $((phase_idx+1)) 完成: ${completed} 成功, ${failed} 失败"
      else
        log INFO "阶段 $((phase_idx+1)) 全部完成: ${completed}/${agent_count} 成功"
      fi
      return $failed
    fi

    sleep "$POLL_INTERVAL"
  done
}

# ── 主循环: 逐阶段执行 ──
log PHASE "═══ 指挥官启动 ═══"
log INFO "团队: ${TEAM_NAME}, 阶段数: ${PHASE_COUNT}"

ACCUMULATED_DIFF=""
TOTAL_PANE=1  # 面板0 是指挥官

for phase_idx in $(seq 0 $((PHASE_COUNT - 1))); do
  PHASE_NAME=$(jq -r ".phases[$phase_idx].name" "$JSON_FILE")
  PHASE_INJECT=$(jq -r ".phases[$phase_idx].inject_diff // false" "$JSON_FILE")
  AGENT_COUNT=$(jq ".phases[$phase_idx].agents | length" "$JSON_FILE")

  log PHASE "━━━ 阶段 $((phase_idx+1))/${PHASE_COUNT}: ${PHASE_NAME} ━━━"

  # 如果需要注入上阶段 diff
  INJECT_FILE=""
  if [[ "$PHASE_INJECT" == "true" && -n "$ACCUMULATED_DIFF" ]]; then
    INJECT_FILE="$ACCUMULATED_DIFF"
    log INFO "注入上阶段变更: $(wc -l < "$INJECT_FILE" | tr -d ' ') 行 diff"
  fi

  # 为本阶段的 agent 创建 tmux 面板
  for agent_idx in $(seq 0 $((AGENT_COUNT - 1))); do
    tmux split-window -t "$SESSION:$WINDOW" -c "$WORK_DIR"
    tmux select-layout -t "$SESSION:$WINDOW" tiled 2>/dev/null || true
    start_agent "$phase_idx" "$agent_idx" "$TOTAL_PANE" "$INJECT_FILE"
    ((TOTAL_PANE++))
  done

  tmux select-layout -t "$SESSION:$WINDOW" tiled 2>/dev/null || true

  # 等待本阶段完成
  PHASE_FAILURES=0
  wait_for_phase "$phase_idx" "$AGENT_COUNT" || PHASE_FAILURES=$?

  # 收集本阶段产物
  ACCUMULATED_DIFF=$(collect_phase_diff "$PHASE_NAME")
  log INFO "阶段 ${PHASE_NAME} 产物已收集: $ACCUMULATED_DIFF"

  # 如果有失败且这不是最后阶段，询问是否继续
  if [[ $PHASE_FAILURES -gt 0 && $phase_idx -lt $((PHASE_COUNT - 1)) ]]; then
    log WARN "阶段 ${PHASE_NAME} 有 ${PHASE_FAILURES} 个失败，自动继续下一阶段（失败 agent 的产物可能不完整）"
  fi

  # 阶段间自动 commit（保存检查点）
  if git diff --quiet 2>/dev/null; then
    log INFO "本阶段无文件变更"
  else
    git add -A 2>/dev/null || true
    git commit -m "commander(${TEAM_NAME}): 阶段${phase_idx+1} ${PHASE_NAME} 完成" 2>/dev/null || true
    log INFO "检查点已提交: 阶段 ${PHASE_NAME}"
  fi

  log PHASE "━━━ 阶段 $((phase_idx+1)) 结束 ━━━"
  echo ""
done

# ── 最终报告 ──
log PHASE "═══ 全部阶段执行完毕 ═══"
log INFO "日志目录: $RUN_DIR"
log INFO "查看详细: ls $RUN_DIR/*.log"

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║                  指挥官: 任务完成                         ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# 打印各阶段摘要
for phase_idx in $(seq 0 $((PHASE_COUNT - 1))); do
  PHASE_NAME=$(jq -r ".phases[$phase_idx].name" "$JSON_FILE")
  AGENT_COUNT=$(jq ".phases[$phase_idx].agents | length" "$JSON_FILE")
  completed=0
  failed=0
  for agent_idx in $(seq 0 $((AGENT_COUNT - 1))); do
    s=$(cat "$RUN_DIR/p${phase_idx}_a${agent_idx}.status" 2>/dev/null || echo "unknown")
    [[ "$s" == "completed" ]] && ((completed++))
    [[ "$s" == "failed" ]] && ((failed++))
  done

  if [[ $failed -eq 0 ]]; then
    echo -e "  ${GREEN}✓${NC} ${BOLD}${PHASE_NAME}${NC}: ${completed}/${AGENT_COUNT} 完成"
  else
    echo -e "  ${YELLOW}⚠${NC} ${BOLD}${PHASE_NAME}${NC}: ${completed} 成功, ${RED}${failed} 失败${NC}"
  fi
done
echo ""
