"""Unified fitness function for experiment tracking."""

from __future__ import annotations

from forge.config import ForgeConfig


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


def compute_unified_fitness_v5(
    qwhr: float,
    routing_accuracy: float,
    circuit_efficiency: float,
    agent_utilization: float,
    context_hit_rate: float,
    token_efficiency: float,
    redundant_call_rate: float,
    stale_warning_rate: float,
    config: ForgeConfig | None = None,
) -> float:
    """Unified Fitness v5 — 8 KPI weighted sum with configurable weights.

    Default weights:
    UF = 0.25*QWHR + 0.15*RoutingAccuracy + 0.10*CircuitEff
       + 0.10*AgentUtil + 0.10*ContextHitRate + 0.10*TokenEff
       + 0.10*(1-RedundantCallRate) + 0.10*(1-StaleWarningRate)

    All inputs clamped to [0.0, 1.0]. Weights read from config.kpi_w_* fields.
    """
    if config is None:
        config = ForgeConfig()

    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    return (
        config.kpi_w_qwhr * _clamp(qwhr)
        + config.kpi_w_routing * _clamp(routing_accuracy)
        + config.kpi_w_circuit * _clamp(circuit_efficiency)
        + config.kpi_w_agent * _clamp(agent_utilization)
        + config.kpi_w_context * _clamp(context_hit_rate)
        + config.kpi_w_token * _clamp(token_efficiency)
        + config.kpi_w_redundant * (1.0 - _clamp(redundant_call_rate))
        + config.kpi_w_stale * (1.0 - _clamp(stale_warning_rate))
    )
