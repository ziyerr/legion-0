#!/usr/bin/env bash
# Codex 军团成员调度器
# 用法:
#   codex-team.sh review <file_or_diff>          — 代码审查
#   codex-team.sh adversarial <file_or_diff>     — 对抗性审查（红队）
#   codex-team.sh rescue "<problem_description>" — 任务救援
#   codex-team.sh second-opinion "<question>"    — 第二意见

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCHEMA_DIR="$SCRIPT_DIR/../skills/codex-member/schemas"
OUTPUT_DIR="/tmp/codex-team-output"
mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 默认模型：读 codex 配置，找不到则用 gpt-5.4
DEFAULT_MODEL=$(grep '^model' ~/.codex/config.toml 2>/dev/null | head -1 | sed 's/.*= *"\(.*\)"/\1/' || echo "gpt-5.4")
MODEL="${CODEX_MODEL:-$DEFAULT_MODEL}"

# ── CC 通信桥接：伞兵结果写入 CC team inbox ──
# 让伞兵的输出进入 CC SendMessage 消息流，被 useInboxPoller 拾取
_bridge_to_inbox() {
    local task_type="$1"  # review/adversarial/rescue/second-opinion
    local result="$2"
    local summary="$3"

    # 需要知道目标 team 和 leader name
    local team_name="${CLAUDE_CODE_TEAM_NAME:-}"
    [[ -z "$team_name" ]] && return  # 不在 CC team 中，跳过桥接

    local leader_inbox="$HOME/.claude/teams/$team_name/inboxes/team-lead.json"
    [[ ! -d "$(dirname "$leader_inbox")" ]] && return

    _BRIDGE_INBOX="$leader_inbox" _BRIDGE_TYPE="$task_type" \
    _BRIDGE_RESULT="$result" _BRIDGE_SUMMARY="$summary" \
    python3 << 'BRIDGE_EOF'
import json, fcntl, os, time, uuid

inbox_path = os.environ['_BRIDGE_INBOX']
lock_path = inbox_path + '.lock'
task_type = os.environ['_BRIDGE_TYPE']
result = os.environ.get('_BRIDGE_RESULT', '')
summary = os.environ.get('_BRIDGE_SUMMARY', '')[:80]

msg = {
    'from': f'codex-{task_type}',
    'text': result,
    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'read': False,
    'color': 'yellow',
    'summary': f'[Codex {task_type}] {summary}'
}

# 确保文件存在
if not os.path.exists(inbox_path):
    os.makedirs(os.path.dirname(inbox_path), exist_ok=True)
    with open(inbox_path, 'w') as f:
        json.dump([], f)

# flock + read-modify-write（对齐 CC proper-lockfile 模式）
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
BRIDGE_EOF
}

usage() {
    echo "Codex 军团成员调度器"
    echo ""
    echo "用法:"
    echo "  $0 review [--base <branch>] [files...]     代码审查"
    echo "  $0 adversarial [--base <branch>] [files...]  对抗性审查"
    echo "  $0 rescue \"<问题描述>\"                      任务救援"
    echo "  $0 second-opinion \"<问题>\"                  第二意见"
    echo ""
    echo "环境变量:"
    echo "  CODEX_MODEL  指定模型 (默认: o3)"
    exit 1
}

# 收集 git diff 上下文
get_diff_context() {
    local base="${1:-main}"
    shift || true
    local files=("$@")

    if [ ${#files[@]} -gt 0 ]; then
        git diff "$base" -- "${files[@]}" 2>/dev/null || git diff -- "${files[@]}" 2>/dev/null || echo "(no diff available)"
    else
        git diff "$base" 2>/dev/null || git diff 2>/dev/null || echo "(no diff available)"
    fi
}

# 代码审查
cmd_review() {
    local base="main"
    local files=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --base) base="$2"; shift 2 ;;
            *) files+=("$1"); shift ;;
        esac
    done

    local diff_content
    diff_content=$(get_diff_context "$base" "${files[@]}")
    local output_file="$OUTPUT_DIR/review_${TIMESTAMP}.md"

    echo "$diff_content" | codex exec \
        --model "$MODEL" \
        --sandbox read-only \
        -o "$output_file" \
        "你是代码审查员，审查以下 git diff。

项目：Novel-to-Video Standalone（Tauri 2 + React 19 + Rust + Python）
规则：Rust 禁止 unwrap 用 ?；前端 invoke() 参数 camelCase；后端 snake_case + serde rename。

请从 stdin 读取 diff 内容，按以下格式输出审查结果：

## 审查结果

### 判定: APPROVE / NEEDS-ATTENTION

### 发现
按严重度排序（critical > major > minor > suggestion）:
- **[severity]** file:line — 问题描述 → 建议修复

### 总结
一段话总结代码质量和主要关注点。" 2>&1 || true

    if [ -f "$output_file" ]; then
        local result
        result=$(cat "$output_file")
        echo "$result"
        # 桥接到 CC inbox，让其他 teammate 也能看到
        _bridge_to_inbox "review" "$result" "代码审查完成"
    else
        echo "⚠️ Codex 审查未产出结果，检查 codex 登录状态: codex login"
    fi
}

# 对抗性审查（红队）
cmd_adversarial() {
    local base="main"
    local files=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --base) base="$2"; shift 2 ;;
            *) files+=("$1"); shift ;;
        esac
    done

    local diff_content
    diff_content=$(get_diff_context "$base" "${files[@]}")
    local output_file="$OUTPUT_DIR/adversarial_${TIMESTAMP}.md"

    echo "$diff_content" | codex exec \
        --model "$MODEL" \
        --sandbox read-only \
        -o "$output_file" \
        "你是红队安全审查员。你的任务是对抗性压力测试这段代码变更。

项目：Novel-to-Video Standalone（Tauri 2 桌面应用，处理用户文件和外部 API）

从 stdin 读取 diff，针对以下维度发起攻击：

1. **安全漏洞** — 命令注入、路径遍历、XSS、SSRF、不安全的反序列化
2. **竞态条件** — 并发访问、文件锁、原子性
3. **资源泄漏** — 未关闭的文件句柄/连接、内存泄漏
4. **边界条件** — 空值、超大输入、非法字符、unicode 边界
5. **降级行为** — 网络断开、API 超时、磁盘满、进程崩溃时的行为
6. **设计缺陷** — 耦合度、可测试性、单一职责违反

输出格式：

## 红队审查报告

### 判定: PASS / FAIL

### 攻击发现
- **[critical/major/minor]** file:line — 攻击向量描述 → 利用方式 → 修复建议 (置信度: high/medium/low)

### 压力测试场景
1. 场景描述 → 预期行为 vs 实际行为

### 总结
整体安全态势评估。" 2>&1 || true

    if [ -f "$output_file" ]; then
        local result
        result=$(cat "$output_file")
        echo "$result"
        _bridge_to_inbox "adversarial" "$result" "红队审查完成"
    else
        echo "⚠️ Codex 红队审查未产出结果"
    fi
}

# 任务救援
cmd_rescue() {
    local problem="$1"
    local output_file="$OUTPUT_DIR/rescue_${TIMESTAMP}.md"

    codex exec \
        --model "$MODEL" \
        --sandbox read-only \
        -C "$PROJECT_DIR" \
        -o "$output_file" \
        "你是救援专家。团队在以下问题上卡住了，需要你独立调查并提供解决方案。

项目：Novel-to-Video Standalone
目录结构：gui/src/(React前端), gui/src-tauri/src/(Rust后端), scripts/(Python), v2/(V2流水线)

问题描述：
$problem

请执行以下步骤：
1. 读取相关代码文件，理解上下文
2. 分析问题根因
3. 提供具体的修复方案（含代码片段和文件路径）
4. 列出验证步骤

输出格式：
## 救援报告
### 根因分析
### 修复方案
### 验证步骤" 2>&1 || true

    if [ -f "$output_file" ]; then
        local result
        result=$(cat "$output_file")
        echo "$result"
        _bridge_to_inbox "rescue" "$result" "救援报告完成"
    else
        echo "⚠️ Codex 救援未产出结果"
    fi
}

# 第二意见
cmd_second_opinion() {
    local question="$1"
    local output_file="$OUTPUT_DIR/opinion_${TIMESTAMP}.md"

    codex exec \
        --model "$MODEL" \
        --sandbox read-only \
        -C "$PROJECT_DIR" \
        -o "$output_file" \
        "你是技术顾问。团队需要你对以下问题提供独立的第二意见。

项目：Novel-to-Video Standalone（Tauri 2 + React 19 + Rust + Python）

问题：
$question

请给出：
1. 你的独立分析（不要假设团队的方案是对的）
2. 如果你的看法与团队不同，解释为什么
3. 具体建议和权衡分析" 2>&1 || true

    if [ -f "$output_file" ]; then
        local result
        result=$(cat "$output_file")
        echo "$result"
        _bridge_to_inbox "second-opinion" "$result" "第二意见完成"
    else
        echo "⚠️ Codex 第二意见未产出结果"
    fi
}

# 主入口
case "${1:-}" in
    review)         shift; cmd_review "$@" ;;
    adversarial)    shift; cmd_adversarial "$@" ;;
    rescue)         shift; cmd_rescue "$@" ;;
    second-opinion) shift; cmd_second_opinion "$@" ;;
    *)              usage ;;
esac
