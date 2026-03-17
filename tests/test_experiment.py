"""Tests for Experiment CRUD operations."""

from __future__ import annotations

import pytest

from forge.storage.models import Experiment
from forge.storage.queries import get_best_experiment, insert_experiment, list_experiments


class TestExperimentCRUD:
    def test_insert_and_list(self, db):
        exp = Experiment(
            workspace_id="test_ws",
            experiment_type="auto",
            config_snapshot='{"alpha": 0.1}',
            config_hash="abc123def456",
            document_hashes={"claude_md": "hash1"},
            document_hash="combined123",
            unified_fitness=0.75,
            qwhr=0.8,
            token_efficiency=0.005,
            promotion_precision=0.6,
        )
        eid = insert_experiment(db, exp)
        assert eid > 0

        experiments = list_experiments(db, "test_ws")
        assert len(experiments) == 1
        assert experiments[0].unified_fitness == pytest.approx(0.75)
        assert experiments[0].config_hash == "abc123def456"

    def test_list_ordering_by_recorded_at(self, db):
        for i in range(5):
            insert_experiment(db, Experiment(
                workspace_id="ws",
                config_snapshot="{}",
                config_hash=f"hash_{i}",
                document_hashes={},
                document_hash="doc",
                unified_fitness=i * 0.1,
            ))
        experiments = list_experiments(db, "ws", limit=3)
        assert len(experiments) == 3
        # Should be newest first
        assert experiments[0].config_hash == "hash_4"

    def test_list_ordering_by_fitness(self, db):
        for i in range(5):
            insert_experiment(db, Experiment(
                workspace_id="ws",
                config_snapshot="{}",
                config_hash=f"hash_{i}",
                document_hashes={},
                document_hash="doc",
                unified_fitness=i * 0.1,
            ))
        experiments = list_experiments(db, "ws", order_by="unified_fitness")
        assert experiments[0].unified_fitness >= experiments[-1].unified_fitness

    def test_get_best_experiment(self, db):
        insert_experiment(db, Experiment(
            workspace_id="ws",
            config_snapshot="{}",
            config_hash="low",
            document_hashes={},
            document_hash="doc",
            unified_fitness=0.3,
        ))
        insert_experiment(db, Experiment(
            workspace_id="ws",
            config_snapshot="{}",
            config_hash="high",
            document_hashes={},
            document_hash="doc",
            unified_fitness=0.9,
        ))
        best = get_best_experiment(db, "ws")
        assert best is not None
        assert best.config_hash == "high"
        assert best.unified_fitness == pytest.approx(0.9)

    def test_get_best_experiment_empty(self, db):
        best = get_best_experiment(db, "empty_ws")
        assert best is None

    def test_workspace_isolation(self, db):
        insert_experiment(db, Experiment(
            workspace_id="ws_a",
            config_snapshot="{}",
            config_hash="a",
            document_hashes={},
            document_hash="doc",
            unified_fitness=0.5,
        ))
        insert_experiment(db, Experiment(
            workspace_id="ws_b",
            config_snapshot="{}",
            config_hash="b",
            document_hashes={},
            document_hash="doc",
            unified_fitness=0.7,
        ))
        a_exps = list_experiments(db, "ws_a")
        assert len(a_exps) == 1
        assert a_exps[0].config_hash == "a"

    def test_document_hashes_roundtrip(self, db):
        doc_hashes = {"claude_md": "abc", "skill_md": "def", "config_yml": "ghi"}
        insert_experiment(db, Experiment(
            workspace_id="ws",
            config_snapshot="{}",
            config_hash="hash",
            document_hashes=doc_hashes,
            document_hash="combined",
            unified_fitness=0.5,
        ))
        experiments = list_experiments(db, "ws")
        assert experiments[0].document_hashes == doc_hashes

    def test_to_metrics_stored(self, db):
        insert_experiment(db, Experiment(
            workspace_id="ws",
            config_snapshot="{}",
            config_hash="hash",
            document_hashes={},
            document_hash="doc",
            unified_fitness=0.6,
            to_success_rate=0.85,
            to_retry_rate=0.15,
            to_scope_violations=2.0,
            sessions_evaluated=10,
            team_runs_evaluated=5,
        ))
        exp = list_experiments(db, "ws")[0]
        assert exp.to_success_rate == pytest.approx(0.85)
        assert exp.to_retry_rate == pytest.approx(0.15)
        assert exp.to_scope_violations == pytest.approx(2.0)
        assert exp.sessions_evaluated == 10
        assert exp.team_runs_evaluated == 5
