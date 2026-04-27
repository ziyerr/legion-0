#!/bin/bash
# ============================================================================
# stop-hook.sh — Legion 停止前检查紧急消息
# ============================================================================
# claude 停止前运行。有 urgent/critical 未读消息时阻止停止。
# ============================================================================

# 非 legion 模式，允许停止
[[ -z "${CLAUDE_LEGION_TEAM_ID:-}" ]] && echo '{"ok": true}' && exit 0

LEGION_DIR="${LEGION_DIR:-$HOME/.claude/legion}"
TEAM_DIR="$LEGION_DIR/team-$CLAUDE_LEGION_TEAM_ID"

# ── 新邮箱系统紧急消息检查 ──
INBOXES_DIR="$TEAM_DIR/inboxes"
if [[ -d "$INBOXES_DIR" ]]; then
  new_urgent=$(python3 -c "
import json, os, glob
inbox_dir = '$INBOXES_DIR'
count = 0
for f in glob.glob(os.path.join(inbox_dir, '*.json')):
    if f.endswith('.lock'): continue
    try:
        with open(f) as fh:
            msgs = json.load(fh)
        for m in msgs:
            if not m.get('read', False) and m.get('type') in ('shutdown', 'gate'):
                count += 1
            elif not m.get('read', False) and 'urgent' in str(m.get('summary', '')).lower():
                count += 1
    except: pass
print(count)
" 2>/dev/null)
  if [[ "$new_urgent" -gt 0 ]]; then
    echo "{\"ok\": false, \"reason\": \"你有 $new_urgent 条紧急邮箱未读消息，请先处理再停止。\"}"
    exit 0
  fi
fi

# 检查 taskboard 中是否有分配给自己的未完成任务
TASKBOARD="$LEGION_DIR/taskboard.json"
if [[ -f "$TASKBOARD" ]]; then
  pending=$(python3 -c "
import json
with open('$TASKBOARD') as f:
    tb = json.load(f)
count = 0
for task in tb.get('tasks', []):
    if task.get('assignee') == '$CLAUDE_LEGION_TEAM_ID' and task.get('status') in ('pending', 'in_progress'):
        count += 1
print(count)
" 2>/dev/null)

  if [[ "$pending" -gt 0 ]]; then
    echo "{\"ok\": false, \"reason\": \"你还有 $pending 个未完成的任务板任务。请先完成或转交。\"}"
    exit 0
  fi
fi

# ── STATE.json 接棒强制：工具调用 >100 的 teammate 必须写 STATE.json ──
if [[ "$CLAUDE_LEGION_TEAM_ID" != L1-* && "$CLAUDE_LEGION_TEAM_ID" != "L1" ]]; then
  HEARTBEAT_COUNTER_FILE="$TEAM_DIR/heartbeat.counter"
  _tc=$(cat "$HEARTBEAT_COUNTER_FILE" 2>/dev/null || echo "0")
  [[ "$_tc" =~ ^[0-9]+$ ]] || _tc=0

  if [[ $_tc -ge 100 ]]; then
    # 检查 STATE.json 是否存在且有内容
    STATE_FILE=""
    for _sf in ".planning/STATE.json" ".planning/STATE.md"; do
      if [[ -f "$_sf" ]]; then
        STATE_FILE="$_sf"
        break
      fi
    done

    if [[ -z "$STATE_FILE" ]]; then
      echo "{\"ok\": false, \"reason\": \"你已执行 ${_tc} 次工具调用但未写接棒状态文件。请先将进度写入 .planning/STATE.json（Schema: {snapshot_by, timestamp, completed, pending, failed_attempts, verification}），然后再退出。这样替代者可以接续你的工作。\"}"
      exit 0
    fi

    # 检查文件是否过小（可能是空模板）
    _state_size=$(wc -c < "$STATE_FILE" 2>/dev/null | tr -d ' ')
    if [[ "${_state_size:-0}" -lt 50 ]]; then
      echo "{\"ok\": false, \"reason\": \"STATE 文件 ${STATE_FILE} 内容过少（${_state_size}字节）。请补充 completed/pending/failed_attempts 等关键信息后再退出。\"}"
      exit 0
    fi
  fi
fi

# ── Arsenal: 检测本次会话是否新增了战法 ──
ARSENAL_CHECK="$HOME/.claude/scripts/arsenal-check.sh"
SESSION_SNAPSHOT="/tmp/arsenal-session-snapshot.md5"
if [[ -x "$ARSENAL_CHECK" ]]; then
  # 首次运行：保存快照
  if [[ ! -f "$SESSION_SNAPSHOT" ]]; then
    "$ARSENAL_CHECK" snapshot 2>/dev/null
  else
    # 后续运行：检测变化
    diff_result=$("$ARSENAL_CHECK" diff 2>/dev/null)
    if [[ "$diff_result" == "CHANGED" ]]; then
      # 新增战法检测到，运行快速巡检（完整性+索引刷新）
      "$ARSENAL_CHECK" quick >/dev/null 2>&1
      # 下次不再重复提示：更新快照
      "$ARSENAL_CHECK" snapshot 2>/dev/null
    fi
  fi
fi

# ── Team Memory Sync: L1 停止时自动回收团队经验 ──
# 使用当前项目 .claude/scripts/team-memory-sync.sh（若存在）
# 可通过 TEAM_MEMORY_SYNC env var 覆盖为其他路径
if [[ "$CLAUDE_LEGION_TEAM_ID" == L1-* ]]; then
  TEAM_MEMORY_SYNC="${TEAM_MEMORY_SYNC:-$(pwd)/.claude/scripts/team-memory-sync.sh}"
  if [[ -x "$TEAM_MEMORY_SYNC" && -d ".planning" ]]; then
    # 后台异步运行，不阻塞停止
    (bash "$TEAM_MEMORY_SYNC" --json > /tmp/team-memory-sync-last.json 2>/tmp/team-memory-sync-last.log) &
  fi
fi

# ── Retrospector: 从 observations 提取重复模式 ──
RETROSPECTOR="$HOME/.claude/scripts/retrospector.sh"
if [[ -x "$RETROSPECTOR" && "$CLAUDE_LEGION_TEAM_ID" == L1-* ]]; then
  ("$RETROSPECTOR" quick > /tmp/retrospector-last.json 2>/dev/null) &
fi

# ── Desktop Notify: macOS 桌面通知（借鉴 ECC）──
# 只对 L1 指挥官发通知（避免 teammate 刷屏）
if [[ "$CLAUDE_LEGION_TEAM_ID" == L1-* && "$(uname)" == "Darwin" ]]; then
  # 从 stdin 已被消费，用 team ID 作为通知标识
  osascript -e "display notification \"${CLAUDE_LEGION_TEAM_ID} 已完成回复\" with title \"Claude Legion\"" 2>/dev/null &
fi

# ── 退出通知由 Commander daemon 的 gc_dead_commanders 统一处理 ──
# Stop hook 每次 turn 结束都会触发，不是只在最终退出时，
# 所以不在此发送 offline 通知（否则每次 turn 结束都会重复发送）。
# Commander daemon 通过检测 tmux 进程状态来判断真正退出，保证只广播一次。

echo '{"ok": true}'
exit 0
