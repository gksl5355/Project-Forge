"""ForgeConfig dataclass + YAML loading + defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


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


_DEFAULT_CONFIG_PATH = Path.home() / ".forge" / "config.yml"


def load_config(path: Path | None = None) -> ForgeConfig:
    """~/.forge/config.yml 로드. 없으면 기본값."""
    config_path = path or _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return ForgeConfig()
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    valid_fields = ForgeConfig.__dataclass_fields__.keys()
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return ForgeConfig(**filtered)
