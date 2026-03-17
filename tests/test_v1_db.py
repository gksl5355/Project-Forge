"""Tests for v1 DB migration and schema changes."""

from __future__ import annotations

import sqlite3
import pytest

from forge.storage.db import CURRENT_SCHEMA_VERSION, _migrate, _ensure_schema


class TestSchemaVersion:
    def test_current_version_is_4(self):
        assert CURRENT_SCHEMA_VERSION == 4


class TestMigration:
    def test_migrate_from_v2(self, db):
        """Simulate v2 → v3 migration on a v2 schema DB."""
        # Our conftest already creates v3 schema, so we test the migration logic
        # by creating a fresh v2 DB
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        # Create v2 schema (without active column and team_runs)
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (2);

            CREATE TABLE failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT NOT NULL,
                pattern TEXT NOT NULL,
                observed_error TEXT,
                likely_cause TEXT,
                avoid_hint TEXT NOT NULL,
                hint_quality TEXT NOT NULL,
                q REAL NOT NULL DEFAULT 0.5,
                times_seen INTEGER NOT NULL DEFAULT 1,
                times_helped INTEGER NOT NULL DEFAULT 0,
                times_warned INTEGER NOT NULL DEFAULT 0,
                tags TEXT DEFAULT '[]',
                projects_seen TEXT DEFAULT '[]',
                source TEXT DEFAULT 'manual',
                review_flag INTEGER DEFAULT 0,
                last_used DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(workspace_id, pattern)
            );

            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                workspace_id TEXT NOT NULL,
                warnings_injected TEXT DEFAULT '[]',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ended_at DATETIME,
                failures_encountered INTEGER DEFAULT 0,
                q_updates_count INTEGER DEFAULT 0,
                promotions_count INTEGER DEFAULT 0
            );
        """)

        # Run migration
        _migrate(conn, from_version=2)

        # Verify active column was added
        conn.execute("INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality, active) VALUES ('test', 'p', 'h', 'preventable', 1)")
        row = conn.execute("SELECT active FROM failures WHERE pattern = 'p'").fetchone()
        assert row[0] == 1

        # Verify team_runs table was created
        conn.execute("INSERT INTO team_runs (workspace_id, run_id) VALUES ('test', 'r1')")
        row = conn.execute("SELECT * FROM team_runs WHERE run_id = 'r1'").fetchone()
        assert row is not None

        # Verify version updated (migrates through to v4)
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 4

        # Verify v4: experiments table and session extensions
        conn.execute("SELECT id FROM experiments LIMIT 0")
        conn.execute("SELECT config_hash, document_hash, unified_fitness FROM sessions LIMIT 0")

        conn.close()


class TestTeamRunsSchema:
    def test_team_runs_columns(self, db):
        """Verify team_runs table has all required columns."""
        db.execute("""
            INSERT INTO team_runs
                (workspace_id, run_id, complexity, team_config, duration_min,
                 success_rate, retry_rate, scope_violations, verdict, agents)
            VALUES ('ws', 'r1', 'MEDIUM', 'sonnet:2', 15.5, 0.85, 0.1, 2, 'SUCCESS', '[]')
        """)
        row = db.execute("SELECT * FROM team_runs WHERE run_id = 'r1'").fetchone()
        assert row["complexity"] == "MEDIUM"
        assert row["success_rate"] == 0.85
        assert row["scope_violations"] == 2

    def test_team_runs_unique_run_id(self, db):
        db.execute("INSERT INTO team_runs (workspace_id, run_id) VALUES ('ws', 'dup')")
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO team_runs (workspace_id, run_id) VALUES ('ws', 'dup')")

    def test_team_runs_index_exists(self, db):
        indexes = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='team_runs'"
        ).fetchall()
        index_names = [i[0] for i in indexes]
        assert "idx_team_runs_ws" in index_names


class TestFailuresActiveColumn:
    def test_active_default_is_1(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality) VALUES ('ws', 'p', 'h', 'preventable')"
        )
        db.commit()
        row = db.execute("SELECT active FROM failures WHERE pattern = 'p'").fetchone()
        assert row[0] == 1

    def test_active_can_be_set_to_0(self, db):
        db.execute(
            "INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality, active) VALUES ('ws', 'p2', 'h', 'preventable', 0)"
        )
        db.commit()
        row = db.execute("SELECT active FROM failures WHERE pattern = 'p2'").fetchone()
        assert row[0] == 0
