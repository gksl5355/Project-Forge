"""Tests for AutoResearch optimizer."""

import copy
import json
import sqlite3

import pytest

from forge.config import ForgeConfig, save_config_yaml, load_config
from forge.engines.optimizer import (
    ExperimentSimulator,
    PARAM_GRID,
    ParameterSpace,
    _extract_warned_patterns,
    compute_qwhr,
    run_autoresearch,
)
from forge.storage.models import Failure, Session
from forge.storage.queries import insert_failure, insert_session, list_sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_failure(
    db: sqlite3.Connection,
    pattern: str,
    q: float = 0.5,
    times_warned: int = 10,
    times_helped: int = 5,
    workspace: str = "test",
    hint_quality: str = "preventable",
) -> int:
    f = Failure(
        workspace_id=workspace,
        pattern=pattern,
        avoid_hint=f"avoid {pattern}",
        hint_quality=hint_quality,
        q=q,
        times_warned=times_warned,
        times_helped=times_helped,
    )
    return insert_failure(db, f)


def _make_session(
    db: sqlite3.Connection,
    session_id: str,
    workspace: str = "test",
    warnings_injected: list[str] | None = None,
    failures_encountered: int = 0,
) -> int:
    s = Session(
        session_id=session_id,
        workspace_id=workspace,
        warnings_injected=warnings_injected or [],
        failures_encountered=failures_encountered,
    )
    return insert_session(db, s)


# ---------------------------------------------------------------------------
# compute_qwhr
# ---------------------------------------------------------------------------

class TestComputeQWHR:
    def test_empty_patterns(self):
        assert compute_qwhr([], {}, {}) == 0.0

    def test_all_helped(self):
        """All patterns helped → QWHR = 1.0."""
        warned = ["a", "b"]
        q_vals = {"a": 0.8, "b": 0.6}
        rates = {"a": 1.0, "b": 1.0}
        assert compute_qwhr(warned, q_vals, rates) == pytest.approx(1.0)

    def test_none_helped(self):
        """All patterns failed → QWHR = 0.0."""
        warned = ["a", "b"]
        q_vals = {"a": 0.8, "b": 0.6}
        rates = {"a": 0.0, "b": 0.0}
        assert compute_qwhr(warned, q_vals, rates) == pytest.approx(0.0)

    def test_mixed(self):
        """High-Q pattern helped, low-Q not → weighted toward high Q."""
        warned = ["high_q", "low_q"]
        q_vals = {"high_q": 0.9, "low_q": 0.1}
        rates = {"high_q": 1.0, "low_q": 0.0}
        # QWHR = (0.9*1.0 + 0.1*0.0) / (0.9 + 0.1) = 0.9
        assert compute_qwhr(warned, q_vals, rates) == pytest.approx(0.9)

    def test_unknown_patterns_use_prior(self):
        """Unknown patterns get 0.5 help rate prior."""
        warned = ["unknown"]
        q_vals = {"unknown": 0.6}
        rates = {}  # no data → default 0.5
        assert compute_qwhr(warned, q_vals, rates) == pytest.approx(0.5)

    def test_zero_q_total(self):
        """All Q values are 0 → return 0.0 (avoid division by zero)."""
        warned = ["a"]
        q_vals = {"a": 0.0}
        rates = {"a": 1.0}
        assert compute_qwhr(warned, q_vals, rates) == 0.0


# ---------------------------------------------------------------------------
# _extract_warned_patterns
# ---------------------------------------------------------------------------

class TestExtractPatterns:
    def test_basic_extraction(self):
        text = (
            "## Past Failures (L0)\n"
            "[WARN] import_error | preventable | Q:0.80 | seen:3 helped:2\n"
            "[WARN] type_mismatch | near_miss | Q:0.60 | seen:1 helped:0\n"
        )
        assert _extract_warned_patterns(text) == ["import_error", "type_mismatch"]

    def test_no_warns(self):
        assert _extract_warned_patterns("## Rules\n[RULE] no mocks (warn)") == []

    def test_dedup(self):
        """Same pattern in L0 and L1 sections should appear once."""
        text = (
            "[WARN] dup_pattern | preventable | Q:0.80 | seen:3 helped:2\n"
            "[WARN] dup_pattern | preventable | Q:0.80 | seen:3 helped:2\n"
            "  -> avoid this\n"
        )
        assert _extract_warned_patterns(text) == ["dup_pattern"]

    def test_empty_text(self):
        assert _extract_warned_patterns("") == []


# ---------------------------------------------------------------------------
# ParameterSpace
# ---------------------------------------------------------------------------

class TestParameterSpace:
    def test_greedy_sweep_skips_current(self):
        """Current value should not appear in sweep."""
        config = ForgeConfig()
        variants = list(ParameterSpace.greedy_sweep(config))
        for param, val, variant in variants:
            assert val != getattr(config, param)

    def test_greedy_sweep_changes_one_param(self):
        """Each variant changes exactly one parameter."""
        config = ForgeConfig()
        for param, val, variant in ParameterSpace.greedy_sweep(config):
            changed = 0
            for p in PARAM_GRID:
                if getattr(variant, p) != getattr(config, p):
                    changed += 1
            assert changed == 1, f"Expected 1 change, got {changed} for {param}={val}"

    def test_greedy_sweep_count(self):
        """Total variants = sum(len(values)-1 for each param)."""
        config = ForgeConfig()
        expected = sum(
            sum(1 for v in vals if v != getattr(config, p))
            for p, vals in PARAM_GRID.items()
        )
        actual = len(list(ParameterSpace.greedy_sweep(config)))
        assert actual == expected


# ---------------------------------------------------------------------------
# ExperimentSimulator
# ---------------------------------------------------------------------------

class TestExperimentSimulator:
    def test_simulate_session_basic(self, db):
        _make_failure(db, "pattern_a", q=0.8, times_warned=10, times_helped=8)
        _make_failure(db, "pattern_b", q=0.4, times_warned=10, times_helped=2)
        _make_session(db, "s1", warnings_injected=["pattern_a", "pattern_b"])

        from forge.storage.queries import list_failures
        failures = list_failures(db, "test")

        simulator = ExperimentSimulator("test", db, failures)
        sessions = list_sessions(db, "test")
        session = sessions[0]

        config = ForgeConfig()
        result = simulator.simulate_session(session, config)

        assert len(result.warned_patterns) > 0
        assert result.tokens_used > 0
        assert 0.0 <= result.qwhr <= 1.0

    def test_evaluate_config_no_sessions(self, db):
        from forge.storage.queries import list_failures
        failures = list_failures(db, "test")
        simulator = ExperimentSimulator("test", db, failures)

        result = simulator.evaluate_config(ForgeConfig(), [])
        assert result.qwhr == 0.0
        assert result.sessions_evaluated == 0

    def test_evaluate_config_with_sessions(self, db):
        _make_failure(db, "err_a", q=0.9, times_warned=20, times_helped=18)
        _make_failure(db, "err_b", q=0.3, times_warned=10, times_helped=1)
        _make_session(db, "s1", warnings_injected=["err_a", "err_b"])
        _make_session(db, "s2", warnings_injected=["err_a"])

        from forge.storage.queries import list_failures
        failures = list_failures(db, "test")
        sessions = list_sessions(db, "test")

        simulator = ExperimentSimulator("test", db, failures)
        result = simulator.evaluate_config(ForgeConfig(), sessions)

        assert result.sessions_evaluated == 2
        assert result.qwhr > 0.0
        assert 0.0 <= result.coverage
        assert 0.0 <= result.waste <= 1.0

    def test_help_rate_prior_for_unwarned(self, db):
        """Failures with times_warned=0 get 0.5 help rate prior."""
        _make_failure(db, "never_warned", q=0.7, times_warned=0, times_helped=0)
        _make_session(db, "s1")

        from forge.storage.queries import list_failures
        failures = list_failures(db, "test")

        simulator = ExperimentSimulator("test", db, failures)
        assert simulator.help_rates["never_warned"] == 0.5


# ---------------------------------------------------------------------------
# run_autoresearch
# ---------------------------------------------------------------------------

class TestRunAutoresearch:
    def test_cold_start_no_sessions(self, db):
        """No sessions → return baseline with zero metrics."""
        config = ForgeConfig()
        result = run_autoresearch("test", db, config, max_experiments=10)

        assert result.baseline.sessions_evaluated == 0
        assert result.total_experiments == 0
        assert not result.improved

    def test_basic_optimization(self, db):
        """With data, optimizer should run experiments."""
        for i in range(5):
            _make_failure(
                db, f"pattern_{i}", q=0.8 - i * 0.1,
                times_warned=10, times_helped=8 - i,
            )
        _make_session(db, "s1", warnings_injected=[f"pattern_{i}" for i in range(5)])
        _make_session(db, "s2", warnings_injected=[f"pattern_{i}" for i in range(3)])

        config = ForgeConfig()
        result = run_autoresearch("test", db, config, max_experiments=20)

        assert result.baseline.sessions_evaluated == 2
        assert result.total_experiments > 0
        assert len(result.experiments) > 1  # at least baseline + 1

    def test_progress_callback(self, db):
        """Progress callback should be called for each experiment."""
        _make_failure(db, "p1", q=0.7, times_warned=5, times_helped=4)
        _make_session(db, "s1", warnings_injected=["p1"])

        calls = []

        def on_progress(step, total, desc, result, improved):
            calls.append((step, desc, result.qwhr, improved))

        config = ForgeConfig()
        run_autoresearch(
            "test", db, config, max_experiments=5,
            on_progress=on_progress,
        )

        assert len(calls) > 0
        # Each call should have step > 0
        assert all(c[0] > 0 for c in calls)

    def test_max_experiments_limit(self, db):
        """Optimizer respects max_experiments limit."""
        for i in range(3):
            _make_failure(db, f"f_{i}", q=0.5)
        _make_session(db, "s1")

        config = ForgeConfig()
        result = run_autoresearch("test", db, config, max_experiments=5)

        assert result.total_experiments <= 5

    def test_greedy_improves_or_stays(self, db):
        """Best QWHR should be >= baseline."""
        _make_failure(db, "good_hint", q=0.9, times_warned=20, times_helped=19)
        _make_failure(db, "bad_hint", q=0.2, times_warned=20, times_helped=1)
        _make_session(db, "s1", warnings_injected=["good_hint", "bad_hint"])

        config = ForgeConfig()
        result = run_autoresearch("test", db, config, max_experiments=30)

        assert result.best.qwhr >= result.baseline.qwhr


# ---------------------------------------------------------------------------
# save_config_yaml
# ---------------------------------------------------------------------------

class TestSaveConfigYaml:
    def test_save_and_load(self, tmp_path):
        config = ForgeConfig(l0_max_entries=10, forge_context_tokens=1500)
        path = tmp_path / "config.yml"
        save_config_yaml(config, path)

        loaded = load_config(path)
        assert loaded.l0_max_entries == 10
        assert loaded.forge_context_tokens == 1500
        # Default values should be preserved
        assert loaded.alpha == 0.1

    def test_only_non_defaults_saved(self, tmp_path):
        """Only non-default values should appear in YAML."""
        config = ForgeConfig(l0_max_entries=10)  # only this differs
        path = tmp_path / "config.yml"
        save_config_yaml(config, path)

        raw = path.read_text()
        assert "l0_max_entries" in raw
        # Default values should NOT be in the file
        assert "alpha" not in raw

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "config.yml"
        config = ForgeConfig(l0_max_entries=20)
        save_config_yaml(config, path)
        assert path.exists()

    def test_default_config_empty_file(self, tmp_path):
        """Saving a default config produces an empty/minimal YAML."""
        config = ForgeConfig()
        path = tmp_path / "config.yml"
        save_config_yaml(config, path)
        loaded = load_config(path)
        assert loaded.l0_max_entries == ForgeConfig().l0_max_entries


# ---------------------------------------------------------------------------
# list_sessions (queries)
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_list_sessions_empty(self, db):
        sessions = list_sessions(db, "test")
        assert sessions == []

    def test_list_sessions_returns_all(self, db):
        _make_session(db, "s1")
        _make_session(db, "s2")
        sessions = list_sessions(db, "test")
        assert len(sessions) == 2

    def test_list_sessions_filters_workspace(self, db):
        _make_session(db, "s1", workspace="ws_a")
        _make_session(db, "s2", workspace="ws_b")
        sessions = list_sessions(db, "ws_a")
        assert len(sessions) == 1
        assert sessions[0].session_id == "s1"

    def test_list_sessions_order_desc(self, db):
        """Most recent session first."""
        _make_session(db, "s_old")
        _make_session(db, "s_new")
        sessions = list_sessions(db, "test")
        # s_new was inserted after s_old → should come first
        assert sessions[0].session_id == "s_new"
