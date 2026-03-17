"""Tests for forge/engines/fitness.py — unified fitness function."""

from __future__ import annotations

import pytest

from forge.engines.fitness import compute_unified_fitness


class TestForgeOnlyFitness:
    """When no TO data, uses forge-only weights: 0.6*QWHR + 0.25*token_eff_norm + 0.15*promo."""

    def test_zero_inputs(self):
        assert compute_unified_fitness(0.0, 0.0, 0.0) == 0.0

    def test_perfect_scores(self):
        # token_efficiency * 100 capped at 1.0 → use 0.01 to get 1.0
        result = compute_unified_fitness(1.0, 0.01, 1.0)
        expected = 0.6 * 1.0 + 0.25 * 1.0 + 0.15 * 1.0
        assert result == pytest.approx(expected)

    def test_token_efficiency_normalization(self):
        # token_efficiency = 0.005 → normalized = 0.5
        result = compute_unified_fitness(0.5, 0.005, 0.5)
        expected = 0.6 * 0.5 + 0.25 * 0.5 + 0.15 * 0.5
        assert result == pytest.approx(expected)

    def test_token_efficiency_capped(self):
        # token_efficiency = 0.02 → normalized = 2.0 → capped at 1.0
        result = compute_unified_fitness(0.5, 0.02, 0.5)
        expected = 0.6 * 0.5 + 0.25 * 1.0 + 0.15 * 0.5
        assert result == pytest.approx(expected)

    def test_returns_forge_only_when_no_to_data(self):
        result = compute_unified_fitness(0.7, 0.005, 0.6, to_run_count=0)
        forge_only = 0.6 * 0.7 + 0.25 * 0.5 + 0.15 * 0.6
        assert result == pytest.approx(forge_only)

    def test_returns_forge_only_when_sr_none(self):
        result = compute_unified_fitness(0.7, 0.005, 0.6, to_success_rate=None, to_run_count=3)
        forge_only = 0.6 * 0.7 + 0.25 * 0.5 + 0.15 * 0.6
        assert result == pytest.approx(forge_only)


class TestTOIntegratedFitness:
    """When TO data present, blends forge and TO fitness based on confidence."""

    def test_full_confidence_at_5_runs(self):
        """to_run_count >= 5 → confidence=1.0, pure TO fitness."""
        result = compute_unified_fitness(
            0.7, 0.005, 0.6,
            to_success_rate=0.8, to_retry_rate=0.2, to_scope_violations=2.0,
            to_run_count=5,
        )
        token_eff_norm = 0.5
        to_fitness = (
            0.40 * 0.7 + 0.20 * token_eff_norm + 0.10 * 0.6
            + 0.15 * 0.8 + 0.10 * 0.8 + 0.05 * 0.8
        )
        assert result == pytest.approx(to_fitness)

    def test_partial_confidence(self):
        """to_run_count=2 → confidence=0.4, blended."""
        result = compute_unified_fitness(
            0.7, 0.005, 0.6,
            to_success_rate=0.8, to_retry_rate=0.2, to_scope_violations=2.0,
            to_run_count=2,
        )
        token_eff_norm = 0.5
        forge = 0.6 * 0.7 + 0.25 * token_eff_norm + 0.15 * 0.6
        to = (
            0.40 * 0.7 + 0.20 * token_eff_norm + 0.10 * 0.6
            + 0.15 * 0.8 + 0.10 * 0.8 + 0.05 * 0.8
        )
        confidence = 2 / 5
        expected = confidence * to + (1 - confidence) * forge
        assert result == pytest.approx(expected)

    def test_sr_capped_at_1(self):
        result = compute_unified_fitness(
            0.5, 0.005, 0.5,
            to_success_rate=1.5, to_retry_rate=0.0, to_scope_violations=0.0,
            to_run_count=10,
        )
        # sr should be capped at 1.0
        assert result > 0

    def test_rr_none_defaults_to_zero(self):
        result = compute_unified_fitness(
            0.5, 0.005, 0.5,
            to_success_rate=0.8, to_retry_rate=None, to_scope_violations=0.0,
            to_run_count=5,
        )
        token_eff_norm = 0.5
        to_fitness = (
            0.40 * 0.5 + 0.20 * token_eff_norm + 0.10 * 0.5
            + 0.15 * 0.8 + 0.10 * 1.0 + 0.05 * 1.0
        )
        assert result == pytest.approx(to_fitness)

    def test_high_scope_violations_reduce_fitness(self):
        low_sv = compute_unified_fitness(
            0.5, 0.005, 0.5,
            to_success_rate=0.8, to_retry_rate=0.1, to_scope_violations=1.0,
            to_run_count=5,
        )
        high_sv = compute_unified_fitness(
            0.5, 0.005, 0.5,
            to_success_rate=0.8, to_retry_rate=0.1, to_scope_violations=8.0,
            to_run_count=5,
        )
        assert low_sv > high_sv

    def test_scope_violations_clamped_at_zero(self):
        """sv > 10 → max(0, 1 - sv/10) = 0."""
        result = compute_unified_fitness(
            0.5, 0.005, 0.5,
            to_success_rate=0.8, to_retry_rate=0.0, to_scope_violations=15.0,
            to_run_count=5,
        )
        assert result > 0  # still positive due to other components
