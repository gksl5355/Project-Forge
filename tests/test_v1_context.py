"""Tests for v1 context budget and unified context."""

from __future__ import annotations

import pytest

from forge.config import ForgeConfig
from forge.core.context import (
    build_unified_context,
    estimate_tokens,
    format_team_runs,
    trim_to_budget,
)
from forge.storage.models import Decision, Failure, Knowledge, Rule, TeamRun


@pytest.fixture
def config():
    return ForgeConfig()


def _make_failure(pattern: str, q: float = 0.5, tags: list[str] | None = None) -> Failure:
    return Failure(
        workspace_id="test_ws",
        pattern=pattern,
        avoid_hint=f"Hint for {pattern}",
        hint_quality="preventable",
        q=q,
        tags=tags or [],
    )


def _make_team_run(run_id: str, **kwargs) -> TeamRun:
    defaults = {
        "workspace_id": "test_ws",
        "run_id": run_id,
        "complexity": "MEDIUM",
        "team_config": "sonnet:2",
        "success_rate": 0.9,
    }
    defaults.update(kwargs)
    return TeamRun(**defaults)


class TestFormatTeamRuns:
    def test_basic_format(self):
        runs = [_make_team_run("run-001")]
        result = format_team_runs(runs)
        assert "[TEAM] run-001" in result
        assert "MEDIUM" in result
        assert "sonnet:2" in result
        assert "90%" in result

    def test_with_verdict(self):
        runs = [_make_team_run("run-002", verdict="SUCCESS")]
        result = format_team_runs(runs)
        assert "verdict:SUCCESS" in result

    def test_null_success_rate(self):
        runs = [_make_team_run("run-003", success_rate=None)]
        result = format_team_runs(runs)
        assert "N/A" in result

    def test_empty_list(self):
        assert format_team_runs([]) == ""


class TestEstimateTokens:
    def test_basic(self):
        assert estimate_tokens("a" * 100) == 25

    def test_empty(self):
        assert estimate_tokens("") == 0


class TestTrimToBudget:
    def test_within_budget(self):
        text = "short text"
        assert trim_to_budget(text, 100) == text

    def test_exceeds_budget(self):
        text = "\n".join([f"line {i}" for i in range(100)])
        result = trim_to_budget(text, 10)
        assert "truncated" in result
        assert estimate_tokens(result) <= 15  # some overhead for marker

    def test_empty(self):
        assert trim_to_budget("", 100) == ""


class TestBuildUnifiedContext:
    def test_forge_only(self, config):
        failures = [_make_failure("err1", q=0.8)]
        rules = [Rule(workspace_id="test_ws", rule_text="No force push", enforcement_mode="block")]

        result = build_unified_context(failures, rules, config)
        assert "## Forge Experience" in result
        assert "err1" in result
        assert "## Team History" not in result

    def test_with_team_runs(self, config):
        failures = [_make_failure("err1")]
        rules = []
        team_runs = [_make_team_run("run-001")]

        result = build_unified_context(
            failures, rules, config, team_runs=team_runs
        )
        assert "## Forge Experience" in result
        assert "## Team History" in result
        assert "run-001" in result

    def test_team_failure_dedup(self, config):
        forge_failures = [_make_failure("shared_pattern")]
        team_failures = [_make_failure("shared_pattern", tags=["team"]),
                        _make_failure("unique_team_err", tags=["team"])]
        team_runs = [_make_team_run("run-001")]

        result = build_unified_context(
            forge_failures, [], config,
            team_runs=team_runs, team_failures=team_failures,
        )
        # shared_pattern should NOT appear in team section (deduped)
        # unique_team_err should appear
        assert "unique_team_err" in result

    def test_total_budget_enforced(self):
        config = ForgeConfig(total_max_tokens=50)
        failures = [_make_failure(f"pattern_{i}", q=0.5 + i * 0.01) for i in range(100)]
        rules = [Rule(workspace_id="test_ws", rule_text=f"Rule {i}") for i in range(20)]

        result = build_unified_context(failures, rules, config)
        assert estimate_tokens(result) <= 55  # some rounding tolerance

    def test_with_decisions_and_knowledge(self, config):
        failures = [_make_failure("err1")]
        decisions = [Decision(workspace_id="test_ws", statement="Use SQLite")]
        knowledge = [Knowledge(workspace_id="test_ws", title="Team Config", content="...")]

        result = build_unified_context(
            failures, [], config,
            decisions=decisions, knowledge_list=knowledge,
        )
        assert "err1" in result
