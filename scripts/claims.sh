#!/bin/bash
# claims.sh — 文件 claim 管理（带文件锁 + 过期清理）
# 用法:
#   claims.sh claim <file> <commander> <task>   — claim 一个文件
#   claims.sh release <commander>                — 释放指定指挥官的所有 claim
#   claims.sh check <file>                       — 检查文件是否被 claim
#   claims.sh list                               — 列出所有活跃 claim
#   claims.sh gc                                 — 清理过期 claim (>30分钟)

set -euo pipefail

CLAIMS_FILE=".claude/commander/active_claims.json"
LOCK_FILE="${CLAIMS_FILE}.lock"

ACTION="${1:-list}"
shift || true

# 确保文件和锁存在
[[ ! -f "$CLAIMS_FILE" ]] && echo '{"claims":[],"updated":""}' > "$CLAIMS_FILE"
touch "$LOCK_FILE"

# 通过环境变量传参给 Python，避免 shell 变量插值和引号问题
export _CLAIMS_FILE="$CLAIMS_FILE"
export _LOCK_FILE="$LOCK_FILE"
export _ACTION="$ACTION"
export _ARG1="${1:-}"
export _ARG2="${2:-}"
export _ARG3="${3:-}"

exec python3 << 'PYEOF'
import json, fcntl, os, sys
from datetime import datetime

CLAIMS_FILE = os.environ["_CLAIMS_FILE"]
LOCK_FILE = os.environ["_LOCK_FILE"]
ACTION = os.environ["_ACTION"]
ARG1 = os.environ.get("_ARG1", "")
ARG2 = os.environ.get("_ARG2", "")
ARG3 = os.environ.get("_ARG3", "")
EXPIRY_SECONDS = 30 * 60  # 30 minutes

with open(LOCK_FILE, "r") as lf:
    fcntl.flock(lf, fcntl.LOCK_EX)
    try:
        # Read
        try:
            with open(CLAIMS_FILE) as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            data = {"claims": [], "updated": ""}

        claims = data.get("claims", [])

        # Auto-GC expired claims on every operation
        now = datetime.now()
        before = len(claims)
        valid = []
        for c in claims:
            since_str = c.get("since", now.isoformat()).replace("Z", "")
            try:
                age = (now - datetime.fromisoformat(since_str)).total_seconds()
            except ValueError:
                age = EXPIRY_SECONDS + 1
            if age < EXPIRY_SECONDS:
                valid.append(c)
        claims = valid
        if len(claims) < before:
            print(f"[claims] auto-cleaned {before - len(claims)} expired claim(s)", file=sys.stderr)

        # Dispatch action
        if ACTION == "claim":
            file_path = ARG1
            commander = ARG2
            task = ARG3
            if not file_path or not commander:
                print("用法: claims.sh claim <file> <commander> <task>")
                sys.exit(1)
            for c in claims:
                if c["file"] == file_path and c["commander"] != commander:
                    print(f"CONFLICT: {c['file']} claimed by {c['commander']} (task: {c.get('task', '')})")
                    sys.exit(1)
            claims = [c for c in claims if not (c["file"] == file_path and c["commander"] == commander)]
            claims.append({"file": file_path, "commander": commander, "task": task, "since": now.isoformat()})
            print(f"OK: {commander} claimed {file_path}")

        elif ACTION == "release":
            commander = ARG1
            if not commander:
                print("用法: claims.sh release <commander>")
                sys.exit(1)
            before_count = len(claims)
            claims = [c for c in claims if c["commander"] != commander]
            released = before_count - len(claims)
            print(f"Released {released} claim(s) ({commander})")

        elif ACTION == "check":
            file_path = ARG1
            if not file_path:
                print("用法: claims.sh check <file>")
                sys.exit(1)
            conflict = [c for c in claims if c["file"] == file_path]
            if conflict:
                c = conflict[0]
                since_str = c["since"].replace("Z", "")
                age = int((now - datetime.fromisoformat(since_str)).total_seconds() / 60)
                print(f"CLAIMED: {c['file']} by {c['commander']} (task: {c.get('task', '')}, {age}min ago)")
            else:
                print(f"FREE: {file_path}")

        elif ACTION == "list":
            if not claims:
                print("(no active claims)")
            else:
                for c in claims:
                    since_str = c["since"].replace("Z", "")
                    age = int((now - datetime.fromisoformat(since_str)).total_seconds() / 60)
                    print(f"  {c['commander']} -> {c['file']} ({c.get('task', '')} {age}min ago)")
                print(f"Total: {len(claims)} active claim(s)")

        elif ACTION == "gc":
            print(f"GC done, {len(claims)} active claim(s) remaining")

        else:
            print("用法: claims.sh {claim|release|check|list|gc}")
            sys.exit(1)

        # Write back
        data["claims"] = claims
        data["updated"] = datetime.now().isoformat()
        with open(CLAIMS_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
PYEOF
