# Project Forge

An experience learning CLI tool for coding agents. Accumulates failures, decisions, rules, and knowledge across sessions, updates their utility via RL-style EMA (MemRL), and injects relevant experience into future sessions.

## Tech Stack

- Python 3.11+, Typer (CLI), sqlite3 (built-in), PyYAML
- Minimize external dependencies. No SQLAlchemy.
- Models: Python dataclass. Tests: pytest.

## Project Structure

```
forge/
├── cli.py              # Typer app, all commands registered here
├── config.py            # ForgeConfig dataclass + YAML loading + defaults
├── engines/             # resume, writeback, detect, transcript
├── core/                # qvalue, matcher, promote, context
├── storage/             # db, models, queries (raw sqlite3)
└── hooks/               # install, templates/
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

## Key Documents

- Idea Notes: `docs/IDEA_NOTES.md`
- PRD: `docs/prd/PRD_v0.2.md`
- Architecture: `docs/architecture/ARCHITECTURE_v0.2.md`
- TRD: `docs/trd/TRD_v0.2.md`

## Silo Ownership (for team development)

- **Silo A (Storage + Config)**: forge/config.py, forge/storage/*
- **Silo B (Core Services)**: forge/core/*
- **Silo C (Engines + CLI + Hooks)**: forge/cli.py, forge/engines/*, forge/hooks/*
- **Shared**: tests/conftest.py, pyproject.toml, CLAUDE.md
