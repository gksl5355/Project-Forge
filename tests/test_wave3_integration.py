"""Wave 3 integration tests: measure v5, CLI commands, cross-module wiring."""
from __future__ import annotations

import json
import sqlite3

import pytest

from forge.config import ForgeConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """In-memory SQLite DB with v5 schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (5);

        CREATE TABLE failures (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id    TEXT NOT NULL,
            pattern         TEXT NOT NULL,
            observed_error  TEXT,
            likely_cause    TEXT,
            avoid_hint      TEXT NOT NULL,
            hint_quality    TEXT NOT NULL CHECK(hint_quality IN ('near_miss','preventable','environmental')),
            q               REAL NOT NULL DEFAULT 0.5,
            times_seen      INTEGER NOT NULL DEFAULT 1,
            times_helped    INTEGER NOT NULL DEFAULT 0,
            times_warned    INTEGER NOT NULL DEFAULT 0,
            tags            TEXT DEFAULT '[]',
            projects_seen   TEXT DEFAULT '[]',
            source          TEXT DEFAULT 'manual',
            review_flag     INTEGER DEFAULT 0,
            active          INTEGER DEFAULT 1,
            last_used       DATETIME,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(workspace_id, pattern)
        );

        CREATE TABLE decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id    TEXT NOT NULL,
            statement       TEXT NOT NULL,
            reasoning       TEXT,
            alternatives    TEXT DEFAULT '[]',
            q               REAL NOT NULL DEFAULT 0.5,
            status          TEXT NOT NULL DEFAULT 'active',
            times_seen      INTEGER NOT NULL DEFAULT 1,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(workspace_id, statement)
        );

        CREATE TABLE rules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id    TEXT NOT NULL,
            rule_text       TEXT NOT NULL,
            scope           TEXT,
            enforcement_mode TEXT DEFAULT 'warn' CHECK(enforcement_mode IN ('block','warn','log')),
            active          INTEGER DEFAULT 1,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE knowledge (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id    TEXT NOT NULL,
            title           TEXT NOT NULL,
            content         TEXT NOT NULL,
            source          TEXT DEFAULT 'seeded' CHECK(source IN ('seeded','organic')),
            q               REAL NOT NULL DEFAULT 0.5,
            tags            TEXT DEFAULT '[]',
            promoted_from   INTEGER REFERENCES failures(id),
            last_used       DATETIME,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE sessions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id        TEXT NOT NULL,
            workspace_id      TEXT NOT NULL,
            started_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at          DATETIME,
            warnings_injected TEXT DEFAULT '[]',
            q_updates_count   INTEGER DEFAULT 0,
            new_patterns      INTEGER DEFAULT 0,
            config_hash       TEXT,
            document_hash     TEXT,
            unified_fitness   REAL,
            UNIQUE(session_id)
        );

        CREATE TABLE experiments (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id        TEXT NOT NULL,
            experiment_type     TEXT NOT NULL DEFAULT 'manual',
            config_snapshot     TEXT,
            config_hash         TEXT,
            document_hashes     TEXT,
            document_hash       TEXT,
            unified_fitness     REAL,
            qwhr                REAL,
            token_efficiency    REAL,
            promotion_precision REAL,
            to_success_rate     REAL,
            to_retry_rate       REAL,
            to_scope_violations REAL,
            sessions_evaluated  INTEGER DEFAULT 0,
            team_runs_evaluated INTEGER DEFAULT 0,
            notes               TEXT,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE team_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            workspace_id    TEXT NOT NULL,
            complexity      TEXT,
            team_config     TEXT,
            agent_count     INTEGER DEFAULT 0,
            duration_minutes REAL,
            success_rate    REAL,
            retry_rate      REAL,
            scope_violations INTEGER DEFAULT 0,
            verdict         TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id, workspace_id)
        );

        CREATE TABLE forge_meta (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE model_choices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id    TEXT NOT NULL,
            session_id      TEXT NOT NULL,
            task_category   TEXT NOT NULL,
            selected_model  TEXT NOT NULL,
            outcome         REAL,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE agents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL UNIQUE,
            workspace_id    TEXT NOT NULL,
            session_id      TEXT NOT NULL,
            team_name       TEXT,
            role            TEXT,
            model           TEXT,
            pane_id         TEXT,
            pid             INTEGER,
            status          TEXT DEFAULT 'active',
            started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at        DATETIME
        );
    """)
    yield conn
    conn.close()


def _seed_workspace(db: sqlite3.Connection, ws: str = "test") -> None:
    """Insert sample data for integration tests."""
    # Failures
    for i, (pat, hint, q, warned, helped) in enumerate([
        ("import_error", "Use correct import path", 0.8, 10, 7),
        ("type_mismatch", "Check type annotations", 0.6, 8, 3),
        ("timeout_flake", "x", 0.2, 5, 0),  # low quality hint
    ]):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality, q, "
            "times_seen, times_warned, times_helped, tags, projects_seen, active) "
            "VALUES (?, ?, ?, 'preventable', ?, ?, ?, ?, '[]', '[]', 1)",
            (ws, pat, hint, q, i + 2, warned, helped),
        )

    # Sessions
    for sid in ["s1", "s2", "s3"]:
        db.execute(
            "INSERT INTO sessions (session_id, workspace_id, warnings_injected, q_updates_count) "
            "VALUES (?, ?, '[\"import_error\"]', 1)",
            (sid, ws),
        )

    # Model choices
    for sid, cat, model, outcome in [
        ("s1", "quick", "haiku", 0.9),
        ("s1", "quick", "haiku", 0.8),
        ("s2", "quick", "sonnet", 0.5),
        ("s2", "standard", "sonnet", 0.7),
        ("s3", "quick", "haiku", 0.85),
        ("s3", "quick", "haiku", 0.88),
        ("s3", "quick", "haiku", 0.92),
    ]:
        db.execute(
            "INSERT INTO model_choices (workspace_id, session_id, task_category, selected_model, outcome) "
            "VALUES (?, ?, ?, ?, ?)",
            (ws, sid, cat, model, outcome),
        )

    # Agents
    for name, status in [("main", "completed"), ("silo-a", "completed"), ("silo-b", "error")]:
        db.execute(
            "INSERT INTO agents (agent_id, workspace_id, session_id, role, status) "
            "VALUES (?, ?, 's1', 'main', ?)",
            (f"{ws}:s1:{name}", ws, status),
        )

    # Breaker state
    db.execute(
        "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
        ("breaker:s1", json.dumps({"consecutive_failures": 2, "tool_calls": 50, "tripped": False})),
    )
    db.execute(
        "INSERT INTO forge_meta (key, value) VALUES (?, ?)",
        ("breaker:s2", json.dumps({"consecutive_failures": 6, "tool_calls": 30, "tripped": True, "trip_reason": "max_failures"})),
    )

    # Rules
    db.execute(
        "INSERT INTO rules (workspace_id, rule_text, enforcement_mode, active) "
        "VALUES (?, 'Always run tests', 'warn', 1)",
        (ws,),
    )

    db.commit()


# ---------------------------------------------------------------------------
# Test: measure.py v5 integration
# ---------------------------------------------------------------------------

class TestMeasureV5Integration:
    def test_run_measure_returns_v5_fields(self, db: sqlite3.Connection) -> None:
        """run_measure should populate all v5 KPI fields."""
        from forge.engines.measure import run_measure

        _seed_workspace(db, "test")
        config = ForgeConfig()
        result = run_measure("test", db, config)

        # v4 fields still present
        assert result.qwhr >= 0.0
        assert result.unified_fitness >= 0.0
        assert result.total_failures == 3
        assert result.total_sessions == 3

        # v5 fields populated
        assert 0.0 <= result.routing_accuracy <= 1.0
        assert 0.0 <= result.circuit_efficiency <= 1.0
        assert 0.0 <= result.agent_utilization <= 1.0
        assert 0.0 <= result.context_hit_rate <= 1.0
        assert 0.0 <= result.tool_efficiency <= 1.0
        assert 0.0 <= result.redundant_call_rate <= 1.0
        assert 0.0 <= result.stale_warning_rate <= 1.0
        assert 0.0 <= result.unified_fitness_v5 <= 1.0

    def test_v5_fitness_reflects_data(self, db: sqlite3.Connection) -> None:
        """v5 fitness should be non-zero with seeded data."""
        from forge.engines.measure import run_measure

        _seed_workspace(db, "test")
        result = run_measure("test", db, ForgeConfig())

        # We have data → fitness should be meaningfully > 0
        assert result.unified_fitness_v5 > 0.1

        # Agent utilization: 2 completed / 3 total = 0.667
        assert abs(result.agent_utilization - 2 / 3) < 0.01

        # Circuit efficiency: 1 tripped / 3 sessions → 1 - 1/3 ≈ 0.667
        assert abs(result.circuit_efficiency - (1 - 1 / 3)) < 0.01

    def test_empty_workspace_defaults(self, db: sqlite3.Connection) -> None:
        """Empty workspace should return sensible defaults."""
        from forge.engines.measure import run_measure

        result = run_measure("empty", db, ForgeConfig())

        assert result.unified_fitness_v5 >= 0.0
        assert result.circuit_efficiency == 1.0  # no sessions → perfect
        assert result.agent_utilization == 0.0
        assert result.routing_accuracy == 0.0


# ---------------------------------------------------------------------------
# Test: fitness v5 ↔ metrics_v5 wiring
# ---------------------------------------------------------------------------

class TestFitnessMetricsWiring:
    def test_fitness_v5_weights_sum_to_one(self) -> None:
        from forge.engines.fitness import compute_unified_fitness_v5

        # All 1.0 → should be 1.0
        assert abs(compute_unified_fitness_v5(1, 1, 1, 1, 1, 1, 0, 0) - 1.0) < 1e-9

    def test_fitness_v5_all_zeros(self) -> None:
        from forge.engines.fitness import compute_unified_fitness_v5

        # All 0.0, redundant=1.0, stale=1.0 → min
        result = compute_unified_fitness_v5(0, 0, 0, 0, 0, 0, 1.0, 1.0)
        assert abs(result) < 1e-9


# ---------------------------------------------------------------------------
# Test: prompt_optimizer ↔ context.py integration
# ---------------------------------------------------------------------------

class TestPromptContextIntegration:
    def test_context_ab_variant_concise(self, db: sqlite3.Connection) -> None:
        """build_context with variant='concise' should use prompt_optimizer format."""
        from forge.core.context import build_context
        from forge.storage.models import Failure

        failures = [
            Failure(
                workspace_id="test", pattern="test_pat", observed_error="err",
                likely_cause="cause", avoid_hint="Use X instead", hint_quality="preventable",
                q=0.7, times_seen=3, times_helped=2, times_warned=5,
            ),
        ]
        config = ForgeConfig()
        result = build_context(failures, [], config, variant="concise")

        assert "test_pat" in result
        assert "Q:0.70" in result

    def test_context_default_variant_unchanged(self, db: sqlite3.Connection) -> None:
        """Default variant should produce same format as before."""
        from forge.core.context import build_context
        from forge.storage.models import Failure

        failures = [
            Failure(
                workspace_id="test", pattern="my_pattern", observed_error="err",
                likely_cause="cause", avoid_hint="Fix it", hint_quality="near_miss",
                q=0.5, times_seen=1, times_helped=0, times_warned=2,
            ),
        ]
        config = ForgeConfig()
        result = build_context(failures, [], config)

        # Default L0 format: [WARN] pattern | quality | Q:... | seen:... helped:...
        assert "[WARN] my_pattern | near_miss | Q:0.50" in result

    def test_injection_score_sorting(self) -> None:
        """sort_by_injection_score should reorder failures."""
        from forge.core.context import build_context
        from forge.storage.models import Failure

        f_low = Failure(
            workspace_id="test", pattern="low_q", observed_error="", likely_cause="",
            avoid_hint="hint", hint_quality="environmental", q=0.1,
            times_seen=1, times_helped=0, times_warned=1,
        )
        f_high = Failure(
            workspace_id="test", pattern="high_q", observed_error="", likely_cause="",
            avoid_hint="hint", hint_quality="near_miss", q=0.9,
            times_seen=5, times_helped=4, times_warned=5,
        )
        config = ForgeConfig()
        result = build_context([f_low, f_high], [], config, sort_by_injection_score=True)

        # high_q should appear first
        pos_high = result.index("high_q")
        pos_low = result.index("low_q")
        assert pos_high < pos_low


# ---------------------------------------------------------------------------
# Test: research_v5 integration
# ---------------------------------------------------------------------------

class TestResearchV5Integration:
    def test_run_research_v5_with_data(self, db: sqlite3.Connection) -> None:
        from forge.engines.research_v5 import run_research_v5

        _seed_workspace(db, "test")
        result = run_research_v5("test", db)

        assert result.unified_fitness_before >= 0.0
        assert result.unified_fitness_after >= result.unified_fitness_before
        assert isinstance(result.improvements, list)
        assert isinstance(result.sweep_log, list)

    def test_run_prompt_research_empty(self, db: sqlite3.Connection) -> None:
        from forge.engines.research_v5 import run_prompt_research

        result = run_prompt_research("empty", db)

        assert result.best_format == "concise"
        assert result.low_quality_hints_count == 0

    def test_run_prompt_research_with_data(self, db: sqlite3.Connection) -> None:
        from forge.engines.research_v5 import run_prompt_research

        _seed_workspace(db, "test")
        result = run_prompt_research("test", db)

        assert result.best_format in ("concise", "detailed")
        total = sum(result.hint_quality_distribution.values())
        assert total == 3  # 3 failures seeded


# ---------------------------------------------------------------------------
# Test: CLI commands (typer testing)
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_db(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Patch get_connection to return in-memory DB for CLI tests."""
    monkeypatch.setattr("forge.cli.get_connection", lambda: db)
    return db


class TestCLICommands:
    def test_measure_v5_flag(self, cli_db: sqlite3.Connection) -> None:
        """forge measure --v5 should include v5 KPI section."""
        from typer.testing import CliRunner
        from forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["measure", "--v5", "-w", "nonexistent"])
        assert result.exit_code == 0
        assert "v5 KPI" in result.output

    def test_measure_hints_flag(self, cli_db: sqlite3.Connection) -> None:
        from typer.testing import CliRunner
        from forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["measure", "--hints", "-w", "nonexistent"])
        assert result.exit_code == 0
        assert "Hint Quality" in result.output

    def test_measure_skills_flag(self, cli_db: sqlite3.Connection) -> None:
        from typer.testing import CliRunner
        from forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["measure", "--skills", "-w", "nonexistent"])
        assert result.exit_code == 0
        assert "Skill Effectiveness" in result.output

    def test_research_v5_flag(self, cli_db: sqlite3.Connection) -> None:
        from typer.testing import CliRunner
        from forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["research", "--v5", "-w", "nonexistent"])
        assert result.exit_code == 0
        assert "AutoResearch v5" in result.output

    def test_research_prompts_flag(self, cli_db: sqlite3.Connection) -> None:
        from typer.testing import CliRunner
        from forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["research", "--prompts", "-w", "nonexistent"])
        assert result.exit_code == 0
        assert "Prompt Research" in result.output

    def test_improve_hints_dry_run(self, cli_db: sqlite3.Connection) -> None:
        from typer.testing import CliRunner
        from forge.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["improve-hints", "-w", "nonexistent"])
        assert result.exit_code == 0
        assert "No low-quality hints" in result.output or "dry-run" in result.output
