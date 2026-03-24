"""Agent lifecycle management engine."""

import json
import logging
import sqlite3
from datetime import datetime, UTC, timedelta

from forge.storage.models import Agent
from forge.storage.queries import insert_agent, update_agent_status, list_agents

logger = logging.getLogger("forge")


def register_agent(
    conn: sqlite3.Connection,
    workspace_id: str,
    session_id: str,
    agent_name: str,
    agent_type: str = "main",
    parent_agent_id: int | None = None,
    metadata: dict | None = None,
) -> int:
    """
    Register a new agent. Returns agent ID.

    Args:
        conn: SQLite connection
        workspace_id: Workspace identifier
        session_id: Current session identifier
        agent_name: Name/identifier for the agent
        agent_type: Type of agent (main, silo, background)
        parent_agent_id: ID of parent agent if spawned by another
        metadata: Optional metadata dict (will be JSON-serialized)

    Returns:
        Database ID of the newly registered agent
    """
    agent = Agent(
        agent_id=f"{workspace_id}:{session_id}:{agent_name}",
        workspace_id=workspace_id,
        session_id=session_id,
        team_name=None,
        role=agent_type,
        model=None,
        pane_id=f"pane_{agent_name}",
        pid=None,
        status="active",
    )
    agent_id = insert_agent(conn, agent)
    if agent_id is None:
        raise RuntimeError(f"Failed to register agent {agent_name}")
    return agent_id


def complete_agent(
    conn: sqlite3.Connection,
    agent_id: str,
    status: str = "completed",
) -> None:
    """
    Mark agent as completed or failed.

    Args:
        conn: SQLite connection
        agent_id: Agent identifier (agent_id field, not DB id)
        status: Final status (completed, timed_out, error)
    """
    update_agent_status(conn, agent_id, status, ended_at=datetime.now(UTC))


def get_session_agents(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[Agent]:
    """
    Get all agents for a session.

    Args:
        conn: SQLite connection
        session_id: Session identifier

    Returns:
        List of Agent objects in the session
    """
    try:
        rows = conn.execute(
            "SELECT * FROM agents WHERE session_id = ? ORDER BY started_at DESC",
            (session_id,),
        ).fetchall()
        agents = []
        for r in rows:
            agent = Agent(
                agent_id=r["agent_id"],
                workspace_id=r["workspace_id"],
                session_id=r["session_id"],
                team_name=r["team_name"],
                role=r["role"],
                model=r["model"],
                pane_id=r["pane_id"],
                pid=r["pid"],
                status=r["status"],
                started_at=_parse_dt(r["started_at"]),
                ended_at=_parse_dt(r["ended_at"]) if r["ended_at"] else None,
                id=r["id"],
            )
            agents.append(agent)
        return agents
    except sqlite3.OperationalError:
        return []


def get_active_agents(
    conn: sqlite3.Connection,
    workspace_id: str,
) -> list[Agent]:
    """
    Get all running agents in a workspace.

    Args:
        conn: SQLite connection
        workspace_id: Workspace identifier

    Returns:
        List of Agent objects with status='active'
    """
    return list_agents(conn, workspace_id, status="active")


def cleanup_stale(
    conn: sqlite3.Connection,
    workspace_id: str,
    stale_threshold_minutes: int = 60,
) -> int:
    """
    Mark agents as 'timed_out' if running for longer than threshold.

    Args:
        conn: SQLite connection
        workspace_id: Workspace identifier
        stale_threshold_minutes: Threshold in minutes (default 60)

    Returns:
        Count of agents marked as stale
    """
    threshold_dt = datetime.now(UTC) - timedelta(minutes=stale_threshold_minutes)
    threshold_str = threshold_dt.isoformat()

    cursor = conn.execute(
        """
        UPDATE agents
        SET status = 'timed_out', ended_at = ?
        WHERE workspace_id = ? AND status = 'active' AND started_at < ?
        """,
        (datetime.now(UTC).isoformat(), workspace_id, threshold_str),
    )
    conn.commit()
    return cursor.rowcount


def get_agent_stats(
    conn: sqlite3.Connection,
    workspace_id: str,
) -> dict:
    """
    Get agent statistics for a workspace.

    Args:
        conn: SQLite connection
        workspace_id: Workspace identifier

    Returns:
        Dictionary with keys:
        - total_agents: Total agent count
        - by_type: Dict of type -> count
        - by_status: Dict of status -> count
        - avg_duration_seconds: Average duration for completed agents
        - stale_count: Count of timed_out agents
        - agent_utilization: (completed / (completed + failed + stale))
    """
    try:
        # Total agents
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM agents WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        total_agents = total["cnt"] if total else 0

        # By status
        by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM agents WHERE workspace_id = ? GROUP BY status",
            (workspace_id,),
        ).fetchall():
            by_status[row["status"]] = row["cnt"]

        # By type (role)
        by_type = {}
        for row in conn.execute(
            "SELECT role, COUNT(*) as cnt FROM agents WHERE workspace_id = ? GROUP BY role",
            (workspace_id,),
        ).fetchall():
            by_type[row["role"] or "unknown"] = row["cnt"]

        # Average duration for completed agents
        avg_duration = None
        completed_row = conn.execute(
            """
            SELECT AVG(
                CAST((julianday(ended_at) - julianday(started_at)) * 86400 AS REAL)
            ) as avg_secs
            FROM agents
            WHERE workspace_id = ? AND status = 'completed' AND ended_at IS NOT NULL
            """,
            (workspace_id,),
        ).fetchone()
        if completed_row and completed_row["avg_secs"] is not None:
            avg_duration = round(completed_row["avg_secs"], 2)

        # Stale count
        stale_count = by_status.get("timed_out", 0)

        # Agent utilization
        completed_count = by_status.get("completed", 0)
        failed_count = by_status.get("error", 0)
        denominator = completed_count + failed_count + stale_count
        agent_utilization = (
            round(completed_count / denominator, 3)
            if denominator > 0
            else 0.0
        )

        return {
            "total_agents": total_agents,
            "by_status": by_status,
            "by_type": by_type,
            "avg_duration_seconds": avg_duration,
            "stale_count": stale_count,
            "agent_utilization": agent_utilization,
        }
    except sqlite3.OperationalError as e:
        logger.warning("Error computing agent stats: %s", e)
        return {
            "total_agents": 0,
            "by_status": {},
            "by_type": {},
            "avg_duration_seconds": None,
            "stale_count": 0,
            "agent_utilization": 0.0,
        }


def get_team_context(
    conn: sqlite3.Connection,
    session_id: str,
) -> str:
    """
    Generate team context string for resume injection.

    Shows active agents, their types, and status.
    Format: "Active agents: [name(type):status, ...]"

    Args:
        conn: SQLite connection
        session_id: Session identifier

    Returns:
        Context string describing active agents in the session
    """
    agents = get_session_agents(conn, session_id)
    if not agents:
        return "No active agents"

    active = [a for a in agents if a.status == "active"]
    if not active:
        return "No active agents"

    agent_strs = []
    for agent in active:
        agent_name = agent.agent_id.split(":")[-1] if agent.agent_id else "unknown"
        agent_type = agent.role or "main"
        agent_strs.append(f"{agent_name}({agent_type}):{agent.status}")

    return f"Active agents: {', '.join(agent_strs)}"


def _parse_dt(value: str | None) -> datetime | None:
    """Parse ISO format datetime string."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
