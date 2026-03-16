#!/bin/bash
# SessionStart hook: forge resume 호출
INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null)

if [ -z "$WORKSPACE" ] || [ -z "$SESSION_ID" ]; then
    exit 0
fi

forge resume --workspace "$WORKSPACE" --session-id "$SESSION_ID"
