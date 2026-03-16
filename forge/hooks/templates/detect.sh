#!/bin/bash
# PostToolUse hook: forge detect 호출
INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)

if [ -z "$WORKSPACE" ]; then
    exit 0
fi

echo "$INPUT" | forge detect --workspace "$WORKSPACE"
