#!/bin/bash
# SessionEnd hook: forge writeback 호출
INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null)
TRANSCRIPT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" 2>/dev/null)

if [ -z "$WORKSPACE" ] || [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT" ]; then
    exit 0
fi

forge writeback --workspace "$WORKSPACE" --session-id "$SESSION_ID" --transcript "$TRANSCRIPT"
