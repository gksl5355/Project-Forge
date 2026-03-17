"""Unified fitness function for experiment tracking."""

from __future__ import annotations


def compute_unified_fitness(
    qwhr: float,
    token_efficiency: float,
    promotion_precision: float,
    to_success_rate: float | None = None,
    to_retry_rate: float | None = None,
    to_scope_violations: float | None = None,
    to_run_count: int = 0,
) -> float:
    """Compute unified fitness score combining Forge and TO metrics.

    Forge-only fitness (when no TO data):
        0.6*QWHR + 0.25*token_eff_norm + 0.15*promotion_precision

    TO-integrated fitness (when TO data available):
        0.40*QWHR + 0.20*token_eff_norm + 0.10*promotion_precision
        + 0.15*success_rate + 0.10*(1-retry_rate) + 0.05*scope_violation_score

    Confidence interpolation: when TO runs < 5, blend toward forge-only.
    """
    token_eff_norm = min(1.0, token_efficiency * 100)
    forge_fitness = 0.6 * qwhr + 0.25 * token_eff_norm + 0.15 * promotion_precision

    if to_run_count == 0 or to_success_rate is None:
        return forge_fitness

    sr = min(to_success_rate, 1.0)
    rr = min(to_retry_rate or 0.0, 1.0)
    sv = max(0.0, 1.0 - (to_scope_violations or 0.0) / 10)

    to_fitness = (
        0.40 * qwhr
        + 0.20 * token_eff_norm
        + 0.10 * promotion_precision
        + 0.15 * sr
        + 0.10 * (1.0 - rr)
        + 0.05 * sv
    )

    confidence = min(1.0, to_run_count / 5)
    return confidence * to_fitness + (1.0 - confidence) * forge_fitness
