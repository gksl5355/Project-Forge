"""Q-Value Engine: EMA 업데이트, 시간 감쇠, 초기값 매핑."""

from __future__ import annotations

from forge.config import ForgeConfig


def ema_update(q: float, reward: float, alpha: float) -> float:
    """Q ← Q + α(r - Q)"""
    return q + alpha * (reward - q)


def time_decay(q: float, days: float, decay_rate: float, q_min: float) -> float:
    """Q *= (1 - decay_rate) ^ days, 최소 q_min."""
    decayed = q * (1 - decay_rate) ** days
    return max(decayed, q_min)


def initial_q(hint_quality: str, config: ForgeConfig) -> float:
    """hint_quality → 초기 Q값 매핑."""
    mapping = {
        "near_miss": config.initial_q_near_miss,
        "preventable": config.initial_q_preventable,
        "environmental": config.initial_q_environmental,
    }
    return mapping.get(hint_quality, config.initial_q_preventable)
