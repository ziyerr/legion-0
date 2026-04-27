#!/bin/bash
# ============================================================================
# stack-verify.sh — 技术栈感知的验证注册表
# ============================================================================
# 自动检测项目技术栈，对应运行验证命令。
# 用法：
#   stack-verify.sh check <file_path>     # 检查单个文件（Quality Gate 用）
#   stack-verify.sh full [project_dir]    # 全栈验证（审计用）
#   stack-verify.sh detect [project_dir]  # 只检测技术栈，不运行验证
# ============================================================================

set -euo pipefail

# PROJECT_DIR 只在 full/detect 模式下用 $2，check 模式用 pwd
if [[ "${1:-}" == "check" ]]; then
  PROJECT_DIR="$(pwd)"
else
  PROJECT_DIR="${2:-$(pwd)}"
fi
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

# ── 验证注册表：文件扩展名 → 验证命令 ──
# 返回格式: "命令|工作目录|描述"
get_verifier() {
  local file="$1"
  local ext="${file##*.}"
  local dir
  dir=$(cd "$(dirname "$file")" 2>/dev/null && pwd || echo "")

  # 先向上查找项目根目录和框架类型
  local _proj_root=""
  local _framework=""
  local _d="$dir"
  for _i in $(seq 1 15); do
    if [[ -f "$_d/next.config.js" || -f "$_d/next.config.mjs" || -f "$_d/next.config.ts" ]]; then
      _proj_root="$_d"; _framework="nextjs"; break
    elif [[ -f "$_d/nuxt.config.ts" || -f "$_d/nuxt.config.js" ]]; then
      _proj_root="$_d"; _framework="nuxt"; break
    elif [[ -f "$_d/package.json" && -z "$_proj_root" ]]; then
      _proj_root="$_d"
    fi
    _d="$(dirname "$_d")"
    [[ "$_d" == "/" ]] && break
  done

  case "$ext" in
    ts|tsx|js|jsx)
      # Next.js 项目
      if [[ "$_framework" == "nextjs" ]]; then
        echo "npx next lint --dir . && npx tsc --noEmit|$_proj_root|Next.js lint + 类型检查"
        return
      fi
      # 判断属于哪个 TS 项目（当前项目特定）
      if [[ "$file" == *"jimeng-api-service"* ]]; then
        echo "npm run build|${PROJECT_DIR}/jimeng-api-service|TypeScript 构建 (jimeng-api)"
      elif [[ "$file" == *"gui/src"* || "$file" == *"gui/src-tauri"* ]]; then
        echo "npx tsc --noEmit|${PROJECT_DIR}/gui|TypeScript 类型检查 (gui)"
      elif [[ -n "$_proj_root" ]]; then
        echo "npx tsc --noEmit|$_proj_root|TypeScript 类型检查"
      fi
      ;;
    rs)
      echo "cargo check|${PROJECT_DIR}/gui/src-tauri|Rust 编译检查"
      ;;
    py)
      # Python: py_compile 语法检查 + ruff lint
      echo "python3 -m py_compile '$file' && ruff check '$file' --select E,F,W|${PROJECT_DIR}|Python 语法+lint ($file)"
      ;;
    css|scss|less)
      # CSS 没有强类型检查，跳过
      echo ""
      ;;
    json)
      echo "python3 -c \"import json; json.load(open('$file'))\"|${PROJECT_DIR}|JSON 语法验证"
      ;;
    *)
      echo ""
      ;;
  esac
}

# ── 检查单个文件 ──
cmd_check() {
  local file="$1"
  # 转为绝对路径
  if [[ "$file" != /* ]]; then
    file="$(pwd)/$file"
  fi
  if [[ ! -f "$file" ]]; then
    echo "文件不存在: $file"
    exit 1
  fi

  local ext="${file##*.}"
  local result=""
  local desc=""

  # 检测文件所在项目的框架
  local _dir _proj_root="" _framework=""
  _dir=$(dirname "$file")
  for _i in $(seq 1 15); do
    if [[ -f "$_dir/next.config.js" || -f "$_dir/next.config.mjs" || -f "$_dir/next.config.ts" ]]; then
      _proj_root="$_dir"; _framework="nextjs"; break
    elif [[ -f "$_dir/nuxt.config.ts" || -f "$_dir/nuxt.config.js" ]]; then
      _proj_root="$_dir"; _framework="nuxt"; break
    elif [[ -f "$_dir/package.json" && -z "$_proj_root" ]]; then
      _proj_root="$_dir"
    fi
    _dir="$(dirname "$_dir")"
    [[ "$_dir" == "/" ]] && break
  done

  case "$ext" in
    ts|tsx|js|jsx)
      # Next.js 项目
      if [[ "$_framework" == "nextjs" && -n "$_proj_root" ]]; then
        desc="Next.js lint + 类型检查"
        result=$(cd "$_proj_root" && npx next lint --dir . --quiet 2>&1) || { echo "FAIL|$desc (next lint)"; exit 1; }
        result=$(cd "$_proj_root" && npx tsc --noEmit --pretty false 2>&1) || { echo "FAIL|$desc (tsc)"; exit 1; }
      # Nuxt 项目
      elif [[ "$_framework" == "nuxt" && -n "$_proj_root" ]]; then
        desc="Nuxt 类型检查"
        result=$(cd "$_proj_root" && npx nuxi typecheck 2>&1) || { echo "FAIL|$desc"; exit 1; }
      # 当前项目特定
      elif [[ "$file" == *"jimeng-api-service"* ]]; then
        desc="TypeScript 构建 (jimeng-api)"
        result=$(cd "${PROJECT_DIR}/jimeng-api-service" && npm run build 2>&1) || { echo "FAIL|$desc"; exit 1; }
      elif [[ "$file" == *"gui/src"* ]]; then
        desc="TypeScript 类型检查 (gui)"
        result=$(cd "${PROJECT_DIR}/gui" && npx tsc --noEmit --pretty false 2>&1) || { echo "FAIL|$desc"; exit 1; }
      elif [[ -n "$_proj_root" ]]; then
        desc="TypeScript 类型检查"
        result=$(cd "$_proj_root" && npx tsc --noEmit --pretty false 2>&1) || { echo "FAIL|$desc"; exit 1; }
      fi
      ;;
    rs)
      desc="Rust 编译检查"
      result=$(cd "${PROJECT_DIR}/gui/src-tauri" && cargo check 2>&1) || { echo "FAIL|$desc"; exit 1; }
      ;;
    py)
      desc="Python 语法检查"
      result=$(python3 -m py_compile "$file" 2>&1) || { echo "FAIL|$desc (语法错误)"; exit 1; }
      # ruff 只检查致命错误（E9 语法错误 + F8 运行时错误），不检查 lint 风格
      if command -v ruff &>/dev/null; then
        result=$(ruff check "$file" --select E9,F8 2>&1) || { echo "FAIL|$desc (ruff 致命错误)"; exit 1; }
      fi
      ;;
    json)
      desc="JSON 语法"
      result=$(python3 -c "import json; json.load(open('$file'))" 2>&1) || { echo "FAIL|$desc"; exit 1; }
      ;;
    *)
      exit 0  # 无需验证的文件类型
      ;;
  esac

  echo "PASS|$desc"
  exit 0
}

# ── 全栈验证 ──
cmd_full() {
  echo "╔══════════════════════════════════════════════╗"
  echo "║         技术栈全量验证                         ║"
  echo "╠══════════════════════════════════════════════╣"

  local total=0 passed=0 failed=0 warnings=0
  local results=""

  # 检测技术栈并逐项验证

  # --- Next.js 项目（自动扫描）---
  for nextconf in "$PROJECT_DIR"/*/next.config.{js,mjs,ts} "$PROJECT_DIR"/next.config.{js,mjs,ts}; do
    [[ -f "$nextconf" ]] || continue
    local next_dir
    next_dir=$(dirname "$nextconf")
    local next_name
    next_name=$(basename "$next_dir")
    [[ "$next_name" == "$(basename "$PROJECT_DIR")" ]] && next_name="root"

    # Next.js lint
    total=$((total + 1))
    echo -n "  Next.js lint ($next_name)... "
    if (cd "$next_dir" && npx next lint --dir . --quiet 2>&1) > /dev/null 2>&1; then
      echo -e "${GREEN}✅ PASS${NC}"
      results+="| Next.js lint ($next_name) | ✅ PASS | \`next lint\` |\n"
      passed=$((passed + 1))
    else
      echo -e "${RED}❌ FAIL${NC}"
      results+="| Next.js lint ($next_name) | ❌ FAIL | lint 错误 |\n"
      failed=$((failed + 1))
    fi

    # Next.js tsc
    if [[ -f "$next_dir/tsconfig.json" ]]; then
      total=$((total + 1))
      echo -n "  Next.js tsc ($next_name)... "
      if (cd "$next_dir" && npx tsc --noEmit 2>&1) > /dev/null 2>&1; then
        echo -e "${GREEN}✅ PASS${NC}"
        results+="| Next.js tsc ($next_name) | ✅ PASS | \`tsc --noEmit\` |\n"
        passed=$((passed + 1))
      else
        echo -e "${RED}❌ FAIL${NC}"
        local next_ts_errors
        next_ts_errors=$(cd "$next_dir" && npx tsc --noEmit 2>&1 | grep -c "error TS" || echo "?")
        results+="| Next.js tsc ($next_name) | ❌ FAIL | ${next_ts_errors} 个类型错误 |\n"
        failed=$((failed + 1))
      fi
    fi

    # Next.js build（可选，耗时较长）
    # 全量验证时不跑 build，太慢。审计时可手动跑 npx next build
  done

  # --- TypeScript (gui) ---
  if [[ -f "$PROJECT_DIR/gui/tsconfig.json" ]]; then
    total=$((total + 1))
    echo -n "  TypeScript (gui)... "
    if (cd "$PROJECT_DIR/gui" && npx tsc --noEmit 2>&1) > /dev/null 2>&1; then
      echo -e "${GREEN}✅ PASS${NC}"
      results+="| TypeScript (gui) | ✅ PASS | \`cd gui && npx tsc --noEmit\` |\n"
      passed=$((passed + 1))
    else
      echo -e "${RED}❌ FAIL${NC}"
      local ts_errors
      ts_errors=$(cd "$PROJECT_DIR/gui" && npx tsc --noEmit 2>&1 | grep -c "error TS" || echo "?")
      results+="| TypeScript (gui) | ❌ FAIL | ${ts_errors} 个类型错误 |\n"
      failed=$((failed + 1))
    fi
  fi

  # --- TypeScript (jimeng-api-service) ---
  if [[ -f "$PROJECT_DIR/jimeng-api-service/package.json" ]]; then
    total=$((total + 1))
    echo -n "  TypeScript (jimeng-api)... "
    if (cd "$PROJECT_DIR/jimeng-api-service" && npm run build 2>&1) > /dev/null 2>&1; then
      echo -e "${GREEN}✅ PASS${NC}"
      results+="| TypeScript (jimeng-api) | ✅ PASS | \`npm run build\` |\n"
      passed=$((passed + 1))
    else
      echo -e "${RED}❌ FAIL${NC}"
      results+="| TypeScript (jimeng-api) | ❌ FAIL | 构建失败 |\n"
      failed=$((failed + 1))
    fi
  fi

  # --- Rust ---
  if [[ -f "$PROJECT_DIR/gui/src-tauri/Cargo.toml" ]]; then
    total=$((total + 1))
    echo -n "  Rust (Tauri)... "
    if (cd "$PROJECT_DIR/gui/src-tauri" && cargo check 2>&1) > /dev/null 2>&1; then
      echo -e "${GREEN}✅ PASS${NC}"
      results+="| Rust (Tauri) | ✅ PASS | \`cargo check\` |\n"
      passed=$((passed + 1))
    else
      echo -e "${RED}❌ FAIL${NC}"
      local rs_errors
      rs_errors=$(cd "$PROJECT_DIR/gui/src-tauri" && cargo check 2>&1 | grep -c "^error" || echo "?")
      results+="| Rust (Tauri) | ❌ FAIL | ${rs_errors} 个编译错误 |\n"
      failed=$((failed + 1))
    fi
  fi

  # --- Python (批量 py_compile) ---
  if [[ -d "$PROJECT_DIR/scripts" ]]; then
    total=$((total + 1))
    echo -n "  Python (scripts/)... "
    local py_errors=0
    local py_error_files=""
    for pyfile in "$PROJECT_DIR"/scripts/*.py; do
      if ! python3 -m py_compile "$pyfile" 2>/dev/null; then
        py_errors=$((py_errors + 1))
        py_error_files+="$(basename "$pyfile") "
      fi
    done
    if [[ "$py_errors" -eq 0 ]]; then
      echo -e "${GREEN}✅ PASS${NC}"
      results+="| Python (scripts/) | ✅ PASS | $(ls "$PROJECT_DIR"/scripts/*.py 2>/dev/null | wc -l | tr -d ' ') 个文件全部通过 |\n"
      passed=$((passed + 1))
    else
      echo -e "${RED}❌ FAIL${NC}"
      results+="| Python (scripts/) | ❌ FAIL | ${py_errors} 个语法错误: ${py_error_files}|\n"
      failed=$((failed + 1))
    fi
  fi

  # --- Python ruff lint ---
  if command -v ruff &>/dev/null && [[ -d "$PROJECT_DIR/scripts" ]]; then
    total=$((total + 1))
    echo -n "  Python ruff lint... "
    local ruff_output ruff_exit
    ruff_output=$(cd "$PROJECT_DIR" && ruff check scripts/ --select E9,F8 2>&1) && ruff_exit=0 || ruff_exit=$?
    if [[ $ruff_exit -eq 0 ]] || echo "$ruff_output" | grep -q "All checks passed"; then
      echo -e "${GREEN}✅ PASS${NC}"
      results+="| Python ruff lint | ✅ PASS | 无严重问题 |\n"
      passed=$((passed + 1))
    else
      echo -e "${YELLOW}⚠️  WARN${NC}"
      results+="| Python ruff lint | ⚠️ WARN | 有 lint 警告（非阻塞）|\n"
      warnings=$((warnings + 1))
    fi
  fi

  # --- JSON 配置文件 ---
  total=$((total + 1))
  echo -n "  JSON 配置... "
  local json_errors=0
  for jf in "$PROJECT_DIR"/gui/src-tauri/tauri.conf.json "$PROJECT_DIR"/jimeng-api-service/tsconfig.json; do
    if [[ -f "$jf" ]] && ! python3 -c "import json; json.load(open('$jf'))" 2>/dev/null; then
      json_errors=$((json_errors + 1))
    fi
  done
  # tsconfig.json 是 JSONC（允许注释/trailing comma），用 tsc 验证而非 json.load
  # tsc --noEmit 已经在 TypeScript 检查里覆盖了
  if [[ "$json_errors" -eq 0 ]]; then
    echo -e "${GREEN}✅ PASS${NC}"
    results+="| JSON 配置 | ✅ PASS | 关键配置文件语法正确 |\n"
    passed=$((passed + 1))
  else
    echo -e "${RED}❌ FAIL${NC}"
    results+="| JSON 配置 | ❌ FAIL | ${json_errors} 个文件语法错误 |\n"
    failed=$((failed + 1))
  fi

  # --- 技术债扫描（--deep 模式）---
  if [[ "${DEEP_MODE:-}" == "1" ]]; then

    # Python 死代码检测（快速统计，不输出详情）
    if command -v ruff &>/dev/null && [[ -d "$PROJECT_DIR/scripts" ]]; then
      total=$((total + 1))
      echo -n "  Python 死代码... "
      local dead_total
      dead_total=$(cd "$PROJECT_DIR" && python3 -c "
import subprocess, json
r = subprocess.run(['ruff','check','scripts/','--select','F401,F811,F841','--output-format','json'], capture_output=True, text=True)
print(len(json.loads(r.stdout or '[]')))
" 2>/dev/null | tr -d '\n')
      if [[ "$dead_total" -le 10 ]]; then
        echo -e "${GREEN}✅ PASS${NC}"
        results+="| Python 死代码 | ✅ PASS | ${dead_total} 个（可接受）|\n"
        passed=$((passed + 1))
      else
        echo -e "${YELLOW}⚠️  WARN${NC}"
        results+="| Python 死代码 | ⚠️ WARN | ${dead_total} 个未使用 import/变量（建议定期清理）|\n"
        warnings=$((warnings + 1))
      fi
    fi

    # TypeScript 死代码检查跳过（tsc --noUnusedLocals 太慢，60s+）
    # TS 死代码在配对审查时由审查者人工检查

    # Python 代码复杂度
    if command -v ruff &>/dev/null && [[ -d "$PROJECT_DIR/scripts" ]]; then
      total=$((total + 1))
      echo -n "  Python 复杂度... "
      local complex_count
      complex_count=$(cd "$PROJECT_DIR" && python3 -c "
import subprocess, json
r = subprocess.run(['ruff','check','scripts/','--select','C901','--output-format','json'], capture_output=True, text=True)
print(len(json.loads(r.stdout or '[]')))
" 2>/dev/null | tr -d '\n')
      if [[ "$complex_count" -le 5 ]]; then
        echo -e "${GREEN}✅ PASS${NC}"
        results+="| Python 复杂度 | ✅ PASS | ${complex_count} 个高复杂度函数 |\n"
        passed=$((passed + 1))
      else
        echo -e "${YELLOW}⚠️  WARN${NC}"
        results+="| Python 复杂度 | ⚠️ WARN | ${complex_count} 个高复杂度函数需重构 |\n"
        warnings=$((warnings + 1))
      fi
    fi
  fi

  # 汇总
  echo "╠══════════════════════════════════════════════╣"
  echo -e "║  总计: $total 项  ✅ $passed  ❌ $failed  ⚠️ $warnings"
  echo "╚══════════════════════════════════════════════╝"

  # 输出 Markdown 表格（供审计报告使用）
  echo ""
  echo "| 技术栈 | 结果 | 详情 |"
  echo "|--------|------|------|"
  echo -e "$results"

  if [[ "$failed" -gt 0 ]]; then
    exit 1
  fi
  exit 0
}

# ── 检测技术栈（不运行验证）──
cmd_detect() {
  echo "| 技术栈 | 位置 | 验证命令 |"
  echo "|--------|------|----------|"
  # Next.js 项目
  for nextconf in "$PROJECT_DIR"/*/next.config.{js,mjs,ts} "$PROJECT_DIR"/next.config.{js,mjs,ts}; do
    [[ -f "$nextconf" ]] || continue
    local nd; nd=$(dirname "$nextconf")
    local nn; nn=$(basename "$nd"); [[ "$nn" == "$(basename "$PROJECT_DIR")" ]] && nn="root"
    echo "| Next.js | ${nn}/ | \`next lint\` + \`tsc --noEmit\` |"
  done
  [[ -f "$PROJECT_DIR/gui/tsconfig.json" ]] && echo "| TypeScript/React | gui/ | \`npx tsc --noEmit\` |"
  [[ -f "$PROJECT_DIR/gui/src-tauri/Cargo.toml" ]] && echo "| Rust/Tauri | gui/src-tauri/ | \`cargo check\` |"
  [[ -d "$PROJECT_DIR/scripts" ]] && echo "| Python | scripts/ ($(ls "$PROJECT_DIR"/scripts/*.py 2>/dev/null | wc -l | tr -d ' ') 个) | \`py_compile\` + \`ruff check\` |"
  [[ -f "$PROJECT_DIR/jimeng-api-service/package.json" ]] && echo "| TypeScript/Node | jimeng-api-service/ | \`npm run build\` |"
  return 0
}

# ── 入口 ──
ACTION="${1:-detect}"

case "$ACTION" in
  check)
    shift
    cmd_check "${1:?用法: stack-verify.sh check <file_path>}"
    ;;
  full)
    cmd_full
    ;;
  deep)
    DEEP_MODE=1 cmd_full
    ;;
  detect)
    cmd_detect
    ;;
  *)
    echo "用法: stack-verify.sh {check|full|deep|detect} [project_dir]"
    echo "  check <file>  — 检查单个文件"
    echo "  full           — 全栈验证（编译/语法）"
    echo "  deep           — 深度验证（full + 死代码 + 复杂度）"
    echo "  detect         — 检测技术栈"
    ;;
esac
