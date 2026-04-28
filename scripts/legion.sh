#!/bin/bash
# ============================================================================
# legion.sh — 军团制战区化协同作战启动器 + 实时通信系统
# ============================================================================
#
# 每次执行创建一个新的 tmux window，启动独立的 claude 实例。
# 所有 window 共享注册表、消息通道、文件锁和任务板。
#
# 用法：
#   legion.sh                          # 启动新 team（交互式输入需求）
#   legion.sh 0                        # 配置全局入口并展开当前项目军团体系
#   legion.sh "实现健康检查接口"        # 启动新 team 并直接给需求
#   legion.sh --commander L1-test "任务" # 启动 team 隶属指定指挥官
#   legion.sh campaign 'JSON计划'      # 部署战役（多 team）
#   legion.sh campaign --commander L1-test 'JSON' # 战役隶属指定指挥官
#   legion.sh status                   # 查看所有 team 状态（按指挥官分组）
#   legion.sh sitrep                   # 综合态势（status+board+locks+inbox）
#   legion.sh ops                      # 一屏运营面板（mixed部队+阻塞+巡查+gate+retro，只读）
#   legion.sh inbox                    # 查看 L1 收到的汇报
#   legion.sh inbox L1-test            # 查看指定指挥官的汇报
#   legion.sh board                    # 查看任务板
#   legion.sh locks                    # 查看文件锁
#   legion.sh msg TEAM_ID "内容"       # L1 下达指令
#   legion.sh gate TEAM_ID block "原因" # 激活审批门（暂停 team）
#   legion.sh gate TEAM_ID approve     # 放行审批门
#   legion.sh l1                       # 恢复离线军团，无离线则新建
#   legion.sh l1 test                  # 启动/恢复 L1-test 指挥官
#   legion.sh l1+1                     # 强制创建全新军团
#   legion.sh l1+1 test                # 强制创建指定名称的全新军团
#   legion.sh joint [--dry-run] "战略目标描述" # 启动联合指挥（大规模任务统一调度）
#   legion.sh war-room                 # 进入作战室（联合指挥的多军团分屏视图）
#   legion.sh watch                    # 实时活动流（tail 所有通信）
#   legion.sh audit                    # 部署审计 team 做最终质量把关
#   legion.sh mixed <cmd>              # 统一 Legion Core 混编调度器（Claude + Codex）
#   legion.sh h                        # 启动/恢复 Claude L1 当前窗口，Codex L1 后台
#   legion.sh host                     # 一键启动独立 Claude L1 + Codex L1；不自动合并分屏
#   legion.sh aicto                    # 查看外部 Hermes AICTO profile 状态/启动指引
#   legion.sh codex l1 [名]            # 启动 Codex L1；不写名则载入在线军团，没有才新增
#   claudel1 [名]                      # 无冲突裸命令：启动/恢复 Claude L1
#   codexl1 [名]                       # 无冲突裸命令：启动/恢复 Codex L1
#   legion.sh claude h                 # Claude L1 当前窗口，Codex L1 后台，同时接入军团通讯
#   legion.sh claude l1 [名]           # 启动 / 恢复 Claude L1 指挥官
#   legion.sh duo                      # 打开两个终端窗口：Codex L1 + Claude L1
#   legion.sh dou                      # 新窗口 Codex L1，当前窗口 Claude L1
#   legion.sh health                   # Commander 健康 + 扩编统计
#   legion.sh kill-all                 # 终止所有 team + 卸载 hooks
#
# ============================================================================

set -euo pipefail

# 按项目隔离：用工作目录的 hash 区分不同项目
LEGION_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEGION_REPO_ROOT="$(cd "$LEGION_SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$(pwd)"
if PROJECT_HASH=$(LEGION_HASH_INPUT="$PROJECT_DIR" python3 -c 'import hashlib, os; print(hashlib.md5(os.environ["LEGION_HASH_INPUT"].encode("utf-8")).hexdigest()[:8])' 2>/dev/null); then
  :
elif command -v md5 >/dev/null 2>&1; then
  PROJECT_HASH=$(printf "%s" "$PROJECT_DIR" | md5 | cut -c1-8)
elif command -v md5sum >/dev/null 2>&1; then
  PROJECT_HASH=$(printf "%s" "$PROJECT_DIR" | md5sum | cut -c1-8)
else
  echo "❌ 找不到 python3/md5/md5sum，无法计算项目 hash" >&2
  exit 1
fi
PROJECT_NAME=$(basename "$PROJECT_DIR")
REQUESTED_ACTION="${1:-launch}"

SESSION="legion-${PROJECT_HASH}-${PROJECT_NAME}"
REGISTRY_DIR="$HOME/.claude/legion/${PROJECT_HASH}"
LEGION_DIR="${LEGION_DIR:-$REGISTRY_DIR}"
MIXED_DIR="${MIXED_DIR:-$REGISTRY_DIR/mixed}"
REGISTRY="$REGISTRY_DIR/registry.json"
SYSTEM_PROMPT_FILE="$REGISTRY_DIR/system-prompt.txt"
LOCKS_FILE="$REGISTRY_DIR/locks.json"
TASKBOARD="$REGISTRY_DIR/taskboard.json"
BROADCAST="$REGISTRY_DIR/broadcast.jsonl"
COMMANDER_PID_FILE="$REGISTRY_DIR/commander.pid"
COMMANDER_HEARTBEAT_FILE="$REGISTRY_DIR/commander.heartbeat"
SETTINGS_FILE="$HOME/.claude/settings.json"
HOOKS_DIR="$HOME/.claude/scripts/hooks"
HEARTBEAT_MAX_AGE=15  # 心跳超过 15 秒判定为死亡

_legion_has_arg() {
  local expected="$1"
  shift || true
  local arg
  for arg in "$@"; do
    [[ "$arg" == "$expected" ]] && return 0
  done
  return 1
}

# 只读视图操作不应当触发初始化、目录注册或 commander 注入。
# 命中此清单的子命令跳过启动态写入。
LEGION_READ_ONLY=0
case "$REQUESTED_ACTION" in
  status|board|locks|inbox|sitrep|watch|health|usage|patrol|retro|retrospector|mailbox|gc-zombies|switch|account|war-room|gate|ops)
    LEGION_READ_ONLY=1
    ;;
  mixed)
    # mixed 只读子命令和 dry-run launch/campaign 都豁免初始化。
    case "${2:-}" in
      status|inbox|readiness|aicto-reports) LEGION_READ_ONLY=1 ;;
      view)
        if _legion_has_arg --dry-run "${@:3}"; then
          LEGION_READ_ONLY=1
        fi
        ;;
      aicto)
        LEGION_READ_ONLY=1
        ;;
      campaign|host|dual-host)
        if _legion_has_arg --dry-run "${@:3}"; then
          LEGION_READ_ONLY=1
        fi
        ;;
    esac
    ;;
  claude|codex)
    case "${2:-}" in
      h|host|主持|l1|l1+1)
        if _legion_has_arg --dry-run "${@:3}"; then
          LEGION_READ_ONLY=1
        fi
        ;;
    esac
    ;;
  aicto|cto|总司令)
    LEGION_READ_ONLY=1
    ;;
  h|host|主持)
    if _legion_has_arg --dry-run "${@:2}"; then
      LEGION_READ_ONLY=1
    fi
    ;;
  view|v|看板|作战面)
    if _legion_has_arg --dry-run "${@:2}"; then
      LEGION_READ_ONLY=1
    fi
    ;;
  duo|dou)
    if _legion_has_arg --dry-run "${@:2}"; then
      LEGION_READ_ONLY=1
    fi
    ;;
esac

# ── 全局军团名册：仅由 legion 0 / legion-init.sh 注册项目 ──
LEGION_DIRECTORY="$HOME/.claude/legion/directory.json"
if [[ "$LEGION_READ_ONLY" -eq 0 ]]; then
  mkdir -p "$REGISTRY_DIR" "$(dirname "$LEGION_DIRECTORY")"
fi
_register_to_directory() {
  python3 << REGEOF
import json, fcntl, os, time
directory_path = os.path.expanduser('$LEGION_DIRECTORY')
lock_path = directory_path + '.lock'
entry = {
    'hash': '$PROJECT_HASH',
    'project': '$PROJECT_NAME',
    'path': '$PROJECT_DIR',
    'cc_team': 'legion-$PROJECT_HASH',
    'last_active': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
}
# 确保文件存在
if not os.path.exists(directory_path):
    with open(directory_path, 'w') as f:
        json.dump({'legions': []}, f)
open(lock_path, 'a').close()
try:
    with open(lock_path, 'r') as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            with open(directory_path) as f:
                data = json.load(f)
            legions = data.get('legions', [])
            # 更新或添加
            found = False
            for l in legions:
                if l['hash'] == entry['hash']:
                    l.update(entry)
                    found = True
                    break
            if not found:
                legions.append(entry)
            data['legions'] = legions
            with open(directory_path, 'w') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
except Exception:
    pass
REGEOF
}
# 普通启动/恢复 L1 只创建 mixed runtime 通讯状态，不注册项目目录。
# 项目注册、memory、技能、工具和持久化通讯基座初始化统一归 legion 0。

# ── 项目军团初始化：新项目首次启动时复制 agent/skill 定义 ──
LEGION_TEMPLATE_PROJECT="$HOME/.claude/legion/template"
_project_legion_ready() {
  local agent_count skill_count
  if [[ -d "$PROJECT_DIR/.claude/agents" ]]; then
    agent_count=$(find "$PROJECT_DIR/.claude/agents" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  else
    agent_count=0
  fi
  if [[ -d "$PROJECT_DIR/.claude/skills" ]]; then
    skill_count=$(find "$PROJECT_DIR/.claude/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  else
    skill_count=0
  fi
  [[ "$agent_count" -ge 5 && "$skill_count" -ge 3 && -f "$PROJECT_DIR/CLAUDE.md" ]]
}

_legion_init_script() {
  if [[ -x "$LEGION_SCRIPT_DIR/legion-init.sh" ]]; then
    printf '%s\n' "$LEGION_SCRIPT_DIR/legion-init.sh"
  elif [[ -x "$HOME/.claude/scripts/legion-init.sh" ]]; then
    printf '%s\n' "$HOME/.claude/scripts/legion-init.sh"
  else
    return 1
  fi
}

_legion_commander_script() {
  if [[ -f "$LEGION_SCRIPT_DIR/legion-commander.py" ]]; then
    printf '%s\n' "$LEGION_SCRIPT_DIR/legion-commander.py"
  elif [[ -f "$HOME/.claude/scripts/legion-commander.py" ]]; then
    printf '%s\n' "$HOME/.claude/scripts/legion-commander.py"
  else
    return 1
  fi
}

_legion_self_check_script() {
  if [[ -f "$LEGION_SCRIPT_DIR/legion-self-check.py" ]]; then
    printf '%s\n' "$LEGION_SCRIPT_DIR/legion-self-check.py"
  elif [[ -f "$HOME/.claude/scripts/legion-self-check.py" ]]; then
    printf '%s\n' "$HOME/.claude/scripts/legion-self-check.py"
  else
    return 1
  fi
}

_run_legion_project_self_check() {
  local self_check_script
  [[ "${LEGION_SELF_CHECK_DISABLE:-0}" == "1" ]] && return 0
  self_check_script="$(_legion_self_check_script)" || return 0
  python3 "$self_check_script" --project "$PROJECT_DIR" --quiet || {
    echo "⚠ Legion 项目自检发现问题，请运行 legion 0 修复" >&2
  }
}

_legion_reference_project() {
  if [[ -d "$HOME/.claude/skills" && -d "$HOME/.claude/agents" ]]; then
    printf '%s\n' "$HOME"
  elif [[ -d "$LEGION_REPO_ROOT/.claude/skills" && -d "$LEGION_REPO_ROOT/.claude/agents" ]]; then
    printf '%s\n' "$LEGION_REPO_ROOT"
  elif [[ -d "$LEGION_REPO_ROOT/skills" && -d "$LEGION_REPO_ROOT/agents" ]]; then
    printf '%s\n' "$LEGION_REPO_ROOT"
  else
    printf '%s\n' "$HOME"
  fi
}

_run_legion_project_self_check

_sync_dir_contents() {
  local src="$1"
  local dst="$2"
  [[ -d "$src" ]] || return 0
  mkdir -p "$dst"
  if [[ "$(cd "$src" && pwd -P)" == "$(cd "$dst" && pwd -P 2>/dev/null || printf '')" ]]; then
    return 0
  fi
  cp -R "$src"/. "$dst"/
}

_seed_dir_if_empty() {
  local src="$1"
  local dst="$2"
  [[ -d "$src" ]] || return 0
  if [[ -d "$dst" ]] && find "$dst" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .; then
    return 0
  fi
  _sync_dir_contents "$src" "$dst"
}

_path_contains_dir() {
  local needle="$1"
  case ":${PATH:-}:" in
    *":$needle:"*) return 0 ;;
    *) return 1 ;;
  esac
}

_append_legion_path_to_shell_rc() {
  local shell_name rc_file
  shell_name="$(basename "${SHELL:-zsh}")"
  case "$shell_name" in
    bash) rc_file="$HOME/.bashrc" ;;
    zsh|*) rc_file="$HOME/.zshrc" ;;
  esac
  mkdir -p "$(dirname "$rc_file")"
  touch "$rc_file"
  if grep -q 'legion-0 global path' "$rc_file" 2>/dev/null; then
    return 0
  fi
  cat >> "$rc_file" <<'EOF'

# >>> legion-0 global path >>>
export PATH="$HOME/.claude/scripts:$PATH"
# <<< legion-0 global path <<<
EOF
  echo "  ✅ 已写入 PATH 配置: $rc_file"
  echo "     新终端可直接使用 legion；当前终端可执行: export PATH=\"\$HOME/.claude/scripts:\$PATH\""
}

_write_global_command_wrappers() {
  local target_dir="$1"
  local scripts_dir="$HOME/.claude/scripts"
  local command_name
  mkdir -p "$target_dir"
  for command_name in legion claudel1 codexl1; do
    cat > "$target_dir/$command_name" <<EOF
#!/usr/bin/env bash
exec "$scripts_dir/$command_name" "\$@"
EOF
    chmod +x "$target_dir/$command_name"
  done
}

_legion_source_fingerprint() {
  (
    cd "$LEGION_REPO_ROOT" || exit 1
    for path in \
      scripts/legion \
      scripts/claudel1 \
      scripts/codexl1 \
      scripts/legion.sh \
      scripts/legion-init.sh \
      scripts/legion-self-check.py \
      scripts/legion_core.py \
      scripts/claude \
      scripts/codex \
      scripts/stack-verify.sh \
      schemas/legion-worker-result.schema.json
    do
      [[ -f "$path" ]] || continue
      shasum "$path"
    done
    for path in .claude/agents .claude/skills agents skills; do
      [[ -d "$path" ]] || continue
      find "$path" -mindepth 1 -maxdepth 1 -print 2>/dev/null | sort
    done
  ) | shasum | awk '{print $1}'
}

_global_legion_config_ready() {
  local scripts_dst="$HOME/.claude/scripts"
  local fingerprint_file="$HOME/.claude/legion/.global-entrypoint-fingerprint"
  local current_fingerprint

  [[ -x "$scripts_dst/legion" && -x "$scripts_dst/claudel1" && -x "$scripts_dst/codexl1" ]] || return 1
  [[ -x "$scripts_dst/legion.sh" && -x "$scripts_dst/legion-init.sh" ]] || return 1
  [[ -x "$(command -v legion 2>/dev/null || true)" ]] || return 1
  [[ -x "$(command -v claudel1 2>/dev/null || true)" ]] || return 1
  [[ -x "$(command -v codexl1 2>/dev/null || true)" ]] || return 1
  [[ -f "$fingerprint_file" ]] || return 1

  current_fingerprint="$(_legion_source_fingerprint)"
  [[ "$(cat "$fingerprint_file" 2>/dev/null)" == "$current_fingerprint" ]]
}

_install_legion_command() {
  local path_dir

  if [[ -n "${LEGION_GLOBAL_BIN_DIR:-}" ]]; then
    _write_global_command_wrappers "$LEGION_GLOBAL_BIN_DIR"
    echo "  ✅ legion/claudel1/codexl1 裸命令: $LEGION_GLOBAL_BIN_DIR"
    return 0
  fi

  if _path_contains_dir "$HOME/.claude/scripts"; then
    echo "  ✅ PATH 已包含 ~/.claude/scripts（legion/claudel1/codexl1）"
    return 0
  fi

  IFS=':' read -r -a _legion_path_dirs <<< "${PATH:-}"
  for path_dir in "${_legion_path_dirs[@]}"; do
    [[ -n "$path_dir" && -d "$path_dir" && -w "$path_dir" ]] || continue
    case "$path_dir" in
      /bin|/sbin|/usr/bin|/usr/sbin) continue ;;
    esac
    _write_global_command_wrappers "$path_dir" 2>/dev/null || continue
    echo "  ✅ legion/claudel1/codexl1 裸命令: $path_dir"
    return 0
  done

  _append_legion_path_to_shell_rc
}

_ensure_global_legion_config() {
  local mode="${1:-auto}"
  local scripts_dst="$HOME/.claude/scripts"
  local schemas_dst="$HOME/.claude/schemas"
  local fingerprint_file="$HOME/.claude/legion/.global-entrypoint-fingerprint"
  local current_fingerprint
  local agents_src=""
  local skills_src=""

  if [[ "$mode" != "force" ]] && _global_legion_config_ready; then
    echo "✅ 全局 legion 入口已就绪"
    return 0
  fi

  echo "🔧 检查全局 legion 入口配置..."
  mkdir -p "$HOME/.claude" "$scripts_dst"

  _sync_dir_contents "$LEGION_REPO_ROOT/scripts" "$scripts_dst"
  _sync_dir_contents "$LEGION_REPO_ROOT/schemas" "$schemas_dst"

  if [[ -d "$LEGION_REPO_ROOT/.claude/agents" ]]; then
    agents_src="$LEGION_REPO_ROOT/.claude/agents"
  elif [[ -d "$LEGION_REPO_ROOT/agents" ]]; then
    agents_src="$LEGION_REPO_ROOT/agents"
  fi
  if [[ -d "$LEGION_REPO_ROOT/.claude/skills" ]]; then
    skills_src="$LEGION_REPO_ROOT/.claude/skills"
  elif [[ -d "$LEGION_REPO_ROOT/skills" ]]; then
    skills_src="$LEGION_REPO_ROOT/skills"
  fi
  _seed_dir_if_empty "$agents_src" "$HOME/.claude/agents"
  _seed_dir_if_empty "$skills_src" "$HOME/.claude/skills"

  chmod +x "$scripts_dst"/*.sh 2>/dev/null || true
  chmod +x "$scripts_dst"/*.py 2>/dev/null || true
  chmod +x "$scripts_dst"/legion "$scripts_dst"/claudel1 "$scripts_dst"/codexl1 2>/dev/null || true
  chmod +x "$scripts_dst"/claude "$scripts_dst"/codex 2>/dev/null || true
  chmod +x "$scripts_dst"/hooks/* 2>/dev/null || true

  _install_legion_command

  mkdir -p "$(dirname "$fingerprint_file")"
  current_fingerprint="$(_legion_source_fingerprint)"
  printf '%s\n' "$current_fingerprint" > "$fingerprint_file"
}

_run_project_initializer() {
  local init_script reference_project
  init_script="$(_legion_init_script)" || {
    echo "❌ 找不到 legion-init.sh。请先运行 install.sh 或使用本仓库 scripts/legion.sh。"
    exit 1
  }
  reference_project="${LEGION_REFERENCE_PROJECT:-$(_legion_reference_project)}"
  LEGION_REFERENCE_PROJECT="$reference_project" LEGION_INIT_ASSUME_YES=1 bash "$init_script" "$@"
}

_ensure_project_initialized() {
  local mode="${1:-full}"
  if _project_legion_ready; then
    echo "✅ 项目军团体系已初始化"
    return 0
  fi
  if [[ "$mode" == "minimal" ]]; then
    echo "🔧 项目军团体系未完整展开，先执行轻量初始化..."
    _run_project_initializer --minimal
  else
    echo "🔧 项目军团体系未完整展开，先执行 legion 0 初始化..."
    _run_project_initializer
  fi
}

_init_project_legion() {
  # 检查是否已有 agent 定义
  if [[ -d "$PROJECT_DIR/.claude/agents" ]] && [[ $(ls "$PROJECT_DIR/.claude/agents/"*.md 2>/dev/null | wc -l) -ge 5 ]]; then
    return  # 已初始化
  fi

  echo "🔧 新项目首次启动军团，初始化 agent 和 skill 定义..."

  # 查找模板源：优先用 template/，否则找全局名册中已有的项目
  local TEMPLATE_SRC=""
  if [[ -d "$LEGION_REPO_ROOT/.claude/agents" ]]; then
    TEMPLATE_SRC="$LEGION_REPO_ROOT"
  elif [[ -d "$HOME/.claude/agents" ]]; then
    TEMPLATE_SRC="$HOME"
  elif [[ -d "$LEGION_TEMPLATE_PROJECT/.claude/agents" ]]; then
    TEMPLATE_SRC="$LEGION_TEMPLATE_PROJECT"
  else
    # 从全局名册找第一个已初始化的项目作为模板
    TEMPLATE_SRC=$(python3 -c "
import json, os
d_path = os.path.expanduser('$LEGION_DIRECTORY')
if not os.path.exists(d_path): exit()
with open(d_path) as f:
    data = json.load(f)
for l in data.get('legions', []):
    agents_dir = os.path.join(l['path'], '.claude', 'agents')
    if os.path.isdir(agents_dir) and len(os.listdir(agents_dir)) >= 5:
        if l['path'] != '$PROJECT_DIR':
            print(l['path'])
            break
" 2>/dev/null)
  fi

  if [[ -z "$TEMPLATE_SRC" ]]; then
    echo "  ⚠ 未找到模板项目，跳过初始化。请手动复制 .claude/agents/ 和 .claude/skills/"
    return
  fi

  echo "  模板源: $TEMPLATE_SRC"

  # 复制 agent 定义（去掉项目特化内容由各 agent 第零步初始化处理）
  mkdir -p "$PROJECT_DIR/.claude/agents"
  for f in "$TEMPLATE_SRC/.claude/agents/"*.md; do
    [[ -f "$f" ]] && cp "$f" "$PROJECT_DIR/.claude/agents/" 2>/dev/null
  done
  echo "  ✅ agents: $(ls "$PROJECT_DIR/.claude/agents/"*.md 2>/dev/null | wc -l | tr -d ' ') 个岗位定义"

  # 复制 skill 定义（SKILL.md + references/，不复制 knowledge/ 内容）
  for skill in agent-team audit recon product-counselor ui-designer sniper degradation-policy spec-driven; do
    local src="$TEMPLATE_SRC/.claude/skills/$skill"
    local dst="$PROJECT_DIR/.claude/skills/$skill"
    if [[ -d "$src" ]]; then
      mkdir -p "$dst"
      # 复制 SKILL.md
      [[ -f "$src/SKILL.md" ]] && cp "$src/SKILL.md" "$dst/"
      # 复制 references/（技术手册等）
      [[ -d "$src/references" ]] && cp -r "$src/references" "$dst/" 2>/dev/null
      # 创建空 knowledge/ 目录（内容由第零步初始化机制重建）
      [[ -d "$src/knowledge" ]] && mkdir -p "$dst/knowledge"
    fi
  done
  echo "  ✅ skills: $(ls -d "$PROJECT_DIR/.claude/skills/"*/ 2>/dev/null | wc -l | tr -d ' ') 个技能定义"

  # 创建 commander 简报目录 + 从其他项目复制简报作为参考
  mkdir -p "$PROJECT_DIR/.claude/commander/briefings"
  if [[ -d "$TEMPLATE_SRC/.claude/commander/briefings" ]]; then
    for brief in "$TEMPLATE_SRC/.claude/commander/briefings/"*.md; do
      [[ -f "$brief" ]] && cp "$brief" "$PROJECT_DIR/.claude/commander/briefings/" 2>/dev/null
    done
    local brief_count=$(ls "$PROJECT_DIR/.claude/commander/briefings/"*.md 2>/dev/null | wc -l | tr -d ' ')
    echo "  ✅ commander briefings: $brief_count 份（从其他项目复制作为参考）"
  else
    echo "  ✅ commander briefings 目录已创建（空，待本项目积累）"
  fi

  # 复制 claims.sh
  [[ -f "$TEMPLATE_SRC/.claude/scripts/claims.sh" ]] && {
    mkdir -p "$PROJECT_DIR/.claude/scripts"
    cp "$TEMPLATE_SRC/.claude/scripts/claims.sh" "$PROJECT_DIR/.claude/scripts/"
    echo "  ✅ claims.sh 已复制"
  }

  # 复制 codex-team.sh
  [[ -f "$TEMPLATE_SRC/.claude/scripts/codex-team.sh" ]] && {
    cp "$TEMPLATE_SRC/.claude/scripts/codex-team.sh" "$PROJECT_DIR/.claude/scripts/"
    echo "  ✅ codex-team.sh 已复制"
  }

  echo "  🎯 初始化完成。各知识库将在首次使用时由第零步机制从代码自动重建。"
}
# 普通启动路径不再隐式展开项目模板；全局/项目/记忆/技能/工具初始化只归 legion 0。

# ── 加载邮箱工具库（已废弃，保留向后兼容）──
MAILBOX_SCRIPT=""
for candidate in \
  "$LEGION_SCRIPT_DIR/legion-mailbox.sh" \
  "$HOME/.claude/scripts/legion-mailbox.sh"; do
  if [[ -f "$candidate" ]]; then
    MAILBOX_SCRIPT="$candidate"
    break
  fi
done
if [[ -n "$MAILBOX_SCRIPT" ]]; then
  export PROJECT_DIR PROJECT_HASH LEGION_DIR REGISTRY REGISTRY_DIR
  source "$MAILBOX_SCRIPT" 2>/dev/null || true
fi

# ── 初始化注册表 ──
_init_registry() {
  if [[ ! -f "$REGISTRY" ]]; then
    echo '{"teams":[]}' > "$REGISTRY"
  fi
}

# ── 初始化通信基础设施 ──
_init_comms() {
  if [[ ! -f "$LOCKS_FILE" ]]; then echo '{"locks":[]}' > "$LOCKS_FILE"; fi
  if [[ ! -f "$TASKBOARD" ]]; then echo '{"tasks":[],"updated":""}' > "$TASKBOARD"; fi
  if [[ ! -f "$BROADCAST" ]]; then touch "$BROADCAST"; fi
}

# ── 安全发送消息到军团终端 ──
# 检查目标是否在等待输入（❯ 提示符），是则 send-keys，否则写 inbox 兜底
_safe_send() {
  local target_session="$1"
  local message="$2"
  local target_team="${3:-}"  # 可选：team ID，用于 inbox 兜底

  # 检查 session 是否存在
  if ! tmux has-session -t "$target_session" 2>/dev/null; then
    echo "  ⚠ session $target_session 不存在" >&2
    return 1
  fi

  # 检查是否在等待输入（最后几行有 ❯）
  local screen
  screen=$(tmux capture-pane -t "$target_session" -p 2>/dev/null | tail -5)
  if echo "$screen" | grep -q '❯'; then
    # 在等待输入，直接发送（转义特殊字符）
    tmux send-keys -t "$target_session" -l "$message"
    tmux send-keys -t "$target_session" Enter
    return 0
  fi

  # 不在等待输入：等最多 10 秒
  for i in $(seq 1 10); do
    sleep 1
    screen=$(tmux capture-pane -t "$target_session" -p 2>/dev/null | tail -5)
    if echo "$screen" | grep -q '❯'; then
      tmux send-keys -t "$target_session" -l "$message"
      tmux send-keys -t "$target_session" Enter
      return 0
    fi
  done

  # 超时，写 inbox 兜底
  if [[ -n "$target_team" ]]; then
    local inbox="$REGISTRY_DIR/team-$target_team/inbox.jsonl"
    if [[ -d "$(dirname "$inbox")" ]]; then
      python3 -c "
import json, uuid
from datetime import datetime
msg = {
    'id': f'msg-{uuid.uuid4().hex[:8]}',
    'ts': datetime.now().isoformat(),
    'from': '联合指挥',
    'to': '$target_team',
    'type': 'notify',
    'priority': 'urgent',
    'payload': {
        'event': 'pending_mission',
        'message': '''$message'''
    }
}
with open('$inbox', 'a') as f:
    f.write(json.dumps(msg, ensure_ascii=False) + '\n')
" 2>/dev/null
      echo "  ⚠ $target_team 正忙，任务已写入 inbox 等待读取" >&2
      return 0
    fi
  fi

  echo "  ⚠ $target_session 无法投递" >&2
  return 1
}

# ── 生成 team ID ──
_gen_id() {
  echo "team-$(date +%H%M%S)-$$"
}

# ── 注册 team ──
_register_team() {
  local id="$1"
  local task="${2:-待分配}"
  local now=$(date '+%Y-%m-%d %H:%M:%S')

  python3 -c "
import json, sys, fcntl

path = '$REGISTRY'
with open(path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    data['teams'].append({
        'id': '$id',
        'task': '''$task''',
        'status': 'active',
        'files': [],
        'started': '$now',
        'window': 'w-$id'
    })
    f.seek(0)
    f.truncate()
    json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
"
}

# ── 检查 Commander 心跳 ──
_commander_alive() {
  # 方法1: PID 存活检查
  if [[ -f "$COMMANDER_PID_FILE" ]]; then
    local pid
    pid=$(cat "$COMMANDER_PID_FILE" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      # 方法2: 心跳文件新鲜度检查
      if [[ -f "$COMMANDER_HEARTBEAT_FILE" ]]; then
        local age
        age=$(python3 -c "
from datetime import datetime
import json
try:
    with open('$COMMANDER_HEARTBEAT_FILE') as f:
        hb = json.load(f)
    ts = datetime.fromisoformat(hb['ts'])
    print(int((datetime.now() - ts).total_seconds()))
except:
    print(999)
" 2>/dev/null)
        if [[ "$age" -lt "$HEARTBEAT_MAX_AGE" ]]; then
          return 0  # 存活且心跳正常
        fi
        echo "Commander PID $pid 存活但心跳过期 (${age}s)，将重启" >&2
      else
        return 0  # 无心跳文件但 PID 存活，视为正常（兼容）
      fi
    fi
  fi
  return 1  # 死亡
}

# ── 启动 Commander 守护进程（幂等 + 心跳自愈）──
_start_commander() {
  if _commander_alive; then
    return 0
  fi

  local COMMANDER_SCRIPT
  if ! COMMANDER_SCRIPT="$(_legion_commander_script)"; then
    echo "错误: Commander 脚本不存在（已查 scripts/ 与 ~/.claude/scripts/）" >&2
    return 1
  fi

  # 清理可能存在的僵尸 commander window
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    if tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -q '^commander$'; then
      tmux kill-window -t "$SESSION:commander" 2>/dev/null || true
      sleep 0.3
    fi
  fi

  # 启动
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" -n "commander"
  else
    tmux new-window -t "$SESSION:" -n "commander" -c "$PROJECT_DIR"
  fi
  tmux send-keys -t "$SESSION:commander" "LEGION_DIR=$REGISTRY_DIR python3 $COMMANDER_SCRIPT" Enter

  # 等待启动并记录 PID
  sleep 1.5
  local cmd_pid py_pid
  cmd_pid=$(tmux list-panes -t "$SESSION:commander" -F '#{pane_pid}' 2>/dev/null | head -1)
  py_pid=$(pgrep -P "$cmd_pid" python3 2>/dev/null | head -1 || echo "")
  if [[ -n "$py_pid" ]]; then
    echo "$py_pid" > "$COMMANDER_PID_FILE"
  else
    echo "$cmd_pid" > "$COMMANDER_PID_FILE"
  fi

  echo "Commander 守护进程已启动 (PID: $(cat $COMMANDER_PID_FILE))"
}

# ── 动态安装 hooks 到 settings.json ──
_install_hooks() {
  SETTINGS_FILE="$SETTINGS_FILE" HOOKS_DIR="$HOOKS_DIR" python3 <<'PY' 2>/dev/null
import json
import os
import shutil
import tempfile
import time

settings_path = os.environ['SETTINGS_FILE']
hooks_dir = os.environ['HOOKS_DIR']

required_hooks = {
    'PostToolUse': {
        'matcher': '',
        'hook': {'type': 'command', 'command': f'bash {hooks_dir}/post-tool-use.sh'},
    },
    'PreToolUse': {
        'matcher': 'Edit|Write|Bash',
        'hook': {'type': 'command', 'command': f'bash {hooks_dir}/pre-tool-use.sh'},
    },
    'Stop': {
        'matcher': '',
        'hook': {'type': 'command', 'command': f'bash {hooks_dir}/stop-hook.sh'},
    },
}

os.makedirs(os.path.dirname(settings_path), exist_ok=True)

if os.path.exists(settings_path):
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        if not isinstance(settings, dict):
            raise ValueError('settings root must be an object')
    except Exception:
        backup_path = f"{settings_path}.broken.{int(time.time())}"
        shutil.copy2(settings_path, backup_path)
        settings = {}
else:
    settings = {}

hooks = settings.get('hooks')
if not isinstance(hooks, dict):
    if hooks is not None:
        settings['_legion_preserved_hooks'] = hooks
    hooks = {}
    settings['hooks'] = hooks

changed = False

for event, required in required_hooks.items():
    matcher = required['matcher']
    hook = required['hook']
    entries = hooks.get(event)
    if not isinstance(entries, list):
        if entries is not None:
            settings.setdefault('_legion_preserved_invalid_hooks', {})[event] = entries
        entries = []
        hooks[event] = entries
        changed = True

    already_installed = False
    matcher_entry = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_matcher = entry.get('matcher', '')
        existing_hooks = entry.get('hooks')
        if not isinstance(existing_hooks, list):
            if entry_matcher == matcher:
                settings.setdefault('_legion_preserved_invalid_hook_entries', {}).setdefault(event, []).append({
                    'matcher': entry_matcher,
                    'hooks': existing_hooks,
                })
                entry['hooks'] = []
                existing_hooks = entry['hooks']
                changed = True
            else:
                continue
        if entry_matcher == matcher and matcher_entry is None:
            matcher_entry = entry
        for existing_hook in existing_hooks:
            if (
                isinstance(existing_hook, dict)
                and entry_matcher == matcher
                and existing_hook.get('type') == hook['type']
                and existing_hook.get('command') == hook['command']
            ):
                already_installed = True
                break
        if already_installed:
            break

    if already_installed:
        continue

    if matcher_entry is not None:
        existing_hooks = matcher_entry.get('hooks')
        if not isinstance(existing_hooks, list):
            matcher_entry['hooks'] = []
            existing_hooks = matcher_entry['hooks']
        existing_hooks.append(hook)
    else:
        entries.append({'matcher': matcher, 'hooks': [hook]})
    changed = True

if changed or not os.path.exists(settings_path):
    fd, tmp_path = tempfile.mkstemp(
        prefix='.settings.',
        suffix='.json',
        dir=os.path.dirname(settings_path),
        text=True,
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp_path, settings_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    print('Hooks 已合并到 settings.json')
else:
    print('Hooks 已存在，无需更新')
PY
}

# ── 卸载 hooks ──
_uninstall_hooks() {
  python3 -c "
import json

settings_path = '$SETTINGS_FILE'
with open(settings_path) as f:
    settings = json.load(f)

if 'hooks' in settings:
    del settings['hooks']
    with open(settings_path, 'w') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('Hooks 已从 settings.json 卸载')
else:
    print('Hooks 未安装，无需卸载')
" 2>/dev/null
}

# ── 初始化指挥官通信通道（支持多指挥官）──
# 用法: _init_commander [name]
#   _init_commander        → 初始化默认 L1
#   _init_commander test   → 初始化 L1-test
_init_commander() {
  local cmd_name="${1:-}"
  local cmd_id="L1"
  local cmd_label="1级指挥官 — 统御全局"
  if [[ -n "$cmd_name" ]]; then
    cmd_id="L1-${cmd_name}"
    cmd_label="1级指挥官 [${cmd_name}]"
  fi

  local cmd_dir="$REGISTRY_DIR/team-$cmd_id"
  mkdir -p "$cmd_dir"
  touch "$cmd_dir/inbox.jsonl" "$cmd_dir/outbox.jsonl"
  # cursor 初始化为当前末尾（跳过历史消息，只看新消息）
  if [[ ! -f "$cmd_dir/inbox.cursor" ]]; then
    wc -l < "$cmd_dir/inbox.jsonl" | tr -d ' ' > "$cmd_dir/inbox.cursor"
  fi
  if [[ ! -f "$cmd_dir/outbox.cursor" ]]; then
    wc -l < "$cmd_dir/outbox.jsonl" | tr -d ' ' > "$cmd_dir/outbox.cursor"
  fi
  if [[ ! -f "$cmd_dir/broadcast.cursor" ]]; then
    local bc_file="$REGISTRY_DIR/broadcast.jsonl"
    [[ -f "$bc_file" ]] && wc -l < "$bc_file" | tr -d ' ' > "$cmd_dir/broadcast.cursor" || echo "0" > "$cmd_dir/broadcast.cursor"
  fi

  # 注册指挥官到注册表（幂等）
  local cmd_now
  cmd_now=$(date '+%Y-%m-%d %H:%M:%S')
  python3 -c "
import json, fcntl
path = '$REGISTRY'
with open(path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    if not any(t['id'] == '$cmd_id' for t in data['teams']):
        data['teams'].insert(0, {
            'id': '$cmd_id',
            'task': '$cmd_label',
            'status': 'commanding',
            'role': 'commander',
            'files': [],
            'started': '$cmd_now',
            'window': '$cmd_id'
        })
        f.seek(0); f.truncate()
        json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
" 2>/dev/null
}

# 兼容旧调用
_init_l1() {
  _init_commander ""
}

# ── 为 team 创建通信目录 ──
_init_team_comms() {
  local team_id="$1"
  local team_dir="$REGISTRY_DIR/team-$team_id"
  mkdir -p "$team_dir"
  # 旧系统（向后兼容）
  touch "$team_dir/inbox.jsonl"
  touch "$team_dir/outbox.jsonl"
  wc -l < "$team_dir/inbox.jsonl" | tr -d ' ' > "$team_dir/inbox.cursor"
  wc -l < "$team_dir/outbox.jsonl" | tr -d ' ' > "$team_dir/outbox.cursor"
  local bc_file="$REGISTRY_DIR/broadcast.jsonl"
  [[ -f "$bc_file" ]] && wc -l < "$bc_file" | tr -d ' ' > "$team_dir/broadcast.cursor" || echo "0" > "$team_dir/broadcast.cursor"
  # 新邮箱系统：创建 inboxes 目录 + 初始化自身 inbox
  mkdir -p "$team_dir/inboxes"
  [[ ! -f "$team_dir/inboxes/${team_id}.json" ]] && echo '[]' > "$team_dir/inboxes/${team_id}.json"
}

# ── 查找后台运行但未显示的 L1 指挥官（轮询，每次返回下一个）──
_find_background_l1() {
  local cursor_file="$REGISTRY_DIR/l1-attach-cursor.txt"
  local last_attached=""
  [[ -f "$cursor_file" ]] && last_attached=$(cat "$cursor_file")

  python3 -c "
import json, subprocess, sys

registry_path = '$REGISTRY'
project_hash = '$PROJECT_HASH'
last_attached = '$last_attached'

try:
    with open(registry_path) as f:
        data = json.load(f)
except:
    sys.exit(0)

# 收集所有在后台运行的 L1 指挥官（tmux session 存在 + claude 在运行）
active = []
for t in data.get('teams', []):
    if not t['id'].startswith('L1-') or t.get('role') != 'commander':
        continue
    cmd_id = t['id']
    session_name = f'legion-{project_hash}-{cmd_id}'

    # Check if tmux session exists
    sess_check = subprocess.run(
        ['tmux', 'has-session', '-t', session_name],
        capture_output=True, timeout=2
    )
    if sess_check.returncode != 0:
        continue  # session 不存在，跳过

    # Check if claude is running (not just idle shell)
    pane_check = subprocess.run(
        ['tmux', 'list-panes', '-t', session_name, '-F', '#{pane_current_command}'],
        capture_output=True, text=True, timeout=2
    )
    current_cmd = pane_check.stdout.strip().split('\n')[0] if pane_check.stdout.strip() else ''
    if current_cmd in ('zsh', 'bash', 'sh', 'login', ''):
        continue  # claude 未运行，跳过

    # Check if session already has a client attached (already displayed)
    client_check = subprocess.run(
        ['tmux', 'list-clients', '-t', session_name],
        capture_output=True, text=True, timeout=2
    )
    if client_check.stdout.strip():
        continue  # 已有窗口显示，跳过

    active.append(cmd_id)

if not active:
    sys.exit(0)

# 轮询：找 last_attached 之后的下一个
if last_attached in active:
    idx = active.index(last_attached)
    # 返回下一个（循环）
    next_idx = (idx + 1) % len(active)
    print(active[next_idx])
else:
    # last_attached 不在列表中，返回第一个
    print(active[0])
" 2>/dev/null
}

# ── 生成新的 L1 代号 ──
_gen_l1_name() {
  python3 -c "
import json, random
codenames = [
    '烈焰','雷霆','苍穹','银河','极光','深渊','星辰','暴风','磐石','幻影',
    '猎鹰','黑曜','赤龙','玄武','白虎','朱雀','青龙','麒麟','鲲鹏','凤凰',
    '破晓','长歌','惊雷','飞雪','烽火','天狼','北斗','昆仑','沧海','九霄',
]
try:
    with open('$REGISTRY') as f:
        data = json.load(f)
    used = {t['id'].replace('L1-','').replace('军团','') for t in data.get('teams', []) if t['id'].startswith('L1-')}
    available = [n for n in codenames if n not in used]
    name = random.choice(available) if available else f'第{len(used)+1}'
    print(name + '军团')
except:
    print(random.choice(codenames) + '军团')
" 2>/dev/null
}

# ── 刷新所有 L1 指挥官的注册表状态（对齐 tmux 实际状态）──
_refresh_l1_registry() {
  python3 -c "
import json, subprocess, fcntl

registry_path = '$REGISTRY'
project_hash = '$PROJECT_HASH'
changed = False

with open(registry_path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)

    for t in data.get('teams', []):
        if not t['id'].startswith('L1-') or t.get('role') != 'commander':
            continue
        cmd_id = t['id']
        session_name = f'legion-{project_hash}-{cmd_id}'

        # 检查 tmux session 是否存在
        sess = subprocess.run(['tmux', 'has-session', '-t', session_name],
                              capture_output=True, timeout=2)
        if sess.returncode != 0:
            # session 不存在 → 标记 completed
            if t.get('status') != 'completed':
                t['status'] = 'completed'
                t['exit_reason'] = 'tmux_session_dead'
                changed = True
            continue

        # session 存在，检查 claude 是否在运行
        pane = subprocess.run(
            ['tmux', 'list-panes', '-t', session_name, '-F', '#{pane_current_command}'],
            capture_output=True, text=True, timeout=2)
        cmd = pane.stdout.strip().split('\n')[0] if pane.stdout.strip() else ''
        if cmd in ('zsh', 'bash', 'sh', 'login', ''):
            # shell 空闲，claude 未运行
            if t.get('status') != 'completed':
                t['status'] = 'completed'
                t['exit_reason'] = 'claude_exited'
                changed = True
        else:
            # claude 正在运行 → 标记 commanding
            if t.get('status') != 'commanding':
                t['status'] = 'commanding'
                t.pop('exit_reason', None)
                t.pop('completed', None)
                changed = True

    if changed:
        f.seek(0); f.truncate()
        json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
" 2>/dev/null
}

# ── 写入 L1 指挥官 prompt 文件 ──
_write_l1_prompt() {
  local cmd_id="$1"
  local cmd_session="$2"
  local prompt_file="$REGISTRY_DIR/prompt-${cmd_id}.txt"

  cat > "$prompt_file" << L1PROMPT
你是 ${cmd_id} — 军团1级指挥官。

## 身份
- Team ID: ${cmd_id}，tmux session: "${cmd_session}"
- 你创建的 teammate 自动出现在 tmux pane 中（用户可见）
- 你部署的 L2 team 在你的 session 内以独立 window 出现

## 思维模式（三步深挖法，所有需求先过一遍）

接到需求后，默认用三步法快速过一遍（30 秒内心默念，不一定要问用户）：
1. **苏格拉底追问** — 用户说的是真需求吗？背后的动机是什么？
2. **第一性原理** — 抛开习惯做法，基于基本事实的最优解是什么？
3. **奥卡姆剃刀** — 砍掉非必要复杂度，最小可执行方案是什么？

复杂/创意类需求 → 读 .claude/skills/brainstorming/SKILL.md 执行完整三步深挖流程。
简单/明确需求 → 心里过一遍即可，直接执行。

## 指挥中心参谋部（智囊团/圆桌会议）

遇到下列场景，主动召唤 \`roundtable\` skill（触发词：\`圆桌会议\` / \`智囊团\` / \`roundtable\` / \`debate\` / \`braintrust\`）——古今人物多视角碰撞辅助决策：

- **战略性决策**：架构路线二选一、技术栈重选、产品方向分叉、关键 API 设计
- **开放性争议**：用户需求存在多种合理解释且成本都不低
- **高风险岔路口**：走错需大成本返工（命中例外4）时先开圆桌
- **跨域方案评审**：涉及 2+ 领域且内部成员视角单一

brainstorming vs roundtable 分工：
- brainstorming → **个人**深度思考（三步深挖 + 用户对话细化需求）
- roundtable → **多人**视角碰撞（不同真实人物思维框架对撕同一问题）

原则：不替代 recon，不替代审计；只在决策需要多元视角互博时启动。快速决策别开圆桌（成本高）。

## 核心规则（5条，条条必须遵守）

1. **新需求必须先侦察** → 创建参谋 teammate，让它读 .claude/skills/recon/SKILL.md 执行 /recon 流程。例外：纯bug修复、纯配置、用户说跳过。
2. **所有并行工作必须可见** → 用 TeamCreate（不是 Agent），禁止 run_in_background。
3. **中型+任务用 Spec 驱动** → 优先读 .claude/thought-weapons/spec-driven/SKILL.md（本项目若有），否则读 ~/.claude/skills/spec-driven/SKILL.md（全局），维护 .planning/ 目录。
4. **完成前必须审计** → 读 .claude/skills/audit/SKILL.md，两阶段审计全过才算完成。
5. **降级必须有理由** → 优先读 .claude/thought-weapons/degradation-policy/SKILL.md（本项目若有），否则读 ~/.claude/skills/degradation-policy/SKILL.md（全局），影响核心目标则不可降级。

## 多指挥官协同

**启动时：** 读 ${REGISTRY_DIR}/registry.json 和 locks.json，向所有在线指挥官通报你的存在。
**开始任务前：** 检查文件锁和其他军团作业范围，发送任务通报，等 10 秒后检查 inbox。
**收到消息时：** 3 次工具调用内必须 ACK 回复。不回复 = 协同失败。

发消息（新邮箱系统 — 带文件锁、结构化、自动投递）：
\`\`\`bash
# 方式1: 使用邮箱工具库（推荐）
source ~/.claude/scripts/legion-mailbox.sh 2>/dev/null
mailbox_send "${cmd_id}" "目标ID" "text" "消息内容" "5字摘要"

# 方式2: 直接写入目标 inbox JSON（带 flock）
python3 -c "
import json, fcntl, time
inbox = '${REGISTRY_DIR}/team-目标ID/inboxes/目标ID.json'
lock = inbox + '.lock'
open(lock, 'a').close()
with open(lock) as lf:
    fcntl.flock(lf, fcntl.LOCK_EX)
    try:
        msgs = json.load(open(inbox))
    except: msgs = []
    msgs.append({'id': f'msg-{int(time.time())}', 'from': '${cmd_id}', 'to': '目标ID', 'type': 'text', 'payload': '消息内容', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ'), 'read': False, 'summary': '摘要'})
    json.dump(msgs, open(inbox, 'w'), ensure_ascii=False, indent=2)
    fcntl.flock(lf, fcntl.LOCK_UN)
"

# 广播给所有在线指挥官
mailbox_broadcast "${cmd_id}" "coordination" "内容" "摘要"
\`\`\`

消息类型: text(普通) | report(汇报) | shutdown(关闭) | gate(审批) | ack(确认) | coordination(协调) | lock(文件锁)

## 可视化规则
- 并行子任务 → TeamCreate 创建 teammate（禁止 Agent 工具、禁止 run_in_background）
- 大规模协作 → \`legion.sh campaign --commander ${cmd_id} 'JSON'\`
- 原则：tmux 窗口数 = 并行工作成员数

## 军团命令
- \`~/.claude/scripts/legion.sh campaign --commander ${cmd_id} 'JSON'\` — 部署战役
- \`~/.claude/scripts/legion.sh joint "目标"\` — 联合指挥（大规模跨域任务）
- \`~/.claude/scripts/legion.sh sitrep\` — 综合态势
- \`~/.claude/scripts/legion.sh inbox ${cmd_id}\` — 查看汇报
- \`~/.claude/scripts/legion.sh msg TEAM "内容"\` — 下达指令
- \`~/.claude/scripts/legion.sh gate TEAM block/approve\` — 审批门
- \`~/.claude/scripts/legion.sh status\` / \`locks\` / \`health\` / \`kill-all\`

## 自治循环模式（Anthropic Harness Engineering）

用户说"自治模式"、"循环完成"、"自动做"、"去睡觉"时 → 切换到自治循环。

**快捷命令：**
- \`~/.claude/scripts/legion.sh auto plan "需求"\` — 规划
- \`~/.claude/scripts/legion.sh auto run\` — 前台执行
- \`~/.claude/scripts/legion.sh auto bg "需求"\` — **一键后台**（规划+执行，去睡觉模式）
- \`~/.claude/scripts/legion.sh auto status\` — 查看进度
- \`~/.claude/scripts/legion.sh auto resume\` — 断点续跑
- \`~/.claude/scripts/legion.sh auto stop\` — 停止

**军团模式 vs 自治模式选择：**

| 场景 | 模式 |
|------|------|
| 需要人工决策/讨论/创意 | 军团模式（有人值守） |
| 需求明确、可拆分、功能开发 | **自治循环**（无人值守） |
| 用户说"帮我做完我去睡了" | **\`legion.sh auto bg "需求"\`** |
| 跨域复杂架构/设计 | 军团模式 |

原理：每个功能独立 \`claude -p\`（天然上下文重置），失败自动 git revert + 重试，最多 3 次后跳过。

## 执行纪律（按复杂度分级，强制）

| 复杂度 | 判断标准 | 侦察 | 团队 | 验证 |
|--------|---------|------|------|------|
| **S 级** | 单文件 bug/配置/查询 | 跳过 | 跳过 | cargo check / tsc 即可 |
| **M 级** | 2~5 文件、单域 | 1 路参谋 | 1-2 实现者 + 1 审查者 | 1 人（合规+红队合一） |
| **L 级** | 跨域、5+ 文件 | **2 路参谋** | **流水线 + 交叉审查** | **2 人**（合规 + 红队） |
| **XL 级** | 10+ 文件、架构变更 | **3 路参谋** | **最大规模流水线 + worktree 隔离** | **3 人**（合规+红队+集成） |

**铁律：** 判错复杂度往高走不往低走。M 级及以上必须组建团队（读 .claude/skills/agent-team/SKILL.md）。
**流水线制：** 实现者全速推进→完成即刻触发审查→汇总反馈一轮修复→最终验证。指挥官确认无害时可自主放行。
**全员 opus：** 创建 teammate 时必须 model: "opus"，禁止降级。
**数据驱动：** 每个任务完成后写 .planning/metrics.json，用数据验证规模↔质量假设。

## 思考深度配置（effort level）

你自己是 max（启动参数已设置）。创建 teammate 时在 prompt 开头加：
- **参谋** → \`首先执行：/effort max\`
- **审查者** → \`首先执行：/effort max\`
- **审计者** → \`首先执行：/effort max\`
- **实现者** → \`首先执行：/effort high\`

## 工作流程
1. **接收需求** → 判断复杂度
2. **侦察** → 创建参谋 teammate 执行 /recon（M级+强制）
3. **⚡再评估复杂度** → 侦察完成后必须重新判断，只能升不能降
4. **方案** → 中型+任务走 /spec-driven，写 .planning/
5. **分支隔离** → 中型+任务 \`git worktree add\`，小任务直接 main
6. **部署流水线团队** → TeamCreate，读 .claude/skills/agent-team/SKILL.md
7. **监控** → sitrep/inbox，指挥官确认无害可自主放行
8. **审计** → /audit 对抗性验证，全过才完成
9. **收尾** → 写 .planning/metrics.json → merge worktree → 汇总结果给用户

## 技能分配
创建 teammate 前先查 \`ls .claude/skills/*/SKILL.md\`，有现成技能的优先分配。
也查全局战法库 \`~/.claude/memory/tactics/\`。

## 情报响应
收到 intel-hub 推送时，下次回复用户时带上情报摘要。相关度 >= 8 则建议调整方案。

## 联合指挥
大规模跨域任务 → \`legion.sh joint "目标"\`。发起后指挥权移交联合指挥官。
收到 joint_command_mission → 最高优先级执行，完成后向联合指挥汇报。

## 上下文保鲜（Anthropic + Manus 最佳实践）

**核心原则：上下文窗口是临时工作区，.planning/ 和 STATE.md 才是持久记忆。**

### 上下文重置策略

| 场景 | 策略 |
|------|------|
| 阶段切换（侦察→实现→审计） | 创建新 teammate 接棒（天然上下文重置），通过 .planning/ 传递需求和决策 |
| teammate 长时运行 200+ 调用 | 让它写 STATE.md 后退出，新 teammate 读 STATE.md 接续 |
| 同一 agent 内切换任务 | /compact 压缩（次优），压缩前确保关键信息已写入文件 |
| 对话超 50% 上下文 | 必须行动：/compact 或创建新 teammate 接棒 |

### 大工具输出压缩（Manus：输入输出比 100:1，工具输出吃掉绝大部分上下文）

工具返回大量内容时，**先压缩再使用，不要把原始输出留在上下文里**：
- \`grep\` 返回 100+ 行 → 先 \`| wc -l\` 数数量，再 \`| head -20\` 看前几行
- \`ls\` 返回 50+ 文件 → 先 \`| wc -l\` 统计，再 \`| grep 关键词\` 过滤
- 大文件读取 → 用 \`Read\` 的 offset/limit 分段读，不要一次读完
- 长命令输出 → 写入临时文件（\`> /tmp/result.txt\`），上下文只保留文件路径

### 保留错误轨迹（Manus：失败操作不要删）

失败的操作帮模型更新对工具行为的认知，避免重复犯错。
- 命令报错 → 保留错误信息在上下文中
- 不要因为"上下文太长"就删掉错误记录
- teammate 接棒时，STATE.md 中也记录失败的尝试和原因

**禁止：** 让单个 teammate 硬撑到上下文耗尽。宁可多建 teammate，不可冒上下文焦虑的风险。
L1PROMPT
}

# ── 写入系统提示 ──
_write_system_prompt() {
  cat > "$SYSTEM_PROMPT_FILE" << 'SYSPROMPT'
你已进入军团协同模式（实时通信版）。你是 **2级指挥官**。

## 指挥链
```
MY_COMMANDER_ID（1级指挥官）→ 你（MY_TEAM_ID，2级指挥官）→ 你的 teammate（执行成员）
```
MY_COMMANDER_ID 是你的直属指挥官，你向 MY_COMMANDER_ID 汇报。

## 启动步骤
1. 阅读 MY_LEGION_DIR/registry.json 了解其他 team 和自己的任务
2. 按 Ralph Loop 流程执行分配给你的任务

## Ralph Loop 流程（Start vague. Loop until perfect.）
1. 理解任务目标 → 快速实现第一版
2. 自检：编译通过？类型正确？逻辑合理？（cargo check / tsc --noEmit）
3. 不通过 → 修复 → 回到第2步
4. 通过 → 向 MY_COMMANDER_ID 汇报完成
5. 收到反馈不满意 → 改进 → 回到第2步
6. 最终确认 → <done>COMPLETE</done>

原则：小步快跑，每轮验证，失败先分析再修，不盲目重试。
注意：你是2级执行者，不需要和用户交互（AskUserQuestion），直接执行。有疑问向 MY_COMMANDER_ID 发消息。

## 军团协同协议（强制）

你的 Team ID: MY_TEAM_ID
环境变量 CLAUDE_LEGION_TEAM_ID 已设置。

### 向指挥官汇报（强制 — 使用新邮箱系统）
你**必须**在以下时刻向 MY_COMMANDER_ID 汇报：
1. **任务开始时** — 汇报你的执行计划和文件范围
2. **关键进展** — 完成重要子任务、遇到阻塞、需要决策时
3. **任务完成时** — 汇报修改摘要、质量检查结果

汇报命令（新邮箱系统 — 带文件锁，结构化协议）：
```bash
# 进度汇报
source ~/.claude/scripts/legion-mailbox.sh 2>/dev/null
mailbox_send "MY_TEAM_ID" "MY_COMMANDER_ID" "report" "进度: 已完成XX，正在YY" "进度汇报"

# 任务完成汇报
mailbox_send "MY_TEAM_ID" "MY_COMMANDER_ID" "report" "完成: 修改了XX文件，cargo check PASS" "任务完成"
```

旧格式兼容（过渡期仍可使用）：
```bash
echo '{"to":"MY_COMMANDER_ID","type":"notify","priority":"normal","payload":{"event":"progress","status":"状态","detail":"详细说明"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl
```

### 军团作战原则（最高优先级）
**不计成本，规模化协作优先，通过数量换取最大化的效率和质量。**

- 遇到可拆分的子任务 → 立即用 Agent 工具创建 teammate 并行处理
- 收到其他 team 的修改请求 → 不要自己顺手改，立即创建新 teammate 专门处理
- 资源从不是瓶颈，速度和质量是唯一指标

### 环境变量继承（强制，最重要的规则）
你的环境变量 `CLAUDE_LEGION_TEAM_ID=MY_TEAM_ID` 已设置。
**你创建的任何 teammate / Agent，都必须在 prompt 最开头包含以下环境声明块（原样复制）：**

```
【军团协同环境 — 必须遵守】
你是 team MY_TEAM_ID 的成员。以下规则强制执行：

1. 每次使用 Bash 工具时，命令前加 export CLAUDE_LEGION_TEAM_ID="MY_TEAM_ID" &&
   示例: export CLAUDE_LEGION_TEAM_ID="MY_TEAM_ID" && cargo check
   这让文件锁和消息 hook 对你生效。

2. 通信方式 — 给其他 team 发消息：
   export CLAUDE_LEGION_TEAM_ID="MY_TEAM_ID" && echo '{"to":"TARGET","type":"notify","payload":{"message":"内容"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl

3. 完成任务后必须通知分配者。
```

为什么必须这样做：
- 没有 `CLAUDE_LEGION_TEAM_ID` → hooks 不生效 → teammate 可以绕过文件锁随意编辑 → 和其他 team 产生冲突
- 共享同一个 outbox → teammate 发的消息通过你的通道路由 → Commander 能正确投递

### 实时通信系统
Hooks 已自动配置，你拥有以下能力：
- **自动收消息**: 每次工具调用后，hook 自动检查收件箱，新消息会注入你的上下文
- **文件锁强制**: 编辑被其他 team 锁定的文件会被自动阻止，并自动向锁持有者发送扩编请求
- **紧急消息**: 停止前会检查是否有未读紧急消息
- **teammate 自动继承**: 你创建的 teammate 共享你的 Team ID，hooks 对他们同样生效

### 发送消息（新邮箱系统 — 推荐）
```bash
source ~/.claude/scripts/legion-mailbox.sh 2>/dev/null
# 普通消息
mailbox_send "MY_TEAM_ID" "TARGET_TEAM_ID" "text" "消息内容" "5字摘要"
# 汇报
mailbox_send "MY_TEAM_ID" "MY_COMMANDER_ID" "report" "汇报内容" "汇报摘要"
# 确认收到
mailbox_send "MY_TEAM_ID" "TARGET_TEAM_ID" "ack" "已收到并处理" "ACK"
# 广播
mailbox_broadcast "MY_TEAM_ID" "coordination" "通知全军" "广播摘要"
```

旧格式兼容（过渡期）：
```bash
echo '{"to":"TARGET_TEAM_ID","type":"notify","priority":"normal","payload":{"event":"描述","detail":"内容"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl
```

### 请求文件锁
修改文件前，先请求锁：
```bash
echo '{"to":"commander","type":"lock_request","payload":{"file":"要锁定的文件路径","reason":"原因"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl
```

### 释放文件锁
完成修改后释放锁：
```bash
echo '{"to":"commander","type":"lock_release","payload":{"file":"要释放的文件路径"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl
```

### 更新任务板
```bash
# 创建任务
echo '{"to":"commander","type":"task_update","payload":{"action":"create","title":"任务描述","assignee":"MY_TEAM_ID"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl

# 完成任务
echo '{"to":"commander","type":"task_update","payload":{"action":"complete","task_id":"task-xxx"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl
```

### 广播消息
```bash
echo '{"to":"all","type":"notify","priority":"normal","payload":{"event":"通知内容"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl
```

### 自动心跳（无需你操作）
PostToolUse hook 每 10 次工具调用自动向 MY_COMMANDER_ID 发送心跳，包含你的工具调用次数和当前修改的文件。
MY_COMMANDER_ID 通过这些心跳实时掌握你的进度。你不需要做任何事情。

### 审批门
MY_COMMANDER_ID 可以随时暂停你的写操作（gate block）。如果你的 Edit/Write/Bash 被审批门阻止：
- 你会收到 `gate_blocked` 消息说明原因
- 你可以继续读代码、分析、做准备，但不能修改文件
- 等 MY_COMMANDER_ID 发送 `gate_approved` 后自动恢复

### 依赖等待协议
如果你的任务描述中包含"前置依赖"，你**必须**：
1. 先读代码、做准备工作（不修改文件）
2. 等待依赖方发送 `mission_complete` 消息（会自动注入你的上下文）
3. 收到后再开始修改文件
4. 如果等待超过 5 分钟没收到，发消息询问依赖方状态

### 注意事项
- Commander 每 0.5s 轮询一次 outbox，消息几乎实时送达
- 锁有 30 分钟过期时间，完成后请主动释放
- priority 可选: normal, urgent, critical（紧急消息会阻止对方停止）

### 任务开始时
调用以下命令注册自己的任务和文件范围：
```bash
python3 -c "
import json, fcntl
path = 'MY_LEGION_DIR/registry.json'
with open(path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    for t in data['teams']:
        if t['id'] == 'MY_TEAM_ID':
            t['task'] = '实际任务描述'
            t['files'] = ['file1.ts', 'file2.rs']
            t['status'] = 'working'
    f.seek(0); f.truncate()
    json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
"
```

### 收到 spawn_teammate_for_edit 请求时（强制）
当你收到 `spawn_teammate_for_edit` 类型的消息时，你**必须**：
1. 立即用 Agent 工具创建一个新 teammate（设 run_in_background: true）
2. 在 prompt 中包含完整的军团环境声明块 + 任务描述
3. 你自己继续做原来的工作，不要暂停

teammate prompt 模板（直接复制，替换 {file}、{edit_description}、{requester}）：
```
【军团协同环境 — 必须遵守】
你是 team MY_TEAM_ID 的成员。以下规则强制执行：
1. 每次使用 Bash 工具时，命令前加 export CLAUDE_LEGION_TEAM_ID="MY_TEAM_ID" &&
2. 通信 outbox: MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl

任务：修改文件 {file}
修改内容：{edit_description}
请求者：{requester}

步骤：
1. 读取文件，理解上下文
2. 执行修改（Edit 工具会自动经过文件锁检查）
3. 完成后通知请求者：
export CLAUDE_LEGION_TEAM_ID="MY_TEAM_ID" && echo '{"to":"{requester}","type":"ack","priority":"normal","payload":{"event":"edit_done","file":"{file}","detail":"简述修改内容"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl
```

### 执行中
- 修改文件前先请求锁，完成后释放
- 如果编辑被阻止，hook 会自动向锁持有者发送扩编请求，你继续做其他工作
- 任何可拆分的子任务都应创建 teammate 并行处理，不计成本

### 上下文节约（Manus 最佳实践：工具输出吃掉 99% 上下文）
- `grep` 大量匹配 → 先 `| wc -l` 统计，再 `| head -20` 看前几行，不要把全部结果留在上下文
- `ls` 文件多 → `| wc -l` 统计 + `| grep 关键词` 过滤
- 大文件 → Read 用 offset/limit 分段读
- 长输出 → 写入 `/tmp/result.txt`，上下文只留路径
- 失败的操作不要删 → 错误记录帮你避免重蹈覆辙

### 自修复循环（Claude Agent SDK：验证失败必须修复，不能忽略）
收到 Quality Gate 失败警报（🔴 标记）时，**必须立即修复再继续，不能跳过**：
1. 读取错误信息，分析原因
2. 修复代码
3. 手动运行验证命令确认通过（`cargo check` / `tsc --noEmit` / `python3 -m py_compile`）
4. 通过后才能继续下一步
如果 3 次修复仍不通过 → SendMessage 向指挥官汇报，请求协助，不要死循环。

### 任务完成时（四步，缺一不可）
```bash
# 0. 自动序列化进度（Schema 化 JSON，Manus 最佳实践）
# 结构化摘要比自由文本可靠：字段固定，不会遗漏关键信息
if [ -d .planning ]; then
  python3 -c "
import json
from datetime import datetime
state = {
    'snapshot_by': 'MY_TEAM_ID',
    'timestamp': datetime.now().isoformat(),
    'completed': [
        # {'file': '文件路径', 'change': '做了什么'}
    ],
    'pending': [
        # {'task': '任务描述', 'reason': '为什么没做'}
    ],
    'failed_attempts': [
        # {'action': '尝试了什么', 'error': '失败原因'} — 保留错误轨迹
    ],
    'verification': {
        'stack_verify': 'PASS/FAIL',
        'details': ''
    }
}
with open('.planning/STATE.json', 'w') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
"
fi

# 1. 向指挥官汇报完成
echo '{"to":"MY_COMMANDER_ID","type":"notify","priority":"urgent","payload":{"event":"mission_complete","summary":"修改摘要","files_changed":["改了哪些文件"],"quality":"编译/类型检查结果"}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl

# 2. 释放所有锁
echo '{"to":"commander","type":"lock_release","payload":{"file":""}}' >> MY_LEGION_DIR/team-MY_TEAM_ID/outbox.jsonl

# 3. 更新注册表
python3 -c "
import json, fcntl
path = 'MY_LEGION_DIR/registry.json'
with open(path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    for t in data['teams']:
        if t['id'] == 'MY_TEAM_ID':
            t['status'] = 'completed'
            t['files'] = []
    f.seek(0); f.truncate()
    json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
"
```
SYSPROMPT
}

_gate_bridge_mixed() {
  local gate_action="$1"
  local gate_target="$2"
  local gate_reason="$3"
  local gate_file="$4"

  [[ -f "$MIXED_DIR/mixed-registry.json" ]] || return 0

  GATE_BRIDGE_MIXED_DIR="$MIXED_DIR" \
  GATE_BRIDGE_ACTION="$gate_action" \
  GATE_BRIDGE_TARGET="$gate_target" \
  GATE_BRIDGE_REASON="$gate_reason" \
  GATE_BRIDGE_FILE="$gate_file" \
    python3 -c '
import fcntl
import json
import os
import random
import time
from pathlib import Path

def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def normalize(value):
    safe = []
    for char in value:
        if char.isalnum() or char in ("-", "_"):
            safe.append(char)
        elif char.isspace():
            safe.append("-")
    normalized = "".join(safe).strip("-_").lower()
    return normalized or f"task-{int(time.time())}"

def append_jsonl(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

mixed_dir = Path(os.environ["GATE_BRIDGE_MIXED_DIR"])
registry_file = mixed_dir / "mixed-registry.json"
events_file = mixed_dir / "events.jsonl"
inbox_dir = mixed_dir / "inbox"
action = os.environ["GATE_BRIDGE_ACTION"]
target = os.environ["GATE_BRIDGE_TARGET"]
reason = os.environ.get("GATE_BRIDGE_REASON", "")
gate_file = os.environ.get("GATE_BRIDGE_FILE", "")
status = "blocked" if action == "block" else "approved"

try:
    with registry_file.open(encoding="utf-8") as fh:
        registry = json.load(fh)
except Exception:
    registry = {}
known = any(str(c.get("id", "")) == target for c in registry.get("commanders", []) or [])
payload = {
    "source": "legion.sh gate",
    "target": target,
    "status": status,
    "reason": reason,
    "gate_file": gate_file,
    "target_known": known,
}
append_jsonl(events_file, {
    "ts": iso_now(),
    "event": f"gate_{status}",
    "task_id": target,
    "payload": payload,
})
if known:
    content = f"GATE {status.upper()}: {reason}" if reason else f"GATE {status.upper()}"
    append_jsonl(inbox_dir / f"{normalize(target)}.jsonl", {
        "id": f"msg-{time.time_ns()}-{random.randint(1000, 9999)}",
        "ts": iso_now(),
        "from": "L1",
        "to": target,
        "type": "gate",
        "content": content,
        "payload": payload,
    })
' 2>/dev/null
}

# ── 主命令 ──
ACTION="$REQUESTED_ACTION"

case "$ACTION" in

  # ── 项目初始化 ──
  0)
    shift
    _ensure_global_legion_config force
    _run_project_initializer "$@"
    exit $?
    ;;

  # ── Provider 显式入口：Codex L1 指挥官 ──
  codex)
    shift
    PROVIDER_SUB="${1:-}"
    case "$PROVIDER_SUB" in
      l1)
        shift
        python3 "$LEGION_SCRIPT_DIR/legion_core.py" l1 --provider codex "$@"
        exit $?
        ;;
      l1+1)
        shift
        python3 "$LEGION_SCRIPT_DIR/legion_core.py" l1 --provider codex --fresh "$@"
        exit $?
        ;;
      *)
        echo "用法:"
        echo "  legion.sh codex l1 [军团名] [--dry-run] [--no-attach]"
        echo "  legion.sh codex l1+1 [军团名]"
        exit 1
        ;;
    esac
    ;;

  # ── Provider 显式入口：Claude L1 指挥官（复用原 l1 逻辑）──
  claude)
    shift
    PROVIDER_SUB="${1:-}"
    case "$PROVIDER_SUB" in
      l1)
        shift
        python3 "$LEGION_SCRIPT_DIR/legion_core.py" l1 --provider claude "$@"
        exit $?
        ;;
      l1+1)
        shift
        python3 "$LEGION_SCRIPT_DIR/legion_core.py" l1 --provider claude --fresh "$@"
        exit $?
        ;;
      h|host|主持)
        shift
        python3 "$LEGION_SCRIPT_DIR/legion_core.py" claude-host "$@"
        exit $?
        ;;
      *)
        echo "用法:"
        echo "  legion.sh claude h [--dry-run] [--no-attach]"
        echo "  legion.sh claude l1 [军团名]"
        echo "  legion.sh claude l1+1 [军团名]"
        exit 1
        ;;
    esac
    ;;

  # ── 自治循环模式 ──
  auto)
    shift
    local_sub="${1:-}"
    if [[ -z "$local_sub" ]]; then
      echo "用法:"
      echo "  legion.sh auto plan \"需求描述\"   — 规划：拆分为原子功能"
      echo "  legion.sh auto run               — 执行：Generator→Evaluator 循环"
      echo "  legion.sh auto status            — 查看进度"
      echo "  legion.sh auto resume            — 从中断处继续"
      echo "  legion.sh auto stop              — 停止循环"
      echo "  legion.sh auto bg \"需求描述\"     — 规划+后台执行（去睡觉模式）"
      exit 0
    fi

    if [[ "$local_sub" == "bg" ]]; then
      # 一键后台模式：规划 + 执行
      shift
      local_req="${1:-}"
      if [[ -z "$local_req" ]]; then
        echo "用法: legion.sh auto bg \"需求描述\""
        exit 1
      fi
      echo "🚀 自治循环后台模式启动..."
      echo "   1. 规划中..."
      bash "$HOME/.claude/scripts/autonomous-loop.sh" plan "$local_req"
      echo "   2. 后台执行..."
      nohup bash "$HOME/.claude/scripts/autonomous-loop.sh" run > /tmp/autonomous-loop.log 2>&1 &
      local_pid=$!
      echo "   PID: $local_pid"
      echo "   日志: tail -f /tmp/autonomous-loop.log"
      echo "   进度: legion.sh auto status"
      echo "   停止: legion.sh auto stop"
    else
      # 透传给 autonomous-loop.sh
      bash "$HOME/.claude/scripts/autonomous-loop.sh" "$@"
    fi
    ;;

  # ── 统一 Legion Core 混编调度器（Claude + Codex）──
  mixed)
    shift
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" "$@"
    exit $?
    ;;

  # ── 双 L1 控制面：Claude 当前窗口，Codex 后台；M+ 任务再动态创建本体系 L2 ──
  h|host|主持)
    shift
    if _legion_has_arg --host-only "$@"; then
      python3 "$LEGION_SCRIPT_DIR/legion_core.py" host "$@"
      exit $?
    fi
    if _legion_has_arg --dual-only "$@"; then
      DUAL_ARGS=()
      for arg in "$@"; do
        [[ "$arg" == "--dual-only" ]] && continue
        DUAL_ARGS+=("$arg")
      done
      python3 "$LEGION_SCRIPT_DIR/legion_core.py" dual-host "${DUAL_ARGS[@]}"
      exit $?
    fi
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" claude-host "$@"
    exit $?
    ;;

  # ── 外部 Hermes AICTO：状态/启动指引，不创建本地 L0 ──
  aicto|cto|总司令)
    shift
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" aicto "$@"
    exit $?
    ;;

  # ── 自动分屏作战面：L1 主持人 + 基础 L2 + 执行任务 L2 同屏交互 ──
  view|v|看板|作战面)
    shift
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" view "$@"
    exit $?
    ;;

  # ── 一键双 L1：两个独立 Terminal 窗口分别启动 Codex / Claude ──
  duo)
    shift
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" duo "$@"
    exit $?
    ;;

  # ── 一键双 L1：新增窗口跑 Codex，当前窗口切换为 Claude ──
  dou)
    shift
    DOU_CODEX_NAME="玄武军团"
    DOU_CLAUDE_NAME="青龙军团"
    DOU_DRY_RUN=0
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --codex)
          DOU_CODEX_NAME="${2:-}"
          shift 2
          ;;
        --claude)
          DOU_CLAUDE_NAME="${2:-}"
          shift 2
          ;;
        --dry-run)
          DOU_DRY_RUN=1
          shift
          ;;
        *)
          echo "未知参数: $1"
          echo "用法: legion.sh dou [--codex 名] [--claude 名] [--dry-run]"
          exit 1
          ;;
      esac
    done
    if [[ "$DOU_DRY_RUN" -eq 1 ]]; then
      python3 "$LEGION_SCRIPT_DIR/legion_core.py" dou --codex "$DOU_CODEX_NAME" --claude "$DOU_CLAUDE_NAME" --dry-run
      exit $?
    fi
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" dou --codex "$DOU_CODEX_NAME" --claude "$DOU_CLAUDE_NAME"
    exec "$0" claude l1 "$DOU_CLAUDE_NAME"
    ;;

  # ── 查看所有 team 状态（只读） ──
  status)
    if [[ ! -f "$REGISTRY" ]]; then
      echo "(无活跃 team)"
      exit 0
    fi
    python3 -c "
import json
try:
    with open('$REGISTRY') as f:
        data = json.load(f)
except Exception:
    print('(无活跃 team)')
    raise SystemExit(0)
if not data.get('teams'):
    print('(无活跃 team)')
else:
    # 分组显示：先指挥官，再按隶属分组
    commanders = [t for t in data['teams'] if t.get('role') == 'commander' or t['id'].startswith('L1')]
    workers = [t for t in data['teams'] if t not in commanders]

    for t in commanders:
        print(f\"★ {t['id']}  [{t['status']}]  {t['task'][:50]}\")
        print(f\"    启动: {t['started']}\")
        # 显示隶属该指挥官的 team
        subs = [w for w in workers if w.get('parent') == t['id']]
        if subs:
            for s in subs:
                icon = '✓' if s['status'] == 'completed' else '⟳' if s['status'] == 'working' else '○'
                files = ', '.join(s.get('files', [])) or '(未声明)'
                print(f\"  {icon} {s['id']}  [{s['status']}]  {s['task'][:45]}\")
                print(f\"      文件: {files}\")
        print()

    # 无隶属的 team
    orphans = [w for w in workers if w.get('parent') not in [c['id'] for c in commanders]]
    if orphans:
        print('── 未分配指挥官 ──')
        for t in orphans:
            icon = '✓' if t['status'] == 'completed' else '⟳' if t['status'] == 'working' else '○'
            files = ', '.join(t.get('files', [])) or '(未声明)'
            parent = t.get('parent', 'L1')
            print(f\"{icon} {t['id']}  [{t['status']}]  → {parent}  {t['task'][:40]}\")
            print(f\"    文件: {files}\")
        print()
"
    ;;

  # ── 消耗统计 ──
  usage)
    shift
    bash "$HOME/.claude/scripts/legion-usage.sh" "$@"
    exit $?
    ;;

  # ── 账号切换 ──
  switch|account)
    shift
    bash "$HOME/.claude/scripts/claude-switch.sh" "$@"
    exit $?
    ;;

  # ── 查看任务板（只读） ──
  board)
    if [[ ! -f "$TASKBOARD" ]]; then
      echo "(任务板为空)"
      exit 0
    fi
    python3 -c "
import json
try:
    with open('$TASKBOARD') as f:
        tb = json.load(f)
except:
    print('(任务板为空)')
    exit()

tasks = tb.get('tasks', [])
if not tasks:
    print('(无任务)')
else:
    print(f'任务板 (更新: {tb.get(\"updated\", \"?\")[:19]})')
    print('─' * 60)
    for t in tasks:
        icon = {'pending': '○', 'in_progress': '⟳', 'completed': '✓', 'blocked': '✗'}.get(t.get('status', ''), '?')
        pr = {'urgent': '🔴', 'critical': '🔴🔴', 'normal': '  '}.get(t.get('priority', 'normal'), '  ')
        print(f\"{icon} {pr} {t.get('id', '?')[:15]:15}  [{t.get('status', '?'):12}]  {t.get('assignee', '?'):20}  {t.get('title', '')[:40]}\")
    print()
    pending = sum(1 for t in tasks if t.get('status') in ('pending', 'in_progress'))
    done = sum(1 for t in tasks if t.get('status') == 'completed')
    print(f'进行中: {pending}  已完成: {done}  总计: {len(tasks)}')
"
    ;;

  # ── 查看文件锁（只读） ──
  locks)
    if [[ ! -f "$LOCKS_FILE" ]]; then
      echo "(无活跃锁)"
      exit 0
    fi
    python3 -c "
import json
from datetime import datetime
try:
    with open('$LOCKS_FILE') as f:
        data = json.load(f)
except:
    print('(无文件锁)')
    exit()

locks = data.get('locks', [])
if not locks:
    print('(无活跃锁)')
else:
    print(f'文件锁 ({len(locks)} 个)')
    print('─' * 70)
    for l in locks:
        expires = l.get('expires', '')[:19]
        print(f\"🔒 {l.get('file', '?')}\")
        print(f\"   所有者: {l.get('owner', '?')}  原因: {l.get('reason', '?')}\")
        print(f\"   获取: {l.get('acquired', '?')[:19]}  过期: {expires}\")
        print()
"
    ;;

  # ── 邮箱自动投递守护进程 ──
  watcher)
    shift
    bash "$HOME/.claude/scripts/legion-watcher.sh" "${1:-status}"
    ;;

  # ── 巡查协议（mixed-aware status / notice / remediate / reinspect）──
  patrol)
    shift
    PATROL_SCRIPT=""
    for candidate in \
      "$LEGION_SCRIPT_DIR/legion-patrol.sh" \
      "$HOME/.claude/scripts/legion-patrol.sh"; do
      [[ -f "$candidate" ]] && PATROL_SCRIPT="$candidate" && break
    done
    if [[ -z "$PATROL_SCRIPT" ]]; then
      echo "❌ 找不到 legion-patrol.sh（已查 scripts/ 与 ~/.claude/scripts/）" >&2
      exit 1
    fi
    LEGION_DIR="$REGISTRY_DIR" MIXED_DIR="$MIXED_DIR" PROJECT_DIR="$PROJECT_DIR" \
      bash "$PATROL_SCRIPT" "${@:-status}"
    exit $?
    ;;

  # ── 回顾官（quick / full）──
  retro|retrospector)
    shift
    RETRO_SCRIPT=""
    for candidate in \
      "$LEGION_SCRIPT_DIR/retrospector.sh" \
      "$HOME/.claude/scripts/retrospector.sh"; do
      [[ -f "$candidate" ]] && RETRO_SCRIPT="$candidate" && break
    done
    if [[ -z "$RETRO_SCRIPT" ]]; then
      echo "❌ 找不到 retrospector.sh（已查 scripts/ 与 ~/.claude/scripts/）" >&2
      exit 1
    fi
    if [[ $# -eq 0 ]]; then
      set -- quick
    fi
    RETRO_PYTHON="${PYTHON:-python3}"
    LEGION_DIR="$REGISTRY_DIR" MIXED_DIR="$MIXED_DIR" PROJECT_DIR="$PROJECT_DIR" PLANNING_DIR="$PROJECT_DIR/.planning" \
      "$RETRO_PYTHON" -c 'import pathlib, sys; script = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"); marker = "# __RETROSPECTOR_PYTHON__\n"; code = script.split(marker, 1)[1].rsplit("\n__RETROSPECTOR_PYTHON__", 1)[0]; sys.argv = [sys.argv[1]] + sys.argv[2:]; exec(compile(code, sys.argv[0], "exec"))' "$RETRO_SCRIPT" "$@"
    exit $?
    ;;

  # ── 邮箱操作 ──
  mailbox)
    shift
    MB_CMD="${1:-help}"
    case "$MB_CMD" in
      send)
        # legion.sh mailbox send <from> <to> <type> <content> [summary]
        if [[ $# -lt 5 ]]; then
          echo "用法: legion.sh mailbox send <from> <to> <type> <content> [summary]"
          exit 1
        fi
        mailbox_send "$2" "$3" "$4" "$5" "${6:-}"
        echo "已发送"
        ;;
      read)
        MB_TEAM="${2:-L1}"
        MB_AGENT="${3:-$MB_TEAM}"
        mailbox_display "$MB_TEAM" "$MB_AGENT"
        ;;
      unread)
        MB_TEAM="${2:-L1}"
        MB_AGENT="${3:-$MB_TEAM}"
        mailbox_display "$MB_TEAM" "$MB_AGENT" "true"
        ;;
      broadcast)
        if [[ $# -lt 4 ]]; then
          echo "用法: legion.sh mailbox broadcast <from> <type> <content> [summary]"
          exit 1
        fi
        BC_COUNT=$(mailbox_broadcast "$2" "$3" "$4" "${5:-}")
        echo "广播已发送到 $BC_COUNT 个 agent"
        ;;
      list)
        MB_TEAM="${2:-L1}"
        echo "=== ${MB_TEAM} 的所有邮箱 ==="
        mailbox_list_inboxes "$MB_TEAM"
        ;;
      clear)
        MB_TEAM="${2:-}"
        MB_AGENT="${3:-$MB_TEAM}"
        if [[ -z "$MB_TEAM" ]]; then
          echo "用法: legion.sh mailbox clear <team_id> [agent_name]"
          exit 1
        fi
        mailbox_clear "$MB_TEAM" "$MB_AGENT"
        echo "邮箱已清空"
        ;;
      *)
        echo "邮箱命令:"
        echo "  legion.sh mailbox send <from> <to> <type> <content> [summary]"
        echo "  legion.sh mailbox read <team_id> [agent_name]"
        echo "  legion.sh mailbox unread <team_id> [agent_name]"
        echo "  legion.sh mailbox broadcast <from> <type> <content> [summary]"
        echo "  legion.sh mailbox list <team_id>"
        echo "  legion.sh mailbox clear <team_id> [agent_name]"
        echo ""
        echo "消息类型: text | report | shutdown | gate | ack | coordination | lock"
        ;;
    esac
    ;;

  # ── 健康检查（只读） ──
  health)
    echo "=== Commander 状态 ==="
    if _commander_alive; then
      python3 -c "
import json
try:
    with open('$COMMANDER_HEARTBEAT_FILE') as f:
        hb = json.load(f)
    uptime = int(hb.get('uptime_seconds', 0))
    m, s = divmod(uptime, 60)
    h, m = divmod(m, 60)
    print(f'  状态: 运行中')
    print(f'  PID:  {hb.get(\"pid\", \"?\")}')
    print(f'  心跳: {hb.get(\"ts\", \"?\")[:19]}')
    print(f'  运行: {h}h {m}m {s}s')
except:
    print('  状态: 运行中（无心跳数据）')
" 2>/dev/null
    else
      echo "  状态: 已停止"
    fi

    echo ""
    echo "=== 扩编限流统计 ==="
    python3 -c "
import json
from datetime import datetime
try:
    with open('$REGISTRY_DIR/spawn_tracker.json') as f:
        tracker = json.load(f)
except:
    print('  (无数据)')
    exit()

spawns = tracker.get('spawns', [])
stats = tracker.get('stats', {})
now = datetime.now()
active = [s for s in spawns if s.get('status') != 'completed']
recent = [s for s in spawns if (now - datetime.fromisoformat(s['ts'])).total_seconds() < 60]
print(f'  活跃扩编: {len(active)} / 全局上限 20')
print(f'  最近 60s: {len(recent)} 个请求')
if stats:
    print(f'  各 team:')
    for team_id, st in stats.items():
        print(f'    {team_id}: 总计 {st.get(\"total\", 0)} / 活跃 {st.get(\"active\", 0)} / 上限 5')
" 2>/dev/null

    echo ""
    echo "=== Hooks 状态 ==="
    python3 -c "
import json, os
settings_path = '$SETTINGS_FILE'
if not os.path.exists(settings_path):
    print('  未安装（legion 启动时自动安装）')
else:
    try:
        with open(settings_path) as f:
            s = json.load(f)
    except Exception as e:
        print(f'  解析失败: {e}')
        raise SystemExit(0)
    if 'hooks' in s and isinstance(s['hooks'], dict) and s['hooks']:
        types = list(s['hooks'].keys())
        print(f\"  已安装: {', '.join(types)}\")
    else:
        print('  未安装（legion 启动时自动安装）')
" 2>/dev/null
    ;;

  # ── 部署战役（支持 --commander）──
  campaign)
    # 解析 --commander 参数
    CAMPAIGN_COMMANDER="L1"
    CAMPAIGN_PLAN=""
    shift  # 移除 "campaign"
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --commander)
          CAMPAIGN_COMMANDER="$2"
          shift 2
          ;;
        *)
          CAMPAIGN_PLAN="$1"
          shift
          ;;
      esac
    done

    if [[ -z "$CAMPAIGN_PLAN" ]]; then
      cat << 'USAGE'
用法: legion.sh campaign [--commander L1-name] 'JSON计划'

计划格式:
[
  {"task":"任务描述","scope":["file1","file2"]},
  {"task":"任务2","scope":["file3"],"depends_on":["任务描述"]}
]

字段说明:
  task       — 任务描述（必填）
  scope      — 文件范围（选填）
  depends_on — 依赖的任务名称列表（选填，等对方完成后再开始）

选项:
  --commander ID — 指定隶属的指挥官（默认 L1）

智能规模:
  - 1 个任务 → 单 team 独立模式（轻量，完整汇报）
  - 2+ 任务 → 全 Legion 模式（并行，实时通信）
USAGE
      exit 1
    fi
    PLAN="$CAMPAIGN_PLAN"

    _init_registry
    _init_comms
    _init_commander ""
    _write_system_prompt
    _install_hooks
    _start_commander

    # 解析计划并部署
    python3 -c "
import json, subprocess, sys, time, fcntl

commander = '$CAMPAIGN_COMMANDER'
plan = json.loads('''$PLAN''')
if not isinstance(plan, list):
    print('错误: 计划必须是 JSON 数组')
    sys.exit(1)

n = len(plan)

# ── 智能规模判断 ──
if n == 1:
    print('╔══ 单 team 独立模式 ══╗')
    entry = plan[0]
    task = entry.get('task', '任务')
    scope = entry.get('scope', [])
    full_task = task
    if scope:
        full_task += f' (文件范围: {\", \".join(scope)})'
    print(f'  任务: {task}')
    print(f'  范围: {\", \".join(scope) if scope else \"(自行判断)\"}')
    print(f'  隶属: {commander}')
    print(f'  模式: 单 team 独立完成，完整汇报给 {commander}')
    print()
    result = subprocess.run(
        ['bash', '$0', '--commander', commander, full_task],
        capture_output=True, text=True, cwd='$(pwd)'
    )
    print(result.stdout)
    sys.exit(0)

# ── 全 Legion 模式 ──
print(f'╔══ 全 Legion 模式: {n} 个 team ══╗')
print()

# 构建依赖图
task_names = [e.get('task', f'任务{i+1}') for i, e in enumerate(plan)]
dep_map = {}  # task_name → [依赖的 task_name]
for i, entry in enumerate(plan):
    deps = entry.get('depends_on', [])
    dep_map[task_names[i]] = deps

# 显示计划
for i, entry in enumerate(plan):
    task = entry.get('task', f'任务{i+1}')
    scope = entry.get('scope', [])
    deps = entry.get('depends_on', [])
    scope_str = ', '.join(scope) if scope else '(自行判断)'
    deps_str = ' → 等待: ' + ', '.join(deps) if deps else ''
    print(f'  [{i+1}] {task}')
    print(f'      范围: {scope_str}{deps_str}')

print()
print('开始部署...')
print()

# 部署并记录 team ID
deployed = {}  # task_name → team_id
for i, entry in enumerate(plan):
    task = task_names[i]
    scope = entry.get('scope', [])
    deps = entry.get('depends_on', [])

    # 构建完整任务描述，注入范围 + 依赖信息
    parts = [task]
    if scope:
        parts.append(f'(文件范围: {\", \".join(scope)})')
    if deps:
        dep_teams = []
        for d in deps:
            if d in deployed:
                dep_teams.append(f'{d}={deployed[d]}')
            else:
                dep_teams.append(d)
        parts.append(f'(前置依赖: {\", \".join(dep_teams)}。等待他们发送 mission_complete 消息后再开始修改文件。在等待期间可以先读代码、做准备。)')

    full_task = ' '.join(parts)

    result = subprocess.run(
        ['bash', '$0', '--commander', commander, full_task],
        capture_output=True, text=True, cwd='$(pwd)'
    )
    output = result.stdout.strip()
    print(output)

    # 提取 team ID
    for line in output.split('\n'):
        if 'ID:' in line and 'team-' in line:
            tid = line.split('team-', 1)[1].strip().split()[0]
            deployed[task] = f'team-{tid}'
            break

    if i < n - 1:
        time.sleep(1)

# 保存战役计划到文件供审计用
campaign_data = {
    'plan': plan,
    'deployed': deployed,
    'started': __import__('datetime').datetime.now().isoformat(),
    'status': 'active'
}
with open('$REGISTRY_DIR/campaign.json', 'w') as f:
    json.dump(campaign_data, f, ensure_ascii=False, indent=2)

print()
print('═' * 50)
print(f'战役部署完成: {n} 个 team')
if dep_map and any(dep_map.values()):
    print('依赖链:')
    for task, deps in dep_map.items():
        if deps:
            print(f'  {\" + \".join(deps)} → {task}')
print()
print('监控:  legion.sh sitrep')
print('汇报:  legion.sh inbox')
print('指令:  legion.sh msg TEAM_ID \"内容\"')
print('审计:  legion.sh audit  (全部完成后)')
print('═' * 50)
" 2>/dev/null
    ;;

  # ── 查看指挥官汇报（支持指定 ID）──
  # legion.sh inbox          → L1 收件箱
  # legion.sh inbox L1-test  → L1-test 收件箱
  inbox)
    INBOX_ID="${2:-L1}"

    # 只读视图：不创建通信骨架、不插入 commander 注册表条目。
    # 优先使用新邮箱系统（如果存在）
    INBOX_DIR_NEW="${LEGION_DIR}/team-${INBOX_ID}/inboxes"
    if type mailbox_display &>/dev/null \
        && [[ -d "$INBOX_DIR_NEW" ]] \
        && ls "$INBOX_DIR_NEW"/*.json &>/dev/null 2>&1; then
      echo "═══ ${INBOX_ID} 邮箱 (新系统) ═══"
      mailbox_display "$INBOX_ID" "$INBOX_ID"
      echo ""
      echo "── 所有 inbox ──"
      mailbox_list_inboxes "$INBOX_ID"
      echo ""
    fi

    # 旧系统：也显示 inbox.jsonl（向后兼容，过渡期后删除）
    python3 -c "
import json, sys, os

cmd_id = '$INBOX_ID'
legion_dir = '$LEGION_DIR'
inbox_path = f'{legion_dir}/team-{cmd_id}/inbox.jsonl'
cursor_file = f'{legion_dir}/team-{cmd_id}/inbox.cursor'

try:
    with open(inbox_path) as f:
        lines = f.readlines()
except FileNotFoundError:
    sys.exit(0)

try:
    cursor = int(open(cursor_file).read().strip())
except:
    cursor = 0

total = len(lines)
unread = total - cursor

if not lines or unread == 0:
    sys.exit(0)

print(f'═══ {cmd_id} 旧收件箱 (过渡期) ═══')
print(f'总 {total} 条, 未读 {unread} 条')
print('─' * 60)

start = max(0, cursor)

for i in range(start, total):
    line = lines[i].strip()
    if not line: continue
    try:
        m = json.loads(line)
        # 跳过已通过新系统投递的消息
        if m.get('_via') == 'mailbox':
            continue
        fr = m.get('from', '?')
        ts = m.get('ts', '?')[:19]
        pr = m.get('priority', 'normal')
        payload = m.get('payload', {})
        event = payload.get('event', m.get('type', '?'))
        marker = ' [NEW]' if i >= cursor else ''
        prefix = '🔴 ' if pr in ('urgent', 'critical') else '   '

        print(f'{prefix}[{ts}] {fr} → {event}{marker}')

        for key in ('summary', 'detail', 'status', 'message', 'quality', 'reason'):
            if key in payload:
                val = str(payload[key])[:80]
                print(f'      {key}: {val}')
        files = payload.get('files_changed', [])
        if files:
            print(f'      files: {\", \".join(files[:5])}')
        print()
    except:
        pass

if unread > 0:
    print(f'({unread} 条未读，未修改已读游标)')
" --all 2>/dev/null
    ;;

  # ── 综合态势感知（只读） ──
  sitrep)
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║              军团态势感知 (SITREP)                      ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""

    echo "── 部队状态 ──"
    python3 -c "
import json, os
registry_path = '$REGISTRY'
if not os.path.exists(registry_path):
    print('  (无部队)')
    raise SystemExit(0)
try:
    with open(registry_path) as f:
        data = json.load(f)
except Exception:
    print('  (注册表不可读)')
    raise SystemExit(0)
teams = [t for t in data.get('teams', []) if t['id'] != 'L1']
if not teams:
    print('  (无部队)')
else:
    active = sum(1 for t in teams if t['status'] in ('active', 'working'))
    done = sum(1 for t in teams if t['status'] == 'completed')
    print(f'  总计: {len(teams)}  作战中: {active}  已完成: {done}')
    print()
    for t in teams:
        icon = {'completed': '✓', 'working': '⟳', 'active': '○'}.get(t['status'], '?')
        print(f'  {icon} {t[\"id\"]:25} [{t[\"status\"]:10}] {t[\"task\"][:45]}')
" 2>/dev/null
    echo ""

    echo "── 文件锁 ──"
    python3 -c "
import json, os
locks_path = '$LOCKS_FILE'
if not os.path.exists(locks_path):
    print('  (无)')
    raise SystemExit(0)
try:
    with open(locks_path) as f:
        locks = json.load(f).get('locks', [])
    if not locks:
        print('  (无)')
    else:
        for l in locks:
            print(f'  🔒 {l[\"owner\"]:15} → {l[\"file\"]}')
except Exception:
    print('  (无)')
" 2>/dev/null
    echo ""

    echo "── 任务板 ──"
    python3 -c "
import json, os
tb_path = '$TASKBOARD'
if not os.path.exists(tb_path):
    print('  (无)')
    raise SystemExit(0)
try:
    with open(tb_path) as f:
        tasks = json.load(f).get('tasks', [])
    pending = [t for t in tasks if t.get('status') in ('pending', 'in_progress')]
    if not pending:
        print('  (无待办)')
    else:
        for t in pending:
            print(f'  ⟳ {t[\"assignee\"]:15} {t[\"title\"][:45]}')
except Exception:
    print('  (无)')
" 2>/dev/null
    echo ""

    echo "── L1 未读消息 ──"
    python3 -c "
import json, os
inbox = '$REGISTRY_DIR/team-L1/inbox.jsonl'
cursor_file = '$REGISTRY_DIR/team-L1/inbox.cursor'
if not os.path.exists(inbox):
    print('  (无)')
    raise SystemExit(0)
try:
    with open(inbox) as f:
        total = len(f.readlines())
    try:
        cursor = int(open(cursor_file).read().strip())
    except Exception:
        cursor = 0
    unread = total - cursor
    if unread > 0:
        print(f'  📬 {unread} 条未读 (运行 legion.sh inbox 查看)')
    else:
        print(f'  (无未读, 共 {total} 条历史)')
except Exception:
    print('  (无)')
" 2>/dev/null
    echo ""

    echo "── Commander ──"
    if _commander_alive; then
      echo "  运行中"
    else
      echo "  ⚠ 已停止"
    fi
    ;;

  # ── 一屏运营面板（只读）：mixed 部队 + 阻塞/失败 + 巡查通知 + release gate + 回顾官 ──
  # 用于 row-23 操作员 UX surfacing：所有关键证据汇总到一个 read-only 入口。
  # 不创建 ~/.claude/legion/directory.json，不初始化 $PROJECT_DIR/.claude，
  # 在 HOME/TMPDIR 隔离的合约测试下也能稳定输出。
  ops)
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║       军团运营面板 (OPS) — 一屏统览                  ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
    LEGION_OPS_REGISTRY_DIR="$REGISTRY_DIR" \
    LEGION_OPS_MIXED_DIR="$MIXED_DIR" \
    LEGION_OPS_LEGION_DIR="$LEGION_DIR" \
    LEGION_OPS_PROJECT_DIR="$PROJECT_DIR" \
    LEGION_OPS_BROADCAST="$BROADCAST" \
      python3 - <<'OPSEOF'
import json
import os
from pathlib import Path

registry_dir = Path(os.environ["LEGION_OPS_REGISTRY_DIR"])
mixed_dir = Path(os.environ["LEGION_OPS_MIXED_DIR"])
legion_dir = Path(os.environ["LEGION_OPS_LEGION_DIR"])
project_dir = Path(os.environ["LEGION_OPS_PROJECT_DIR"])
broadcast_file = Path(os.environ["LEGION_OPS_BROADCAST"])


def _load_json(p):
    try:
        with p.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


registry = _load_json(mixed_dir / "mixed-registry.json") if mixed_dir.exists() else None

# ── Mixed 部队 ──
print("── Mixed 部队 (commanders) ──")
if not registry:
    print("  (未发现 mixed-registry.json)")
else:
    commanders = registry.get("commanders") or []
    if not commanders:
        print("  (无 commander)")
    else:
        for c in commanders:
            cid = str(c.get("id", "?"))
            provider = str(c.get("provider", "?"))
            status = str(c.get("status", "?"))
            level = c.get("level")
            if not level:
                if cid.startswith("L1-"):
                    level = 1
                elif cid.startswith("L2-"):
                    level = 2
                else:
                    level = "?"
            branch = c.get("branch") or "-"
            parent = c.get("parent") or "-"
            lifecycle = c.get("lifecycle") or "-"
            failure = str(c.get("failure", "")).strip()
            line = f"  {cid:24} provider={provider:6} status={status:10} L{level} branch={branch} parent={parent} lifecycle={lifecycle}"
            if failure:
                line += f" — failure={failure[:80]}"
            print(line)
print("")

# ── 阻塞 / 失败任务 ──
print("── 阻塞 / 失败任务 ──")
blockers = []
if registry:
    for t in registry.get("tasks") or []:
        if str(t.get("status", "")).lower() in ("blocked", "failed"):
            blockers.append(t)
if not blockers:
    print("  (无阻塞/失败任务)")
else:
    for t in blockers:
        tid = str(t.get("id", "?"))
        role = str(t.get("role", "?"))
        status = str(t.get("status", "?"))
        commander = str(t.get("commander", "-"))
        reason = str(t.get("failure") or t.get("blocked_reason") or "").strip()
        scope_raw = t.get("scope") or []
        if isinstance(scope_raw, str):
            scope_items = [scope_raw]
        else:
            scope_items = [str(item) for item in scope_raw]
        scope = ", ".join(scope_items) or "(auto)"
        task_text = str(t.get("task", "")).replace("\n", " ")[:80]
        icon = "✗" if status == "failed" else "⏸"
        print(f"  {icon} {tid:18} {status:9} role={role:12} commander={commander} {task_text}")
        print(f"      scope: {scope}")
        if reason:
            print(f"      原因: {reason[:120]}")
print("")

# ── 巡查通知书 ──
print("── 巡查通知书 (patrol notices) ──")
patrol_dir = legion_dir / "patrol"
notices = []
if patrol_dir.exists():
    try:
        notices = sorted(patrol_dir.glob("notice-*.json"))
    except Exception:
        notices = []
if not notices:
    print("  (无)")
else:
    for nf in notices:
        n = _load_json(nf) or {}
        team = n.get("team_id", "?")
        nstatus = n.get("status", "?")
        count = n.get("edit_count", 0)
        issued = str(n.get("issued_at", ""))[:19]
        remed = str(n.get("remediated_at", ""))[:19]
        reason = str(n.get("reason", "")).strip()[:120]
        line = f"  {team:24} status={nstatus:11} edits={count} issued={issued}"
        if remed:
            line += f" remediated_at={remed}"
        print(line)
        if reason:
            print(f"      reason: {reason}")
print("")

# ── Release Gate (team-*/gate.json) ──
print("── Release Gate (team-*/gate.json) ──")
gates = []
if registry_dir.exists():
    try:
        for gate_file in sorted(registry_dir.glob("team-*/gate.json")):
            gate = _load_json(gate_file) or {}
            team = gate_file.parent.name.replace("team-", "")
            gates.append((team, gate))
    except Exception:
        gates = []
if not gates:
    print("  (无 gate)")
else:
    for team, gate in gates:
        gstatus = str(gate.get("status", "?"))
        if gstatus == "blocked":
            icon = "⛔"
        elif gstatus == "approved":
            icon = "✅"
        else:
            icon = "?"
        reason = str(gate.get("reason", "")).strip()[:80]
        when = str(gate.get("blocked_at") or gate.get("approved_at") or "")[:19]
        line = f"  {icon} {team:24} status={gstatus}"
        if when:
            line += f" at={when}"
        if reason:
            line += f" reason={reason}"
        print(line)
print("")

# ── Retrospective release status ──
print("── Retrospective Release Status ──")
planning = project_dir / ".planning"
retros_dir = planning / "retrospectives"
state_file = planning / "STATE.md"
records = []
if retros_dir.exists():
    try:
        records = sorted(retros_dir.glob("*.md"), reverse=True)
    except Exception:
        records = []
if not records:
    print("  (无 retrospective 记录)")
else:
    latest = records[0]
    print(f"  最新: {latest.name}")
    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
    except Exception:
        text = ""
    keys = ("verdict", "release gate", "blocks_release", "classification", "release_blocking")
    seen = set()
    for line in text.splitlines():
        low = line.lower()
        for key in keys:
            if key in low and key not in seen:
                seen.add(key)
                print(f"    {line.strip()[:140]}")
                break
        if len(seen) == len(keys):
            break
if state_file.exists():
    try:
        state_text = state_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        state_text = ""
    release_lines = [
        line.strip()
        for line in state_text.splitlines()
        if "release" in line.lower() or "retrospective" in line.lower()
    ]
    if release_lines:
        print("  STATE.md 摘要:")
        for line in release_lines[-3:]:
            print(f"    {line[:140]}")
print("")

# ── 近期 Mixed 事件 (patrol / gate / blocked / failed / release) ──
print("── 近期 Mixed 事件 (patrol / gate / blocked / failed / release, ≤ 8) ──")
events_file = mixed_dir / "events.jsonl"
matches = []
if events_file.exists():
    try:
        with events_file.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue
                event = str(rec.get("event") or rec.get("type") or "").lower()
                if any(k in event for k in ("patrol", "gate", "block", "fail", "release")):
                    matches.append(rec)
    except Exception:
        pass
if not matches:
    print("  (无相关事件)")
else:
    for rec in matches[-8:]:
        ts = str(rec.get("timestamp", ""))[:19]
        event = str(rec.get("event", "") or rec.get("type", ""))
        subject = str(rec.get("subject_id", "") or rec.get("task_id", "") or "-")
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        note = str(
            payload.get("reason", "")
            or payload.get("verdict", "")
            or payload.get("classification", "")
            or payload.get("failure", "")
        ).strip()
        line = f"  [{ts}] {event:24} subject={subject}"
        if note:
            line += f" — {note[:80]}"
        print(line)
print("")
print("提示: 写操作仍走 patrol / gate / retro 各自子命令；ops 是只读快照。")
OPSEOF
    ;;

  # ── 审批门控制 ──
  gate)
    if [[ $# -lt 3 ]]; then
      echo "用法:"
      echo "  legion.sh gate TEAM_ID block \"原因\"  # 暂停 team 的所有写操作"
      echo "  legion.sh gate TEAM_ID approve       # 放行"
      echo "  legion.sh gate TEAM_ID status        # 查看门状态"
      exit 1
    fi
    GATE_TARGET="$2"
    GATE_ACTION="$3"
    GATE_REASON="${4:-L1 审批}"
    GATE_FILE="$REGISTRY_DIR/team-$GATE_TARGET/gate.json"

    # 只读子动作（status）不应当创建 team 目录或注册表条目
    case "$GATE_ACTION" in
      block|approve)
        mkdir -p "$REGISTRY_DIR/team-$GATE_TARGET"
        ;;
    esac

    case "$GATE_ACTION" in
      block)
        GATE_FILE="$GATE_FILE" \
        GATE_REASON="$GATE_REASON" \
        GATE_TARGET="$GATE_TARGET" \
          python3 -c '
import json, os
from datetime import datetime
gate = {
    "status": "blocked",
    "reason": os.environ["GATE_REASON"],
    "blocked_at": datetime.now().isoformat(),
    "blocked_by": "L1",
}
with open(os.environ["GATE_FILE"], "w", encoding="utf-8") as fh:
    json.dump(gate, fh, ensure_ascii=False, indent=2)
target = os.environ["GATE_TARGET"]
reason = os.environ["GATE_REASON"]
print(f"⛔ {target} 已暂停: {reason}")
print("该 team 的所有 Edit/Write/Bash 操作将被阻止")
print(f"放行: legion.sh gate {target} approve")
' 2>/dev/null

        # 通知该 team
        GATE_OUTBOX="$REGISTRY_DIR/team-L1/outbox.jsonl" \
        GATE_TARGET="$GATE_TARGET" \
        GATE_REASON="$GATE_REASON" \
          python3 -c '
import json, os, uuid
from datetime import datetime
msg = {
    "id": f"msg-{uuid.uuid4().hex[:8]}",
    "ts": datetime.now().isoformat(),
    "from": "L1",
    "to": os.environ["GATE_TARGET"],
    "type": "notify",
    "priority": "critical",
    "payload": {
        "event": "gate_blocked",
        "reason": os.environ["GATE_REASON"],
        "instruction": "L1 已暂停你的写操作。请等待审批。你可以继续读代码和分析，但不要尝试修改文件。",
    },
}
outbox = os.environ["GATE_OUTBOX"]
os.makedirs(os.path.dirname(outbox), exist_ok=True)
with open(outbox, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(msg, ensure_ascii=False) + "\n")
' 2>/dev/null
        if ! _gate_bridge_mixed block "$GATE_TARGET" "$GATE_REASON" "$GATE_FILE"; then
          echo "❌ mixed gate evidence write failed for $GATE_TARGET" >&2
          exit 1
        fi
        ;;

      approve)
        if [[ -f "$GATE_FILE" ]]; then
          GATE_FILE="$GATE_FILE" GATE_TARGET="$GATE_TARGET" python3 -c '
import json, os
from datetime import datetime
gate = {
    "status": "approved",
    "approved_at": datetime.now().isoformat(),
    "approved_by": "L1",
}
with open(os.environ["GATE_FILE"], "w", encoding="utf-8") as fh:
    json.dump(gate, fh, ensure_ascii=False, indent=2)
target = os.environ["GATE_TARGET"]
print(f"✅ {target} 已放行")
' 2>/dev/null
          if ! _gate_bridge_mixed approve "$GATE_TARGET" "$GATE_REASON" "$GATE_FILE"; then
            echo "❌ mixed gate evidence write failed for $GATE_TARGET" >&2
            exit 1
          fi

          # 安全驱动指挥官恢复执行
          TARGET_SESSION="legion-${PROJECT_HASH}-${GATE_TARGET}"
          _safe_send "$TARGET_SESSION" "审批门已解除，请继续执行之前被中断的任务。" "$GATE_TARGET"
          echo "  已驱动 ${GATE_TARGET} 恢复执行"
        else
          echo "$GATE_TARGET 无活跃的审批门"
        fi
        ;;

      status)
        if [[ -f "$GATE_FILE" ]]; then
          python3 -c "
import json
with open('$GATE_FILE') as f:
    gate = json.load(f)
status = gate.get('status', '?')
icon = '⛔' if status == 'blocked' else '✅'
print(f'{icon} {\"$GATE_TARGET\"}: {status}')
for k, v in gate.items():
    if k != 'status':
        print(f'  {k}: {v}')
" 2>/dev/null
        else
          echo "✅ $GATE_TARGET: 无审批门（正常运行）"
        fi
        ;;
    esac
    ;;

  # ── 实时活动流（只读） ──
  watch)
    echo "═══ Legion 实时活动流 (Ctrl+C 退出) ═══"
    echo ""

    # tail 所有通信文件（只读：不创建任何文件，不写注册表）
    WATCH_FILES=""
    if [[ -d "$REGISTRY_DIR" ]]; then
      for team_dir in "$REGISTRY_DIR"/team-*/; do
        [[ -d "$team_dir" ]] || continue
        [[ -f "${team_dir}inbox.jsonl" ]] && WATCH_FILES="$WATCH_FILES ${team_dir}inbox.jsonl"
        [[ -f "${team_dir}outbox.jsonl" ]] && WATCH_FILES="$WATCH_FILES ${team_dir}outbox.jsonl"
      done
    fi

    [[ -f "$BROADCAST" ]] && WATCH_FILES="$WATCH_FILES $BROADCAST"

    if [[ -z "$WATCH_FILES" ]]; then
      echo "(无活跃通信通道)"
      exit 0
    fi

    # 用 tail -f 实时跟踪，python 格式化输出
    tail -f -n 0 $WATCH_FILES 2>/dev/null | python3 -c "
import sys, json

for line in sys.stdin:
    line = line.strip()
    if not line or line.startswith('==>'):
        continue
    try:
        m = json.loads(line)
        fr = m.get('from', '?')
        to = m.get('to', '?')
        tp = m.get('type', '?')
        pr = m.get('priority', 'normal')
        ts = m.get('ts', '')
        if ts:
            ts = ts[11:19]  # HH:MM:SS
        payload = m.get('payload', {})
        event = payload.get('event', tp)

        # 颜色
        if pr in ('urgent', 'critical'):
            color = '\033[31m'  # 红
        elif event in ('heartbeat',):
            color = '\033[90m'  # 灰
        elif event in ('mission_complete', 'audit_complete'):
            color = '\033[32m'  # 绿
        elif event in ('gate_blocked',):
            color = '\033[33m'  # 黄
        else:
            color = '\033[36m'  # 青

        reset = '\033[0m'

        # 格式化
        detail = ''
        for k in ('message', 'summary', 'detail', 'status', 'file', 'reason'):
            if k in payload:
                detail = f' | {payload[k]}'
                break

        if event == 'heartbeat':
            calls = payload.get('tool_calls', '?')
            files = payload.get('active_files', [])
            detail = f' | calls={calls}'
            if files:
                detail += f' files={','.join(files[:3])}'

        print(f'{color}[{ts}] {fr} → {to} ({event}){detail}{reset}', flush=True)
    except:
        pass
" 2>/dev/null
    ;;

  # ── 审计（全部完成后部署审计 team）──
  audit)
    _init_registry
    _init_comms
    _init_l1

    # 检查是否所有 team 已完成
    python3 -c "
import json, subprocess, sys

with open('$REGISTRY') as f:
    data = json.load(f)

teams = [t for t in data['teams'] if t['id'] != 'L1']
active = [t for t in teams if t['status'] in ('active', 'working')]

if active:
    print(f'⚠ 还有 {len(active)} 个 team 未完成:')
    for t in active:
        print(f'  ⟳ {t[\"id\"]}  {t[\"task\"][:50]}')
    print()
    print('等待全部完成后再审计，或加 --force 强制审计')
    if '--force' not in sys.argv:
        sys.exit(1)
    print('强制审计模式...')
    print()

# 收集战役信息
campaign_file = '$REGISTRY_DIR/campaign.json'
try:
    with open(campaign_file) as f:
        campaign = json.load(f)
except:
    campaign = {}

# 收集所有 team 的完成报告
reports = []
for t in teams:
    inbox = '$REGISTRY_DIR/team-L1/inbox.jsonl'
    try:
        with open(inbox) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                m = json.loads(line)
                if m.get('from') == t['id'] and m.get('payload', {}).get('event') == 'mission_complete':
                    reports.append(m)
    except:
        pass

# 构建审计任务描述
completed_teams = [t for t in teams if t['status'] == 'completed']
audit_context = []
audit_context.append(f'战役共 {len(teams)} 个 team，已完成 {len(completed_teams)} 个')
audit_context.append('')
audit_context.append('各 team 任务:')
for t in teams:
    status = '✓' if t['status'] == 'completed' else '⟳'
    audit_context.append(f'  {status} {t[\"id\"]}: {t[\"task\"]}')

if reports:
    audit_context.append('')
    audit_context.append('完成报告:')
    for r in reports:
        p = r.get('payload', {})
        audit_context.append(f'  [{r[\"from\"]}] {p.get(\"summary\", \"无摘要\")}')
        files = p.get('files_changed', [])
        if files:
            audit_context.append(f'    改动文件: {\", \".join(files)}')
        quality = p.get('quality', '')
        if quality:
            audit_context.append(f'    质量: {quality}')

audit_desc = '\n'.join(audit_context)
print(audit_desc)
print()
print('部署审计 team...')

# 部署审计 team
audit_task = f'''【审计任务】你是审计 team，负责最终质量把关。

战役概况:
{audit_desc}

审计步骤:
1. 运行 cargo check（Rust 编译检查）
2. 运行 cd gui && npx tsc --noEmit（TypeScript 类型检查）
3. 检查各 team 修改的文件，确认：
   - 无冲突或覆盖
   - 代码风格一致
   - 无遗留 TODO 或 debug 代码
   - 无安全问题（unwrap、硬编码密钥等）
4. 运行 git diff --stat 查看总体改动量
5. 向 L1 汇报审计结果:
   - 编译/类型检查是否通过
   - 发现的问题列表（按严重程度排序）
   - 修复建议
   - 如果有问题，直接修复后再汇报

汇报格式:
echo '{\"to\":\"L1\",\"type\":\"notify\",\"priority\":\"urgent\",\"payload\":{\"event\":\"audit_complete\",\"passed\":true/false,\"issues\":[],\"summary\":\"审计摘要\"}}' >> ''/team-AUDIT_TEAM_ID/outbox.jsonl
'''

result = subprocess.run(
    ['bash', '$0', audit_task],
    capture_output=True, text=True, cwd='$(pwd)'
)
print(result.stdout)
" "$@" 2>/dev/null
    ;;

  # ── 手动发消息 ──
  # ── 跨项目通信（直写目标项目的 CC inbox）──
  xmsg)
    if [[ $# -lt 3 ]]; then
      cat << 'XMSG_USAGE'
用法: legion.sh xmsg <目标项目名> "消息内容" [目标agent名]

示例:
  legion.sh xmsg <目标项目名> "跨项目情报内容"                 # 自动发给目标项目活跃 L1
  legion.sh xmsg <目标项目名> "情报内容" L1-<军团名>           # 指定目标 agent

查看所有项目:
  legion.sh xmsg list                                        # 列出全局军团名册

原理:
  消息携带 reply_to 回信地址，对方用同样命令回复
XMSG_USAGE
      exit 1
    fi

    # 子命令: list — 列出全局军团名册
    if [[ "$2" == "list" ]]; then
      python3 -c "
import json, os, time
d_path = os.path.expanduser('$LEGION_DIRECTORY')
if not os.path.exists(d_path):
    print('(军团名册为空)')
    exit()
with open(d_path) as f:
    data = json.load(f)
print('项目名 | Hash | CC Team | 最后活跃')
print('-------|------|---------|--------')
for l in data.get('legions', []):
    print(f\"{l['project']} | {l['hash']} | {l['cc_team']} | {l.get('last_active','?')[:19]}\")
" 2>/dev/null
      exit 0
    fi

    XTARGET_PROJECT="$2"
    XMESSAGE="$3"
    XTARGET_AGENT="${4:-}"

    # 从全局名册查找目标项目 hash
    XTARGET_HASH=$(python3 -c "
import json, os, sys
d_path = os.path.expanduser('$LEGION_DIRECTORY')
target = '$XTARGET_PROJECT'
if not os.path.exists(d_path):
    sys.exit(1)
with open(d_path) as f:
    data = json.load(f)
for l in data.get('legions', []):
    if l['project'] == target or l['hash'] == target or l['hash'].startswith(target):
        print(l['hash'])
        sys.exit(0)
sys.exit(1)
" 2>/dev/null)

    if [[ -z "$XTARGET_HASH" ]]; then
      echo "❌ 找不到项目 '$XTARGET_PROJECT'。运行 legion.sh xmsg list 查看可用项目。"
      exit 1
    fi

    # 如果没指定 agent，找首席 L1（第一个 commanding 的）
    # 多 L1 时只发给首席，由首席决定是否转派
    if [[ -z "$XTARGET_AGENT" ]]; then
      XTARGET_AGENT=$(python3 -c "
import json, os, sys, glob

# 查 registry，取第一个 commanding 的 L1（首席）
for base in [os.path.expanduser('~/.claude/legion'), '/tmp/claude-legion']:
    reg = os.path.join(base, '$XTARGET_HASH', 'registry.json')
    if os.path.exists(reg):
        with open(reg) as f:
            data = json.load(f)
        for t in data.get('teams', []):
            if t['id'].startswith('L1-') and t.get('status') in ('commanding', 'active', 'working'):
                print(t['id'])
                sys.exit(0)

# 查 CC inbox 目录兜底
inbox_dir = os.path.expanduser(f'~/.claude/teams/legion-$XTARGET_HASH/inboxes/')
if os.path.isdir(inbox_dir):
    for f in sorted(glob.glob(os.path.join(inbox_dir, 'L1-*.json'))):
        print(os.path.basename(f).replace('.json',''))
        sys.exit(0)

# 兜底
print('team-lead')
" 2>/dev/null)
    fi
    XSENDER="${CLAUDE_CODE_AGENT_NAME:-L1}"
    XSENDER_TEAM="legion-${PROJECT_HASH}"

    _XMSG_INBOX="$HOME/.claude/teams/legion-${XTARGET_HASH}/inboxes/${XTARGET_AGENT}.json" \
    _XMSG_FROM="${XSENDER}@${PROJECT_NAME}" \
    _XMSG_TEXT="$XMESSAGE" \
    _XMSG_REPLY_TO="${XSENDER_TEAM}/${XSENDER}" \
    python3 << 'XMSG_EOF'
import json, fcntl, os, time, uuid

inbox_path = os.environ['_XMSG_INBOX']
lock_path = inbox_path + '.lock'
msg = {
    'from': os.environ['_XMSG_FROM'],
    'text': os.environ['_XMSG_TEXT'],
    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'read': False,
    'color': 'magenta',
    'summary': f"[跨项目] {os.environ['_XMSG_FROM']}: {os.environ['_XMSG_TEXT'][:50]}",
    'reply_to': os.environ['_XMSG_REPLY_TO']
}

# 确保目录和文件存在
inbox_dir = os.path.dirname(inbox_path)
os.makedirs(inbox_dir, exist_ok=True)
if not os.path.exists(inbox_path):
    with open(inbox_path, 'w') as f:
        json.dump([], f)

# flock + read-modify-write (对齐 CC proper-lockfile 模式)
open(lock_path, 'a').close()
for attempt in range(10):
    try:
        with open(lock_path, 'r') as lf:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with open(inbox_path) as f:
                    messages = json.load(f)
                messages.append(msg)
                with open(inbox_path, 'w') as f:
                    json.dump(messages, f, ensure_ascii=False, indent=2)
                break
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    except (IOError, OSError):
        import random; time.sleep(0.005 + random.random() * 0.095)

print(f"消息已送达: {os.environ['_XMSG_FROM']} → {os.path.basename(inbox_path).replace('.json','')}")
print(f"回信地址: {os.environ['_XMSG_REPLY_TO']}")
print(f"对方回复命令: legion.sh xmsg {os.environ.get('PROJECT_HASH','')} {os.environ['_XMSG_FROM'].split('@')[0]} \"回复内容\"")
XMSG_EOF
    ;;

  msg)
    if [[ $# -lt 3 ]]; then
      echo "用法: legion.sh msg TEAM_ID \"消息内容\" [--from L1-xxx]"
      exit 1
    fi
    TARGET="$2"
    MESSAGE="$3"
    SENDER="${4:-L1}"

    if [[ "${4:-}" == "--from" ]]; then
      SENDER="${5:-L1}"
    fi

    # 统一写入目标 inbox.json（flock 安全，目标 hook 自动轮询接收）
    TARGET_DIR="$REGISTRY_DIR/team-$TARGET"
    mkdir -p "$TARGET_DIR"
    python3 -c "
import json, fcntl, time, uuid, os

inbox = '$TARGET_DIR/inbox.json'
lock = inbox + '.lock'
os.makedirs(os.path.dirname(inbox), exist_ok=True)
open(lock, 'a').close()

with open(lock) as lf:
    fcntl.flock(lf, fcntl.LOCK_EX)
    try:
        msgs = json.load(open(inbox))
    except:
        msgs = []
    msgs.append({
        'id': f'msg-{uuid.uuid4().hex[:8]}',
        'from': '$SENDER',
        'to': '$TARGET',
        'type': 'text',
        'payload': '''$MESSAGE''',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'read': False
    })
    json.dump(msgs, open(inbox, 'w'), ensure_ascii=False, indent=2)
    fcntl.flock(lf, fcntl.LOCK_UN)
" 2>/dev/null

    echo "[${SENDER} → ${TARGET}] 已投递到 inbox.json"

    # 急件：同时尝试 tmux 直注（目标空闲则立即送达）
    _safe_send "legion-${PROJECT_HASH}-${TARGET}" "收到来自 ${SENDER} 的消息：${MESSAGE:0:80}" "$TARGET" 2>/dev/null &
    ;;

  # ── 清理已完成的 team ──
  clean)
    _init_registry
    python3 -c "
import json, fcntl
with open('$REGISTRY', 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    before = len(data['teams'])
    data['teams'] = [t for t in data['teams'] if t['status'] != 'completed']
    after = len(data['teams'])
    f.seek(0); f.truncate()
    json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
print(f'清理完成: 移除 {before - after} 个已完成 team，剩余 {after} 个')
"
    ;;

  # ── 跨 session 僵尸 GC ──
  gc-zombies)
    python3 ~/.claude/scripts/legion-gc-cross.py "${@:2}"
    ;;

  # ── 全部终止 ──
  kill-all)
    # 停止 Watcher 守护进程
    WATCHER_PID_FILE="${REGISTRY_DIR}/watcher.pid"
    if [[ -f "$WATCHER_PID_FILE" ]]; then
      _wpid=$(cat "$WATCHER_PID_FILE" 2>/dev/null || echo "")
      if [[ -n "$_wpid" ]]; then
        kill "$_wpid" 2>/dev/null || true
        pkill -P "$_wpid" 2>/dev/null || true
      fi
      rm -f "$WATCHER_PID_FILE"
      echo "Watcher 已停止"
    fi

    # 停止 Commander
    if [[ -f "$COMMANDER_PID_FILE" ]]; then
      _pid=$(cat "$COMMANDER_PID_FILE" 2>/dev/null || echo "")
      if [[ -n "$_pid" ]]; then
        kill "$_pid" 2>/dev/null || true
      fi
      rm -f "$COMMANDER_PID_FILE"
    fi
    rm -f "$COMMANDER_HEARTBEAT_FILE"

    # 只杀本项目的军团 session（按 PROJECT_HASH 过滤，不影响其他项目）
    tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -E "^legion-${PROJECT_HASH}" | while read s; do
      tmux kill-session -t "$s" 2>/dev/null || true
    done

    echo '{"teams":[]}' > "$REGISTRY"
    echo '{"locks":[]}' > "$LOCKS_FILE"
    echo '{"spawns":[],"stats":{}}' > "$REGISTRY_DIR/spawn_tracker.json"

    # 仅当没有其他项目的军团在运行时才卸载全局 hooks
    OTHER_LEGIONS=$(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -E "^legion-" | grep -v "^legion-${PROJECT_HASH}" | wc -l | tr -d ' ')
    if [[ "$OTHER_LEGIONS" -eq 0 ]]; then
      _uninstall_hooks
      echo "本项目军团已全部关闭，无其他项目军团运行，hooks 已卸载"
    else
      echo "本项目军团已全部关闭（保留 hooks：其他项目仍有 ${OTHER_LEGIONS} 个军团 session 在运行）"
    fi
    ;;

  # ── L1 指挥官启动（优先 attach 后台运行的军团）──
  l1)
    # legion.sh l1         → attach 后台军团（轮询），无后台则新建
    # legion.sh l1 test    → attach/新建指定名称的指挥官
    CMD_NAME="${2:-}"

    _init_registry
    _init_comms
    _refresh_l1_registry

    if [[ -z "$CMD_NAME" ]]; then
      # 优先查找后台运行中的军团
      BACKGROUND_CMD=$(_find_background_l1)
      if [[ -n "$BACKGROUND_CMD" ]]; then
        CMD_SESSION="legion-${PROJECT_HASH}-${BACKGROUND_CMD}"
        # 记录本次 attach 的军团，下次轮到下一个
        echo "$BACKGROUND_CMD" > "$REGISTRY_DIR/l1-attach-cursor.txt"
        echo "================================================"
        echo "  载入后台军团: ${BACKGROUND_CMD}"
        echo "  Session: ${CMD_SESSION}"
        echo "================================================"
        exec tmux a -t "$CMD_SESSION"
      fi
      # 无后台军团，新建
      CMD_NAME=$(_gen_l1_name)
    fi

    CMD_ID="L1-${CMD_NAME}"
    CMD_SESSION="legion-${PROJECT_HASH}-${CMD_ID}"
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" register-commander claude "$CMD_ID" --session "$CMD_SESSION" --status commanding >/dev/null 2>&1 || true

    # 如果指定名称的 session 已存在（后台运行中），直接 attach
    if tmux has-session -t "$CMD_SESSION" 2>/dev/null; then
      # 检查是否已有窗口显示该军团
      EXISTING_CLIENTS=$(tmux list-clients -t "$CMD_SESSION" -F '#{client_tty}' 2>/dev/null)
      if [[ -n "$EXISTING_CLIENTS" ]]; then
        echo "  军团 ${CMD_ID} 已在窗口中显示:"
        echo "$EXISTING_CLIENTS" | sed 's/^/    /'
        echo "  如需新建军团请使用: legion.sh l1+1"
        exit 0
      fi
      echo "$CMD_ID" > "$REGISTRY_DIR/l1-attach-cursor.txt"
      echo "================================================"
      echo "  载入后台军团: ${CMD_ID}"
      echo "  Session: ${CMD_SESSION}"
      echo "================================================"
      exec tmux a -t "$CMD_SESSION"
    fi

    # session 不存在，新建军团
    _init_commander "$CMD_NAME"
    _write_system_prompt
    _install_hooks
    _start_commander

    tmux new-session -d -s "$CMD_SESSION" -c "$PROJECT_DIR" -n "${CMD_ID}"

    L1_PROMPT_FILE="$REGISTRY_DIR/prompt-${CMD_ID}.txt"
    _write_l1_prompt "$CMD_ID" "$CMD_SESSION"

    CMD_LAUNCH_SCRIPT="$REGISTRY_DIR/launch-${CMD_ID}.sh"
    cat > "$CMD_LAUNCH_SCRIPT" << LAUNCHEOF
#!/bin/bash
export CLAUDE_LEGION_TEAM_ID="${CMD_ID}"
export LEGION_DIR="${REGISTRY_DIR}"
export CLAUDE_CODE_TEAM_NAME="legion-${PROJECT_HASH}"
export CLAUDE_CODE_AGENT_NAME="${CMD_ID}"
PROMPT=\$(cat "$L1_PROMPT_FILE")
exec claude --dangerously-skip-permissions --effort max --append-system-prompt "\$PROMPT"
LAUNCHEOF
    chmod +x "$CMD_LAUNCH_SCRIPT"
    tmux send-keys -t "$CMD_SESSION:${CMD_ID}" "bash $CMD_LAUNCH_SCRIPT" Enter

    BOOT_SCRIPT="$REGISTRY_DIR/boot-${CMD_ID}.sh"
    cat > "$BOOT_SCRIPT" << 'BOOTEOF'
#!/bin/bash
TARGET_SESSION="$1"
TARGET_WINDOW="$2"
REGISTRY_DIR="$3"
BOOT_MSG="执行启动自检协议（强制），按以下步骤逐项检查并输出汇总表格：

1) Superpowers 技能：ls .claude/skills/*/SKILL.md 统计数量，确认 verification-before-completion/using-superpowers/writing-plans/recon/audit/agent-team/spec-driven 等核心技能全部存在。缺失则运行 npx skills add obra/superpowers -y
2) 指挥官注册表：cat ${REGISTRY_DIR}/registry.json，列出所有在线指挥官（status=commanding）
3) 文件锁：cat ${REGISTRY_DIR}/locks.json，检查是否有冲突
4) 协调通报：如有其他在线指挥官，向每个发送协调消息通报身份和工作范围；无则跳过
5) 收件箱：检查 inbox，处理未回复的消息
6) 本地技能库：ls .claude/skills/*/SKILL.md | wc -l 统计可用技能数
7) 全局战法库：ls ~/.claude/memory/tactics/ 统计战法数
8) 武器库巡检：bash ~/.claude/scripts/arsenal-check.sh quick — 完整性检查 + INDEX 重建 + 保存快照（bash ~/.claude/scripts/arsenal-check.sh snapshot）
9) 回顾官快扫：bash ~/.claude/scripts/retrospector.sh quick 2>/dev/null — 检查 observations/inspector/STATE 中是否有未提取的知识候选，有则报告数量
10) 专用 Agent 定义：ls .claude/agents/*.md 检查 implement/review/verify/explore/plan 是否存在。缺失则标记 CRITICAL — 没有 agent 定义无法组建团队，必须从参考项目复制或手动创建后才能接受 M 级以上任务
11) CLAUDE.md 流程规则：检查 CLAUDE.md 是否包含执行纪律（复杂度分级/流水线制/三层验证）。缺失或过时则标记 WARN — 指挥官需人工确认项目是否适用军团流程

最后输出 Markdown 汇总表格，格式如下：
| 检查项 | 状态 | 详情 |
|--------|------|------|
每项一行，状态用已安装/已确认/无冲突/空/就绪/CRITICAL/WARN等。有 CRITICAL 项必须先修复再接任务。"
for i in $(seq 1 30); do
  sleep 1
  if tmux capture-pane -t "${TARGET_SESSION}:${TARGET_WINDOW}" -p 2>/dev/null | grep -q '❯'; then
    sleep 1
    tmux send-keys -t "${TARGET_SESSION}:${TARGET_WINDOW}" "$BOOT_MSG" Enter
    exit 0
  fi
done
tmux send-keys -t "${TARGET_SESSION}:${TARGET_WINDOW}" "$BOOT_MSG" Enter
BOOTEOF
    chmod +x "$BOOT_SCRIPT"
    bash "$BOOT_SCRIPT" "$CMD_SESSION" "${CMD_ID}" "$REGISTRY_DIR" &

    echo "$CMD_ID" > "$REGISTRY_DIR/l1-attach-cursor.txt"
    echo "================================================"
    echo "  军团指挥官 ${CMD_ID} 已就位（新建）"
    echo "  Session: ${CMD_SESSION}"
    echo "  进入:    tmux a -t ${CMD_SESSION}"
    echo "================================================"

    exec tmux a -t "$CMD_SESSION"
    ;;

  # ── 联合指挥：大规模任务统一调度多军团 ──
  joint)
    JOINT_PLAN_ONLY=0
    JOINT_OBJECTIVE_ARGS=()
    shift
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --dry-run|--plan-only|--no-execute)
          JOINT_PLAN_ONLY=1
          shift
          ;;
        -h|--help)
          echo "用法: legion.sh joint [--dry-run|--plan-only] \"战略目标描述\""
          echo "  --dry-run / --plan-only  只生成作战计划，不执行分配"
          exit 0
          ;;
        --)
          shift
          while [[ $# -gt 0 ]]; do
            JOINT_OBJECTIVE_ARGS+=("$1")
            shift
          done
          ;;
        *)
          JOINT_OBJECTIVE_ARGS+=("$1")
          shift
          ;;
      esac
    done
    JOINT_OBJECTIVE="${JOINT_OBJECTIVE_ARGS[*]}"
    if [[ -z "$JOINT_OBJECTIVE" ]]; then
      echo "用法: legion.sh joint [--dry-run|--plan-only] \"战略目标描述\""
      exit 1
    fi

    _init_registry
    _init_comms
    _refresh_l1_registry

    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║           联合指挥 — 战役启动                      ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo ""
    echo "  战略目标: $JOINT_OBJECTIVE"
    echo ""

    # 1. 扫描所有在线军团状态
    JOINT_PLAN=$(python3 -c "
import json, subprocess

registry = '$REGISTRY'
project_hash = '$PROJECT_HASH'

with open(registry) as f:
    data = json.load(f)

available = []
busy = []

for t in data.get('teams', []):
    if not t['id'].startswith('L1-') or t.get('status') != 'commanding':
        continue
    cmd_id = t['id']
    session_name = f'legion-{project_hash}-{cmd_id}'

    # 检查是否空闲（看屏幕有没有 ❯ 提示符在等输入）
    try:
        result = subprocess.run(
            ['tmux', 'capture-pane', '-t', session_name, '-p'],
            capture_output=True, text=True, timeout=5
        )
        screen = result.stdout.strip()
        last_lines = screen.split('\n')[-5:]
        is_idle = any('❯' in l for l in last_lines)

        # 获取上下文摘要（最后 30 行）
        context = '\n'.join(screen.split('\n')[-30:])[:500]

        if is_idle:
            available.append({'id': cmd_id, 'context': context})
        else:
            busy.append({'id': cmd_id})
    except:
        pass

print(json.dumps({'available': available, 'busy': busy}, ensure_ascii=False))
" 2>/dev/null)

    AVAIL_COUNT=$(echo "$JOINT_PLAN" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['available']))" 2>/dev/null)
    BUSY_COUNT=$(echo "$JOINT_PLAN" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['busy']))" 2>/dev/null)

    echo "  在线军团: 空闲 ${AVAIL_COUNT} / 忙碌 ${BUSY_COUNT}"
    echo ""

    # 2. 用 claude 分析目标，匹配军团，拆解方向
    JOINT_ANALYSIS=$(echo "$JOINT_PLAN" | python3 -c "
import sys, json
plan = json.load(sys.stdin)
avail = plan['available']
avail_summary = '\n'.join([f'- {a[\"id\"]}: {a[\"context\"][:200]}' for a in avail])
print(avail_summary)
" 2>/dev/null)

    echo "  正在分析战略目标，拆解作战方向..."
    echo ""

    # 获取项目结构摘要
    PROJECT_STRUCTURE=$(find "$PROJECT_DIR" -maxdepth 3 -type d \
      -not -path '*/node_modules/*' -not -path '*/.git/*' \
      -not -path '*/target/*' -not -path '*/__pycache__/*' \
      -not -path '*/dist/*' -not -path '*/.cache/*' \
      2>/dev/null | head -50 | sed "s|$PROJECT_DIR/||")

    ASSIGNMENT=$(claude -p "你是联合指挥官。根据战略目标、项目结构和可用军团，制定最高效的作战计划。

战略目标：$JOINT_OBJECTIVE

项目目录结构：
$PROJECT_STRUCTURE

可用空闲军团及其当前上下文：
$JOINT_ANALYSIS

组建原则（严格遵守）：
1. 只复用上下文高度匹配的空闲军团（该军团之前在做的事和新方向直接相关）
2. 上下文不匹配的军团不要分配任务，标记为 NEW 新建
3. 根据项目结构科学拆分方向（如：前端/Rust后端/Python脚本/测试 各一个方向）
4. 每个方向的文件范围必须明确且不重叠
5. 方向数量按实际需要，不多不少
6. 标注方向之间的依赖关系（哪些可以并行，哪些需要等待）
7. 给每个方向明确的验收标准

输出 JSON（不要其他内容）：
{
  \"directions\": [
    {
      \"legion\": \"L1-xxx军团（上下文匹配时）或 NEW\",
      \"role\": \"该方向的角色定位（如：前端工程组/后端工程组/脚本工程组/测试组）\",
      \"mission\": \"具体任务描述\",
      \"file_scope\": [\"负责的目录/文件范围\"],
      \"depends_on\": [\"依赖的其他方向角色，空数组表示可立即并行\"],
      \"acceptance\": \"该方向的验收标准\"
    }
  ],
  \"overall_acceptance\": \"整体验收标准（所有方向完成后）\",
  \"estimated_parallel_groups\": \"可并行的组数\"
}" --max-turns 1 2>/dev/null)

    echo "$ASSIGNMENT" | python3 -c "
import sys, json, re

text = sys.stdin.read()
match = re.search(r'\{.*\}', text, re.DOTALL)
if not match:
    print('  ⚠ 分析失败，请手动分配')
    sys.exit(1)

plan = json.loads(match.group())
directions = plan.get('directions', [])
reuse = sum(1 for d in directions if d.get('legion', 'NEW') != 'NEW')
new = sum(1 for d in directions if d.get('legion', 'NEW') == 'NEW')
parallel = plan.get('estimated_parallel_groups', '?')

print('  ═══ 作战计划 ═══')
print(f'  共 {len(directions)} 个方向 | 复用 {reuse} + 新建 {new} | 可并行 {parallel} 组')
print()

for i, d in enumerate(directions, 1):
    legion = d.get('legion', 'NEW')
    role = d.get('role', '')
    mission = d.get('mission', '')
    scope = d.get('file_scope', [])
    deps = d.get('depends_on', [])
    accept = d.get('acceptance', '')
    tag = '🔄 复用' if legion != 'NEW' else '🆕 新建'

    print(f'  方向{i} [{tag}] {legion}')
    print(f'    角色: {role}')
    print(f'    任务: {mission}')
    if scope:
        print(f'    范围: {\" | \".join(scope)}')
    if deps:
        print(f'    依赖: {\" → \".join(deps)}（需等待）')
    else:
        print(f'    依赖: 无（可立即并行）')
    if accept:
        print(f'    验收: {accept}')
    print()

overall = plan.get('overall_acceptance', '')
if overall:
    print(f'  整体验收: {overall}')
    print()

with open('/tmp/legion-joint-plan.json', 'w') as f:
    json.dump(plan, f, ensure_ascii=False, indent=2)
" 2>/dev/null

    echo ""
    if [[ "$JOINT_PLAN_ONLY" == "1" ]]; then
      echo "  只生成计划模式：已写入 /tmp/legion-joint-plan.json，未执行分配"
      exit 0
    fi
    echo "  非交互模式：默认执行作战计划"

    # 3. 执行分配：复用军团直接 tmux send-keys，新建军团用 l1+1
    echo ""
    echo "  ═══ 执行分配 ═══"

    if [[ -f /tmp/legion-joint-plan.json ]]; then
      PROJECT_HASH="$PROJECT_HASH" PROJECT_DIR="$PROJECT_DIR" REGISTRY_DIR="$REGISTRY_DIR" python3 << 'JOINT_EXEC'
import json, subprocess, os, time

plan_file = '/tmp/legion-joint-plan.json'
project_hash = os.environ.get('PROJECT_HASH', '')
project_dir = os.environ.get('PROJECT_DIR', '')
registry_dir = os.environ.get('REGISTRY_DIR', '')
legion_sh = os.path.expanduser('~/.claude/scripts/legion.sh')

# 修正变量（环境缺失或异常时的兜底）
if not project_dir or '$' in project_dir:
    project_dir = os.getcwd()

if not project_hash or '$' in project_hash:
    import hashlib
    project_hash = hashlib.md5(project_dir.encode()).hexdigest()[:8]

if not registry_dir or '$' in registry_dir:
    registry_dir = os.path.expanduser(f'~/.claude/legion/{project_hash}')

with open(plan_file) as f:
    plan = json.load(f)

for i, d in enumerate(plan.get('directions', []), 1):
    legion = d.get('legion', 'NEW')
    role = d.get('role', f'方向{i}')
    mission = d.get('mission', '')
    scope = d.get('file_scope', [])
    acceptance = d.get('acceptance', '')

    full_mission = f'【联合指挥令 — {role}】\n任务: {mission}'
    if scope:
        full_mission += f'\n文件范围: {", ".join(scope)}'
    if acceptance:
        full_mission += f'\n验收标准: {acceptance}'
    full_mission += '\n\n此任务为联合指挥最高优先级。按正常流程执行（侦察→方案→执行→审计），完成后汇报。'

    if legion == 'NEW':
        # 新建军团：用 tmux 在后台创建
        print(f'  🆕 方向{i} [{role}] 新建军团...')
        # 直接调用 l1+1 的核心逻辑：创建 session + 启动 claude
        result = subprocess.run(
            ['bash', '-c', f'cd {project_dir} && TMUX= {legion_sh} l1+1 2>&1 | head -20'],
            capture_output=True, text=True, timeout=60
        )
        # 从输出提取军团 ID
        new_id = None
        for line in result.stdout.split('\n'):
            if '军团指挥官' in line and '已就位' in line:
                for word in line.split():
                    if word.startswith('L1-'):
                        new_id = word
                        break
        if not new_id:
            print(f'    ⚠ 新建失败，输出: {result.stdout[:200]}')
            continue
        legion = new_id
        print(f'    → {legion}')
        # 等新军团 claude 启动
        time.sleep(8)

    session_name = f'legion-{project_hash}-{legion}'

    # 写入 inbox（留痕）
    import uuid
    from datetime import datetime
    msg = json.dumps({
        'from': '联合指挥',
        'type': 'notify',
        'priority': 'urgent',
        'payload': {
            'event': 'joint_command_mission',
            'message': full_mission
        }
    }, ensure_ascii=False)
    inbox_path = f'{registry_dir}/team-{legion}/inbox.jsonl'
    os.makedirs(os.path.dirname(inbox_path), exist_ok=True)
    with open(inbox_path, 'a') as f:
        f.write(msg + '\n')

    # tmux send-keys 直接驱动
    try:
        subprocess.run(
            ['tmux', 'send-keys', '-t', session_name, full_mission, 'Enter'],
            capture_output=True, timeout=5
        )
        print(f'  ✅ {legion} [{role}] ← {mission[:50]}...')
    except Exception as e:
        print(f'  ⚠ {legion} 分配失败: {e}')

JOINT_EXEC
    fi

    # 4. 通知所有在线军团：联合指挥已接管
    python3 -c "
import json, subprocess, os

registry = '$REGISTRY'
registry_dir = '$REGISTRY_DIR'
project_hash = '$PROJECT_HASH'
objective = '''$JOINT_OBJECTIVE'''

with open(registry) as f:
    data = json.load(f)

# 读取被选中的军团列表
selected = set()
try:
    with open('/tmp/legion-joint-plan.json') as f:
        plan = json.load(f)
    for d in plan.get('directions', []):
        leg = d.get('legion', '')
        if leg != 'NEW' and leg.startswith('L1-'):
            selected.add(leg)
except:
    pass

for t in data.get('teams', []):
    if not t['id'].startswith('L1-') or t.get('status') != 'commanding':
        continue
    cmd_id = t['id']
    session_name = f'legion-{project_hash}-{cmd_id}'

    if cmd_id in selected:
        # 已被分配任务的军团（通过之前的 tmux send-keys 已经收到了）
        continue

    # 未被选中的军团：通知联合指挥已接管
    msg = f'【联合指挥通知】联合指挥官已接管任务「{objective[:50]}」。你未被编入此次作战序列，继续执行你原有的任务或等待用户新指令。'
    inbox_path = f'{registry_dir}/team-{cmd_id}/inbox.jsonl'
    import uuid
    from datetime import datetime
    entry = json.dumps({
        'from': '联合指挥',
        'type': 'notify',
        'priority': 'normal',
        'payload': {
            'event': 'joint_command_info',
            'message': msg
        }
    }, ensure_ascii=False)
    with open(inbox_path, 'a') as f:
        f.write(entry + '\n')
" 2>/dev/null

    # 5. 创建作战室：tmux 分屏展示所有参战军团
    python3 -c "
import json, subprocess, os

project_hash = '$PROJECT_HASH'
session = '$SESSION'

try:
    with open('/tmp/legion-joint-plan.json') as f:
        plan = json.load(f)
except:
    plan = {'directions': []}

# 收集所有参战军团的 session 名
participants = []
for d in plan.get('directions', []):
    leg = d.get('legion', '')
    if leg.startswith('L1-'):
        sess = f'legion-{project_hash}-{leg}'
        role = d.get('role', '')
        participants.append((sess, leg, role))

if not participants:
    exit(0)

# 在基座 session 创建 'war-room' window
base_session = f'legion-{project_hash}-{os.path.basename(os.getcwd())}'

# 先尝试删除旧的 war-room
subprocess.run(['tmux', 'kill-window', '-t', f'{base_session}:war-room'],
               capture_output=True, timeout=3)

# 创建 war-room window，第一个 pane attach 到第一个参战军团
first_sess, first_id, first_role = participants[0]
subprocess.run([
    'tmux', 'new-window', '-t', base_session, '-n', 'war-room',
    f'tmux a -t {first_sess}'
], capture_output=True, timeout=5)

# 后续参战军团用 split-pane
for i, (sess, leg_id, role) in enumerate(participants[1:], 1):
    # 交替水平/垂直分割
    split_flag = '-h' if i % 2 == 1 else '-v'
    subprocess.run([
        'tmux', 'split-window', split_flag, '-t', f'{base_session}:war-room',
        f'tmux a -t {sess}'
    ], capture_output=True, timeout=5)

# 均匀分布 panes
subprocess.run(['tmux', 'select-layout', '-t', f'{base_session}:war-room', 'tiled'],
               capture_output=True, timeout=3)

print(f'  作战室已创建: {len(participants)} 个分屏')
for sess, leg_id, role in participants:
    print(f'    {leg_id} [{role}]')
" 2>/dev/null

    echo ""
    echo "  ═══ 联合指挥已启动 ═══"
    echo "  作战室: tmux a -t ${SESSION} 然后切换到 war-room 窗口"
    echo "  快捷键: Ctrl-b w 选择 war-room 窗口查看所有参战军团"
    echo "  态势: legion.sh sitrep"
    echo ""
    ;;

  # ── 作战室：进入联合指挥的多军团分屏视图 ──
  war-room)
    BASE_SESSION="legion-${PROJECT_HASH}-${PROJECT_NAME}"
    if tmux has-session -t "$BASE_SESSION" 2>/dev/null; then
      # 检查 war-room 窗口是否存在
      if tmux list-windows -t "$BASE_SESSION" -F '#{window_name}' 2>/dev/null | grep -q '^war-room$'; then
        echo "  进入作战室..."
        exec tmux a -t "$BASE_SESSION:war-room"
      else
        echo "  作战室不存在。先用 legion.sh joint \"目标\" 启动联合指挥。"
      fi
    else
      echo "  基座 session 不存在。"
    fi
    ;;

  # ── L1 强制新建指挥官 ──
  l1+1)
    # legion.sh l1+1        → 强制创建全新军团
    # legion.sh l1+1 test   → 强制创建指定名称的军团
    CMD_NAME="${2:-}"

    _init_registry
    _init_comms
    _refresh_l1_registry

    if [[ -z "$CMD_NAME" ]]; then
      CMD_NAME=$(_gen_l1_name)
    fi
    CMD_ID="L1-${CMD_NAME}"
    CMD_SESSION="legion-${PROJECT_HASH}-${CMD_ID}"
    python3 "$LEGION_SCRIPT_DIR/legion_core.py" register-commander claude "$CMD_ID" --session "$CMD_SESSION" --status commanding >/dev/null 2>&1 || true

    _init_commander "$CMD_NAME"
    _write_system_prompt
    _install_hooks
    _start_commander

    if ! tmux has-session -t "$CMD_SESSION" 2>/dev/null; then
      tmux new-session -d -s "$CMD_SESSION" -c "$PROJECT_DIR" -n "${CMD_ID}"

      L1_PROMPT_FILE="$REGISTRY_DIR/prompt-${CMD_ID}.txt"
      _write_l1_prompt "$CMD_ID" "$CMD_SESSION"

      CMD_LAUNCH_SCRIPT="$REGISTRY_DIR/launch-${CMD_ID}.sh"
      cat > "$CMD_LAUNCH_SCRIPT" << LAUNCHEOF
#!/bin/bash
export CLAUDE_LEGION_TEAM_ID="${CMD_ID}"
export LEGION_DIR="${REGISTRY_DIR}"
export CLAUDE_CODE_TEAM_NAME="legion-${PROJECT_HASH}"
export CLAUDE_CODE_AGENT_NAME="${CMD_ID}"
PROMPT=\$(cat "$L1_PROMPT_FILE")
exec claude --dangerously-skip-permissions --effort max --append-system-prompt "\$PROMPT"
LAUNCHEOF
      chmod +x "$CMD_LAUNCH_SCRIPT"
      tmux send-keys -t "$CMD_SESSION:${CMD_ID}" "bash $CMD_LAUNCH_SCRIPT" Enter

      BOOT_SCRIPT="$REGISTRY_DIR/boot-${CMD_ID}.sh"
      cat > "$BOOT_SCRIPT" << 'BOOTEOF'
#!/bin/bash
TARGET_SESSION="$1"
TARGET_WINDOW="$2"
REGISTRY_DIR="$3"
BOOT_MSG="执行启动自检协议（强制），按以下步骤逐项检查并输出汇总表格：

1) Superpowers 技能：ls .claude/skills/*/SKILL.md 统计数量，确认 verification-before-completion/using-superpowers/writing-plans/recon/audit/agent-team/spec-driven 等核心技能全部存在。缺失则运行 npx skills add obra/superpowers -y
2) 指挥官注册表：cat ${REGISTRY_DIR}/registry.json，列出所有在线指挥官（status=commanding）
3) 文件锁：cat ${REGISTRY_DIR}/locks.json，检查是否有冲突
4) 协调通报：如有其他在线指挥官，向每个发送协调消息通报身份和工作范围；无则跳过
5) 收件箱：检查 inbox，处理未回复的消息
6) 本地技能库：ls .claude/skills/*/SKILL.md | wc -l 统计可用技能数
7) 全局战法库：ls ~/.claude/memory/tactics/ 统计战法数
8) 武器库巡检：bash ~/.claude/scripts/arsenal-check.sh quick — 完整性检查 + INDEX 重建 + 保存快照（bash ~/.claude/scripts/arsenal-check.sh snapshot）
9) 回顾官快扫：bash ~/.claude/scripts/retrospector.sh quick 2>/dev/null — 检查 observations/inspector/STATE 中是否有未提取的知识候选，有则报告数量
10) 专用 Agent 定义：ls .claude/agents/*.md 检查 implement/review/verify/explore/plan 是否存在。缺失则标记 CRITICAL — 没有 agent 定义无法组建团队，必须从参考项目复制或手动创建后才能接受 M 级以上任务
11) CLAUDE.md 流程规则：检查 CLAUDE.md 是否包含执行纪律（复杂度分级/流水线制/三层验证）。缺失或过时则标记 WARN — 指挥官需人工确认项目是否适用军团流程

最后输出 Markdown 汇总表格，格式如下：
| 检查项 | 状态 | 详情 |
|--------|------|------|
每项一行，状态用已安装/已确认/无冲突/空/就绪/CRITICAL/WARN等。有 CRITICAL 项必须先修复再接任务。"
for i in $(seq 1 30); do
  sleep 1
  if tmux capture-pane -t "${TARGET_SESSION}:${TARGET_WINDOW}" -p 2>/dev/null | grep -q '❯'; then
    sleep 1
    tmux send-keys -t "${TARGET_SESSION}:${TARGET_WINDOW}" "$BOOT_MSG" Enter
    exit 0
  fi
done
tmux send-keys -t "${TARGET_SESSION}:${TARGET_WINDOW}" "$BOOT_MSG" Enter
BOOTEOF
      chmod +x "$BOOT_SCRIPT"
      bash "$BOOT_SCRIPT" "$CMD_SESSION" "${CMD_ID}" "$REGISTRY_DIR" &
    fi

    echo "================================================"
    echo "  军团指挥官 ${CMD_ID} 已就位（新建）"
    echo "  Session: ${CMD_SESSION}"
    echo "  进入:    tmux a -t ${CMD_SESSION}"
    echo "  共享:    Commander (teams:commander)"
    echo "================================================"

    exec tmux a -t "$CMD_SESSION"
    ;;

  # ── 启动新 team ──
  *)
    # 解析 --commander 参数
    PARENT_COMMANDER="L1"
    TASK_ARGS=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --commander)
          PARENT_COMMANDER="$2"
          shift 2
          ;;
        *)
          TASK_ARGS+=("$1")
          shift
          ;;
      esac
    done
    TASK="${TASK_ARGS[*]}"
    [[ "$ACTION" == "launch" ]] && TASK=""

    _init_registry
    _init_comms
    _init_commander ""
    _write_system_prompt

    # 安装 hooks（幂等）
    _install_hooks

    # 启动 Commander（幂等 + 心跳自愈）
    _start_commander

    TEAM_ID=$(_gen_id)

    # 注册到注册表（带 parent_commander 信息）
    _register_team "$TEAM_ID" "$TASK"
    # 追加 parent_commander 字段
    python3 -c "
import json, fcntl
path = '$REGISTRY'
with open(path, 'r+') as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    for t in data['teams']:
        if t['id'] == '$TEAM_ID':
            t['parent'] = '$PARENT_COMMANDER'
    f.seek(0); f.truncate()
    json.dump(data, f, ensure_ascii=False, indent=2)
    fcntl.flock(f, fcntl.LOCK_UN)
" 2>/dev/null

    # 创建通信目录
    _init_team_comms "$TEAM_ID"

    # 确定 team 应该放在哪个 tmux session
    # 有指挥官 → 放到指挥官的独立 session 里
    # 无指挥官 → 放到公共 session "teams" 里
    TEAM_SESSION="legion-${PROJECT_HASH}-${PARENT_COMMANDER}"
    if ! tmux has-session -t "$TEAM_SESSION" 2>/dev/null; then
      # 指挥官 session 不存在，放到公共 session
      TEAM_SESSION="$SESSION"
      if ! tmux has-session -t "$TEAM_SESSION" 2>/dev/null; then
        tmux new-session -d -s "$TEAM_SESSION" -c "$PROJECT_DIR" -n "commander"
        TEAM_COMMANDER_SCRIPT="$(_legion_commander_script)" || {
          echo "错误: Commander 脚本不存在（已查 scripts/ 与 ~/.claude/scripts/）" >&2
          exit 1
        }
        tmux send-keys -t "$TEAM_SESSION:commander" "LEGION_DIR=$REGISTRY_DIR python3 $TEAM_COMMANDER_SCRIPT" Enter
        sleep 0.5
      fi
    fi
    tmux new-window -t "$TEAM_SESSION:" -n "w-$TEAM_ID" -c "$PROJECT_DIR"

    # 将 TEAM_ID 和 COMMANDER_ID 注入系统提示
    TEAM_PROMPT_FILE="$REGISTRY_DIR/prompt-$TEAM_ID.txt"
    sed -e "s/MY_TEAM_ID/$TEAM_ID/g" -e "s/MY_COMMANDER_ID/$PARENT_COMMANDER/g" -e "s|''|$REGISTRY_DIR|g" "$SYSTEM_PROMPT_FILE" > "$TEAM_PROMPT_FILE"

    # 生成启动脚本（避免 prompt 内容的特殊字符破坏 shell 解析）
    TEAM_LAUNCH_SCRIPT="$REGISTRY_DIR/launch-$TEAM_ID.sh"
    cat > "$TEAM_LAUNCH_SCRIPT" << LAUNCHEOF
#!/bin/bash
export CLAUDE_LEGION_TEAM_ID="$TEAM_ID"
export LEGION_DIR="$REGISTRY_DIR"
export CLAUDE_CODE_TEAM_NAME="legion-${PROJECT_HASH}"
export CLAUDE_CODE_AGENT_NAME="$TEAM_ID"
PROMPT=\$(cat "$TEAM_PROMPT_FILE")
exec claude --dangerously-skip-permissions --effort high --append-system-prompt "\$PROMPT"
LAUNCHEOF
    chmod +x "$TEAM_LAUNCH_SCRIPT"
    tmux send-keys -t "$TEAM_SESSION:w-$TEAM_ID" "bash $TEAM_LAUNCH_SCRIPT" Enter

    echo "================================================"
    echo "  军团 Team 已部署"
    echo "  ID:        $TEAM_ID"
    echo "  隶属:      $PARENT_COMMANDER"
    echo "  Session:   $TEAM_SESSION"
    echo "  Window:    w-$TEAM_ID"
    echo "================================================"
    echo ""
    echo "进入:   tmux a -t $TEAM_SESSION"
    echo "状态:   legion.sh status"
    echo "发消息: legion.sh msg $TEAM_ID \"内容\""
    ;;

esac
