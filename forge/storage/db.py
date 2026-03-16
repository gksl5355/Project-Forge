"""SQLite connection, schema initialization, and migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE schema_version (
    version INTEGER NOT NULL
);
INSERT INTO schema_version VALUES (1);

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
    last_used       DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, pattern)
);

CREATE TABLE decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL,
    statement       TEXT NOT NULL,
    rationale       TEXT,
    alternatives    TEXT DEFAULT '[]',
    q               REAL NOT NULL DEFAULT 0.5,
    status          TEXT DEFAULT 'active' CHECK(status IN ('active','superseded','revisiting')),
    superseded_by   INTEGER REFERENCES decisions(id),
    tags            TEXT DEFAULT '[]',
    last_used       DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
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
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL UNIQUE,
    workspace_id    TEXT NOT NULL,
    warnings_injected TEXT DEFAULT '[]',
    started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at        DATETIME
);

CREATE INDEX idx_failures_ws_q ON failures(workspace_id, q DESC);
CREATE INDEX idx_decisions_ws_status ON decisions(workspace_id, status);
CREATE INDEX idx_knowledge_ws_q ON knowledge(workspace_id, q DESC);
CREATE INDEX idx_rules_ws_active ON rules(workspace_id, active);
"""

_DEFAULT_DB_PATH = Path.home() / ".forge" / "forge.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a configured SQLite connection."""
    path = db_path or _DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Create DB file and initialize schema. Idempotent."""
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create schema if not present, or migrate if outdated."""
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "schema_version" not in tables:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        return

    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    if version < CURRENT_SCHEMA_VERSION:
        _migrate(conn, from_version=version)


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Apply incremental migrations. Extend as schema evolves."""
    # No migrations needed for v1 → future versions add ALTER TABLE here
    conn.execute(
        "UPDATE schema_version SET version = ?", (CURRENT_SCHEMA_VERSION,)
    )
    conn.commit()
