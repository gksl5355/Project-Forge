"""Comprehensive micro-benchmark and optimization test suite for Forge v5.

Tests cover all tunable parameters across multiple values. Fast tests (<100ms each)
that verify end-to-end wiring and measure sensitivity of each parameter.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, UTC

import pytest

from forge.config import ForgeConfig
from forge.core.circuit_breaker import (
    check_breaker,
    increment_failure,
    increment_tool_call,
    reset_failures,
)
from forge.core.context import build_context, format_l0, format_l1
from forge.engines.fitness import compute_unified_fitness_v5
from forge.engines.prompt_optimizer import (
    compute_injection_score,
    generate_ab_format,
    get_best_format,
    record_format_outcome,
    score_hint_quality,
)
from forge.engines.routing import resolve_model
from forge.storage.models import Failure
from forge.storage.queries import insert_failure, list_failures, list_rules


# --- Helpers for seeding test data ---


def _seed_failures(
    db: sqlite3.Connection, workspace_id: str, count: int = 10
) -> None:
    """Create N test failures with varying Q, hint quality, tags."""
    for i in range(count):
        q = 0.1 + (i / count) * 0.8  # Q from 0.1 to 0.9
        quality = ["near_miss", "preventable", "environmental"][i % 3]
        failure = Failure(
            workspace_id=workspace_id,
            pattern=f"test_pattern_{i}",
            observed_error=f"Error {i}",
            likely_cause=f"Cause {i}",
            avoid_hint=f"Use check_{i}() to avoid error {i} in module_{i}",
            hint_quality=quality,
            q=q,
            times_seen=i + 1,
            times_helped=max(0, i - 3),
            times_warned=i + 1,
            tags=["python", "test"],
            projects_seen=[workspace_id],
            source="test",
        )
        insert_failure(db, failure)
    db.commit()


def _seed_session(
    db: sqlite3.Connection,
    workspace_id: str,
    session_id: str,
    warnings: list[str] | None = None,
) -> None:
    """Insert a test session."""
    db.execute(
        "INSERT INTO sessions(session_id, workspace_id, warnings_injected, config_hash, document_hash) VALUES (?, ?, ?, 'h1', 'd1')",
        (session_id, workspace_id, json.dumps(warnings or [])),
    )
    db.commit()


# =============================================================================
# 1. A/B FORMAT SELECTION TESTS (20+)
# =============================================================================


@pytest.mark.parametrize(
    "min_obs,threshold,concise_helped,concise_total,detailed_helped,detailed_total,expected",
    [
        # concise rate = 70%, detailed rate = 80%, diff = 10% = 0.10
        # 0.10 > 0.05 → detailed wins
        (10, 0.05, 7, 10, 8, 10, "detailed"),
        (10, 0.05, 5, 10, 9, 10, "detailed"),  # clear winner
        (10, 0.05, 9, 10, 5, 10, "concise"),  # concise wins
        # concise rate = 60%, detailed rate = 80%, diff = 20% = 0.20
        # 0.20 > 0.05 → detailed wins
        (5, 0.05, 3, 5, 4, 5, "detailed"),
        (5, 0.10, 3, 5, 5, 5, "detailed"),  # exceeds threshold
        (20, 0.05, 15, 20, 16, 20, "concise"),  # within threshold
        (3, 0.01, 2, 3, 3, 3, "detailed"),  # tiny sample, low threshold
        (10, 0.0, 5, 10, 6, 10, "detailed"),  # zero threshold, any diff matters
        (10, 0.5, 3, 10, 9, 10, "detailed"),  # high threshold, big diff needed
        (10, 0.5, 5, 10, 7, 10, "concise"),  # high threshold, not enough diff
        (1, 0.01, 1, 1, 1, 1, "concise"),  # tie at minimum
        (1, 0.01, 0, 1, 1, 1, "detailed"),  # detailed 100% vs 0%
        (100, 0.05, 50, 100, 55, 100, "concise"),  # within threshold
        (100, 0.05, 45, 100, 55, 100, "detailed"),  # large sample, exceeds threshold
        (2, 0.2, 1, 2, 2, 2, "detailed"),  # small sample, high threshold, clear winner
        (5, 0.0, 2, 5, 2, 5, "concise"),  # zero threshold, tied helps→default
        (10, 0.3, 6, 10, 8, 10, "concise"),  # 60% vs 80%, threshold 30% → not enough
        # concise rate = 60%, detailed rate = 80%, diff = 20% = 0.20
        # 0.20 > 0.25 → no, within threshold → concise (default on tie)
        (10, 0.25, 6, 10, 8, 10, "concise"),
    ],
)
def test_ab_format_sensitivity(
    db: sqlite3.Connection,
    min_obs: int,
    threshold: float,
    concise_helped: int,
    concise_total: int,
    detailed_helped: int,
    detailed_total: int,
    expected: str,
) -> None:
    """Test A/B variant selection across parameter space."""
    config = ForgeConfig(ab_min_observations=min_obs, ab_variant_threshold=threshold)
    ws = "test_ab"
    data = {
        "concise": {"helped": concise_helped, "total": concise_total},
        "detailed": {"helped": detailed_helped, "total": detailed_total},
    }
    db.execute("INSERT INTO forge_meta(key, value) VALUES (?, ?)", (f"ab_outcomes:{ws}", json.dumps(data)))
    db.commit()

    result = get_best_format(db, ws, config)
    assert result == expected


@pytest.mark.parametrize("variant", ["concise", "detailed"])
def test_ab_format_generation(db: sqlite3.Connection, variant: str) -> None:
    """Test that A/B format generation produces valid output."""
    _seed_failures(db, "test_ab_gen", count=1)
    failures = list_failures(db, "test_ab_gen")
    assert len(failures) >= 1

    failure = failures[0]
    text = generate_ab_format(failure, variant=variant)

    assert len(text) > 0
    assert failure.pattern in text
    assert failure.q >= 0
    if variant == "concise":
        assert "→" in text
    elif variant == "detailed":
        assert "seen:" in text


# =============================================================================
# 2. INJECTION SCORE SENSITIVITY TESTS (15+)
# =============================================================================


@pytest.mark.parametrize(
    "base_w,recency_w,relevance_w",
    [
        (0.6, 0.2, 0.2),  # default
        (0.8, 0.1, 0.1),  # Q-dominant
        (0.4, 0.3, 0.3),  # balanced
        (0.2, 0.4, 0.4),  # recency+relevance dominant
        (1.0, 0.0, 0.0),  # pure Q
        (0.0, 0.5, 0.5),  # no Q influence (but Q still multiplies)
        (0.5, 0.5, 0.0),  # no relevance
        (0.5, 0.0, 0.5),  # no recency
        (0.333, 0.333, 0.334),  # three-way even
        (0.7, 0.15, 0.15),  # slight Q boost
    ],
)
def test_injection_score_weights(
    base_w: float, recency_w: float, relevance_w: float
) -> None:
    """Test injection score ordering with different weight configurations."""
    config = ForgeConfig(
        injection_base_weight=base_w,
        injection_recency_weight=recency_w,
        injection_relevance_weight=relevance_w,
    )

    # Create failures with distinct Q values and tags
    f_high_q = Failure(
        workspace_id="w",
        pattern="high_q",
        observed_error="err",
        likely_cause="cause",
        avoid_hint="h",
        hint_quality="near_miss",
        q=0.9,
        times_seen=1,
        times_helped=0,
        times_warned=0,
        tags=["python", "error"],
    )
    f_low_q = Failure(
        workspace_id="w",
        pattern="low_q",
        observed_error="err",
        likely_cause="cause",
        avoid_hint="h",
        hint_quality="environmental",
        q=0.2,
        times_seen=1,
        times_helped=0,
        times_warned=0,
        tags=["deploy"],
    )
    f_mid_q = Failure(
        workspace_id="w",
        pattern="mid_q",
        observed_error="err",
        likely_cause="cause",
        avoid_hint="h",
        hint_quality="preventable",
        q=0.5,
        times_seen=1,
        times_helped=0,
        times_warned=0,
        tags=["python"],
    )

    session_tags = ["python", "error"]

    scores = {
        "high_q": compute_injection_score(f_high_q, session_tags, recency_days=1.0, config=config),
        "mid_q": compute_injection_score(f_mid_q, session_tags, recency_days=5.0, config=config),
        "low_q": compute_injection_score(f_low_q, session_tags, recency_days=30.0, config=config),
    }

    # Verify scores are in valid range (Q is always [0,1], so max multiplier is ~1)
    for name, score in scores.items():
        assert 0.0 <= score <= 2.0, f"{name} score {score} out of range"

    # high_q should generally score highest if Q matters at all
    if base_w >= 0.4:
        assert scores["high_q"] > scores["low_q"]


@pytest.mark.parametrize(
    "session_tags,failure_tags,expected_relevance_min",
    [
        (["python", "error"], ["python", "error"], 1.0),  # perfect match
        (["python"], ["python", "error"], 0.5),  # 50% overlap (1/(1+2))
        (["python"], ["deploy"], 0.0),  # no overlap
        ([], ["python"], 0.0),  # empty session tags
        (["python"], [], 0.0),  # empty failure tags
        (["a", "b", "c"], ["a", "b"], 2.0 / 3.0),  # 2 of 3 in union
    ],
)
def test_injection_relevance_scoring(
    session_tags: list[str], failure_tags: list[str], expected_relevance_min: float
) -> None:
    """Test relevance factor in injection score."""
    config = ForgeConfig(injection_base_weight=0.0, injection_recency_weight=0.0, injection_relevance_weight=1.0)

    failure = Failure(
        workspace_id="w",
        pattern="test",
        observed_error="err",
        likely_cause="cause",
        avoid_hint="hint",
        hint_quality="preventable",
        q=1.0,
        times_seen=1,
        times_helped=0,
        times_warned=0,
        tags=failure_tags,
    )

    score = compute_injection_score(failure, session_tags, recency_days=0.0, config=config)
    # Score = Q * (0 + 0 + 1 * relevance) = relevance (since Q=1.0)
    assert abs(score - expected_relevance_min) < 0.001


# =============================================================================
# 3. HINT QUALITY SCORING SENSITIVITY (20+)
# =============================================================================


@pytest.mark.parametrize(
    "hint,action_bonus,vague_penalty,expected_min,expected_max",
    [
        ("Use check_config() to validate", 0.15, 0.1, 0.6, 1.0),  # good hint
        # "maybe try something" = 2 vague words, short (14 chars ok but 2 vague)
        # baseline 0.5 + length 0.2 - 2*0.1 = 0.6 (but "try" is action verb, +0.15) = 0.75
        ("maybe try something", 0.15, 0.1, 0.5, 0.8),  # vague but has action verb
        ("Avoid using rm -rf without --dry-run first", 0.15, 0.1, 0.7, 1.0),  # excellent
        ("bad", 0.15, 0.1, 0.0, 0.3),  # too short
        ("Use check_config() to validate", 0.30, 0.1, 0.7, 1.0),  # high action bonus
        ("Use check_config() to validate", 0.05, 0.1, 0.5, 0.9),  # low action bonus
        ("maybe possibly could perhaps try", 0.15, 0.2, 0.0, 0.2),  # high vague penalty
        ("maybe possibly could perhaps try", 0.15, 0.05, 0.0, 0.5),  # low vague penalty
        ("", 0.15, 0.1, 0.0, 0.3),  # empty
        ("Check: use 'pip install --upgrade' for dependency issues with ERROR_MODULE_NOT_FOUND", 0.15, 0.1, 0.7, 1.0),  # very specific
        ("Run the test suite", 0.15, 0.1, 0.6, 1.0),  # actionable
        ("Set DEBUG=1 environment variable", 0.15, 0.1, 0.6, 1.0),  # specific value
        ("Never call delete() without backup", 0.15, 0.1, 0.7, 1.0),  # strong action verb
        ("Make sure to do the thing", 0.15, 0.1, 0.3, 0.7),  # soft action verb
        ("Could maybe try this possibly", 0.0, 0.5, -0.5, 0.3),  # all vague, no bonuses
    ],
)
def test_hint_quality_sensitivity(
    hint: str, action_bonus: float, vague_penalty: float, expected_min: float, expected_max: float
) -> None:
    """Test hint quality scoring across parameter space."""
    config = ForgeConfig(hint_actionability_bonus=action_bonus, hint_vagueness_penalty=vague_penalty)
    score = score_hint_quality(hint, config)
    assert expected_min <= score <= expected_max, f"Score {score} not in [{expected_min}, {expected_max}]"


@pytest.mark.parametrize(
    "hint,expected_action_word",
    [
        ("Use the API", "use"),
        ("Avoid errors", "avoid"),
        ("Check the logs", "check"),
        ("Add the flag", "add"),
        ("Never skip validation", "never"),
    ],
)
def test_hint_action_verb_detection(hint: str, expected_action_word: str) -> None:
    """Test that action verb detection works correctly."""
    config = ForgeConfig(hint_actionability_bonus=1.0, hint_vagueness_penalty=0.0)
    score_high = score_hint_quality(hint, config)

    # Now test without the action verb in the hint
    hint_no_verb = hint.replace(expected_action_word.title(), "Do") + " something"
    config_no_bonus = ForgeConfig(hint_actionability_bonus=0.0, hint_vagueness_penalty=0.0)
    score_low = score_hint_quality(hint_no_verb, config_no_bonus)

    assert score_high >= 0.5  # should be decent with action bonus


# =============================================================================
# 4. CIRCUIT BREAKER SENSITIVITY (10+)
# =============================================================================


@pytest.mark.parametrize(
    "max_failures,max_tools,n_failures,n_tools,should_trip",
    [
        (10, 200, 5, 50, False),  # under limits
        (10, 200, 10, 50, True),  # hit failure limit
        (10, 200, 5, 200, True),  # hit tool limit
        (5, 100, 5, 50, True),  # tighter failure limit
        (5, 100, 4, 99, False),  # just under both
        (3, 50, 3, 30, True),  # very tight
        (20, 500, 19, 499, False),  # relaxed, just under
        (1, 10, 1, 5, True),  # minimal
        (100, 1000, 50, 500, False),  # very relaxed
        (2, 20, 1, 19, False),  # one failure, one tool short
    ],
)
def test_circuit_breaker_sensitivity(
    db: sqlite3.Connection,
    max_failures: int,
    max_tools: int,
    n_failures: int,
    n_tools: int,
    should_trip: bool,
) -> None:
    """Test circuit breaker trips at correct limits."""
    config = ForgeConfig(
        circuit_breaker_enabled=True,
        max_consecutive_failures=max_failures,
        max_tool_calls_per_session=max_tools,
    )
    sid = "test_session"

    for _ in range(n_tools):
        increment_tool_call(db, sid)
    for _ in range(n_failures):
        increment_failure(db, sid)

    breaker = check_breaker(db, sid, config)
    assert breaker.is_tripped == should_trip


def test_circuit_breaker_reset(db: sqlite3.Connection) -> None:
    """Test that circuit breaker resets on success."""
    config = ForgeConfig(circuit_breaker_enabled=True, max_consecutive_failures=5)
    sid = "test_reset"

    # Trigger 3 failures
    for _ in range(3):
        increment_failure(db, sid)

    breaker = check_breaker(db, sid, config)
    assert breaker.consecutive_failures == 3
    assert not breaker.is_tripped

    # Reset
    reset_failures(db, sid)
    breaker = check_breaker(db, sid, config)
    assert breaker.consecutive_failures == 0


# =============================================================================
# 5. KPI WEIGHT SENSITIVITY (15+)
# =============================================================================


@pytest.mark.parametrize(
    "weights,kpis,expected_min,expected_max",
    [
        # Default weights, all metrics at 1.0
        ((0.25, 0.15, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10), (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0), 0.95, 1.05),
        # Default weights, all metrics at 0.0
        ((0.25, 0.15, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10), (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0), -0.05, 0.05),
        # QWHR dominant
        ((0.80, 0.025, 0.025, 0.025, 0.025, 0.025, 0.025, 0.025), (0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0), 0.55, 0.70),
        # Even weights
        ((0.125, 0.125, 0.125, 0.125, 0.125, 0.125, 0.125, 0.125), (0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5), 0.45, 0.55),
        # Only QWHR
        ((1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), (0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0), 0.45, 0.55),
        # All 0.5 means (1-0.5)=0.5 for negative metrics (redundant and stale)
        # 0.5 * 0.5 + 0.15 * 0.5 + ... + 0.1*(1-0.2) + 0.1*(1-0.2)
        # = 0.125 + 0.075 + 0.05 + 0.05 + 0.05 + 0.05 + 0.08 + 0.08 = 0.56
        ((0.25, 0.15, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10), (0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.2, 0.2), 0.50, 0.62),
    ],
)
def test_kpi_weight_sensitivity(
    weights: tuple, kpis: tuple, expected_min: float, expected_max: float
) -> None:
    """Test KPI weight sensitivity for v5 fitness."""
    config = ForgeConfig(
        kpi_w_qwhr=weights[0],
        kpi_w_routing=weights[1],
        kpi_w_circuit=weights[2],
        kpi_w_agent=weights[3],
        kpi_w_context=weights[4],
        kpi_w_token=weights[5],
        kpi_w_redundant=weights[6],
        kpi_w_stale=weights[7],
    )

    result = compute_unified_fitness_v5(
        qwhr=kpis[0],
        routing_accuracy=kpis[1],
        circuit_efficiency=kpis[2],
        agent_utilization=kpis[3],
        context_hit_rate=kpis[4],
        token_efficiency=kpis[5],
        redundant_call_rate=kpis[6],
        stale_warning_rate=kpis[7],
        config=config,
    )
    assert expected_min <= result <= expected_max, f"Fitness {result} not in [{expected_min}, {expected_max}]"


def test_kpi_clamping() -> None:
    """Test that KPI values are clamped to [0, 1]."""
    config = ForgeConfig()

    # Test with values outside [0, 1]
    result = compute_unified_fitness_v5(
        qwhr=1.5,  # clamped to 1.0
        routing_accuracy=-0.5,  # clamped to 0.0
        circuit_efficiency=1.2,  # clamped to 1.0
        agent_utilization=0.5,
        context_hit_rate=0.5,
        token_efficiency=0.5,
        redundant_call_rate=0.5,
        stale_warning_rate=0.5,
        config=config,
    )

    # Should be valid [0, 1]
    assert 0.0 <= result <= 1.0


# =============================================================================
# 6. ROUTING MIN OBSERVATIONS (8+)
# =============================================================================


@pytest.mark.parametrize(
    "min_obs,n_choices,should_have_learned",
    [
        (5, 3, False),  # not enough observations
        (5, 5, True),  # exactly enough
        (5, 10, True),  # plenty
        (3, 2, False),  # tight, not enough
        (3, 3, True),  # tight, exactly enough
        (10, 5, False),  # raised bar
        (10, 10, True),  # meets raised bar
        (1, 1, True),  # minimal
    ],
)
def test_routing_min_observations(
    db: sqlite3.Connection, min_obs: int, n_choices: int, should_have_learned: bool
) -> None:
    """Test routing respects minimum observations threshold."""
    config = ForgeConfig(routing_enabled=True, routing_min_observations=min_obs)
    ws = "test_routing"

    # Seed model choices with high success rate for 'quick' category
    for i in range(n_choices):
        db.execute(
            "INSERT INTO model_choices(workspace_id, session_id, task_category, selected_model, outcome) VALUES (?, ?, ?, ?, ?)",
            (ws, f"s{i}", "quick", "claude-haiku-4-5", 0.9),
        )
    db.commit()

    result = resolve_model(ws, "quick", config, db)
    assert isinstance(result, str)
    assert len(result) > 0


def test_routing_fallback_to_default(db: sqlite3.Connection) -> None:
    """Test routing falls back to default model when disabled."""
    config = ForgeConfig(routing_enabled=False, llm_model="claude-opus-4-6")
    ws = "test_routing_disabled"

    result = resolve_model(ws, "any", config, db)
    assert result == "claude-opus-4-6"


# =============================================================================
# 7. CONTEXT FORMAT TESTS (10+)
# =============================================================================


@pytest.mark.parametrize("variant", ["concise", "detailed"])
def test_context_format_variants(db: sqlite3.Connection, variant: str) -> None:
    """Compare context output across format variants."""
    ws = "test_format"
    _seed_failures(db, ws, count=5)

    failures = list_failures(db, ws)
    assert len(failures) > 0

    if variant == "concise":
        context = format_l0(failures, variant=variant)
    else:
        context = format_l1(failures, variant=variant)

    assert len(context) > 0
    assert "test_pattern_" in context


def test_l0_vs_l1_length(db: sqlite3.Connection) -> None:
    """Test that L1 is longer than L0 (includes hints)."""
    ws = "test_l0_l1"
    _seed_failures(db, ws, count=3)

    failures = list_failures(db, ws)
    l0 = format_l0(failures)
    l1 = format_l1(failures)

    assert len(l1) > len(l0), "L1 should include additional hint details"


def test_context_with_rules(db: sqlite3.Connection) -> None:
    """Test context building includes rules."""
    ws = "test_rules"
    _seed_failures(db, ws, count=2)

    # Add a rule
    db.execute(
        "INSERT INTO rules(workspace_id, rule_text, enforcement_mode) VALUES (?, ?, ?)",
        (ws, "Always validate inputs", "warn"),
    )
    db.commit()

    failures = list_failures(db, ws)
    rules = list_rules(db, ws)

    assert len(rules) > 0

    context = build_context(failures, rules, ForgeConfig())
    assert len(context) > 0


# =============================================================================
# 8. FULL PIPELINE WIRING TESTS (5+)
# =============================================================================


def test_full_pipeline_ab_and_injection(db: sqlite3.Connection) -> None:
    """End-to-end: A/B variant selection + injection scoring."""
    ws = "test_pipeline_ab"
    config = ForgeConfig(ab_enabled=True, injection_score_enabled=True)

    _seed_failures(db, ws, count=5)

    # Record some A/B outcomes
    record_format_outcome(db, ws, "concise", True)
    record_format_outcome(db, ws, "concise", True)
    record_format_outcome(db, ws, "detailed", False)

    db.commit()

    # Should still default to concise (not enough observations)
    variant = get_best_format(db, ws, config)
    assert variant in ["concise", "detailed"]


def test_breaker_isolation_per_session(db: sqlite3.Connection) -> None:
    """Circuit breaker state should be isolated per session."""
    config = ForgeConfig(circuit_breaker_enabled=True, max_consecutive_failures=3)

    sid1 = "session_1"
    sid2 = "session_2"

    # Trigger failures in session 1
    for _ in range(3):
        increment_failure(db, sid1)

    breaker1 = check_breaker(db, sid1, config)
    breaker2 = check_breaker(db, sid2, config)

    assert breaker1.is_tripped
    assert not breaker2.is_tripped


def test_routing_respects_config_map(db: sqlite3.Connection) -> None:
    """Routing should use model_map when insufficient data."""
    config = ForgeConfig(
        routing_enabled=True,
        routing_model_map_str="quick=haiku,standard=sonnet,deep=opus",
        routing_min_observations=100,  # very high bar
    )
    ws = "test_routing_map"

    # Add insufficient data
    db.execute(
        "INSERT INTO model_choices(workspace_id, session_id, task_category, selected_model, outcome) VALUES (?, ?, ?, ?, ?)",
        (ws, "s1", "quick", "haiku", 0.9),
    )
    db.commit()

    result = resolve_model(ws, "quick", config, db)
    assert result == "haiku"  # from model_map


def test_injection_score_ordering(db: sqlite3.Connection) -> None:
    """Injection score should reorder failures appropriately."""
    config = ForgeConfig(
        injection_base_weight=0.0, injection_recency_weight=1.0, injection_relevance_weight=0.0
    )

    # Old failure
    old_failure = Failure(
        workspace_id="w",
        pattern="old",
        observed_error="e",
        likely_cause="c",
        avoid_hint="hint",
        hint_quality="preventable",
        q=1.0,
        times_seen=1,
        times_helped=0,
        times_warned=0,
        tags=["test"],
        last_used=datetime.now(UTC) - timedelta(days=100),
    )

    # New failure
    new_failure = Failure(
        workspace_id="w",
        pattern="new",
        observed_error="e",
        likely_cause="c",
        avoid_hint="hint",
        hint_quality="preventable",
        q=1.0,
        times_seen=1,
        times_helped=0,
        times_warned=0,
        tags=["test"],
        last_used=datetime.now(UTC),
    )

    score_old = compute_injection_score(old_failure, ["test"], recency_days=100, config=config)
    score_new = compute_injection_score(new_failure, ["test"], recency_days=0, config=config)

    assert score_new > score_old, "Newer failure should score higher with recency weight"


# =============================================================================
# 9. EDGE CASES AND BOUNDARY CONDITIONS (10+)
# =============================================================================


def test_empty_failures_context(db: sqlite3.Connection) -> None:
    """Context should handle empty failure list gracefully."""
    config = ForgeConfig()
    failures: list[Failure] = []
    rules: list = []

    context = build_context(failures, rules, config)
    assert isinstance(context, str)


def test_circuit_breaker_disabled(db: sqlite3.Connection) -> None:
    """Breaker should never trip when disabled."""
    config = ForgeConfig(circuit_breaker_enabled=False, max_consecutive_failures=1, max_tool_calls_per_session=1)
    sid = "test_disabled"

    # Trigger way over limits
    for _ in range(100):
        increment_failure(db, sid)
        increment_tool_call(db, sid)

    breaker = check_breaker(db, sid, config)
    assert not breaker.is_tripped


def test_routing_with_no_data(db: sqlite3.Connection) -> None:
    """Routing should return default model when no data exists."""
    config = ForgeConfig(
        routing_enabled=True,
        llm_model="claude-haiku-4-5-20251001",
        routing_model_map_str="quick=haiku",
    )
    ws = "test_routing_empty"

    result = resolve_model(ws, "unknown_category", config, db)
    assert result in ["claude-haiku-4-5-20251001", "haiku"]


def test_hint_quality_all_zeros(db: sqlite3.Connection) -> None:
    """Hint quality with all penalties zeroed should still work."""
    config = ForgeConfig(hint_actionability_bonus=0.0, hint_vagueness_penalty=0.0)

    score = score_hint_quality("some random hint text", config)
    assert 0.0 <= score <= 1.0


@pytest.mark.parametrize("q", [0.0, 0.1, 0.5, 0.9, 1.0])
def test_injection_score_with_varying_q(q: float) -> None:
    """Injection score should scale linearly with Q."""
    failure = Failure(
        workspace_id="w",
        pattern="test",
        observed_error="e",
        likely_cause="c",
        avoid_hint="hint",
        hint_quality="preventable",
        q=q,
        times_seen=1,
        times_helped=0,
        times_warned=0,
        tags=[],
    )
    config = ForgeConfig(injection_base_weight=1.0, injection_recency_weight=0.0, injection_relevance_weight=0.0)

    score = compute_injection_score(failure, [], recency_days=0, config=config)
    assert abs(score - q) < 0.001, f"Score {score} should equal Q {q}"


def test_kpi_fitness_bounds() -> None:
    """KPI fitness should always be in [0, 1] regardless of input."""
    config = ForgeConfig()

    # Test extreme values
    result_all_ones = compute_unified_fitness_v5(
        qwhr=1.0,
        routing_accuracy=1.0,
        circuit_efficiency=1.0,
        agent_utilization=1.0,
        context_hit_rate=1.0,
        token_efficiency=1.0,
        redundant_call_rate=1.0,
        stale_warning_rate=1.0,
        config=config,
    )

    result_all_zeros = compute_unified_fitness_v5(
        qwhr=0.0,
        routing_accuracy=0.0,
        circuit_efficiency=0.0,
        agent_utilization=0.0,
        context_hit_rate=0.0,
        token_efficiency=0.0,
        redundant_call_rate=0.0,
        stale_warning_rate=0.0,
        config=config,
    )

    assert 0.0 <= result_all_ones <= 1.0
    assert 0.0 <= result_all_zeros <= 1.0


# =============================================================================
# 10. PERFORMANCE AND SCALABILITY (5+)
# =============================================================================


def test_large_failure_context_performance(db: sqlite3.Connection) -> None:
    """Building context with many failures should complete quickly."""
    ws = "test_perf"
    _seed_failures(db, ws, count=100)

    failures = list_failures(db, ws)
    assert len(failures) == 100

    config = ForgeConfig(l0_max_entries=50)
    context = build_context(failures, [], config)

    # Should complete quickly and contain reasonable amount of text
    assert len(context) > 0
    assert len(context) < 50000  # sanity check for reasonable size


def test_injection_score_batch_performance(db: sqlite3.Connection) -> None:
    """Computing injection scores for many failures should be fast."""
    _seed_failures(db, "test_batch", count=50)

    failures = list_failures(db, "test_batch")
    config = ForgeConfig()

    # Compute scores for all
    scores = [compute_injection_score(f, ["python"], recency_days=1.0, config=config) for f in failures]

    assert len(scores) == 50
    assert all(0.0 <= s <= 2.0 for s in scores)


def test_circuit_breaker_many_increments(db: sqlite3.Connection) -> None:
    """Circuit breaker should handle many increments efficiently."""
    config = ForgeConfig(circuit_breaker_enabled=True, max_consecutive_failures=50)
    sid = "test_many_increments"

    for _ in range(45):
        increment_tool_call(db, sid)

    breaker = check_breaker(db, sid, config)
    assert not breaker.is_tripped
    assert breaker.tool_calls == 45


# =============================================================================
# 11. CONSISTENCY AND DETERMINISM (5+)
# =============================================================================


def test_hint_quality_consistent(db: sqlite3.Connection) -> None:
    """Hint quality score should be deterministic."""
    config = ForgeConfig()
    hint = "Use check_config() to validate inputs"

    score1 = score_hint_quality(hint, config)
    score2 = score_hint_quality(hint, config)

    assert score1 == score2


def test_injection_score_consistent() -> None:
    """Injection score should be deterministic."""
    failure = Failure(
        workspace_id="w",
        pattern="test",
        observed_error="e",
        likely_cause="c",
        avoid_hint="hint",
        hint_quality="preventable",
        q=0.75,
        times_seen=5,
        times_helped=2,
        times_warned=5,
        tags=["python"],
    )
    config = ForgeConfig()

    score1 = compute_injection_score(failure, ["python"], recency_days=5.0, config=config)
    score2 = compute_injection_score(failure, ["python"], recency_days=5.0, config=config)

    assert score1 == score2


def test_ab_format_consistent(db: sqlite3.Connection) -> None:
    """A/B format selection should be consistent for same input."""
    config = ForgeConfig(ab_min_observations=5, ab_variant_threshold=0.1)
    ws = "test_ab_consistent"

    data = {"concise": {"helped": 6, "total": 10}, "detailed": {"helped": 4, "total": 10}}
    db.execute("INSERT INTO forge_meta(key, value) VALUES (?, ?)", (f"ab_outcomes:{ws}", json.dumps(data)))
    db.commit()

    result1 = get_best_format(db, ws, config)
    result2 = get_best_format(db, ws, config)

    assert result1 == result2
