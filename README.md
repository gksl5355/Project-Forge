[English](README.md) | [한국어](README.ko.md)

# Project Forge

**An experience memory layer for coding agents.**

[![CI](https://github.com/gksl5355/Project-Forge/actions/workflows/ci.yml/badge.svg)](https://github.com/gksl5355/Project-Forge/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1203_passed-brightgreen?logo=pytest&logoColor=white)](#metrics)
[![Dependencies](https://img.shields.io/badge/deps-2_(typer%2C_pyyaml)-blue)](#tech-stack)
[![Schema](https://img.shields.io/badge/schema-v5-orange)](#architecture)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What is Forge?

Forge is an **experience memory layer** that sits between your coding agent sessions. It is not an orchestrator, not a harness — it is the long-term memory that agents lack.

**The problem:** LLM coding agents (Claude Code, Cursor, etc.) start every session from scratch. They repeat the same mistakes, forget yesterday's fixes, and can't learn from past failures.

**Forge solves this by:**

1. **Remembering** — automatically captures failures, decisions, and rules from every session
2. **Learning** — uses reinforcement learning (Q-values) to measure which experiences actually help
3. **Injecting** — feeds the most useful experiences into the next session's context, ranked by proven effectiveness

It runs as **Claude Code hooks** — zero manual intervention after setup.

```
Session Start               Mid-session                 Session End
  forge resume                 forge detect                forge writeback
  ↓                            ↓                           ↓
  Load Q-ranked patterns       Match stderr to DB          Parse transcript
  ↓                            ↓                           ↓
  Inject into context          Warn: "Seen this before,    Update Q-values
  "Last time this failed,       try: use async with"       Record experiment
   here's the fix (Q:0.8)"                                 Auto-promote
```

## Installation

### Step 1: Install

```bash
# pip
pip install git+https://github.com/gksl5355/Project-Forge.git

# or uv (faster)
uv tool install git+https://github.com/gksl5355/Project-Forge.git
```

> **Important:** `forge` must be on your system PATH. Virtual-env-only installs will not work with hooks.

### Step 2: Setup

```bash
forge setup
```

This one command:
- Creates the experience database (`~/.forge/forge.db`)
- Installs learning hooks (session start/end/failure detection)
- Installs guard hooks (secret detection, `--no-verify` blocking)
- Installs team skills (spawn-team, doctor, debate, ralph)
- Patches `~/.claude/settings.json` (append-only, creates backup)

```
=== Forge Setup ===

Hooks & Settings:
  + hooks.SessionStart: resume.sh
  + hooks.SessionEnd: writeback.sh
  + hooks.PostToolUse: detect.sh
  = env.AGENT_TEAMS = 1 (ok)           ← existing value preserved
  ! env.SOME_KEY = X (recommends: Y)   ← conflict shown, not overwritten

Skills:
  + ~/.claude/skills/spawn-team/

Proceed? [Y/n]:
```

- `forge setup -y` to skip confirmation

### Step 3: Done

Start coding. Forge learns automatically from every session.

```bash
# Check your Forge Score after a few sessions
forge score

# View with full breakdown
forge score --detail
```

### For developers (editable install)

```bash
git clone https://github.com/gksl5355/Project-Forge.git
cd Project-Forge
pip install -e ".[dev]"     # or: make dev
forge setup
```

## Features

### Automatic Experience Learning

Every session goes through a learn → remember → inject cycle:

| Phase | Hook | What happens |
|-------|------|-------------|
| **Start** | `forge resume` | Loads top experiences by Q-value, injects into agent context |
| **During** | `forge detect` | Matches stderr/failures against known patterns, warns in real-time |
| **End** | `forge writeback` | Parses transcript, extracts new failures, updates Q-values |

No manual intervention needed. Forge gets smarter with every session.

### Q-Value Learning (MemRL)

Based on [MemRL](https://arxiv.org/html/2601.03192v2) — each experience has a Q-value that measures how useful it actually is:

```
Q ← Q + α(reward - Q)

reward = 1.0  →  Warning helped (failure was avoided)
reward = 0.0  →  Warning ignored (same error repeated)

Time decay: Q *= (1 - 0.005)^days_since_last_used
```

High-Q experiences get shown first. Low-Q ones fade away. The system self-corrects.

### Forge Score

One number that tells you how well Forge is working:

```bash
forge score
# === Forge Score (workspace: default) ===
#
#   Forge Score:     0.68 / 1.00
#
#   학습 효과 (QWHR):     0.72
#   컨텍스트 적중률:       0.65
#   토큰 효율:             0.58
#   패턴: 47개 | 세션: 23개

forge score --detail     # full breakdown with routing, circuit breaker, etc.
```

The score is computed from 8 internal metrics, weighted and optimized through parameter sweeps. You don't need to know the formula — just watch the number go up.

### Smart Context Injection

Forge doesn't dump all experiences at once. It ranks them using:

- **Q-value** — proven effectiveness
- **Recency** — recent failures weighted higher (configurable decay)
- **Relevance** — tag overlap with current session

The top experiences are formatted in a token-efficient format and injected at session start.

### Adaptive Warning Formats

Forge automatically tests different warning formats (A/B testing) and converges on whichever format actually helps your agent more:

- **Essential**: `[WARN] pattern → hint` (minimal tokens)
- **Annotated**: `[WARN] pattern Q:0.75 → hint` (balanced)
- **Concise**: `[WARN] pattern Q:0.75 → hint_short` (default)
- **Detailed**: Full stats with seen/helped counts

### Guard Hooks

Protective hooks that prevent common agent failure modes:

| Hook | What it does |
|------|-------------|
| `block-no-verify.sh` | Blocks `--no-verify` — prevents bypassing pre-commit hooks |
| `guard-secrets.sh` | Detects API keys, tokens, private keys in writes |
| `suggest-compact.sh` | Suggests `/compact` after 50+ tool calls |
| `cost-tracker.sh` | Logs session metrics for efficiency tracking |

### Circuit Breaker

Automatically detects when a session is stuck in a failure loop:

- Tracks consecutive failures and total tool calls per session
- Trips when limits are exceeded (configurable)
- Resets on success

### Model Routing

Learns which LLM model works best for different task types:

```
quick tasks  → claude-haiku-4-5      (fast, cheap)
standard     → claude-sonnet-4-6     (balanced)
deep tasks   → claude-opus-4-6       (thorough)
review       → claude-sonnet-4-6     (good at review)
```

Routing accuracy improves as more session data accumulates.

### Team Orchestration Support

Forge integrates with `/spawn-team` to learn from multi-agent runs:

```bash
forge recommend --complexity MEDIUM
# → sonnet:2+haiku:1 (3 runs, success: 85%, confidence: medium)

forge resume --team-brief
# → Recent team failures + recommended config
```

### Global Promotion

When a pattern appears in 2+ projects, Forge automatically promotes it to a global experience that benefits all workspaces.

## Commands

### Everyday

| Command | Description |
|---------|-------------|
| `forge setup` | Full setup (DB + hooks + skills + settings) |
| `forge score` | View your Forge Score |
| `forge score --detail` | Full score breakdown |
| `forge config` | View/change settings |
| `forge stats` | Workspace statistics |

### Data Management

| Command | Description |
|---------|-------------|
| `forge record failure` | Record a failure pattern with hint |
| `forge record decision` | Record a decision with rationale |
| `forge record rule` | Record a project rule (block/warn/log) |
| `forge list` | List experiences by type |
| `forge detail PATTERN` | Detailed view of a pattern |
| `forge search -t TAG` | Search by tag |
| `forge edit` | Edit existing records |

### Analysis

| Command | Description |
|---------|-------------|
| `forge trend` | Fitness trend over time |
| `forge recommend` | Team config recommendation |
| `forge decay` | Apply time decay to stale patterns |
| `forge promote ID` | Promote to global or knowledge |
| `forge ingest` | Ingest team run data |
| `forge dedup` | Merge duplicate patterns |

### Hooks (automatic, not manually called)

| Command | Trigger | Description |
|---------|---------|-------------|
| `forge resume` | SessionStart | Inject experiences into context |
| `forge detect` | PostToolUse | Real-time failure matching |
| `forge writeback` | SessionEnd | Learn from session transcript |

## Configuration

```bash
forge config                    # view basic settings
forge config --set alpha=0.15   # change a setting
forge config --advanced         # view all parameters (40+)
```

Basic settings (`~/.forge/config.yml`):

```yaml
max_tokens: 3000          # max context tokens for injection
l0_max_entries: 50         # max patterns to show
llm_model: claude-haiku-4-5-20251001
alpha: 0.1                 # EMA learning rate
routing_enabled: true      # model routing on/off
circuit_breaker_enabled: true
```

All settings are optional. Defaults are pre-optimized.

## Architecture

```
forge/
├── cli.py              # Typer CLI (all commands)
├── config.py           # ForgeConfig + YAML loading
├── engines/            # Core engines
│   ├── resume.py       # Session start: context injection
│   ├── detect.py       # Mid-session: failure matching
│   ├── writeback.py    # Session end: learning
│   ├── fitness.py      # Forge Score computation
│   ├── routing.py      # Model routing
│   ├── prompt_optimizer.py  # A/B testing, hint scoring
│   ├── sweep.py        # Parameter optimization
│   └── ...
├── core/               # Core logic
│   ├── qvalue.py       # Q-value EMA updates
│   ├── context.py      # L0/L1 context formatting
│   ├── circuit_breaker.py
│   └── ...
├── storage/            # SQLite storage
│   ├── db.py           # Schema, connections
│   ├── models.py       # Dataclass models
│   └── queries.py      # Raw SQL queries
├── hooks/              # Shell hook templates
└── skills/             # Bundled SKILL.md files
```

**Data flow:**

```
Agent session
  ↓ SessionStart hook
forge resume → DB query → context injection
  ↓ PostToolUse hook (on failure)
forge detect → pattern match → real-time warning
  ↓ SessionEnd hook
forge writeback → transcript parse → Q update → experiment record
```

## What Gets Installed

| Component | Location | Purpose |
|-----------|----------|---------|
| Experience DB | `~/.forge/forge.db` | SQLite — failures, decisions, rules, experiments |
| Learning hooks | `~/.forge/hooks/*.sh` | Session start/end/failure detection |
| Guard hooks | `~/.forge/hooks/*.sh` | Secret guard, no-verify block, compact suggest |
| Team skills | `~/.claude/skills/` | spawn-team, doctor, debate, ralph |
| Settings patch | `~/.claude/settings.json` | Hook registration (append-only, backup created) |
| Config | `~/.forge/config.yml` | Optional overrides (created on first `forge config --set`) |

## Metrics

| Metric | Value |
|--------|-------|
| Tests | 1,203 (all passing) |
| Source modules | 40 |
| Test files | 42 |
| Lines of code | ~8,900 |
| DB schema | v5 |
| External dependencies | 2 (typer, pyyaml) |
| Python | 3.12+ |

## Tech Stack

- **Python 3.12+** — runtime
- **SQLite** — built-in DB, zero config, no external server
- **Typer** — CLI framework
- **PyYAML** — config parsing

## Acknowledgements

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — EMA-based Q-value learning. Core insight: Q measures "hint usefulness", not "failure severity"
- **[OpenViking](https://github.com/nicepkg/OpenViking) (ByteDance)** — L0/L1/L2 layered context loading for token efficiency
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Hook system that makes automatic learning possible

## License

MIT
