"""Category-based model routing engine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from forge.config import ForgeConfig, load_config
from forge.storage.db import get_connection
from forge.storage.queries import (
    get_model_success_rates,
    insert_model_choice,
    update_model_choice_outcome,
)

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger("forge")


def parse_model_map(map_str: str) -> dict[str, str]:
    """Parse 'quick=model1,standard=model2' → {'quick': 'model1', ...}"""
    if not map_str or not map_str.strip():
        return {}

    result = {}
    for pair in map_str.split(","):
        pair = pair.strip()
        if "=" not in pair:
            logger.warning("Invalid model map pair: %s", pair)
            continue
        key, val = pair.split("=", 1)
        key, val = key.strip(), val.strip()
        if key and val:
            result[key] = val
    return result


def resolve_model(
    workspace_id: str, category: str, config: ForgeConfig | None = None, db: sqlite3.Connection | None = None
) -> str:
    """
    Resolve which model to use for a given category.

    1. If routing disabled → return config.llm_model
    2. Check success rates from DB
    3. If enough data (>= 5 choices), pick best performing model for this category
    4. Otherwise, use model_map default
    """
    if config is None:
        config = load_config()

    # If routing disabled, return default model
    if not config.routing_enabled:
        return config.llm_model

    # Parse the model map
    model_map = parse_model_map(config.routing_model_map_str)

    # Try to get success rates from DB
    should_close = False
    try:
        if db is None:
            db = get_connection()
            should_close = True

        success_rates = get_model_success_rates(db, workspace_id, category)

        # If we have enough data (>= 5 choices), pick best performing model
        if success_rates and len(success_rates) > 0:
            # Find the best model with at least 5 observations
            for model, avg_outcome, count in success_rates:
                if count >= 5:
                    logger.debug(
                        "Routing %s/%s → %s (avg_outcome=%.2f, count=%d)",
                        workspace_id, category, model, avg_outcome, count
                    )
                    return model

    except Exception as e:
        logger.warning("Failed to query model success rates: %s", e)
    finally:
        if should_close and db is not None:
            db.close()

    # Fall back to model_map default
    default = model_map.get(category, config.llm_model)
    logger.debug("Routing %s/%s → %s (default)", workspace_id, category, default)
    return default


def record_choice(
    workspace_id: str, session_id: str, category: str, model_id: str, db: sqlite3.Connection | None = None
) -> int | None:
    """Record a model choice. Returns the choice ID."""
    should_close = False
    if db is None:
        db = get_connection()
        should_close = True
    try:
        choice_id = insert_model_choice(db, workspace_id, session_id, category, model_id)
        return choice_id
    finally:
        if should_close:
            db.close()


def record_outcome(
    choice_id: int, outcome: float, latency_ms: int | None = None, tokens_used: int | None = None, db: sqlite3.Connection | None = None
) -> None:
    """Record the outcome of a model choice (0.0-1.0)."""
    if choice_id is None:
        logger.warning("Cannot record outcome for None choice_id")
        return

    # Clamp outcome to [0.0, 1.0]
    outcome = max(0.0, min(1.0, outcome))

    should_close = False
    if db is None:
        db = get_connection()
        should_close = True
    try:
        update_model_choice_outcome(db, choice_id, outcome)
    finally:
        if should_close:
            db.close()

    logger.debug("Recorded outcome %.2f for choice_id=%d (latency=%s, tokens=%s)",
                 outcome, choice_id, latency_ms, tokens_used)


def get_routing_stats(workspace_id: str, db: sqlite3.Connection | None = None) -> dict:
    """Get routing statistics: per-category success rates, total choices, etc."""
    try:
        should_close = False
        if db is None:
            db = get_connection()
            should_close = True

        try:
            # Get all categories and their success rates
            rows = db.execute(
                """SELECT task_category, selected_model, AVG(outcome) as avg_outcome, COUNT(*) as cnt
                   FROM model_choices
                   WHERE workspace_id = ? AND outcome IS NOT NULL
                   GROUP BY task_category, selected_model
                   ORDER BY task_category, avg_outcome DESC""",
                (workspace_id,),
            ).fetchall()

            # Organize by category
            stats: dict[str, dict] = {}
            for row in rows:
                category = row["task_category"]
                if category not in stats:
                    stats[category] = {
                        "models": [],
                        "best_model": None,
                        "best_outcome": 0.0,
                        "total_choices": 0,
                    }

                model = row["selected_model"]
                avg_outcome = row["avg_outcome"]
                count = row["cnt"]

                stats[category]["models"].append({
                    "model": model,
                    "avg_outcome": avg_outcome,
                    "count": count,
                })
                stats[category]["total_choices"] += count

                # Track best
                if avg_outcome > stats[category]["best_outcome"]:
                    stats[category]["best_model"] = model
                    stats[category]["best_outcome"] = avg_outcome

            # Get total choices across all categories
            total = db.execute(
                "SELECT COUNT(*) as cnt FROM model_choices WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()

            return {
                "categories": stats,
                "total_choices": total["cnt"] if total else 0,
            }
        finally:
            if should_close:
                db.close()

    except Exception as e:
        logger.error("Failed to get routing stats: %s", e)
        return {"categories": {}, "total_choices": 0}
