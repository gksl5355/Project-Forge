"""Tests for AutoResearch v2 engine (research_v5)."""
from __future__ import annotations

import json

import pytest

from forge.config import ForgeConfig
from forge.engines.research_v5 import (
    PromptResearchResult,
    ResearchResult,
    _optimize_breaker,
    _optimize_context_budget,
    _optimize_routing,
    run_prompt_research,
    run_research_v5,
)


# ---------------------------------------------------------------------------
# run_research_v5: empty DB
# ---------------------------------------------------------------------------

def test_run_research_v5_empty_db(db):
    result = run_research_v5("ws1", db)

    assert isinstance(result, ResearchResult)
    assert result.unified_fitness_before == 0.0
    # No data → no improvements → after == before
    assert result.unified_fitness_after == 0.0
    assert result.improvements == []
    assert isinstance(result.improvements, list)
    assert isinstance(result.best_config, dict)
    assert isinstance(result.sweep_log, list)
    assert len(result.sweep_log) == 3  # routing, breaker, context steps


def test_run_research_v5_with_sessions(db):
    """With sessions having unified_fitness, baseline should be non-zero."""
    for i in range(3):
        db.execute(
            """INSERT INTO sessions
               (session_id, workspace_id, warnings_injected, unified_fitness)
               VALUES (?, ?, ?, ?)""",
            (f"s{i}", "ws1", "[]", 0.6 + i * 0.1),
        )
    db.commit()

    result = run_research_v5("ws1", db)

    assert result.unified_fitness_before == pytest.approx(0.7, abs=1e-6)
    assert result.unified_fitness_after >= result.unified_fitness_before


def test_run_research_v5_with_custom_config(db):
    """Custom config is used; no session data → fitness_before = 0."""
    config = ForgeConfig(max_consecutive_failures=5, l0_max_entries=20)
    result = run_research_v5("ws_custom", db, config=config)

    assert isinstance(result, ResearchResult)
    assert result.unified_fitness_before == 0.0


# ---------------------------------------------------------------------------
# _optimize_routing
# ---------------------------------------------------------------------------

def test_optimize_routing_empty(db):
    config = ForgeConfig()
    improvements = _optimize_routing(db, "ws1", config)
    assert improvements == []


def test_optimize_routing_suggests_better_model(db):
    """If sonnet outperforms haiku for 'quick' with >= 5 samples, suggest switch."""
    ws = "ws_routing"
    config = ForgeConfig(
        routing_model_map_str="quick=claude-haiku-4-5,standard=claude-sonnet-4-6"
    )

    # 5 samples of haiku with outcome 0.5
    for i in range(5):
        db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, task_category, selected_model, outcome)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, f"sess_haiku_{i}", "quick", "claude-haiku-4-5", 0.5),
        )
    # 5 samples of sonnet with outcome 0.9
    for i in range(5):
        db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, task_category, selected_model, outcome)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, f"sess_sonnet_{i}", "quick", "claude-sonnet-4-6", 0.9),
        )
    db.commit()

    improvements = _optimize_routing(db, ws, config)

    params = [imp["parameter"] for imp in improvements]
    assert "routing:quick" in params
    assert "routing_model_map_str" in params

    route_imp = next(i for i in improvements if i["parameter"] == "routing:quick")
    assert route_imp["old"] == "claude-haiku-4-5"
    assert route_imp["new"] == "claude-sonnet-4-6"
    assert route_imp["expected_gain"] > 0


def test_optimize_routing_no_switch_without_enough_samples(db):
    """With < 5 samples, no suggestion should be made."""
    ws = "ws_routing2"
    config = ForgeConfig(
        routing_model_map_str="quick=claude-haiku-4-5"
    )

    # Only 3 samples of sonnet (below threshold of 5)
    for i in range(3):
        db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, task_category, selected_model, outcome)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, f"sess_{i}", "quick", "claude-sonnet-4-6", 0.95),
        )
    db.commit()

    improvements = _optimize_routing(db, ws, config)
    assert improvements == []


def test_optimize_routing_no_switch_when_current_is_best(db):
    """No suggestion when current model is already best."""
    ws = "ws_routing3"
    config = ForgeConfig(
        routing_model_map_str="quick=claude-sonnet-4-6"
    )

    # 5 samples: sonnet 0.9, haiku 0.6
    for i in range(5):
        db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, task_category, selected_model, outcome)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, f"ss_{i}", "quick", "claude-sonnet-4-6", 0.9),
        )
    for i in range(5):
        db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, task_category, selected_model, outcome)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, f"sh_{i}", "quick", "claude-haiku-4-5", 0.6),
        )
    db.commit()

    improvements = _optimize_routing(db, ws, config)
    assert improvements == []


# ---------------------------------------------------------------------------
# _optimize_breaker
# ---------------------------------------------------------------------------

def _insert_breaker_states(db, prefix: str, count: int, tripped_count: int) -> None:
    """Helper: insert `count` breaker states, first `tripped_count` are tripped."""
    for i in range(count):
        tripped = i < tripped_count
        state = {
            "consecutive_failures": 15 if tripped else 2,
            "tool_calls": 50,
            "tripped": tripped,
        }
        db.execute(
            "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
            (f"breaker:{prefix}_sess_{i}", json.dumps(state)),
        )
    db.commit()


def test_optimize_breaker_high_break_rate(db):
    """break_rate > 20% → suggest increasing max_consecutive_failures."""
    # 10 sessions, 4 tripped (40%)
    _insert_breaker_states(db, "high", count=10, tripped_count=4)

    config = ForgeConfig(max_consecutive_failures=10)
    improvements = _optimize_breaker(db, "ws_breaker", config)

    params = {imp["parameter"]: imp for imp in improvements}
    assert "max_consecutive_failures" in params
    assert params["max_consecutive_failures"]["new"] > config.max_consecutive_failures
    assert params["max_consecutive_failures"]["new"] == 13  # min(10+3, 20)


def test_optimize_breaker_low_break_rate_suggests_decrease(db):
    """break_rate < 1% and max_consecutive_failures > 3 → suggest decreasing."""
    # 20 sessions, 0 tripped (0%)
    _insert_breaker_states(db, "low", count=20, tripped_count=0)

    config = ForgeConfig(max_consecutive_failures=10)
    improvements = _optimize_breaker(db, "ws_breaker_low", config)

    params = {imp["parameter"]: imp for imp in improvements}
    assert "max_consecutive_failures" in params
    assert params["max_consecutive_failures"]["new"] < config.max_consecutive_failures
    assert params["max_consecutive_failures"]["new"] == 8  # max(10-2, 3)


def test_optimize_breaker_low_break_rate_no_decrease_when_at_min(db):
    """max_consecutive_failures <= 3 → no decrease suggestion."""
    _insert_breaker_states(db, "low2", count=20, tripped_count=0)

    config = ForgeConfig(max_consecutive_failures=3)
    improvements = _optimize_breaker(db, "ws_breaker_min", config)

    params = [imp["parameter"] for imp in improvements]
    assert "max_consecutive_failures" not in params


def test_optimize_breaker_high_tool_calls_suggests_increase(db):
    """avg_tool_calls > 80% of max → suggest increasing max_tool_calls_per_session."""
    # Insert sessions with high tool call counts
    for i in range(5):
        state = {"consecutive_failures": 0, "tool_calls": 175, "tripped": False}
        db.execute(
            "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
            (f"breaker:tool_high_{i}", json.dumps(state)),
        )
    db.commit()

    config = ForgeConfig(max_tool_calls_per_session=200)
    improvements = _optimize_breaker(db, "ws_tool", config)

    params = {imp["parameter"]: imp for imp in improvements}
    assert "max_tool_calls_per_session" in params
    assert params["max_tool_calls_per_session"]["new"] > 200


def test_optimize_breaker_empty_db(db):
    """No breaker states → no suggestions."""
    config = ForgeConfig()
    improvements = _optimize_breaker(db, "ws_empty", config)
    assert improvements == []


# ---------------------------------------------------------------------------
# _optimize_context_budget
# ---------------------------------------------------------------------------

def test_optimize_context_budget_low_hit_rate(db):
    """Sessions with warnings but no q_updates → low hit rate → reduce l0_max_entries."""
    ws = "ws_ctx"
    for i in range(5):
        db.execute(
            """INSERT INTO sessions
               (session_id, workspace_id, warnings_injected, q_updates_count)
               VALUES (?, ?, ?, ?)""",
            (f"ctx_sess_{i}", ws, '["pattern_a"]', 0),
        )
    db.commit()

    config = ForgeConfig(l0_max_entries=50)
    improvements = _optimize_context_budget(db, ws, config)

    params = {imp["parameter"]: imp for imp in improvements}
    assert "l0_max_entries" in params
    assert params["l0_max_entries"]["new"] < 50
    assert params["l0_max_entries"]["new"] == 25  # max(50//2, 5)


def test_optimize_context_budget_high_stale_rate(db):
    """Failures with low help rate → stale_warning_rate > 0.5 → reduce l0 and l1."""
    ws = "ws_stale"
    for i in range(6):
        db.execute(
            """INSERT INTO failures
               (workspace_id, pattern, avoid_hint, hint_quality, q,
                times_warned, times_helped)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ws, f"pat_{i}", "hint", "near_miss", 0.5, 10, 1),  # 0.1 help rate
        )
    db.commit()

    config = ForgeConfig(l0_max_entries=50, l1_project_entries=3)
    improvements = _optimize_context_budget(db, ws, config)

    params = {imp["parameter"]: imp for imp in improvements}
    assert "l0_max_entries" in params
    assert "l1_project_entries" in params
    assert params["l1_project_entries"]["new"] == 2  # max(3-1, 1)


def test_optimize_context_budget_context_overhead(db):
    """forge + team tokens > total by > 5% → suggest reducing forge_context_tokens."""
    config = ForgeConfig(
        forge_context_tokens=3000,
        team_context_tokens=1000,
        total_max_tokens=3500,
    )
    # context_overhead = 3000 + 1000 - 3500 = 500
    # 500 > 3500 * 0.05 = 175 → trigger

    improvements = _optimize_context_budget(db, "ws_overhead", config)

    params = {imp["parameter"]: imp for imp in improvements}
    assert "forge_context_tokens" in params
    assert params["forge_context_tokens"]["new"] < 3000
    assert params["forge_context_tokens"]["new"] == 2700  # max(int(3000*0.9), 500)


def test_optimize_context_budget_no_overhead_default(db):
    """Default config has no overhead → no forge_context_tokens suggestion."""
    config = ForgeConfig()  # forge=2500, team=1000, total=4000 → no overflow
    improvements = _optimize_context_budget(db, "ws_default", config)

    params = [imp["parameter"] for imp in improvements]
    assert "forge_context_tokens" not in params


def test_optimize_context_budget_good_hit_rate_no_suggestions(db):
    """High context hit rate → no l0_max_entries suggestion."""
    ws = "ws_good"
    for i in range(5):
        db.execute(
            """INSERT INTO sessions
               (session_id, workspace_id, warnings_injected, q_updates_count)
               VALUES (?, ?, ?, ?)""",
            (f"good_sess_{i}", ws, '["pat"]', 2),  # all sessions have q_updates
        )
    db.commit()

    config = ForgeConfig(l0_max_entries=50)
    improvements = _optimize_context_budget(db, ws, config)

    params = [imp["parameter"] for imp in improvements]
    assert "l0_max_entries" not in params


# ---------------------------------------------------------------------------
# run_prompt_research
# ---------------------------------------------------------------------------

def test_run_prompt_research_empty_db(db):
    result = run_prompt_research("ws_empty", db)

    assert isinstance(result, PromptResearchResult)
    assert result.best_format == "concise"
    assert "concise" in result.format_stats
    assert "detailed" in result.format_stats
    assert result.low_quality_hints_count == 0
    assert result.hint_quality_distribution == {"good": 0, "medium": 0, "poor": 0}


def test_run_prompt_research_with_ab_data(db):
    """Detailed format outperforms concise → best_format = detailed."""
    ws = "ws_ab"
    ab_stats = {
        "concise": {"helped": 10, "total": 20},
        "detailed": {"helped": 15, "total": 20},
    }
    db.execute(
        "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
        (f"ab_stats:{ws}", json.dumps(ab_stats)),
    )
    db.commit()

    result = run_prompt_research(ws, db)

    assert result.best_format == "detailed"
    assert result.format_stats["detailed"]["rate"] == pytest.approx(0.75)
    assert result.format_stats["concise"]["rate"] == pytest.approx(0.5)


def test_run_prompt_research_hint_quality_distribution(db):
    """Hints classified into good/medium/poor based on q value."""
    ws = "ws_hints"
    hint_data = [
        ("pat_good1", 0.8, "near_miss"),
        ("pat_good2", 0.7, "near_miss"),
        ("pat_med1", 0.5, "preventable"),
        ("pat_med2", 0.4, "environmental"),
        ("pat_poor1", 0.2, "near_miss"),
        ("pat_poor2", 0.1, "preventable"),
        ("pat_poor3", 0.0, "environmental"),
    ]
    for pattern, q, quality in hint_data:
        db.execute(
            """INSERT INTO failures
               (workspace_id, pattern, avoid_hint, hint_quality, q)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, pattern, "hint", quality, q),
        )
    db.commit()

    result = run_prompt_research(ws, db)

    assert result.hint_quality_distribution["good"] == 2
    assert result.hint_quality_distribution["medium"] == 2
    assert result.hint_quality_distribution["poor"] == 3
    assert result.low_quality_hints_count == 3


def test_run_prompt_research_ab_concise_wins(db):
    """When concise has higher rate, best_format = concise."""
    ws = "ws_concise"
    ab_stats = {
        "concise": {"helped": 18, "total": 20},
        "detailed": {"helped": 8, "total": 20},
    }
    db.execute(
        "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
        (f"ab_stats:{ws}", json.dumps(ab_stats)),
    )
    db.commit()

    result = run_prompt_research(ws, db)
    assert result.best_format == "concise"


def test_run_prompt_research_zero_total_in_ab_stats(db):
    """Zero total in A/B stats → rate = 0.0, no division error."""
    ws = "ws_zero"
    ab_stats = {
        "concise": {"helped": 0, "total": 0},
        "detailed": {"helped": 0, "total": 0},
    }
    db.execute(
        "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
        (f"ab_stats:{ws}", json.dumps(ab_stats)),
    )
    db.commit()

    result = run_prompt_research(ws, db)
    assert result.format_stats["concise"]["rate"] == 0.0
    assert result.format_stats["detailed"]["rate"] == 0.0


# ---------------------------------------------------------------------------
# ResearchResult structure
# ---------------------------------------------------------------------------

def test_research_result_best_config_excludes_routing_details(db):
    """best_config should not include 'routing:category' keys."""
    ws = "ws_struct"
    config = ForgeConfig(
        routing_model_map_str="quick=claude-haiku-4-5"
    )
    for i in range(5):
        db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, task_category, selected_model, outcome)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, f"s{i}", "quick", "claude-sonnet-4-6", 0.95),
        )
    for i in range(5):
        db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, task_category, selected_model, outcome)
               VALUES (?, ?, ?, ?, ?)""",
            (ws, f"h{i}", "quick", "claude-haiku-4-5", 0.3),
        )
    db.commit()

    result = run_research_v5(ws, db, config=config)

    for key in result.best_config:
        assert not key.startswith("routing:"), f"unexpected key: {key}"


def test_research_result_after_fitness_gte_before(db):
    """after fitness should always be >= before (improvements only add gain)."""
    db.execute(
        """INSERT INTO sessions
           (session_id, workspace_id, warnings_injected, unified_fitness)
           VALUES (?, ?, ?, ?)""",
        ("s1", "ws_fit", "[]", 0.5),
    )
    db.commit()

    result = run_research_v5("ws_fit", db)
    assert result.unified_fitness_after >= result.unified_fitness_before


def test_research_result_after_fitness_capped_at_one(db):
    """after fitness must not exceed 1.0."""
    db.execute(
        """INSERT INTO sessions
           (session_id, workspace_id, warnings_injected, unified_fitness)
           VALUES (?, ?, ?, ?)""",
        ("s1", "ws_cap", "[]", 0.99),
    )
    # High break rate to generate large expected_gain
    _insert_breaker_states(db, "cap", count=10, tripped_count=5)
    db.commit()

    result = run_research_v5("ws_cap", db)
    assert result.unified_fitness_after <= 1.0
