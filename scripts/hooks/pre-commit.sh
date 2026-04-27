#!/usr/bin/env bash
# Pre-commit hook: sync legion template with agents/ and skills/ before commit.
#
# Rationale: ~/.claude/agents/ and the 8 core skills are the source of truth.
# ~/.claude/legion/template/.claude/{agents,skills}/ is the deployment template
# read by legion.sh. They must stay in sync. Running as pre-commit lets us
# stage the template sync into the same commit atomically.
#
# Monitors: agents/*.md and skills/{agent-team,audit,recon,product-counselor,
# ui-designer,sniper,degradation-policy,spec-driven}/
#
# Does NOT monitor: scripts/, memory/tactics/, commander/ (those are global
# but not part of the new-project deployment template per legion.sh:152).

set -e

# Check what's staged
STAGED_AGENTS=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null | grep -E '^agents/' || true)
STAGED_SKILLS=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null | grep -E '^skills/(agent-team|audit|recon|product-counselor|ui-designer|sniper|degradation-policy|spec-driven)/' || true)

if [ -z "$STAGED_AGENTS" ] && [ -z "$STAGED_SKILLS" ]; then
    # No monitored paths changed, nothing to sync
    exit 0
fi

AGENTS_DIR="$HOME/.claude/agents"
SKILLS_DIR="$HOME/.claude/skills"
TEMPLATE_AGENTS="$HOME/.claude/legion/template/.claude/agents"
TEMPLATE_SKILLS="$HOME/.claude/legion/template/.claude/skills"

if [ ! -d "$TEMPLATE_AGENTS" ]; then
    echo "pre-commit: $TEMPLATE_AGENTS does not exist, skipping sync" >&2
    exit 0
fi

CHANGED=()

# Sync agents if needed
if [ -n "$STAGED_AGENTS" ]; then
    cp "$AGENTS_DIR"/*.md "$TEMPLATE_AGENTS/" 2>/dev/null
    git add "$TEMPLATE_AGENTS"
    CHANGED+=("agents")
fi

# Sync skills if needed (only the 8 core skills legion.sh:152 expects)
if [ -n "$STAGED_SKILLS" ]; then
    mkdir -p "$TEMPLATE_SKILLS"
    for skill in agent-team audit recon product-counselor ui-designer sniper degradation-policy spec-driven; do
        src="$SKILLS_DIR/$skill"
        dst="$TEMPLATE_SKILLS/$skill"
        if [ -d "$src" ]; then
            rm -rf "$dst"
            mkdir -p "$dst"
            # Copy SKILL.md + references/ (per legion.sh:160 rule, don't copy knowledge/ contents)
            [ -f "$src/SKILL.md" ] && cp "$src/SKILL.md" "$dst/"
            [ -d "$src/references" ] && cp -r "$src/references" "$dst/"
            [ -d "$src/knowledge" ] && mkdir -p "$dst/knowledge"
        fi
    done
    git add "$TEMPLATE_SKILLS"
    CHANGED+=("skills")
fi

echo "pre-commit: synced ${CHANGED[*]} to legion/template/ and staged"
