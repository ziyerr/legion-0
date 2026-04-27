#!/bin/bash
# ============================================================================
# elite.sh — Claude 亲自指挥的精英编排器（供 Claude 会话内调用）
# ============================================================================
#
# 与 team-orchestrator.sh 的区别：
#   team-orchestrator.sh = 脚本自治（启动后 Claude 看不到过程）
#   elite.sh             = Claude 亲自指挥（Claude 通过日志文件全程参与）
#
# 本脚本只做"手脚"动作，所有"大脑"决策由调用方 Claude 完成：
#   - 在同一 window 内创建 pane + 启动 claude -p worker
#   - 轮询等待完成
#   - 关闭 pane
#
# 布局：所有 agent 在同一个 tmux window 内以 tiled pane 排列，
#       第一个 pane (pane.0) 是状态面板（watch 刷新），
#       后续 pane 各跑一个 agent。
#
# 用法（由 Claude 在 Bash 工具中调用）：
#
#   # 初始化 tmux window（状态面板）
#   elite.sh init --session 11 --name "团队名"
#
#   # 启动 workers（在同一 window 内新建 pane）
#   elite.sh start --id agent-0 --model opus --perm auto --prompt "任务..."
#
#   # 检查是否完成
#   elite.sh poll --id agent-0
#
#   # 关闭 pane
#   elite.sh kill --id agent-0
#
# ============================================================================

set -euo pipefail

LOG_BASE="/tmp/claude-elite-live"
mkdir -p "$LOG_BASE"

ACTION="${1:-help}"
shift || true

# 参数解析
ID="" ; MODEL="opus" ; PERM="auto" ; PROMPT="" ; SESSION="" ; WINDOW="" ; WORK_DIR="$(pwd)" ; NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --id) shift; ID="$1" ;;
    --model) shift; MODEL="$1" ;;
    --perm) shift; PERM="$1" ;;
    --prompt) shift; PROMPT="$1" ;;
    --session) shift; SESSION="$1" ;;
    --window) shift; WINDOW="$1" ;;
    --work-dir) shift; WORK_DIR="$1" ;;
    --name) shift; NAME="$1" ;;
    *) ;;
  esac
  shift
done

# ── 辅助：获取主 window 名 ──
_get_main_window() {
  cat "$LOG_BASE/main_window" 2>/dev/null || echo ""
}

# ── 辅助：获取 session ──
_get_session() {
  cat "$LOG_BASE/session" 2>/dev/null || tmux display-message -p '#{session_name}' 2>/dev/null || echo "0"
}

# ── 辅助：重排布局 ──
_retile() {
  local sess="$1"
  local win="$2"
  tmux select-layout -t "$sess:$win" tiled 2>/dev/null || true
}

# ── 辅助：更新状态面板 ──
_update_status() {
  local sf="$LOG_BASE/status.txt"
  local team=$(cat "$LOG_BASE/team_name" 2>/dev/null || echo "elite")
  local now=$(date '+%H:%M:%S')
  local running=0 done=0 failed=0 total=0

  {
    echo "╔═══════════════════════════════════════╗"
    echo "║  ELITE — $team"
    echo "║  更新: $now"
    echo "╠═══════════════════════════════════════╣"

    for log_f in "$LOG_BASE"/*.log; do
      [[ -f "$log_f" ]] || continue
      local aid=$(basename "$log_f" .log)
      local done_f="$LOG_BASE/${aid}.done"
      local exit_f="$LOG_BASE/${aid}.exit"
      ((total++))

      if [[ -f "$done_f" ]]; then
        local ec=$(cat "$exit_f" 2>/dev/null || echo "-1")
        if [[ "$ec" == "0" ]]; then
          echo "║  ✓ $aid (完成)"
          ((done++))
        else
          echo "║  ✗ $aid (失败 exit=$ec)"
          ((failed++))
        fi
      else
        local lines=$(wc -l < "$log_f" 2>/dev/null | tr -d ' ')
        echo "║  ⟳ $aid (运行中 ${lines}行)"
        ((running++))
      fi
    done

    if [[ $total -eq 0 ]]; then
      echo "║  (无 agent)"
    fi

    echo "╠═══════════════════════════════════════╣"
    echo "║  总计:$total  运行:$running  完成:$done  失败:$failed"
    echo "╚═══════════════════════════════════════╝"
  } > "$sf"
}

case "$ACTION" in

  # ── 初始化：创建主 window，pane.0 作状态面板 ──
  init)
    [[ -z "$SESSION" ]] && SESSION=$(tmux display-message -p '#{session_name}' 2>/dev/null || echo "0")
    [[ -z "$NAME" ]] && NAME="elite-$(date +%H%M%S)"

    MAIN_WIN="e-$NAME"
    STATUS_FILE="$LOG_BASE/status.txt"
    echo "$NAME" > "$LOG_BASE/team_name"
    echo "$SESSION" > "$LOG_BASE/session"
    echo "$MAIN_WIN" > "$LOG_BASE/main_window"
    cat > "$STATUS_FILE" << STATEOF
╔═══════════════════════════════════════╗
║  ELITE ORCHESTRATOR — $NAME
║  等待指挥官指令...
║  Agents: (无)
╚═══════════════════════════════════════╝
STATEOF

    # 创建主 window，pane.0 用于状态显示
    tmux new-window -t "$SESSION:" -n "$MAIN_WIN" -c "$WORK_DIR"

    # 记录状态 pane 的 ID，后续不能误删
    STATUS_PANE_ID=$(tmux display-message -t "$SESSION:$MAIN_WIN.0" -p '#{pane_id}')
    echo "$STATUS_PANE_ID" > "$LOG_BASE/status_pane_id"

    tmux send-keys -t "$SESSION:$MAIN_WIN.0" "while true; do clear; cat $STATUS_FILE; sleep 2; done" Enter

    echo '{"session":"'"$SESSION"'","window":"'"$MAIN_WIN"'","status_file":"'"$STATUS_FILE"'","log_base":"'"$LOG_BASE"'"}'
    ;;

  # ── 启动 agent：在主 window 内 split 新 pane ──
  start)
    [[ -z "$ID" ]] && { echo "需要 --id"; exit 1; }
    [[ -z "$PROMPT" ]] && { echo "需要 --prompt"; exit 1; }
    [[ -z "$SESSION" ]] && SESSION=$(_get_session)

    MAIN_WIN=$(_get_main_window)
    [[ -z "$MAIN_WIN" ]] && { echo "错误: 未初始化，请先运行 init"; exit 1; }

    LOG_FILE="$LOG_BASE/${ID}.log"
    DONE_FILE="$LOG_BASE/${ID}.done"
    EXIT_FILE="$LOG_BASE/${ID}.exit"
    PROMPT_FILE="$LOG_BASE/${ID}.prompt"

    # 清理旧状态
    rm -f "$DONE_FILE" "$EXIT_FILE" "$LOG_FILE"

    # 保存 prompt 到文件（避免 shell 转义问题）
    echo "$PROMPT" > "$PROMPT_FILE"

    # 在主 window 内 split 新 pane
    PANE_ID=$(tmux split-window -t "$SESSION:$MAIN_WIN" -c "$WORK_DIR" -P -F '#{pane_id}')

    # 重排为 tiled 布局（均匀分配空间）
    _retile "$SESSION" "$MAIN_WIN"

    # 在新 pane 中启动 claude -p
    tmux send-keys -t "$PANE_ID" "echo -e '\\033[1;36m[$ID]\\033[0m 启动...' && claude -p --model $MODEL --permission-mode $PERM \"\$(cat $PROMPT_FILE)\" 2>&1 | tee $LOG_FILE; echo \$? > $EXIT_FILE; touch $DONE_FILE" Enter

    # 记录 pane ID，用于后续关闭
    echo "$PANE_ID" > "$LOG_BASE/${ID}.pane"

    # 更新状态面板
    _update_status

    echo '{"id":"'"$ID"'","pane_id":"'"$PANE_ID"'","log":"'"$LOG_FILE"'","done":"'"$DONE_FILE"'"}'
    ;;

  # ── 轮询：检查 agent 是否完成 ──
  poll)
    [[ -z "$ID" ]] && { echo "需要 --id"; exit 1; }
    DONE_FILE="$LOG_BASE/${ID}.done"
    EXIT_FILE="$LOG_BASE/${ID}.exit"
    LOG_FILE="$LOG_BASE/${ID}.log"

    if [[ -f "$DONE_FILE" ]]; then
      EXIT_CODE=$(cat "$EXIT_FILE" 2>/dev/null || echo "-1")
      LINES=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "0")
      echo '{"done":true,"exit_code":'"$EXIT_CODE"',"log_lines":'"$LINES"'}'
    else
      LINES=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "0")
      echo '{"done":false,"log_lines":'"$LINES"'}'
    fi
    ;;

  # ── 批量轮询 ──
  poll-all)
    ALL_DONE=true
    RESULTS="{"
    for log_f in "$LOG_BASE"/*.log; do
      [[ -f "$log_f" ]] || continue
      aid=$(basename "$log_f" .log)
      done_f="$LOG_BASE/${aid}.done"
      if [[ -f "$done_f" ]]; then
        ec=$(cat "$LOG_BASE/${aid}.exit" 2>/dev/null || echo "-1")
        RESULTS+="\"$aid\":{\"done\":true,\"exit_code\":$ec},"
      else
        ALL_DONE=false
        RESULTS+="\"$aid\":{\"done\":false},"
      fi
    done
    RESULTS="${RESULTS%,}}"
    if $ALL_DONE; then
      echo "{\"all_done\":true,\"agents\":$RESULTS}"
    else
      echo "{\"all_done\":false,\"agents\":$RESULTS}"
    fi
    ;;

  # ── 关闭 agent pane ──
  kill)
    [[ -z "$ID" ]] && { echo "需要 --id"; exit 1; }
    [[ -z "$SESSION" ]] && SESSION=$(_get_session)
    MAIN_WIN=$(_get_main_window)

    PANE_FILE="$LOG_BASE/${ID}.pane"
    if [[ -f "$PANE_FILE" ]]; then
      PANE_ID=$(cat "$PANE_FILE")
      tmux kill-pane -t "$PANE_ID" 2>/dev/null || true
      rm -f "$PANE_FILE"
      # 重排剩余 pane
      [[ -n "$MAIN_WIN" ]] && _retile "$SESSION" "$MAIN_WIN"
      _update_status
      echo '{"killed":"'"$ID"'"}'
    else
      echo '{"error":"pane not found for '"$ID"'"}'
    fi
    ;;

  # ── 批量关闭所有 agent pane（保留状态 pane） ──
  kill-all)
    [[ -z "$SESSION" ]] && SESSION=$(_get_session)
    MAIN_WIN=$(_get_main_window)
    STATUS_PANE_ID=$(cat "$LOG_BASE/status_pane_id" 2>/dev/null || echo "")

    KILLED=0
    for pane_f in "$LOG_BASE"/*.pane; do
      [[ -f "$pane_f" ]] || continue
      PANE_ID=$(cat "$pane_f")
      # 不要误杀状态 pane
      if [[ "$PANE_ID" != "$STATUS_PANE_ID" ]]; then
        tmux kill-pane -t "$PANE_ID" 2>/dev/null || true
        ((KILLED++))
      fi
      rm -f "$pane_f"
    done
    [[ -n "$MAIN_WIN" ]] && _retile "$SESSION" "$MAIN_WIN"
    _update_status
    echo '{"killed_count":'"$KILLED"'}'
    ;;

  # ── 更新状态面板 ──
  status)
    MSG="${NAME:-$PROMPT}"
    echo "$MSG" > "$LOG_BASE/status.txt"
    ;;

  # ── 清理 ──
  clean)
    rm -f "$LOG_BASE"/*.{log,done,exit,pane,prompt,window}
    rm -f "$LOG_BASE"/{team_name,session,main_window,status_pane_id,status.txt}
    echo '{"cleaned":true}'
    ;;

  # ── 帮助 ──
  *)
    echo "用法: elite.sh <action> [options]"
    echo "  init    --session S --name N        创建主 window（状态+多 pane）"
    echo "  start   --id ID --prompt '...'      在主 window 内新建 pane 启动 agent"
    echo "  poll    --id ID                     检查完成状态"
    echo "  poll-all                            检查所有 agent"
    echo "  kill    --id ID                     关闭 agent pane"
    echo "  kill-all                            关闭所有 agent pane（保留状态面板）"
    echo "  status  --name '消息'               更新状态面板"
    echo "  clean                               清理所有状态和日志"
    ;;
esac
