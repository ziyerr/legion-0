#!/usr/bin/env bash
# Install ~/.claude git hooks from scripts/hooks/ source to .git/hooks/
# Run this after cloning ~/.claude to a new machine.

set -e

CLAUDE_DIR="$HOME/.claude"
SRC_DIR="$CLAUDE_DIR/scripts/hooks"
DST_DIR="$CLAUDE_DIR/.git/hooks"

if [ ! -d "$CLAUDE_DIR/.git" ]; then
    echo "error: $CLAUDE_DIR is not a git repository" >&2
    exit 1
fi

if [ ! -d "$SRC_DIR" ]; then
    echo "error: $SRC_DIR does not exist" >&2
    exit 1
fi

# Install pre-commit (template sync for agents/ and skills/)
if [ -f "$SRC_DIR/pre-commit.sh" ]; then
    cp "$SRC_DIR/pre-commit.sh" "$DST_DIR/pre-commit"
    chmod +x "$DST_DIR/pre-commit"
    echo "installed: $DST_DIR/pre-commit"
fi

# Install post-commit (auto push to remote)
if [ -f "$SRC_DIR/post-commit.sh" ]; then
    cp "$SRC_DIR/post-commit.sh" "$DST_DIR/post-commit"
    chmod +x "$DST_DIR/post-commit"
    echo "installed: $DST_DIR/post-commit"
fi

echo "done."
