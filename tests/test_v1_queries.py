"""Tests for v1 query additions: team_runs CRUD, soft_delete, search_by_tags optimization."""

from __future__ import annotations

import pytest

from forge.storage.models import Failure, TeamRun
from forge.storage.queries import (
    get_team_run,
    insert_failure,
    insert_team_run,
    list_failures,
    list_team_runs,
    search_by_tags,
    soft_delete_failure,
    _safe_json_loads,
)


class TestTeamRunCRUD:
    def test_insert_and_get(self, db):
        tr = TeamRun(
            workspace_id="test_ws",
            run_id="2026-03-08-001",
            complexity="MEDIUM",
            team_config="sonnet:2 + haiku:1",
            duration_min=15.5,
            success_rate=0.85,
            retry_rate=0.1,
            scope_violations=2,
            verdict="SUCCESS",
            agents=[{"name": "silo-a", "model": "sonnet"}],
        )
        tid = insert_team_run(db, tr)
        assert tid > 0

        result = get_team_run(db, "2026-03-08-001")
        assert result is not None
        assert result.workspace_id == "test_ws"
        assert result.complexity == "MEDIUM"
        assert result.success_rate == 0.85
        assert result.scope_violations == 2
        assert len(result.agents) == 1

    def test_get_nonexistent(self, db):
        assert get_team_run(db, "nonexistent") is None

    def test_list_team_runs(self, db):
        for i in range(5):
            tr = TeamRun(workspace_id="test_ws", run_id=f"run-{i:03d}")
            insert_team_run(db, tr)

        results = list_team_runs(db, "test_ws")
        assert len(results) == 5

    def test_list_team_runs_limit(self, db):
        for i in range(10):
            insert_team_run(db, TeamRun(workspace_id="test_ws", run_id=f"run-{i:03d}"))

        results = list_team_runs(db, "test_ws", limit=3)
        assert len(results) == 3

    def test_list_team_runs_workspace_filter(self, db):
        insert_team_run(db, TeamRun(workspace_id="ws1", run_id="r1"))
        insert_team_run(db, TeamRun(workspace_id="ws2", run_id="r2"))

        assert len(list_team_runs(db, "ws1")) == 1
        assert len(list_team_runs(db, "ws2")) == 1

    def test_duplicate_run_id_raises(self, db):
        insert_team_run(db, TeamRun(workspace_id="test_ws", run_id="dup"))
        with pytest.raises(Exception):
            insert_team_run(db, TeamRun(workspace_id="test_ws", run_id="dup"))


class TestSoftDelete:
    def test_soft_delete(self, db):
        f = Failure(
            workspace_id="test_ws",
            pattern="test_pattern",
            avoid_hint="hint",
            hint_quality="preventable",
        )
        fid = insert_failure(db, f)
        assert len(list_failures(db, "test_ws", active_only=True)) == 1

        soft_delete_failure(db, fid)
        assert len(list_failures(db, "test_ws", active_only=True)) == 0

    def test_soft_delete_preserves_data(self, db):
        f = Failure(
            workspace_id="test_ws",
            pattern="preserved",
            avoid_hint="hint",
            hint_quality="preventable",
        )
        fid = insert_failure(db, f)
        soft_delete_failure(db, fid)

        # Should still be visible with active_only=False
        all_failures = list_failures(db, "test_ws", active_only=False)
        assert len(all_failures) == 1
        assert all_failures[0].active is False


class TestSearchByTagsOptimized:
    def test_single_tag(self, db):
        f = Failure(
            workspace_id="test_ws",
            pattern="tagged",
            avoid_hint="hint",
            hint_quality="preventable",
            tags=["python", "import"],
        )
        insert_failure(db, f)

        results = search_by_tags(db, "test_ws", ["python"])
        assert len(results) == 1

    def test_multiple_tags_no_duplicates(self, db):
        f = Failure(
            workspace_id="test_ws",
            pattern="multi_tag",
            avoid_hint="hint",
            hint_quality="preventable",
            tags=["python", "import"],
        )
        insert_failure(db, f)

        results = search_by_tags(db, "test_ws", ["python", "import"])
        assert len(results) == 1  # no duplicates

    def test_empty_tags(self, db):
        assert search_by_tags(db, "test_ws", []) == []

    def test_excludes_inactive(self, db):
        f = Failure(
            workspace_id="test_ws",
            pattern="inactive_tagged",
            avoid_hint="hint",
            hint_quality="preventable",
            tags=["python"],
        )
        fid = insert_failure(db, f)
        soft_delete_failure(db, fid)

        results = search_by_tags(db, "test_ws", ["python"])
        assert len(results) == 0


class TestSafeJsonLoads:
    def test_valid_json(self):
        assert _safe_json_loads('["a", "b"]') == ["a", "b"]

    def test_none(self):
        assert _safe_json_loads(None) == []

    def test_empty_string(self):
        assert _safe_json_loads("") == []

    def test_invalid_json(self):
        assert _safe_json_loads("not json") == []

    def test_custom_default(self):
        assert _safe_json_loads("bad", default={"key": "val"}) == {"key": "val"}


class TestActiveColumn:
    def test_list_failures_active_only_default(self, db):
        f1 = Failure(workspace_id="test_ws", pattern="active", avoid_hint="h", hint_quality="preventable")
        f2 = Failure(workspace_id="test_ws", pattern="inactive", avoid_hint="h", hint_quality="preventable")
        insert_failure(db, f1)
        fid2 = insert_failure(db, f2)
        soft_delete_failure(db, fid2)

        results = list_failures(db, "test_ws")
        assert len(results) == 1
        assert results[0].pattern == "active"

    def test_list_failures_include_inactive(self, db):
        f1 = Failure(workspace_id="test_ws", pattern="a1", avoid_hint="h", hint_quality="preventable")
        f2 = Failure(workspace_id="test_ws", pattern="a2", avoid_hint="h", hint_quality="preventable")
        insert_failure(db, f1)
        fid2 = insert_failure(db, f2)
        soft_delete_failure(db, fid2)

        results = list_failures(db, "test_ws", active_only=False)
        assert len(results) == 2
