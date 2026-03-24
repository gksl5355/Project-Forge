"""Parameter sweep and benchmarking infrastructure for Forge v6."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, UTC

from forge.config import ForgeConfig
from forge.engines.fitness import compute_unified_fitness_v5
from forge.storage.db import _ensure_schema
from forge.storage.models import Failure
from forge.storage.queries import insert_failure, list_failures, list_rules


@dataclass
class SweepResult:
    """Result from a single parameter combination in a sweep."""

    config_snapshot: dict  # {param_name: value}
    unified_fitness: float
    individual_kpis: dict  # {kpi_name: value}
    param_str: str  # comma-separated param=value for display


def run_parameter_sweep(
    param_grid: dict[str, list],
    workspace_id: str = "sweep",
    n_failures: int = 20,
    n_sessions: int = 5,
) -> list[SweepResult]:
    """Run parameter sweep across a grid of values.

    For each combination of parameters:
    1. Create a ForgeConfig with those values
    2. Initialize an in-memory DB, seed with test data
    3. Run the fitness pipeline
    4. Record results

    Args:
        param_grid: {param_name: [value1, value2, ...]}
        workspace_id: workspace for test data (default: "sweep")
        n_failures: number of test failures to seed
        n_sessions: number of test sessions to simulate

    Returns:
        List of SweepResult sorted by unified_fitness (descending).
    """
    results: list[SweepResult] = []

    # Generate all combinations
    param_names = list(param_grid.keys())
    param_lists = [param_grid[name] for name in param_names]

    def _cartesian_product(lists: list[list]) -> list[list]:
        """Generate cartesian product of lists."""
        if not lists:
            return [[]]
        if len(lists) == 1:
            return [[v] for v in lists[0]]
        rest = _cartesian_product(lists[1:])
        return [[v] + combo for v in lists[0] for combo in rest]

    combinations = _cartesian_product(param_lists)

    for combo in combinations:
        # Build config with this combination
        config_dict = {param_names[i]: combo[i] for i in range(len(param_names))}
        config = _build_config_from_dict(config_dict)

        # Initialize in-memory DB
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(db)

        # Seed test data
        _seed_test_data(db, workspace_id, n_failures, n_sessions)

        # Compute fitness
        try:
            kpis = compute_unified_fitness_v5(db, workspace_id, config)
            unified_fitness = kpis.get("unified_fitness", 0.0)
        except Exception:
            # If fitness computation fails, use 0.0
            unified_fitness = 0.0
            kpis = {"unified_fitness": 0.0}

        # Record result
        param_str = ", ".join(f"{k}={v}" for k, v in config_dict.items())
        result = SweepResult(
            config_snapshot=config_dict,
            unified_fitness=unified_fitness,
            individual_kpis=kpis,
            param_str=param_str,
        )
        results.append(result)

        db.close()

    # Sort by unified_fitness descending
    results.sort(key=lambda r: r.unified_fitness, reverse=True)
    return results


def _build_config_from_dict(params: dict) -> ForgeConfig:
    """Build a ForgeConfig from a parameter dict.

    Only sets parameters that are valid ForgeConfig fields.
    """
    config = ForgeConfig()
    valid_fields = set(ForgeConfig.__dataclass_fields__.keys())
    for key, value in params.items():
        if key in valid_fields:
            setattr(config, key, value)
    return config


def _seed_test_data(
    db: sqlite3.Connection,
    workspace_id: str,
    n_failures: int,
    n_sessions: int,
) -> None:
    """Seed in-memory DB with test failures and sessions.

    Args:
        db: in-memory sqlite connection
        workspace_id: workspace ID
        n_failures: number of failures to create
        n_sessions: number of sessions to create
    """
    # Create test failures
    for i in range(n_failures):
        # Vary Q from 0.1 to 0.9
        q = 0.1 + (i / max(1, n_failures - 1)) * 0.8
        quality = ["near_miss", "preventable", "environmental"][i % 3]

        failure = Failure(
            workspace_id=workspace_id,
            pattern=f"test_pattern_{i}",
            observed_error=f"Error {i}",
            likely_cause=f"Cause {i}",
            avoid_hint=f"Use check_{i}() to avoid error {i}",
            hint_quality=quality,
            q=q,
            times_seen=i + 1,
            times_helped=max(0, i - 3),
            times_warned=i + 1,
            tags=["test", f"category_{i % 3}"],
            projects_seen=[workspace_id],
            source="sweep",
        )
        insert_failure(db, failure)

    # Create test sessions
    import json
    for i in range(n_sessions):
        session_id = f"session_{i}"
        # Simulate some warnings injected
        warnings = [f"test_pattern_{j}" for j in range(min(3, n_failures))]
        db.execute(
            """
            INSERT INTO sessions(session_id, workspace_id, warnings_injected, config_hash, document_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                workspace_id,
                json.dumps(warnings),
                f"hash_{i}",
                f"doc_hash_{i}",
            ),
        )

    db.commit()
