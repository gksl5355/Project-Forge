#!/bin/bash
# SessionEnd hook: forge writeback 호출
set -e
trap 'exit 0' ERR

# Check if forge command exists
if ! command -v forge &> /dev/null; then
    echo "Warning: forge command not found. Skipping writeback." >&2
    exit 0
fi

INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>&1) || true
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>&1) || true
TRANSCRIPT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('transcript_path',''))" 2>&1) || true

if [ -z "$WORKSPACE" ] || [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT" ]; then
    echo "Warning: Missing WORKSPACE, SESSION_ID, or TRANSCRIPT in input." >&2
    exit 0
fi

forge writeback --workspace "$WORKSPACE" --session-id "$SESSION_ID" --transcript "$TRANSCRIPT" 2>&1 || {
    echo "Warning: forge writeback failed." >&2
    exit 0
}
