"""Detect Engine: Bash 실패 실시간 감지 → 패턴 매칭."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from forge.config import ForgeConfig
from forge.core.matcher import match_pattern
from forge.storage.queries import list_failures, list_rules

logger = logging.getLogger("forge")
_RULES_LOG = Path.home() / ".forge" / "rules.log"


def run_detect(
    tool_name: str,
    tool_response: dict,
    workspace_id: str,
    db: sqlite3.Connection,
    session_id: str | None = None,
    config: ForgeConfig | None = None,
) -> dict | None:
    """Bash 실패 감지 → 규칙/패턴 매칭 → hookSpecificOutput JSON 또는 None.

    Returns:
        None if not a Bash failure or no match.
        dict with pattern info if match found.
    """
    # Track all tool calls (for circuit breaker)
    if session_id and config and config.circuit_breaker_enabled:
        from forge.core.circuit_breaker import check_breaker, increment_tool_call

        try:
            increment_tool_call(db, session_id)
            breaker = check_breaker(db, session_id, config)
            if breaker.is_tripped:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": f"⚠️ [CIRCUIT BREAKER] {breaker.trip_reason}",
                    }
                }
        except Exception:
            pass

    if tool_name.lower() != "bash":
        return None

    exit_code = tool_response.get("exit_code", 0)
    try:
        exit_code = int(exit_code)
    except (TypeError, ValueError):
        exit_code = 0

    if exit_code == 0:
        # Reset failures on success
        if session_id and config and config.circuit_breaker_enabled:
            from forge.core.circuit_breaker import reset_failures

            try:
                reset_failures(db, session_id)
            except Exception:
                pass
        return None

    stderr = tool_response.get("stderr") or ""
    command = tool_response.get("command") or ""

    # Track failures (for circuit breaker)
    if session_id and config and config.circuit_breaker_enabled:
        from forge.core.circuit_breaker import increment_failure

        try:
            increment_failure(db, session_id)
        except Exception:
            pass

    # Active rules: collect strongest match per enforcement mode
    block_match = None
    warn_match = None
    log_match = None

    for rule in list_rules(db, workspace_id):
        if rule.rule_text in stderr or rule.rule_text in command:
            if rule.enforcement_mode == "block" and block_match is None:
                block_match = rule
            elif rule.enforcement_mode == "warn" and warn_match is None:
                warn_match = rule
            elif rule.enforcement_mode == "log" and log_match is None:
                log_match = rule

    # Log-mode rules always write to log file
    if log_match is not None:
        _append_rules_log(log_match.rule_text, command, stderr)

    # Failure pattern match
    failures = list_failures(db, workspace_id)
    matched_failure = match_pattern(stderr, failures)

    # Return strongest match: block > warn > failure pattern
    if block_match is not None:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"[BLOCK] Forge Rule: {block_match.rule_text}",
            }
        }
    if warn_match is not None:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"[WARN] Forge Rule: {warn_match.rule_text}",
            }
        }
    if matched_failure is not None:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"⚠️ Forge: {matched_failure.pattern} 패턴 감지. "
                    f"{matched_failure.avoid_hint} (Q: {matched_failure.q:.2f})"
                ),
            }
        }
    return None


def _append_rules_log(rule_text: str, command: str, stderr: str) -> None:
    """log 모드 규칙 매칭을 ~/.forge/rules.log에 기록."""
    try:
        _RULES_LOG.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat()
        with _RULES_LOG.open("a", encoding="utf-8") as f:
            f.write(
                f"{timestamp} [LOG] Rule matched: {rule_text!r}"
                f" | cmd={command!r} | stderr={stderr[:200]!r}\n"
            )
    except OSError:
        logger.warning("Could not write to rules.log")
