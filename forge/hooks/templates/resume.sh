#!/bin/bash
# SessionStart hook: forge resume 호출
set -e
trap 'exit 0' ERR

# Check if forge command exists
if ! command -v forge &> /dev/null; then
    echo "Warning: forge command not found. Skipping resume." >&2
    exit 0
fi

INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>&1) || true
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>&1) || true

if [ -z "$WORKSPACE" ] || [ -z "$SESSION_ID" ]; then
    echo "Warning: Missing WORKSPACE or SESSION_ID in input." >&2
    exit 0
fi

forge resume --workspace "$WORKSPACE" --session-id "$SESSION_ID" 2>&1 || {
    echo "Warning: forge resume failed." >&2
    exit 0
}
