#!/bin/bash
# [DEPRECATED] legion-env.sh — 已被 Claude Code 原生 teammate 环境替代
# CC 通过 --agent-id --team-name --agent-name 自动设置环境变量
# 通信通过 SendMessage 工具而非 shell 函数
[[ -n "${CLAUDE_LEGION_TEAM_ID:-}" ]] && echo "[legion-env] 已废弃，请使用 SendMessage 工具通信" >&2
