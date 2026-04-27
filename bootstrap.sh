#!/usr/bin/env bash
# ============================================================================
# legion-0 bootstrap.sh — 新电脑一行部署入口
# ----------------------------------------------------------------------------
# Usage（在目标电脑上跑）:
#
#   curl -fsSL https://raw.githubusercontent.com/ziyerr/legion-0/master/bootstrap.sh | bash
#
# 自动完成:
#   1. 依赖检查（缺失则打印安装命令并退出）
#   2. 克隆 legion-0 仓库到 ~/.claude（或 $CLAUDE_HOME）
#   3. 跑 install.sh 做环境初始化
#   4. 打印下一步操作
#
# 不做（避免改动系统）:
#   - 不自动装 Homebrew / apt 包 / node / npm
#   - 不碰 claude CLI 的登录态
#   - 不改用户 shell rc 文件
# ============================================================================
set -euo pipefail

REPO_URL="${LEGION_REPO:-https://github.com/ziyerr/legion-0.git}"
TARGET="${CLAUDE_HOME:-$HOME/.claude}"
BRANCH="${LEGION_BRANCH:-master}"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m  %s\n" "$*"; }
warn() { printf "\033[1;33m⚠\033[0m  %s\n" "$*"; }
die()  { printf "\033[1;31m✗\033[0m  %s\n" "$*" >&2; exit 1; }

# ============================================================================
# 1. 最小依赖检查（bootstrap 阶段只需要 git；其他 install.sh 再查）
# ============================================================================
say "legion-0 bootstrap 启动"

command -v git >/dev/null || die "缺少 git。macOS: brew install git  |  Linux: apt install git / yum install git"
ok "git 已就绪"

# 可选早期检查（给用户一个 headsup，不阻塞）
missing_hints=()
for cmd in tmux jq python3 node; do
  command -v "$cmd" >/dev/null || missing_hints+=("$cmd")
done
if [ ${#missing_hints[@]} -gt 0 ]; then
  warn "以下依赖在运行 install.sh 时需要，当前缺失：${missing_hints[*]}"
  warn "macOS 一键装：brew install ${missing_hints[*]}"
  warn "bootstrap 会继续，但 install.sh 会再次报错中断 —— 请提前装好"
fi

# ============================================================================
# 2. 目标目录判定
# ============================================================================
say "目标路径：$TARGET"

if [ -e "$TARGET" ]; then
  # 已存在 —— 判断是否本仓库
  if [ -d "$TARGET/.git" ] && git -C "$TARGET" remote get-url origin 2>/dev/null | grep -q "legion-0"; then
    say "检测到已安装的 legion-0，拉取最新 + 重跑 install.sh"
    git -C "$TARGET" fetch --all --prune
    git -C "$TARGET" pull --ff-only || die "拉取失败：$TARGET 有本地未提交改动，先处理后再跑"
    ok "已更新到最新"
  else
    die "$TARGET 已存在但不是 legion-0 仓库。
    → 备份已有数据：mv $TARGET ${TARGET}.bak-\$(date +%s)
    → 重新执行本命令
    或设置自定义路径：CLAUDE_HOME=~/.claude-legion curl -fsSL ... | bash"
  fi
else
  # 全新安装
  say "克隆 legion-0 → $TARGET"
  git clone --branch "$BRANCH" --depth 50 "$REPO_URL" "$TARGET"
  ok "仓库已克隆"
fi

# ============================================================================
# 3. 运行 install.sh
# ============================================================================
say "执行 install.sh 环境初始化"
[ -x "$TARGET/install.sh" ] || chmod +x "$TARGET/install.sh"
"$TARGET/install.sh"

# ============================================================================
# 4. 完成提示
# ============================================================================
cat <<'EOF'

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 legion-0 bootstrap 完成

 下一步（按需）:
   1. 装 Claude Code CLI（如未装）:  npm i -g @anthropic-ai/claude-code
   2. 首次登录:                      claude（首次会引导登录）
   3. 启动 L1 指挥官:                 ~/.claude/scripts/legion.sh l1 <军团名>

 文档:   ~/.claude/README.md
 升级:   重跑本命令即可（会 git pull 最新）
 卸载:   rm -rf ~/.claude
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
