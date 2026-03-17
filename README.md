# Project Forge

**Experience learning CLI for coding agents.**

Forge accumulates failures, decisions, rules, and knowledge across coding sessions. It updates their utility via RL-style EMA (MemRL), injects relevant experience into future sessions, and optimizes configuration through DL-style experiment tracking.

## Quick Start

```bash
# Install
uv pip install -e .   # or: pip install -e .

# One-command setup (DB + hooks + team support)
forge setup
```

That's it. Forge will auto-learn from every Claude Code session.

## What Forge Does

```
Session Start              Session End                Mid-session
  forge resume               forge writeback            forge detect
  ↓                          ↓                          ↓
  Load experience            Parse transcript           Match stderr
  ↓                          ↓                          ↓
  Inject L0/L1 context       Q-value update             Warn known pattern
                             Record experiment
                             Auto-promote
```

## Core Features

### Experience Memory
- **Failures** — Pattern + avoid_hint + Q-value. Helpful hints rise, useless ones decay
- **Decisions** — Statement + rationale + status. Track what worked
- **Rules** — Project constraints with enforcement (block/warn/log)
- **Knowledge** — Promoted from high-Q failures, cross-project

### Q-Value Learning (MemRL)
```
Q ← Q + α(r - Q)     α = 0.1
r = 1.0 → warning helped    r = 0.0 → warning failed
Time decay: Q *= (1 - 0.005)^days
```

### Experiment Tracking (v4)
- Every session records: config hash, document hash, unified fitness
- `forge trend` — visualize fitness over time
- `forge research` — auto-optimize config parameters
- `forge research --include-docs` — analyze document directives

### Team Orchestration
- `forge ingest --auto` — collect team run outcomes
- `forge recommend --complexity MEDIUM` — best team config from history
- `forge resume --team-brief` — inject team experience at spawn
- `forge measure` — unified metrics (QWHR + TO success/retry/scope)

## Commands

| Command | Description |
|---------|-------------|
| `forge setup` | One-stop setup (DB + hooks + team env) |
| `forge record failure` | Record a failure pattern |
| `forge record decision` | Record a decision |
| `forge record rule` | Record a project rule |
| `forge record knowledge` | Record knowledge |
| `forge list` | List experiences |
| `forge search -t TAG` | Search by tag |
| `forge detail PATTERN` | Show failure details |
| `forge stats` | Workspace statistics |
| `forge measure` | Optimization metrics |
| `forge trend` | Fitness trend chart |
| `forge optimize` | Auto-optimize config (greedy sweep) |
| `forge research` | Extended AutoResearch with experiment tracking |
| `forge recommend` | Team config recommendation |
| `forge decay` | Apply time decay |
| `forge promote ID` | Promote to global/knowledge |
| `forge ingest` | Ingest team orchestration data |
| `forge dedup` | Deduplicate similar patterns |

## How `forge setup` Works

```bash
forge setup
# [1/3] DB initialized.           → ~/.forge/forge.db
# [2/3] Hooks + teammate.sh installed.
#   ~/.forge/hooks/resume.sh      → SessionStart hook
#   ~/.forge/hooks/writeback.sh   → SessionEnd hook
#   ~/.forge/hooks/detect.sh      → PostToolUse hook
#   ~/.forge/hooks/teammate.sh    → Team model selector
#   ~/.claude/settings.json       → Hooks + env patched
# [3/3] Setup complete.
```

## Configuration

`~/.forge/config.yml` (all optional):

```yaml
# Context injection
l0_max_entries: 50
l1_project_entries: 3
l1_global_entries: 2
forge_context_tokens: 2500

# Learning
alpha: 0.1
decay_daily: 0.005

# Team routing thresholds
routing_n_parallel_min: 3
routing_n_files_min: 5
max_agents: 5
```

## Tech Stack

- Python 3.12+ / SQLite (built-in) / Typer / PyYAML

## Docs

- [Architecture](docs/architecture/ARCHITECTURE_v0.2.md)
- [Migration Log](docs/MIGRATION_LOG.md)

---

# Project Forge (한국어)

**코딩 에이전트를 위한 경험 학습 CLI.**

Forge는 코딩 세션의 실패/결정/규칙/지식을 축적하고, MemRL EMA로 경험 가치를 갱신하며, DL 스타일 실험 추적으로 설정을 자동 최적화합니다.

## 설치

```bash
uv pip install -e .
forge setup    # DB + hooks + 팀 환경 한번에 설정
```

## 핵심 명령

```bash
forge record failure -p "패턴명" -h "회피 힌트"    # 실패 기록
forge list --type failure --sort q                 # Q값 순 조회
forge measure                                       # 메트릭 측정
forge trend                                         # fitness 추이
forge research --max-rounds 50                      # 자동 최적화
forge recommend --complexity MEDIUM                  # 팀 구성 추천
```

## 자동 학습 흐름

1. 세션 시작 → `forge resume`이 경험 주입
2. 코딩 중 → `forge detect`이 실패 패턴 경고
3. 세션 종료 → `forge writeback`이 Q값 갱신 + 실험 기록
4. 팀 실행 후 → `forge ingest`이 런 데이터 수집
