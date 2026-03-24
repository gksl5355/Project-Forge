"""ForgeConfig dataclass + YAML loading + defaults."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("forge")


@dataclass
class ForgeConfig:
    # context
    max_tokens: int = 3000
    l0_max_entries: int = 50
    l1_project_entries: int = 3
    l1_global_entries: int = 2
    rules_max_entries: int = 10
    # learning
    alpha: float = 0.1
    decay_daily: float = 0.005
    q_min: float = 0.05
    promote_threshold: int = 2
    promote_min_times_seen: int = 3
    knowledge_promote_q: float = 0.8
    knowledge_promote_helped: int = 5
    # initial_q
    initial_q_near_miss: float = 0.6
    initial_q_preventable: float = 0.5
    initial_q_environmental: float = 0.3
    initial_q_decision: float = 0.5
    initial_q_knowledge: float = 0.5
    # v1: vector search
    vector_search_enabled: bool = True
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    lambda_weight: float = 0.5        # hybrid score: (1-λ)*sim + λ*Q
    dedup_threshold: float = 0.8      # cosine similarity for dedup
    # v1: context budget
    total_max_tokens: int = 4000
    team_context_tokens: int = 1000
    forge_context_tokens: int = 2500
    # v1: LLM extraction
    llm_extract_enabled: bool = False
    llm_model: str = "claude-haiku-4-5-20251001"
    # v2: dedup interval
    dedup_interval_days: int = 0      # 0=disabled, >0=auto dedup after N days
    # v2: auto ingest
    auto_ingest_enabled: bool = True
    # v5: model routing
    routing_enabled: bool = True
    routing_model_map_str: str = "quick=claude-haiku-4-5,standard=claude-sonnet-4-6,deep=claude-opus-4-6,review=claude-sonnet-4-6"
    # v5: circuit breaker
    circuit_breaker_enabled: bool = True
    max_consecutive_failures: int = 10
    max_tool_calls_per_session: int = 200
    # v5: agent manager
    agent_manager_enabled: bool = True
    # v5: prompt optimizer — A/B testing
    ab_enabled: bool = True
    ab_min_observations: int = 10
    ab_variant_threshold: float = 0.05
    # v5: prompt optimizer — injection ordering
    injection_score_enabled: bool = True
    injection_recency_weight: float = 0.2
    injection_relevance_weight: float = 0.2
    injection_base_weight: float = 0.6
    injection_recency_decay: str = "exponential"  # exponential | exponential_slow | linear
    # v5: prompt optimizer — hint quality
    hint_quality_threshold: float = 0.3
    hint_actionability_bonus: float = 0.15
    hint_vagueness_penalty: float = 0.1
    # v5: routing tuning
    routing_min_observations: int = 5
    # v5: unified fitness v5 weights (must sum to 1.0, optimized via Wave 6 sweep)
    kpi_w_qwhr: float = 0.30
    kpi_w_routing: float = 0.15
    kpi_w_circuit: float = 0.08
    kpi_w_agent: float = 0.08
    kpi_w_context: float = 0.15
    kpi_w_token: float = 0.12
    kpi_w_redundant: float = 0.06
    kpi_w_stale: float = 0.06


_DEFAULT_CONFIG_PATH = Path.home() / ".forge" / "config.yml"


def load_config(path: Path | None = None) -> ForgeConfig:
    """~/.forge/config.yml 로드. 없으면 기본값."""
    config_path = path or _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return ForgeConfig()
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse config YAML at %s: %s", config_path, e)
        return ForgeConfig()
    valid_fields = ForgeConfig.__dataclass_fields__.keys()
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    config = ForgeConfig(**filtered)
    return _validate_config(config)


def save_config_yaml(config: ForgeConfig, path: Path | None = None) -> None:
    """Save config to YAML file. Only writes non-default values."""
    config_path = path or _DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    defaults = ForgeConfig()
    data: dict[str, object] = {}
    for name in ForgeConfig.__dataclass_fields__:
        val = getattr(config, name)
        if val != getattr(defaults, name):
            data[name] = val
    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def _validate_config(config: ForgeConfig) -> ForgeConfig:
    """Validate and clamp config values to valid ranges."""
    # Clamp learning parameters to [0.0, 1.0]
    config.alpha = max(0.0, min(1.0, config.alpha))
    config.decay_daily = max(0.0, min(1.0, config.decay_daily))
    config.q_min = max(0.0, min(1.0, config.q_min))
    config.knowledge_promote_q = max(0.0, min(1.0, config.knowledge_promote_q))
    config.lambda_weight = max(0.0, min(1.0, config.lambda_weight))
    config.dedup_threshold = max(0.0, min(1.0, config.dedup_threshold))

    # Clamp initial Q values to [0.0, 1.0]
    config.initial_q_near_miss = max(0.0, min(1.0, config.initial_q_near_miss))
    config.initial_q_preventable = max(0.0, min(1.0, config.initial_q_preventable))
    config.initial_q_environmental = max(0.0, min(1.0, config.initial_q_environmental))
    config.initial_q_decision = max(0.0, min(1.0, config.initial_q_decision))
    config.initial_q_knowledge = max(0.0, min(1.0, config.initial_q_knowledge))

    # Ensure positive integers
    if config.max_tokens <= 0:
        config.max_tokens = 3000
    if config.l0_max_entries <= 0:
        config.l0_max_entries = 50
    if config.l1_project_entries <= 0:
        config.l1_project_entries = 3
    if config.l1_global_entries <= 0:
        config.l1_global_entries = 2
    if config.rules_max_entries <= 0:
        config.rules_max_entries = 10
    if config.promote_threshold <= 0:
        config.promote_threshold = 2
    if config.promote_min_times_seen <= 0:
        config.promote_min_times_seen = 3
    if config.knowledge_promote_helped <= 0:
        config.knowledge_promote_helped = 5
    if config.total_max_tokens <= 0:
        config.total_max_tokens = 4000
    if config.team_context_tokens <= 0:
        config.team_context_tokens = 1000
    if config.forge_context_tokens <= 0:
        config.forge_context_tokens = 2500
    if config.dedup_interval_days < 0:
        config.dedup_interval_days = 0
    # v5: circuit breaker
    if config.max_consecutive_failures <= 0:
        config.max_consecutive_failures = 10
    if config.max_tool_calls_per_session <= 0:
        config.max_tool_calls_per_session = 200
    # v5: A/B testing
    config.ab_variant_threshold = max(0.0, min(1.0, config.ab_variant_threshold))
    if config.ab_min_observations <= 0:
        config.ab_min_observations = 10
    # v5: injection ordering weights (clamp and normalize)
    config.injection_recency_weight = max(0.0, min(1.0, config.injection_recency_weight))
    config.injection_relevance_weight = max(0.0, min(1.0, config.injection_relevance_weight))
    config.injection_base_weight = max(0.0, min(1.0, config.injection_base_weight))
    # v5: hint quality
    config.hint_quality_threshold = max(0.0, min(1.0, config.hint_quality_threshold))
    config.hint_actionability_bonus = max(0.0, min(0.5, config.hint_actionability_bonus))
    config.hint_vagueness_penalty = max(0.0, min(0.5, config.hint_vagueness_penalty))
    # v5: routing
    if config.routing_min_observations <= 0:
        config.routing_min_observations = 5
    # v5: KPI weights — normalize to sum=1.0
    kpi_sum = (
        config.kpi_w_qwhr + config.kpi_w_routing + config.kpi_w_circuit
        + config.kpi_w_agent + config.kpi_w_context + config.kpi_w_token
        + config.kpi_w_redundant + config.kpi_w_stale
    )
    if kpi_sum > 0 and abs(kpi_sum - 1.0) > 0.001:
        config.kpi_w_qwhr /= kpi_sum
        config.kpi_w_routing /= kpi_sum
        config.kpi_w_circuit /= kpi_sum
        config.kpi_w_agent /= kpi_sum
        config.kpi_w_context /= kpi_sum
        config.kpi_w_token /= kpi_sum
        config.kpi_w_redundant /= kpi_sum
        config.kpi_w_stale /= kpi_sum

    return config
