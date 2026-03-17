"""AutoResearch: Context optimization via retrospective simulation."""

from __future__ import annotations

import copy
import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterator

from forge.config import ForgeConfig
from forge.core.context import build_context, estimate_tokens, trim_to_budget
from forge.storage.models import Failure, Session
from forge.storage.queries import (
    list_decisions,
    list_failures,
    list_knowledge,
    list_rules,
    list_sessions,
)

logger = logging.getLogger("forge")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SessionResult:
    """Per-session simulation result."""
    warned_patterns: list[str]
    helped_count: int
    not_helped_count: int
    qwhr: float
    tokens_used: int


@dataclass
class ExperimentResult:
    """Result of evaluating a single config candidate."""
    config: ForgeConfig
    qwhr: float
    token_efficiency: float
    coverage: float
    waste: float
    sessions_evaluated: int


@dataclass
class OptimizationResult:
    """Final result of the optimization run."""
    baseline: ExperimentResult
    best: ExperimentResult
    experiments: list[ExperimentResult]
    total_experiments: int
    improved: bool


# Progress callback: (step, max_experiments, param_desc, result, improved)
ProgressFn = Callable[[int, int, str, ExperimentResult, bool], None] | None


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------

PARAM_GRID: dict[str, list[int]] = {
    "l0_max_entries": [5, 10, 20, 30, 50],
    "l1_project_entries": [1, 2, 3, 5],
    "l1_global_entries": [0, 1, 2, 3],
    "rules_max_entries": [3, 5, 10],
    "total_max_tokens": [1000, 1500, 2000, 2500, 3000, 4000],
    "forge_context_tokens": [1000, 1500, 2000, 2500],
}


class ParameterSpace:
    """Config parameter space for optimization."""

    @staticmethod
    def greedy_sweep(
        baseline: ForgeConfig,
    ) -> Iterator[tuple[str, int, ForgeConfig]]:
        """Yield (param_name, value, variant) for each candidate config."""
        for param, values in PARAM_GRID.items():
            current_val = getattr(baseline, param)
            for val in values:
                if val == current_val:
                    continue
                variant = copy.copy(baseline)
                setattr(variant, param, val)
                yield param, val, variant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_warned_patterns(context_text: str) -> list[str]:
    """Extract pattern names from [WARN] lines in formatted context."""
    patterns: list[str] = []
    for line in context_text.split("\n"):
        if line.startswith("[WARN] "):
            parts = line[7:].split(" | ")
            if parts:
                pattern = parts[0].strip()
                if pattern and pattern not in patterns:
                    patterns.append(pattern)
    return patterns


def compute_qwhr(
    warned_patterns: list[str],
    q_values: dict[str, float],
    help_rates: dict[str, float],
) -> float:
    """Compute Q-Weighted Hit Rate.

    QWHR = sum(Q_i * help_rate_i) / sum(Q_i) for warned patterns.
    Returns 0.0 if no warned patterns or zero total Q.
    """
    if not warned_patterns:
        return 0.0
    q_weighted_helped = sum(
        q_values.get(p, 0.0) * help_rates.get(p, 0.5) for p in warned_patterns
    )
    q_total = sum(q_values.get(p, 0.0) for p in warned_patterns)
    return q_weighted_helped / q_total if q_total > 0 else 0.0


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class ExperimentSimulator:
    """Evaluates config candidates using retrospective session simulation."""

    def __init__(
        self,
        workspace_id: str,
        db: sqlite3.Connection,
        failures: list[Failure],
    ) -> None:
        self.workspace_id = workspace_id
        self.db = db
        self.failures = failures
        self.rules = list_rules(db, workspace_id)
        self.decisions = list_decisions(db, workspace_id)
        self.knowledge = list_knowledge(db, workspace_id)

        # Pre-compute help rates and Q values per pattern
        self.help_rates: dict[str, float] = {}
        self.q_values: dict[str, float] = {}
        for f in failures:
            self.q_values[f.pattern] = f.q
            if f.times_warned > 0:
                self.help_rates[f.pattern] = f.times_helped / f.times_warned
            else:
                self.help_rates[f.pattern] = 0.5  # uninformative prior

    def simulate_session(
        self, session: Session, test_config: ForgeConfig,
    ) -> SessionResult:
        """Simulate what context a test_config would produce."""
        context = build_context(
            self.failures, self.rules, test_config,
            self.decisions, self.knowledge,
        )
        context = trim_to_budget(context, test_config.forge_context_tokens)
        tokens_used = estimate_tokens(context)
        warned = _extract_warned_patterns(context)

        helped = sum(1 for p in warned if self.help_rates.get(p, 0.5) >= 0.5)
        not_helped = len(warned) - helped

        qwhr = compute_qwhr(warned, self.q_values, self.help_rates)

        return SessionResult(
            warned_patterns=warned,
            helped_count=helped,
            not_helped_count=not_helped,
            qwhr=qwhr,
            tokens_used=tokens_used,
        )

    def evaluate_config(
        self, test_config: ForgeConfig, sessions: list[Session],
    ) -> ExperimentResult:
        """Evaluate a config by averaging across all sessions."""
        if not sessions:
            return ExperimentResult(
                config=test_config, qwhr=0.0,
                token_efficiency=0.0, coverage=0.0, waste=0.0,
                sessions_evaluated=0,
            )

        total_qwhr = 0.0
        total_tokens = 0
        total_helped = 0
        total_warned = 0
        total_not_helped = 0

        for session in sessions:
            result = self.simulate_session(session, test_config)
            total_qwhr += result.qwhr
            total_tokens += result.tokens_used
            total_helped += result.helped_count
            total_warned += len(result.warned_patterns)
            total_not_helped += result.not_helped_count

        n = len(sessions)
        avg_qwhr = total_qwhr / n

        token_efficiency = total_helped / total_tokens if total_tokens > 0 else 0.0
        coverage = total_warned / (len(self.failures) * n) if self.failures else 0.0
        waste = total_not_helped / total_warned if total_warned > 0 else 0.0

        return ExperimentResult(
            config=test_config,
            qwhr=avg_qwhr,
            token_efficiency=token_efficiency,
            coverage=coverage,
            waste=waste,
            sessions_evaluated=n,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_autoresearch(
    workspace_id: str,
    db: sqlite3.Connection,
    config: ForgeConfig,
    max_experiments: int = 50,
    strategy: str = "greedy",
    on_progress: ProgressFn = None,
) -> OptimizationResult:
    """Run AutoResearch optimization.

    Uses retrospective simulation on past session data to find
    optimal config parameters for context injection.
    """
    failures = list_failures(db, workspace_id)
    sessions = list_sessions(db, workspace_id)

    if not sessions:
        baseline_result = ExperimentResult(
            config=config, qwhr=0.0,
            token_efficiency=0.0, coverage=0.0, waste=0.0,
            sessions_evaluated=0,
        )
        return OptimizationResult(
            baseline=baseline_result, best=baseline_result,
            experiments=[], total_experiments=0, improved=False,
        )

    simulator = ExperimentSimulator(workspace_id, db, failures)
    baseline = simulator.evaluate_config(config, sessions)
    best = baseline
    experiments: list[ExperimentResult] = [baseline]

    if strategy == "greedy":
        current_config = copy.copy(config)
        experiment_count = 0
        changed = True

        while changed and experiment_count < max_experiments:
            changed = False
            for param, values in PARAM_GRID.items():
                current_val = getattr(current_config, param)
                best_for_param = best
                best_val_for_param = current_val

                for val in values:
                    if val == current_val or experiment_count >= max_experiments:
                        continue

                    variant = copy.copy(current_config)
                    setattr(variant, param, val)
                    experiment_count += 1

                    result = simulator.evaluate_config(variant, sessions)
                    experiments.append(result)

                    is_improved = result.qwhr > best.qwhr
                    if on_progress:
                        on_progress(
                            experiment_count, max_experiments,
                            f"{param}={val}", result, is_improved,
                        )

                    if result.qwhr > best_for_param.qwhr:
                        best_for_param = result
                        best_val_for_param = val

                # Apply best value for this parameter
                if best_for_param.qwhr > best.qwhr:
                    best = best_for_param
                    setattr(current_config, param, best_val_for_param)
                    changed = True

    return OptimizationResult(
        baseline=baseline,
        best=best,
        experiments=experiments,
        total_experiments=len(experiments) - 1,  # exclude baseline
        improved=best.qwhr > baseline.qwhr,
    )
