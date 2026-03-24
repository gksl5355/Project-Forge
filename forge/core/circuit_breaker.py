"""Circuit breaker to prevent infinite loops and runaway sessions."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from forge.config import ForgeConfig

logger = logging.getLogger("forge")


@dataclass
class BreakerState:
    """State of circuit breaker for a session."""

    session_id: str
    consecutive_failures: int
    tool_calls: int
    is_tripped: bool
    trip_reason: str | None = None


def _get_breaker_state_raw(
    conn: sqlite3.Connection, session_id: str
) -> dict[str, Any]:
    """Load breaker state from forge_meta as JSON. Returns empty dict if not found."""
    cursor = conn.execute(
        "SELECT value FROM forge_meta WHERE key = ?", (f"breaker:{session_id}",)
    )
    row = cursor.fetchone()
    if row is None:
        return {"consecutive_failures": 0, "tool_calls": 0}
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse breaker state for %s", session_id)
        return {"consecutive_failures": 0, "tool_calls": 0}


def _save_breaker_state_raw(
    conn: sqlite3.Connection, session_id: str, state: dict[str, Any]
) -> None:
    """Save breaker state to forge_meta as JSON."""
    state_json = json.dumps(state)
    conn.execute(
        """
        INSERT INTO forge_meta (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
        (f"breaker:{session_id}", state_json),
    )
    conn.commit()


def check_breaker(
    conn: sqlite3.Connection, session_id: str, config: ForgeConfig
) -> BreakerState:
    """
    Check if circuit breaker should trip.
    Reads state from forge_meta (key: f"breaker:{session_id}")
    Returns BreakerState with is_tripped=True if limits exceeded.
    """
    if not config.circuit_breaker_enabled:
        return BreakerState(
            session_id=session_id,
            consecutive_failures=0,
            tool_calls=0,
            is_tripped=False,
            trip_reason=None,
        )

    state = _get_breaker_state_raw(conn, session_id)
    consecutive_failures = state.get("consecutive_failures", 0)
    tool_calls = state.get("tool_calls", 0)

    trip_reason = None
    is_tripped = False

    if consecutive_failures >= config.max_consecutive_failures:
        is_tripped = True
        trip_reason = f"consecutive_failures={consecutive_failures} >= max={config.max_consecutive_failures}"
        logger.warning(
            "Circuit breaker tripped for %s: %s", session_id, trip_reason
        )

    if tool_calls >= config.max_tool_calls_per_session:
        is_tripped = True
        trip_reason = f"tool_calls={tool_calls} >= max={config.max_tool_calls_per_session}"
        logger.warning(
            "Circuit breaker tripped for %s: %s", session_id, trip_reason
        )

    return BreakerState(
        session_id=session_id,
        consecutive_failures=consecutive_failures,
        tool_calls=tool_calls,
        is_tripped=is_tripped,
        trip_reason=trip_reason,
    )


def increment_failure(conn: sqlite3.Connection, session_id: str) -> int:
    """Increment consecutive failure count. Returns new count."""
    state = _get_breaker_state_raw(conn, session_id)
    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    _save_breaker_state_raw(conn, session_id, state)
    return state["consecutive_failures"]


def increment_tool_call(conn: sqlite3.Connection, session_id: str) -> int:
    """Increment tool call count. Returns new count."""
    state = _get_breaker_state_raw(conn, session_id)
    state["tool_calls"] = state.get("tool_calls", 0) + 1
    _save_breaker_state_raw(conn, session_id, state)
    return state["tool_calls"]


def reset_failures(conn: sqlite3.Connection, session_id: str) -> None:
    """Reset consecutive failure count (on success)."""
    state = _get_breaker_state_raw(conn, session_id)
    state["consecutive_failures"] = 0
    _save_breaker_state_raw(conn, session_id, state)


def record_circuit_break(
    conn: sqlite3.Connection, session_id: str, reason: str
) -> None:
    """Record that a circuit break occurred (for stats/measure)."""
    state = _get_breaker_state_raw(conn, session_id)
    state["tripped"] = True
    state["trip_reason"] = reason
    state["trip_timestamp"] = json.dumps(
        {}
    )  # Placeholder for timestamp tracking if needed
    _save_breaker_state_raw(conn, session_id, state)
    logger.info("Recorded circuit break for %s: %s", session_id, reason)


def get_breaker_stats(
    conn: sqlite3.Connection, workspace_id: str | None = None
) -> dict[str, Any]:
    """
    Get circuit breaker statistics:
    - total_sessions: number of sessions with breaker state
    - total_breaks: number of sessions that tripped
    - break_rate: percentage of sessions that tripped
    - avg_tool_calls_per_session: average tool calls
    - common_trip_reasons: list of most common trip reasons
    """
    cursor = conn.execute(
        "SELECT key, value FROM forge_meta WHERE key LIKE 'breaker:%'"
    )
    rows = cursor.fetchall()

    total_sessions = len(rows)
    total_breaks = 0
    trip_reasons: dict[str, int] = {}
    total_tool_calls = 0
    sessions_with_tool_calls = 0

    for row in rows:
        try:
            state = json.loads(row[1])
            if state.get("tripped", False):
                total_breaks += 1
            if state.get("trip_reason"):
                reason = state["trip_reason"]
                trip_reasons[reason] = trip_reasons.get(reason, 0) + 1
            tool_calls = state.get("tool_calls", 0)
            if tool_calls > 0:
                total_tool_calls += tool_calls
                sessions_with_tool_calls += 1
        except (json.JSONDecodeError, TypeError):
            pass

    break_rate = (total_breaks / total_sessions * 100) if total_sessions > 0 else 0.0
    avg_tool_calls = (
        (total_tool_calls / sessions_with_tool_calls)
        if sessions_with_tool_calls > 0
        else 0.0
    )

    # Sort trip reasons by frequency
    common_trip_reasons = sorted(trip_reasons.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_sessions": total_sessions,
        "total_breaks": total_breaks,
        "break_rate_percent": round(break_rate, 2),
        "avg_tool_calls_per_session": round(avg_tool_calls, 2),
        "common_trip_reasons": [
            {"reason": reason, "count": count} for reason, count in common_trip_reasons
        ],
    }
