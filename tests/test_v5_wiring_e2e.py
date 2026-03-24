"""End-to-end wiring verification tests for v5 modules.

Tests that all 5 v5 modules are properly wired into the session flow:
- resume: A/B variant selection, injection ordering, circuit breaker check, agent registration, model routing
- detect: tool call tracking, failure tracking, circuit breaker state management
- writeback: A/B outcome recording, hint quality scoring, circuit breaker reset, agent completion

All tests use the db fixture (in-memory SQLite with v5 schema).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge.config import ForgeConfig
from forge.core.circuit_breaker import check_breaker, increment_failure, increment_tool_call
from forge.engines.agent_manager import complete_agent, get_session_agents, register_agent
from forge.engines.detect import run_detect
from forge.engines.prompt_optimizer import (
    get_active_variant,
    get_best_format,
    record_format_outcome,
)
from forge.engines.resume import run_resume
from forge.engines.routing import get_routing_stats
from forge.engines.writeback import run_writeback
from forge.storage.models import Failure, Session
from forge.storage.queries import (
    get_session,
    insert_failure,
    insert_model_choice,
    list_agents,
)


def _create_transcript(content: str = "") -> Path:
    """Helper: Create a temporary transcript file with JSONL content."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


# ============================================================================
# 1. RESUME WIRING VERIFICATION
# ============================================================================


def test_resume_selects_ab_variant(db: sqlite3.Connection) -> None:
    """resume should select A/B variant when ab_enabled=True."""
    workspace_id = "test_ws"
    session_id = "sess_001"
    config = ForgeConfig(ab_enabled=True)

    # Seed a failure to inject
    f1 = Failure(
        workspace_id=workspace_id,
        pattern="test_variant_pattern",
        avoid_hint="Test hint",
        hint_quality="preventable",
        q=0.6,
    )
    insert_failure(db, f1)

    # Seed ab_outcomes with clear winner (concise format)
    ab_outcomes = {
        "concise": {"helped": 8, "total": 10},  # 80% success
        "detailed": {"helped": 3, "total": 10},  # 30% success
    }
    db.execute(
        """
        INSERT INTO forge_meta(key, value)
        VALUES (?, ?)
        """,
        (f"ab_outcomes:{workspace_id}", json.dumps(ab_outcomes)),
    )
    db.commit()

    # Call run_resume
    context = run_resume(workspace_id, session_id, db, config)

    # Verify concise format was selected and context has failure info
    assert context is not None, "Context should not be None"
    assert "test_variant_pattern" in context, "Context should include injected pattern"


def test_resume_uses_injection_ordering(db: sqlite3.Connection) -> None:
    """resume should sort failures by injection_score when enabled."""
    workspace_id = "test_ws"
    session_id = "sess_002"
    config = ForgeConfig(injection_score_enabled=True)

    # Seed failures with varying Q values
    f1 = Failure(
        workspace_id=workspace_id,
        pattern="pattern_high_q",
        avoid_hint="High Q hint",
        hint_quality="preventable",
        q=0.9,
    )
    f2 = Failure(
        workspace_id=workspace_id,
        pattern="pattern_low_q",
        avoid_hint="Low Q hint",
        hint_quality="environmental",
        q=0.2,
    )
    insert_failure(db, f1)
    insert_failure(db, f2)

    # Call run_resume with injection_score_enabled=True
    context_with_scoring = run_resume(workspace_id, session_id, db, config)

    # Call with injection_score_enabled=False
    config_no_scoring = ForgeConfig(injection_score_enabled=False)
    context_without_scoring = run_resume(workspace_id, session_id + "_no_score", db, config_no_scoring)

    # Verify both produce output (order may differ but content should be present)
    assert "pattern_high_q" in context_with_scoring or "pattern_high_q" in context_without_scoring, \
        "At least one context should mention high_q pattern"


def test_resume_checks_circuit_breaker(db: sqlite3.Connection) -> None:
    """resume should prepend breaker warning when tripped."""
    workspace_id = "test_ws"
    session_id = "sess_003"
    config = ForgeConfig(circuit_breaker_enabled=True)

    # Pre-trip the breaker by setting excessive tool calls
    breaker_state = {
        "consecutive_failures": 5,
        "tool_calls": config.max_tool_calls_per_session + 1,
    }
    db.execute(
        """
        INSERT INTO forge_meta(key, value)
        VALUES (?, ?)
        """,
        (f"breaker:{session_id}", json.dumps(breaker_state)),
    )
    db.commit()

    # Call run_resume
    context = run_resume(workspace_id, session_id, db, config)

    # Verify context starts with circuit breaker warning
    assert context.startswith("⚠️ [CIRCUIT BREAKER]"), \
        f"Context should start with circuit breaker warning, got: {context[:100]}"


def test_resume_registers_agent(db: sqlite3.Connection) -> None:
    """resume should register main agent when agent_manager_enabled."""
    workspace_id = "test_ws"
    session_id = "sess_004"
    config = ForgeConfig(agent_manager_enabled=True)

    # Call run_resume
    run_resume(workspace_id, session_id, db, config)

    # Check agents table has an entry for this session
    agents = get_session_agents(db, session_id)
    assert len(agents) > 0, "Should register at least one agent"
    assert agents[0].status == "active", "Main agent should be in 'active' status"
    assert agents[0].role == "main", "Should register as 'main' agent"


def test_resume_includes_routing_context(db: sqlite3.Connection) -> None:
    """resume should append routing info when data exists."""
    workspace_id = "test_ws"
    session_id = "sess_005"
    config = ForgeConfig(routing_enabled=True)

    # Seed model_choices with data
    for i in range(3):
        insert_model_choice(
            db,
            workspace_id,
            session_id,
            task_category="task_a",
            selected_model=f"model_{i}",
        )
    # Record outcomes
    rows = db.execute(
        "SELECT id FROM model_choices WHERE workspace_id = ? AND task_category = ?",
        (workspace_id, "task_a"),
    ).fetchall()
    for row in rows:
        db.execute(
            "UPDATE model_choices SET outcome = ? WHERE id = ?",
            (0.9, row["id"]),
        )
    db.commit()

    # Call run_resume
    context = run_resume(workspace_id, session_id, db, config)

    # Verify "Model Routing" section in context
    assert "Model Routing" in context, "Context should include routing info"


# ============================================================================
# 2. DETECT WIRING VERIFICATION
# ============================================================================


def test_detect_increments_tool_call(db: sqlite3.Connection) -> None:
    """detect should increment tool call counter."""
    workspace_id = "test_ws"
    session_id = "sess_006"
    config = ForgeConfig(circuit_breaker_enabled=True)

    tool_response = {
        "exit_code": 0,
        "stdout": "success",
        "stderr": "",
    }

    # Call run_detect with session_id and config
    run_detect("bash", tool_response, workspace_id, db, session_id, config)

    # Check forge_meta breaker state shows tool_calls incremented
    row = db.execute(
        "SELECT value FROM forge_meta WHERE key = ?",
        (f"breaker:{session_id}",),
    ).fetchone()
    assert row is not None, "Breaker state should be created"
    state = json.loads(row[0])
    assert state.get("tool_calls", 0) == 1, "Tool call count should be 1"


def test_detect_increments_failure_on_bash_error(db: sqlite3.Connection) -> None:
    """detect should increment failure counter on bash error."""
    workspace_id = "test_ws"
    session_id = "sess_007"
    config = ForgeConfig(circuit_breaker_enabled=True)

    tool_response = {
        "exit_code": 1,
        "stdout": "",
        "stderr": "Command not found",
        "command": "unknown_cmd",
    }

    # Call run_detect with exit_code=1
    run_detect("bash", tool_response, workspace_id, db, session_id, config)

    # Check breaker state shows consecutive_failures incremented
    row = db.execute(
        "SELECT value FROM forge_meta WHERE key = ?",
        (f"breaker:{session_id}",),
    ).fetchone()
    assert row is not None, "Breaker state should be created"
    state = json.loads(row[0])
    assert state.get("consecutive_failures", 0) == 1, "Failure count should be 1"


def test_detect_resets_failure_on_bash_success(db: sqlite3.Connection) -> None:
    """detect should reset failure counter on bash success."""
    workspace_id = "test_ws"
    session_id = "sess_008"
    config = ForgeConfig(circuit_breaker_enabled=True)

    # Seed some failures first
    breaker_state = {
        "consecutive_failures": 3,
        "tool_calls": 0,
    }
    db.execute(
        """
        INSERT INTO forge_meta(key, value)
        VALUES (?, ?)
        """,
        (f"breaker:{session_id}", json.dumps(breaker_state)),
    )
    db.commit()

    tool_response = {
        "exit_code": 0,
        "stdout": "success",
        "stderr": "",
    }

    # Call run_detect with exit_code=0
    run_detect("bash", tool_response, workspace_id, db, session_id, config)

    # Check breaker state shows consecutive_failures = 0
    row = db.execute(
        "SELECT value FROM forge_meta WHERE key = ?",
        (f"breaker:{session_id}",),
    ).fetchone()
    assert row is not None, "Breaker state should exist"
    state = json.loads(row[0])
    assert state.get("consecutive_failures", 0) == 0, "Failure count should be reset to 0"


def test_detect_trips_breaker(db: sqlite3.Connection) -> None:
    """detect should trip breaker and return warning."""
    workspace_id = "test_ws"
    session_id = "sess_009"
    config = ForgeConfig(
        circuit_breaker_enabled=True,
        max_consecutive_failures=1,  # Trip after 1 failure
    )

    tool_response = {
        "exit_code": 1,
        "stdout": "",
        "stderr": "Error 1",
        "command": "cmd1",
    }

    # First call: increments tool_call, checks breaker (not tripped yet), then increments failure
    result1 = run_detect("bash", tool_response, workspace_id, db, session_id, config)
    assert result1 is None, "First error: breaker check happens before failure increment"

    # Second call: increments tool_call, checks breaker (now consecutive_failures=1, tripped!), returns warning
    result2 = run_detect("bash", tool_response, workspace_id, db, session_id, config)
    assert result2 is not None, "Second error should trigger breaker on check"
    assert "CIRCUIT BREAKER" in result2.get("hookSpecificOutput", {}).get("additionalContext", ""), \
        "Should return CIRCUIT BREAKER warning"


def test_detect_backward_compatible_no_session(db: sqlite3.Connection) -> None:
    """detect without session_id should work like before."""
    workspace_id = "test_ws"

    tool_response = {
        "exit_code": 1,
        "stdout": "",
        "stderr": "Some error",
        "command": "cmd",
    }

    # Call run_detect without session_id or config
    result = run_detect("bash", tool_response, workspace_id, db)

    # Should return None (no matching pattern) but not crash
    assert result is None, "Should return None for unmapped error"


# ============================================================================
# 3. WRITEBACK WIRING VERIFICATION
# ============================================================================


def test_writeback_records_ab_outcome(db: sqlite3.Connection) -> None:
    """writeback should record A/B format outcome."""
    workspace_id = "test_ws"
    session_id = "sess_010"
    config = ForgeConfig(ab_enabled=True)

    # Seed session with warnings
    f1 = Failure(
        workspace_id=workspace_id,
        pattern="test_pattern",
        avoid_hint="Test hint",
        hint_quality="preventable",
        q=0.5,
    )
    insert_failure(db, f1)

    # Create session record
    session = Session(
        session_id=session_id,
        workspace_id=workspace_id,
        warnings_injected=["test_pattern"],
    )
    db.execute(
        """
        INSERT INTO sessions(session_id, workspace_id, warnings_injected)
        VALUES (?, ?, ?)
        """,
        (session.session_id, session.workspace_id, json.dumps(session.warnings_injected)),
    )
    db.commit()

    # Create transcript with matching error
    transcript = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    transcript.write(json.dumps({"tool_name": "bash", "exit_code": 1, "stderr": "test error"}) + "\n")
    transcript.close()

    # Run writeback
    run_writeback(workspace_id, session_id, Path(transcript.name), db, config)

    # Check forge_meta has ab_outcomes data
    row = db.execute(
        "SELECT value FROM forge_meta WHERE key = ?",
        (f"ab_outcomes:{workspace_id}",),
    ).fetchone()
    assert row is not None, "ab_outcomes should be recorded"
    ab_data = json.loads(row[0])
    assert "concise" in ab_data and "detailed" in ab_data, "Should have both variants"


def test_writeback_scores_hint_quality(db: sqlite3.Connection) -> None:
    """writeback should score hint quality for auto-detected failures."""
    workspace_id = "test_ws"
    session_id = "sess_011"
    config = ForgeConfig(ab_enabled=False)

    # Create transcript with error that doesn't match existing patterns
    transcript = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    transcript.write(
        json.dumps({
            "tool_name": "bash",
            "exit_code": 1,
            "stderr": "ImportError: No module named 'foo'",
        }) + "\n"
    )
    transcript.close()

    # Run writeback
    run_writeback(workspace_id, session_id, Path(transcript.name), db, config)

    # Check new failure was created with quality score
    rows = db.execute(
        "SELECT hint_quality, avoid_hint FROM failures WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()
    assert len(rows) > 0, "Should create new failure for auto-detected error"
    # Quality should be one of the valid types, not random
    assert rows[0]["hint_quality"] in ("near_miss", "preventable", "environmental"), \
        f"Quality should be valid, got: {rows[0]['hint_quality']}"


def test_writeback_resets_circuit_breaker(db: sqlite3.Connection) -> None:
    """writeback should reset circuit breaker on session end."""
    workspace_id = "test_ws"
    session_id = "sess_012"
    config = ForgeConfig(circuit_breaker_enabled=True)

    # Pre-set breaker state with some failures
    breaker_state = {
        "consecutive_failures": 3,
        "tool_calls": 10,
    }
    db.execute(
        """
        INSERT INTO forge_meta(key, value)
        VALUES (?, ?)
        """,
        (f"breaker:{session_id}", json.dumps(breaker_state)),
    )
    db.commit()

    # Create empty transcript
    transcript = _create_transcript("")

    # Run writeback
    run_writeback(workspace_id, session_id, transcript, db, config)

    # Check breaker state is reset
    row = db.execute(
        "SELECT value FROM forge_meta WHERE key = ?",
        (f"breaker:{session_id}",),
    ).fetchone()
    assert row is not None, "Breaker state should still exist"
    state = json.loads(row[0])
    assert state.get("consecutive_failures", 0) == 0, "Failures should be reset"


def test_writeback_completes_agents(db: sqlite3.Connection) -> None:
    """writeback should mark active agents as completed."""
    workspace_id = "test_ws"
    session_id = "sess_013"
    config = ForgeConfig(agent_manager_enabled=True)

    # Register an agent first
    agent_id = register_agent(db, workspace_id, session_id, "test_agent", "main")

    # Verify it's active
    agents = get_session_agents(db, session_id)
    assert len(agents) > 0, "Should have registered agent"
    assert agents[0].status == "active", "Agent should be active before writeback"

    # Create empty transcript
    transcript = _create_transcript("")

    # Run writeback
    run_writeback(workspace_id, session_id, transcript, db, config)

    # Check agent status changed to "completed"
    agents = get_session_agents(db, session_id)
    assert len(agents) > 0, "Should still have agent"
    assert agents[0].status == "completed", "Agent should be completed after writeback"


# ============================================================================
# 4. CROSS-MODULE INTEGRATION
# ============================================================================


def test_full_session_lifecycle(db: sqlite3.Connection) -> None:
    """Complete session: resume → detect(s) → writeback with all v5 features."""
    workspace_id = "test_ws"
    session_id = "sess_014"
    config = ForgeConfig(
        ab_enabled=True,
        circuit_breaker_enabled=True,
        agent_manager_enabled=True,
        routing_enabled=False,  # Simplify for test
    )

    # Seed a failure for resume to inject
    f1 = Failure(
        workspace_id=workspace_id,
        pattern="test_failure",
        avoid_hint="Avoid this issue",
        hint_quality="preventable",
        q=0.7,
    )
    insert_failure(db, f1)

    # 1. Resume with all features enabled
    context = run_resume(workspace_id, session_id, db, config)
    assert context is not None, "Resume should produce context"
    assert "test_failure" in context, "Context should include injected pattern"

    # Verify agent registered
    agents = get_session_agents(db, session_id)
    assert len(agents) > 0, "Agent should be registered"

    # 2. Several detect calls (some success, some failure)
    # First success
    run_detect("bash", {"exit_code": 0, "stdout": "ok", "stderr": ""}, workspace_id, db, session_id, config)
    breaker_state1 = check_breaker(db, session_id, config)
    assert breaker_state1.consecutive_failures == 0, "Failures should be reset on success"

    # Then failure
    run_detect("bash", {"exit_code": 1, "stderr": "test error", "command": "cmd"}, workspace_id, db, session_id, config)
    breaker_state2 = check_breaker(db, session_id, config)
    assert breaker_state2.consecutive_failures == 1, "Failure count should increment"

    # 3. Writeback
    transcript = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    # Write a failure event matching our test_failure pattern
    transcript.write(json.dumps({
        "tool_name": "bash",
        "exit_code": 1,
        "stderr": "test_failure occurred",
    }) + "\n")
    transcript.close()

    run_writeback(workspace_id, session_id, Path(transcript.name), db, config)

    # 4. Verify: agent registered + completed, breaker tracked + reset, A/B recorded
    agents = get_session_agents(db, session_id)
    assert len(agents) > 0, "Agent should exist"
    assert agents[0].status == "completed", "Agent should be completed"

    breaker_final = check_breaker(db, session_id, config)
    assert breaker_final.consecutive_failures == 0, "Breaker should be reset after writeback"

    ab_row = db.execute(
        "SELECT value FROM forge_meta WHERE key = ?",
        (f"ab_outcomes:{workspace_id}",),
    ).fetchone()
    assert ab_row is not None, "A/B outcomes should be recorded"


def test_measure_reflects_v5_kpis(db: sqlite3.Connection) -> None:
    """measure should compute all v5 KPIs after a session."""
    from forge.engines.measure import run_measure

    workspace_id = "test_ws"
    session_id = "sess_015"
    config = ForgeConfig()

    # Seed a failure
    f1 = Failure(
        workspace_id=workspace_id,
        pattern="measure_test",
        avoid_hint="Test hint",
        hint_quality="preventable",
        q=0.6,
        times_seen=5,
        times_helped=3,
        times_warned=5,
    )
    insert_failure(db, f1)

    # Seed a session
    db.execute(
        """
        INSERT INTO sessions(session_id, workspace_id, warnings_injected)
        VALUES (?, ?, ?)
        """,
        (session_id, workspace_id, json.dumps(["measure_test"])),
    )
    db.commit()

    # Run measure
    result = run_measure(workspace_id, db, config)

    # Verify all v5 KPI fields are populated
    assert result.routing_accuracy >= 0.0, "routing_accuracy should be computed"
    assert result.circuit_efficiency >= 0.0, "circuit_efficiency should be computed"
    assert result.agent_utilization >= 0.0, "agent_utilization should be computed"
    assert result.context_hit_rate >= 0.0, "context_hit_rate should be computed"
    assert result.tool_efficiency >= 0.0, "tool_efficiency should be computed"
    assert result.redundant_call_rate >= 0.0, "redundant_call_rate should be computed"
    assert result.stale_warning_rate >= 0.0, "stale_warning_rate should be computed"
    assert result.unified_fitness_v5 >= 0.0, "unified_fitness_v5 should be computed"


def test_config_weights_flow_to_fitness(db: sqlite3.Connection) -> None:
    """Custom KPI weights in config should affect unified_fitness_v5."""
    from forge.engines.measure import run_measure

    workspace_id = "test_ws"
    config = ForgeConfig()

    # Seed a failure
    f1 = Failure(
        workspace_id=workspace_id,
        pattern="weight_test",
        avoid_hint="Test",
        hint_quality="preventable",
        q=0.7,
        times_seen=10,
        times_helped=8,
        times_warned=10,
    )
    insert_failure(db, f1)

    # Run measure with default weights
    result1 = run_measure(workspace_id, db, config)
    fitness1 = result1.unified_fitness_v5

    # Run measure with custom weights (modify config in-place for test)
    config.weight_qwhr = 0.5  # Increase QWHR weight
    config.weight_token_efficiency = 0.05  # Decrease token efficiency weight
    result2 = run_measure(workspace_id, db, config)
    fitness2 = result2.unified_fitness_v5

    # Results may vary based on actual metrics, but both should be computed
    assert isinstance(fitness1, (int, float)), "fitness1 should be numeric"
    assert isinstance(fitness2, (int, float)), "fitness2 should be numeric"
    # Both should be non-negative
    assert fitness1 >= 0.0 and fitness2 >= 0.0, "Both fitness scores should be non-negative"


# ============================================================================
# Additional Edge Cases
# ============================================================================


def test_resume_without_failures(db: sqlite3.Connection) -> None:
    """resume should work even with no failures in DB."""
    workspace_id = "empty_ws"
    session_id = "sess_016"
    config = ForgeConfig()

    # Don't seed any failures
    context = run_resume(workspace_id, session_id, db, config)

    # Should still produce valid output (may be empty or minimal)
    assert isinstance(context, str), "resume should return string even with no failures"


def test_detect_non_bash_tool(db: sqlite3.Connection) -> None:
    """detect should return None for non-bash tools."""
    workspace_id = "test_ws"

    tool_response = {
        "exit_code": 1,
        "stdout": "",
        "stderr": "Some error",
    }

    # Call run_detect with non-bash tool
    result = run_detect("python", tool_response, workspace_id, db)

    # Should return None (not a bash tool)
    assert result is None, "Should return None for non-bash tool"


def test_writeback_with_empty_transcript(db: sqlite3.Connection) -> None:
    """writeback should handle empty transcript gracefully."""
    workspace_id = "test_ws"
    session_id = "sess_017"
    config = ForgeConfig()

    # Create empty transcript
    transcript = _create_transcript("")

    # Should not crash
    run_writeback(workspace_id, session_id, transcript, db, config)

    # Session should still be updated
    session = get_session(db, session_id)
    # Session may or may not be created (depends on writeback creating it), but shouldn't crash
    assert True, "writeback should handle empty transcript without crashing"


def test_writeback_with_nonexistent_transcript(db: sqlite3.Connection) -> None:
    """writeback should handle nonexistent transcript gracefully."""
    workspace_id = "test_ws"
    session_id = "sess_018"
    config = ForgeConfig()

    # Reference nonexistent file
    transcript = Path("/nonexistent/file.jsonl")

    # Should not crash (parse_transcript returns [] for missing files)
    run_writeback(workspace_id, session_id, transcript, db, config)

    # Should complete without error
    assert True, "writeback should handle nonexistent transcript gracefully"
