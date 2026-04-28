#!/bin/bash
# ============================================================================
# legion-init.sh — 军团系统项目初始化
# ============================================================================
#
# 在任意新项目目录执行，自动完成军团系统项目级初始化：
#   1. 复制 skills（从参考项目）
#   2. 复制 agents（从参考项目）
#   3. 创建 commander 简报目录
#   4. 生成/补齐 CLAUDE.md 模板（如不存在或缺少执行纪律）
#   5. 创建 settings.local.json（如不存在）
#   6. 创建 memory 目录结构
#   7. 注册到全局 legion directory
#
# 用法：
#   cd /path/to/new-project
#   bash ~/.claude/scripts/legion-init.sh                    # 交互式
#   bash ~/.claude/scripts/legion-init.sh --from ~/my-reference-project  # 指定参考项目
#   LEGION_REFERENCE_PROJECT=~/my-ref bash ~/.claude/scripts/legion-init.sh  # env 覆盖
#   bash ~/.claude/scripts/legion-init.sh --minimal          # 最小初始化（只复制核心技能）
#
# ============================================================================

set -euo pipefail

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# 参考项目：从 $REFERENCE_PROJECT/.claude/{skills,agents}/ 拷贝到新项目
# 默认用 $HOME（因 $HOME/.claude/skills/ 和 agents/ 是 legion-0 全局库位置）
# 可通过 --from <path> 或 LEGION_REFERENCE_PROJECT env var 覆盖为具体项目
REFERENCE_PROJECT="${LEGION_REFERENCE_PROJECT:-$HOME}"
MINIMAL=false
TARGET_DIR="$(pwd)"
ASSUME_YES="${LEGION_INIT_ASSUME_YES:-false}"

# 核心技能列表（--minimal 模式只复制这些）
CORE_SKILLS=(
  "agent-team"
  "audit"
  "autonomous-loop"
  "degradation-policy"
  "recon"
  "spec-driven"
  "startup"
  "verification-before-completion"
  "using-superpowers"
  "writing-plans"
  "brainstorming"
  "claw-roundtable-skill"
  "product-counselor"
  "sniper"
)

# 核心 Agent 定义（始终复制）
CORE_AGENTS=(
  "implement.md"
  "review.md"
  "verify.md"
  "explore.md"
  "plan.md"
)

BACKUP_ROOT="${TARGET_DIR}/.claude/backups/legion-init/$(date +%Y%m%d-%H%M%S)"

backup_existing_file() {
  local existing="$1"
  local rel backup_file
  [[ -e "$existing" ]] || return 0
  rel="${existing#"${TARGET_DIR}/"}"
  backup_file="${BACKUP_ROOT}/${rel}"
  mkdir -p "$(dirname "$backup_file")"
  cp -p "$existing" "$backup_file"
  echo -e "  ${YELLOW}⚠ 已备份将被覆盖文件: ${rel}${NC}"
}

copy_file_with_backup() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [[ "$(cd "$(dirname "$src")" && pwd -P)/$(basename "$src")" == "$(cd "$(dirname "$dst")" && pwd -P 2>/dev/null || pwd)/$(basename "$dst")" ]]; then
    return 0
  fi
  if [[ -e "$dst" ]] && ! cmp -s "$src" "$dst"; then
    backup_existing_file "$dst"
  fi
  cp "$src" "$dst"
}

copy_dir_with_backup() {
  local src="$1"
  local dst_parent="$2"
  local dst rel src_file dst_file
  [[ -d "$src" ]] || return 0
  dst="${dst_parent}/$(basename "$src")"
  mkdir -p "$dst_parent"
  if [[ "$(cd "$src" && pwd -P)" == "$(mkdir -p "$dst" && cd "$dst" && pwd -P)" ]]; then
    return 0
  fi
  if [[ -d "$dst" ]]; then
    while IFS= read -r -d '' src_file; do
      rel="${src_file#"$src"/}"
      dst_file="$dst/$rel"
      if [[ -e "$dst_file" ]] && ! cmp -s "$src_file" "$dst_file"; then
        backup_existing_file "$dst_file"
      fi
    done < <(find "$src" -type f -print0 2>/dev/null)
  fi
  cp -r "$src" "$dst_parent/"
}

install_generated_file_with_backup() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [[ -e "$dst" ]] && ! cmp -s "$src" "$dst"; then
    backup_existing_file "$dst"
  fi
  mv "$src" "$dst"
}

claude_has_execution_discipline() {
  local claude_file="$1"
  grep -q "legion-init execution-discipline/v2" "$claude_file" 2>/dev/null
}

merge_claude_execution_discipline() {
  local claude_file="$1"

  backup_existing_file "$claude_file"
  CLAUDE_FILE="$claude_file" python3 << 'PY'
from pathlib import Path
import os

path = Path(os.environ["CLAUDE_FILE"])
text = path.read_text(encoding="utf-8")
block = """# >>> legion-init execution-discipline/v2 >>>
# 指挥官自主权（全局第一原则）

所有 L1 指挥官在所有项目中默认拥有流程决策的完全自主权。

**流程决策（要不要组团 / 侦察 / spec / 审查 / 放行 / 升级复杂度 / 选技能 / 选 teammate 配置）→ 直接判断执行，不向用户确认。**

## 军团核心原则：规模优先

军团目标是不计资源消耗成本，通过最大化有效军团规模协作提升效率和质量。

1. **资源成本不是降级理由** — token、时间、进程数、tmux 窗口数、模型调用成本不得作为降级理由。
2. **默认向上扩编** — 非平凡任务优先用 `--corps` 扩编 L2，并并行组织侦察 / 实现 / 审查 / 验证 / 审计 / 产品 / UI。
3. **最大有效规模，不是盲目重复** — 扩编必须带来互补视角或并行吞吐。
4. **质量门前置且独立** — 实现与 review / verify / audit 分离。
5. **上下文即资产** — L2 是否解散取决于上下文是否仍有价值。

## 四种例外：只有这些情形才停下问用户

1. **不可逆破坏** — rm -rf、force push 主分支、drop table、覆盖未提交代码、删除分支、删除未备份数据
2. **需求本身模糊** — 有多种合理解释，无法通过读代码 / 读 memory 消除歧义
3. **跨项目 / 共享状态变更** — 影响他人、跨 repo、改 CI/CD 管线、改全局配置 / hooks / 技能 / 全局 AGENTS.md / 全局 CLAUDE.md
4. **关键决策成本高** — 走到死胡同需要大成本返工的岔路口

## 句式纪律

禁止流程确认（“可以吗 / 要不要先 recon / 需要我组团吗 / 可以进入下一步吗”）。允许汇报已发生动作；命中例外时说“命中第 N 种例外：[情形]，请你决定：[A / B]”。

## 作战纪律

S 级单文件可轻量；M 级 2-5 文件需侦察/实现/审查；L 级跨域需多路侦察、流水线与独立验证；XL 级架构变更用最大有效规模。铁律：不跑验证不许完成；禁止降级核心目标；复杂度拿不准向上；功能开发先经产品参谋。

项目级 AGENTS.md / CLAUDE.md 可以覆盖本规则；需要更严格人工确认时写“禁用自主权第一原则”。
# <<< legion-init execution-discipline/v2 <<<"""

start_token = "# >>> legion-init execution-discipline"
end_token = "# <<< legion-init execution-discipline"
start = text.find(start_token)
end = text.find(end_token, start + 1) if start != -1 else -1

if start != -1 and end != -1:
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end + 1
    merged = text[:start].rstrip() + "\n\n" + block + "\n\n" + text[line_end:].lstrip()
else:
    merged = block + "\n\n---\n\n" + text.lstrip()

path.write_text(merged.rstrip() + "\n", encoding="utf-8")
PY
  echo -e "  ${GREEN}✓ CLAUDE.md 已备份并合并最新完整执行纪律模板${NC}"
}

# 解析参数
while [[ $# -gt 0 ]]; do
  case $1 in
    --from)
      REFERENCE_PROJECT="$2"
      shift 2
      ;;
    --minimal)
      MINIMAL=true
      shift
      ;;
    --help|-h)
      head -18 "$0" | tail -14
      exit 0
      ;;
    *)
      echo -e "${RED}未知参数: $1${NC}"
      exit 1
      ;;
  esac
done

if [[ -d "${REFERENCE_PROJECT}/.claude/skills" && -d "${REFERENCE_PROJECT}/.claude/agents" ]]; then
  REF_CLAUDE_DIR="${REFERENCE_PROJECT}/.claude"
elif [[ -d "${REFERENCE_PROJECT}/skills" && -d "${REFERENCE_PROJECT}/agents" ]]; then
  REF_CLAUDE_DIR="${REFERENCE_PROJECT}"
else
  echo -e "${RED}错误: 参考项目 ${REFERENCE_PROJECT} 不存在可用的 skills/agents 模板${NC}"
  echo -e "${YELLOW}要求其一: ${REFERENCE_PROJECT}/.claude/{skills,agents} 或 ${REFERENCE_PROJECT}/{skills,agents}${NC}"
  exit 1
fi
REF_SKILLS_DIR="${REF_CLAUDE_DIR}/skills"
REF_AGENTS_DIR="${REF_CLAUDE_DIR}/agents"

echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo -e "${BLUE}  军团系统 — 项目初始化${NC}"
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo ""
echo -e "  目标项目: ${GREEN}${TARGET_DIR}${NC}"
echo -e "  参考项目: ${YELLOW}${REFERENCE_PROJECT}${NC}"
echo -e "  模板目录: ${YELLOW}${REF_CLAUDE_DIR}${NC}"
if $MINIMAL; then MODE_LABEL="最小"; else MODE_LABEL="完整"; fi
echo -e "  模式:     ${MODE_LABEL}${NC}"
echo ""

# 检查目标目录是否是 git 仓库
if [[ ! -d "${TARGET_DIR}/.git" ]]; then
  echo -e "${YELLOW}警告: 当前目录不是 git 仓库。建议先 git init。${NC}"
  if [[ "$ASSUME_YES" == "1" || "$ASSUME_YES" == "true" || ! -t 0 ]]; then
    echo -e "${YELLOW}  → 非交互初始化继续执行${NC}"
  else
    read -p "继续？(y/N) " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || exit 0
  fi
fi

COUNTER=0
TOTAL=7

# ─────────────────────────────────────────
# Step 1: Skills
# ─────────────────────────────────────────
COUNTER=$((COUNTER + 1))
echo -e "${GREEN}[${COUNTER}/${TOTAL}]${NC} 复制技能..."

mkdir -p "${TARGET_DIR}/.claude/skills"

if $MINIMAL; then
  for skill in "${CORE_SKILLS[@]}"; do
    if [[ -d "${REF_SKILLS_DIR}/${skill}" ]]; then
      copy_dir_with_backup "${REF_SKILLS_DIR}/${skill}" "${TARGET_DIR}/.claude/skills"
      echo "  ✓ ${skill}"
    else
      echo -e "  ${YELLOW}⚠ ${skill} 不存在于参考项目${NC}"
    fi
  done
else
  # 复制全部技能
  for skill_dir in "${REF_SKILLS_DIR}"/*; do
    [[ -d "$skill_dir" ]] || continue
    copy_dir_with_backup "$skill_dir" "${TARGET_DIR}/.claude/skills"
  done
fi
SKILL_COUNT=$(find "${TARGET_DIR}/.claude/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')

echo -e "  ${GREEN}→ ${SKILL_COUNT} 个技能已就位${NC}"

# Codex uses .agents/skills as its project skill root. Keep a lightweight bridge
# so Codex L1/L2 commanders can discover Claude-native Legion skills.
mkdir -p "${TARGET_DIR}/.agents/skills/claw-roundtable-skill"
BRIDGE_TMP=$(mktemp "${TARGET_DIR}/.agents/skills/claw-roundtable-skill/SKILL.md.tmp.XXXXXX")
cat > "$BRIDGE_TMP" << 'CODEX_ROUNDTABLE_SKILL_EOF'
---
name: claw-roundtable-skill
description: Use when Legion/Codex is asked for RoundTable, 圆桌会议, multi-expert debate, high-cost architecture/API/security decisions, XL planning, or when recon leaves multiple viable paths. Bridges to the project Claude RoundTable runtime and must health-check before claiming execution.
---

# Claw RoundTable Bridge

Use this skill inside Codex/Legion branches to access the project RoundTable package at `.claude/skills/claw-roundtable-skill`.

## Required Checks

1. Confirm the project package exists:
`test -f .claude/skills/claw-roundtable-skill/SKILL.md`

2. Run base health before using analysis or expert matching:
`python3 .claude/skills/claw-roundtable-skill/roundtable_health.py`

3. Before claiming a real multi-expert RoundTable execution, run:
`python3 .claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime`

If `--require-runtime` fails with missing `openclaw.tools.sessions_spawn`, do not claim RoundTable completed. Report that only analysis/expert matching is available and use Legion Core `mixed campaign --corps` for the actual multi-agent discussion.

## Analysis

For demand analysis without runtime:

```bash
PYTHONPATH=.claude/skills/claw-roundtable-skill python3 - <<'PY'
from roundtable_engine_v2 import analyze_requirement

result = analyze_requirement("要讨论的问题")
print(result)
PY
```

## Legion Rule

This is an on-demand shared weapon for all L1/L2 branches. Codex commanders perform RoundTable initialization during normal startup because the default runtime bridge uses the Codex CLI. Claude commanders do not run RoundTable initialization during routine startup, but they can run explicit RoundTable/OpenClaw access tests when requested. Completion claims always require runtime health evidence.

For native OpenClaw backend integration testing:

```bash
OPENCLAW_ROUNDTABLE_BACKEND=openclaw python3 .claude/skills/claw-roundtable-skill/roundtable_health.py --require-runtime
```
CODEX_ROUNDTABLE_SKILL_EOF
install_generated_file_with_backup "$BRIDGE_TMP" "${TARGET_DIR}/.agents/skills/claw-roundtable-skill/SKILL.md"
echo "  ✓ Codex 圆桌 skill 桥接入口已就位"

# ─────────────────────────────────────────
# Step 2: Agents
# ─────────────────────────────────────────
COUNTER=$((COUNTER + 1))
echo -e "${GREEN}[${COUNTER}/${TOTAL}]${NC} 复制 Agent 定义..."

mkdir -p "${TARGET_DIR}/.claude/agents"

if $MINIMAL; then
  for agent in "${CORE_AGENTS[@]}"; do
    if [[ -f "${REF_AGENTS_DIR}/${agent}" ]]; then
      copy_file_with_backup "${REF_AGENTS_DIR}/${agent}" "${TARGET_DIR}/.claude/agents/${agent}"
      echo "  ✓ ${agent}"
    fi
  done
else
  for agent_file in "${REF_AGENTS_DIR}/"*.md; do
    [[ -f "$agent_file" ]] || continue
    copy_file_with_backup "$agent_file" "${TARGET_DIR}/.claude/agents/$(basename "$agent_file")"
  done
fi

AGENT_COUNT=$(find "${TARGET_DIR}/.claude/agents" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
echo -e "  ${GREEN}→ ${AGENT_COUNT} 个 Agent 定义已就位${NC}"

# ─────────────────────────────────────────
# Step 3: Commander briefings
# ─────────────────────────────────────────
COUNTER=$((COUNTER + 1))
echo -e "${GREEN}[${COUNTER}/${TOTAL}]${NC} 创建指挥官简报目录..."

mkdir -p "${TARGET_DIR}/.claude/commander/briefings"

if [[ ! -f "${TARGET_DIR}/.claude/commander/briefings/default.md" ]]; then
  cat > "${TARGET_DIR}/.claude/commander/briefings/default.md" << 'BRIEFING_EOF'
# 指挥官简报

新指挥官接管时读此文件。只记录其他地方没有的信息。
BRIEFING_EOF
  echo "  ✓ 默认简报已创建"
else
  echo "  → 简报已存在，跳过"
fi

# ─────────────────────────────────────────
# Step 4: CLAUDE.md
# ─────────────────────────────────────────
COUNTER=$((COUNTER + 1))
echo -e "${GREEN}[${COUNTER}/${TOTAL}]${NC} 检查 CLAUDE.md..."

if [[ ! -f "${TARGET_DIR}/CLAUDE.md" ]]; then
  PROJECT_NAME=$(basename "$TARGET_DIR")
  cat > "${TARGET_DIR}/CLAUDE.md" << CLAUDE_EOF
# >>> legion-init execution-discipline/v2 >>>
# 指挥官自主权（全局第一原则）

所有 L1 指挥官在所有项目中默认拥有流程决策的完全自主权。

**流程决策（要不要组团 / 侦察 / spec / 审查 / 放行 / 升级复杂度 / 选技能 / 选 teammate 配置）→ 直接判断执行，不向用户确认。**

## 军团核心原则：规模优先

军团体系的核心目标是：**不计资源消耗成本，通过最大化有效军团规模协作，实现效率和质量的最大化提升。**

默认策略：

1. **资源成本不是降级理由** — token、时间、进程数、tmux 窗口数、模型调用成本，不得作为少组团、少侦察、少审查、少验证的理由。
2. **默认向上扩编** — 遇到非平凡任务，优先用 \`--corps\` 按专业分支扩编 L2，并并行组织侦察 / 实现 / 审查 / 验证 / 审计 / 产品 / UI 等军种。
3. **最大有效规模，不是盲目重复** — 扩编必须带来互补视角或并行吞吐：不同文件范围、不同风险假设、不同验证方法、不同专业分支。禁止多个军团无差别重复同一动作。
4. **质量门前置且独立** — 实现与审计/验证必须分离；中型及以上任务默认引入独立 review / verify / audit 分支，不以“节省成本”为由省略。
5. **上下文即资产** — 动态扩编 L2 是否解散，取决于其持有上下文是否仍有价值；需要后续迭代、失败诊断、复杂背景延续时保留，不需要时才释放。

本原则中的“不计成本”指资源消耗成本，不覆盖下面四种例外；不可逆破坏、需求歧义、跨项目共享状态、高返工风险仍必须停下请示。

## 四种例外：只有这些情形才停下问用户

1. **不可逆破坏** — rm -rf、force push 主分支、drop table、覆盖未提交代码、删除分支、删除未备份数据
2. **需求本身模糊** — 有多种合理解释，无法通过读代码 / 读 memory 消除歧义
3. **跨项目 / 共享状态变更** — 影响他人、跨 repo、改 CI/CD 管线、改全局配置 / hooks / 技能 / 全局 AGENTS.md / 全局 CLAUDE.md
4. **关键决策成本高** — 走到死胡同需要大成本返工的岔路口

## 句式纪律

**禁止**：任何形式的流程确认（"我打算…可以吗" / "要不要先 recon" / "需要我组团吗" / "可以进入下一步吗"）——这些都是流程决策，指挥官全权自主。
**允许**：汇报已发生动作（"已经 xxx，结果是 xxx"）、命中例外时的停下请示（"命中第 N 种例外：[情形]，请你决定：[A / B]"）。

## 覆盖优先级

项目级 AGENTS.md / CLAUDE.md 可以覆盖本规则。需要更严格的人工确认流程，在项目 AGENTS.md 或 CLAUDE.md 里写"禁用自主权第一原则"即可。

---

# 作战执行纪律（按任务复杂度分级，Hook 辅助提醒）

接到任务后**先判断复杂度**，确认问题后**再评估一次**（修复可能比预期复杂），再决定执行方式：

| 复杂度 | 判断标准 | 侦察 | 团队 | 验证 |
|--------|---------|------|------|------|
| **S 级** | 单文件 bug/配置/查询 | 跳过 | 跳过 | cargo check / tsc 即可 |
| **M 级** | 2~5 文件、单域 | 1 路参谋 | 1-2 实现者 + 1 审查者 | 1 人（合规+红队合一） |
| **L 级** | 跨域、5+ 文件 | **2 路参谋**（技术+风险） | **流水线 + 交叉审查** | **2 人**（合规 + 红队） |
| **XL 级** | 10+ 文件、架构变更 | **3 路参谋**（技术+风险+内部） | **最大规模流水线 + worktree 隔离** | **3 人**（合规+红队+集成） |

**流水线制**：实现者全速推进→完成即刻触发审查→汇总反馈一轮修复→最终验证（读 .claude/skills/agent-team/SKILL.md）。

**铁律（不分级，始终适用）：**
1. 不跑验证不许说完成
2. 禁止降级核心目标（优先读 .claude/thought-weapons/degradation-policy/SKILL.md，否则 ~/.claude/skills/degradation-policy/SKILL.md）
3. 判错复杂度要往高走不往低走（拿不准 → 按更高级别执行）
4. **模型适配** — 写代码的 agent（implement, verify）必须 Opus；只读 agent（explore, review, plan）允许 Sonnet
5. **产品参谋必经** — 所有功能开发必须经产品参谋设计

## 执行流程

\`\`\`
三步深挖 → 判断复杂度 → 侦察(recon) → ⚡再评估 → 产品设计 → 设计(spec-driven) → 流水线实现+审查(agent-team) → 对抗性验证(audit)
\`\`\`

**指挥官简报**: \`.claude/commander/briefings/{L1名}.md\`
# <<< legion-init execution-discipline/v2 <<<

---

# Project: ${PROJECT_NAME}

## Tech Stack
<!-- TODO: 填写项目技术栈 -->

## Architecture
<!-- TODO: 填写项目架构 -->

## Coding Rules
<!-- TODO: 填写编码规范 -->
CLAUDE_EOF
  echo -e "  ${GREEN}✓ CLAUDE.md 模板已创建（请手动填写 Tech Stack / Architecture / Coding Rules）${NC}"
else
  # 检查是否包含执行纪律
  if claude_has_execution_discipline "${TARGET_DIR}/CLAUDE.md"; then
    echo "  → CLAUDE.md 已存在且包含执行纪律，跳过"
  else
    merge_claude_execution_discipline "${TARGET_DIR}/CLAUDE.md"
  fi
fi

# ─────────────────────────────────────────
# Step 5: settings.local.json
# ─────────────────────────────────────────
COUNTER=$((COUNTER + 1))
echo -e "${GREEN}[${COUNTER}/${TOTAL}]${NC} 检查 settings.local.json..."

if [[ ! -f "${TARGET_DIR}/.claude/settings.local.json" ]]; then
  cat > "${TARGET_DIR}/.claude/settings.local.json" << 'SETTINGS_EOF'
{
  "permissions": {
    "allow": []
  },
  "enabledMcpjsonServers": [
    "sequential-thinking",
    "memory",
    "fetch"
  ]
}
SETTINGS_EOF
  echo "  ✓ settings.local.json 已创建"
else
  echo "  → 已存在，跳过"
fi

# ─────────────────────────────────────────
# Step 6: Memory 目录
# ─────────────────────────────────────────
COUNTER=$((COUNTER + 1))
echo -e "${GREEN}[${COUNTER}/${TOTAL}]${NC} 创建 memory 目录..."

# 获取项目级 memory 路径（Claude Code 的标准路径）
MEMORY_DIR="$HOME/.claude/projects/-$(echo "$TARGET_DIR" | tr '/' '-')/memory"
mkdir -p "$MEMORY_DIR"

if [[ ! -f "${MEMORY_DIR}/MEMORY.md" ]]; then
  cat > "${MEMORY_DIR}/MEMORY.md" << 'MEMORY_EOF'
# Memory Index

## Project

## User

## Feedback

## Reference
MEMORY_EOF
  echo "  ✓ MEMORY.md 索引已创建"
else
  echo "  → MEMORY.md 已存在，跳过"
fi

# ─────────────────────────────────────────
# Step 7: 注册到全局 directory
# ─────────────────────────────────────────
COUNTER=$((COUNTER + 1))
echo -e "${GREEN}[${COUNTER}/${TOTAL}]${NC} 注册到军团目录..."

PROJECT_HASH=$(echo -n "$TARGET_DIR" | md5 | cut -c1-8)
LEGION_DIR="$HOME/.claude/legion/${PROJECT_HASH}"
mkdir -p "$LEGION_DIR"

# 初始化 registry 和 locks
[[ -f "$LEGION_DIR/registry.json" ]] || echo '{"teams":[]}' > "$LEGION_DIR/registry.json"
[[ -f "$LEGION_DIR/locks.json" ]] || echo '{"locks":[]}' > "$LEGION_DIR/locks.json"

# 更新全局 directory
DIRECTORY="$HOME/.claude/legion/directory.json"
mkdir -p "$(dirname "$DIRECTORY")"
[[ -f "$DIRECTORY" ]] || echo '{"legions":[]}' > "$DIRECTORY"
python3 -c "
import json, time
d = json.load(open('$DIRECTORY'))
legions = d.get('legions', [])
# 更新或新增
found = False
for l in legions:
    if l['hash'] == '${PROJECT_HASH}':
        l['last_active'] = time.strftime('%Y-%m-%dT%H:%M:%SZ')
        found = True
        break
if not found:
    legions.append({
        'hash': '${PROJECT_HASH}',
        'project': '$(basename "$TARGET_DIR")',
        'path': '${TARGET_DIR}',
        'cc_team': 'legion-${PROJECT_HASH}',
        'last_active': time.strftime('%Y-%m-%dT%H:%M:%SZ')
    })
d['legions'] = legions
json.dump(d, open('$DIRECTORY', 'w'), indent=4, ensure_ascii=False)
print('  ✓ 已注册到全局目录 (hash: ${PROJECT_HASH})')
"

# ─────────────────────────────────────────
# 完成
# ─────────────────────────────────────────
echo ""
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ 初始化完成！${NC}"
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo ""
echo "  下一步："
echo "  1. 编辑 CLAUDE.md 填写项目专属信息（Tech Stack / Architecture / Coding Rules）"
echo "  2. cd ${TARGET_DIR} && ~/.claude/scripts/legion.sh l1"
echo "     → 启动军团指挥官"
echo ""
echo "  快速验证："
echo "  ~/.claude/scripts/legion.sh status"
echo ""
