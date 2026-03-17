"""Recommend engine: team config recommendation based on past runs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from forge.storage.queries import list_team_runs


@dataclass
class Recommendation:
    config: str              # e.g. "sonnet:2+haiku:1"
    complexity: str          # SIMPLE | MEDIUM | COMPLEX
    runs: int                # number of runs with this config
    avg_success_rate: float  # average success rate
    avg_retry_rate: float | None
    confidence: str          # low | medium | high


def run_recommend(
    workspace_id: str,
    complexity: str,
    db: sqlite3.Connection,
) -> Recommendation | None:
    """Recommend best team config for given complexity based on past team runs.

    Returns None if no matching runs exist.
    """
    team_runs = list_team_runs(db, workspace_id, limit=100)
    matching = [
        tr for tr in team_runs
        if (tr.complexity or "").upper() == complexity.upper()
        and tr.success_rate is not None
    ]

    if not matching:
        return None

    # Group by team_config
    by_config: dict[str, list] = {}
    for tr in matching:
        key = tr.team_config or "unknown"
        by_config.setdefault(key, []).append(tr)

    # Rank by avg success_rate (primary), then run count as tiebreaker
    scored: list[tuple[float, int, str]] = []  # (avg_sr, run_count, config)
    for config, runs in by_config.items():
        sr_vals = [r.success_rate for r in runs if r.success_rate is not None]
        if not sr_vals:
            continue
        avg_sr = sum(sr_vals) / len(sr_vals)
        scored.append((avg_sr, len(runs), config))

    if not scored:
        return None

    # Sort: highest avg_sr first, then most runs, then config name for determinism
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    _, _, best_config = scored[0]

    runs_for_best = by_config[best_config]
    sr_vals = [r.success_rate for r in runs_for_best]
    rr_vals = [r.retry_rate for r in runs_for_best if r.retry_rate is not None]

    avg_sr = sum(sr_vals) / len(sr_vals)
    avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else None

    n = len(runs_for_best)
    if n >= 8:
        confidence = "high"
    elif n >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return Recommendation(
        config=best_config,
        complexity=complexity.upper(),
        runs=n,
        avg_success_rate=avg_sr,
        avg_retry_rate=avg_rr,
        confidence=confidence,
    )
