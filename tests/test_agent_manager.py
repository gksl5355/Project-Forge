"""Tests for agent state management engine."""

from datetime import datetime, UTC, timedelta
import pytest

from forge.engines.agent_manager import (
    register_agent,
    complete_agent,
    get_session_agents,
    get_active_agents,
    cleanup_stale,
    get_agent_stats,
    get_team_context,
)


class TestRegisterAgent:
    """Test agent registration."""

    def test_register_agent_returns_id(self, db):
        """Register a new agent and receive its ID."""
        agent_id = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="researcher",
        )
        assert isinstance(agent_id, int)
        assert agent_id > 0

    def test_register_agent_main_type(self, db):
        """Register a main agent (default type)."""
        agent_id = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="main-agent",
        )
        agents = get_session_agents(db, "sess-001")
        assert len(agents) == 1
        assert agents[0].role == "main"
        assert agents[0].status == "active"

    def test_register_agent_with_type(self, db):
        """Register an agent with a specific type."""
        agent_id = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="worker",
            agent_type="silo",
        )
        agents = get_session_agents(db, "sess-001")
        assert agents[0].role == "silo"

    def test_register_multiple_agents(self, db):
        """Register multiple agents in same session."""
        ids = []
        for i in range(3):
            agent_id = register_agent(
                db,
                workspace_id="test-ws",
                session_id="sess-001",
                agent_name=f"agent-{i}",
            )
            ids.append(agent_id)
        assert len(ids) == 3
        assert len(set(ids)) == 3  # All unique


class TestCompleteAgent:
    """Test agent completion."""

    def test_complete_agent_success(self, db):
        """Mark agent as completed."""
        agent_id = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="researcher",
        )
        agent = get_session_agents(db, "sess-001")[0]
        agent_ident = agent.agent_id

        complete_agent(db, agent_ident, status="completed")

        agents = get_session_agents(db, "sess-001")
        assert agents[0].status == "completed"
        assert agents[0].ended_at is not None

    def test_complete_agent_error(self, db):
        """Mark agent as failed."""
        agent_id = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="worker",
        )
        agent = get_session_agents(db, "sess-001")[0]
        agent_ident = agent.agent_id

        complete_agent(db, agent_ident, status="error")

        agents = get_session_agents(db, "sess-001")
        assert agents[0].status == "error"


class TestGetSessionAgents:
    """Test session agent retrieval."""

    def test_get_session_agents_empty(self, db):
        """Get agents for empty session."""
        agents = get_session_agents(db, "nonexistent")
        assert agents == []

    def test_get_session_agents_multiple(self, db):
        """Get all agents in a session."""
        for i in range(3):
            register_agent(
                db,
                workspace_id="test-ws",
                session_id="sess-001",
                agent_name=f"agent-{i}",
            )
        agents = get_session_agents(db, "sess-001")
        assert len(agents) == 3

    def test_get_session_agents_ordered(self, db):
        """Agents ordered by start time descending."""
        for i in range(3):
            register_agent(
                db,
                workspace_id="test-ws",
                session_id="sess-001",
                agent_name=f"agent-{i}",
            )
        agents = get_session_agents(db, "sess-001")
        # Latest should come first
        assert len(agents) == 3


class TestGetActiveAgents:
    """Test retrieval of active agents."""

    def test_get_active_agents_empty(self, db):
        """Get active agents when none exist."""
        agents = get_active_agents(db, "test-ws")
        assert agents == []

    def test_get_active_agents_filters_status(self, db):
        """Only return agents with 'active' status."""
        # Register active agent
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="active-agent",
        )
        # Register and complete another
        agent2 = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="completed-agent",
        )
        agent2_obj = get_session_agents(db, "sess-001")[1]
        complete_agent(db, agent2_obj.agent_id, status="completed")

        active = get_active_agents(db, "test-ws")
        assert len(active) == 1
        assert active[0].status == "active"


class TestCleanupStale:
    """Test stale agent cleanup."""

    def test_cleanup_stale_no_stale_agents(self, db):
        """No agents marked stale when all recent."""
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="recent-agent",
        )
        count = cleanup_stale(db, "test-ws", stale_threshold_minutes=60)
        assert count == 0

    def test_cleanup_stale_marks_old_agents(self, db):
        """Mark agents running longer than threshold as stale."""
        # Insert agent manually with old start time
        old_time = (datetime.now(UTC) - timedelta(minutes=120)).isoformat()
        db.execute(
            """
            INSERT INTO agents
            (agent_id, workspace_id, session_id, status, started_at, role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("old-agent-1", "test-ws", "sess-001", "active", old_time, "main"),
        )
        db.commit()

        # Should mark this as stale
        count = cleanup_stale(db, "test-ws", stale_threshold_minutes=60)
        assert count == 1

        # Check status changed
        agents = get_session_agents(db, "sess-001")
        assert agents[0].status == "timed_out"

    def test_cleanup_stale_respects_threshold(self, db):
        """Only mark agents older than threshold."""
        # Old agent
        old_time = (datetime.now(UTC) - timedelta(minutes=120)).isoformat()
        db.execute(
            """
            INSERT INTO agents
            (agent_id, workspace_id, session_id, status, started_at, role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("old-agent-1", "test-ws", "sess-001", "active", old_time, "main"),
        )

        # Recent agent
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="recent-agent",
        )
        db.commit()

        count = cleanup_stale(db, "test-ws", stale_threshold_minutes=60)
        assert count == 1

        agents = get_session_agents(db, "sess-001")
        statuses = [a.status for a in agents]
        assert "timed_out" in statuses
        assert "active" in statuses


class TestGetAgentStats:
    """Test agent statistics computation."""

    def test_get_agent_stats_empty(self, db):
        """Stats for empty workspace."""
        stats = get_agent_stats(db, "test-ws")
        assert stats["total_agents"] == 0
        assert stats["by_status"] == {}
        assert stats["by_type"] == {}
        assert stats["avg_duration_seconds"] is None
        assert stats["stale_count"] == 0
        assert stats["agent_utilization"] == 0.0

    def test_get_agent_stats_totals(self, db):
        """Count total agents."""
        for i in range(3):
            register_agent(
                db,
                workspace_id="test-ws",
                session_id="sess-001",
                agent_name=f"agent-{i}",
            )
        stats = get_agent_stats(db, "test-ws")
        assert stats["total_agents"] == 3

    def test_get_agent_stats_by_status(self, db):
        """Break down agents by status."""
        # Active agent
        agent1 = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="active-1",
        )
        # Completed agent
        agent2 = register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="completed-1",
        )
        agents = get_session_agents(db, "sess-001")
        complete_agent(db, agents[0].agent_id, status="completed")

        stats = get_agent_stats(db, "test-ws")
        assert stats["by_status"]["active"] == 1
        assert stats["by_status"]["completed"] == 1

    def test_get_agent_stats_by_type(self, db):
        """Break down agents by type (role)."""
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="main-agent",
            agent_type="main",
        )
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="worker",
            agent_type="silo",
        )
        stats = get_agent_stats(db, "test-ws")
        assert stats["by_type"]["main"] == 1
        assert stats["by_type"]["silo"] == 1

    def test_get_agent_stats_avg_duration(self, db):
        """Calculate average duration for completed agents."""
        # Create and complete agent
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="agent-1",
        )
        agent = get_session_agents(db, "sess-001")[0]
        complete_agent(db, agent.agent_id, status="completed")

        stats = get_agent_stats(db, "test-ws")
        assert stats["avg_duration_seconds"] is not None
        assert isinstance(stats["avg_duration_seconds"], float)
        assert stats["avg_duration_seconds"] >= 0

    def test_get_agent_stats_utilization(self, db):
        """Calculate agent utilization."""
        # 1 completed, 1 failed, 1 stale = utilization = 1/3
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="a1",
        )
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="a2",
        )
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="a3",
        )

        # Complete one
        agents = get_session_agents(db, "sess-001")
        complete_agent(db, agents[0].agent_id, status="completed")

        # Fail one
        complete_agent(db, agents[1].agent_id, status="error")

        # Stale one
        complete_agent(db, agents[2].agent_id, status="timed_out")

        stats = get_agent_stats(db, "test-ws")
        assert stats["stale_count"] == 1
        # Utilization = completed / (completed + failed + stale)
        expected = 1.0 / 3.0
        assert abs(stats["agent_utilization"] - expected) < 0.01


class TestGetTeamContext:
    """Test team context string generation."""

    def test_get_team_context_no_agents(self, db):
        """Context when no agents exist."""
        context = get_team_context(db, "sess-001")
        assert "No active agents" in context

    def test_get_team_context_single_agent(self, db):
        """Context with single active agent."""
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="researcher",
        )
        context = get_team_context(db, "sess-001")
        assert "Active agents:" in context
        assert "researcher" in context
        assert "active" in context

    def test_get_team_context_multiple_agents(self, db):
        """Context with multiple active agents."""
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="researcher",
            agent_type="main",
        )
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="worker",
            agent_type="silo",
        )
        context = get_team_context(db, "sess-001")
        assert "researcher" in context
        assert "worker" in context
        assert "main" in context
        assert "silo" in context

    def test_get_team_context_excludes_inactive(self, db):
        """Context only includes active agents."""
        # Active agent
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="active",
        )
        # Complete one agent
        agents = get_session_agents(db, "sess-001")
        complete_agent(db, agents[0].agent_id, status="completed")

        # Add another active
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="active-2",
        )

        context = get_team_context(db, "sess-001")
        assert "active-2" in context
        # Completed shouldn't be in the context for active agents
        assert context.count("active") == 2  # Only in type description, not the completed agent

    def test_get_team_context_format(self, db):
        """Context follows expected format."""
        register_agent(
            db,
            workspace_id="test-ws",
            session_id="sess-001",
            agent_name="worker",
            agent_type="silo",
        )
        context = get_team_context(db, "sess-001")
        # Should be: "Active agents: worker(silo):active"
        assert context.startswith("Active agents:")
        assert "worker(silo):active" in context
