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

## Think of It Like a New Team Member

Forge is like a junior developer sitting next to your agent — one who quietly watches every session, takes notes, and gets smarter over time.

- **Week 1**: Just observing. Learning your patterns silently.
- **Week 2**: *"Hey, last time you tried that, it broke — here's what worked."*
- **Month 2**: Anticipates problems before they happen. Knows your codebase's quirks.

It's not perfect from day one. But the longer you work together, the better it gets — and unlike a real teammate, it never forgets.

### How It Stays Lean

<img src=".github/assets/flow-diagram.svg" alt="Forge flow diagram" width="100%"/>

**Proven advice only** — Every experience is scored by real outcomes. Helped avoid an error? Score goes up. Got ignored? Goes down. Only high-scoring experiences make it to your next session.

**Fresh over stale** — Recent patterns take priority. A 3-month-old error won't waste tokens every session.

**Self-improving format** — The same warning can be phrased 4 ways. Forge tests which one your agent actually follows, then sticks with what works.

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

**Learns from every session** — Captures failures and fixes automatically. No tagging or labeling needed.

**Only speaks when useful** — Ranks experiences by real outcomes. Your context window stays clean.

**Guards your back** — Catches API keys before commit, blocks `--no-verify`, suggests `/compact` when sessions get long.

**Gets smarter across projects** — Same pattern in 2+ projects? Automatically shared across all your workspaces.

**Breaks the loop** — Detects when a session is stuck repeating the same failure and intervenes.

**Orchestrates agent teams** — Manages multi-agent team runs and automatically collects what worked, what failed, and the best team configurations.

**Routes to the right model** — Picks the optimal model (Haiku/Sonnet/Opus) per task category based on past success rates. No manual configuration needed.

**Self-tunes** — `forge optimize` explores parameter combinations against your actual session data, finds what improves your Forge Score, and applies the best config automatically.

## What to Expect

Forge needs real sessions to learn from — it gets better the more you use it:

- **Sessions 1-3**: Quietly watching. Taking notes.
- **Sessions 4-5**: *"Hey, I've seen this before."* First warnings appear.
- **Sessions 6+**: Anticipating problems. Your Forge Score climbs.

This is by design — no noise until it has something useful to say.

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
