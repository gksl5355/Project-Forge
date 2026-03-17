#!/bin/bash
# PostToolUse hook: forge detect 호출
set -e
trap 'exit 0' ERR

# Check if forge command exists
if ! command -v forge &> /dev/null; then
    echo "Warning: forge command not found. Skipping detect." >&2
    exit 0
fi

INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>&1) || true

if [ -z "$WORKSPACE" ]; then
    echo "Warning: Missing WORKSPACE in input." >&2
    exit 0
fi

echo "$INPUT" | forge detect --workspace "$WORKSPACE" 2>&1 || {
    echo "Warning: forge detect failed." >&2
    exit 0
}
