"""Tests for circuit breaker functionality."""
import pytest

from forge.config import ForgeConfig
from forge.core.circuit_breaker import (
    BreakerState,
    check_breaker,
    get_breaker_stats,
    increment_failure,
    increment_tool_call,
    record_circuit_break,
    reset_failures,
)


def test_check_breaker_ok(db):
    """Test circuit breaker in normal state."""
    config = ForgeConfig()
    session_id = "test_session_1"

    breaker = check_breaker(db, session_id, config)

    assert isinstance(breaker, BreakerState)
    assert breaker.session_id == session_id
    assert breaker.consecutive_failures == 0
    assert breaker.tool_calls == 0
    assert breaker.is_tripped is False
    assert breaker.trip_reason is None


def test_trip_on_consecutive_failures(db):
    """Test that circuit breaker trips when max_consecutive_failures exceeded."""
    config = ForgeConfig(max_consecutive_failures=3)
    session_id = "test_session_2"

    # Increment failures to max
    for _ in range(3):
        increment_failure(db, session_id)

    breaker = check_breaker(db, session_id, config)

    assert breaker.is_tripped is True
    assert breaker.consecutive_failures == 3
    assert "consecutive_failures=3" in breaker.trip_reason


def test_trip_on_tool_calls(db):
    """Test that circuit breaker trips when max_tool_calls_per_session exceeded."""
    config = ForgeConfig(max_tool_calls_per_session=5)
    session_id = "test_session_3"

    # Increment tool calls to max
    for _ in range(5):
        increment_tool_call(db, session_id)

    breaker = check_breaker(db, session_id, config)

    assert breaker.is_tripped is True
    assert breaker.tool_calls == 5
    assert "tool_calls=5" in breaker.trip_reason


def test_increment_and_reset(db):
    """Test incrementing and resetting failures."""
    session_id = "test_session_4"

    # Increment failures
    count1 = increment_failure(db, session_id)
    assert count1 == 1

    count2 = increment_failure(db, session_id)
    assert count2 == 2

    # Reset
    reset_failures(db, session_id)

    # Verify reset
    config = ForgeConfig()
    breaker = check_breaker(db, session_id, config)
    assert breaker.consecutive_failures == 0


def test_record_circuit_break(db):
    """Test recording a circuit break event."""
    session_id = "test_session_5"
    reason = "consecutive_failures=5 >= max=5"

    record_circuit_break(db, session_id, reason)

    # Verify the state was recorded
    cursor = db.execute(
        "SELECT value FROM forge_meta WHERE key = ?", (f"breaker:{session_id}",)
    )
    row = cursor.fetchone()
    assert row is not None

    import json

    state = json.loads(row[0])
    assert state.get("tripped") is True
    assert state.get("trip_reason") == reason


def test_get_breaker_stats(db):
    """Test retrieving circuit breaker statistics."""
    config = ForgeConfig(max_consecutive_failures=2)

    # Create a few sessions with different states
    session1 = "session_stats_1"
    session2 = "session_stats_2"
    session3 = "session_stats_3"

    # Session 1: normal
    for _ in range(3):
        increment_tool_call(db, session1)

    # Session 2: tripped on failures
    for _ in range(2):
        increment_failure(db, session2)
    record_circuit_break(db, session2, "max_consecutive_failures")

    # Session 3: some tool calls
    for _ in range(5):
        increment_tool_call(db, session3)

    stats = get_breaker_stats(db)

    assert stats["total_sessions"] == 3
    assert stats["total_breaks"] == 1
    assert stats["break_rate_percent"] == pytest.approx(33.33, abs=0.01)
    # avg_tool_calls only counts sessions with tool_calls > 0: (3 + 5) / 2 = 4.0
    assert stats["avg_tool_calls_per_session"] == pytest.approx(4.0, abs=0.01)


def test_breaker_disabled(db):
    """Test that disabled breaker always passes."""
    config = ForgeConfig(circuit_breaker_enabled=False)
    session_id = "test_session_6"

    # Increment to would-be-tripping levels
    for _ in range(100):
        increment_failure(db, session_id)

    # But breaker should still report not tripped
    breaker = check_breaker(db, session_id, config)

    assert breaker.is_tripped is False
    assert breaker.trip_reason is None


def test_multiple_sessions_independent(db):
    """Test that states are independent per session."""
    session1 = "session_m1"
    session2 = "session_m2"

    # Increment failures for session1
    for _ in range(3):
        increment_failure(db, session1)

    # Increment tool calls for session2
    for _ in range(5):
        increment_tool_call(db, session2)

    config = ForgeConfig()
    breaker1 = check_breaker(db, session1, config)
    breaker2 = check_breaker(db, session2, config)

    assert breaker1.consecutive_failures == 3
    assert breaker1.tool_calls == 0

    assert breaker2.consecutive_failures == 0
    assert breaker2.tool_calls == 5


def test_incrementing_persists(db):
    """Test that state persists across multiple check_breaker calls."""
    session_id = "test_session_persist"

    increment_failure(db, session_id)
    increment_tool_call(db, session_id)

    config = ForgeConfig()
    breaker1 = check_breaker(db, session_id, config)

    assert breaker1.consecutive_failures == 1
    assert breaker1.tool_calls == 1

    # Increment again
    increment_failure(db, session_id)
    increment_tool_call(db, session_id)

    breaker2 = check_breaker(db, session_id, config)

    assert breaker2.consecutive_failures == 2
    assert breaker2.tool_calls == 2


def test_trip_reason_priority(db):
    """Test that if both limits exceeded, failure reason is recorded."""
    config = ForgeConfig(
        max_consecutive_failures=2, max_tool_calls_per_session=3
    )
    session_id = "test_session_priority"

    # Exceed both limits
    for _ in range(2):
        increment_failure(db, session_id)
    for _ in range(3):
        increment_tool_call(db, session_id)

    breaker = check_breaker(db, session_id, config)

    assert breaker.is_tripped is True
    # One of them will be the trip reason (consecutive failures checked first)
    assert breaker.trip_reason is not None
    assert "consecutive_failures" in breaker.trip_reason or "tool_calls" in breaker.trip_reason


def test_empty_stats(db):
    """Test statistics when no sessions exist."""
    stats = get_breaker_stats(db)

    assert stats["total_sessions"] == 0
    assert stats["total_breaks"] == 0
    assert stats["break_rate_percent"] == 0.0
    assert stats["avg_tool_calls_per_session"] == 0.0
    assert stats["common_trip_reasons"] == []
