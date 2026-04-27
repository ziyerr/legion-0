#!/bin/bash
# ============================================================================
# post-tool-use.sh — Quality Gate + 观察记录 + 心跳 + 协议提醒
# ============================================================================
# 通信已由 CC useInboxPoller 处理。
# 非 legion 模式：跳过通信逻辑，但保留 Quality Gate 基础保护。
# ============================================================================

# 非 legion 模式：跳过通信，但保留 Quality Gate 基础保护
if [[ -z "${CLAUDE_LEGION_TEAM_ID:-}" ]]; then
  # 从 stdin 读取工具调用信息
  _HOOK_INPUT=$(timeout 1 cat 2>/dev/null || echo "{}")
  _TOOL_NAME=$(echo "$_HOOK_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)

  # Quality Gate: Edit/Write 后检查
  if [[ "$_TOOL_NAME" == "Edit" || "$_TOOL_NAME" == "Write" ]]; then
    _FILE_PATH=$(echo "$_HOOK_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)
    if [[ -n "$_FILE_PATH" ]]; then
      _STACK_VERIFY="$HOME/.claude/scripts/stack-verify.sh"
      if [[ -x "$_STACK_VERIFY" ]]; then
        _QG_OUTPUT=$("$_STACK_VERIFY" check "$_FILE_PATH" 2>&1)
        _QG_STATUS=$?
        _QG_CONTENT=$(printf '%s\n' "$_QG_OUTPUT" | head -1)
        if [[ "$_QG_CONTENT" == FAIL* ]]; then
          _desc="${_QG_CONTENT#FAIL|}"
          _QG_CONTEXT="🔴 Quality Gate 失败: ${_desc}。请修复后继续。" \
          python3 -c "import json, os; print(json.dumps({'additionalContext': os.environ.get('_QG_CONTEXT', '')}, ensure_ascii=False))"
        elif [[ "$_QG_STATUS" -ne 0 ]]; then
          _desc="${_QG_CONTENT:-stack-verify exited with status $_QG_STATUS}"
          _QG_CONTEXT="🔴 Quality Gate 失败: ${_desc}。请修复后继续。" \
          python3 -c "import json, os; print(json.dumps({'additionalContext': os.environ.get('_QG_CONTEXT', '')}, ensure_ascii=False))"
        fi
      fi
    fi
  fi

  exit 0
fi

LEGION_DIR="${LEGION_DIR:-$HOME/.claude/legion}"
TEAM_DIR="$LEGION_DIR/team-$CLAUDE_LEGION_TEAM_ID"
HEARTBEAT_COUNTER_FILE="$TEAM_DIR/heartbeat.counter"
HEARTBEAT_INTERVAL=10  # 每 10 次工具调用发一次心跳

# 确保目录存在
mkdir -p "$TEAM_DIR"

# ── Commander 心跳检测：60秒无心跳 → 警告通信失效 ──
COMMANDER_HEARTBEAT="$LEGION_DIR/commander.heartbeat"
if [[ -f "$COMMANDER_HEARTBEAT" ]]; then
  _hb_age=$(python3 -c "
import os, time
try:
    mtime = os.path.getmtime('$COMMANDER_HEARTBEAT')
    age = time.time() - mtime
    print(int(age))
except:
    print(0)
" 2>/dev/null)
  if [[ "${_hb_age:-0}" -gt 60 ]]; then
    QUALITY_GATE_MSG="${QUALITY_GATE_MSG:+$QUALITY_GATE_MSG\n}⚠️ Commander 心跳超时（${_hb_age}秒无更新）。消息路由可能已停止。如果你发送的消息没有被处理，请通知用户检查 Commander 进程。"
  fi
fi

# ── 从 stdin 读取工具调用信息 ──
HOOK_INPUT=$(timeout 1 cat 2>/dev/null || echo "{}")
TOOL_NAME=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)

# ── L1 指挥官：检测团队创建（TeamCreate 或 Agent），自动标记 recon_done / has_teammates ──
if [[ "$CLAUDE_LEGION_TEAM_ID" == L1-* && ("$TOOL_NAME" == "TeamCreate" || "$TOOL_NAME" == "Agent") ]]; then
  PHASE_FILE="$TEAM_DIR/task_phase.json"
  echo "$HOOK_INPUT" | python3 -c "
import sys, json

d = json.load(sys.stdin)
inp = d.get('tool_input', {})
desc = (str(inp.get('description', '')) + str(inp.get('prompt', ''))).lower()
recon_kw = ['参谋', 'recon', '侦察', '调研', 'scout', 'research']

try:
    with open('$PHASE_FILE') as f:
        phase = json.load(f)
except:
    phase = {}

if any(kw in desc for kw in recon_kw):
    phase['recon_done'] = True
phase['has_teammates'] = True

with open('$PHASE_FILE', 'w') as f:
    json.dump(phase, f)
" 2>/dev/null
fi

# ── 自动心跳汇报（每 N 次工具调用向 L1 发一次进度快照）──
_counter=$(cat "$HEARTBEAT_COUNTER_FILE" 2>/dev/null || echo "0")
[[ "$_counter" =~ ^[0-9]+$ ]] || _counter=0
_counter=$((_counter + 1))
echo "$_counter" > "$HEARTBEAT_COUNTER_FILE"

if [[ $((_counter % HEARTBEAT_INTERVAL)) -eq 0 && "$CLAUDE_LEGION_TEAM_ID" != "L1" ]]; then
  # 收集快照：当前工具调用次数 + 最近修改的文件
  python3 -c "
import json, uuid, subprocess
from datetime import datetime

team_id = '$CLAUDE_LEGION_TEAM_ID'
counter = $_counter

# 获取最近 git 修改（本 team 的活动指纹）
try:
    result = subprocess.run(['git', 'diff', '--name-only'], capture_output=True, text=True, timeout=3)
    changed = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()][:5]
except:
    changed = []

msg = {
    'id': f'msg-{uuid.uuid4().hex[:8]}',
    'ts': datetime.now().isoformat(),
    'from': team_id,
    'to': 'L1',
    'type': 'notify',
    'priority': 'normal',
    'payload': {
        'event': 'heartbeat',
        'tool_calls': counter,
        'active_files': changed
    }
}

legion_dir = '$LEGION_DIR'
outbox = f'{legion_dir}/team-{team_id}/outbox.jsonl'
with open(outbox, 'a') as f:
    f.write(json.dumps(msg, ensure_ascii=False) + '\n')
" 2>/dev/null
fi

# ── Inbox 轮询：每 20 次工具调用检查未读消息 ──
INBOX_POLL_INTERVAL=20
INBOX_FILE="$TEAM_DIR/inbox.json"
INBOX_MSG=""
if [[ $((_counter % INBOX_POLL_INTERVAL)) -eq 0 && -f "$INBOX_FILE" ]]; then
  INBOX_MSG=$(python3 -c "
import json, fcntl, os

inbox = '$INBOX_FILE'
lock = inbox + '.lock'
if not os.path.exists(inbox):
    exit(0)

open(lock, 'a').close()
with open(lock) as lf:
    fcntl.flock(lf, fcntl.LOCK_EX)
    try:
        msgs = json.load(open(inbox))
    except:
        msgs = []

    unread = [m for m in msgs if not m.get('read', False)]
    if not unread:
        fcntl.flock(lf, fcntl.LOCK_UN)
        exit(0)

    # 标记为已读
    for m in msgs:
        m['read'] = True
    json.dump(msgs, open(inbox, 'w'), ensure_ascii=False, indent=2)
    fcntl.flock(lf, fcntl.LOCK_UN)

    # 格式化输出
    lines = []
    for m in unread:
        sender = m.get('from', '?')
        payload = m.get('payload', '')
        ts = m.get('timestamp', '')
        lines.append(f'[{sender} {ts}] {payload}')
    print('📨 收到 ' + str(len(unread)) + ' 条跨军团消息：\n' + '\n'.join(lines))
" 2>/dev/null)
fi

# ── L1 指挥官任务阶段状态机（代码硬门控）──
if [[ "$CLAUDE_LEGION_TEAM_ID" == L1-* ]]; then
  PHASE_FILE="$TEAM_DIR/task_phase.json"

  # 从 stdin 拿到最新工具调用（hook input 已经被上层读过了，这里用环境推断）
  # 通过检测 teammate 创建和审计命令来推进阶段
  python3 -c "
import json, os
from datetime import datetime

phase_file = '$PHASE_FILE'
counter = $_counter

try:
    with open(phase_file) as f:
        state = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    state = {'phase': 'idle', 'task_start_counter': 0, 'recon_done': False, 'has_teammates': False, 'audit_started': False}

# 检测阶段转换信号（通过文件系统状态推断）
team_dir = '$TEAM_DIR'
legion_dir = '$LEGION_DIR'
team_id = '$CLAUDE_LEGION_TEAM_ID'

# 检测是否创建了 teammate（outbox 中有 spawn 相关消息）
outbox_path = os.path.join(team_dir, 'outbox.jsonl')
if os.path.exists(outbox_path):
    try:
        with open(outbox_path) as f:
            lines = f.readlines()
        for line in lines[-10:]:  # 检查最近 10 条
            try:
                msg = json.loads(line.strip())
                event = msg.get('payload', {}).get('event', '')
                if 'spawn' in event or 'teammate' in event.lower():
                    state['has_teammates'] = True
            except:
                pass
    except:
        pass

# 阶段推进逻辑
phase = state.get('phase', 'idle')

# idle → active：检测到工具调用开始增长
if phase == 'idle' and counter > state.get('task_start_counter', 0) + 3:
    state['phase'] = 'active'
    state['task_start_counter'] = counter
    state['recon_done'] = False
    state['has_teammates'] = False
    state['audit_started'] = False
    state['source_edit_count'] = 0

with open(phase_file, 'w') as f:
    json.dump(state, f)
" 2>/dev/null
fi

# ── Strategic Compact: 在逻辑边界建议 /compact（借鉴 ECC）──
COMPACT_THRESHOLD=${COMPACT_THRESHOLD:-80}
COMPACT_REMINDER_INTERVAL=30
COMPACT_MSG=""
if [[ $((_counter % COMPACT_REMINDER_INTERVAL)) -eq 0 && _counter -ge $COMPACT_THRESHOLD ]]; then
  # 只对 L1 指挥官提醒（teammate 由指挥官管理）
  if [[ "$CLAUDE_LEGION_TEAM_ID" == L1-* ]]; then
    COMPACT_MSG="⚡ 上下文保鲜提醒（第 ${_counter} 次工具调用）：
Anthropic 研究证实：上下文重置 > 上下文压缩。压缩会导致'上下文焦虑'（模型过早收尾）。
建议策略：
- 阶段切换（侦察→实现、实现→审计）→ 创建新 teammate 接棒（天然重置），通过 .planning/ 传递上下文
- 同一 agent 内切换任务 → /compact 压缩（次优但可接受）
- teammate 长时运行 200+ 调用 → 让它写 STATE.md 后退出，新 teammate 读 STATE.md 接续
关键：外部文件（.planning/STATE.md）是跨 agent 的记忆，上下文窗口只是临时工作区。"
  fi
fi

# ── Quality Gate: Edit/Write 后技术栈感知的自动验证 ──
QUALITY_GATE_MSG="${QUALITY_GATE_MSG:-}"
if [[ "$TOOL_NAME" == "Edit" || "$TOOL_NAME" == "Write" ]]; then
  FILE_PATH=$(echo "$HOOK_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)
  if [[ -n "$FILE_PATH" ]]; then
    QG_RESULT_FILE="$TEAM_DIR/.quality_gate_result"
    STACK_VERIFY="$HOME/.claude/scripts/stack-verify.sh"
    if [[ -x "$STACK_VERIFY" ]]; then
      # 异步运行技术栈验证
      (result=$("$STACK_VERIFY" check "$FILE_PATH" 2>&1)
       if [[ "$result" == FAIL* ]]; then
         echo "$result" > "$QG_RESULT_FILE"
       else
         rm -f "$QG_RESULT_FILE"
       fi
      ) &
    fi
  fi
fi

# QG 结果读取：每次工具调用都检查（不限于 Edit/Write）
QG_RESULT_FILE="$TEAM_DIR/.quality_gate_result"
if [[ -f "$QG_RESULT_FILE" ]]; then
  QG_CONTENT=$(cat "$QG_RESULT_FILE" 2>/dev/null)
  if [[ "$QG_CONTENT" == FAIL* ]]; then
    _desc="${QG_CONTENT#FAIL|}"
    QUALITY_GATE_MSG="🔴 Quality Gate 失败: ${_desc}。请修复后继续。"
    # ── 失败观察记录（Harness 哲学：每次失败都是训练数据）──
    OBS_FILE="$HOME/.claude/homunculus/observations.jsonl"
    mkdir -p "$(dirname "$OBS_FILE")"
    _MB_OBS_FILE="$OBS_FILE" _MB_OBS_TEAM="${CLAUDE_LEGION_TEAM_ID}" \
    _MB_OBS_FILEPATH="${FILE_PATH:-unknown}" _MB_OBS_TOOL="${TOOL_NAME:-unknown}" \
    _MB_OBS_ERROR="$QG_CONTENT" \
    python3 -c "
import json, os
from datetime import datetime
obs = {
    'ts': datetime.now().isoformat(),
    'type': 'quality_gate_fail',
    'team': os.environ.get('_MB_OBS_TEAM', 'unknown'),
    'file': os.environ.get('_MB_OBS_FILEPATH', ''),
    'error': os.environ.get('_MB_OBS_ERROR', ''),
    'tool': os.environ.get('_MB_OBS_TOOL', '')
}
with open(os.environ['_MB_OBS_FILE'], 'a') as f:
    f.write(json.dumps(obs, ensure_ascii=False) + '\n')
" 2>/dev/null
  fi
  rm -f "$QG_RESULT_FILE"
fi

# ── Continuous Learning: 记录工具使用观察（借鉴 ECC）──
LEARNING_DIR="$HOME/.claude/homunculus"
if [[ "$CLAUDE_LEGION_TEAM_ID" == L1-* ]]; then
  mkdir -p "$LEARNING_DIR"
  # 每 20 次工具调用记录一次摘要（避免 I/O 过重）
  if [[ $((_counter % 20)) -eq 0 && _counter -gt 0 ]]; then
    echo "$HOOK_INPUT" | python3 -c "
import sys, json, os
from datetime import datetime

try:
    d = json.load(sys.stdin)
except:
    sys.exit(0)

tool = d.get('tool_name', '')
inp = d.get('tool_input', {})
out = d.get('tool_output', '')

# 只记录有意义的工具（跳过 Read/Glob 等纯查询）
if tool in ('Edit', 'Write', 'Bash', 'TeamCreate'):
    obs = {
        'ts': datetime.now().isoformat(),
        'tool': tool,
        'file': inp.get('file_path', inp.get('command', ''))[:200],
        'team': os.environ.get('CLAUDE_LEGION_TEAM_ID', ''),
    }
    obs_file = os.path.expanduser('~/.claude/homunculus/observations.jsonl')
    with open(obs_file, 'a') as f:
        f.write(json.dumps(obs, ensure_ascii=False) + '\n')

    # 文件超过 5MB 自动归档
    try:
        if os.path.getsize(obs_file) > 5 * 1024 * 1024:
            archive_dir = os.path.expanduser('~/.claude/homunculus/archive')
            os.makedirs(archive_dir, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            os.rename(obs_file, f'{archive_dir}/observations-{ts}.jsonl')
    except:
        pass
" 2>/dev/null
  fi
fi

# ── Auto-Compact 强制：teammate 工具调用超 150 次 → 强制提醒 ──
AUTO_COMPACT_THRESHOLD=150
if [[ "$CLAUDE_LEGION_TEAM_ID" != L1-* && _counter -ge $AUTO_COMPACT_THRESHOLD ]]; then
  # 每 50 次提醒一次（150, 200, 250...）
  if [[ $(( (_counter - AUTO_COMPACT_THRESHOLD) % 50 )) -eq 0 ]]; then
    QUALITY_GATE_MSG="${QUALITY_GATE_MSG:+$QUALITY_GATE_MSG\n}⚡ Auto-Compact 警告（第 ${_counter} 次工具调用）：你的上下文即将耗尽。请立即执行以下操作：
1. 将当前进度写入 .planning/STATE.json（Schema: {completed, pending, failed_attempts, verification}）
2. SendMessage 给指挥官报告进度
3. 如果任务未完成，建议指挥官创建新 teammate 接棒"
  fi
fi

# ── 协议定期提醒（防止上下文压缩导致遗忘）──
PROTOCOL_INTERVAL=50
PENDING_PROTOCOL=""
if [[ $((_counter % PROTOCOL_INTERVAL)) -eq 0 && _counter -gt 0 ]]; then
  if [[ "$CLAUDE_LEGION_TEAM_ID" == L1-* ]]; then
    PENDING_PROTOCOL="【军团协议提醒 — 防止上下文压缩遗忘】
1. Spec 驱动：维护 .planning/（REQUIREMENTS/DECISIONS/STATE），决策 LOCKED 不可推翻
2. 上下文保鲜：对话变长时 /compact + 读 STATE.md 恢复
3. 结构化任务：给 teammate 用 XML 格式（files/action/verify/done/commit）
4. 原子提交：每个 task 完成就 git commit
5. 两阶段审计：规格符合性 + cargo check/tsc，必须贴完整输出
6. worktree 隔离 | 参谋外部调研 | 消息 ACK | 情报响应"
  else
    PENDING_PROTOCOL="【团队协议提醒】
1. 先读 .planning/ 下的 REQUIREMENTS.md 和 DECISIONS.md 了解需求和已锁定决策
2. 只修改你负责范围内的文件，按 task 的 verify 命令验证
3. 每完成一个 task 立即 git commit（原子提交）
4. 完成后通过 SendMessage 汇报指挥官，贴验证命令的完整输出
5. 遇到阻塞及时汇报，不要死等"
  fi
fi

# ── 输出 additionalContext：inbox + 协议提醒 + compact 提醒 + QG 警报 ──
_output=""
if [[ -n "${INBOX_MSG:-}" ]]; then
  _output+="$INBOX_MSG\n\n"
fi
if [[ -n "$PENDING_PROTOCOL" ]]; then
  _output+="$PENDING_PROTOCOL\n"
fi
if [[ -n "${COMPACT_MSG:-}" ]]; then
  _output+="\n$COMPACT_MSG\n"
fi
if [[ -n "${QUALITY_GATE_MSG:-}" ]]; then
  _output+="\n$QUALITY_GATE_MSG\n"
fi
if [[ -n "$_output" ]]; then
  escaped=$(echo -e "$_output" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null)
  echo "{\"additionalContext\": $escaped}"
fi

exit 0
