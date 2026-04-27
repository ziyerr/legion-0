#!/usr/bin/env bash
# Post-commit hook: fire-and-forget push to remote.
#
# Rationale: Keep ~/.claude/ continuously synced to the remote backup so
# new machines can clone and recover the full harness state. Runs in
# background so it never blocks commits. Failures are logged to
# ~/.claude/.git/push.log for debugging.
#
# This is safe from recursion because push does not create new commits.

set -e

cd "$HOME/.claude"

# Only push if remote 'origin' exists
if ! git remote | grep -q '^origin$'; then
    # No remote configured, nothing to push
    exit 0
fi

# Get current branch
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "master")

# Fire-and-forget push in background
{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] pushing $BRANCH to origin" >> "$HOME/.claude/.git/push.log"
    git push origin "$BRANCH" 2>> "$HOME/.claude/.git/push.log"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] push exit $?" >> "$HOME/.claude/.git/push.log"
} &

exit 0
