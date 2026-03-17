"""E2E pipeline tests: experiment tracking through the full flow."""

from __future__ import annotations

import json

import pytest

from forge.config import ForgeConfig
from forge.core.hashing import compute_combined_doc_hash, compute_config_hash, compute_doc_hashes
from forge.engines.fitness import compute_unified_fitness
from forge.engines.measure import run_measure
from forge.storage.models import Experiment, Failure, Session, TeamRun
from forge.storage.queries import (
    get_best_experiment,
    insert_experiment,
    insert_failure,
    insert_session,
    insert_team_run,
    list_experiments,
)


class TestE2EPipeline:
    """Test the full pipeline: data -> measure -> experiment -> trend."""

    def _seed_data(self, db, workspace: str = "e2e_ws"):
        """Seed database with realistic test data."""
        # Failures
        insert_failure(db, Failure(
            workspace_id=workspace, pattern="import_error",
            avoid_hint="Install missing package", hint_quality="preventable",
            q=0.7, times_seen=5, times_helped=3, times_warned=4,
        ))
        insert_failure(db, Failure(
            workspace_id=workspace, pattern="type_error",
            avoid_hint="Check type annotations", hint_quality="near_miss",
            q=0.8, times_seen=3, times_helped=2, times_warned=3,
        ))
        # Session
        insert_session(db, Session(
            session_id="e2e-session-1", workspace_id=workspace,
        ))
        # Team runs
        insert_team_run(db, TeamRun(
            workspace_id=workspace, run_id="e2e-run-1",
            complexity="MEDIUM", team_config="sonnet:2+haiku:1",
            success_rate=0.85, retry_rate=0.1, scope_violations=1,
        ))

    def test_measure_produces_unified_fitness(self, db):
        self._seed_data(db)
        config = ForgeConfig()
        result = run_measure("e2e_ws", db, config)
        assert result.unified_fitness > 0
        assert result.qwhr > 0

    def test_experiment_recording(self, db):
        self._seed_data(db)
        config = ForgeConfig()

        # Measure
        result = run_measure("e2e_ws", db, config)

        # Record experiment
        config_hash = compute_config_hash(config)
        doc_hash = compute_combined_doc_hash({})

        exp = Experiment(
            workspace_id="e2e_ws",
            experiment_type="auto",
            config_snapshot=json.dumps({"alpha": config.alpha}),
            config_hash=config_hash,
            document_hashes={},
            document_hash=doc_hash,
            unified_fitness=result.unified_fitness,
            qwhr=result.qwhr,
            promotion_precision=result.promotion_precision,
            sessions_evaluated=result.total_sessions,
            team_runs_evaluated=result.to_total_runs,
        )
        eid = insert_experiment(db, exp)
        assert eid > 0

        # Verify retrieval
        best = get_best_experiment(db, "e2e_ws")
        assert best is not None
        assert best.unified_fitness == result.unified_fitness

    def test_multiple_experiments_trend(self, db):
        """Record multiple experiments and verify ordering."""
        self._seed_data(db)

        for i in range(5):
            insert_experiment(db, Experiment(
                workspace_id="e2e_ws",
                config_snapshot=json.dumps({"round": i}),
                config_hash=f"hash_{i:03d}",
                document_hashes={},
                document_hash="doc_hash",
                unified_fitness=0.5 + i * 0.05,
            ))

        experiments = list_experiments(db, "e2e_ws", limit=10)
        assert len(experiments) == 5
        # Best should have highest fitness
        best = get_best_experiment(db, "e2e_ws")
        assert best.unified_fitness == pytest.approx(0.7)

    def test_config_hash_consistency(self):
        config = ForgeConfig()
        h1 = compute_config_hash(config)
        h2 = compute_config_hash(config)
        assert h1 == h2
        assert len(h1) == 12

    def test_unified_fitness_with_to_data(self, db):
        """Unified fitness correctly includes TO metrics when available."""
        self._seed_data(db)
        config = ForgeConfig()
        result = run_measure("e2e_ws", db, config)

        # Should include TO data (we seeded a team run)
        assert result.to_total_runs > 0
        assert result.unified_fitness > 0

        # Manual calculation should match
        token_eff = result.helped_per_1k_tokens / 1000.0 if result.helped_per_1k_tokens > 0 else 0.0
        expected = compute_unified_fitness(
            qwhr=result.qwhr,
            token_efficiency=token_eff,
            promotion_precision=result.promotion_precision,
            to_success_rate=result.to_avg_success_rate,
            to_retry_rate=result.to_avg_retry_rate,
            to_scope_violations=result.to_avg_scope_violations,
            to_run_count=result.to_total_runs,
        )
        assert result.unified_fitness == pytest.approx(expected)
