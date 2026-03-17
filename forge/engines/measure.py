"""Measurement engine: compute optimization metrics for a workspace."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from forge.config import ForgeConfig
from forge.core.context import build_context, estimate_tokens
from forge.engines.optimizer import compute_qwhr
from forge.storage.queries import list_failures, list_rules, list_sessions


@dataclass
class MeasureResult:
    qwhr: float                              # Q-Weighted Hit Rate (0~1)
    promotion_precision: float               # __global__ 패턴 중 helped된 비율 (0~1)
    l1_vs_l0_help_rate: float               # L1 help_rate - 전체 help_rate (양수면 L1이 효과적)
    helped_per_1k_tokens: float             # 1000토큰당 도움 횟수
    section_effectiveness: dict[str, float | None]  # failures: avg_help_rate, others: None
    q_convergence_speed: float              # 도움된 패턴의 평균 times_seen (적을수록 빠른 수렴)
    total_failures: int
    total_sessions: int


def run_measure(
    workspace_id: str,
    db: sqlite3.Connection,
    config: ForgeConfig,
) -> MeasureResult:
    """Compute optimization metrics for the given workspace."""
    failures = list_failures(db, workspace_id)
    rules = list_rules(db, workspace_id)
    sessions = list_sessions(db, workspace_id)

    total_failures = len(failures)
    total_sessions = len(sessions)

    # Pre-compute help_rates and q_values
    q_values: dict[str, float] = {}
    help_rates: dict[str, float] = {}
    for f in failures:
        q_values[f.pattern] = f.q
        if f.times_warned > 0:
            help_rates[f.pattern] = f.times_helped / f.times_warned
        else:
            help_rates[f.pattern] = 0.5  # uninformative prior

    # QWHR: compute over all active failure patterns
    warned_patterns = [f.pattern for f in failures]
    qwhr = compute_qwhr(warned_patterns, q_values, help_rates)

    # Promotion precision: __global__ failures 중 times_helped > 0 비율
    global_failures = list_failures(db, "__global__", include_global=False)
    if global_failures:
        helped_global = sum(1 for f in global_failures if f.times_helped > 0)
        promotion_precision = helped_global / len(global_failures)
    else:
        promotion_precision = 0.0

    # L1 vs L0 help rate: Q 상위 l1_count개 vs 전체 평균 차이
    l1_count = config.l1_project_entries + config.l1_global_entries
    if failures and l1_count > 0:
        l1_failures = sorted(failures, key=lambda f: f.q, reverse=True)[:l1_count]
        l1_avg = sum(help_rates.get(f.pattern, 0.0) for f in l1_failures) / len(l1_failures)
        overall_avg = sum(help_rates.values()) / len(help_rates) if help_rates else 0.0
        l1_vs_l0_help_rate = l1_avg - overall_avg
    else:
        l1_vs_l0_help_rate = 0.0

    # Helped per 1K tokens
    total_helped = sum(f.times_helped for f in failures)
    if failures:
        context = build_context(failures, rules, config)
        tokens = estimate_tokens(context)
        helped_per_1k_tokens = total_helped / (tokens / 1000) if tokens > 0 else 0.0
    else:
        helped_per_1k_tokens = 0.0

    # Section effectiveness: failures만 help_rate 데이터 있음
    if failures:
        avg_help_rate: float | None = sum(help_rates.values()) / len(help_rates)
    else:
        avg_help_rate = None

    section_effectiveness: dict[str, float | None] = {
        "failures": avg_help_rate,
        "decisions": None,
        "rules": None,
        "knowledge": None,
    }

    # Q convergence speed: helped 패턴들의 평균 times_seen
    helped_failures = [f for f in failures if f.times_helped > 0]
    if helped_failures:
        q_convergence_speed = sum(f.times_seen for f in helped_failures) / len(helped_failures)
    else:
        q_convergence_speed = 0.0

    return MeasureResult(
        qwhr=qwhr,
        promotion_precision=promotion_precision,
        l1_vs_l0_help_rate=l1_vs_l0_help_rate,
        helped_per_1k_tokens=helped_per_1k_tokens,
        section_effectiveness=section_effectiveness,
        q_convergence_speed=q_convergence_speed,
        total_failures=total_failures,
        total_sessions=total_sessions,
    )
