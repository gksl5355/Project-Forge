"""Tests for v1 ingest engine."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from forge.config import ForgeConfig
from forge.engines.ingest import run_ingest, run_ingest_auto
from forge.storage.queries import (
    get_failure_by_pattern,
    get_team_run,
    list_failures,
    list_knowledge,
    list_team_runs,
)


@pytest.fixture
def config():
    return ForgeConfig()


@pytest.fixture
def run_dir(tmp_path):
    """Create a mock TO run directory with report.yml and events.yml."""
    d = tmp_path / "run-001"
    d.mkdir()
    return d


class TestIngestReport:
    def test_ingest_report_basic(self, db, config, run_dir):
        report = {
            "run_id": "2026-03-08-001",
            "complexity": "MEDIUM",
            "team_config": "sonnet:2 + haiku:1",
            "duration_min": 15.5,
            "success_rate": 0.85,
            "retry_rate": 0.1,
            "scope_violations": 1,
            "verdict": "SUCCESS",
            "agents": [{"name": "silo-a", "model": "sonnet", "tasks_completed": 3}],
        }
        (run_dir / "report.yml").write_text(yaml.dump(report))

        counts = run_ingest("test_ws", run_dir, db, config)

        assert counts["team_runs"] == 1
        tr = get_team_run(db, "2026-03-08-001")
        assert tr is not None
        assert tr.complexity == "MEDIUM"
        assert tr.success_rate == 0.85
        assert tr.scope_violations == 1
        assert len(tr.agents) == 1

    def test_ingest_report_duplicate_skip(self, db, config, run_dir):
        report = {"run_id": "dup-001", "complexity": "SIMPLE"}
        (run_dir / "report.yml").write_text(yaml.dump(report))

        counts1 = run_ingest("test_ws", run_dir, db, config)
        counts2 = run_ingest("test_ws", run_dir, db, config)

        assert counts1["team_runs"] == 1
        assert counts2["team_runs"] == 0  # skipped

    def test_ingest_report_no_run_id(self, db, config, run_dir):
        (run_dir / "report.yml").write_text(yaml.dump({"complexity": "SIMPLE"}))

        counts = run_ingest("test_ws", run_dir, db, config)
        assert counts["team_runs"] == 0

    def test_ingest_no_report(self, db, config, run_dir):
        counts = run_ingest("test_ws", run_dir, db, config)
        assert counts["team_runs"] == 0


class TestIngestEvents:
    def test_scope_drift_creates_failure(self, db, config, run_dir):
        events = [
            {
                "type": "scope_drift",
                "agent": "silo-a",
                "description": "Modified files outside assigned scope",
            }
        ]
        (run_dir / "events.yml").write_text(yaml.dump(events))

        counts = run_ingest("test_ws", run_dir, db, config)
        assert counts["failures"] == 1

        f = get_failure_by_pattern(db, "test_ws", "scope_drift_silo-a")
        assert f is not None
        assert f.hint_quality == "preventable"
        assert "team" in f.tags

    def test_retry_heavy_creates_failure(self, db, config, run_dir):
        events = [
            {
                "type": "retry_heavy",
                "agent": "silo-b",
                "description": "5 retries on build step",
            }
        ]
        (run_dir / "events.yml").write_text(yaml.dump(events))

        counts = run_ingest("test_ws", run_dir, db, config)
        assert counts["failures"] == 1

        f = get_failure_by_pattern(db, "test_ws", "retry_heavy_silo-b")
        assert f is not None
        assert f.hint_quality == "near_miss"

    def test_team_success_creates_knowledge(self, db, config, run_dir):
        events = [
            {
                "type": "team_success",
                "task_type": "refactor",
                "team_config": "sonnet:2",
                "description": "Completed refactor in 10min",
            }
        ]
        (run_dir / "events.yml").write_text(yaml.dump(events))

        counts = run_ingest("test_ws", run_dir, db, config)
        assert counts["knowledge"] == 1

        kl = list_knowledge(db, "test_ws", include_global=False)
        assert len(kl) == 1
        assert "team_config" in kl[0].title
        assert "sonnet:2" in kl[0].content

    def test_duplicate_scope_drift_increments(self, db, config, run_dir):
        events = [
            {"type": "scope_drift", "agent": "silo-a", "description": "First"},
        ]
        (run_dir / "events.yml").write_text(yaml.dump(events))
        run_ingest("test_ws", run_dir, db, config)

        events2 = [
            {"type": "scope_drift", "agent": "silo-a", "description": "Second"},
        ]
        (run_dir / "events.yml").write_text(yaml.dump(events2))
        run_ingest("test_ws", run_dir, db, config)

        f = get_failure_by_pattern(db, "test_ws", "scope_drift_silo-a")
        assert f.times_seen == 2

    def test_mixed_events(self, db, config, run_dir):
        report = {"run_id": "mix-001", "complexity": "COMPLEX"}
        events = [
            {"type": "scope_drift", "agent": "a", "description": "d1"},
            {"type": "retry_heavy", "agent": "b", "description": "d2"},
            {"type": "team_success", "task_type": "build", "description": "d3"},
            {"type": "unknown_type", "description": "ignored"},
        ]
        (run_dir / "report.yml").write_text(yaml.dump(report))
        (run_dir / "events.yml").write_text(yaml.dump(events))

        counts = run_ingest("test_ws", run_dir, db, config)
        assert counts["team_runs"] == 1
        assert counts["failures"] == 2
        assert counts["knowledge"] == 1


class TestIngestAuto:
    def test_auto_with_latest(self, db, config, tmp_path):
        latest = tmp_path / "latest"
        latest.mkdir()
        report = {"run_id": "auto-001", "complexity": "SIMPLE"}
        (latest / "report.yml").write_text(yaml.dump(report))

        counts = run_ingest_auto("test_ws", tmp_path, db, config)
        assert counts["team_runs"] == 1

    def test_auto_nonexistent_dir(self, db, config, tmp_path):
        counts = run_ingest_auto("test_ws", tmp_path / "nonexistent", db, config)
        assert counts["team_runs"] == 0

    def test_auto_multiple_runs(self, db, config, tmp_path):
        for i in range(3):
            d = tmp_path / f"run-{i:03d}"
            d.mkdir()
            (d / "report.yml").write_text(yaml.dump({"run_id": f"auto-{i}", "complexity": "SIMPLE"}))

        counts = run_ingest_auto("test_ws", tmp_path, db, config)
        assert counts["team_runs"] == 3
