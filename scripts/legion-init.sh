#!/bin/bash
# ============================================================================
# legion-init.sh — 军团系统项目初始化
# ============================================================================
#
# 在任意新项目目录执行，自动完成军团系统项目级初始化：
#   1. 复制 skills（从参考项目）
#   2. 复制 agents（从参考项目）
#   3. 创建 commander 简报目录
#   4. 生成 CLAUDE.md 模板（如不存在）
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
      cp -r "${REF_SKILLS_DIR}/${skill}" "${TARGET_DIR}/.claude/skills/"
      echo "  ✓ ${skill}"
    else
      echo -e "  ${YELLOW}⚠ ${skill} 不存在于参考项目${NC}"
    fi
  done
else
  # 复制全部技能
  for skill_dir in "${REF_SKILLS_DIR}"/*; do
    [[ -d "$skill_dir" ]] || continue
    skill_name=$(basename "$skill_dir")
    cp -r "$skill_dir" "${TARGET_DIR}/.claude/skills/"
  done
fi
SKILL_COUNT=$(find "${TARGET_DIR}/.claude/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')

echo -e "  ${GREEN}→ ${SKILL_COUNT} 个技能已就位${NC}"

# Codex uses .agents/skills as its project skill root. Keep a lightweight bridge
# so Codex L1/L2 commanders can discover Claude-native Legion skills.
mkdir -p "${TARGET_DIR}/.agents/skills/claw-roundtable-skill"
cat > "${TARGET_DIR}/.agents/skills/claw-roundtable-skill/SKILL.md" << 'CODEX_ROUNDTABLE_SKILL_EOF'
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

This is a shared weapon for all L1/L2 branches. Every branch can invoke it when the task requires multi-perspective decision pressure, but completion claims require runtime health evidence.
CODEX_ROUNDTABLE_SKILL_EOF
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
      cp "${REF_AGENTS_DIR}/${agent}" "${TARGET_DIR}/.claude/agents/"
      echo "  ✓ ${agent}"
    fi
  done
else
  cp "${REF_AGENTS_DIR}/"*.md "${TARGET_DIR}/.claude/agents/" 2>/dev/null
fi

AGENT_COUNT=$(ls "${TARGET_DIR}/.claude/agents/"*.md 2>/dev/null | wc -l | tr -d ' ')
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
# ⛔ 执行纪律（按任务复杂度分级，Hook 辅助提醒）

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

---

# Harness 哲学（架构原则）

## 为删除而写
每个 hook、skill、脚本都是临时的。模型升级时，先删再加。

## 三步深挖（苏格拉底 + 第一性原理 + 奥卡姆剃刀）
接到需求默认过一遍：用户说的是真需求吗？基于基本事实的最优解是什么？最小可执行方案是什么？

---

# Project: ${PROJECT_NAME}

## Tech Stack
<!-- TODO: 填写项目技术栈 -->

## Architecture
<!-- TODO: 填写项目架构 -->

## Coding Rules
<!-- TODO: 填写编码规范 -->

## 执行流程

\`\`\`
三步深挖 → 判断复杂度 → 侦察(recon) → ⚡再评估 → 产品设计 → 设计(spec-driven) → 流水线实现+审查(agent-team) → 对抗性验证(audit)
\`\`\`

**指挥官简报**: \`.claude/commander/briefings/{L1名}.md\`

通过 TeamCreate 创建 teammate（tmux 模式），每个 teammate 独立 pane。
CLAUDE_EOF
  echo -e "  ${GREEN}✓ CLAUDE.md 模板已创建（请手动填写 Tech Stack / Architecture / Coding Rules）${NC}"
else
  # 检查是否包含执行纪律
  if grep -q "执行纪律" "${TARGET_DIR}/CLAUDE.md" 2>/dev/null; then
    echo "  → CLAUDE.md 已存在且包含执行纪律，跳过"
  else
    echo -e "  ${YELLOW}⚠ CLAUDE.md 已存在但缺少执行纪律模板，请手动补充${NC}"
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
