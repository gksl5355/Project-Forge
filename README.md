[English](README.md) | [한국어](README.ko.md)

# Forge

**Stop re-debugging what your agent already solved yesterday.**

[![PyPI](https://img.shields.io/pypi/v/forge-memory?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/forge-memory/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1100%2B_passed-brightgreen?logo=pytest&logoColor=white)](#tech-details)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## The Problem

Every Claude Code session starts from scratch. The agent doesn't remember that `--no-verify` broke your pipeline yesterday, or that the async handler needs a specific pattern. You end up repeating the same corrections — wasting time and tokens on problems you've already solved.

## What Forge Does

Forge gives your coding agent **long-term memory**.

Install it once, and it silently captures every failure and fix from each session, learns which experiences actually helped (using reinforcement learning), and injects the most useful ones into the next session — before the agent makes the same mistake.

On your next session, Forge shows up with: *"Last time you hit this error, you fixed it with async context managers (Q:0.8)"* — before you waste time rediscovering the same fix.

## Why Use Forge

### Comparison: How do you handle agent mistakes today?

| | No tool | CLAUDE.md only | **Forge** |
|---|---|---|---|
| **Error repetition** | Same error every session | Reduced if you wrote a rule | Automatically warned before it happens |
| **Knowledge capture** | Lost when session ends | You write rules manually | Auto-captured from every session |
| **Maintenance effort** | None (but pain accumulates) | You maintain every rule | Zero — learns and forgets on its own |
| **Cross-project sharing** | None | Copy-paste between repos | Auto-promotes after 2+ projects |
| **Effectiveness tracking** | No way to measure | No way to measure | **Forge Score** — 8 metrics tracked |
| **Secret leak protection** | None | None | Built-in detection (API keys, tokens) |
| **Session failure detection** | Manual | Manual | Real-time pattern matching |
| **Context token cost** | N/A | Static (always same size) | Dynamic — only injects what's proven useful |

### Forge + CLAUDE.md — use both

They solve different problems:

| | Forge | CLAUDE.md |
|---|---|---|
| **Content** | Dynamic patterns from real sessions | Static rules you define |
| **Example** | "This async pattern caused timeouts 3 sessions in a row" | "Always use `async with` for DB" |
| **Updates** | Automatic (Q-value RL, time decay) | Manual (you edit) |
| **Scope** | Cross-project (global promotion) | Single project |

CLAUDE.md sets the rules. Forge handles the exceptions your rules can't cover.

### Forge by the numbers

| | |
|---|---|
| **Setup time** | ~30 seconds (`forge setup`) |
| **Runtime dependencies** | 2 (typer, pyyaml) — no heavy frameworks |
| **Data storage** | Single SQLite file, local only |
| **Experience types tracked** | 5 (failures, decisions, rules, knowledge, experiments) |
| **Metrics tracked per session** | 8 KPIs (learning, routing, efficiency, etc.) |
| **Warning formats** | 4 variants, auto-selected via A/B testing |
| **Guard hooks** | 4 (secret detection, no-verify block, compact suggest, cost tracking) |
| **Tests** | 1,100+ (all passing) |

## Install

### 1. Install

```bash
pip install forge-memory
```

Or with uv (faster):

```bash
uv tool install forge-memory
```

> `forge` must be on your system PATH. `uv tool install` handles this automatically. If using `pip`, install globally (not in a virtualenv).

### 2. Setup

```bash
forge setup
```

Takes about 30 seconds. Sets up the experience database, session hooks, guard hooks, and team skills. Shows you exactly what will change and asks for confirmation.

### 3. Verify

```bash
forge stats
```

You should see `0 failures, 0 sessions`. Forge is ready. Start coding normally.

### What to Expect

Forge needs real sessions to learn from. Here's what happens:

- **Sessions 1-3**: Forge is learning. Patterns accumulate silently.
- **Sessions 4-5**: First warnings appear. Forge starts injecting relevant experiences.
- **Sessions 6+**: Warnings get smarter. Your Forge Score climbs.

This is by design — Forge avoids injecting noise. Run `forge score` after a few sessions to watch progress.

## Forge Score

One number that tells you how well Forge is working:

```
$ forge score

=== Forge Score (workspace: default) ===

  Forge Score:     0.68 / 1.00

  Learning effect:       0.72
  Context hit rate:      0.65
  Token efficiency:      0.58
  Patterns: 47 | Sessions: 23
```

**Reading the score**: Above 0.5 means Forge is helping more than it's missing. Above 0.7 means your agent is actively benefiting from past sessions. Use `forge score --detail` for the full breakdown.

## Key Features

### Automatic Learning
Every session is a learning opportunity. Forge captures failures, tracks whether its warnings helped, and adjusts accordingly. No manual tagging or labeling needed.

### Smart Context Injection
Forge ranks experiences by proven effectiveness, recency, and relevance — then injects only the top ones. Your context window stays clean.

### Guard Hooks
Built-in protection against common agent failures:
- **Secret detection** — catches API keys, tokens, and private keys before they're committed
- **`--no-verify` blocking** — prevents bypassing pre-commit hooks
- **Session health** — suggests `/compact` when sessions get too long

### Cross-Project Learning
When Forge sees the same pattern in 2+ projects, it automatically promotes it to a global experience that benefits all your workspaces.

### Adaptive Warning Formats
Forge A/B tests different warning formats and converges on whatever actually helps your specific agent. No configuration needed.

### Circuit Breaker
Detects when a session is stuck in a failure loop and intervenes before wasting more tokens.

## Is Forge for You?

- You use Claude Code regularly (3+ sessions per week) — **yes**
- You notice the agent hitting the same errors across sessions — **yes**
- You want to stop repeating the same fixes — **yes**
- You use Cursor / Copilot / other agents — **not yet** (Claude Code only for now)

## Commands

**Everyday:**

```bash
forge setup              # Initial setup (once)
forge score              # Check your Forge Score
forge score --detail     # Full breakdown
forge config             # View settings
forge stats              # Workspace statistics
```

**Data management:**

```bash
forge list               # List all experiences
forge search -t python   # Search by tag
forge detail PATTERN     # Detailed view
forge record failure     # Manually record a pattern
forge promote ID         # Promote to global
```

**Automatic (via hooks — you don't call these):**

```bash
forge resume             # Session start → inject experiences
forge detect             # Mid-session → real-time warnings
forge writeback          # Session end → learn from transcript
```

## Configuration

```bash
forge config                    # View basic settings (10 params)
forge config --advanced         # View all settings (40+ params)
forge config --set alpha=0.15   # Change a setting
```

All settings are optional. Defaults are pre-optimized.

## Privacy

All data stays local in `~/.forge/forge.db`. Nothing is sent anywhere. The database is plain SQLite — inspect, export, or delete it anytime.

## Tech Details

| Item | Value |
|------|-------|
| Package | [forge-memory](https://pypi.org/project/forge-memory/) |
| Tests | 1,100+ (all passing) |
| Dependencies | 2 (typer, pyyaml) |
| Database | SQLite (built-in, zero config) |
| Python | 3.12+ |
| License | MIT |

### Inspired By

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — The Q-learning algorithm behind Forge's experience ranking
- **[OpenViking](https://github.com/nicepkg/OpenViking)** — Inspired Forge's layered context injection for token efficiency
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — The hook system that makes silent learning possible

## License

MIT
