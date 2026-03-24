[English](README.md) | [한국어](README.ko.md)

# Forge

**Your coding agent keeps making the same mistakes. Forge fixes that.**

[![PyPI](https://img.shields.io/pypi/v/forge-memory?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/forge-memory/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1203_passed-brightgreen?logo=pytest&logoColor=white)](#tech-details)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## The Problem

Every time you start a new Claude Code session, the agent starts from scratch. It doesn't remember that `--no-verify` broke your pipeline yesterday, or that the async handler needs a specific pattern. You end up repeating the same corrections, wasting time and tokens.

## What Forge Does

Forge is an **experience memory layer** for coding agents. Install it once, and it silently:

- **Captures** every failure, decision, and fix from each session
- **Learns** which of those experiences actually helped (using reinforcement learning)
- **Injects** the most useful ones into the next session — before the agent makes the same mistake

Think of it as **long-term memory** that coding agents don't have.

## Why Use Forge

| Without Forge | With Forge |
|---------------|------------|
| Agent repeats the same error across sessions | Agent is warned before it happens |
| You manually correct the same patterns | Corrections are remembered and injected automatically |
| Context window wasted on trial-and-error | Only proven-useful experiences are injected |
| No way to know if your agent is improving | **Forge Score** measures learning effectiveness |
| Guard rails require manual setup | Secret detection, `--no-verify` blocking built-in |
| Each project learns in isolation | Patterns auto-promote across projects |

## Install (3 steps)

### 1. Install

```bash
pip install forge-memory
```

Or with uv (faster):

```bash
uv tool install forge-memory
```

### 2. Setup

```bash
forge setup
```

This single command sets up everything:
- Experience database
- Session hooks (auto-learn on every session)
- Guard hooks (secret detection, safety checks)
- Team skills

It shows you exactly what will change and asks for confirmation.

### 3. Done

That's it. Start coding. Forge works automatically in the background.

After a few sessions, check your score:

```bash
forge score
```

## How It Works

```
  You start a Claude Code session
            |
            v
  [forge resume] loads relevant past experiences
  "Last time you hit this error, here's what fixed it (Q:0.8)"
            |
            v
  You code. Agent hits a familiar error pattern
            |
            v
  [forge detect] warns in real-time
  "Seen this before — try: use async with instead"
            |
            v
  Session ends
            |
            v
  [forge writeback] learns from the session
  - New patterns captured
  - Q-values updated (did the warnings help?)
  - Useful patterns promoted across projects
```

All of this happens through **Claude Code hooks** — no manual intervention.

## Forge Score

One number that tells you how well Forge is working:

```bash
$ forge score

=== Forge Score (workspace: default) ===

  Forge Score:     0.68 / 1.00

  Learning effect:       0.72
  Context hit rate:      0.65
  Token efficiency:      0.58
  Patterns: 47 | Sessions: 23
```

The score goes up as Forge learns what actually helps your agent. Use `forge score --detail` for the full breakdown.

## Key Features

### Automatic Learning
Every session is a learning opportunity. Forge captures failures, tracks whether its warnings helped, and adjusts accordingly. No manual tagging or labeling required.

### Smart Injection
Forge doesn't dump everything it knows into context. It ranks experiences by:
- **Proven effectiveness** — did this warning actually prevent the error last time?
- **Recency** — recent failures are weighted higher
- **Relevance** — tag overlap with the current session

Only the top experiences make it into context, saving tokens.

### Guard Hooks
Built-in protection against common agent failure modes:
- **Secret detection** — catches API keys, tokens, and private keys before they're committed
- **`--no-verify` blocking** — prevents the agent from bypassing pre-commit hooks
- **Session health** — suggests `/compact` when sessions get too long

### Cross-Project Learning
When Forge sees the same pattern in 2+ projects, it automatically promotes it to a global experience. Your learnings carry across projects.

### Adaptive Warning Formats
Forge A/B tests different warning formats and converges on whatever actually helps your specific agent setup. No configuration needed.

### Circuit Breaker
Detects when a session is stuck in a failure loop and intervenes before wasting more tokens.

## Important Notes

### Requirements
- **Python 3.12+**
- **Claude Code** — Forge uses Claude Code's hook system. Other agents are not supported yet.
- `forge` command must be on your **system PATH** (not just inside a virtualenv)

### First Few Sessions
Forge starts with zero knowledge. It needs a few sessions to build up useful patterns. Don't expect improvements on day one — check `forge score` after 5-10 sessions.

### What Forge Is NOT
- **Not an orchestrator** — Forge doesn't control your agent. It advises.
- **Not a test runner** — it learns from real coding sessions, not test suites.
- **Not a replacement for CLAUDE.md** — Forge handles dynamic, session-specific learnings. Static project rules still belong in CLAUDE.md.

### Privacy
All data stays local in `~/.forge/forge.db`. Nothing is sent anywhere. The database is plain SQLite — you can inspect, export, or delete it anytime.

## Commands

Everyday commands:

```bash
forge setup              # Initial setup (run once)
forge score              # Check your Forge Score
forge score --detail     # Full breakdown
forge config             # View settings
forge config --set KEY=VALUE  # Change a setting
forge stats              # Workspace statistics
```

Data management:

```bash
forge list               # List all experiences
forge search -t python   # Search by tag
forge detail PATTERN     # Detailed view
forge record failure     # Manually record a pattern
forge promote ID         # Promote to global
```

These run automatically via hooks (you don't need to call them):

```bash
forge resume             # Session start: inject experiences
forge detect             # Mid-session: real-time warnings
forge writeback          # Session end: learn from transcript
```

## Configuration

```bash
forge config             # View basic settings (10 params)
forge config --advanced  # View all settings (40+ params)
```

All settings are optional. Defaults are pre-optimized. Common ones:

```yaml
# ~/.forge/config.yml
max_tokens: 3000          # Max tokens for context injection
l0_max_entries: 50         # Max patterns to inject
alpha: 0.1                 # Learning rate (higher = faster adaptation)
routing_enabled: true      # Model routing on/off
```

## Tech Details

| Item | Value |
|------|-------|
| Package | [forge-memory](https://pypi.org/project/forge-memory/) |
| Tests | 1,203 (all passing) |
| Dependencies | 2 (typer, pyyaml) |
| Database | SQLite (built-in, zero config) |
| Python | 3.12+ |
| License | MIT |

### References

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — Q-value learning algorithm
- **[OpenViking](https://github.com/nicepkg/OpenViking)** — Layered context loading
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Hook system

## License

MIT
