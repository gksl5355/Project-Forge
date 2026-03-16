"""Detect Engine: Bash 실패 실시간 감지 → 패턴 매칭."""

from __future__ import annotations

import sqlite3

from forge.core.matcher import match_pattern
from forge.storage.queries import list_failures


def run_detect(
    tool_name: str,
    tool_response: dict,
    workspace_id: str,
    db: sqlite3.Connection,
) -> dict | None:
    """Bash 실패 감지 → 기존 패턴 매칭 → hookSpecificOutput JSON 또는 None.

    Returns:
        None if not a Bash failure or no match.
        dict with pattern info if match found.
    """
    if tool_name.lower() != "bash":
        return None

    exit_code = tool_response.get("exit_code", 0)
    try:
        exit_code = int(exit_code)
    except (TypeError, ValueError):
        exit_code = 0

    if exit_code == 0:
        return None

    stderr = tool_response.get("stderr") or ""
    failures = list_failures(db, workspace_id)
    matched = match_pattern(stderr, failures)

    if matched is None:
        return None

    additional_context = (
        f"⚠️ Forge: {matched.pattern} 패턴 감지. "
        f"{matched.avoid_hint} (Q: {matched.q:.2f})"
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": additional_context,
        }
    }
