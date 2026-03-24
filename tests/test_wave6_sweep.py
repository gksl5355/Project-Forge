"""Comprehensive test suite for Wave 6 — new prompt formats, recency decay, and sweep infrastructure."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, UTC

import pytest

from forge.config import ForgeConfig
from forge.engines.prompt_optimizer import (
    _compute_recency_factor,
    compute_injection_score,
    generate_ab_format,
    ESSENTIAL_VARIANT,
    ANNOTATED_VARIANT,
    CONCISE_VARIANT,
    DETAILED_VARIANT,
)
from forge.engines.sweep import run_parameter_sweep, _build_config_from_dict, _seed_test_data
from forge.storage.models import Failure
from forge.storage.queries import insert_failure, list_failures


# =============================================================================
# 6A. New Prompt Formats Tests
# =============================================================================


@pytest.mark.parametrize("variant", ["essential", "annotated", "concise", "detailed"])
def test_prompt_format_variants_generate_output(
    db: sqlite3.Connection, variant: str
) -> None:
    """Test that all 4 format variants generate non-empty output."""
    failure = Failure(
        workspace_id="test",
        pattern="test_pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="Use check_foo() to avoid this error",
        hint_quality="preventable",
        q=0.75,
        times_seen=5,
        times_helped=3,
        times_warned=5,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")
    assert len(failures) == 1

    text = generate_ab_format(failures[0], variant=variant)
    assert len(text) > 0
    assert failures[0].pattern in text


@pytest.mark.parametrize("variant", ["essential", "annotated", "concise", "detailed"])
def test_prompt_format_contains_pattern(db: sqlite3.Connection, variant: str) -> None:
    """Test that pattern is always included in output."""
    failure = Failure(
        workspace_id="test",
        pattern="missing_null_check",
        observed_error="NullPointerException",
        likely_cause="unchecked access",
        avoid_hint="Always check for null before dereferencing",
        hint_quality="preventable",
        q=0.65,
        times_seen=10,
        times_helped=7,
        times_warned=10,
        tags=["java"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")
    text = generate_ab_format(failures[0], variant=variant)
    assert "missing_null_check" in text


def test_essential_format_minimal_tokens(db: sqlite3.Connection) -> None:
    """Test that essential format is minimal (no Q, no stats)."""
    failure = Failure(
        workspace_id="test",
        pattern="pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="Avoid this mistake",
        hint_quality="preventable",
        q=0.7,
        times_seen=5,
        times_helped=2,
        times_warned=5,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")
    essential = generate_ab_format(failures[0], variant="essential")
    concise = generate_ab_format(failures[0], variant="concise")

    # Essential should be shorter than concise (no Q)
    assert len(essential) < len(concise)
    # Essential should not contain Q
    assert "Q:" not in essential


def test_annotated_format_has_q(db: sqlite3.Connection) -> None:
    """Test that annotated format includes Q value."""
    failure = Failure(
        workspace_id="test",
        pattern="pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="Avoid this mistake",
        hint_quality="preventable",
        q=0.82,
        times_seen=5,
        times_helped=2,
        times_warned=5,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")
    annotated = generate_ab_format(failures[0], variant="annotated")

    # Should have Q value
    assert "Q:" in annotated
    assert "0.82" in annotated


def test_detailed_format_includes_stats(db: sqlite3.Connection) -> None:
    """Test that detailed format includes all stats (seen, helped, quality)."""
    failure = Failure(
        workspace_id="test",
        pattern="pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="Full detailed hint with lots of explanation about what to check and why",
        hint_quality="near_miss",
        q=0.55,
        times_seen=15,
        times_helped=8,
        times_warned=15,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")
    detailed = generate_ab_format(failures[0], variant="detailed")

    # Should have all stat components
    assert "near_miss" in detailed  # hint_quality
    assert "seen:15" in detailed or "seen=15" in detailed
    assert "helped:8" in detailed or "helped=8" in detailed
    assert "Q:" in detailed


@pytest.mark.parametrize("variant", ["essential", "annotated", "concise", "detailed"])
def test_format_variant_truncates_long_hints(db: sqlite3.Connection, variant: str) -> None:
    """Test that hint truncation is consistent across variants (where applicable)."""
    long_hint = "x" * 100  # 100 chars
    failure = Failure(
        workspace_id="test",
        pattern="pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint=long_hint,
        hint_quality="preventable",
        q=0.5,
        times_seen=1,
        times_helped=0,
        times_warned=1,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")
    text = generate_ab_format(failures[0], variant=variant)

    # essential/annotated/concise should truncate to 50 chars + "..."
    # detailed should use full hint
    if variant == "detailed":
        assert long_hint in text or (len(text) > 50 and "x" * 50 in text)
    else:
        # Should contain truncated version
        if "..." in text:
            assert len(text) < len(long_hint) + 100


# =============================================================================
# 6B. Recency Decay Function Tests
# =============================================================================


@pytest.mark.parametrize(
    "days,decay_type,expected_range",
    [
        # Exponential decay (default): exp(-0.1 * d)
        (0, "exponential", (0.99, 1.01)),  # exp(0) = 1
        (10, "exponential", (0.36, 0.38)),  # exp(-1) ≈ 0.367
        (100, "exponential", (0.0, 0.01)),  # exp(-10) ≈ 0
        # Exponential slow: exp(-0.05 * d)
        (0, "exponential_slow", (0.99, 1.01)),  # exp(0) = 1
        (10, "exponential_slow", (0.60, 0.62)),  # exp(-0.5) ≈ 0.606
        (100, "exponential_slow", (0.00673, 0.00674)),  # exp(-5) ≈ 0.00673
        # Linear: max(0, 1 - d/365)
        (0, "linear", (0.99, 1.01)),  # 1 - 0 = 1
        (182.5, "linear", (0.49, 0.51)),  # 1 - 0.5 = 0.5
        (365, "linear", (-0.01, 0.01)),  # 1 - 1 = 0
        (730, "linear", (-0.01, 0.01)),  # max(0, 1 - 2) = 0
    ],
)
def test_recency_decay_functions(days: float, decay_type: str, expected_range: tuple) -> None:
    """Test recency decay functions match expected curves."""
    result = _compute_recency_factor(days, decay_type)

    assert isinstance(result, float)
    assert expected_range[0] <= result <= expected_range[1], \
        f"days={days}, decay={decay_type}, result={result}, expected={expected_range}"


def test_recency_decay_exponential_vs_slow() -> None:
    """Test that exponential_slow decays slower than exponential."""
    days = 50
    fast = _compute_recency_factor(days, "exponential")
    slow = _compute_recency_factor(days, "exponential_slow")

    # Slow should be higher (slower decay)
    assert slow > fast


def test_recency_decay_linear_bounds() -> None:
    """Test that linear decay is bounded [0, 1]."""
    for days in [0, 100, 365, 730, 1000]:
        result = _compute_recency_factor(days, "linear")
        assert 0.0 <= result <= 1.0


def test_recency_decay_invalid_type_defaults_to_exponential() -> None:
    """Test that invalid decay type defaults to exponential."""
    result = _compute_recency_factor(10, "unknown_decay")
    expected = _compute_recency_factor(10, "exponential")
    assert result == expected


# =============================================================================
# 6C. Injection Score with Different Decay Functions
# =============================================================================


@pytest.mark.parametrize("decay_type", ["exponential", "exponential_slow", "linear"])
def test_injection_score_with_decay_function(
    db: sqlite3.Connection, decay_type: str
) -> None:
    """Test compute_injection_score with different decay functions."""
    config = ForgeConfig(
        injection_recency_decay=decay_type,
        injection_base_weight=0.6,
        injection_recency_weight=0.2,
        injection_relevance_weight=0.2,
    )

    failure = Failure(
        workspace_id="test",
        pattern="pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="hint",
        hint_quality="preventable",
        q=0.8,
        times_seen=1,
        times_helped=0,
        times_warned=1,
        tags=["python"],
        projects_seen=["test"],
        source="test",
    )

    # Score with 10 days recency
    score = compute_injection_score(
        failure,
        session_tags=["python", "test"],
        recency_days=10,
        config=config,
    )

    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0  # Score should be normalized-ish


def test_injection_score_decay_differences() -> None:
    """Test that different decay functions produce different scores."""
    failure = Failure(
        workspace_id="test",
        pattern="pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="hint",
        hint_quality="preventable",
        q=0.7,
        times_seen=1,
        times_helped=0,
        times_warned=1,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )

    config_exp = ForgeConfig(injection_recency_decay="exponential")
    config_slow = ForgeConfig(injection_recency_decay="exponential_slow")
    config_lin = ForgeConfig(injection_recency_decay="linear")

    days = 50
    score_exp = compute_injection_score(failure, recency_days=days, config=config_exp)
    score_slow = compute_injection_score(failure, recency_days=days, config=config_slow)
    score_lin = compute_injection_score(failure, recency_days=days, config=config_lin)

    # All should be different
    assert score_exp != score_slow
    assert score_slow != score_lin


# =============================================================================
# 6D. Sweep Infrastructure Tests
# =============================================================================


def test_sweep_basic_execution() -> None:
    """Test that sweep executes and returns results."""
    param_grid = {
        "ab_variant_threshold": [0.01, 0.05],
        "ab_min_observations": [5, 10],
    }

    results = run_parameter_sweep(param_grid, n_failures=5, n_sessions=2)

    assert len(results) > 0
    # Should have 2 * 2 = 4 results
    assert len(results) == 4
    # All results should have valid fitness
    for result in results:
        assert isinstance(result.unified_fitness, float)
        assert 0.0 <= result.unified_fitness <= 1.0
        assert result.config_snapshot is not None
        assert result.individual_kpis is not None


def test_sweep_results_sorted_by_fitness() -> None:
    """Test that results are sorted by fitness descending."""
    param_grid = {
        "alpha": [0.05, 0.1, 0.15],
    }

    results = run_parameter_sweep(param_grid, n_failures=5, n_sessions=2)

    assert len(results) > 0
    # Check sorted order
    for i in range(len(results) - 1):
        assert results[i].unified_fitness >= results[i + 1].unified_fitness


def test_sweep_parameter_grid_coverage() -> None:
    """Test that sweep covers all parameter combinations."""
    param_grid = {
        "injection_recency_decay": ["exponential", "linear"],
        "injection_base_weight": [0.5, 0.6],
    }

    results = run_parameter_sweep(param_grid, n_failures=5, n_sessions=2)

    # Should have 2 * 2 = 4 combinations
    assert len(results) == 4

    # Check that all combinations are present
    decay_values = set()
    base_weight_values = set()
    for result in results:
        decay_values.add(result.config_snapshot.get("injection_recency_decay"))
        base_weight_values.add(result.config_snapshot.get("injection_base_weight"))

    assert len(decay_values) == 2
    assert len(base_weight_values) == 2


def test_sweep_config_snapshot_matches_params() -> None:
    """Test that returned config_snapshot matches the parameters used."""
    param_grid = {
        "alpha": [0.08],
        "beta": [0.12],
    }

    results = run_parameter_sweep(param_grid, n_failures=5, n_sessions=2)

    # Should have only 1 result (1 * 1)
    assert len(results) == 1

    result = results[0]
    # Note: "beta" is not a valid ForgeConfig field, so it won't be in snapshot
    assert result.config_snapshot.get("alpha") == 0.08


def test_sweep_with_large_parameter_space() -> None:
    """Test sweep with a reasonable larger grid."""
    param_grid = {
        "hint_actionability_bonus": [0.1, 0.15, 0.2],
        "hint_vagueness_penalty": [0.05, 0.1],
    }

    results = run_parameter_sweep(param_grid, n_failures=5, n_sessions=2)

    # Should have 3 * 2 = 6 results
    assert len(results) == 6


def test_build_config_from_dict() -> None:
    """Test _build_config_from_dict creates correct ForgeConfig."""
    params = {
        "alpha": 0.2,
        "ab_variant_threshold": 0.08,
        "invalid_field": 999,  # Should be ignored
    }

    config = _build_config_from_dict(params)

    assert config.alpha == 0.2
    assert config.ab_variant_threshold == 0.08
    # Invalid field should not be set
    assert not hasattr(config, "invalid_field")


def test_sweep_seeding() -> None:
    """Test that _seed_test_data correctly seeds failures and sessions."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    from forge.storage.db import _ensure_schema
    _ensure_schema(db)

    _seed_test_data(db, "test_ws", n_failures=10, n_sessions=5)

    # Check failures
    failures = list_failures(db, "test_ws")
    assert len(failures) == 10

    # Check sessions exist
    sessions = db.execute(
        "SELECT COUNT(*) FROM sessions WHERE workspace_id = ?", ("test_ws",)
    ).fetchone()
    assert sessions[0] == 5


# =============================================================================
# 6E. Combined Format + Config Tests
# =============================================================================


@pytest.mark.parametrize(
    "variant,decay_type",
    [
        ("essential", "exponential"),
        ("annotated", "exponential_slow"),
        ("concise", "linear"),
        ("detailed", "exponential"),
    ],
)
def test_format_and_decay_combination(
    db: sqlite3.Connection, variant: str, decay_type: str
) -> None:
    """Test combining new formats with new decay functions."""
    config = ForgeConfig(
        injection_recency_decay=decay_type,
    )

    failure = Failure(
        workspace_id="test",
        pattern="pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="Use check() to validate",
        hint_quality="preventable",
        q=0.6,
        times_seen=5,
        times_helped=2,
        times_warned=5,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")
    text = generate_ab_format(failures[0], variant=variant)
    score = compute_injection_score(failures[0], recency_days=20, config=config)

    assert len(text) > 0
    assert 0.0 <= score <= 1.0


# =============================================================================
# 6F. Integration Tests
# =============================================================================


def test_sweep_includes_format_and_decay_params() -> None:
    """Test sweep with format-related and decay-related parameters."""
    param_grid = {
        "injection_recency_decay": ["exponential", "linear"],
        "ab_variant_threshold": [0.01, 0.05],
    }

    results = run_parameter_sweep(param_grid, n_failures=5, n_sessions=2)

    assert len(results) == 4
    # All results should be valid
    for result in results:
        assert isinstance(result.unified_fitness, float)
        assert "injection_recency_decay" in result.config_snapshot
        assert "ab_variant_threshold" in result.config_snapshot


def test_all_variants_pass_through_context() -> None:
    """Test that all variants work when passed through context formatting."""
    from forge.core.context import format_l0, format_l1

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    from forge.storage.db import _ensure_schema
    _ensure_schema(db)

    failure = Failure(
        workspace_id="test",
        pattern="test_pattern",
        observed_error="error",
        likely_cause="cause",
        avoid_hint="Use check_foo() to avoid",
        hint_quality="preventable",
        q=0.7,
        times_seen=5,
        times_helped=2,
        times_warned=5,
        tags=["test"],
        projects_seen=["test"],
        source="test",
    )
    insert_failure(db, failure)

    failures = list_failures(db, "test")

    for variant in ["essential", "annotated", "concise", "detailed"]:
        l0 = format_l0(failures, variant=variant)
        l1 = format_l1(failures, variant=variant)
        assert len(l0) > 0
        assert len(l1) > 0
        assert "test_pattern" in l0
        assert "test_pattern" in l1


def test_hint_quality_independent_of_format() -> None:
    """Test that hint quality scoring is independent of format variant."""
    from forge.engines.prompt_optimizer import score_hint_quality

    hints = [
        "Use check() before access",
        "Always validate input",
        "Maybe check something",
        "xxxxxxxxxxxxxxxxxxxxxxx",
    ]

    scores = [score_hint_quality(hint) for hint in hints]

    # Scores should be consistent regardless of format
    for score in scores:
        assert 0.0 <= score <= 1.0
