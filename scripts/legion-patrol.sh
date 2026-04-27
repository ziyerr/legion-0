#!/bin/bash
# ============================================================================
# legion-patrol.sh — 巡查协议（通知→整改→复查→放行）+ Mixed-aware status
# ============================================================================
# 巡查不是"拦截者"，是"信任评估者"。
# commander 编组团队 = 已整改 → 巡查复查团队编制 → 自动放行。
#
# 兼容契约：notice / remediate / reinspect 行为保持不变（hook 直接 source）。
# 新增（mixed-aware）：status 同时聚合多源证据：
#   1) 未解决的巡查通知书           ($PATROL_DIR/notice-*.json)
#   2) Mixed 注册表 commander 列表  (mixed-registry.json)
#   3) Tmux 活性分类                live / missing / inaccessible
#                                   ("Operation not permitted" 不被折叠为 missing)
#   4) Release-gate 证据            (team-*/gate.json + 关联 mixed 事件)
#   5) 最近 patrol / gate 相关事件  (events.jsonl)
#
# 用法:
#   source ~/.claude/scripts/legion-patrol.sh
#
#   # 巡查发通知书（由 hook 调用）
#   patrol_issue_notice "L1-烽火军团" "源码编辑无团队" "12"
#
#   # commander 发送整改回执（编组团队后调用）
#   patrol_remediate "L1-烽火军团" "已编组团队 legion-upgrade，含审查者"
#
#   # 巡查复查（由 hook 在下次拦截时调用）
#   patrol_reinspect "L1-烽火军团"  → 返回 PASS/FAIL
#
#   # Mixed-aware 状态视图（release gate 输入）
#   bash legion-patrol.sh status
# ============================================================================

set -euo pipefail

LEGION_DIR="${LEGION_DIR:-$HOME/.claude/legion}"
PATROL_DIR="$LEGION_DIR/patrol"

_ensure_patrol_dir() {
  mkdir -p "$PATROL_DIR"
}

# ── 巡查发通知书 ──
# 参数: team_id reason edit_count
patrol_issue_notice() {
  _ensure_patrol_dir
  local team_id="$1"
  local reason="${2:-未知}"
  local edit_count="${3:-0}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  PATROL_NOTICE_FILE="$PATROL_DIR/notice-${team_id}.json" \
  PATROL_TEAM_ID="$team_id" \
  PATROL_REASON="$reason" \
  PATROL_EDIT_COUNT="$edit_count" \
  PATROL_TS="$ts" \
    python3 -c '
import json, os
notice = {
    "type": "patrol_notice",
    "team_id": os.environ["PATROL_TEAM_ID"],
    "reason": os.environ.get("PATROL_REASON", "未知"),
    "edit_count": int(os.environ.get("PATROL_EDIT_COUNT", "0") or 0),
    "issued_at": os.environ["PATROL_TS"],
    "status": "pending_remediation",
}
with open(os.environ["PATROL_NOTICE_FILE"], "w", encoding="utf-8") as fh:
    json.dump(notice, fh, ensure_ascii=False, indent=2)
' 2>/dev/null

  echo "[巡查] 通知书已发出 → $team_id: $reason" >&2
}

# ── commander 发送整改回执 ──
# 参数: team_id evidence
patrol_remediate() {
  _ensure_patrol_dir
  local team_id="$1"
  local evidence="${2:-已编组团队}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  local notice_file="$PATROL_DIR/notice-${team_id}.json"
  if [[ ! -f "$notice_file" ]]; then
    echo "[巡查] 无待处理通知书" >&2
    return 0
  fi

  # 更新通知书状态为"已整改待复查"
  PATROL_NOTICE_FILE="$notice_file" \
  PATROL_EVIDENCE="$evidence" \
  PATROL_TS="$ts" \
    python3 -c '
import json, os
path = os.environ["PATROL_NOTICE_FILE"]
with open(path, encoding="utf-8") as fh:
    notice = json.load(fh)
notice["status"] = "remediated"
notice["remediation_evidence"] = os.environ.get("PATROL_EVIDENCE", "已编组团队")
notice["remediated_at"] = os.environ["PATROL_TS"]
with open(path, "w", encoding="utf-8") as fh:
    json.dump(notice, fh, ensure_ascii=False, indent=2)
' 2>/dev/null

  echo "[巡查] 整改回执已提交 → $team_id: $evidence" >&2
}

# ── 巡查复查 ──
# 参数: team_id
# 返回: 0=PASS(放行), 1=FAIL(继续拦截)
patrol_reinspect() {
  local team_id="$1"
  local notice_file="$PATROL_DIR/notice-${team_id}.json"
  local team_dir="$LEGION_DIR/team-${team_id}"
  local phase_file="$team_dir/task_phase.json"

  # 无通知书 → 放行
  if [[ ! -f "$notice_file" ]]; then
    return 0
  fi

  local status
  status=$(PATROL_NOTICE_FILE="$notice_file" python3 -c '
import json, os
with open(os.environ["PATROL_NOTICE_FILE"], encoding="utf-8") as fh:
    notice = json.load(fh)
print(notice.get("status", "unknown"))
' 2>/dev/null)

  # 未整改 → 继续拦截
  if [[ "$status" != "remediated" ]]; then
    echo "FAIL:未收到整改回执"
    return 1
  fi

  # 已整改 → 验证团队编制
  local has_teammates="false"
  local pass_reason="团队已确认"

  # 检查0: mixed registry 中 target commander 的子树/任务 + tmux 活性
  local mixed_evidence=""
  if mixed_evidence=$(_mixed_target_teammate_evidence "$team_id"); then
    has_teammates="true"
    pass_reason="$mixed_evidence"
  fi

  # 检查1: task_phase.json 是否标记 has_teammates
  if [[ "$has_teammates" == "false" && -f "$phase_file" ]]; then
    has_teammates=$(PATROL_PHASE_FILE="$phase_file" python3 -c '
import json, os
with open(os.environ["PATROL_PHASE_FILE"], encoding="utf-8") as fh:
    phase = json.load(fh)
print("true" if phase.get("has_teammates") else "false")
' 2>/dev/null)
    [[ "$has_teammates" == "true" ]] && pass_reason="legacy task_phase has_teammates=true"
  fi

  if [[ "$has_teammates" == "true" ]]; then
    # 团队确认存在 → 放行 + 清除通知书 + 清除 gate
    echo "PASS:$pass_reason"

    # 清除通知书
    rm -f "$notice_file"

    # 清除 gate（如果有）
    local gate_file="$team_dir/gate.json"
    if [[ -f "$gate_file" ]]; then
      rm -f "$gate_file"
    fi

    # 重置编辑计数
    if [[ -f "$phase_file" ]]; then
      PATROL_PHASE_FILE="$phase_file" python3 -c '
import json, os
path = os.environ["PATROL_PHASE_FILE"]
with open(path, encoding="utf-8") as fh:
    phase = json.load(fh)
phase["source_edit_count"] = 0
with open(path, "w", encoding="utf-8") as fh:
    json.dump(phase, fh, ensure_ascii=False)
' 2>/dev/null
    fi

    return 0
  else
    echo "FAIL:未检测到活跃团队成员"
    return 1
  fi
}

# ── Mixed 运行目录解析 ──
# 优先级：
#   1) 显式 MIXED_DIR 环境变量
#   2) PROJECT_DIR (或 PWD) 的 md5 推断 → $LEGION_DIR/<hash>/mixed
#   3) 在 $LEGION_DIR 下找最新的 mixed-registry.json，回退到其父目录
# stdout: 找到的 mixed 目录路径；返回非 0 表示未找到
_resolve_mixed_dir() {
  if [[ -n "${MIXED_DIR:-}" && -f "$MIXED_DIR/mixed-registry.json" ]]; then
    echo "$MIXED_DIR"
    return 0
  fi

  local proj="${PROJECT_DIR:-$(pwd)}"
  local hash=""
  if command -v md5 >/dev/null 2>&1; then
    hash=$(printf "%s" "$proj" | md5 2>/dev/null | cut -c1-8)
  elif command -v md5sum >/dev/null 2>&1; then
    hash=$(printf "%s" "$proj" | md5sum 2>/dev/null | cut -c1-8)
  fi
  if [[ -n "$hash" && -f "$LEGION_DIR/$hash/mixed/mixed-registry.json" ]]; then
    echo "$LEGION_DIR/$hash/mixed"
    return 0
  fi

  # 回退：扫描 LEGION_DIR 寻找最近的 mixed-registry.json
  local found=""
  if [[ -d "$LEGION_DIR" ]]; then
    found=$(find "$LEGION_DIR" -maxdepth 4 -name "mixed-registry.json" -print0 2>/dev/null \
      | xargs -0 ls -t 2>/dev/null | head -1)
  fi
  if [[ -n "$found" ]]; then
    dirname "$found"
    return 0
  fi

  return 1
}

# ── 分类 tmux 会话活性 ──
# 输出: live | missing | inaccessible
# 关键：不把 "Operation not permitted" / 权限错误 / 套接字失败折叠成 missing，
# 否则 status 会把活着但当前进程访问不到的指挥官错误地标记为失联。
_classify_tmux_session() {
  local session="$1"
  if [[ -z "$session" ]]; then
    echo "missing"
    return 0
  fi
  if ! command -v tmux >/dev/null 2>&1; then
    echo "inaccessible"
    return 0
  fi

  local err rc=0
  err=$(tmux has-session -t "$session" 2>&1 >/dev/null)
  rc=$?

  if [[ $rc -eq 0 ]]; then
    echo "live"
    return 0
  fi

  local lower
  lower=$(printf "%s" "$err" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    *"operation not permitted"*|*"permission denied"*|*"no such file or directory"*"/tmp/tmux"*|*"failed to connect"*|*"connection refused"*|*"socket"*)
      echo "inaccessible"
      ;;
    *)
      echo "missing"
      ;;
  esac
}

# ── Mixed 子树团队证据 ──
# 验证范围限定在 target commander 的 mixed subtree：
#   - child L2 commanders: parent 链路归属于 target，且 tmux live/inaccessible
#   - worker tasks: commander/origin_commander 归属于 target 子树，且已启动/运行
# 不再扫描 ~/.claude/teams 全局配置，避免 unrelated team config 误放行。
_mixed_target_teammate_evidence() {
  local target="$1"
  local mixed_dir registry rows project_session=""
  if ! mixed_dir=$(_resolve_mixed_dir); then
    return 1
  fi
  registry="$mixed_dir/mixed-registry.json"
  [[ -f "$registry" ]] || return 1

  rows=$(PATROL_TARGET="$target" PATROL_REGISTRY="$registry" python3 -c '
import json, os
target = os.environ["PATROL_TARGET"]
with open(os.environ["PATROL_REGISTRY"], encoding="utf-8") as fh:
    data = json.load(fh)
def field(value):
    value = str(value)
    return value if value else "-"
project_session = str(data.get("project", {}).get("session", ""))
print("\t".join(["PROJECT", field(project_session), "-", "-", "-"]))
commanders = data.get("commanders", []) or []
seen = {target}
changed = True
while changed:
    changed = False
    for commander in commanders:
        cid = str(commander.get("id", ""))
        parent = str(commander.get("parent", ""))
        if cid and cid not in seen and parent in seen:
            seen.add(cid)
            changed = True
for commander in commanders:
    cid = str(commander.get("id", ""))
    if cid in seen and cid != target:
        print("\t".join([
            "COMMANDER",
            cid,
            field(commander.get("status", "")),
            field(commander.get("session", "")),
            "-",
        ]))
for task in data.get("tasks", []) or []:
    commander = str(task.get("commander", ""))
    origin = str(task.get("origin_commander", ""))
    if commander in seen or origin in seen:
        print("\t".join([
            "TASK",
            str(task.get("id", "")),
            field(task.get("status", "")),
            "-",
            field(task.get("window", "")),
        ]))
' 2>/dev/null) || return 1
  [[ -n "$rows" ]] || return 1

  local kind id status session window liveness
  local accepted=0 active=0 live=0 inaccessible=0 missing=0
  local samples=()
  while IFS=$'\t' read -r kind id status session window; do
    [[ -n "$kind" ]] || continue
    case "$kind" in
      PROJECT)
        project_session="$id"
        [[ "$project_session" == "-" ]] && project_session=""
        continue
        ;;
      COMMANDER)
        [[ "$session" == "-" ]] && session=""
        case "$status" in
          failed|blocked|cancelled|disbanded|completed) continue ;;
        esac
        liveness=$(_classify_tmux_session "$session")
        case "$liveness" in
          live)
            accepted=$((accepted+1)); active=$((active+1)); live=$((live+1)); samples+=("$id:$status:tmux=live")
            ;;
          inaccessible)
            accepted=$((accepted+1)); active=$((active+1)); inaccessible=$((inaccessible+1)); samples+=("$id:$status:tmux=inaccessible")
            ;;
          *)
            missing=$((missing+1))
            ;;
        esac
        ;;
      TASK)
        [[ "$window" == "-" ]] && window=""
        case "$status" in
          failed|blocked|cancelled|disbanded|completed) continue ;;
        esac
        [[ -n "$window" ]] || continue
        liveness=$(_classify_tmux_session "$project_session")
        case "$liveness" in
          live)
            accepted=$((accepted+1)); active=$((active+1)); live=$((live+1)); samples+=("$id:$status:tmux=live")
            ;;
          inaccessible)
            accepted=$((accepted+1)); active=$((active+1)); inaccessible=$((inaccessible+1)); samples+=("$id:$status:tmux=inaccessible")
            ;;
          *)
            missing=$((missing+1))
            ;;
        esac
        ;;
    esac
  done < <(printf '%s\n' "$rows")

  [[ "$accepted" -gt 0 ]] || return 1
  local sample_text="${samples[*]}"
  printf 'mixed subtree confirmed: active=%d tmux_live=%d tmux_inaccessible=%d stale_missing=%d evidence=%s' \
    "$active" "$live" "$inaccessible" "$missing" "$sample_text"
}

# ── Section 1: 未解决的巡查通知书 ──
_print_patrol_notices() {
  echo "=== 巡查通知书（未解决） ==="
  if [[ ! -d "$PATROL_DIR" ]]; then
    echo "  (无)"
    return 0
  fi
  local found=0
  local f
  shopt -s nullglob
  for f in "$PATROL_DIR"/notice-*.json; do
    [[ -f "$f" ]] || continue
    found=1
    PATROL_NOTICE_FILE="$f" python3 -c '
import json, os
try:
    with open(os.environ["PATROL_NOTICE_FILE"], encoding="utf-8") as fh:
        n = json.load(fh)
except Exception as exc:
    print(f"  (notice 读取失败: {exc})")
    raise SystemExit(0)
team = n.get("team_id", "?")
status = n.get("status", "?")
reason = n.get("reason", "?")
count = n.get("edit_count", 0)
issued = n.get("issued_at", "?")
remed = n.get("remediated_at", "")
extra = f" remediated_at={remed}" if remed else ""
print(f"  {team}: status={status} count={count} issued={issued}{extra}")
print(f"      reason: {reason}")
' 2>/dev/null
  done
  shopt -u nullglob
  [[ "$found" -eq 0 ]] && echo "  (无)"
}

# ── Section 2: Mixed 注册表 commander + tmux 活性 ──
_print_mixed_commanders() {
  echo "=== Mixed 注册表（commander + tmux 活性） ==="
  local mixed_dir
  if ! mixed_dir=$(_resolve_mixed_dir); then
    echo "  (未找到 mixed 运行目录；设置 MIXED_DIR 或 PROJECT_DIR 后重试)"
    return 0
  fi
  echo "  source: $mixed_dir/mixed-registry.json"

  local registry="$mixed_dir/mixed-registry.json"
  if [[ ! -f "$registry" ]]; then
    echo "  (mixed-registry.json 不存在)"
    return 0
  fi

  local commanders
  commanders=$(PATROL_REGISTRY="$registry" python3 -c '
import json, os
try:
    with open(os.environ["PATROL_REGISTRY"], encoding="utf-8") as fh:
        d = json.load(fh)
except Exception:
    raise SystemExit(0)
for c in d.get("commanders", []) or []:
    def field(value):
        value = str(value)
        return value if value else "-"
    cid = str(c.get("id", "?"))
    provider = str(c.get("provider", "?"))
    status = str(c.get("status", "?"))
    session = field(c.get("session", ""))
    failure = field(str(c.get("failure", "")).replace("\t", " ")[:120])
    print("\t".join([cid, provider, status, session, failure]))
' 2>/dev/null)

  if [[ -z "$commanders" ]]; then
    echo "  (registry 中无 commander)"
    return 0
  fi

  local total=0 live=0 missing=0 inaccessible=0
  local cid provider status session failure liveness
  while IFS=$'\t' read -r cid provider status session failure; do
    [[ -z "$cid" ]] && continue
    [[ "$session" == "-" ]] && session=""
    [[ "$failure" == "-" ]] && failure=""
    total=$((total+1))
    liveness=$(_classify_tmux_session "$session")
    case "$liveness" in
      live) live=$((live+1));;
      missing) missing=$((missing+1));;
      inaccessible) inaccessible=$((inaccessible+1));;
    esac
    if [[ -n "$failure" ]]; then
      printf "  %s [%s] status=%s tmux=%s — failure=%s\n" \
        "$cid" "$provider" "$status" "$liveness" "$failure"
    else
      printf "  %s [%s] status=%s tmux=%s\n" \
        "$cid" "$provider" "$status" "$liveness"
    fi
  done < <(printf '%s\n' "$commanders")
  printf "  -- 共 %d；tmux live=%d missing=%d inaccessible=%d\n" \
    "$total" "$live" "$missing" "$inaccessible"
}

# ── Mixed events 过滤打印（无 heredoc / 无临时文件） ──
_print_filtered_events() {
  local events="$1"
  local limit="$2"
  local prefix="$3"
  local empty_text="$4"
  PATROL_EVENTS_FILE="$events" \
  PATROL_EVENT_LIMIT="$limit" \
  PATROL_EVENT_PREFIX="$prefix" \
  PATROL_EVENT_EMPTY="$empty_text" \
    python3 -c '
import json, os
keys = (
    "patrol", "gate", "blocked", "violation", "warning",
    "approve", "deny", "remediat", "reinspect",
    "task_failed", "task_blocked", "commander_failed",
)
matched = []
try:
    with open(os.environ["PATROL_EVENTS_FILE"], encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            name = str(event.get("event", "")).lower()
            try:
                payload = json.dumps(event.get("payload", {}), ensure_ascii=False).lower()
            except Exception:
                payload = ""
            if any(key in name for key in keys) or any(key in payload for key in keys):
                matched.append(event)
except Exception:
    pass
limit = int(os.environ.get("PATROL_EVENT_LIMIT", "20") or 20)
prefix = os.environ.get("PATROL_EVENT_PREFIX", "")
empty = os.environ.get("PATROL_EVENT_EMPTY", "(无相关事件)")
matched = matched[-limit:]
if not matched:
    print(f"{prefix}{empty}")
else:
    for event in matched:
        ts = event.get("ts", "")
        name = event.get("event", "?")
        task_id = event.get("task_id", "")
        head = f"{prefix}{ts} {name}"
        if task_id:
            head += f" task={task_id}"
        payload = event.get("payload", {}) or {}
        if isinstance(payload, dict) and payload:
            kv = ", ".join(f"{key}={payload[key]}" for key in list(payload)[:4])
            head += f" — {kv}"
        print(head)
' 2>/dev/null
}

# ── Section 3: Release-gate 证据 ──
# 同时枚举传统 team-*/gate.json 与 mixed events 中的 gate/blocked 关联事件。
_print_release_gate_evidence() {
  echo "=== Release-Gate 证据（gate.json + mixed 关联事件） ==="
  local found=0
  local gate_file team_dir team_id
  shopt -s nullglob
  for gate_file in "$LEGION_DIR"/team-*/gate.json; do
    [[ -f "$gate_file" ]] || continue
    team_dir=$(dirname "$gate_file")
    team_id=$(basename "$team_dir" | sed 's/^team-//')
    found=1
    PATROL_GATE_FILE="$gate_file" PATROL_TEAM_ID="$team_id" python3 -c '
import json, os
team = os.environ["PATROL_TEAM_ID"]
try:
    with open(os.environ["PATROL_GATE_FILE"], encoding="utf-8") as fh:
        gate = json.load(fh)
except Exception as exc:
    print(f"  (gate 读取失败 {team}: {exc})")
    raise SystemExit(0)
status = gate.get("status", "?")
icon = "⛔" if status == "blocked" else ("✅" if status == "approved" else "?")
reason = gate.get("reason", "")
print(f"  {icon} team-{team}: gate={status}" + (f" reason={reason}" if reason else ""))
for key, value in gate.items():
    if key in ("status", "reason"):
        continue
    print(f"      {key}: {value}")
' 2>/dev/null
  done
  shopt -u nullglob
  [[ "$found" -eq 0 ]] && echo "  (无 team-*/gate.json)"

  # mixed events 中的 gate/blocked 关联条目（最多 10 条）
  local mixed_dir events
  if mixed_dir=$(_resolve_mixed_dir); then
    events="$mixed_dir/events.jsonl"
    if [[ -f "$events" ]]; then
      echo "  -- mixed events 关联条目（最近 10 条）："
      _print_filtered_events "$events" 10 "      " "(无)"
    fi
  fi
}

# ── Section 4: 最近 patrol / gate / blocked 相关事件 ──
_print_mixed_events() {
  echo "=== 最近 Mixed 事件（patrol / gate / blocked / failed，最多 20 条） ==="
  local mixed_dir
  if ! mixed_dir=$(_resolve_mixed_dir); then
    echo "  (未找到 mixed 运行目录)"
    return 0
  fi
  local events="$mixed_dir/events.jsonl"
  if [[ ! -f "$events" ]]; then
    echo "  (events.jsonl 不存在)"
    return 0
  fi

  _print_filtered_events "$events" 20 "  " "(无相关事件)"
}

# ── Mixed-aware 状态视图（release gate 输入） ──
patrol_mixed_status() {
  _print_patrol_notices
  echo
  _print_mixed_commanders
  echo
  _print_release_gate_evidence
  echo
  _print_mixed_events
}

# ── CLI 入口 ──
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-help}" in
    notice)    patrol_issue_notice "${2:-}" "${3:-}" "${4:-0}" ;;
    remediate) patrol_remediate "${2:-}" "${3:-}" ;;
    reinspect) patrol_reinspect "${2:-}" ;;
    status|mixed-status)
      patrol_mixed_status
      ;;
    help|*)
      printf '%s\n' \
        "用法: legion-patrol.sh {notice|remediate|reinspect|status}" \
        "  notice    TEAM REASON [COUNT]  — 发通知书" \
        "  remediate TEAM EVIDENCE        — 提交整改回执" \
        "  reinspect TEAM                 — 复查（返回 PASS/FAIL）" \
        "  status                         — Mixed-aware 状态视图：" \
        "                                    通知书 + commander/tmux 活性 + release-gate + 关联事件" \
        "环境变量:" \
        "  LEGION_DIR    覆盖 ~/.claude/legion" \
        "  MIXED_DIR     直接指定 mixed 运行目录（含 mixed-registry.json）" \
        "  PROJECT_DIR   覆盖项目目录用于推断 mixed 运行目录"
      ;;
  esac
fi
