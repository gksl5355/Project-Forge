"""CRUD query functions for all Forge storage tables."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, UTC

from forge.storage.models import Decision, Failure, Knowledge, Rule, Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    # SQLite stores datetimes as ISO strings
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _dt_str(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------

def _row_to_failure(row: sqlite3.Row) -> Failure:
    return Failure(
        id=row["id"],
        workspace_id=row["workspace_id"],
        pattern=row["pattern"],
        observed_error=row["observed_error"],
        likely_cause=row["likely_cause"],
        avoid_hint=row["avoid_hint"],
        hint_quality=row["hint_quality"],
        q=row["q"],
        times_seen=row["times_seen"],
        times_helped=row["times_helped"],
        times_warned=row["times_warned"],
        tags=json.loads(row["tags"] or "[]"),
        projects_seen=json.loads(row["projects_seen"] or "[]"),
        source=row["source"],
        review_flag=bool(row["review_flag"]),
        last_used=_parse_dt(row["last_used"]),
        created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
        updated_at=_parse_dt(row["updated_at"]) or datetime.now(UTC),
    )


def insert_failure(db: sqlite3.Connection, failure: Failure) -> int:
    cur = db.execute(
        """
        INSERT INTO failures
            (workspace_id, pattern, observed_error, likely_cause, avoid_hint,
             hint_quality, q, times_seen, times_helped, times_warned,
             tags, projects_seen, source, review_flag, last_used,
             created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            failure.workspace_id,
            failure.pattern,
            failure.observed_error,
            failure.likely_cause,
            failure.avoid_hint,
            failure.hint_quality,
            failure.q,
            failure.times_seen,
            failure.times_helped,
            failure.times_warned,
            json.dumps(failure.tags),
            json.dumps(failure.projects_seen),
            failure.source,
            int(failure.review_flag),
            _dt_str(failure.last_used),
            _dt_str(failure.created_at),
            _dt_str(failure.updated_at),
        ),
    )
    db.commit()
    return cur.lastrowid


def get_failure_by_pattern(
    db: sqlite3.Connection, workspace_id: str, pattern: str
) -> Failure | None:
    row = db.execute(
        "SELECT * FROM failures WHERE workspace_id = ? AND pattern = ?",
        (workspace_id, pattern),
    ).fetchone()
    return _row_to_failure(row) if row else None


def get_failure_by_id(
    db: sqlite3.Connection, failure_id: int, workspace_id: str
) -> Failure | None:
    row = db.execute(
        "SELECT * FROM failures WHERE id = ? AND workspace_id = ?",
        (failure_id, workspace_id),
    ).fetchone()
    return _row_to_failure(row) if row else None


def list_failures(
    db: sqlite3.Connection,
    workspace_id: str,
    sort_by: str = "q",
    include_global: bool = True,
) -> list[Failure]:
    allowed_sort = {"q", "times_seen", "created_at", "updated_at", "last_used"}
    order_col = sort_by if sort_by in allowed_sort else "q"

    if include_global:
        rows = db.execute(
            f"SELECT * FROM failures WHERE workspace_id IN (?, '__global__') ORDER BY {order_col} DESC",
            (workspace_id,),
        ).fetchall()
    else:
        rows = db.execute(
            f"SELECT * FROM failures WHERE workspace_id = ? ORDER BY {order_col} DESC",
            (workspace_id,),
        ).fetchall()
    return [_row_to_failure(r) for r in rows]


def update_failure(db: sqlite3.Connection, failure: Failure) -> None:
    db.execute(
        """
        UPDATE failures SET
            observed_error = ?, likely_cause = ?, avoid_hint = ?,
            hint_quality = ?, q = ?, times_seen = ?, times_helped = ?,
            times_warned = ?, tags = ?, projects_seen = ?, source = ?,
            review_flag = ?, last_used = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            failure.observed_error,
            failure.likely_cause,
            failure.avoid_hint,
            failure.hint_quality,
            failure.q,
            failure.times_seen,
            failure.times_helped,
            failure.times_warned,
            json.dumps(failure.tags),
            json.dumps(failure.projects_seen),
            failure.source,
            int(failure.review_flag),
            _dt_str(failure.last_used),
            _dt_str(datetime.now(UTC)),
            failure.id,
        ),
    )
    db.commit()


def list_flagged_failures(
    db: sqlite3.Connection, workspace_id: str
) -> list[Failure]:
    """review_flag=True인 실패 목록 반환."""
    rows = db.execute(
        "SELECT * FROM failures WHERE workspace_id = ? AND review_flag = 1 ORDER BY q DESC",
        (workspace_id,),
    ).fetchall()
    return [_row_to_failure(r) for r in rows]


def search_by_tags(
    db: sqlite3.Connection, workspace_id: str, tags: list[str]
) -> list[Failure]:
    """Return failures matching ANY of the given tags (json_each full scan)."""
    results: list[Failure] = []
    seen_ids: set[int] = set()
    for tag in tags:
        rows = db.execute(
            """
            SELECT f.* FROM failures f, json_each(f.tags) t
            WHERE f.workspace_id IN (?, '__global__') AND t.value = ?
            """,
            (workspace_id, tag),
        ).fetchall()
        for row in rows:
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                results.append(_row_to_failure(row))
    return results


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def _row_to_decision(row: sqlite3.Row) -> Decision:
    return Decision(
        id=row["id"],
        workspace_id=row["workspace_id"],
        statement=row["statement"],
        rationale=row["rationale"],
        alternatives=json.loads(row["alternatives"] or "[]"),
        q=row["q"],
        status=row["status"],
        superseded_by=row["superseded_by"],
        tags=json.loads(row["tags"] or "[]"),
        last_used=_parse_dt(row["last_used"]),
        created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
        updated_at=_parse_dt(row["updated_at"]) or datetime.now(UTC),
    )


def insert_decision(db: sqlite3.Connection, decision: Decision) -> int:
    cur = db.execute(
        """
        INSERT INTO decisions
            (workspace_id, statement, rationale, alternatives, q,
             status, superseded_by, tags, last_used, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            decision.workspace_id,
            decision.statement,
            decision.rationale,
            json.dumps(decision.alternatives),
            decision.q,
            decision.status,
            decision.superseded_by,
            json.dumps(decision.tags),
            _dt_str(decision.last_used),
            _dt_str(decision.created_at),
            _dt_str(decision.updated_at),
        ),
    )
    db.commit()
    return cur.lastrowid


def get_decision_by_id(
    db: sqlite3.Connection, decision_id: int, workspace_id: str
) -> Decision | None:
    row = db.execute(
        "SELECT * FROM decisions WHERE id = ? AND workspace_id = ?",
        (decision_id, workspace_id),
    ).fetchone()
    return _row_to_decision(row) if row else None


def list_decisions(
    db: sqlite3.Connection, workspace_id: str, status: str = "active"
) -> list[Decision]:
    rows = db.execute(
        "SELECT * FROM decisions WHERE workspace_id = ? AND status = ? ORDER BY q DESC",
        (workspace_id, status),
    ).fetchall()
    return [_row_to_decision(r) for r in rows]


def update_decision(db: sqlite3.Connection, decision: Decision) -> None:
    db.execute(
        """
        UPDATE decisions SET
            statement = ?, rationale = ?, alternatives = ?, q = ?,
            status = ?, superseded_by = ?, tags = ?, last_used = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            decision.statement,
            decision.rationale,
            json.dumps(decision.alternatives),
            decision.q,
            decision.status,
            decision.superseded_by,
            json.dumps(decision.tags),
            _dt_str(decision.last_used),
            _dt_str(datetime.now(UTC)),
            decision.id,
        ),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

def _row_to_rule(row: sqlite3.Row) -> Rule:
    return Rule(
        id=row["id"],
        workspace_id=row["workspace_id"],
        rule_text=row["rule_text"],
        scope=row["scope"],
        enforcement_mode=row["enforcement_mode"],
        active=bool(row["active"]),
        created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
    )


def insert_rule(db: sqlite3.Connection, rule: Rule) -> int:
    cur = db.execute(
        """
        INSERT INTO rules
            (workspace_id, rule_text, scope, enforcement_mode, active, created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (
            rule.workspace_id,
            rule.rule_text,
            rule.scope,
            rule.enforcement_mode,
            int(rule.active),
            _dt_str(rule.created_at),
        ),
    )
    db.commit()
    return cur.lastrowid


def list_rules(db: sqlite3.Connection, workspace_id: str) -> list[Rule]:
    rows = db.execute(
        "SELECT * FROM rules WHERE workspace_id = ? AND active = 1 ORDER BY id",
        (workspace_id,),
    ).fetchall()
    return [_row_to_rule(r) for r in rows]


def update_rule(db: sqlite3.Connection, rule: Rule) -> None:
    db.execute(
        """
        UPDATE rules SET
            rule_text = ?, scope = ?, enforcement_mode = ?, active = ?
        WHERE id = ?
        """,
        (
            rule.rule_text,
            rule.scope,
            rule.enforcement_mode,
            int(rule.active),
            rule.id,
        ),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------

def _row_to_knowledge(row: sqlite3.Row) -> Knowledge:
    return Knowledge(
        id=row["id"],
        workspace_id=row["workspace_id"],
        title=row["title"],
        content=row["content"],
        source=row["source"],
        q=row["q"],
        tags=json.loads(row["tags"] or "[]"),
        promoted_from=row["promoted_from"],
        last_used=_parse_dt(row["last_used"]),
        created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
    )


def insert_knowledge(db: sqlite3.Connection, knowledge: Knowledge) -> int:
    cur = db.execute(
        """
        INSERT INTO knowledge
            (workspace_id, title, content, source, q,
             tags, promoted_from, last_used, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            knowledge.workspace_id,
            knowledge.title,
            knowledge.content,
            knowledge.source,
            knowledge.q,
            json.dumps(knowledge.tags),
            knowledge.promoted_from,
            _dt_str(knowledge.last_used),
            _dt_str(knowledge.created_at),
        ),
    )
    db.commit()
    return cur.lastrowid


def list_knowledge(
    db: sqlite3.Connection, workspace_id: str, include_global: bool = True
) -> list[Knowledge]:
    if include_global:
        rows = db.execute(
            "SELECT * FROM knowledge WHERE workspace_id IN (?, '__global__') ORDER BY q DESC",
            (workspace_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM knowledge WHERE workspace_id = ? ORDER BY q DESC",
            (workspace_id,),
        ).fetchall()
    return [_row_to_knowledge(r) for r in rows]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _row_to_session(row: sqlite3.Row) -> Session:
    keys = row.keys()
    return Session(
        id=row["id"],
        session_id=row["session_id"],
        workspace_id=row["workspace_id"],
        warnings_injected=json.loads(row["warnings_injected"] or "[]"),
        started_at=_parse_dt(row["started_at"]) or datetime.now(UTC),
        ended_at=_parse_dt(row["ended_at"]),
        failures_encountered=row["failures_encountered"] if "failures_encountered" in keys else 0,
        q_updates_count=row["q_updates_count"] if "q_updates_count" in keys else 0,
        promotions_count=row["promotions_count"] if "promotions_count" in keys else 0,
    )


def insert_session(db: sqlite3.Connection, session: Session) -> int:
    cur = db.execute(
        """
        INSERT INTO sessions
            (session_id, workspace_id, warnings_injected, started_at, ended_at,
             failures_encountered, q_updates_count, promotions_count)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            session.session_id,
            session.workspace_id,
            json.dumps(session.warnings_injected),
            _dt_str(session.started_at),
            _dt_str(session.ended_at),
            session.failures_encountered,
            session.q_updates_count,
            session.promotions_count,
        ),
    )
    db.commit()
    return cur.lastrowid


def get_session(db: sqlite3.Connection, session_id: str) -> Session | None:
    row = db.execute(
        "SELECT * FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return _row_to_session(row) if row else None


def update_session_end(db: sqlite3.Connection, session_id: str) -> None:
    db.execute(
        "UPDATE sessions SET ended_at = ? WHERE session_id = ?",
        (_dt_str(datetime.now(UTC)), session_id),
    )
    db.commit()


def update_session_metrics(
    db: sqlite3.Connection,
    session_id: str,
    failures_encountered: int,
    q_updates_count: int,
    promotions_count: int,
) -> None:
    db.execute(
        """
        UPDATE sessions SET
            ended_at = ?,
            failures_encountered = ?,
            q_updates_count = ?,
            promotions_count = ?
        WHERE session_id = ?
        """,
        (
            _dt_str(datetime.now(UTC)),
            failures_encountered,
            q_updates_count,
            promotions_count,
            session_id,
        ),
    )
    db.commit()
