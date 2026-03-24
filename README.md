[English](README.md) | [한국어](README.ko.md)

# Project Forge

**Make your coding agent learn from its mistakes.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1069_passed-brightgreen?logo=pytest&logoColor=white)](#metrics)
[![Dependencies](https://img.shields.io/badge/deps-2_(typer%2C_pyyaml)-blue)](#tech-stack)
[![Schema](https://img.shields.io/badge/schema-v5-orange)](#experiment-tracking)
[![Hooks](https://img.shields.io/badge/hooks-7_active-purple)](#guard-hooks)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/gksl5355/Project-Forge?style=flat&logo=github)](https://github.com/gksl5355/Project-Forge)

---

Ever had Claude Code repeat the same mistake across sessions? Forget a fix you found yesterday? Forge automatically remembers what went wrong, what worked, and injects that experience into every future session.

## How it works

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

**Install once, forget about it.** Forge runs as Claude Code hooks — no manual intervention needed.

## Quick start

### With pip (Python 3.12+ required)

```bash
# Option A: pip (global install)
pip install git+https://github.com/gksl5355/Project-Forge.git

# Option B: uv (recommended)
uv tool install git+https://github.com/gksl5355/Project-Forge.git

forge setup
```

> **Note:** Forge hooks require the `forge` command to be globally accessible.
> If you use a virtual environment or `uv run` only, the hooks will silently fail because they can't find the command on PATH.

**For developers** (editable install — code changes apply immediately):

```bash
git clone https://github.com/gksl5355/Project-Forge.git
cd Project-Forge
uv tool install -e .
forge setup
```

Or install from source with dev dependencies:

```bash
git clone https://github.com/gksl5355/Project-Forge.git
cd Project-Forge
pip install -e ".[dev]"
```

### With uv

```bash
uv pip install git+https://github.com/gksl5355/Project-Forge.git
forge setup
```

Or install from source:

```bash
git clone https://github.com/gksl5355/Project-Forge.git
cd Project-Forge
uv pip install -e ".[dev]"
```

`forge setup` shows exactly what will change and asks before applying:

```
=== Forge Setup ===

Hooks & Settings:
  + hooks.SessionStart: resume.sh
  + hooks.SessionEnd: writeback.sh
  = env.AGENT_TEAMS = 1 (ok)              ← existing value preserved
  ! env.SOME_KEY = X (Forge recommends: Y) ← conflict shown, not overwritten

Skills:
  + ~/.claude/skills/spawn-team/
  + ~/.claude/skills/doctor/

Proceed? [Y/n]:
```

- `+` added / `=` already set / `!` differs from recommended (warning only)
- `settings.json.bak` backup created before any change
- `forge setup -y` to skip confirmation

## What gets installed

| Component | Location | Purpose |
|-----------|----------|---------|
| Experience DB | `~/.forge/forge.db` | SQLite. Failures, decisions, rules, experiments |
| Learning hooks | `~/.forge/hooks/*.sh` | Session start/end/failure detection |
| Team skills | `~/.claude/skills/` | spawn-team, doctor, debate, ralph |
| Model router | `~/.forge/hooks/teammate.sh` | Per-agent model selection |
| Settings patch | `~/.claude/settings.json` | Hooks + env (append-only merge) |

## Guard hooks

Forge v1.2 adds protective hooks that run automatically alongside the learning hooks:

| Hook | Trigger | What it does |
|------|---------|-------------|
| `block-no-verify.sh` | PreToolUse (Bash) | Blocks `--no-verify` flag — prevents Claude from bypassing pre-commit hooks that Forge depends on |
| `guard-secrets.sh` | PreToolUse (Write/Edit) | Detects AWS keys, GitHub PATs, API keys, private keys in content; warns on writes to `.env`/`.pem`/credential files |
| `suggest-compact.sh` | PreToolUse (Edit/Write) | Tracks tool call count per session, suggests `/compact` at 50 calls and every 25 after |
| `cost-tracker.sh` | Stop | Logs session events to `~/.claude/metrics/costs.jsonl` for TokenEfficiency measurement |

**Why these exist:** Claude tends to `--no-verify` when hooks fail (breaking Forge's learning pipeline), hardcode secrets during debugging, and degrade in quality during long sessions. These hooks prevent the most common failure modes automatically.

### `/verify` command

PR-ready check in one command:

```
/verify
→ Tests + Coverage | Lint (ruff) | Format | Debug print audit | Change scope
→ Ready for PR: YES/NO
```

## Q-value learning

Based on [MemRL](https://arxiv.org/html/2601.03192v2) EMA with convergence guarantee:

```
Q ← Q + α(r - Q)     α = 0.1

r = 1.0  →  Warning helped (failure avoided next time)
r = 0.0  →  Warning ignored (same error repeated)

Time decay: Q *= (1 - 0.005)^days_since_last_used
```

High-Q experiences get injected first. Low-Q ones fade away. The system self-corrects.

| Initial Q | Hint quality | Meaning |
|-----------|-------------|---------|
| 0.6 | near_miss | Almost got it right |
| 0.5 | preventable | Could have been avoided |
| 0.3 | environmental | External/env issue |

## Experiment tracking

Every session records a config hash, document hash, and unified fitness score:

```bash
forge measure
#   QWHR: 0.72 | Promotion precision: 0.60 | Unified fitness: 0.6845

forge trend -n 20
#   Time             | Fitness | Config   | Type
#   2026-03-17 15:42 | 0.6845  | a2f4c1   | auto
#   2026-03-17 14:30 | 0.6614  | a2f4c1   | manual

forge research --max-rounds 50    # auto-optimize config parameters
```

## Team orchestration

```bash
forge recommend --complexity MEDIUM
# → sonnet:2+haiku:1 (3 runs, success: 85%, confidence: medium)

forge resume --team-brief
# → Recent team runs + team-related failure patterns
```

The bundled `/spawn-team` skill calls these automatically.

## Commands

| Command | Description |
|---------|-------------|
| `forge setup` | Full setup (DB + hooks + skills). Shows changes, asks before applying |
| `forge record failure` | Record a failure pattern with hint and quality |
| `forge record decision` | Record a decision with rationale |
| `forge record rule` | Record a project rule (block/warn/log) |
| `forge list` | List experiences by type |
| `forge detail PATTERN` | Detailed view of a failure pattern |
| `forge search -t TAG` | Search by tag |
| `forge stats` | Workspace statistics |
| `forge measure` | Compute optimization metrics + unified fitness |
| `forge trend` | Fitness trend over time |
| `forge optimize` | Greedy sweep over config parameters |
| `forge research` | Extended AutoResearch with experiment recording |
| `forge recommend` | Team config recommendation from history |
| `forge decay` | Apply time decay to stale patterns |
| `forge promote ID` | Promote failure to global or knowledge |
| `forge ingest` | Ingest team orchestration run data |
| `forge dedup` | Merge duplicate patterns |

## Configuration

`~/.forge/config.yml` — all optional, sensible defaults:

```yaml
# Context injection
l0_max_entries: 50
forge_context_tokens: 2500

# Learning
alpha: 0.1
decay_daily: 0.005

# Team routing
routing_n_parallel_min: 3
routing_n_files_min: 5
max_agents: 5
```

## Metrics

| Metric | Value |
|--------|-------|
| Tests | 846 (all passing) |
| Source modules | 32 |
| Test files | 32 |
| Lines of code | ~10,700 |
| DB schema version | v4 |
| External dependencies | 2 (typer, pyyaml) |
| Python | 3.12+ |

## Tech stack

- **Python 3.12+** — runtime
- **SQLite** — built-in DB, no external server
- **Typer** — CLI framework (argument parsing, help generation)
- **PyYAML** — config file parsing

## Acknowledgements

Forge's design is influenced by:

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — EMA-based Q-value update with convergence guarantee. The core insight: Q measures "hint usefulness", not "failure severity"
- **[OpenViking](https://github.com/nicepkg/OpenViking) (ByteDance)** — L0/L1/L2 layered context loading for token-efficient experience injection
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Hook system (SessionStart/SessionEnd/PostToolUse) that makes automatic learning possible

## License

MIT
