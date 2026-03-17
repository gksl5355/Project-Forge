#!/bin/bash
# teammate.sh — Team agent model wrapper (managed by Forge)
#
# Reads signal files for per-spawn model selection.
# Default: Sonnet. Write signal before spawn for other models.
#
# Signal file paths (checked in order):
#   /tmp/claude-team-model-{agent-name}  (agent-specific)
#   /tmp/claude-team-model               (generic fallback)

AGENT_NAME=""
PREV=""
for arg in "$@"; do
    if [[ "$PREV" == "--agent-name" ]]; then
        AGENT_NAME="$arg"
        break
    fi
    PREV="$arg"
done

MODEL="claude-sonnet-4-6"
if [ -n "$AGENT_NAME" ] && [ -f "/tmp/claude-team-model-${AGENT_NAME}" ]; then
    VAL=$(cat "/tmp/claude-team-model-${AGENT_NAME}")
    rm -f "/tmp/claude-team-model-${AGENT_NAME}"
    case "$VAL" in
        claude-opus-4-6|claude-sonnet-4-6|claude-haiku-4-5) MODEL="$VAL" ;;
    esac
elif [ -f "/tmp/claude-team-model" ]; then
    VAL=$(cat "/tmp/claude-team-model")
    rm -f "/tmp/claude-team-model"
    case "$VAL" in
        claude-opus-4-6|claude-sonnet-4-6|claude-haiku-4-5) MODEL="$VAL" ;;
    esac
fi

args=()
skip_next=false
for arg in "$@"; do
    if $skip_next; then skip_next=false; continue; fi
    if [[ "$arg" == "--model" ]]; then skip_next=true; continue; fi
    if [[ "$arg" == --model=* ]]; then continue; fi
    args+=("$arg")
done

exec claude "${args[@]}" --model "$MODEL"
