# Contributing

## Setup

```bash
git clone https://github.com/gksl5355/Project-Forge.git
cd Project-Forge
uv pip install -e ".[dev]"
```

## Tests

```bash
pytest tests/ --ignore=tests/test_output_analyzer.py -q
```

846 tests, all should pass. Tests use in-memory SQLite (no setup needed).

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
├── core/          # Q-value, matcher, promote, context, hashing, directive
├── engines/       # resume, writeback, detect, fitness, optimizer, measure
├── storage/       # db, models, queries (raw sqlite3)
├── hooks/         # install.py + templates/ (shell scripts)
└── skills/        # Bundled SKILL.md files
```

## Adding a CLI command

1. Add function in `forge/cli.py` with `@app.command("name")`
2. Add tests in `tests/test_edge_cli.py`
3. Run tests

## Pull requests

- One feature per PR
- Tests must pass
- Type hints required
