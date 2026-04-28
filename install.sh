#!/usr/bin/env bash
# ============================================================================
# legion-0 install.sh — 军团体系一键部署
# ----------------------------------------------------------------------------
# 支持两种场景：
#   A) clone 到 ~/.claude/ → 就地 setup（推荐）
#   B) clone 到别处 → 自动创建 ~/.claude/ symlink 指向 clone 目录
#
# 可重复运行（idempotent），不破坏已有用户数据。
# ============================================================================
set -euo pipefail

LEGION_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
MIN_CLI_VER="2.1.118"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m  %s\n" "$*"; }
warn() { printf "\033[1;33m⚠\033[0m  %s\n" "$*"; }
die()  { printf "\033[1;31m✗\033[0m  %s\n" "$*" >&2; exit 1; }

# ============================================================================
# 1. 依赖检查
# ============================================================================
say "检查系统依赖"
missing=()
for cmd in tmux jq python3 node git; do
  command -v "$cmd" >/dev/null || missing+=("$cmd")
done
[ ${#missing[@]} -eq 0 ] || die "缺少依赖: ${missing[*]} — 请先安装（macOS: brew install ${missing[*]}；Linux: 用你的包管理器）"
ok "tmux / jq / python3 / node / git 已就绪"

# Claude CLI 版本
if command -v claude >/dev/null; then
  CLI_VER="$(claude --version 2>/dev/null | awk '{print $1}' || echo 0.0.0)"
  LOWEST="$(printf '%s\n%s\n' "$CLI_VER" "$MIN_CLI_VER" | sort -V | head -1)"
  if [ "$LOWEST" = "$MIN_CLI_VER" ]; then
    ok "Claude CLI $CLI_VER ≥ $MIN_CLI_VER"
  else
    warn "Claude CLI 版本 $CLI_VER < $MIN_CLI_VER（有授权弹窗 bug）"
    warn "建议：npm i -g @anthropic-ai/claude-code@latest"
  fi
else
  warn "未检测到 claude CLI"
  warn "安装：npm i -g @anthropic-ai/claude-code"
fi

# ============================================================================
# 2. 安装位置判定
# ============================================================================
say "安装位置：${CLAUDE_HOME}"
if [ "${LEGION_ROOT}" = "${CLAUDE_HOME}" ]; then
  ok "就地安装（LEGION_ROOT 就是 ${CLAUDE_HOME}）"
elif [ -L "${CLAUDE_HOME}" ] && [ "$(readlink "${CLAUDE_HOME}")" = "${LEGION_ROOT}" ]; then
  ok "${CLAUDE_HOME} 已是指向 ${LEGION_ROOT} 的 symlink"
elif [ -e "${CLAUDE_HOME}" ]; then
  die "${CLAUDE_HOME} 已存在且不是本仓库
    → 手动备份后执行：rm -rf ${CLAUDE_HOME}
    → 或：CLAUDE_HOME=~/my-legion ./install.sh 使用自定义路径"
else
  say "创建 symlink：${CLAUDE_HOME} → ${LEGION_ROOT}"
  ln -s "${LEGION_ROOT}" "${CLAUDE_HOME}"
  ok "symlink 已建"
fi

# ============================================================================
# 3. 重建运行时目录（gitignore 排除，clone 后为空）
# ============================================================================
say "重建运行时目录"
runtime_dirs=(
  legion sessions cache backups
  file-history shell-snapshots paste-cache session-env
  downloads projects todos tasks teams
  ide plugins statsig
)
for d in "${runtime_dirs[@]}"; do
  mkdir -p "${CLAUDE_HOME}/$d"
done
ok "运行时目录已就绪（${#runtime_dirs[@]} 个）"

# ============================================================================
# 4. 脚本权限位
# ============================================================================
say "确保 scripts/ 可执行"
chmod +x "${LEGION_ROOT}"/scripts/*.sh 2>/dev/null || true
chmod +x "${LEGION_ROOT}"/scripts/*.py 2>/dev/null || true
[ -f "${LEGION_ROOT}/scripts/codex" ] && chmod +x "${LEGION_ROOT}/scripts/codex" || true
[ -f "${LEGION_ROOT}/scripts/claude" ] && chmod +x "${LEGION_ROOT}/scripts/claude" || true
[ -f "${LEGION_ROOT}/scripts/legion" ] && chmod +x "${LEGION_ROOT}/scripts/legion" || true
[ -d "${LEGION_ROOT}/scripts/hooks" ] && chmod +x "${LEGION_ROOT}/scripts/hooks"/* 2>/dev/null || true
[ -f "${LEGION_ROOT}/install.sh" ] && chmod +x "${LEGION_ROOT}/install.sh" || true
ok "权限位已设"

# ============================================================================
# 5. Git hooks
# ============================================================================
if [ -d "${LEGION_ROOT}/.git" ]; then
  say "检查 git hooks（模板同步 + auto-push）"
  for h in pre-commit post-commit; do
    if [ -f "${LEGION_ROOT}/.git/hooks/$h" ] && [ -x "${LEGION_ROOT}/.git/hooks/$h" ]; then
      ok "$h hook 就位"
    else
      warn "$h hook 缺失或不可执行（不影响使用，但模板同步/auto-push 失效）"
    fi
  done
fi

# ============================================================================
# 6. 安装自检
# ============================================================================
say "安装自检"
[ -x "${LEGION_ROOT}/scripts/legion.sh" ] || die "scripts/legion.sh 不可执行"
[ -d "${LEGION_ROOT}/agents" ]  || die "agents/ 缺失"
[ -d "${LEGION_ROOT}/skills" ]  || die "skills/ 缺失"
[ -d "${LEGION_ROOT}/commander" ] || warn "commander/ 缺失 — L1 指挥官启动可能降级"
[ -f "${LEGION_ROOT}/CLAUDE.md" ] || warn "CLAUDE.md 缺失 — 全局自主权第一原则未定义"

n_agents="$(find "${LEGION_ROOT}/agents" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
n_skills="$(find "${LEGION_ROOT}/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
n_scripts="$(find "${LEGION_ROOT}/scripts" -maxdepth 1 -type f -name '*.sh' 2>/dev/null | wc -l | tr -d ' ')"
n_tactics="$(find "${LEGION_ROOT}/memory/tactics" -maxdepth 1 -type f -name 'tactic-*.md' 2>/dev/null | wc -l | tr -d ' ')"

ok "agents=$n_agents  skills=$n_skills  scripts=$n_scripts  tactics=$n_tactics"

# ============================================================================
# 完成
# ============================================================================
G=$'\033[1;32m'; N=$'\033[0m'
cat <<EOF

${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}
${G} 军团体系部署完成${N}

 快速开始：
   1. 项目初始化+配置：  ~/.claude/scripts/legion 0
   2. 一键主持启动：     legion h
   3. 启动 L1 指挥官：   ~/.claude/scripts/legion.sh l1 <军团名>
   4. Codex L1 指挥官：  ~/.claude/scripts/legion codex l1 [军团名]
   4b. Claude L1 指挥官： ~/.claude/scripts/claude l1 [军团名]
   5. 状态查询：         ~/.claude/scripts/legion.sh status
   6. 作战态势：         ~/.claude/scripts/legion.sh sitrep

 裸命令 claude/codex l1：
   export PATH="\$HOME/.claude/scripts:\$PATH"
   legion 0                 # 当前项目初始化
   legion h                 # 初始化并启动主持人 + Claude/Codex 军团
   claude l1 青龙军团        # 进入/启动 Claude L1；--no-attach 可后台启动
   legion codex l1          # 载入在线 Codex L1；没有才随机新增
   codex l1 玄武军团         # 进入/启动 Codex L1；--no-attach 可后台启动
   legion codex l1 玄武军团  # 进入/启动指定军团名

 项目级定制：
   在项目根目录新建 \`.claude/agents/\` 或 \`.claude/skills/\` 覆盖全局版本。

 卸载：
   rm -rf ${CLAUDE_HOME}    # 就地安装
   rm ${CLAUDE_HOME}        # symlink 模式（保留 clone 目录）

 详细文档： ${LEGION_ROOT}/README.md
${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}
EOF
