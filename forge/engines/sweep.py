"""Parameter sweep and benchmarking infrastructure for Forge v6."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from forge.config import ForgeConfig
from forge.engines.fitness import compute_unified_fitness_v5
from forge.engines.metrics_v5 import (
    compute_agent_utilization,
    compute_circuit_efficiency,
    compute_context_hit_rate,
    compute_redundant_call_rate,
    compute_routing_accuracy,
    compute_stale_warning_rate,
    compute_tool_efficiency,
)
from forge.storage.db import _ensure_schema
from forge.storage.models import Failure
from forge.storage.queries import insert_failure


@dataclass
class SweepResult:
    """Result from a single parameter combination in a sweep."""

    config_snapshot: dict  # {param_name: value}
    unified_fitness: float
    individual_kpis: dict  # {kpi_name: value}
    param_str: str  # comma-separated param=value for display


def _compute_qwhr(db: sqlite3.Connection, workspace_id: str) -> float:
    """QWHR = Q-weighted helped/warned ratio."""
    row = db.execute(
        "SELECT q, times_helped, times_warned FROM failures WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()
    if not row:
        return 0.0
    total_q_weighted_helped = sum(r[0] * (r[1] / r[2]) for r in row if r[2] > 0)
    count = sum(1 for r in row if r[2] > 0)
    return total_q_weighted_helped / count if count > 0 else 0.0


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
    3. Compute all 8 KPIs from DB, then unified fitness
    4. Record results

    Returns:
        List of SweepResult sorted by unified_fitness (descending).
    """
    results: list[SweepResult] = []

    param_names = list(param_grid.keys())
    param_lists = [param_grid[name] for name in param_names]

    def _cartesian_product(lists: list[list]) -> list[list]:
        if not lists:
            return [[]]
        if len(lists) == 1:
            return [[v] for v in lists[0]]
        rest = _cartesian_product(lists[1:])
        return [[v] + combo for v in lists[0] for combo in rest]

    combinations = _cartesian_product(param_lists)

    for combo in combinations:
        config_dict = {param_names[i]: combo[i] for i in range(len(param_names))}
        config = _build_config_from_dict(config_dict)

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(db)

        _seed_test_data(db, workspace_id, n_failures, n_sessions, config)

        # Compute all 8 KPIs from DB
        qwhr = _compute_qwhr(db, workspace_id)
        routing_acc = compute_routing_accuracy(db, workspace_id)
        circuit_eff = compute_circuit_efficiency(db, workspace_id)
        agent_util = compute_agent_utilization(db, workspace_id)
        context_hr = compute_context_hit_rate(db, workspace_id)
        token_eff = compute_tool_efficiency(db, workspace_id)
        redundant = compute_redundant_call_rate(db, workspace_id)
        stale = compute_stale_warning_rate(db, workspace_id)

        kpis = {
            "qwhr": qwhr,
            "routing_accuracy": routing_acc,
            "circuit_efficiency": circuit_eff,
            "agent_utilization": agent_util,
            "context_hit_rate": context_hr,
            "token_efficiency": token_eff,
            "redundant_call_rate": redundant,
            "stale_warning_rate": stale,
        }

        unified_fitness = compute_unified_fitness_v5(
            qwhr=qwhr,
            routing_accuracy=routing_acc,
            circuit_efficiency=circuit_eff,
            agent_utilization=agent_util,
            context_hit_rate=context_hr,
            token_efficiency=token_eff,
            redundant_call_rate=redundant,
            stale_warning_rate=stale,
            config=config,
        )
        kpis["unified_fitness"] = unified_fitness

        param_str = ", ".join(f"{k}={v}" for k, v in config_dict.items())
        results.append(SweepResult(
            config_snapshot=config_dict,
            unified_fitness=unified_fitness,
            individual_kpis=kpis,
            param_str=param_str,
        ))

        db.close()

    results.sort(key=lambda r: r.unified_fitness, reverse=True)
    return results


def _build_config_from_dict(params: dict) -> ForgeConfig:
    """Build a ForgeConfig from a parameter dict."""
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
    config: ForgeConfig | None = None,
) -> None:
    """Seed in-memory DB with realistic test data for sweep evaluation.

    Creates failures, sessions, model_choices, agents, and breaker state
    so all 8 KPIs can be computed from the data.
    """
    # --- Failures ---
    for i in range(n_failures):
        q = 0.1 + (i / max(1, n_failures - 1)) * 0.8
        quality = ["near_miss", "preventable", "environmental"][i % 3]
        # Realistic: higher Q patterns get helped more
        times_warned = i + 1
        times_helped = max(0, int(q * times_warned * 0.7))

        failure = Failure(
            workspace_id=workspace_id,
            pattern=f"test_pattern_{i}",
            observed_error=f"Error {i}",
            likely_cause=f"Cause {i}",
            avoid_hint=f"Use check_{i}() to avoid error {i} in module_{i}",
            hint_quality=quality,
            q=q,
            times_seen=i + 1,
            times_helped=times_helped,
            times_warned=times_warned,
            tags=["test", f"category_{i % 3}"],
            projects_seen=[workspace_id],
            source="sweep",
        )
        insert_failure(db, failure)

    # --- Sessions ---
    for i in range(n_sessions):
        session_id = f"session_{i}"
        warnings = [f"test_pattern_{j}" for j in range(min(5, n_failures))]
        db.execute(
            "INSERT INTO sessions(session_id, workspace_id, warnings_injected, config_hash, document_hash) VALUES (?, ?, ?, ?, ?)",
            (session_id, workspace_id, json.dumps(warnings), f"hash_{i}", f"doc_{i}"),
        )

        # --- Breaker state per session ---
        # Some sessions have tool calls and occasional failures
        tool_calls = 20 + i * 5
        consecutive_failures = 1 if i % 3 == 0 else 0
        breaker_state = {
            "consecutive_failures": consecutive_failures,
            "tool_calls": tool_calls,
            "tripped": False,
        }
        db.execute(
            "INSERT OR REPLACE INTO forge_meta(key, value) VALUES (?, ?)",
            (f"breaker:{session_id}", json.dumps(breaker_state)),
        )

    # --- Model choices (for routing accuracy) ---
    models = ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4"]
    categories = ["quick", "standard", "deep"]
    for i in range(n_sessions * 3):
        cat = categories[i % 3]
        # Best model per category: haiku→quick, sonnet→standard, opus→deep
        best_idx = i % 3
        # 70% chance of picking the "best" model, 30% random
        if i % 10 < 7:
            model = models[best_idx]
            outcome = 0.8 + (i % 5) * 0.04
        else:
            model = models[(best_idx + 1) % 3]
            outcome = 0.4 + (i % 5) * 0.04
        db.execute(
            "INSERT INTO model_choices(workspace_id, session_id, task_category, selected_model, outcome) VALUES (?, ?, ?, ?, ?)",
            (workspace_id, f"session_{i % n_sessions}", cat, model, outcome),
        )

    # --- Agents (for agent utilization) ---
    statuses = ["completed", "completed", "completed", "error", "timed_out"]
    for i in range(n_sessions * 2):
        status = statuses[i % len(statuses)]
        db.execute(
            "INSERT INTO agents(workspace_id, session_id, agent_id, role, status) VALUES (?, ?, ?, ?, ?)",
            (workspace_id, f"session_{i % n_sessions}", f"agent_{i}", "worker", status),
        )

    db.commit()
