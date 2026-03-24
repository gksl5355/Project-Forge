"""Tests for category-based model routing engine."""

import pytest
import sqlite3

from forge.config import ForgeConfig
from forge.engines.routing import (
    parse_model_map,
    resolve_model,
    record_choice,
    record_outcome,
    get_routing_stats,
)


class TestParseModelMap:
    """Test parse_model_map function."""

    def test_parse_model_map_normal(self) -> None:
        """Test parsing a normal model map string."""
        result = parse_model_map("quick=claude-haiku-4-5,standard=claude-sonnet-4-6")
        assert result == {
            "quick": "claude-haiku-4-5",
            "standard": "claude-sonnet-4-6",
        }

    def test_parse_model_map_empty_string(self) -> None:
        """Test parsing empty string returns empty dict."""
        result = parse_model_map("")
        assert result == {}

    def test_parse_model_map_whitespace(self) -> None:
        """Test parsing whitespace-only string returns empty dict."""
        result = parse_model_map("   ")
        assert result == {}

    def test_parse_model_map_with_spaces(self) -> None:
        """Test parsing with spaces around delimiters."""
        result = parse_model_map(" quick = claude-haiku , standard = claude-sonnet ")
        assert result == {
            "quick": "claude-haiku",
            "standard": "claude-sonnet",
        }

    def test_parse_model_map_invalid_pair(self) -> None:
        """Test parsing with invalid pairs (no =) are skipped."""
        result = parse_model_map("quick=haiku,invalid_pair,standard=sonnet")
        assert result == {
            "quick": "haiku",
            "standard": "sonnet",
        }

    def test_parse_model_map_multiple_equals(self) -> None:
        """Test parsing with multiple = in a pair (split on first =)."""
        result = parse_model_map("key=value=extra")
        assert result == {"key": "value=extra"}


class TestResolveModelDefault:
    """Test resolve_model with routing disabled."""

    def test_resolve_model_routing_disabled(self, db: sqlite3.Connection) -> None:
        """When routing disabled, return config.llm_model."""
        config = ForgeConfig(routing_enabled=False, llm_model="test-model-default")
        model = resolve_model("ws1", "quick", config=config)
        assert model == "test-model-default"


class TestResolveModelFromMap:
    """Test resolve_model from model_map."""

    def test_resolve_model_from_map(self, db: sqlite3.Connection) -> None:
        """When no DB data, use model_map default."""
        config = ForgeConfig(
            routing_enabled=True,
            routing_model_map_str="quick=haiku,standard=sonnet,deep=opus",
            llm_model="claude-sonnet-4-6",  # default fallback
        )
        model = resolve_model("ws1", "quick", config=config)
        assert model == "haiku"

        model = resolve_model("ws1", "standard", config=config)
        assert model == "sonnet"

        model = resolve_model("ws1", "deep", config=config)
        assert model == "opus"

    def test_resolve_model_unknown_category(self, db: sqlite3.Connection) -> None:
        """Unknown category uses config.llm_model fallback."""
        config = ForgeConfig(
            routing_enabled=True,
            routing_model_map_str="quick=haiku",
            llm_model="sonnet-default",
        )
        model = resolve_model("ws1", "unknown", config=config)
        assert model == "sonnet-default"


class TestResolveModelFromStats:
    """Test resolve_model using success rates from DB."""

    def test_resolve_model_with_success_rates(self, db: sqlite3.Connection) -> None:
        """With sufficient data, pick best performing model."""
        config = ForgeConfig(
            routing_enabled=True,
            routing_model_map_str="quick=haiku",
            llm_model="default",
        )

        # Insert 5+ choices for haiku with high success rate
        for i in range(5):
            db.execute(
                """INSERT INTO model_choices
                   (workspace_id, session_id, task_category, selected_model, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws1", f"session{i}", "quick", "haiku", 0.9),
            )
        db.commit()

        # Insert 3 choices for sonnet with lower success rate (not enough for selection)
        for i in range(3):
            db.execute(
                """INSERT INTO model_choices
                   (workspace_id, session_id, task_category, selected_model, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws1", f"session{i+10}", "quick", "sonnet", 0.5),
            )
        db.commit()

        model = resolve_model("ws1", "quick", config=config, db=db)
        assert model == "haiku"

    def test_resolve_model_fallback_when_insufficient_data(self, db: sqlite3.Connection) -> None:
        """With < 5 choices, fall back to model_map."""
        config = ForgeConfig(
            routing_enabled=True,
            routing_model_map_str="quick=haiku,standard=sonnet",
            llm_model="default",
        )

        # Insert only 3 choices (< 5)
        for i in range(3):
            db.execute(
                """INSERT INTO model_choices
                   (workspace_id, session_id, task_category, selected_model, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws1", f"session{i}", "quick", "sonnet", 0.7),
            )
        db.commit()

        model = resolve_model("ws1", "quick", config=config, db=db)
        # Should fall back to model_map default
        assert model == "haiku"


class TestRecordAndOutcome:
    """Test record_choice and record_outcome."""

    def test_record_and_outcome(self, db: sqlite3.Connection) -> None:
        """Record choice and update outcome."""
        # Record a choice
        choice_id = record_choice("ws1", "session1", "quick", "haiku", db=db)
        assert choice_id is not None
        assert isinstance(choice_id, int)

        # Verify it was inserted
        row = db.execute(
            "SELECT * FROM model_choices WHERE id = ?", (choice_id,)
        ).fetchone()
        assert row is not None
        assert row["workspace_id"] == "ws1"
        assert row["session_id"] == "session1"
        assert row["task_category"] == "quick"
        assert row["selected_model"] == "haiku"
        assert row["outcome"] is None

        # Record outcome
        record_outcome(choice_id, 0.85, db=db)

        # Verify outcome was updated
        row = db.execute(
            "SELECT * FROM model_choices WHERE id = ?", (choice_id,)
        ).fetchone()
        assert row["outcome"] == 0.85

    def test_record_outcome_clamping(self, db: sqlite3.Connection) -> None:
        """Test that outcome is clamped to [0.0, 1.0]."""
        choice_id = record_choice("ws1", "session1", "quick", "haiku", db=db)

        # Record outcome > 1.0 (should clamp)
        record_outcome(choice_id, 1.5, db=db)
        row = db.execute(
            "SELECT outcome FROM model_choices WHERE id = ?", (choice_id,)
        ).fetchone()
        assert row["outcome"] == 1.0

        # Record outcome < 0.0 (should clamp)
        record_outcome(choice_id, -0.5, db=db)
        row = db.execute(
            "SELECT outcome FROM model_choices WHERE id = ?", (choice_id,)
        ).fetchone()
        assert row["outcome"] == 0.0

    def test_record_outcome_with_none_choice_id(self, db: sqlite3.Connection) -> None:
        """Test that record_outcome handles None choice_id gracefully."""
        # Should not raise, just log warning
        record_outcome(None, 0.5, db=db)  # type: ignore


class TestGetRoutingStats:
    """Test get_routing_stats function."""

    def test_get_routing_stats_empty(self, db: sqlite3.Connection) -> None:
        """Test stats with no data."""
        stats = get_routing_stats("ws1", db=db)
        assert stats["total_choices"] == 0
        assert stats["categories"] == {}

    def test_get_routing_stats_multiple_categories(self, db: sqlite3.Connection) -> None:
        """Test stats with multiple categories."""
        # Insert choices for multiple categories
        for i in range(5):
            db.execute(
                """INSERT INTO model_choices
                   (workspace_id, session_id, task_category, selected_model, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws1", f"session{i}", "quick", "haiku", 0.9),
            )
            db.execute(
                """INSERT INTO model_choices
                   (workspace_id, session_id, task_category, selected_model, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws1", f"session{i}", "standard", "sonnet", 0.8),
            )
        db.commit()

        stats = get_routing_stats("ws1", db=db)
        assert stats["total_choices"] == 10
        assert "quick" in stats["categories"]
        assert "standard" in stats["categories"]

        # Check quick category
        quick_stats = stats["categories"]["quick"]
        assert quick_stats["best_model"] == "haiku"
        assert quick_stats["best_outcome"] == 0.9
        assert quick_stats["total_choices"] == 5

        # Check standard category
        standard_stats = stats["categories"]["standard"]
        assert standard_stats["best_model"] == "sonnet"
        assert standard_stats["best_outcome"] == 0.8
        assert standard_stats["total_choices"] == 5

    def test_get_routing_stats_multiple_models_per_category(
        self, db: sqlite3.Connection
    ) -> None:
        """Test stats when multiple models are tried for same category."""
        # Insert choices for haiku (avg 0.9)
        for i in range(5):
            db.execute(
                """INSERT INTO model_choices
                   (workspace_id, session_id, task_category, selected_model, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws1", f"session{i}", "quick", "haiku", 0.9),
            )

        # Insert choices for sonnet (avg 0.7)
        for i in range(5):
            db.execute(
                """INSERT INTO model_choices
                   (workspace_id, session_id, task_category, selected_model, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                ("ws1", f"session{i+10}", "quick", "sonnet", 0.7),
            )
        db.commit()

        stats = get_routing_stats("ws1", db=db)
        quick_stats = stats["categories"]["quick"]
        assert quick_stats["best_model"] == "haiku"
        assert quick_stats["best_outcome"] == 0.9
        assert len(quick_stats["models"]) == 2
        # haiku should come first (higher avg_outcome)
        assert quick_stats["models"][0]["model"] == "haiku"
        assert quick_stats["models"][1]["model"] == "sonnet"
