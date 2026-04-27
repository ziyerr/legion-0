#!/bin/bash
# ============================================================================
# team-orchestrator.sh — 精英指挥官编排器（无妥协版）
# ============================================================================
#
# 设计原则:
#   - 质量是唯一退出条件，没有轮次上限
#   - 全程 opus，不降级
#   - 多层质量门禁: 编译 → 类型检查 → 代码审查 → 安全扫描
#   - 卡住自动升级策略（换角度、拆问题、合并修复）
#   - 每轮 git checkpoint，可随时回滚
#
# 用法:
#   team-orchestrator.sh -f mission.json [--dry-run]
#
# JSON 格式:
#   {
#     "team": "名称",
#     "model": "opus",                    ← 全员 opus
#     "permission_mode": "auto",
#     "quality_gates": [                  ← 全部通过才算完成
#       {"name": "Rust编译", "cmd": "cd gui/src-tauri && cargo check 2>&1"},
#       {"name": "TS类型",   "cmd": "cd gui && npx tsc --noEmit 2>&1"},
#       {"name": "代码审查", "type": "ai_review"}   ← AI 审查 diff
#     ],
#     "workers": [
#       {
#         "role": "Rust后端",
#         "prompt": "...",
#         "files": ["gui/src-tauri/**"],
#         "verify": "cargo check"
#       }
#     ]
#   }
#
# ============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; GRAY='\033[0;90m'; BOLD='\033[1m'
MAGENTA='\033[0;35m'; NC='\033[0m'

JSON_FILE=""; DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) shift; JSON_FILE="$1" ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,/^# ====$/p' "$0" | sed 's/^# //' | sed 's/^#//'; exit 0 ;;
    *) echo -e "${RED}未知: $1${NC}"; exit 1 ;;
  esac
  shift
done

[[ -z "$JSON_FILE" || ! -f "$JSON_FILE" ]] && { echo -e "${RED}-f mission.json 必需${NC}"; exit 1; }
command -v jq &>/dev/null || { echo -e "${RED}需要 jq: brew install jq${NC}"; exit 1; }

# ── 配置 ──
TEAM=$(jq -r '.team // "elite"' "$JSON_FILE")
MODEL=$(jq -r '.model // "opus"' "$JSON_FILE")
PERM=$(jq -r '.permission_mode // "auto"' "$JSON_FILE")
WORKER_N=$(jq '.workers | length' "$JSON_FILE")
GATE_N=$(jq '.quality_gates | length' "$JSON_FILE")
WORK_DIR=$(jq -r '.work_dir // empty' "$JSON_FILE")
[[ -z "$WORK_DIR" ]] && WORK_DIR="$(pwd)"

RUN_DIR="/tmp/claude-elite/${TEAM}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"/{workers,fixes,tests,commander,review}

BASE_COMMIT=$(cd "$WORK_DIR" && git rev-parse HEAD 2>/dev/null || echo "none")
echo "$BASE_COMMIT" > "$RUN_DIR/base_commit"

# ── 打印 ──
echo ""
echo -e "${BOLD}${MAGENTA}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${MAGENTA}║         ELITE ORCHESTRATOR — 无妥协，质量唯一退出条件          ║${NC}"
echo -e "${BOLD}${MAGENTA}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}团队${NC}      : ${GREEN}${TEAM}${NC}"
echo -e "  ${BOLD}模型${NC}      : ${GREEN}${MODEL}${NC} (全员，含指挥官)"
echo -e "  ${BOLD}Workers${NC}   : ${GREEN}${WORKER_N}${NC}"
echo -e "  ${BOLD}质量门禁${NC}  : ${GREEN}${GATE_N} 道${NC} (全部通过才退出)"
echo -e "  ${BOLD}轮次上限${NC}  : ${GREEN}无${NC} (直到完美)"
echo -e "  ${BOLD}工作目录${NC}  : ${GREEN}${WORK_DIR}${NC}"
echo ""

echo -e "  ${BOLD}质量门禁:${NC}"
for i in $(seq 0 $((GATE_N - 1))); do
  gname=$(jq -r ".quality_gates[$i].name" "$JSON_FILE")
  gtype=$(jq -r ".quality_gates[$i].type // \"cmd\"" "$JSON_FILE")
  gcmd=$(jq -r ".quality_gates[$i].cmd // \"(AI审查)\"" "$JSON_FILE")
  echo -e "    ${CYAN}[$((i+1))]${NC} ${BOLD}${gname}${NC} ${GRAY}(${gtype}) ${gcmd:0:60}${NC}"
done
echo ""

echo -e "  ${BOLD}Workers:${NC}"
for i in $(seq 0 $((WORKER_N - 1))); do
  role=$(jq -r ".workers[$i].role" "$JSON_FILE")
  files=$(jq -r ".workers[$i].files // [] | join(\", \")" "$JSON_FILE")
  echo -e "    ${YELLOW}[$((i+1))]${NC} ${BOLD}${role}${NC} ${GRAY}${files}${NC}"
done
echo ""

echo -e "  ${BOLD}流程:${NC}"
echo -e "    并行开发(Ralph) → 全部质量门禁 → AI指挥官分析"
echo -e "    → 定向修复 → 门禁 → 分析 → 修复 → ... → 全部通过"
echo -e "    卡住3轮同一错误 → 自动升级策略(合并修复/换角度/拆问题)"
echo ""

$DRY_RUN && { echo -e "${YELLOW}[DRY RUN]${NC}"; exit 0; }

# ── tmux ──
if [[ -z "${TMUX:-}" ]]; then
  tmux new-session -d -s "elite" -c "$WORK_DIR"
  SESSION="elite"
else
  SESSION=$(tmux display-message -p '#{session_name}')
fi
tmux new-window -t "$SESSION" -n "$TEAM" -c "$WORK_DIR"
WIN="$TEAM"

CMD_LOG="$RUN_DIR/commander/live.log"
touch "$CMD_LOG"
tmux send-keys -t "$SESSION:$WIN.0" "tail -f $CMD_LOG" Enter

log() {
  local ts=$(date '+%H:%M:%S')
  echo -e "[${ts}] $*" | tee -a "$CMD_LOG"
}

# ════════════════════════════════════════════
# 阶段 1: 全员并行开发
# ════════════════════════════════════════════
log "${BOLD}${MAGENTA}══ 阶段 1: 全员并行开发 ══${NC}"

PANE=1
for i in $(seq 0 $((WORKER_N - 1))); do
  role=$(jq -r ".workers[$i].role" "$JSON_FILE")
  prompt=$(jq -r ".workers[$i].prompt" "$JSON_FILE")
  verify=$(jq -r ".workers[$i].verify // empty" "$JSON_FILE")
  ralph=$(jq -r ".workers[$i].ralph // true" "$JSON_FILE")
  ralph_iter=$(jq -r ".workers[$i].ralph_max_iter // 10" "$JSON_FILE")

  status_f="$RUN_DIR/workers/${i}.status"
  log_f="$RUN_DIR/workers/${i}.log"
  script_f="$RUN_DIR/workers/run-${i}.sh"
  echo "running" > "$status_f"

  cat > "$script_f" << WEOF
#!/bin/bash
echo -e "\033[1;35m[ELITE] ${role}\033[0m"
echo "━━━━━━━━━━━━━━━━━━━━━━━━"
WEOF

  if [[ "$ralph" == "true" ]]; then
    r_args="-m $MODEL -p $PERM -n $ralph_iter --label '${role}' -c"
    [[ -n "$verify" ]] && r_args+=" --verify '$verify'"
    cat >> "$script_f" << WEOF
PROMPT=\$(cat <<'XEOF'
${prompt}

完成后输出: <done>COMPLETE</done>
XEOF
)
bash ~/.claude/scripts/ralph-loop.sh $r_args "\$PROMPT" 2>&1 | tee "$log_f"
WEOF
  else
    cat >> "$script_f" << WEOF
PROMPT=\$(cat <<'XEOF'
${prompt}
XEOF
)
claude -p --model $MODEL --permission-mode $PERM "\$PROMPT" 2>&1 | tee "$log_f"
WEOF
  fi

  cat >> "$script_f" << WEOF
[[ \$? -eq 0 ]] && echo "completed" > "$status_f" || echo "failed" > "$status_f"
WEOF
  chmod +x "$script_f"

  tmux split-window -t "$SESSION:$WIN" -c "$WORK_DIR"
  tmux send-keys -t "$SESSION:$WIN.$PANE" "bash $script_f" Enter
  ((PANE++))
  log "  启动: ${role} → 面板${PANE}"
done
tmux select-layout -t "$SESSION:$WIN" tiled 2>/dev/null || true

# 等待全部 workers
log "等待 ${WORKER_N} 个 workers..."
while true; do
  done_n=0
  for i in $(seq 0 $((WORKER_N - 1))); do
    s=$(cat "$RUN_DIR/workers/${i}.status" 2>/dev/null)
    [[ "$s" == "completed" || "$s" == "failed" ]] && ((done_n++))
  done
  [[ $done_n -ge $WORKER_N ]] && break
  sleep 5
done

c=0; f=0
for i in $(seq 0 $((WORKER_N - 1))); do
  s=$(cat "$RUN_DIR/workers/${i}.status" 2>/dev/null)
  [[ "$s" == "completed" ]] && ((c++)) || ((f++))
done
log "${GREEN}阶段1完成: ${c}成功 ${f}失败${NC}"

# 关闭所有 worker 面板（保留面板0指挥官）
log "回收 worker 面板..."
for p in $(seq $((PANE - 1)) -1 1); do
  tmux kill-pane -t "$SESSION:$WIN.$p" 2>/dev/null || true
done
PANE=1  # 重置面板计数，后续修复从面板1开始

cd "$WORK_DIR"
git add -A 2>/dev/null && git commit -m "elite(${TEAM}): 阶段1完成" 2>/dev/null || true

# ════════════════════════════════════════════
# 阶段 2: 质量门禁循环（无上限）
# ════════════════════════════════════════════
ROUND=0
PREV_ERRORS=""       # 上轮错误签名，用于卡住检测
STUCK_COUNT=0        # 连续相同错误计数
STRATEGY="normal"    # normal | combined | decompose | escalate

while true; do
  ((ROUND++))
  log ""
  log "${BOLD}${YELLOW}══ 联调轮次 ${ROUND} ══${NC}${GRAY} 策略: ${STRATEGY}${NC}"

  # ── 运行所有质量门禁 ──
  ALL_PASS=true
  GATE_RESULTS=""
  FAILED_GATES=""

  for g in $(seq 0 $((GATE_N - 1))); do
    gname=$(jq -r ".quality_gates[$g].name" "$JSON_FILE")
    gtype=$(jq -r ".quality_gates[$g].type // \"cmd\"" "$JSON_FILE")
    gcmd=$(jq -r ".quality_gates[$g].cmd // empty" "$JSON_FILE")

    if [[ "$gtype" == "ai_review" ]]; then
      # AI 代码审查门禁
      log "  门禁 ${gname}: AI 审查..."
      BASE=$(cat "$RUN_DIR/base_commit")
      DIFF=$(cd "$WORK_DIR" && git diff "$BASE" 2>/dev/null | head -1000 || echo "无diff")

      REVIEW_PROMPT=$(cat << 'REVEOF'
你是严格的高级代码审查员。审查以下 diff，检查：
1. 逻辑错误或 bug
2. 类型安全问题（unwrap、强制类型转换）
3. 前后端接口不一致（参数名、类型不匹配）
4. 资源泄漏或错误处理缺失
5. 安全风险（注入、硬编码密钥）

输出格式（严格 JSON）：
如果有问题：
```json
{"pass": false, "issues": [{"severity": "high|medium|low", "file": "路径", "line": "行号或范围", "issue": "问题描述", "fix": "修复建议"}]}
```
如果没问题：
```json
{"pass": true, "summary": "审查通过的简要说明"}
```

只报告真正的问题，不要吹毛求疵。
REVEOF
)
      REVIEW_PROMPT+="

## Diff
\`\`\`diff
${DIFF}
\`\`\`"

      set +e
      REVIEW_OUT=$(cd "$WORK_DIR" && claude -p --model "$MODEL" --permission-mode plan "$REVIEW_PROMPT" 2>&1)
      set -e
      echo "$REVIEW_OUT" > "$RUN_DIR/review/round-${ROUND}.txt"

      # 提取 JSON
      REVIEW_JSON=$(echo "$REVIEW_OUT" | sed -n '/^```json/,/^```/p' | sed '1d;$d')
      [[ -z "$REVIEW_JSON" ]] && REVIEW_JSON=$(echo "$REVIEW_OUT" | grep -o '{.*}' | head -1)

      REVIEW_PASS=$(echo "$REVIEW_JSON" | jq -r '.pass // false' 2>/dev/null)
      if [[ "$REVIEW_PASS" == "true" ]]; then
        log "  ${GREEN}✓ ${gname}${NC}"
        GATE_RESULTS+="=== ${gname}: PASS ===
"
      else
        ALL_PASS=false
        ISSUES=$(echo "$REVIEW_JSON" | jq -r '.issues[]? | "[\(.severity)] \(.file):\(.line) \(.issue)"' 2>/dev/null || echo "$REVIEW_OUT")
        log "  ${RED}✗ ${gname}${NC}"
        GATE_RESULTS+="=== ${gname}: FAIL ===
${ISSUES}
"
        FAILED_GATES+="${gname}; "
      fi

    elif [[ -n "$gcmd" ]]; then
      # 命令行门禁
      log "  门禁 ${gname}: ${GRAY}${gcmd:0:50}${NC}"
      set +e
      result=$(cd "$WORK_DIR" && eval "$gcmd" 2>&1)
      ec=$?
      set -e

      GATE_RESULTS+="=== ${gname} (exit: ${ec}) ===
${result}
"
      if [[ $ec -eq 0 ]]; then
        # 额外检查: 即使 exit 0，看看输出里有没有 error
        if echo "$result" | grep -qi "error\[" 2>/dev/null; then
          ALL_PASS=false
          log "  ${RED}✗ ${gname} (有 error 输出)${NC}"
          FAILED_GATES+="${gname}; "
        else
          log "  ${GREEN}✓ ${gname}${NC}"
        fi
      else
        ALL_PASS=false
        log "  ${RED}✗ ${gname}${NC}"
        FAILED_GATES+="${gname}; "
      fi
    fi
  done

  echo "$GATE_RESULTS" > "$RUN_DIR/tests/round-${ROUND}.txt"

  # ── 全部通过? ──
  if $ALL_PASS; then
    log ""
    log "${GREEN}${BOLD}████ 全部 ${GATE_N} 道质量门禁通过！████${NC}"
    cd "$WORK_DIR"
    git add -A 2>/dev/null && git commit -m "elite(${TEAM}): 全部门禁通过 (${ROUND}轮)" 2>/dev/null || true
    break
  fi

  log "  失败门禁: ${FAILED_GATES}"

  # ── 卡住检测 ──
  ERROR_SIG=$(echo "$GATE_RESULTS" | grep -i "error\|fail\|issue" | sort | md5 2>/dev/null || echo "$GATE_RESULTS" | wc -c)
  if [[ "$ERROR_SIG" == "$PREV_ERRORS" ]]; then
    ((STUCK_COUNT++))
    log "  ${YELLOW}⚠ 连续 ${STUCK_COUNT} 轮相同错误${NC}"

    if [[ $STUCK_COUNT -ge 5 ]]; then
      STRATEGY="escalate"
      log "  ${MAGENTA}策略升级 → escalate: 将所有错误合并为一个综合修复任务${NC}"
    elif [[ $STUCK_COUNT -ge 3 ]]; then
      STRATEGY="combined"
      log "  ${MAGENTA}策略升级 → combined: 合并多个 worker 的修复为一个 agent${NC}"
    fi
  else
    STUCK_COUNT=0
    STRATEGY="normal"
  fi
  PREV_ERRORS="$ERROR_SIG"

  # ── AI 指挥官分析 ──
  log "指挥官分析中..."

  BASE=$(cat "$RUN_DIR/base_commit")
  DIFF_STAT=$(cd "$WORK_DIR" && git diff "$BASE" --stat 2>/dev/null || echo "无")
  DIFF_CONTENT=$(cd "$WORK_DIR" && git diff "$BASE" 2>/dev/null | head -800 || echo "无")

  WORKER_INFO=""
  for i in $(seq 0 $((WORKER_N - 1))); do
    r=$(jq -r ".workers[$i].role" "$JSON_FILE")
    f=$(jq -r ".workers[$i].files // [] | join(\", \")" "$JSON_FILE")
    WORKER_INFO+="  Worker${i} [${r}] 文件范围: ${f}
"
  done

  # 根据策略调整指挥官 prompt
  STRATEGY_INSTRUCTION=""
  case "$STRATEGY" in
    combined)
      STRATEGY_INSTRUCTION="
## 特别指令: 合并修复策略
前几轮的单独修复未能解决问题。请将所有相关修复合并为**一个**综合修复任务，
让一个 agent 同时处理前后端的相关代码，而不是分别派发。
输出时 fixes 数组只包含一个元素，instruction 中涵盖所有需要修改的文件。"
      ;;
    escalate)
      STRATEGY_INSTRUCTION="
## 特别指令: 升级策略
已连续多轮卡在相同错误。请：
1. 重新审视问题的根本原因，可能之前的分析方向有误
2. 考虑是否需要回滚某些修改
3. 尝试完全不同的解决方案
4. 在 instruction 中详细说明新的思路"
      ;;
  esac

  COMMANDER_PROMPT="你是精英团队的指挥官。团队 workers 已完成并行开发，现在集成测试发现问题。

## 你的职责
1. 精确定位错误根因（哪个文件、哪行、什么问题）
2. 判断应该由哪个 worker 修复（根据其文件范围）
3. 生成**可直接执行**的修复指令（不是建议，是命令）
4. 如果错误涉及多个 worker 的接口不一致，指出双方各自需要改什么

${STRATEGY_INSTRUCTION}

## 输出格式（严格 JSON，不要其他文字）
\`\`\`json
{
  \"analysis\": \"根因分析（一句话）\",
  \"fixes\": [
    {
      \"target_worker\": 0,
      \"role\": \"对应角色名\",
      \"instruction\": \"精确的修复指令: 在哪个文件的什么位置做什么修改\",
      \"reason\": \"为什么是这个 worker 负责修复\"
    }
  ]
}
\`\`\`

## Worker 信息
${WORKER_INFO}

## 当前轮次: ${ROUND}, 策略: ${STRATEGY}
## 失败门禁: ${FAILED_GATES}

## 测试结果
${GATE_RESULTS}

## 变更摘要
${DIFF_STAT}

## 代码变更 (前800行)
\`\`\`diff
${DIFF_CONTENT}
\`\`\`"

  set +e
  CMD_OUT=$(cd "$WORK_DIR" && claude -p --model "$MODEL" --permission-mode plan "$COMMANDER_PROMPT" 2>&1)
  set -e
  echo "$CMD_OUT" > "$RUN_DIR/commander/round-${ROUND}.txt"

  # 提取 JSON
  ORDERS=$(echo "$CMD_OUT" | sed -n '/^```json/,/^```/p' | sed '1d;$d')
  [[ -z "$ORDERS" ]] && ORDERS=$(echo "$CMD_OUT" | python3 -c "
import sys,re,json
text=sys.stdin.read()
m=re.search(r'\{.*\}',text,re.DOTALL)
if m:
    try: json.loads(m.group()); print(m.group())
    except: pass
" 2>/dev/null || echo "")

  if [[ -z "$ORDERS" ]]; then
    log "${RED}指挥官未返回有效 JSON，重试...${NC}"
    continue
  fi
  echo "$ORDERS" > "$RUN_DIR/commander/orders-${ROUND}.json"

  ANALYSIS=$(echo "$ORDERS" | jq -r '.analysis // "无"' 2>/dev/null)
  FIX_N=$(echo "$ORDERS" | jq '.fixes | length' 2>/dev/null || echo "0")
  log "  分析: ${ANALYSIS}"
  log "  派发 ${FIX_N} 个修复任务"

  # ── 派发修复 agents ──
  FIX_PANES=()  # 记录本轮创建的面板，完成后关闭
  for fi in $(seq 0 $((FIX_N - 1))); do
    role=$(echo "$ORDERS" | jq -r ".fixes[$fi].role" 2>/dev/null)
    instruction=$(echo "$ORDERS" | jq -r ".fixes[$fi].instruction" 2>/dev/null)
    reason=$(echo "$ORDERS" | jq -r ".fixes[$fi].reason" 2>/dev/null)

    log "  ${YELLOW}→ 修复 [${role}]: ${reason}${NC}"

    fix_log="$RUN_DIR/fixes/r${ROUND}-f${fi}.log"
    fix_done="$RUN_DIR/fixes/r${ROUND}-f${fi}.done"
    fix_script="$RUN_DIR/fixes/r${ROUND}-f${fi}.sh"

    # 修复 agent 的完整 prompt
    TEST_TAIL=$(tail -50 "$RUN_DIR/tests/round-${ROUND}.txt" 2>/dev/null)

    cat > "$fix_script" << FEOF
#!/bin/bash
echo -e "\033[1;33m[修复] ${role} (轮次${ROUND})\033[0m"
echo -e "\033[0;90m${reason}\033[0m"
echo "━━━━━━━━━━━━━━━━━━"

PROMPT=\$(cat <<'FIXEOF'
你是精英修复工程师。执行以下精确修复：

## 修复指令
${instruction}

## 背景
${reason}

## 相关测试错误
${TEST_TAIL}

## 要求
1. 只修改指令中指定的文件
2. 精确修复，不做额外改动
3. 确保修改后相关编译/类型检查能通过
4. 完成后输出: <done>COMPLETE</done>
FIXEOF
)

claude -p --model $MODEL --permission-mode $PERM "\$PROMPT" 2>&1 | tee "$fix_log"
touch "$fix_done"
FEOF
    chmod +x "$fix_script"

    # 创建面板并记录
    tmux split-window -t "$SESSION:$WIN" -c "$WORK_DIR"
    # 获取新创建的面板 ID（最后一个活跃面板）
    NEW_PANE=$(tmux list-panes -t "$SESSION:$WIN" -F '#{pane_id}' | tail -1)
    FIX_PANES+=("$NEW_PANE")
    tmux select-layout -t "$SESSION:$WIN" tiled 2>/dev/null || true
    tmux send-keys -t "$NEW_PANE" "bash $fix_script" Enter
  done

  # 等待所有修复完成
  log "  等待 ${FIX_N} 个修复 agent..."
  while true; do
    all_fixed=true
    for fi in $(seq 0 $((FIX_N - 1))); do
      [[ ! -f "$RUN_DIR/fixes/r${ROUND}-f${fi}.done" ]] && all_fixed=false
    done
    $all_fixed && break
    sleep 5
  done

  # 关闭本轮修复面板
  log "  回收修复面板..."
  for pane_id in "${FIX_PANES[@]}"; do
    tmux kill-pane -t "$pane_id" 2>/dev/null || true
  done

  # commit 修复
  cd "$WORK_DIR"
  git add -A 2>/dev/null && git commit -m "elite(${TEAM}): 轮次${ROUND}修复 (${STRATEGY})" 2>/dev/null || true

  log "  修复完成，重新检查门禁..."
done

# ════════════════════════════════════════════
# 最终报告
# ════════════════════════════════════════════
echo "" | tee -a "$CMD_LOG"
echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════════════════╗${NC}" | tee -a "$CMD_LOG"
echo -e "${BOLD}${GREEN}║           ELITE ORCHESTRATOR — 任务完成                ║${NC}" | tee -a "$CMD_LOG"
echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════╝${NC}" | tee -a "$CMD_LOG"
echo -e "  联调轮次: ${ROUND}" | tee -a "$CMD_LOG"
echo -e "  质量门禁: ${GATE_N} 道全部通过" | tee -a "$CMD_LOG"
echo -e "  日志目录: ${RUN_DIR}" | tee -a "$CMD_LOG"
echo "" | tee -a "$CMD_LOG"

# 打印最终 diff 统计
echo -e "${BOLD}变更统计:${NC}" | tee -a "$CMD_LOG"
cd "$WORK_DIR" && git diff "$BASE" --stat 2>/dev/null | tee -a "$CMD_LOG"
