"""AutoResearch v2 — v5 KPI-based parameter optimization."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field

from forge.config import ForgeConfig, load_config

logger = logging.getLogger("forge")

# ---------------------------------------------------------------------------
# Optional imports with graceful fallback
# ---------------------------------------------------------------------------

try:
    from forge.engines.fitness import compute_unified_fitness as _compute_unified_fitness
except ImportError:  # pragma: no cover
    def _compute_unified_fitness(  # type: ignore[misc]
        qwhr: float, token_efficiency: float, promotion_precision: float, **kwargs: object
    ) -> float:
        return 0.6 * qwhr + 0.25 * min(1.0, token_efficiency * 100) + 0.15 * promotion_precision

try:
    from forge.core.circuit_breaker import get_breaker_stats as _get_breaker_stats
except ImportError:  # pragma: no cover
    def _get_breaker_stats(  # type: ignore[misc]
        conn: sqlite3.Connection, workspace_id: str | None = None
    ) -> dict:
        return {
            "total_sessions": 0, "total_breaks": 0,
            "break_rate_percent": 0.0, "avg_tool_calls_per_session": 0.0,
            "common_trip_reasons": [],
        }

try:
    from forge.storage.queries import get_model_success_rates as _get_model_success_rates
except ImportError:  # pragma: no cover
    def _get_model_success_rates(  # type: ignore[misc]
        conn: sqlite3.Connection, workspace_id: str, task_category: str
    ) -> list[tuple[str, float, int]]:
        return []

try:
    from forge.engines.routing import parse_model_map as _parse_model_map
except ImportError:  # pragma: no cover
    def _parse_model_map(map_str: str) -> dict[str, str]:  # type: ignore[misc]
        result: dict[str, str] = {}
        for pair in map_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                result[k.strip()] = v.strip()
        return result


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ResearchResult:
    best_config: dict[str, object]
    improvements: list[dict]
    unified_fitness_before: float
    unified_fitness_after: float
    sweep_log: list[dict] = field(default_factory=list)


@dataclass
class PromptResearchResult:
    best_format: str
    format_stats: dict[str, dict]
    low_quality_hints_count: int
    hint_quality_distribution: dict[str, int]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_baseline_fitness(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Estimate baseline fitness from recent sessions with recorded unified_fitness."""
    try:
        rows = conn.execute(
            """SELECT unified_fitness FROM sessions
               WHERE workspace_id = ? AND unified_fitness IS NOT NULL
               ORDER BY started_at DESC LIMIT 10""",
            (workspace_id,),
        ).fetchall()
        if not rows:
            return 0.0
        return sum(r[0] for r in rows) / len(rows)
    except sqlite3.OperationalError:
        return 0.0


def _get_context_hit_rate(conn: sqlite3.Connection, workspace_id: str) -> float | None:
    """Estimate context hit rate: sessions with q_updates / sessions with warnings."""
    try:
        row = conn.execute(
            """SELECT
                   COUNT(*) as total,
                   COALESCE(SUM(CASE WHEN q_updates_count > 0 THEN 1 ELSE 0 END), 0) as hits
               FROM sessions
               WHERE workspace_id = ?
                 AND warnings_injected IS NOT NULL
                 AND warnings_injected != '[]'""",
            (workspace_id,),
        ).fetchone()
        if row is None or row[0] == 0:
            return None
        return row[1] / row[0]
    except sqlite3.OperationalError:
        return None


def _get_stale_warning_rate(conn: sqlite3.Connection, workspace_id: str) -> float | None:
    """Fraction of warned failures with low help rate (< 0.3)."""
    try:
        row = conn.execute(
            """SELECT
                   COUNT(*) as total,
                   COALESCE(SUM(CASE WHEN CAST(times_helped AS REAL) / times_warned < 0.3
                                    THEN 1 ELSE 0 END), 0) as stale
               FROM failures
               WHERE workspace_id = ? AND times_warned > 0""",
            (workspace_id,),
        ).fetchone()
        if row is None or row[0] == 0:
            return None
        return row[1] / row[0]
    except sqlite3.OperationalError:
        return None


# ---------------------------------------------------------------------------
# Optimization sub-functions
# ---------------------------------------------------------------------------

def _optimize_routing(
    conn: sqlite3.Connection, workspace_id: str, config: ForgeConfig
) -> list[dict]:
    """Analyze model_choices, return suggestions for routing_model_map_str."""
    improvements: list[dict] = []

    try:
        current_map = _parse_model_map(config.routing_model_map_str)
    except Exception:
        return improvements

    new_map = dict(current_map)
    map_changed = False

    for category, current_model in current_map.items():
        try:
            rates = _get_model_success_rates(conn, workspace_id, category)
        except Exception:
            continue

        if not rates:
            continue

        best_model: str | None = None
        best_rate: float = 0.0
        current_rate: float = 0.0

        for model, avg_outcome, count in rates:
            if count >= 5:
                if avg_outcome > best_rate:
                    best_rate = avg_outcome
                    best_model = model
                if model == current_model:
                    current_rate = avg_outcome

        if best_model and best_model != current_model and best_rate > current_rate + 0.05:
            new_map[category] = best_model
            map_changed = True
            improvements.append({
                "parameter": f"routing:{category}",
                "old": current_model,
                "new": best_model,
                "expected_gain": round((best_rate - current_rate) * 0.1, 4),
            })

    if map_changed:
        new_map_str = ",".join(f"{k}={v}" for k, v in new_map.items())
        improvements.append({
            "parameter": "routing_model_map_str",
            "old": config.routing_model_map_str,
            "new": new_map_str,
            "expected_gain": 0.0,
        })

    return improvements


def _optimize_breaker(
    conn: sqlite3.Connection, workspace_id: str, config: ForgeConfig
) -> list[dict]:
    """Analyze breaker stats, return threshold suggestions."""
    improvements: list[dict] = []

    try:
        stats = _get_breaker_stats(conn, workspace_id)
    except Exception:
        return improvements

    if stats.get("total_sessions", 0) == 0:
        return improvements

    break_rate = stats.get("break_rate_percent", 0.0)
    avg_tool_calls = stats.get("avg_tool_calls_per_session", 0.0)

    # max_consecutive_failures tuning
    if break_rate > 20.0:
        new_val = min(config.max_consecutive_failures + 3, 20)
        if new_val != config.max_consecutive_failures:
            improvements.append({
                "parameter": "max_consecutive_failures",
                "old": config.max_consecutive_failures,
                "new": new_val,
                "expected_gain": 0.02,
            })
    elif break_rate < 1.0 and config.max_consecutive_failures > 3:
        new_val = max(config.max_consecutive_failures - 2, 3)
        if new_val != config.max_consecutive_failures:
            improvements.append({
                "parameter": "max_consecutive_failures",
                "old": config.max_consecutive_failures,
                "new": new_val,
                "expected_gain": 0.01,
            })

    # max_tool_calls_per_session tuning
    if avg_tool_calls > 0:
        if avg_tool_calls > 0.8 * config.max_tool_calls_per_session:
            new_val = min(int(config.max_tool_calls_per_session * 1.5), 500)
            if new_val != config.max_tool_calls_per_session:
                improvements.append({
                    "parameter": "max_tool_calls_per_session",
                    "old": config.max_tool_calls_per_session,
                    "new": new_val,
                    "expected_gain": 0.015,
                })
        elif (
            avg_tool_calls < 0.2 * config.max_tool_calls_per_session
            and config.max_tool_calls_per_session > 100
        ):
            new_val = max(int(config.max_tool_calls_per_session * 0.7), 100)
            if new_val != config.max_tool_calls_per_session:
                improvements.append({
                    "parameter": "max_tool_calls_per_session",
                    "old": config.max_tool_calls_per_session,
                    "new": new_val,
                    "expected_gain": 0.005,
                })

    return improvements


def _optimize_context_budget(
    conn: sqlite3.Connection, workspace_id: str, config: ForgeConfig
) -> list[dict]:
    """Analyze context metrics, return budget suggestions."""
    improvements: list[dict] = []

    context_hit_rate = _get_context_hit_rate(conn, workspace_id)
    stale_warning_rate = _get_stale_warning_rate(conn, workspace_id)

    l0_suggestion: int | None = None

    # Low context hit rate → reduce l0_max_entries
    if context_hit_rate is not None and context_hit_rate < 0.3:
        l0_suggestion = max(config.l0_max_entries // 2, 5)

    # High stale warning rate → reduce l0 and l1
    if stale_warning_rate is not None and stale_warning_rate > 0.5:
        reduced_l0 = max(int(config.l0_max_entries * 0.7), 5)
        l0_suggestion = (
            min(l0_suggestion, reduced_l0) if l0_suggestion is not None else reduced_l0
        )
        new_l1 = max(config.l1_project_entries - 1, 1)
        if new_l1 != config.l1_project_entries:
            improvements.append({
                "parameter": "l1_project_entries",
                "old": config.l1_project_entries,
                "new": new_l1,
                "expected_gain": 0.01,
            })

    if l0_suggestion is not None and l0_suggestion != config.l0_max_entries:
        improvements.append({
            "parameter": "l0_max_entries",
            "old": config.l0_max_entries,
            "new": l0_suggestion,
            "expected_gain": 0.02,
        })

    # Context overhead: forge + team tokens exceed total by > 5%
    context_overhead = (
        config.forge_context_tokens + config.team_context_tokens - config.total_max_tokens
    )
    if context_overhead > config.total_max_tokens * 0.05:
        new_forge = max(int(config.forge_context_tokens * 0.9), 500)
        if new_forge != config.forge_context_tokens:
            improvements.append({
                "parameter": "forge_context_tokens",
                "old": config.forge_context_tokens,
                "new": new_forge,
                "expected_gain": 0.01,
            })

    return improvements


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def run_research_v5(
    workspace_id: str,
    conn: sqlite3.Connection,
    config: ForgeConfig | None = None,
) -> ResearchResult:
    """V5 full optimization sweep.

    Extends existing optimizer.run_config_sweep with new parameters:
    1. Existing: alpha, l0/l1/rules entries, promote_threshold
    2. NEW: routing_model_map optimization
       - Per category: find best performing model from model_choices
       - Suggest routing_model_map_str update
    3. NEW: circuit breaker tuning
       - If break_rate > 20%: suggest increasing max_consecutive_failures
       - If break_rate < 1% and max_consecutive_failures > 3: suggest decreasing
       - Same logic for max_tool_calls_per_session
    4. NEW: context budget optimization
       - If context_hit_rate < 0.3: suggest reducing l0_max_entries
       - If stale_warning_rate > 0.5: suggest reducing l0/l1 entries
       - If context_overhead > 5% of total_max_tokens: suggest reducing budgets
    """
    if config is None:
        config = load_config()

    baseline_fitness = _compute_baseline_fitness(conn, workspace_id)
    improvements: list[dict] = []
    sweep_log: list[dict] = []

    # 1. Routing optimization
    routing_improvements = _optimize_routing(conn, workspace_id, config)
    improvements.extend(routing_improvements)
    sweep_log.append({
        "params": {
            imp["parameter"]: imp["new"]
            for imp in routing_improvements
            if not imp["parameter"].startswith("routing:")
        },
        "fitness": baseline_fitness + sum(
            i.get("expected_gain", 0.0) for i in routing_improvements
        ),
    })

    # 2. Circuit breaker optimization
    breaker_improvements = _optimize_breaker(conn, workspace_id, config)
    improvements.extend(breaker_improvements)
    sweep_log.append({
        "params": {imp["parameter"]: imp["new"] for imp in breaker_improvements},
        "fitness": baseline_fitness + sum(
            i.get("expected_gain", 0.0) for i in breaker_improvements
        ),
    })

    # 3. Context budget optimization
    context_improvements = _optimize_context_budget(conn, workspace_id, config)
    improvements.extend(context_improvements)
    sweep_log.append({
        "params": {imp["parameter"]: imp["new"] for imp in context_improvements},
        "fitness": baseline_fitness + sum(
            i.get("expected_gain", 0.0) for i in context_improvements
        ),
    })

    # Build best_config (skip per-category routing: details)
    best_config: dict[str, object] = {}
    for imp in improvements:
        if not imp["parameter"].startswith("routing:"):
            best_config[imp["parameter"]] = imp["new"]

    total_gain = sum(imp.get("expected_gain", 0.0) for imp in improvements)
    after_fitness = min(1.0, baseline_fitness + total_gain)

    return ResearchResult(
        best_config=best_config,
        improvements=improvements,
        unified_fitness_before=baseline_fitness,
        unified_fitness_after=after_fitness,
        sweep_log=sweep_log,
    )


def run_prompt_research(
    workspace_id: str,
    conn: sqlite3.Connection,
) -> PromptResearchResult:
    """Analyze A/B format effectiveness and hint quality distribution.

    1. Read A/B stats from forge_meta (key: "ab_stats:{workspace_id}")
    2. Determine best format variant
    3. Count low quality hints (score < 0.3)
    4. Categorize hints: good (>=0.7), medium (0.3-0.7), poor (<0.3)
    """
    # 1. Read A/B stats from forge_meta
    format_stats: dict[str, dict] = {}
    best_format = "concise"

    try:
        row = conn.execute(
            "SELECT value FROM forge_meta WHERE key = ?",
            (f"ab_stats:{workspace_id}",),
        ).fetchone()

        if row:
            ab_data = json.loads(row[0])
            for variant, stats in ab_data.items():
                helped = stats.get("helped", 0)
                total = stats.get("total", 0)
                rate = helped / total if total > 0 else 0.0
                format_stats[variant] = {"helped": helped, "total": total, "rate": rate}

            if format_stats:
                best_format = max(format_stats, key=lambda k: format_stats[k]["rate"])
    except (sqlite3.OperationalError, json.JSONDecodeError, TypeError):
        pass

    # Default stats if no A/B data available
    if not format_stats:
        format_stats = {
            "concise": {"helped": 0, "total": 0, "rate": 0.0},
            "detailed": {"helped": 0, "total": 0, "rate": 0.0},
        }

    # 2. Analyze hint quality distribution from failures
    low_quality_count = 0
    hint_distribution: dict[str, int] = {"good": 0, "medium": 0, "poor": 0}

    try:
        rows = conn.execute(
            "SELECT q FROM failures WHERE workspace_id = ? AND active = 1",
            (workspace_id,),
        ).fetchall()

        for r in rows:
            q = r[0]
            if q >= 0.7:
                hint_distribution["good"] += 1
            elif q >= 0.3:
                hint_distribution["medium"] += 1
            else:
                hint_distribution["poor"] += 1
                low_quality_count += 1
    except sqlite3.OperationalError:
        pass

    return PromptResearchResult(
        best_format=best_format,
        format_stats=format_stats,
        low_quality_hints_count=low_quality_count,
        hint_quality_distribution=hint_distribution,
    )
