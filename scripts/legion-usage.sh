#!/bin/bash
# ============================================================================
# legion-usage.sh — 军团 Token 消耗统计
# ============================================================================
# 数据源: ccusage daily --instances --json
# 按项目聚合每日 token 消耗和每月累计
# 统计以 token 为核心，不含美元价格
#
# 用法:
#   legion-usage.sh today [project-key]       — 当日消耗
#   legion-usage.sh daily [N] [project-key]   — 最近N天（默认7）
#   legion-usage.sh month [YYYY-MM] [project]  — 指定月份详情
#   legion-usage.sh monthly [project-key]     — 按月累计（所有月份）
#   legion-usage.sh project [project-key]     — 项目全览（今日+本月+累计）
#   legion-usage.sh all                       — 所有项目对比
#
# project-key 默认为当前 CWD 对应的 key（/ → -）
# ============================================================================

set -euo pipefail

CACHE_FILE="$HOME/.claude/usage-cache.json"
CACHE_MAX_AGE=300  # 5分钟

# 获取当前项目 key
_current_project_key() {
  pwd | sed 's|/|-|g'
}

# 读 ccusage daily --instances --json（带缓存+空文件保护）
_load_daily_data() {
  local needs_refresh=1
  if [[ -f "$CACHE_FILE" ]]; then
    local size
    size=$(stat -f %z "$CACHE_FILE" 2>/dev/null || stat -c %s "$CACHE_FILE" 2>/dev/null || echo 0)
    local mtime
    mtime=$(stat -f %m "$CACHE_FILE" 2>/dev/null || stat -c %Y "$CACHE_FILE" 2>/dev/null || echo "0")
    local now
    now=$(date +%s)
    if [[ "$size" -gt 0 ]] && [[ $((now - mtime)) -lt $CACHE_MAX_AGE ]]; then
      needs_refresh=0
    fi
  fi

  if [[ "$needs_refresh" -eq 1 ]]; then
    if ! command -v ccusage >/dev/null 2>&1; then
      echo "错误: ccusage 未安装。brew install ccusage 或 npm i -g ccusage" >&2
      exit 1
    fi
    local tmp
    tmp=$(ccusage daily --instances --json 2>/dev/null)
    if [[ -z "$tmp" ]] || ! echo "$tmp" | jq . >/dev/null 2>&1; then
      echo "错误: ccusage 调用失败或返回非 JSON" >&2
      exit 1
    fi
    echo "$tmp" > "$CACHE_FILE"
  fi

  cat "$CACHE_FILE"
}

# 今日消耗
cmd_today() {
  local project="${1:-$(_current_project_key)}"
  local today
  today=$(date +%Y-%m-%d)

  _load_daily_data | python3 -c "
import json, sys
d = json.load(sys.stdin)
projects = d.get('projects', {})
project = '$project'
today = '$today'

def fmt_tok(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.2f}M'
    if n >= 1e3: return f'{n/1e3:.1f}K'
    return str(n)

if project not in projects:
    matches = [k for k in projects.keys() if project.lstrip('-') in k]
    if not matches:
        print(f'未找到项目: {project}')
        print(f'可用项目 (top 10 按 token 累计):')
        top = sorted(projects.items(), key=lambda x: sum(
            d.get('inputTokens',0)+d.get('outputTokens',0)+d.get('cacheCreationTokens',0)+d.get('cacheReadTokens',0) for d in x[1]
        ), reverse=True)[:10]
        for k, days in top:
            total = sum(d.get('inputTokens',0)+d.get('outputTokens',0)+d.get('cacheCreationTokens',0)+d.get('cacheReadTokens',0) for d in days)
            print(f'  {k}  {fmt_tok(total)}')
        sys.exit(1)
    project = matches[0]

days = projects[project]
today_data = next((d for d in days if d['date'] == today), None)

print(f'=== {project} — {today} ===')
if today_data:
    it = today_data.get('inputTokens', 0)
    ot = today_data.get('outputTokens', 0)
    cc = today_data.get('cacheCreationTokens', 0)
    cr = today_data.get('cacheReadTokens', 0)
    total_tok = it + ot + cc + cr
    print(f'  🔢 总 Token:  {total_tok:>15,}  ({fmt_tok(total_tok)})')
    print(f'  📥 输入:      {it:>15,}')
    print(f'  📤 输出:      {ot:>15,}')
    print(f'  ✨ 缓存创建:  {cc:>15,}')
    print(f'  ⚡ 缓存读取:  {cr:>15,}')
    if 'modelsUsed' in today_data:
        print(f'  🤖 模型:      {\", \".join(today_data[\"modelsUsed\"])}')
else:
    print('  (今日暂无消耗)')
"
}

# 最近N天
cmd_daily() {
  local n="${1:-7}"
  local project="${2:-$(_current_project_key)}"

  _load_daily_data | python3 -c "
import json, sys
d = json.load(sys.stdin)
projects = d.get('projects', {})
project = '$project'
n = int('$n')

def fmt_tok(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.2f}M'
    if n >= 1e3: return f'{n/1e3:.1f}K'
    return str(n)

if project not in projects:
    matches = [k for k in projects.keys() if project.lstrip('-') in k]
    if not matches:
        print(f'未找到项目: {project}')
        sys.exit(1)
    project = matches[0]

days = sorted(projects[project], key=lambda x: x['date'])[-n:]

print(f'=== {project} — 最近 {len(days)} 天 (单位: Token) ===')
print(f'{\"日期\":<12} {\"总Token\":>14} {\"输入\":>12} {\"输出\":>12} {\"缓存读\":>14}')
print('-' * 68)
grand_total = 0
grand_in = 0
grand_out = 0
grand_cr = 0
for day in days:
    it = day.get('inputTokens', 0)
    ot = day.get('outputTokens', 0)
    cc = day.get('cacheCreationTokens', 0)
    cr = day.get('cacheReadTokens', 0)
    total = it + ot + cc + cr
    grand_total += total
    grand_in += it
    grand_out += ot
    grand_cr += cr
    print(f'{day[\"date\"]:<12} {total:>14,} {it:>12,} {ot:>12,} {cr:>14,}')
print('-' * 68)
print(f'{\"合计\":<12} {grand_total:>14,} {grand_in:>12,} {grand_out:>12,} {grand_cr:>14,}')
print(f'{\"\":12} ({fmt_tok(grand_total)})')
"
}

# 指定月份详情
cmd_month() {
  local month="${1:-$(date +%Y-%m)}"
  local project="${2:-$(_current_project_key)}"

  _load_daily_data | python3 -c "
import json, sys
from collections import defaultdict
d = json.load(sys.stdin)
projects = d.get('projects', {})
project = '$project'
month = '$month'

def fmt_tok(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.2f}M'
    if n >= 1e3: return f'{n/1e3:.1f}K'
    return str(n)

if project not in projects:
    matches = [k for k in projects.keys() if project.lstrip('-') in k]
    if not matches:
        print(f'未找到项目: {project}')
        sys.exit(1)
    project = matches[0]

days = [d for d in projects[project] if d['date'].startswith(month)]

if not days:
    print(f'=== {project} — {month} ===')
    print('  (该月暂无消耗)')
    sys.exit(0)

total_it = sum(d.get('inputTokens', 0) for d in days)
total_ot = sum(d.get('outputTokens', 0) for d in days)
total_cc = sum(d.get('cacheCreationTokens', 0) for d in days)
total_cr = sum(d.get('cacheReadTokens', 0) for d in days)
total_tok = total_it + total_ot + total_cc + total_cr

print(f'=== {project} — {month} 月度详情 (单位: Token) ===')
print(f'  🔢 月度总Token: {total_tok:>15,}  ({fmt_tok(total_tok)})')
print(f'  📅 活跃天数:   {len(days):>15}')
print(f'  📥 输入:       {total_it:>15,}')
print(f'  📤 输出:       {total_ot:>15,}')
print(f'  ✨ 缓存创建:   {total_cc:>15,}')
print(f'  ⚡ 缓存读取:   {total_cr:>15,}')
print(f'  📊 日均Token:  {total_tok//len(days):>15,}')
print()
print('按日 Token 消耗 top 10:')
top_days = sorted(days, key=lambda x: (
    x.get('inputTokens',0)+x.get('outputTokens',0)+x.get('cacheCreationTokens',0)+x.get('cacheReadTokens',0)
), reverse=True)[:10]
for day in top_days:
    tok = day.get('inputTokens',0)+day.get('outputTokens',0)+day.get('cacheCreationTokens',0)+day.get('cacheReadTokens',0)
    print(f'  {day[\"date\"]}  {tok:>15,}  ({fmt_tok(tok)})')
"
}

# 按月累计（所有月份）
cmd_monthly() {
  local project="${1:-$(_current_project_key)}"

  _load_daily_data | python3 -c "
import json, sys
from collections import defaultdict
d = json.load(sys.stdin)
projects = d.get('projects', {})
project = '$project'

def fmt_tok(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.2f}M'
    if n >= 1e3: return f'{n/1e3:.1f}K'
    return str(n)

if project not in projects:
    matches = [k for k in projects.keys() if project.lstrip('-') in k]
    if not matches:
        print(f'未找到项目: {project}')
        sys.exit(1)
    project = matches[0]

# 按月聚合
monthly = defaultdict(lambda: {'tokens': 0, 'input': 0, 'output': 0, 'cache': 0, 'days': 0})
for day in projects[project]:
    m = day['date'][:7]
    it = day.get('inputTokens', 0)
    ot = day.get('outputTokens', 0)
    cc = day.get('cacheCreationTokens', 0)
    cr = day.get('cacheReadTokens', 0)
    monthly[m]['tokens'] += it + ot + cc + cr
    monthly[m]['input'] += it
    monthly[m]['output'] += ot
    monthly[m]['cache'] += cc + cr
    monthly[m]['days'] += 1

print(f'=== {project} — 按月 Token 累计 ===')
print(f'{\"月份\":<10} {\"总Token\":>16} {\"输入\":>14} {\"输出\":>14} {\"缓存\":>16} {\"天数\":>6}')
print('-' * 82)
grand_tok = 0
grand_days = 0
for m in sorted(monthly.keys()):
    v = monthly[m]
    grand_tok += v['tokens']
    grand_days += v['days']
    print(f'{m:<10} {v[\"tokens\"]:>16,} {v[\"input\"]:>14,} {v[\"output\"]:>14,} {v[\"cache\"]:>16,} {v[\"days\"]:>6}')
print('-' * 82)
print(f'{\"总计\":<10} {grand_tok:>16,}  ({fmt_tok(grand_tok)})  活跃{grand_days}天')
"
}

# 项目全览（今日+本月+历史）
cmd_project() {
  local project="${1:-$(_current_project_key)}"
  local today
  today=$(date +%Y-%m-%d)
  local this_month
  this_month=$(date +%Y-%m)

  _load_daily_data | python3 -c "
import json, sys
d = json.load(sys.stdin)
projects = d.get('projects', {})
project = '$project'
today = '$today'
this_month = '$this_month'

def fmt_tok(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.2f}M'
    if n >= 1e3: return f'{n/1e3:.1f}K'
    return str(n)

def sum_tok(day):
    return (day.get('inputTokens',0) + day.get('outputTokens',0)
            + day.get('cacheCreationTokens',0) + day.get('cacheReadTokens',0))

if project not in projects:
    matches = [k for k in projects.keys() if project.lstrip('-') in k]
    if not matches:
        print(f'未找到项目: {project}')
        print(f'可用项目 (top 10 按 token 累计):')
        top = sorted(projects.items(), key=lambda x: sum(sum_tok(d) for d in x[1]), reverse=True)[:10]
        for k, days in top:
            total = sum(sum_tok(d) for d in days)
            print(f'  {k}  {fmt_tok(total)}')
        sys.exit(1)
    project = matches[0]

days = projects[project]

# 今日
today_data = next((d for d in days if d['date'] == today), None)
today_tok = sum_tok(today_data) if today_data else 0

# 本月
this_month_days = [d for d in days if d['date'].startswith(this_month)]
this_month_tok = sum(sum_tok(d) for d in this_month_days)

# 历史总计
total_tok = sum(sum_tok(d) for d in days)

# 历史最高日
peak = max(days, key=sum_tok) if days else None

print(f'╔══════════════════════════════════════════════════════════╗')
print(f'║ 📊 项目 Token 消耗全览                                    ║')
print(f'╚══════════════════════════════════════════════════════════╝')
print(f'项目: {project}')
print()
print(f'┌─ 今日 ({today}) ─────────────────────')
print(f'│  🔢 Token: {today_tok:,}  ({fmt_tok(today_tok)})')
if today_data:
    print(f'│  📥 输入: {today_data.get(\"inputTokens\",0):,}')
    print(f'│  📤 输出: {today_data.get(\"outputTokens\",0):,}')
    print(f'│  ⚡ 缓存读: {today_data.get(\"cacheReadTokens\",0):,}')
print()
print(f'┌─ 本月 ({this_month}) ─────────────────')
print(f'│  🔢 累计Token: {this_month_tok:,}  ({fmt_tok(this_month_tok)})')
print(f'│  📅 活跃天数: {len(this_month_days)}')
if this_month_days:
    print(f'│  📊 日均Token: {this_month_tok//len(this_month_days):,}')
print()
print(f'┌─ 历史累计 ─────────────────────────')
print(f'│  🔢 总Token: {total_tok:,}  ({fmt_tok(total_tok)})')
print(f'│  📅 活跃天数: {len(days)}')
if peak:
    peak_tok = sum_tok(peak)
    print(f'│  🏔️ 最高日: {peak[\"date\"]}  {peak_tok:,}  ({fmt_tok(peak_tok)})')
print()
"
}

# 所有项目对比
cmd_all() {
  _load_daily_data | python3 -c "
import json, sys
d = json.load(sys.stdin)
projects = d.get('projects', {})
today = '$(date +%Y-%m-%d)'
this_month = '$(date +%Y-%m)'

def fmt_tok(n):
    if n >= 1e9: return f'{n/1e9:.2f}B'
    if n >= 1e6: return f'{n/1e6:.2f}M'
    if n >= 1e3: return f'{n/1e3:.1f}K'
    return str(n)

def sum_tok(day):
    return (day.get('inputTokens',0) + day.get('outputTokens',0)
            + day.get('cacheCreationTokens',0) + day.get('cacheReadTokens',0))

rows = []
for k, days in projects.items():
    today_tok = sum(sum_tok(d) for d in days if d['date'] == today)
    month_tok = sum(sum_tok(d) for d in days if d['date'].startswith(this_month))
    total_tok = sum(sum_tok(d) for d in days)
    last_date = max(d['date'] for d in days) if days else '-'
    rows.append((k, today_tok, month_tok, total_tok, last_date))

rows.sort(key=lambda x: x[3], reverse=True)

print(f'=== 所有项目 Token 消耗对比 ===')
print(f'{\"项目\":<50} {\"今日\":>12} {\"本月\":>14} {\"累计\":>14} {\"最后活跃\":>12}')
print('-' * 106)
for r in rows[:20]:
    name = r[0][:48] if len(r[0]) > 48 else r[0]
    print(f'{name:<50} {fmt_tok(r[1]):>12} {fmt_tok(r[2]):>14} {fmt_tok(r[3]):>14} {r[4]:>12}')
print('-' * 106)
t_today = sum(r[1] for r in rows)
t_month = sum(r[2] for r in rows)
t_total = sum(r[3] for r in rows)
print(f'{\"合计\":<50} {fmt_tok(t_today):>12} {fmt_tok(t_month):>14} {fmt_tok(t_total):>14}')
"
}

# 主路由
case "${1:-project}" in
  today)   shift; cmd_today "$@" ;;
  daily)   shift; cmd_daily "$@" ;;
  month)   shift; cmd_month "$@" ;;
  monthly) shift; cmd_monthly "$@" ;;
  project) shift; cmd_project "$@" ;;
  all)     shift; cmd_all "$@" ;;
  refresh) rm -f "$CACHE_FILE" && echo "缓存已清除" ;;
  help|*)
    cat << 'HELP_EOF'
军团 Token 消耗统计 (legion-usage.sh)

用法:
  legion-usage.sh project [key]       — 项目全览（今日+本月+累计）⭐默认
  legion-usage.sh today [key]         — 今日详情
  legion-usage.sh daily [N] [key]     — 最近N天（默认7）
  legion-usage.sh month [YYYY-MM] [key] — 月份详情
  legion-usage.sh monthly [key]       — 按月累计（历史所有月）
  legion-usage.sh all                 — 所有项目对比
  legion-usage.sh refresh             — 清除5分钟缓存

说明:
  - 所有数据以 Token 为单位，不含美元价格
  - 大数字自动格式化为 K/M/B
  - key 默认为当前目录对应的 project-key（CWD 斜线转横线）
  - 数据源: ccusage daily --instances --json（5分钟缓存）

示例:
  legion-usage.sh                     # 当前项目全览
  legion-usage.sh daily 30            # 最近30天
  legion-usage.sh month 2026-04       # 4月详情
  legion-usage.sh all                 # 所有项目对比
HELP_EOF
    ;;
esac
