"""CRUD query functions for all Forge storage tables."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, UTC

from forge.storage.models import Agent, Decision, Experiment, Failure, Knowledge, ModelChoice, Rule, Session, TeamRun

logger = logging.getLogger("forge")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Failed to parse datetime: %s", value[:50] if value else "")
        return None


def _dt_str(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_json_loads(value: str | None, default: list | dict | None = None) -> list | dict:
    """json.loads with exception handling (v0 fix #1)."""
    if default is None:
        default = []
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse JSON: %s", value[:100] if value else "")
        return default


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------

def _row_to_failure(row: sqlite3.Row) -> Failure:
    keys = row.keys()
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
        tags=_safe_json_loads(row["tags"]),
        projects_seen=_safe_json_loads(row["projects_seen"]),
        source=row["source"],
        review_flag=bool(row["review_flag"]),
        active=bool(row["active"]) if "active" in keys else True,
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
             tags, projects_seen, source, review_flag, active, last_used,
             created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            int(failure.active),
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
    active_only: bool = True,
) -> list[Failure]:
    allowed_sort = {"q", "times_seen", "created_at", "updated_at", "last_used"}
    order_col = sort_by if sort_by in allowed_sort else "q"

    active_clause = " AND active = 1" if active_only else ""

    if include_global:
        rows = db.execute(
            f"SELECT * FROM failures WHERE workspace_id IN (?, '__global__'){active_clause} ORDER BY {order_col} DESC",
            (workspace_id,),
        ).fetchall()
    else:
        rows = db.execute(
            f"SELECT * FROM failures WHERE workspace_id = ?{active_clause} ORDER BY {order_col} DESC",
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
            review_flag = ?, active = ?, last_used = ?, updated_at = ?
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
            int(failure.active),
            _dt_str(failure.last_used),
            _dt_str(datetime.now(UTC)),
            failure.id,
        ),
    )
    db.commit()


def soft_delete_failure(db: sqlite3.Connection, failure_id: int) -> None:
    """Soft-delete a failure by setting active=0."""
    db.execute(
        "UPDATE failures SET active = 0, updated_at = ? WHERE id = ?",
        (_dt_str(datetime.now(UTC)), failure_id),
    )
    db.commit()


def list_flagged_failures(
    db: sqlite3.Connection, workspace_id: str
) -> list[Failure]:
    """review_flag=True인 실패 목록 반환."""
    rows = db.execute(
        "SELECT * FROM failures WHERE workspace_id = ? AND review_flag = 1 AND active = 1 ORDER BY q DESC",
        (workspace_id,),
    ).fetchall()
    return [_row_to_failure(r) for r in rows]


def search_by_tags(
    db: sqlite3.Connection, workspace_id: str, tags: list[str]
) -> list[Failure]:
    """Return failures matching ANY of the given tags (single query, v0 fix #2)."""
    if not tags:
        return []
    placeholders = ",".join("?" for _ in tags)
    rows = db.execute(
        f"""
        SELECT DISTINCT f.* FROM failures f, json_each(f.tags) t
        WHERE f.workspace_id IN (?, '__global__')
          AND f.active = 1
          AND t.value IN ({placeholders})
        ORDER BY f.q DESC
        """,
        (workspace_id, *tags),
    ).fetchall()
    return [_row_to_failure(r) for r in rows]


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def _row_to_decision(row: sqlite3.Row) -> Decision:
    return Decision(
        id=row["id"],
        workspace_id=row["workspace_id"],
        statement=row["statement"],
        rationale=row["rationale"],
        alternatives=_safe_json_loads(row["alternatives"]),
        q=row["q"],
        status=row["status"],
        superseded_by=row["superseded_by"],
        tags=_safe_json_loads(row["tags"]),
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


def get_rule_by_id(
    db: sqlite3.Connection, rule_id: int, workspace_id: str
) -> Rule | None:
    row = db.execute(
        "SELECT * FROM rules WHERE id = ? AND workspace_id = ?",
        (rule_id, workspace_id),
    ).fetchone()
    return _row_to_rule(row) if row else None


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
        tags=_safe_json_loads(row["tags"]),
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


def get_knowledge_by_id(
    db: sqlite3.Connection, knowledge_id: int, workspace_id: str
) -> Knowledge | None:
    row = db.execute(
        "SELECT * FROM knowledge WHERE id = ? AND workspace_id = ?",
        (knowledge_id, workspace_id),
    ).fetchone()
    return _row_to_knowledge(row) if row else None


def update_knowledge(db: sqlite3.Connection, knowledge: Knowledge) -> None:
    db.execute(
        """
        UPDATE knowledge SET
            title = ?, content = ?, q = ?, tags = ?, last_used = ?
        WHERE id = ?
        """,
        (
            knowledge.title,
            knowledge.content,
            knowledge.q,
            json.dumps(knowledge.tags),
            _dt_str(knowledge.last_used),
            knowledge.id,
        ),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _row_to_session(row: sqlite3.Row) -> Session:
    keys = row.keys()
    return Session(
        id=row["id"],
        session_id=row["session_id"],
        workspace_id=row["workspace_id"],
        warnings_injected=_safe_json_loads(row["warnings_injected"]),
        started_at=_parse_dt(row["started_at"]) or datetime.now(UTC),
        ended_at=_parse_dt(row["ended_at"]),
        failures_encountered=row["failures_encountered"] if "failures_encountered" in keys else 0,
        q_updates_count=row["q_updates_count"] if "q_updates_count" in keys else 0,
        promotions_count=row["promotions_count"] if "promotions_count" in keys else 0,
        config_hash=row["config_hash"] if "config_hash" in keys else None,
        document_hash=row["document_hash"] if "document_hash" in keys else None,
        unified_fitness=row["unified_fitness"] if "unified_fitness" in keys else None,
    )


def insert_session(db: sqlite3.Connection, session: Session) -> int:
    cur = db.execute(
        """
        INSERT INTO sessions
            (session_id, workspace_id, warnings_injected, started_at, ended_at,
             failures_encountered, q_updates_count, promotions_count,
             config_hash, document_hash, unified_fitness)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
            session.config_hash,
            session.document_hash,
            session.unified_fitness,
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


def list_sessions(
    db: sqlite3.Connection, workspace_id: str
) -> list[Session]:
    """List all sessions for a workspace, ordered by most recent first."""
    rows = db.execute(
        "SELECT * FROM sessions WHERE workspace_id = ? ORDER BY started_at DESC",
        (workspace_id,),
    ).fetchall()
    return [_row_to_session(r) for r in rows]


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


# ---------------------------------------------------------------------------
# TeamRun
# ---------------------------------------------------------------------------

def _row_to_team_run(row: sqlite3.Row) -> TeamRun:
    return TeamRun(
        id=row["id"],
        workspace_id=row["workspace_id"],
        run_id=row["run_id"],
        complexity=row["complexity"],
        team_config=row["team_config"],
        duration_min=row["duration_min"],
        success_rate=row["success_rate"],
        retry_rate=row["retry_rate"],
        scope_violations=row["scope_violations"],
        verdict=row["verdict"],
        agents=_safe_json_loads(row["agents"]),
        created_at=_parse_dt(row["created_at"]) or datetime.now(UTC),
    )


def insert_team_run(db: sqlite3.Connection, team_run: TeamRun) -> int:
    cur = db.execute(
        """
        INSERT INTO team_runs
            (workspace_id, run_id, complexity, team_config, duration_min,
             success_rate, retry_rate, scope_violations, verdict, agents, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            team_run.workspace_id,
            team_run.run_id,
            team_run.complexity,
            team_run.team_config,
            team_run.duration_min,
            team_run.success_rate,
            team_run.retry_rate,
            team_run.scope_violations,
            team_run.verdict,
            json.dumps(team_run.agents),
            _dt_str(team_run.created_at),
        ),
    )
    db.commit()
    return cur.lastrowid


def get_team_run(db: sqlite3.Connection, run_id: str) -> TeamRun | None:
    row = db.execute(
        "SELECT * FROM team_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return _row_to_team_run(row) if row else None


def list_team_runs(
    db: sqlite3.Connection, workspace_id: str, limit: int = 10
) -> list[TeamRun]:
    rows = db.execute(
        "SELECT * FROM team_runs WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
        (workspace_id, limit),
    ).fetchall()
    return [_row_to_team_run(r) for r in rows]


def update_team_run(db: sqlite3.Connection, team_run: TeamRun) -> None:
    db.execute(
        """
        UPDATE team_runs SET
            verdict = ?, success_rate = ?, retry_rate = ?,
            scope_violations = ?, agents = ?
        WHERE id = ?
        """,
        (
            team_run.verdict,
            team_run.success_rate,
            team_run.retry_rate,
            team_run.scope_violations,
            json.dumps(team_run.agents),
            team_run.id,
        ),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Forge Meta (key-value store for system metadata)
# ---------------------------------------------------------------------------

def get_meta(db: sqlite3.Connection, key: str) -> str | None:
    try:
        row = db.execute(
            "SELECT value FROM forge_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        """
        INSERT INTO forge_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, _dt_str(datetime.now(UTC))),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------

def _row_to_experiment(row: sqlite3.Row) -> Experiment:
    return Experiment(
        id=row["id"],
        workspace_id=row["workspace_id"],
        experiment_type=row["experiment_type"],
        config_snapshot=row["config_snapshot"],
        config_hash=row["config_hash"],
        document_hashes=_safe_json_loads(row["document_hashes"], default={}),
        document_hash=row["document_hash"],
        unified_fitness=row["unified_fitness"],
        qwhr=row["qwhr"],
        token_efficiency=row["token_efficiency"],
        promotion_precision=row["promotion_precision"],
        to_success_rate=row["to_success_rate"],
        to_retry_rate=row["to_retry_rate"],
        to_scope_violations=row["to_scope_violations"],
        sessions_evaluated=row["sessions_evaluated"],
        team_runs_evaluated=row["team_runs_evaluated"],
        notes=row["notes"],
        recorded_at=_parse_dt(row["recorded_at"]) or datetime.now(UTC),
    )


def insert_experiment(db: sqlite3.Connection, experiment: Experiment) -> int:
    cur = db.execute(
        """
        INSERT INTO experiments
            (workspace_id, experiment_type, config_snapshot, config_hash,
             document_hashes, document_hash, unified_fitness,
             qwhr, token_efficiency, promotion_precision,
             to_success_rate, to_retry_rate, to_scope_violations,
             sessions_evaluated, team_runs_evaluated, notes, recorded_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            experiment.workspace_id,
            experiment.experiment_type,
            experiment.config_snapshot,
            experiment.config_hash,
            json.dumps(experiment.document_hashes),
            experiment.document_hash,
            experiment.unified_fitness,
            experiment.qwhr,
            experiment.token_efficiency,
            experiment.promotion_precision,
            experiment.to_success_rate,
            experiment.to_retry_rate,
            experiment.to_scope_violations,
            experiment.sessions_evaluated,
            experiment.team_runs_evaluated,
            experiment.notes,
            _dt_str(experiment.recorded_at),
        ),
    )
    db.commit()
    return cur.lastrowid


def list_experiments(
    db: sqlite3.Connection,
    workspace_id: str,
    limit: int = 20,
    order_by: str = "recorded_at",
) -> list[Experiment]:
    allowed_order = {"recorded_at", "unified_fitness"}
    col = order_by if order_by in allowed_order else "recorded_at"
    rows = db.execute(
        f"SELECT * FROM experiments WHERE workspace_id = ? ORDER BY {col} DESC LIMIT ?",
        (workspace_id, limit),
    ).fetchall()
    return [_row_to_experiment(r) for r in rows]


def get_best_experiment(
    db: sqlite3.Connection, workspace_id: str
) -> Experiment | None:
    row = db.execute(
        "SELECT * FROM experiments WHERE workspace_id = ? ORDER BY unified_fitness DESC LIMIT 1",
        (workspace_id,),
    ).fetchone()
    return _row_to_experiment(row) if row else None


# ---------------------------------------------------------------------------
# v5: Agent management
# ---------------------------------------------------------------------------

def insert_agent(db: sqlite3.Connection, agent: "Agent") -> int | None:
    """Register agent. Ignore if agent_id already exists (dedup)."""
    from forge.storage.models import Agent as _A  # noqa: F811
    try:
        cur = db.execute(
            """INSERT OR IGNORE INTO agents
               (agent_id, workspace_id, session_id, team_name, role, model, pane_id, pid, status, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent.agent_id, agent.workspace_id, agent.session_id,
             agent.team_name, agent.role, agent.model,
             agent.pane_id, agent.pid, agent.status, _dt_str(agent.started_at)),
        )
        db.commit()
        return cur.lastrowid if cur.rowcount > 0 else None
    except sqlite3.OperationalError:
        return None


def update_agent_status(
    db: sqlite3.Connection, agent_id: str, status: str, ended_at: datetime | None = None
) -> None:
    """Update agent status (completed/timed_out/error)."""
    from datetime import datetime, UTC
    end = _dt_str(ended_at) if ended_at else _dt_str(datetime.now(UTC))
    db.execute(
        "UPDATE agents SET status = ?, ended_at = ? WHERE agent_id = ?",
        (status, end, agent_id),
    )
    db.commit()


def list_agents(
    db: sqlite3.Connection, workspace_id: str, team_name: str | None = None, status: str | None = None
) -> list["Agent"]:
    """List agents, optionally filtered by team and/or status."""
    from forge.storage.models import Agent
    sql = "SELECT * FROM agents WHERE workspace_id = ?"
    params: list = [workspace_id]
    if team_name:
        sql += " AND team_name = ?"
        params.append(team_name)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY started_at DESC"
    try:
        rows = db.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        Agent(
            agent_id=r["agent_id"], workspace_id=r["workspace_id"],
            session_id=r["session_id"], team_name=r["team_name"],
            role=r["role"], model=r["model"], pane_id=r["pane_id"],
            pid=r["pid"], status=r["status"],
            started_at=_parse_dt(r["started_at"]),
            ended_at=_parse_dt(r["ended_at"]) if r["ended_at"] else None,
            id=r["id"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# v5: Model routing choices
# ---------------------------------------------------------------------------

def insert_model_choice(
    db: sqlite3.Connection,
    workspace_id: str, session_id: str, task_category: str,
    selected_model: str, agent_name: str | None = None,
) -> int | None:
    """Record a model routing choice."""
    try:
        cur = db.execute(
            """INSERT INTO model_choices
               (workspace_id, session_id, agent_name, task_category, selected_model)
               VALUES (?, ?, ?, ?, ?)""",
            (workspace_id, session_id, agent_name, task_category, selected_model),
        )
        db.commit()
        return cur.lastrowid
    except sqlite3.OperationalError:
        return None


def update_model_choice_outcome(
    db: sqlite3.Connection, choice_id: int, outcome: float
) -> None:
    """Update outcome (0.0-1.0) for a model choice after session completes."""
    db.execute("UPDATE model_choices SET outcome = ? WHERE id = ?", (outcome, choice_id))
    db.commit()


def get_model_success_rates(
    db: sqlite3.Connection, workspace_id: str, task_category: str
) -> list[tuple[str, float, int]]:
    """Get (model, avg_outcome, count) for a category, ordered by success rate."""
    try:
        rows = db.execute(
            """SELECT selected_model, AVG(outcome) as avg_outcome, COUNT(*) as cnt
               FROM model_choices
               WHERE workspace_id = ? AND task_category = ? AND outcome IS NOT NULL
               GROUP BY selected_model
               ORDER BY avg_outcome DESC""",
            (workspace_id, task_category),
        ).fetchall()
        return [(r["selected_model"], r["avg_outcome"], r["cnt"]) for r in rows]
    except sqlite3.OperationalError:
        return []
