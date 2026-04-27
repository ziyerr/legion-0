#!/usr/bin/env bash
# Mixed Claude/Codex Legion wrapper.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/legion_core.py" "$@"
