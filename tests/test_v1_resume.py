"""Tests for v1 resume engine with team context integration."""

from __future__ import annotations

import pytest

from forge.config import ForgeConfig
from forge.engines.resume import run_resume
from forge.storage.models import Failure, TeamRun
from forge.storage.queries import insert_failure, insert_team_run


@pytest.fixture
def config():
    return ForgeConfig()


class TestResumeTeamBrief:
    def test_team_brief_empty(self, db, config):
        result = run_resume("test_ws", "sess-001", db, config, team_brief=True)
        assert result == ""

    def test_team_brief_with_runs(self, db, config):
        insert_team_run(db, TeamRun(workspace_id="test_ws", run_id="run-001", complexity="MEDIUM", team_config="sonnet:2", success_rate=0.9))

        result = run_resume("test_ws", "sess-002", db, config, team_brief=True)
        assert "Recent Team Runs" in result
        assert "run-001" in result

    def test_team_brief_with_team_failures(self, db, config):
        insert_failure(db, Failure(
            workspace_id="test_ws",
            pattern="scope_drift_silo_a",
            avoid_hint="Check scope",
            hint_quality="preventable",
            tags=["team", "scope_drift"],
        ))

        result = run_resume("test_ws", "sess-003", db, config, team_brief=True)
        assert "Team-Related Failures" in result
        assert "scope_drift_silo_a" in result


class TestResumeUnifiedContext:
    def test_unified_with_team_runs(self, db, config):
        insert_failure(db, Failure(
            workspace_id="test_ws",
            pattern="regular_err",
            avoid_hint="Fix it",
            hint_quality="preventable",
        ))
        insert_team_run(db, TeamRun(workspace_id="test_ws", run_id="run-001", complexity="SIMPLE"))

        result = run_resume("test_ws", "sess-004", db, config)
        assert "## Forge Experience" in result
        assert "## Team History" in result
        assert "regular_err" in result
        assert "run-001" in result

    def test_fallback_without_team_runs(self, db, config):
        insert_failure(db, Failure(
            workspace_id="test_ws",
            pattern="solo_err",
            avoid_hint="Fix it",
            hint_quality="preventable",
        ))

        result = run_resume("test_ws", "sess-005", db, config)
        # Should use old code path without Forge Experience / Team History headers
        assert "solo_err" in result
        assert "## Team History" not in result

    def test_team_failures_separated(self, db, config):
        insert_failure(db, Failure(
            workspace_id="test_ws",
            pattern="regular",
            avoid_hint="r",
            hint_quality="preventable",
        ))
        insert_failure(db, Failure(
            workspace_id="test_ws",
            pattern="team_issue",
            avoid_hint="t",
            hint_quality="preventable",
            tags=["team"],
        ))
        insert_team_run(db, TeamRun(workspace_id="test_ws", run_id="run-001"))

        result = run_resume("test_ws", "sess-006", db, config)
        assert "## Forge Experience" in result
        assert "## Team History" in result
