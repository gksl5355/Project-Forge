"""Unit tests for forge/engines/metrics_v5.py and compute_unified_fitness_v5."""

from __future__ import annotations

import json
import pytest

from forge.engines.metrics_v5 import (
    compute_agent_utilization,
    compute_circuit_efficiency,
    compute_context_hit_rate,
    compute_redundant_call_rate,
    compute_routing_accuracy,
    compute_stale_warning_rate,
    compute_tool_efficiency,
)
from forge.engines.fitness import compute_unified_fitness_v5

WS = "test_ws"


# ---------------------------------------------------------------------------
# compute_routing_accuracy
# ---------------------------------------------------------------------------

class TestRoutingAccuracy:
    def test_empty_db(self, db):
        assert compute_routing_accuracy(db, WS) == 0.0

    def test_all_outcome_none(self, db):
        db.execute(
            "INSERT INTO model_choices (workspace_id, session_id, task_category, selected_model, outcome)"
            " VALUES (?, 's1', 'quick', 'haiku', NULL)",
            (WS,),
        )
        db.commit()
        assert compute_routing_accuracy(db, WS) == 0.0

    def test_single_category_best_always_chosen(self, db):
        # haiku always wins in 'quick', and it's always chosen
        for i, (model, outcome) in enumerate([("haiku", 0.9), ("haiku", 0.8), ("sonnet", 0.4)]):
            db.execute(
                "INSERT INTO model_choices (workspace_id, session_id, task_category, selected_model, outcome)"
                " VALUES (?, ?, 'quick', ?, ?)",
                (WS, f"s{i}", model, outcome),
            )
        db.commit()
        # best model = haiku (avg 0.85). Chosen 2 out of 3.
        result = compute_routing_accuracy(db, WS)
        assert abs(result - 2 / 3) < 1e-9

    def test_multiple_categories(self, db):
        rows = [
            ("cat_a", "m1", 0.9),
            ("cat_a", "m1", 0.8),
            ("cat_a", "m2", 0.3),
            ("cat_b", "m2", 1.0),
            ("cat_b", "m2", 0.9),
        ]
        for i, (cat, model, outcome) in enumerate(rows):
            db.execute(
                "INSERT INTO model_choices (workspace_id, session_id, task_category, selected_model, outcome)"
                " VALUES (?, ?, ?, ?, ?)",
                (WS, f"s{i}", cat, model, outcome),
            )
        db.commit()
        # cat_a best = m1 (avg 0.85), cat_b best = m2 (avg 0.95)
        # correct: 2 (both m1 in cat_a) + 2 (both m2 in cat_b) = 4/5
        result = compute_routing_accuracy(db, WS)
        assert abs(result - 4 / 5) < 1e-9

    def test_wrong_workspace_ignored(self, db):
        db.execute(
            "INSERT INTO model_choices (workspace_id, session_id, task_category, selected_model, outcome)"
            " VALUES ('other_ws', 's1', 'quick', 'haiku', 0.9)",
        )
        db.commit()
        assert compute_routing_accuracy(db, WS) == 0.0


# ---------------------------------------------------------------------------
# compute_circuit_efficiency
# ---------------------------------------------------------------------------

class TestCircuitEfficiency:
    def test_no_sessions(self, db):
        assert compute_circuit_efficiency(db, WS) == 1.0

    def test_sessions_no_breaks(self, db):
        db.execute(
            "INSERT INTO sessions (session_id, workspace_id) VALUES ('s1', ?)", (WS,)
        )
        db.commit()
        assert compute_circuit_efficiency(db, WS) == 1.0

    def test_one_break_of_two(self, db):
        for sid in ("s1", "s2"):
            db.execute(
                "INSERT INTO sessions (session_id, workspace_id) VALUES (?, ?)",
                (sid, WS),
            )
        # Mark s1 as tripped
        db.execute(
            "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
            ("breaker:s1", json.dumps({"tripped": True, "consecutive_failures": 3, "tool_calls": 10})),
        )
        db.commit()
        result = compute_circuit_efficiency(db, WS)
        assert abs(result - 0.5) < 1e-9

    def test_all_tripped(self, db):
        for sid in ("s1", "s2"):
            db.execute(
                "INSERT INTO sessions (session_id, workspace_id) VALUES (?, ?)",
                (sid, WS),
            )
            db.execute(
                "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
                (f"breaker:{sid}", json.dumps({"tripped": True})),
            )
        db.commit()
        assert compute_circuit_efficiency(db, WS) == 0.0

    def test_malformed_meta_ignored(self, db):
        db.execute(
            "INSERT INTO sessions (session_id, workspace_id) VALUES ('s1', ?)", (WS,)
        )
        db.execute(
            "INSERT INTO forge_meta (key, value) VALUES ('breaker:s1', 'not-json')"
        )
        db.commit()
        assert compute_circuit_efficiency(db, WS) == 1.0


# ---------------------------------------------------------------------------
# compute_agent_utilization
# ---------------------------------------------------------------------------

class TestAgentUtilization:
    def test_empty_db(self, db):
        assert compute_agent_utilization(db, WS) == 0.0

    def test_all_completed(self, db):
        for i in range(3):
            db.execute(
                "INSERT INTO agents (agent_id, workspace_id, session_id, status)"
                " VALUES (?, ?, 's1', 'completed')",
                (f"a{i}", WS),
            )
        db.commit()
        assert compute_agent_utilization(db, WS) == 1.0

    def test_mixed_statuses(self, db):
        statuses = ["completed", "completed", "error", "timed_out"]
        for i, status in enumerate(statuses):
            db.execute(
                "INSERT INTO agents (agent_id, workspace_id, session_id, status)"
                " VALUES (?, ?, 's1', ?)",
                (f"a{i}", WS, status),
            )
        db.commit()
        result = compute_agent_utilization(db, WS)
        assert abs(result - 2 / 4) < 1e-9

    def test_active_agents_excluded(self, db):
        # 'active' status should not count in denominator
        db.execute(
            "INSERT INTO agents (agent_id, workspace_id, session_id, status)"
            " VALUES ('a1', ?, 's1', 'active')",
            (WS,),
        )
        db.commit()
        assert compute_agent_utilization(db, WS) == 0.0

    def test_wrong_workspace_ignored(self, db):
        db.execute(
            "INSERT INTO agents (agent_id, workspace_id, session_id, status)"
            " VALUES ('a1', 'other_ws', 's1', 'completed')"
        )
        db.commit()
        assert compute_agent_utilization(db, WS) == 0.0


# ---------------------------------------------------------------------------
# compute_context_hit_rate
# ---------------------------------------------------------------------------

class TestContextHitRate:
    def test_empty_db(self, db):
        assert compute_context_hit_rate(db, WS) == 0.0

    def test_no_warnings(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
            " times_warned, times_helped) VALUES (?, 'p1', 'h', 'near_miss', 0, 0)",
            (WS,),
        )
        db.commit()
        assert compute_context_hit_rate(db, WS) == 0.0

    def test_half_helped(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
            " times_warned, times_helped) VALUES (?, 'p1', 'h', 'near_miss', 10, 5)",
            (WS,),
        )
        db.commit()
        assert abs(compute_context_hit_rate(db, WS) - 0.5) < 1e-9

    def test_capped_at_1(self, db):
        # helped > warned (data integrity issue) → capped at 1.0
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
            " times_warned, times_helped) VALUES (?, 'p1', 'h', 'near_miss', 5, 10)",
            (WS,),
        )
        db.commit()
        assert compute_context_hit_rate(db, WS) == 1.0

    def test_multiple_failures_aggregated(self, db):
        for i, (warned, helped) in enumerate([(4, 2), (6, 3)]):
            db.execute(
                "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
                " times_warned, times_helped) VALUES (?, ?, 'h', 'near_miss', ?, ?)",
                (WS, f"p{i}", warned, helped),
            )
        db.commit()
        # sum_helped=5, sum_warned=10 → 0.5
        assert abs(compute_context_hit_rate(db, WS) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# compute_tool_efficiency
# ---------------------------------------------------------------------------

class TestToolEfficiency:
    def test_empty_db(self, db):
        assert compute_tool_efficiency(db, WS) == 0.0

    def test_with_failures_returns_0_to_1(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
            " times_helped, times_warned) VALUES (?, 'p1', 'avoid foo', 'near_miss', 5, 3)",
            (WS,),
        )
        db.commit()
        result = compute_tool_efficiency(db, WS)
        assert 0.0 <= result <= 1.0

    def test_zero_helped_returns_0(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
            " times_helped, times_warned) VALUES (?, 'p1', 'avoid foo', 'near_miss', 0, 3)",
            (WS,),
        )
        db.commit()
        result = compute_tool_efficiency(db, WS)
        assert result == 0.0

    def test_high_helped_capped_at_1(self, db):
        # Insert many failures with very high helped count → should cap at 1.0
        for i in range(20):
            db.execute(
                "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
                " times_helped, times_warned) VALUES (?, ?, 'avoid foo', 'near_miss', 1000, 500)",
                (WS, f"p{i}"),
            )
        db.commit()
        result = compute_tool_efficiency(db, WS)
        assert result == 1.0


# ---------------------------------------------------------------------------
# compute_redundant_call_rate
# ---------------------------------------------------------------------------

class TestRedundantCallRate:
    def test_no_sessions(self, db):
        assert compute_redundant_call_rate(db, WS) == 0.0

    def test_sessions_no_breaker_data(self, db):
        db.execute(
            "INSERT INTO sessions (session_id, workspace_id) VALUES ('s1', ?)", (WS,)
        )
        db.commit()
        assert compute_redundant_call_rate(db, WS) == 0.0

    def test_zero_tool_calls(self, db):
        db.execute(
            "INSERT INTO sessions (session_id, workspace_id) VALUES ('s1', ?)", (WS,)
        )
        db.execute(
            "INSERT INTO forge_meta (key, value) VALUES ('breaker:s1', ?)",
            (json.dumps({"consecutive_failures": 3, "tool_calls": 0}),),
        )
        db.commit()
        assert compute_redundant_call_rate(db, WS) == 0.0

    def test_known_ratio(self, db):
        for sid, cf, tc in [("s1", 2, 10), ("s2", 4, 10)]:
            db.execute(
                "INSERT INTO sessions (session_id, workspace_id) VALUES (?, ?)",
                (sid, WS),
            )
            db.execute(
                "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
                (f"breaker:{sid}", json.dumps({"consecutive_failures": cf, "tool_calls": tc})),
            )
        db.commit()
        # total_cf=6, total_tc=20 → 0.3
        result = compute_redundant_call_rate(db, WS)
        assert abs(result - 0.3) < 1e-9

    def test_malformed_meta_skipped(self, db):
        db.execute(
            "INSERT INTO sessions (session_id, workspace_id) VALUES ('s1', ?)", (WS,)
        )
        db.execute(
            "INSERT INTO forge_meta (key, value) VALUES ('breaker:s1', 'bad-json')"
        )
        db.commit()
        assert compute_redundant_call_rate(db, WS) == 0.0


# ---------------------------------------------------------------------------
# compute_stale_warning_rate
# ---------------------------------------------------------------------------

class TestStaleWarningRate:
    def test_empty_db(self, db):
        assert compute_stale_warning_rate(db, WS) == 0.0

    def test_no_warned_failures(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
            " times_warned, times_helped) VALUES (?, 'p1', 'h', 'near_miss', 0, 0)",
            (WS,),
        )
        db.commit()
        assert compute_stale_warning_rate(db, WS) == 0.0

    def test_all_helped(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
            " times_warned, times_helped) VALUES (?, 'p1', 'h', 'near_miss', 5, 5)",
            (WS,),
        )
        db.commit()
        assert compute_stale_warning_rate(db, WS) == 0.0

    def test_half_stale(self, db):
        for i, (warned, helped) in enumerate([(3, 2), (3, 0)]):
            db.execute(
                "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
                " times_warned, times_helped) VALUES (?, ?, 'h', 'near_miss', ?, ?)",
                (WS, f"p{i}", warned, helped),
            )
        db.commit()
        result = compute_stale_warning_rate(db, WS)
        assert abs(result - 0.5) < 1e-9

    def test_all_stale(self, db):
        for i in range(3):
            db.execute(
                "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,"
                " times_warned, times_helped) VALUES (?, ?, 'h', 'near_miss', 2, 0)",
                (WS, f"p{i}"),
            )
        db.commit()
        assert compute_stale_warning_rate(db, WS) == 1.0


# ---------------------------------------------------------------------------
# compute_unified_fitness_v5
# ---------------------------------------------------------------------------

class TestUnifiedFitnessV5:
    def test_all_zeros(self):
        result = compute_unified_fitness_v5(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        # redundant_call_rate=0 → (1-0)=1 term, stale_warning_rate=0 → (1-0)=1 term
        # = 0.06 + 0.06 = 0.12
        assert abs(result - 0.12) < 1e-9

    def test_all_ones(self):
        result = compute_unified_fitness_v5(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        # redundant=1 → (1-1)=0, stale=1 → (1-1)=0
        # = 0.30+0.15+0.08+0.08+0.15+0.12+0+0 = 0.88
        assert abs(result - 0.88) < 1e-9

    def test_all_perfect_with_zero_penalites(self):
        # qwhr=1, routing=1, circuit=1, agent=1, context=1, token=1, redundant=0, stale=0
        result = compute_unified_fitness_v5(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0)
        # all positive KPIs=1, negative KPIs=0 → (1-0)=1 → sum of all weights = 1.0
        assert abs(result - 1.0) < 1e-9

    def test_known_inputs(self):
        result = compute_unified_fitness_v5(
            qwhr=0.8,
            routing_accuracy=0.6,
            circuit_efficiency=1.0,
            agent_utilization=0.7,
            context_hit_rate=0.5,
            token_efficiency=0.4,
            redundant_call_rate=0.2,
            stale_warning_rate=0.3,
        )
        expected = (
            0.30 * 0.8
            + 0.15 * 0.6
            + 0.08 * 1.0
            + 0.08 * 0.7
            + 0.15 * 0.5
            + 0.12 * 0.4
            + 0.06 * (1 - 0.2)
            + 0.06 * (1 - 0.3)
        )
        assert abs(result - expected) < 1e-9

    def test_clamping_above_1(self):
        result = compute_unified_fitness_v5(2.0, 2.0, 2.0, 2.0, 2.0, 2.0, -1.0, -1.0)
        # All clamped: positive→1, negative→clamp(-1)=0 → (1-0)=1 → sum = 1.0
        assert abs(result - 1.0) < 1e-9

    def test_clamping_below_0(self):
        result = compute_unified_fitness_v5(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, 2.0, 2.0)
        # All clamped to 0 except redundant/stale → clamp(2)=1 → (1-1)=0
        assert result == 0.0
