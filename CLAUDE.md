# Project Forge

An experience learning CLI tool for coding agents. Accumulates failures, decisions, rules, and knowledge across sessions, updates their utility via RL-style EMA (MemRL), and injects relevant experience into future sessions.

## Tech Stack

- Python 3.12+, Typer (CLI), sqlite3 (built-in), PyYAML
- Minimize external dependencies. No SQLAlchemy.
- Models: Python dataclass. Tests: pytest.

## Project Structure

```
forge/
├── cli.py              # Typer app, all commands registered here
├── config.py            # ForgeConfig dataclass + YAML loading + defaults
├── engines/             # resume, writeback, detect, transcript, fitness, measure, routing, agent_manager, metrics_v5, prompt_optimizer, research_v5
├── core/                # qvalue, matcher, promote, context, hashing, directive, circuit_breaker, output_analyzer
├── extras/              # optimizer, ablation, dedup, directive_extractor, extractor, embedding
├── storage/             # db, models, queries (raw sqlite3)
├── hooks/               # install, templates/ (resume/writeback/detect/teammate.sh)
└── skills/              # bundled SKILL.md files (spawn-team, doctor, debate, ralph)
```

## Core Concepts

- **Q-value**: MemRL EMA formula. `Q ← Q + α(r - Q)`. Measures experience utility.
- **failure**: First-class entity. pattern + avoid_hint + hint_quality + Q.
- **hint_quality**: near_miss (Q:0.6) / preventable (Q:0.5) / environmental (Q:0.3)
- **Global promotion**: When projects_seen >= 2, copy to `__global__` workspace.
- **L0/L1/L2**: Context layered loading. L0 (one-liner) + L1 (summary) injected at session start. L2 on-demand.
- **P1 matching**: Pattern name exact match + tag filter. Vector search deferred to v1.

## Coding Rules

- Type hints required on all function signatures
- Docstrings optional if function signature is self-explanatory
- JSON columns (tags, projects_seen, alternatives, warnings_injected): serialize as `list[str]` via `json.dumps`/`json.loads`
- DB path: `~/.forge/forge.db`
- Config path: `~/.forge/config.yml` (falls back to defaults if missing)
- Transactions: writeback runs as a single transaction
- All CLI commands use Typer
- Tests use pytest with in-memory SQLite fixture (see tests/conftest.py)

## Forge + TO Integration

Forge is the **single source of truth** for all team orchestration learning.

**Data flow:**
```
spawn-team run → report.yml + events.yml → forge ingest → forge.db → forge resume/recommend
```

- `forge ingest`: reads report.yml/events.yml → TeamRun, Failure, Knowledge
- `forge resume --team-brief`: Q-ranked team failures + recent runs
- `forge recommend --complexity X`: best team config based on past runs
- `forge measure`: includes TO metrics (avg success/retry/scope_violations, best configs per complexity)
- `writeback.sh` auto-ingests TO data on session end (background, non-blocking)

## Silo Ownership (for team development)

- **Silo A (Storage + Config)**: forge/config.py, forge/storage/*
- **Silo B (Core Services)**: forge/core/*
- **Silo C (Engines + CLI + Hooks)**: forge/cli.py, forge/engines/*, forge/hooks/*
- **Shared**: tests/conftest.py, pyproject.toml, CLAUDE.md

## Experiment Tracking (v5)

- Schema v5: `experiments`, `sessions`, `model_choices`, `agents` tables
- Unified fitness v4: auto-interpolates forge-only (0.6*QWHR+0.25*TokenEff+0.15*PromoPrecision) and TO-integrated modes
- **Unified fitness v5** (8 KPI, Wave 6 sweep-optimized): `0.30*QWHR + 0.15*RoutingAccuracy + 0.08*CircuitEff + 0.08*AgentUtil + 0.15*ContextHitRate + 0.12*TokenEff + 0.06*(1-RedundantCallRate) + 0.06*(1-StaleWarningRate)`
- Config/document hashing: SHA256[:12] for change detection
- Directive model: atomic document decomposition (rule, threshold, workflow, description, constraint)
- Model routing: category-based model selection with success rate tracking
- Circuit breaker: consecutive failure / tool call limits (forge_meta state)
- Agent lifecycle: register → active → completed/error/timed_out

## Prompt Optimization

- **A/B format testing**: 4 variants (essential/annotated/concise/detailed), EMA-tracked effectiveness (forge_meta)
- **Hint quality scoring**: length, specificity, actionability, vagueness → 0.0~1.0
- **Skill directive analysis**: SKILL.md parsing, clarity scoring, problematic directive flagging
- **Injection order**: `Q × recency × relevance` composite score for context ordering
- **Recency decay**: 3 modes (exponential/exponential_slow/linear) via `injection_recency_decay` config
- **Parameter sweep**: `forge sweep --params GROUP` for grid search optimization

## CLI Commands

Core: `forge init`, `forge resume`, `forge writeback`, `forge detect`, `forge install-hooks`, `forge setup`
Data: `forge record`, `forge list`, `forge search`, `forge detail`, `forge edit`, `forge promote`
Analysis: `forge stats`, `forge decay`, `forge ingest`, `forge recommend`
Score: `forge score [--detail]` — Forge Score 조회 (경험 학습 효과 측정)
Config: `forge config [--advanced] [--set KEY=VALUE]` — 설정 조회/변경
Optimization (hidden):
- `forge measure [--v5] [--hints] [--skills]` — 레거시 metrics
- `forge tune [--params GROUP] [--top N]` — parameter grid search (고급)
- `forge research [--v5] [--prompts]` — auto-optimization
- `forge improve-hints [--dry-run|--apply]` — low-quality hint rewriting
- `forge trend` — experiment history
Extras: `forge embed`, `forge dedup`, `forge optimize`
