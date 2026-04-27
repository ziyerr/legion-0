#!/bin/bash
# ============================================================================
# pre-tool-use.sh — 审批门 + 团队强制执行 + 巡查自动放行
# ============================================================================
# 1. 审批门检查（gate.json blocked → 先尝试巡查复查自动放行）
# 2. 巡查通知书检查（未整改 → fail-closed 阻断）
# 3. L1/L2 团队强制：编辑源码无 teammate → 渐进式拦截
#    - 1-5 次：放行（可能是 S 级）
#    - 6-10 次：软警告
#    - 11+ 次：硬阻断 + 发通知书（commander 编组团队后自动放行）
#
# 巡查协议：通知书 → 整改回执 → 复查 → 自动放行
# commander 编组团队后调用: bash legion-patrol.sh remediate TEAM "已编组团队"
# 下次 hook 触发时自动复查，团队确认存在则放行。
#
# Fail-closed 语义：
#   - 未解除的巡查通知书（status != remediated）阻断写操作。
#   - 未审批的 gate 阻断（status == blocked 或文件无法解析）阻断写操作。
#   - 仅 status == approved 的 gate 视为已批准放行。
# ============================================================================

# 非 legion 模式，直接退出
[[ -z "${CLAUDE_LEGION_TEAM_ID:-}" ]] && exit 0

LEGION_DIR="${LEGION_DIR:-$HOME/.claude/legion}"
TEAM_DIR="$LEGION_DIR/team-$CLAUDE_LEGION_TEAM_ID"
GATE_FILE="$TEAM_DIR/gate.json"
PATROL_DIR="$LEGION_DIR/patrol"
PATROL_NOTICE="$PATROL_DIR/notice-$CLAUDE_LEGION_TEAM_ID.json"
PATROL_SCRIPT="$HOME/.claude/scripts/legion-patrol.sh"

# 识别 L1/L2 指挥官（混合编组同时支持两种前缀）
_IS_LEGION_COMMANDER=false
case "$CLAUDE_LEGION_TEAM_ID" in
  L1-*|L2-*) _IS_LEGION_COMMANDER=true ;;
esac

# ── 巡查复查辅助：仅在脚本可用时尝试自动放行 ──
_try_patrol_reinspect() {
  if [[ -f "$PATROL_SCRIPT" ]]; then
    local out
    out=$(source "$PATROL_SCRIPT" && patrol_reinspect "$CLAUDE_LEGION_TEAM_ID" 2>/dev/null) || out=""
    if [[ "$out" == PASS:* ]]; then
      printf '%s' "${out#PASS:}"
      return 0
    fi
  fi
  return 1
}

# ── 巡查通知书 fail-closed ──
# 任何未整改的通知书必须在放行前解除（reinspect PASS 或被人工 remediate+复查）。
if [[ "$_IS_LEGION_COMMANDER" == "true" && -f "$PATROL_NOTICE" ]]; then
  NOTICE_STATUS=$(python3 -c "
import json, sys
try:
    with open('$PATROL_NOTICE') as f:
        n = json.load(f)
    print(n.get('status', 'unknown'))
except Exception:
    # fail-closed：通知书无法解析 → 视为未解除
    print('unreadable')
" 2>/dev/null)
  NOTICE_STATUS="${NOTICE_STATUS:-unreadable}"

  if [[ "$NOTICE_STATUS" != "remediated" ]]; then
    if PATROL_PASS_REASON=$(_try_patrol_reinspect); then
      echo "{\"additionalContext\": \"✅ 巡查复查通过：${PATROL_PASS_REASON}。通知书已解除，继续执行。\"}"
    else
      echo "⛔ 巡查通知书未整改（${CLAUDE_LEGION_TEAM_ID}, status=${NOTICE_STATUS}）。" >&2
      echo "整改方式：1) TeamCreate 组建团队  2) bash ~/.claude/scripts/legion-patrol.sh remediate ${CLAUDE_LEGION_TEAM_ID} \"已编组团队含审查者\"  3) 重试操作即可自动放行" >&2
      exit 2
    fi
  else
    # 已收到整改回执但 reinspect 还未确认团队 → 必须确认后才放行
    if PATROL_PASS_REASON=$(_try_patrol_reinspect); then
      echo "{\"additionalContext\": \"✅ 巡查复查通过：${PATROL_PASS_REASON}。通知书已解除，继续执行。\"}"
    else
      echo "⛔ 巡查通知书 status=remediated 但复查未通过（${CLAUDE_LEGION_TEAM_ID}）。" >&2
      echo "请确认 TeamCreate 已成功编组（含 implement/review）后重试。" >&2
      exit 2
    fi
  fi
fi

# ── 审批门检查（含巡查自动放行） ──
if [[ -f "$GATE_FILE" ]]; then
  GATE_STATUS=$(python3 -c "
import json
try:
    with open('$GATE_FILE') as f:
        gate = json.load(f)
    status = gate.get('status', '')
    if status == 'blocked':
        print(f'BLOCKED:{gate.get(\"reason\", \"等待审批\")}')
    elif status == 'approved':
        print('OK')
    else:
        # fail-closed：未知状态视为阻断
        print(f'BLOCKED:gate status={status or \"unknown\"}')
except Exception:
    # fail-closed：gate 文件无法解析视为阻断
    print('BLOCKED:gate file unreadable')
" 2>/dev/null)
  GATE_STATUS="${GATE_STATUS:-BLOCKED:gate inspection failed}"

  if [[ "$GATE_STATUS" == BLOCKED:* ]]; then
    # ── 巡查复查：检查 commander 是否已整改（编组了团队） ──
    if PATROL_PASS_REASON=$(_try_patrol_reinspect); then
      echo "{\"additionalContext\": \"✅ 巡查复查通过：${PATROL_PASS_REASON}。审批门已自动解除，继续执行。\"}"
      # gate 已被 patrol_reinspect 清除，继续
    else
      REASON="${GATE_STATUS#BLOCKED:}"
      echo "⛔ 审批门已激活: $REASON" >&2
      if [[ -f "$PATROL_SCRIPT" ]]; then
        echo "整改方式：1) TeamCreate 组建团队  2) bash ~/.claude/scripts/legion-patrol.sh remediate $CLAUDE_LEGION_TEAM_ID \"已编组团队\"  3) 重试操作即可自动放行" >&2
      else
        echo "等待 L1 批准后继续。L1 使用 legion.sh gate $CLAUDE_LEGION_TEAM_ID approve 放行。" >&2
      fi
      exit 2
    fi
  fi
fi

# ── L1/L2 团队强制：只对指挥官的直接编辑生效 ──
# 注意：teammate（通过 Agent/TeamCreate 创建）继承 L1/L2 的 CLAUDE_LEGION_TEAM_ID，
# 但 CLAUDE_CODE_AGENT_NAME 不同。如果 agent name 不等于 team id，说明是 teammate 在编辑，放行。
if [[ "$_IS_LEGION_COMMANDER" == "true" ]]; then
  # teammate 编辑 → 直接放行（不计入指挥官的编辑计数）
  _AGENT_NAME="${CLAUDE_CODE_AGENT_NAME:-$CLAUDE_LEGION_TEAM_ID}"
  if [[ "$_AGENT_NAME" != "$CLAUDE_LEGION_TEAM_ID" && "$_AGENT_NAME" != "" ]]; then
    cat > /dev/null  # drain stdin
    exit 0
  fi

  PHASE_FILE="$TEAM_DIR/task_phase.json"
  mkdir -p "$TEAM_DIR"

  # 从 stdin 预读
  INPUT=$(cat)

  RESULT=$(echo "$INPUT" | python3 -c "
import sys, json, os, time

d = json.load(sys.stdin)
tool = d.get('tool_name', '')
inp = d.get('tool_input', {})
fp = inp.get('file_path', inp.get('command', ''))

# 只检查 Edit/Write
if tool not in ('Edit', 'Write'):
    print('SKIP')
    sys.exit(0)

# 排除 harness 文件（.claude/, .planning/, .git/, node_modules/）
harness_dirs = ['.claude/', '.planning/', '.git/', 'node_modules/', '/tmp/']
if any(h in str(fp) for h in harness_dirs):
    print('SKIP')
    sys.exit(0)

# 排除配置文件
config_exts = ['.json', '.toml', '.yaml', '.yml', '.lock', '.env']
if any(str(fp).endswith(ext) for ext in config_exts):
    print('SKIP')
    sys.exit(0)

# 是源码编辑 → 记录并判定
phase_file = '$PHASE_FILE'
try:
    with open(phase_file) as f:
        phase = json.load(f)
except:
    phase = {}

has_teammates = phase.get('has_teammates', False)
edit_count = phase.get('source_edit_count', 0)
edit_count += 1
phase['source_edit_count'] = edit_count
phase['last_edit'] = time.strftime('%Y-%m-%dT%H:%M:%SZ')

with open(phase_file, 'w') as f:
    json.dump(phase, f, ensure_ascii=False)

# 有 teammate → 放行
if has_teammates:
    print('SKIP')
    sys.exit(0)

# 渐进式强制：保留 legacy 警告→违规→门 的递进流程
if edit_count <= 5:
    print('SKIP')
elif edit_count <= 10:
    print(f'WARN:{edit_count}')
else:
    # 11+ 次 → 硬阻断，自动创建 gate
    gate_file = '$GATE_FILE'
    gate = {
        'status': 'blocked',
        'reason': f'自动拦截：指挥官已执行 {edit_count} 次源码编辑但未创建任何 teammate。M 级以上任务必须组建团队（TeamCreate）。请先创建 implement/review agent 再继续。',
        'blocked_by': 'hook-auto',
        'blocked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'edit_count': edit_count
    }
    with open(gate_file, 'w') as f:
        json.dump(gate, f, ensure_ascii=False)
    print(f'BLOCK:{edit_count}')
" 2>/dev/null)

  case "$RESULT" in
    WARN:*)
      COUNT="${RESULT#WARN:}"
      echo "{\"additionalContext\": \"⚠️ 团队强制提醒 ($COUNT/10)：你已编辑 $COUNT 个源文件但未创建任何 teammate。超过 10 次将被自动阻断。如果这是 S 级小修复请在 task_phase.json 中设置 has_teammates:true 跳过检查；否则请立即 TeamCreate 组建团队。\"}"
      ;;
    BLOCK:*)
      COUNT="${RESULT#BLOCK:}"
      # 发巡查通知书
      if [[ -f "$PATROL_SCRIPT" ]]; then
        source "$PATROL_SCRIPT"
        patrol_issue_notice "$CLAUDE_LEGION_TEAM_ID" "指挥官已执行${COUNT}次源码编辑无teammate" "$COUNT" 2>/dev/null
      fi
      echo "⛔ 巡查通知书：$COUNT 次源码编辑无 teammate。" >&2
      echo "整改方式：1) TeamCreate 组建团队  2) bash ~/.claude/scripts/legion-patrol.sh remediate $CLAUDE_LEGION_TEAM_ID \"已编组团队含审查者\"  3) 重试操作即可自动放行" >&2
      exit 2
      ;;
  esac
fi

exit 0
