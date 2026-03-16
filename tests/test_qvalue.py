"""Tests for forge.core.qvalue."""

import pytest

from forge.config import ForgeConfig
from forge.core.qvalue import ema_update, initial_q, time_decay


def test_ema_update_basic():
    result = ema_update(0.5, 1.0, 0.1)
    assert result == pytest.approx(0.55)


def test_ema_update_formula():
    # Q_new = Q + alpha * (r - Q)
    q, r, alpha = 0.6, 0.0, 0.1
    assert ema_update(q, r, alpha) == pytest.approx(q + alpha * (r - q))


def test_ema_update_reward_equals_q_no_change():
    assert ema_update(0.5, 0.5, 0.1) == pytest.approx(0.5)


def test_ema_update_converges_to_reward():
    q = 0.0
    for _ in range(1000):
        q = ema_update(q, 1.0, 0.1)
    assert q == pytest.approx(1.0, abs=0.01)


def test_ema_update_negative_reward():
    result = ema_update(0.5, 0.0, 0.1)
    assert result == pytest.approx(0.45)


def test_time_decay_basic():
    q, days, decay_rate, q_min = 0.5, 10, 0.005, 0.05
    expected = 0.5 * (1 - 0.005) ** 10
    assert time_decay(q, days, decay_rate, q_min) == pytest.approx(expected)


def test_time_decay_zero_days_no_change():
    assert time_decay(0.7, 0, 0.005, 0.05) == pytest.approx(0.7)


def test_time_decay_clamps_to_q_min():
    # 아주 오랜 시간 경과 → q_min으로 고정
    result = time_decay(0.5, 10_000, 0.005, 0.05)
    assert result == pytest.approx(0.05)


def test_time_decay_respects_q_min():
    result = time_decay(0.06, 1000, 0.005, 0.05)
    assert result >= 0.05


def test_initial_q_near_miss():
    config = ForgeConfig()
    assert initial_q("near_miss", config) == pytest.approx(0.6)


def test_initial_q_preventable():
    config = ForgeConfig()
    assert initial_q("preventable", config) == pytest.approx(0.5)


def test_initial_q_environmental():
    config = ForgeConfig()
    assert initial_q("environmental", config) == pytest.approx(0.3)


def test_initial_q_unknown_falls_back_to_preventable():
    config = ForgeConfig()
    assert initial_q("unknown_type", config) == pytest.approx(config.initial_q_preventable)


def test_initial_q_uses_config_values():
    config = ForgeConfig(initial_q_near_miss=0.9)
    assert initial_q("near_miss", config) == pytest.approx(0.9)
