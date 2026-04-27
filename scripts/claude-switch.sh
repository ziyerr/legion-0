#!/bin/bash
# ============================================================================
# claude-switch.sh — Claude Code 账号快速切换
# ============================================================================
# 管理多个 Claude 账号（Pro/Max/Team），在 Claude Code 关闭后秒级切换。
#
# 合规边界：
# - 仅适用于你合法拥有的独立账号（个人+工作+团队共享账号等）
# - 禁止：账号共享、批量小号刻意规避限额
# - Anthropic TOS 允许一人持有多账号的合理场景
#
# 用法:
#   claude-switch save <name>     — 保存当前登录状态为 profile
#   claude-switch use <name>      — 切换到 profile (Claude Code 必须先关闭)
#   claude-switch list            — 列出所有 profile
#   claude-switch current         — 显示当前登录账号
#   claude-switch delete <name>   — 删除 profile
#   claude-switch status          — 显示所有 profile 使用量
#
# 存储: ~/.claude/account-profiles/
# ============================================================================

set -euo pipefail

PROFILES_DIR="$HOME/.claude/account-profiles"
CLAUDE_JSON="$HOME/.claude.json"
KEYCHAIN_SERVICE="Claude Code-credentials"
KEYCHAIN_ACCOUNT="${USER}"

mkdir -p "$PROFILES_DIR"
chmod 700 "$PROFILES_DIR"

# ── 验证切换是否生效（通过 claude auth status）──
_verify_switch() {
  local expected_email="$1"
  if ! command -v claude >/dev/null 2>&1; then
    return 0  # claude CLI 不可用时跳过验证
  fi
  local actual
  actual=$(claude auth status 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('email', ''))
except: pass
" 2>/dev/null)
  if [[ -n "$actual" ]] && [[ "$actual" == "$expected_email" ]]; then
    echo "  ✓ 验证通过 (claude auth status: $actual)"
    return 0
  elif [[ -n "$actual" ]]; then
    echo "  ⚠️  当前 claude auth status 仍显示: $actual"
    echo "     Keychain 已切换，但 Claude Code 进程可能缓存了旧 token"
    echo "     建议：在 Claude Code 内运行 /login 或发送下一条消息触发 refresh"
    return 1
  fi
}

# ── 读取 Keychain OAuth ──
_read_keychain() {
  security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null || echo ""
}

# ── 写入 Keychain ──
_write_keychain() {
  local oauth_json="$1"
  # security 命令的 stdout 会打印 keychain info，必须同时屏蔽
  security delete-generic-password -s "$KEYCHAIN_SERVICE" >/dev/null 2>&1 || true
  security add-generic-password \
    -s "$KEYCHAIN_SERVICE" \
    -a "$KEYCHAIN_ACCOUNT" \
    -w "$oauth_json" \
    -U >/dev/null 2>&1
}

# ── save: 保存当前账号为 profile ──
cmd_save() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    echo "用法: claude-switch save <name>"
    exit 1
  fi

  # 验证名称安全
  if ! [[ "$name" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "错误: 名称只能包含字母/数字/下划线/横杠"
    exit 1
  fi

  # 读 Keychain
  local oauth
  oauth=$(_read_keychain)
  if [[ -z "$oauth" ]]; then
    echo "错误: Keychain 中未找到 '$KEYCHAIN_SERVICE' 凭据"
    echo "请先在 Claude Code 中 /login"
    exit 1
  fi

  # 读 .claude.json 的账号字段
  if [[ ! -f "$CLAUDE_JSON" ]]; then
    echo "错误: $CLAUDE_JSON 不存在"
    exit 1
  fi

  local profile_file="$PROFILES_DIR/${name}.json"

  # 通过环境变量传递 JSON，避免 heredoc 转义问题
  export _CS_OAUTH_JSON="$oauth"
  export _CS_CLAUDE_JSON="$CLAUDE_JSON"
  export _CS_PROFILE_FILE="$profile_file"
  export _CS_NAME="$name"

  python3 << 'PYEOF'
import json, os
from datetime import datetime, timezone

claude_json_path = os.environ['_CS_CLAUDE_JSON']
profile_file = os.environ['_CS_PROFILE_FILE']
name = os.environ['_CS_NAME']
oauth_raw = os.environ['_CS_OAUTH_JSON']

# 读 .claude.json
with open(claude_json_path) as f:
    claude_data = json.load(f)

# 解析 Keychain OAuth
keychain_oauth = json.loads(oauth_raw)

# 提取账号字段
oauth_account = claude_data.get("oauthAccount", {})
email = oauth_account.get("emailAddress", "unknown")
display = oauth_account.get("displayName", "unknown")
sub_type = keychain_oauth.get("claudeAiOauth", {}).get("subscriptionType", "unknown")
rate_tier = keychain_oauth.get("claudeAiOauth", {}).get("rateLimitTier", "unknown")

# 构建 profile
profile = {
    "name": name,
    "email": email,
    "display_name": display,
    "subscription_type": sub_type,
    "rate_limit_tier": rate_tier,
    "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "keychain_oauth": keychain_oauth,
    "account_fields": {
        "oauthAccount": oauth_account,
        "userID": claude_data.get("userID", ""),
        "hasAvailableSubscription": claude_data.get("hasAvailableSubscription", False),
    }
}

# 写入 profile 文件（权限 600）
with open(profile_file, "w") as f:
    json.dump(profile, f, ensure_ascii=False, indent=2)
os.chmod(profile_file, 0o600)

print(f"✓ 已保存 profile: {name}")
print(f"  邮箱: {email}")
print(f"  姓名: {display}")
print(f"  订阅: {sub_type} ({rate_tier})")
print(f"  文件: {profile_file}")
PYEOF

  unset _CS_OAUTH_JSON _CS_CLAUDE_JSON _CS_PROFILE_FILE _CS_NAME

  # 记录为当前
  echo "$name" > "$PROFILES_DIR/.current"
}

# ── use: 切换到 profile ──
cmd_use() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    echo "用法: claude-switch use <name>"
    exit 1
  fi

  local profile_file="$PROFILES_DIR/${name}.json"
  if [[ ! -f "$profile_file" ]]; then
    echo "错误: profile '$name' 不存在"
    echo "可用 profile:"
    cmd_list
    exit 1
  fi

  # 读 profile，提取 keychain oauth JSON
  local oauth_json
  export _CS_PROFILE_FILE="$profile_file"
  oauth_json=$(python3 -c "
import json, os
with open(os.environ['_CS_PROFILE_FILE']) as f:
    p = json.load(f)
print(json.dumps(p['keychain_oauth']))
" 2>/dev/null)

  if [[ -z "$oauth_json" ]]; then
    echo "错误: profile 文件损坏"
    exit 1
  fi

  # 写入 Keychain
  _write_keychain "$oauth_json"

  # 更新 .claude.json 的账号字段
  export _CS_CLAUDE_JSON="$CLAUDE_JSON"
  python3 << 'PYEOF'
import json, os, tempfile

profile_file = os.environ['_CS_PROFILE_FILE']
claude_json_path = os.environ['_CS_CLAUDE_JSON']

with open(profile_file) as f:
    profile = json.load(f)

with open(claude_json_path) as f:
    claude_data = json.load(f)

# 替换账号字段
fields = profile['account_fields']
claude_data['oauthAccount'] = fields['oauthAccount']
claude_data['userID'] = fields['userID']
claude_data['hasAvailableSubscription'] = fields['hasAvailableSubscription']

# 清除可能过期的订阅缓存
for stale_key in ['passesEligibilityCache', 'overageCreditGrantCache',
                  'cachedExtraUsageDisabledReason', 's1mAccessCache']:
    if stale_key in claude_data:
        del claude_data[stale_key]

# 原子写入
tmp = tempfile.NamedTemporaryFile('w', dir=os.path.dirname(claude_json_path),
                                    delete=False, suffix='.tmp')
json.dump(claude_data, tmp, ensure_ascii=False, indent=2)
tmp.close()
os.chmod(tmp.name, 0o600)
os.replace(tmp.name, claude_json_path)
PYEOF
  unset _CS_PROFILE_FILE _CS_CLAUDE_JSON

  # 记录当前 profile
  echo "$name" > "$PROFILES_DIR/.current"

  # 读 profile 元数据展示
  export _CS_PROFILE_FILE="$profile_file"
  local target_email
  target_email=$(python3 -c "
import json, os
with open(os.environ['_CS_PROFILE_FILE']) as f:
    p = json.load(f)
print(p['email'])
" 2>/dev/null)
  python3 -c "
import json, os
with open(os.environ['_CS_PROFILE_FILE']) as f:
    p = json.load(f)
print(f'✅ 已切换到: {p[\"name\"]}')
print(f'  邮箱: {p[\"email\"]}')
print(f'  姓名: {p[\"display_name\"]}')
print(f'  订阅: {p[\"subscription_type\"]} ({p[\"rate_limit_tier\"]})')
" 2>/dev/null
  unset _CS_PROFILE_FILE

  # 验证切换是否生效
  echo ""
  _verify_switch "$target_email" || {
    echo ""
    echo "  如果 Claude Code 运行中未自动感知:"
    echo "  1) 在 Claude Code 内发送任意消息（会触发 token 重读）"
    echo "  2) 或运行 /login 强制刷新"
    echo "  3) 或完全退出 Claude Code 后重启"
  }
}

# ── list: 列出所有 profile（含 token 过期 + 本月用量） ──
cmd_list() {
  if [[ ! -d "$PROFILES_DIR" ]] || [[ -z "$(ls -A "$PROFILES_DIR"/*.json 2>/dev/null)" ]]; then
    echo "(无 profile)"
    return
  fi

  local current=""
  [[ -f "$PROFILES_DIR/.current" ]] && current=$(cat "$PROFILES_DIR/.current")

  # 收集当前账号的动态数据
  local block_cache="$HOME/.claude/ccusage-cache.json"
  local usage_cache="$HOME/.claude/usage-cache.json"

  # 刷新 block cache（2分钟，带空文件保护）
  local block_size=0
  [[ -f "$block_cache" ]] && block_size=$(stat -f %z "$block_cache" 2>/dev/null || stat -c %s "$block_cache" 2>/dev/null || echo 0)
  if [[ "$block_size" -eq 0 ]] || [[ $(($(date +%s) - $(stat -f %m "$block_cache" 2>/dev/null || stat -c %Y "$block_cache" 2>/dev/null || echo 0))) -gt 120 ]]; then
    local tmp
    tmp=$(ccusage blocks --json 2>/dev/null)
    if [[ -n "$tmp" ]] && echo "$tmp" | jq . >/dev/null 2>&1; then
      echo "$tmp" > "$block_cache"
    fi
  fi

  # 刷新 usage cache（5分钟，带空文件保护）
  local usage_size=0
  [[ -f "$usage_cache" ]] && usage_size=$(stat -f %z "$usage_cache" 2>/dev/null || stat -c %s "$usage_cache" 2>/dev/null || echo 0)
  if [[ "$usage_size" -eq 0 ]] || [[ $(($(date +%s) - $(stat -f %m "$usage_cache" 2>/dev/null || stat -c %Y "$usage_cache" 2>/dev/null || echo 0))) -gt 300 ]]; then
    local tmp2
    tmp2=$(ccusage daily --instances --json 2>/dev/null)
    if [[ -n "$tmp2" ]] && echo "$tmp2" | jq . >/dev/null 2>&1; then
      echo "$tmp2" > "$usage_cache"
    fi
  fi

  echo "=== Claude 账号 Profiles ==="
  printf "%-3s %-12s %-28s %-6s %-14s %-18s %-14s\n" "" "NAME" "EMAIL" "SUB" "TOKEN过期" "5H BLOCK" "本月累计"
  echo "------------------------------------------------------------------------------------------------------"

  for f in "$PROFILES_DIR"/*.json; do
    [[ -f "$f" ]] || continue
    export _CS_F="$f"
    export _CS_CURRENT="$current"
    export _CS_BLOCK_CACHE="$block_cache"
    export _CS_USAGE_CACHE="$usage_cache"
    python3 << 'PYEOF'
import json, os, time
from datetime import datetime

def fmt_tok(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.0f}M'
    if n >= 1e3: return f'{n/1e3:.0f}K'
    return str(n)

def fmt_duration(seconds):
    if seconds <= 0: return '已过期'
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    if days > 0: return f'{days}d{hours}h'
    if hours > 0: return f'{hours}h{mins}m'
    return f'{mins}m'

with open(os.environ['_CS_F']) as fh:
    p = json.load(fh)

name = p['name']
email = p['email'][:26] + '..' if len(p['email']) > 28 else p['email']
sub = p['subscription_type'][:6]
current = os.environ['_CS_CURRENT']
marker = '→ ' if name == current else '  '

# Token 过期倒计时（每个 profile 都有）
exp_ms = p.get('keychain_oauth', {}).get('claudeAiOauth', {}).get('expiresAt', 0)
if exp_ms:
    remain_sec = exp_ms / 1000 - time.time()
    token_exp = fmt_duration(remain_sec)
else:
    token_exp = '-'

# 5h block 和本月累计（只对当前账号有效）
block_str = '-'
month_str = '-'
if name == current:
    # 5h block
    try:
        with open(os.environ['_CS_BLOCK_CACHE']) as fh:
            bd = json.load(fh)
        active = None
        for b in bd.get('blocks', []):
            if b.get('isActive'):
                active = b; break
        if active:
            tok = active.get('totalTokens', 0)
            proj_tok = active.get('projection', {}).get('totalTokens', tok)
            remaining = active.get('projection', {}).get('remainingMinutes', 0)
            block_str = f'{fmt_tok(tok)}/{fmt_tok(proj_tok)} ({remaining}m)'
    except: pass

    # 本月累计 (所有项目总和)
    try:
        with open(os.environ['_CS_USAGE_CACHE']) as fh:
            ud = json.load(fh)
        this_month = datetime.now().strftime('%Y-%m')
        total = 0
        for proj_days in ud.get('projects', {}).values():
            for day in proj_days:
                if day['date'].startswith(this_month):
                    total += (day.get('inputTokens',0) + day.get('outputTokens',0)
                              + day.get('cacheCreationTokens',0) + day.get('cacheReadTokens',0))
        month_str = fmt_tok(total) if total else '0'
    except: pass

print(f'{marker}{name:<12} {email:<28} {sub:<6} {token_exp:<14} {block_str:<18} {month_str:<14}')
PYEOF
    unset _CS_F _CS_CURRENT _CS_BLOCK_CACHE _CS_USAGE_CACHE
  done

  echo "------------------------------------------------------------------------------------------------------"
  echo "说明: 5H BLOCK 和 本月累计 仅对当前登录账号可得 (ccusage 数据不区分账号)"
}

# ── current: 显示当前账号 ──
cmd_current() {
  local current=""
  [[ -f "$PROFILES_DIR/.current" ]] && current=$(cat "$PROFILES_DIR/.current")

  echo "=== 当前登录账号 ==="

  # 从 .claude.json 读真实状态
  if [[ -f "$CLAUDE_JSON" ]]; then
    python3 -c "
import json
with open('$CLAUDE_JSON') as f:
    d = json.load(f)
oauth = d.get('oauthAccount', {})
print(f'  邮箱: {oauth.get(\"emailAddress\", \"未登录\")}')
print(f'  姓名: {oauth.get(\"displayName\", \"-\")}')
print(f'  组织: {oauth.get(\"organizationName\", \"-\")}')
print(f'  角色: {oauth.get(\"organizationRole\", \"-\")}')
print(f'  计费: {oauth.get(\"billingType\", \"-\")}')
" 2>/dev/null
  fi

  # 从 Keychain 读订阅类型
  local oauth_raw
  oauth_raw=$(_read_keychain)
  if [[ -n "$oauth_raw" ]]; then
    export _CS_OAUTH_JSON="$oauth_raw"
    python3 -c "
import json, os, time
d = json.loads(os.environ['_CS_OAUTH_JSON'])
o = d.get('claudeAiOauth', {})
print(f'  订阅: {o.get(\"subscriptionType\", \"-\")} ({o.get(\"rateLimitTier\", \"-\")})')
exp = o.get('expiresAt', 0) / 1000
if exp > time.time():
    remain = exp - time.time()
    h = int(remain / 3600)
    m = int((remain % 3600) / 60)
    print(f'  Token过期: {h}h {m}m 后')
" 2>/dev/null
    unset _CS_OAUTH_JSON
  fi

  [[ -n "$current" ]] && echo "  Profile: $current"
}

# ── delete: 删除 profile ──
cmd_delete() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    echo "用法: claude-switch delete <name>"
    exit 1
  fi

  local profile_file="$PROFILES_DIR/${name}.json"
  if [[ ! -f "$profile_file" ]]; then
    echo "profile '$name' 不存在"
    exit 1
  fi

  read -p "删除 profile '$name'？(y/N) " -n 1 -r REPLY
  echo
  if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    rm -f "$profile_file"
    [[ -f "$PROFILES_DIR/.current" ]] && [[ "$(cat "$PROFILES_DIR/.current")" == "$name" ]] && rm -f "$PROFILES_DIR/.current"
    echo "✓ 已删除"
  fi
}

# ── status: 显示所有 profile 的使用状态 ──
cmd_status() {
  cmd_list
  echo ""
  cmd_current
  echo ""
  echo "=== 当前账号今日 Token 消耗 ==="
  bash "$HOME/.claude/scripts/legion-usage.sh" today 2>/dev/null | grep -E "总 Token|今日" | head -3
}

# ── limit: 设置 profile 的 5h window 经验阈值 ──
cmd_limit() {
  local name="${1:-}"
  local tokens="${2:-}"
  if [[ -z "$name" ]] || [[ -z "$tokens" ]]; then
    echo "用法: claude-switch limit <profile> <tokens>"
    echo "示例: claude-switch limit main 500000000   # 5亿 tokens"
    echo "      claude-switch limit main 500M        # 支持 K/M/B 后缀"
    echo ""
    echo "说明: 5h window 的经验阈值，Anthropic 不公开精确数字，按你的历史限流经验配置"
    echo "      Max 20x 参考: ~300-500M tokens per 5h window"
    echo "      Max 5x 参考:  ~75-125M tokens"
    echo "      Pro 参考:     ~15-30M tokens"
    exit 1
  fi

  local profile_file="$PROFILES_DIR/${name}.json"
  if [[ ! -f "$profile_file" ]]; then
    echo "错误: profile '$name' 不存在"
    exit 1
  fi

  # 解析后缀
  local tok_num="$tokens"
  case "$tokens" in
    *K|*k) tok_num=$(echo "${tokens%[Kk]}" | python3 -c "import sys; print(int(float(sys.stdin.read().strip())*1000))") ;;
    *M|*m) tok_num=$(echo "${tokens%[Mm]}" | python3 -c "import sys; print(int(float(sys.stdin.read().strip())*1000000))") ;;
    *B|*b) tok_num=$(echo "${tokens%[Bb]}" | python3 -c "import sys; print(int(float(sys.stdin.read().strip())*1000000000))") ;;
  esac

  if ! [[ "$tok_num" =~ ^[0-9]+$ ]]; then
    echo "错误: 无效 tokens 值: $tokens (解析为 $tok_num)"
    exit 1
  fi

  export _CS_PROFILE_FILE="$profile_file"
  export _CS_TOK_LIMIT="$tok_num"
  python3 << 'PYEOF'
import json, os
pf = os.environ['_CS_PROFILE_FILE']
with open(pf) as f:
    p = json.load(f)
p['rate_limit_tokens'] = int(os.environ['_CS_TOK_LIMIT'])
with open(pf, 'w') as f:
    json.dump(p, f, ensure_ascii=False, indent=2)
def fmt(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.0f}M'
    if n >= 1e3: return f'{n/1e3:.0f}K'
    return str(n)
print(f"✓ {p['name']} 的 5h window 阈值已设为 {fmt(p['rate_limit_tokens'])}")
PYEOF
  unset _CS_PROFILE_FILE _CS_TOK_LIMIT
}

# ── queue-setup: 设置自动轮换队列 ──
cmd_queue_setup() {
  if [[ $# -lt 2 ]]; then
    echo "用法: claude-switch queue <profile1> <profile2> [profile3...]"
    echo "示例: claude-switch queue main work personal"
    exit 1
  fi

  # 验证每个 profile 存在
  for p in "$@"; do
    if [[ ! -f "$PROFILES_DIR/${p}.json" ]]; then
      echo "错误: profile '$p' 不存在"
      exit 1
    fi
  done

  # 写入队列文件
  printf '%s\n' "$@" > "$PROFILES_DIR/.queue"
  echo "✓ 轮换队列已设置: $*"
  echo "  用法: claude-switch auto-next — 切换到队列中下一个可用账号"
}

# ── auto-next: 智能切换到下一个可用账号 ──
cmd_auto_next() {
  if [[ ! -f "$PROFILES_DIR/.queue" ]]; then
    echo "错误: 未设置轮换队列"
    echo "先运行: claude-switch queue <p1> <p2> [p3...]"
    exit 1
  fi

  local queue=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && queue+=("$line")
  done < "$PROFILES_DIR/.queue"

  local current=""
  [[ -f "$PROFILES_DIR/.current" ]] && current=$(cat "$PROFILES_DIR/.current")

  # 找到当前账号在队列中的位置，切到下一个
  local next=""
  local found=0
  for p in "${queue[@]}"; do
    if [[ "$found" -eq 1 ]]; then
      next="$p"
      break
    fi
    [[ "$p" == "$current" ]] && found=1
  done

  # 如果当前是最后一个，回到第一个
  if [[ -z "$next" ]]; then
    next="${queue[0]}"
  fi

  if [[ "$next" == "$current" ]]; then
    echo "队列中只有一个账号，无法轮换"
    exit 1
  fi

  echo "队列: ${queue[*]}"
  echo "当前: ${current:-未知}"
  echo "切换到: $next"
  echo ""
  cmd_use "$next"
}

# ── check: 检查当前 block 用量状态，返回退出码供 hook 使用 ──
#   exit 0 = OK
#   exit 1 = WARN (超过 80%)
#   exit 2 = CRITICAL (预测即将耗尽)
cmd_check() {
  local block_cache="$HOME/.claude/ccusage-cache.json"
  if [[ ! -f "$block_cache" ]]; then
    ccusage blocks --json > "$block_cache" 2>/dev/null || {
      echo "OK: 无 ccusage 数据"
      exit 0
    }
  fi

  python3 << PYEOF
import json, sys
try:
    with open("$block_cache") as f:
        d = json.load(f)
    active = None
    for b in d.get("blocks", []):
        if b.get("isActive"):
            active = b
            break
    if not active:
        print("OK: 无活跃 block")
        sys.exit(0)

    tok = active.get("totalTokens", 0)
    proj = active.get("projection", {})
    proj_tok = proj.get("totalTokens", tok)
    remaining_min = proj.get("remainingMinutes", 0)
    burn_rate = active.get("burnRate", {}).get("tokensPerMinute", 0)

    # 预测会在 remainingMinutes 前多久触顶
    # 用 Max 20x 的典型阈值参考：约 200M tokens/5h window（估算，实际按 Anthropic 调整）
    # 不写死，用 projection 是否接近 remaining*burn 来判断
    projected_at_end = tok + burn_rate * remaining_min

    def fmt(n):
        if n >= 1e9: return f'{n/1e9:.2f}B'
        if n >= 1e6: return f'{n/1e6:.0f}M'
        if n >= 1e3: return f'{n/1e3:.0f}K'
        return str(n)

    print(f"已用: {fmt(tok)}")
    print(f"速率: {fmt(burn_rate)}/min")
    print(f"剩余: {remaining_min} 分钟")
    print(f"预测本block结束: {fmt(proj_tok)}")

    # CRITICAL: burn rate 极高且已用超过 150M（接近典型阈值）
    if burn_rate > 2_000_000 and tok > 150_000_000:
        print("CRITICAL: 高速消耗且接近阈值")
        sys.exit(2)
    # WARN: 已用超过 100M 或 burn rate 高
    elif tok > 100_000_000 or burn_rate > 1_500_000:
        print("WARN: 消耗较高")
        sys.exit(1)
    else:
        print("OK")
        sys.exit(0)
except Exception as e:
    print(f"OK: {e}")
    sys.exit(0)
PYEOF
}

# ── 主路由 ──
case "${1:-help}" in
  save)    shift; cmd_save "$@" ;;
  use)     shift; cmd_use "$@" ;;
  switch)  shift; cmd_use "$@" ;;  # alias
  list|ls) cmd_list ;;
  current|who) cmd_current ;;
  delete|rm) shift; cmd_delete "$@" ;;
  status)  cmd_status ;;
  queue)   shift; cmd_queue_setup "$@" ;;
  auto-next|next) cmd_auto_next ;;
  check)   cmd_check ;;
  limit)   shift; cmd_limit "$@" ;;
  help|*)
    cat << 'HELP_EOF'
Claude 账号快速切换 (claude-switch.sh)

基础命令:
  claude-switch save <name>       — 保存当前登录状态为 profile
  claude-switch use <name>        — 切换到 profile
  claude-switch list              — 列出所有 profile
  claude-switch current           — 显示当前登录账号
  claude-switch delete <name>     — 删除 profile
  claude-switch status            — 综合状态（列表+当前+消耗）

轮换模式（自动切换队列）:
  claude-switch queue <p1> <p2> [p3...] — 设置轮换队列
  claude-switch auto-next               — 切换到队列下一个账号
  claude-switch check                   — 检查当前 block 用量 (OK/WARN/CRITICAL)

工作流程（无需退出 Claude Code）:
  1. 用账号A登录 → claude-switch save work
  2. 在 Claude Code 内 /login 到账号B → claude-switch save personal
  3. 设置队列: claude-switch queue work personal
  4. 当 statusline 🔥🔥 红色预警 → claude-switch auto-next
  5. 切换立即生效（claude auth status 自动验证）
     — Claude Code 运行时会在下次 API 调用时用新 token
     — 如未立即感知，在 Claude Code 内发送任意消息触发刷新

关于"运行时切换":
  Claude Code 运行时按需读 Keychain，所以 claude-switch 修改后
  下次调用即生效。无需退出重启，无需 /login 走 OAuth 流程。
  这比 /login 更快（省掉浏览器授权）。

合规提醒:
  - 仅用于你合法拥有的独立账号（工作+个人+团队共享等）
  - 禁止：账号共享、批量注册小号刻意规避限额
  - Anthropic TOS 允许合理的多账号场景

存储位置:
  ~/.claude/account-profiles/     (权限 700)
  Keychain: "Claude Code-credentials"
HELP_EOF
    ;;
esac
