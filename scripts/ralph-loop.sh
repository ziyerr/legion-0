#!/bin/bash
# ============================================================================
# ralph-loop.sh — Ralph Loop 迭代执行器
# ============================================================================
# 核心理念: "Start vague. Loop until perfect."
# 每次迭代是独立的新对话，以 spec 为真相来源，循环直到 AI 输出完成信号。
#
# 用法:
#   ralph-loop.sh [选项] "任务描述"
#   ralph-loop.sh [选项] -s spec-file.md
#
# 选项:
#   -s file          Spec 文件路径（优先于命令行 prompt）
#   -n max           最大迭代次数（默认 10）
#   -m model         模型（sonnet/opus/haiku，默认 sonnet）
#   -p mode          权限模式（默认 auto）
#   -t seconds       单次迭代超时（默认 600 = 10分钟）
#   -w               启用 worktree 隔离
#   -c               每次迭代后自动 git commit
#   -v               启用验证命令（迭代间运行测试）
#   --verify "cmd"   验证命令（如 "cargo check" "npm test"）
#   --label name     标签，用于日志和 commit message
#   --log-dir dir    日志目录（默认 /tmp/ralph-loop）
#   --append prompt  每次迭代追加的上下文（如修复提示）
#   --dry-run        只打印计划
#   -h               帮助
#
# 示例:
#   # 简单任务
#   ralph-loop.sh "实现视频同步功能，完成后输出 <done>COMPLETE</done>"
#
#   # 带 spec 文件 + 验证
#   ralph-loop.sh -s SPEC.md --verify "cargo check" -c --label "video-sync"
#
#   # 高精度模式
#   ralph-loop.sh -m opus -n 5 -s SPEC.md --verify "npm test"
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
SPEC_FILE=""
PROMPT=""
MAX_ITER=10
MODEL="sonnet"
PERM_MODE="auto"
TIMEOUT=600
USE_WORKTREE=false
AUTO_COMMIT=false
VERIFY_CMD=""
LABEL="ralph"
LOG_DIR="/tmp/ralph-loop"
APPEND_PROMPT=""
DRY_RUN=false
DONE_SIGNAL='<done>COMPLETE</done>'

# ── 帮助 ──
usage() {
  sed -n '2,/^# ====$/p' "$0" | sed 's/^# //' | sed 's/^#//'
  exit 0
}

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s) shift; SPEC_FILE="$1" ;;
    -n) shift; MAX_ITER="$1" ;;
    -m) shift; MODEL="$1" ;;
    -p) shift; PERM_MODE="$1" ;;
    -t) shift; TIMEOUT="$1" ;;
    -w) USE_WORKTREE=true ;;
    -c) AUTO_COMMIT=true ;;
    -v) ;; # -v is a flag, verify cmd comes via --verify
    --verify) shift; VERIFY_CMD="$1" ;;
    --label) shift; LABEL="$1" ;;
    --log-dir) shift; LOG_DIR="$1" ;;
    --append) shift; APPEND_PROMPT="$1" ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage ;;
    -*) echo -e "${RED}未知参数: $1${NC}"; usage ;;
    *) PROMPT="$1" ;;
  esac
  shift
done

# ── 校验 ──
if [[ -z "$SPEC_FILE" && -z "$PROMPT" ]]; then
  echo -e "${RED}请提供 spec 文件 (-s) 或任务描述${NC}"
  usage
fi

# ── 准备 ──
RUN_ID="${LABEL}-$(date +%Y%m%d-%H%M%S)"
RUN_LOG_DIR="${LOG_DIR}/${RUN_ID}"
mkdir -p "$RUN_LOG_DIR"

# 状态文件
STATUS_FILE="${RUN_LOG_DIR}/status"
echo "running" > "$STATUS_FILE"

# ── 构建 base prompt ──
build_prompt() {
  local iteration=$1
  local prev_output_file=$2
  local verify_result=$3

  local prompt_text=""

  # Spec 文件内容
  if [[ -n "$SPEC_FILE" && -f "$SPEC_FILE" ]]; then
    prompt_text+="$(cat "$SPEC_FILE")"
  elif [[ -n "$PROMPT" ]]; then
    prompt_text+="$PROMPT"
  fi

  # 迭代上下文
  prompt_text+="

---
## 迭代信息
- 当前迭代: ${iteration}/${MAX_ITER}
- 标签: ${LABEL}

## 执行规则
1. 仔细检查当前代码状态，理解已有的修改
2. 继续完成尚未完成的部分
3. 修复发现的任何问题
4. 所有任务完成后，输出完成信号: ${DONE_SIGNAL}
5. 如果无法完成，说明原因和阻塞点"

  # 上次迭代的验证结果
  if [[ -n "$verify_result" && "$verify_result" != "skip" ]]; then
    prompt_text+="

## 上次验证结果
\`\`\`
${verify_result}
\`\`\`
请根据以上错误进行修复。"
  fi

  # 追加提示
  if [[ -n "$APPEND_PROMPT" ]]; then
    prompt_text+="

## 额外指示
${APPEND_PROMPT}"
  fi

  echo "$prompt_text"
}

# ── 打印计划 ──
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║          Ralph Loop 迭代执行器                       ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}标签${NC}        : ${GREEN}${LABEL}${NC}"
echo -e "  ${BOLD}最大迭代${NC}    : ${GREEN}${MAX_ITER}${NC}"
echo -e "  ${BOLD}模型${NC}        : ${GREEN}${MODEL}${NC}"
echo -e "  ${BOLD}单次超时${NC}    : ${GREEN}${TIMEOUT}s${NC}"
echo -e "  ${BOLD}自动提交${NC}    : ${GREEN}${AUTO_COMMIT}${NC}"
echo -e "  ${BOLD}验证命令${NC}    : ${GREEN}${VERIFY_CMD:-无}${NC}"
echo -e "  ${BOLD}Spec 文件${NC}   : ${GREEN}${SPEC_FILE:-无(使用命令行prompt)}${NC}"
echo -e "  ${BOLD}日志目录${NC}    : ${GREEN}${RUN_LOG_DIR}${NC}"
echo ""

if $DRY_RUN; then
  echo -e "${YELLOW}[DRY RUN] 以上为执行计划${NC}"
  echo ""
  echo -e "${BOLD}首次 Prompt 预览:${NC}"
  echo "────────────────────────────────"
  build_prompt 1 "" "skip"
  echo "────────────────────────────────"
  exit 0
fi

# ── 主循环 ──
ITERATION=0
VERIFY_RESULT="skip"
COMPLETED=false

echo -e "${BOLD}${CYAN}开始 Ralph Loop...${NC}"
echo ""

while [[ $ITERATION -lt $MAX_ITER ]]; do
  ITERATION=$((ITERATION + 1))
  ITER_LOG="${RUN_LOG_DIR}/iter-${ITERATION}.log"
  ITER_START=$(date +%s)

  echo -e "${BOLD}${YELLOW}━━━ 迭代 ${ITERATION}/${MAX_ITER} ━━━${NC}  $(date '+%H:%M:%S')"

  # 构建 prompt
  FULL_PROMPT=$(build_prompt "$ITERATION" "${RUN_LOG_DIR}/iter-$((ITERATION-1)).log" "$VERIFY_RESULT")

  # 保存 prompt（调试用）
  echo "$FULL_PROMPT" > "${RUN_LOG_DIR}/iter-${ITERATION}.prompt"

  # 构建 claude 命令
  CLAUDE_CMD="claude -p --model ${MODEL} --permission-mode ${PERM_MODE}"
  if $USE_WORKTREE && [[ $ITERATION -eq 1 ]]; then
    CLAUDE_CMD+=" --worktree"
  fi

  # 执行
  set +e
  OUTPUT=$(timeout "$TIMEOUT" bash -c "$CLAUDE_CMD \"\$1\"" _ "$FULL_PROMPT" 2>&1)
  EXIT_CODE=$?
  set -e

  # 保存输出
  echo "$OUTPUT" > "$ITER_LOG"

  ITER_END=$(date +%s)
  ITER_DURATION=$((ITER_END - ITER_START))

  # 输出摘要（最后几行）
  SUMMARY=$(echo "$OUTPUT" | tail -5)
  echo -e "${GRAY}${SUMMARY}${NC}"
  echo -e "${GRAY}  耗时: ${ITER_DURATION}s  日志: ${ITER_LOG}${NC}"

  # 超时检查
  if [[ $EXIT_CODE -eq 124 ]]; then
    echo -e "${RED}  ⏰ 迭代超时 (${TIMEOUT}s)${NC}"
    VERIFY_RESULT="上次迭代超时，请精简你的方法，集中在最关键的修改上。"
    continue
  fi

  # 检查完成信号
  if echo "$OUTPUT" | grep -q "$DONE_SIGNAL"; then
    echo -e "${GREEN}${BOLD}  ✓ 检测到完成信号！${NC}"
    COMPLETED=true

    # 最终验证
    if [[ -n "$VERIFY_CMD" ]]; then
      echo -e "${CYAN}  运行最终验证: ${VERIFY_CMD}${NC}"
      set +e
      FINAL_VERIFY=$(eval "$VERIFY_CMD" 2>&1)
      FINAL_EXIT=$?
      set -e
      echo "$FINAL_VERIFY" > "${RUN_LOG_DIR}/final-verify.log"

      if [[ $FINAL_EXIT -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}  ✓ 验证通过！${NC}"
      else
        echo -e "${YELLOW}  ⚠ AI 声称完成但验证失败，继续迭代...${NC}"
        VERIFY_RESULT="$FINAL_VERIFY"
        COMPLETED=false
      fi
    fi

    if $COMPLETED; then
      # 自动提交最终结果
      if $AUTO_COMMIT; then
        echo -e "${CYAN}  提交最终结果...${NC}"
        git add -A 2>/dev/null && \
          git commit -m "ralph(${LABEL}): complete after ${ITERATION} iterations" 2>/dev/null || true
      fi
      break
    fi
  else
    echo -e "${YELLOW}  ○ 未完成，继续迭代...${NC}"

    # 中间验证（提供给下次迭代）
    if [[ -n "$VERIFY_CMD" ]]; then
      echo -e "${CYAN}  运行中间验证: ${VERIFY_CMD}${NC}"
      set +e
      VERIFY_RESULT=$(eval "$VERIFY_CMD" 2>&1)
      VERIFY_EXIT=$?
      set -e
      echo "$VERIFY_RESULT" > "${RUN_LOG_DIR}/verify-${ITERATION}.log"

      if [[ $VERIFY_EXIT -eq 0 ]]; then
        echo -e "${GREEN}  ✓ 验证通过（但未输出完成信号）${NC}"
        VERIFY_RESULT="验证命令通过，但你没有输出完成信号。如果所有任务已完成，请输出 ${DONE_SIGNAL}"
      else
        echo -e "${YELLOW}  ✗ 验证失败，错误将传递给下次迭代${NC}"
        # VERIFY_RESULT 已包含错误信息
      fi
    else
      VERIFY_RESULT="skip"
    fi

    # 中间提交
    if $AUTO_COMMIT; then
      git add -A 2>/dev/null && \
        git commit -m "ralph(${LABEL}): iteration ${ITERATION}" 2>/dev/null || true
    fi
  fi

  echo ""
done

# ── 结束 ──
echo ""
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if $COMPLETED; then
  echo "completed" > "$STATUS_FILE"
  echo -e "${GREEN}${BOLD}🎉 Ralph Loop 完成！${NC}"
  echo -e "  ${BOLD}迭代次数${NC}: ${ITERATION}"
else
  if [[ $ITERATION -ge $MAX_ITER ]]; then
    echo "max_iterations" > "$STATUS_FILE"
    echo -e "${YELLOW}${BOLD}⚠ 达到最大迭代次数 (${MAX_ITER})${NC}"
  else
    echo "stopped" > "$STATUS_FILE"
    echo -e "${RED}${BOLD}✗ 未完成${NC}"
  fi
fi

echo -e "  ${BOLD}日志目录${NC}: ${RUN_LOG_DIR}"
echo -e "  ${BOLD}各迭代日志${NC}: ls ${RUN_LOG_DIR}/iter-*.log"
echo ""
