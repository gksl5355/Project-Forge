# Contributing

## Setup

```bash
git clone https://github.com/0xshuttle/Project-Forge.git
cd Project-Forge

# With pip
pip install -e ".[dev]"

# Or with uv
uv pip install -e ".[dev]"

# Or with make
make dev
```

## Tests

```bash
pytest tests/ --ignore=tests/test_output_analyzer.py -q
```

1,050+ tests, all should pass. Tests use in-memory SQLite (no setup needed).

## Code style

- Python 3.12+, type hints on all function signatures
- No SQLAlchemy — raw sqlite3 only
- Models: Python dataclass
- CLI: Typer
- JSON columns: `json.dumps`/`json.loads`

## Project structure

```
forge/
├── cli.py         # All Typer commands
├── config.py      # ForgeConfig dataclass
├── core/          # Q-value, matcher, promote, context, circuit breaker
├── engines/       # resume, writeback, detect, fitness, routing, prompt optimizer
├── extras/        # optimizer, ablation, dedup, embedding
├── storage/       # db, models, queries (raw sqlite3)
├── hooks/         # install.py + templates/ (shell scripts)
└── skills/        # Bundled SKILL.md files
```

## Adding a CLI command

1. Add function in `forge/cli.py` with `@app.command("name")`
2. Add tests in `tests/`
3. Run full test suite

## Pull requests

- One feature per PR
- Tests must pass
- Type hints required
