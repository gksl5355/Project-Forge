<div align="center">

<img src=".github/assets/hero-banner.svg" alt="Forge — Persistent memory for coding agents" width="100%"/>

<br/>

[![PyPI](https://img.shields.io/pypi/v/forge-memory?style=flat-square&logo=pypi&logoColor=white)](https://pypi.org/project/forge-memory/)
[![Python](https://img.shields.io/badge/python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1243_passed-brightgreen?style=flat-square&logo=pytest&logoColor=white)](#tech-details)
[![MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[English](README.md) · [한국어](README.ko.md)

</div>

---

```
$ claude                              # session starts

[Forge] 3 experiences loaded (Q > 0.5)
  ⚠ async_timeout — Use context manager for DB connections (Q: 0.82)
  ⚠ missing_dotenv — Install python-dotenv before config import (Q: 0.71)
  ℹ pytest_scope — Session-scoped fixtures need explicit teardown (Q: 0.65)
```

## Quick Start

```bash
pip install forge-memory    # or: uv tool install forge-memory
forge setup                 # DB + hooks + skills (~30s)
forge stats                 # verify: 0 failures, 0 sessions
```

That's it. Start coding normally — Forge learns silently from every session.

> `forge` must be on your PATH. `uv tool install` handles this automatically.
> With `pip`, install globally — not in a virtualenv.

---

## What It Does

Forge gives your Claude Code agent **persistent memory across sessions**.

It captures failures and fixes from each session, measures which experiences actually helped via Q-value reinforcement learning, and injects only the proven-useful ones into future sessions — before the agent repeats a mistake.

### How It Works

<img src=".github/assets/flow-diagram.svg" alt="Forge flow diagram" width="100%"/>

**Q-value ranking** — Each experience has a Q score. Helped avoid an error? Q goes up. Ignored? Q goes down. Only high-Q experiences get injected.

**Time decay** — Old patterns lose priority automatically. A 3-month-old error won't clutter every session.

**A/B format testing** — Same warning, 4 different phrasings. Forge finds which one your agent actually follows.

Result: **only proven-useful experiences, in the most effective format, at minimum token cost.**

## Forge vs. Alternatives

| | Nothing | CLAUDE.md only | **Forge** |
|---|---|---|---|
| Error repetition | Every session | Reduced if rule exists | Warned before it happens |
| Knowledge capture | Lost at session end | You write manually | Auto-captured |
| Maintenance | None (pain accumulates) | You maintain every rule | Zero — self-learning |
| Cross-project | None | Copy-paste | Auto-promotes after 2+ projects |
| Effectiveness | No measurement | No measurement | 8 KPIs tracked |
| Token cost | Trial-and-error | Static (full rules every time) | Dynamic — proven items only |

> **Forge + CLAUDE.md work together.** CLAUDE.md sets your rules. Forge catches the exceptions your rules don't cover.

## Forge Score

One number for how well Forge is working:

```
$ forge score

=== Forge Score (workspace: default) ===

  Forge Score:     0.68 / 1.00

  Learning effect:       0.72
  Context hit rate:      0.65
  Token efficiency:      0.58
  Patterns: 47 | Sessions: 23
```

**0.5+** = helping more than missing · **0.7+** = agent actively benefiting from past sessions

Use `forge score --detail` for the full breakdown.

## Features

### Automatic Learning
Every session end triggers analysis. Failures captured, Q-values updated, weak patterns pruned — no manual work needed.

### Smart Context Injection
Experiences ranked by Q-value x recency x relevance. Only the top ones enter your context window.

### Guard Hooks
- **Secret detection** — catches API keys and tokens before commit
- **`--no-verify` blocking** — prevents pre-commit bypass
- **Session health** — suggests `/compact` when sessions get long

### Cross-Project Promotion
Same pattern in 2+ projects? Automatically promoted to global, shared across all workspaces.

### Circuit Breaker
Detects failure loops and intervenes before wasting more tokens.

## What to Expect

Forge needs real sessions to learn from:

- **Sessions 1-3**: Collecting patterns silently. No warnings yet.
- **Sessions 4-5**: First warnings appear.
- **Sessions 6+**: Warnings get accurate. Score climbs.

## Commands

```bash
# Everyday
forge setup                  # One-time setup
forge score                  # Your Forge Score
forge score --detail         # Full breakdown
forge config                 # View settings
forge stats                  # Workspace stats

# Data
forge list                   # All experiences
forge search -t python       # Search by tag
forge detail PATTERN         # Pattern details
forge record failure         # Manual recording
forge promote ID             # Promote to global

# Automatic (via hooks — you never call these)
forge resume                 # Session start → inject
forge detect                 # Mid-session → warn
forge writeback              # Session end → learn
```

## Configuration

```bash
forge config                       # Basic (10 params)
forge config --advanced            # All (40+ params)
forge config --set alpha=0.15      # Change a value
```

Defaults are pre-optimized. No configuration required.

## Privacy

Everything stays in `~/.forge/forge.db`. Nothing leaves your machine. Plain SQLite — inspect, export, or delete anytime.

## Tech Details

| | |
|---|---|
| Package | [forge-memory](https://pypi.org/project/forge-memory/) |
| Tests | 1,243 passed |
| Dependencies | 2 (typer, pyyaml) |
| Database | SQLite (built-in) |
| Python | 3.12+ |
| License | MIT |

### Built On

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — Q-learning for experience ranking
- **[OpenViking](https://github.com/nicepkg/OpenViking)** — Layered context injection
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Hook system enabling silent learning

## License

MIT
