#!/bin/bash
# ============================================================================
# autonomous-loop.sh — 无人值守自治循环
# ============================================================================
# 基于 Anthropic Harness Engineering 研究：
#   Planner → Generator → Evaluator 循环，每个功能独立 context。
#
# 用法：
#   autonomous-loop.sh plan "项目需求描述"    # 规划：拆分为原子功能
#   autonomous-loop.sh run                    # 执行：逐个实现+验证
#   autonomous-loop.sh run --parallel 3       # 并行执行（最多 N 个）
#   autonomous-loop.sh status                 # 查看进度
#   autonomous-loop.sh resume                 # 从上次中断处继续
#
# 前置条件：
#   - .planning/features.json 存在（由 plan 命令生成）
#   - git 工作区干净（会自动 stash）
# ============================================================================

set -euo pipefail

PROJECT_DIR="$(pwd)"
PLANNING_DIR="$PROJECT_DIR/.planning"
FEATURES_FILE="$PLANNING_DIR/features.json"
PROGRESS_LOG="$PLANNING_DIR/progress.log"
LOOP_PID_FILE="$PLANNING_DIR/.loop.pid"
MAX_RETRIES=3
MAX_TURNS=30
PARALLEL=1

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1" | tee -a "$PROGRESS_LOG" 2>/dev/null; }
log_ok() { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✅ $1${NC}" | tee -a "$PROGRESS_LOG" 2>/dev/null; }
log_fail() { echo -e "${RED}[$(date '+%H:%M:%S')] ❌ $1${NC}" | tee -a "$PROGRESS_LOG" 2>/dev/null; }
log_warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠️  $1${NC}" | tee -a "$PROGRESS_LOG" 2>/dev/null; }

# ── 规划阶段：让 AI 把需求拆成原子功能 ──
cmd_plan() {
  local requirement="$1"
  mkdir -p "$PLANNING_DIR"

  log "🧠 规划阶段：拆分需求为原子功能..."

  claude -p "$(cat <<PLANEOF
你是项目规划师。将以下需求拆分为可独立实现的原子功能列表。

需求：$requirement

要求：
1. 每个功能必须可以在一个 context window 内完成（10-20 分钟）
2. 每个功能有明确的验收标准（怎么验证它做对了）
3. 功能之间标注依赖关系（哪些必须先做）
4. 输出严格 JSON 格式到 .planning/features.json

输出格式（直接写文件，不要解释）：
{
  "task": "需求的一句话描述",
  "created": "$(date '+%Y-%m-%d')",
  "total_features": N,
  "features": [
    {
      "id": "F001",
      "name": "功能名称",
      "description": "具体要做什么",
      "acceptance_criteria": ["验收标准1", "验收标准2"],
      "depends_on": [],
      "files": ["预期要改的文件"],
      "status": "pending",
      "retries": 0,
      "verified": false,
      "notes": ""
    }
  ]
}

注意：
- 按依赖顺序排列（被依赖的排前面）
- 每个功能改动不超过 3 个文件
- 功能粒度要小：一个函数、一个组件、一个接口
- 先读项目结构（ls, CLAUDE.md）再拆分
PLANEOF
)" --allowedTools "Read,Bash,Glob,Grep,Write" --max-turns 20 2>&1 | tail -5

  if [[ -f "$FEATURES_FILE" ]]; then
    local count
    count=$(python3 -c "import json; print(len(json.load(open('$FEATURES_FILE'))['features']))" 2>/dev/null || echo "0")
    log_ok "规划完成：$count 个原子功能已写入 $FEATURES_FILE"
  else
    log_fail "规划失败：features.json 未生成"
    exit 1
  fi
}

# ── 获取下一个待执行的功能 ──
get_next_feature() {
  python3 -c "
import json, sys

with open('$FEATURES_FILE') as f:
    data = json.load(f)

features = data.get('features', [])
done_ids = {f['id'] for f in features if f['status'] in ('done', 'skipped')}

for f in features:
    if f['status'] == 'pending':
        deps = f.get('depends_on', [])
        if all(d in done_ids for d in deps):
            print(json.dumps(f, ensure_ascii=False))
            sys.exit(0)

# 没有可执行的了
sys.exit(1)
" 2>/dev/null
}

# ── 更新功能状态 ──
update_feature() {
  local feature_id="$1"
  local new_status="$2"
  local notes="${3:-}"

  python3 -c "
import json, fcntl

path = '$FEATURES_FILE'
with open(path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    for feat in data['features']:
        if feat['id'] == '$feature_id':
            feat['status'] = '$new_status'
            if '$notes':
                feat['notes'] = '''$notes'''
            if '$new_status' == 'done':
                feat['verified'] = True
            if '$new_status' == 'failed':
                feat['retries'] = feat.get('retries', 0) + 1
            break
    f.seek(0)
    f.truncate()
    json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
" 2>/dev/null
}

# ── Generator：实现一个功能 ──
run_generator() {
  local feature_json="$1"
  local feature_id feature_name feature_desc feature_files acceptance

  feature_id=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  feature_name=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
  feature_desc=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('description',''))")
  feature_files=$(echo "$feature_json" | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('files',[])))")
  acceptance=$(echo "$feature_json" | python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('acceptance_criteria',[])))")

  log "🔨 Generator: 实现 $feature_id - $feature_name"
  update_feature "$feature_id" "in_progress"

  local gen_output
  gen_output=$(claude -p "$(cat <<GENEOF
你是代码实现者。实现以下功能：

功能 ID: $feature_id
功能名: $feature_name
描述: $feature_desc
预期文件: $feature_files
验收标准:
$acceptance

规则：
1. 先读 CLAUDE.md 了解编码规范
2. 如有 .planning/REQUIREMENTS.md 和 DECISIONS.md，先读
3. 只改必要的文件，不做额外重构
4. Rust 禁止 unwrap，用 ? 或 map_err
5. 前端 invoke() 参数 camelCase，后端 snake_case + serde rename
6. 完成后运行验证：Rust → cargo check, TS → tsc --noEmit, Python → python3 -c "import 模块"
7. 验证通过后 git add 改动的文件并 git commit -m "feat($feature_id): $feature_name"
8. 如果验证不通过，修复后再次验证，最多重试 3 次
GENEOF
)" --allowedTools "Read,Edit,Write,Bash,Glob,Grep" --max-turns "$MAX_TURNS" 2>&1)

  # 检查 git 是否有新 commit
  local latest_msg
  latest_msg=$(git log -1 --pretty=format:"%s" 2>/dev/null || echo "")
  if [[ "$latest_msg" == *"$feature_id"* ]]; then
    log_ok "Generator 完成: $feature_id ($feature_name) — 已 commit"
    return 0
  else
    log_warn "Generator 完成但未 commit: $feature_id"
    # 尝试自动 commit 未 staged 的改动
    if [[ -n $(git diff --name-only 2>/dev/null) ]]; then
      git add -A && git commit -m "feat($feature_id): $feature_name" 2>/dev/null || true
      return 0
    fi
    return 1
  fi
}

# ── Evaluator：验证一个功能 ──
run_evaluator() {
  local feature_json="$1"
  local feature_id feature_name acceptance

  feature_id=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  feature_name=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
  acceptance=$(echo "$feature_json" | python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('acceptance_criteria',[])))")

  log "🔍 Evaluator: 验证 $feature_id - $feature_name"

  local eval_output
  eval_output=$(claude -p "$(cat <<EVALEOF
你是独立评估器。你的目标是严格验证功能是否正确实现。不要宽容。

功能 ID: $feature_id
功能名: $feature_name
验收标准:
$acceptance

验证步骤：
1. 读 git diff HEAD~1 查看最近的改动
2. 对照验收标准逐条检查
3. 运行编译/类型检查：
   - 如有 .ts/.tsx 改动: cd gui && npx tsc --noEmit
   - 如有 .rs 改动: cd gui/src-tauri && cargo check
   - 如有 .py 改动: python3 -c "import 模块"
4. 如有前端改动且 http://localhost:1420 可访问: curl 验证页面可加载
5. 检查安全问题：unwrap、XSS、注入、未处理错误

输出最后一行必须是以下之一（不带任何其他字符）：
VERDICT:PASS
VERDICT:FAIL:具体原因
EVALEOF
)" --allowedTools "Read,Bash,Glob,Grep" --max-turns 15 2>&1)

  # 提取判定结果
  local verdict
  verdict=$(echo "$eval_output" | grep "^VERDICT:" | tail -1)

  if [[ "$verdict" == "VERDICT:PASS" ]]; then
    log_ok "Evaluator 通过: $feature_id"
    return 0
  else
    local reason="${verdict#VERDICT:FAIL:}"
    log_fail "Evaluator 拒绝: $feature_id — $reason"
    return 1
  fi
}

# ── 失败回滚 ──
revert_feature() {
  local feature_id="$1"
  log_warn "回滚 $feature_id: git revert HEAD"
  git revert HEAD --no-edit 2>/dev/null || git reset HEAD~1 --hard 2>/dev/null || true
}

# ── 主执行循环 ──
cmd_run() {
  if [[ ! -f "$FEATURES_FILE" ]]; then
    log_fail "features.json 不存在。先运行: autonomous-loop.sh plan \"需求描述\""
    exit 1
  fi

  # 记录 PID
  echo $$ > "$LOOP_PID_FILE"
  trap 'rm -f "$LOOP_PID_FILE"; log "循环已停止"' EXIT

  # 确保 git 工作区干净
  if [[ -n $(git status --porcelain 2>/dev/null) ]]; then
    log_warn "工作区不干净，自动 stash"
    git stash push -m "autonomous-loop-stash-$(date +%s)" 2>/dev/null || true
  fi

  local total done_count failed_count skipped_count
  total=$(python3 -c "import json; print(len(json.load(open('$FEATURES_FILE'))['features']))")
  log "🚀 自治循环启动: $total 个功能待实现"
  log "   最大重试: $MAX_RETRIES 次/功能"
  log "   最大轮次: $MAX_TURNS 次/Agent"
  log "   并行度: $PARALLEL"
  echo ""

  local loop_start
  loop_start=$(date +%s)
  local completed=0

  while true; do
    local feature_json
    feature_json=$(get_next_feature) || break

    local feature_id feature_name retries
    feature_id=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
    feature_name=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
    retries=$(echo "$feature_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('retries',0))")

    completed=$((completed + 1))
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "📦 功能 $completed/$total: $feature_id - $feature_name (重试: $retries/$MAX_RETRIES)"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Generator 实现
    if run_generator "$feature_json"; then
      # Evaluator 验证
      if run_evaluator "$feature_json"; then
        update_feature "$feature_id" "done"
        log_ok "✅ $feature_id 完成并验证通过"
      else
        # 验证失败
        if [[ "$retries" -lt "$MAX_RETRIES" ]]; then
          log_warn "$feature_id 验证失败，回滚后重试 ($((retries + 1))/$MAX_RETRIES)"
          revert_feature "$feature_id"
          update_feature "$feature_id" "pending" "评估失败，已回滚重试"
        else
          log_fail "$feature_id 已达最大重试次数，跳过"
          revert_feature "$feature_id"
          update_feature "$feature_id" "skipped" "超过最大重试次数"
        fi
      fi
    else
      # 实现失败
      if [[ "$retries" -lt "$MAX_RETRIES" ]]; then
        log_warn "$feature_id 实现失败，重试 ($((retries + 1))/$MAX_RETRIES)"
        update_feature "$feature_id" "pending" "实现失败，重试"
      else
        log_fail "$feature_id 实现多次失败，跳过"
        update_feature "$feature_id" "skipped" "实现失败，超过重试上限"
      fi
    fi

    echo ""
  done

  # 汇总
  local loop_end elapsed_s elapsed_m
  loop_end=$(date +%s)
  elapsed_s=$((loop_end - loop_start))
  elapsed_m=$((elapsed_s / 60))

  done_count=$(python3 -c "import json; print(len([f for f in json.load(open('$FEATURES_FILE'))['features'] if f['status']=='done']))")
  failed_count=$(python3 -c "import json; print(len([f for f in json.load(open('$FEATURES_FILE'))['features'] if f['status']=='failed']))")
  skipped_count=$(python3 -c "import json; print(len([f for f in json.load(open('$FEATURES_FILE'))['features'] if f['status']=='skipped']))")

  echo ""
  log "╔══════════════════════════════════════════╗"
  log "║         自治循环执行完成                   ║"
  log "╠══════════════════════════════════════════╣"
  log "║  总功能数:  $total"
  log "║  ✅ 完成:   $done_count"
  log "║  ❌ 失败:   $failed_count"
  log "║  ⏭️  跳过:   $skipped_count"
  log "║  ⏱️  耗时:   ${elapsed_m}分${elapsed_s}秒"
  log "╚══════════════════════════════════════════╝"

  # macOS 桌面通知
  if [[ "$(uname)" == "Darwin" ]]; then
    osascript -e "display notification \"完成 $done_count/$total 个功能，耗时 ${elapsed_m}分钟\" with title \"自治循环完成\"" 2>/dev/null &
  fi
}

# ── 查看进度 ──
cmd_status() {
  if [[ ! -f "$FEATURES_FILE" ]]; then
    echo "features.json 不存在"
    exit 1
  fi

  python3 -c "
import json

with open('$FEATURES_FILE') as f:
    data = json.load(f)

features = data['features']
total = len(features)
done = len([f for f in features if f['status'] == 'done'])
pending = len([f for f in features if f['status'] == 'pending'])
in_progress = len([f for f in features if f['status'] == 'in_progress'])
failed = len([f for f in features if f['status'] == 'failed'])
skipped = len([f for f in features if f['status'] == 'skipped'])

pct = int(done / total * 100) if total > 0 else 0
bar_filled = pct // 5
bar = '█' * bar_filled + '░' * (20 - bar_filled)

print(f'任务: {data.get(\"task\", \"未命名\")}')
print(f'进度: [{bar}] {pct}% ({done}/{total})')
print(f'  ✅ 完成: {done}  ⏳ 待执行: {pending}  🔄 进行中: {in_progress}  ❌ 失败: {failed}  ⏭️ 跳过: {skipped}')
print()

for f in features:
    status_icon = {'done':'✅','pending':'⏳','in_progress':'🔄','failed':'❌','skipped':'⏭️'}.get(f['status'],'❓')
    retries = f'\" (重试{f[\"retries\"]}次)' if f.get('retries',0) > 0 else ''
    notes = f' — {f[\"notes\"]}' if f.get('notes') else ''
    print(f'  {status_icon} {f[\"id\"]} {f[\"name\"]}{retries}{notes}')
"
}

# ── 从中断处继续 ──
cmd_resume() {
  log "📎 从上次中断处继续..."
  # 把所有 in_progress 重置为 pending
  python3 -c "
import json, fcntl
path = '$FEATURES_FILE'
with open(path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    for feat in data['features']:
        if feat['status'] == 'in_progress':
            feat['status'] = 'pending'
    f.seek(0); f.truncate()
    json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
" 2>/dev/null
  cmd_run
}

# ── 入口 ──
ACTION="${1:-status}"
shift || true

case "$ACTION" in
  plan)
    if [[ -z "${1:-}" ]]; then
      echo "用法: autonomous-loop.sh plan \"需求描述\""
      exit 1
    fi
    cmd_plan "$1"
    ;;
  run)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --parallel) PARALLEL="$2"; shift 2 ;;
        --max-retries) MAX_RETRIES="$2"; shift 2 ;;
        --max-turns) MAX_TURNS="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    cmd_run
    ;;
  resume)
    cmd_resume
    ;;
  status)
    cmd_status
    ;;
  stop)
    if [[ -f "$LOOP_PID_FILE" ]]; then
      kill "$(cat "$LOOP_PID_FILE")" 2>/dev/null && echo "已停止" || echo "进程不存在"
      rm -f "$LOOP_PID_FILE"
    else
      echo "没有运行中的循环"
    fi
    ;;
  *)
    echo "用法: autonomous-loop.sh {plan|run|resume|status|stop} [选项]"
    echo ""
    echo "命令:"
    echo "  plan \"需求\"     规划：将需求拆分为原子功能"
    echo "  run              执行：逐个实现+验证"
    echo "  resume           从中断处继续"
    echo "  status           查看进度"
    echo "  stop             停止运行中的循环"
    echo ""
    echo "选项:"
    echo "  --max-retries N  每个功能最大重试次数 (默认: 3)"
    echo "  --max-turns N    每个 Agent 最大工具调用数 (默认: 30)"
    ;;
esac
