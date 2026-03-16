# Project Forge

**Experience learning CLI for coding agents.**

Project Forge accumulates failure patterns, decisions, rules, and knowledge across coding sessions, updates their utility via RL-style EMA ([MemRL](https://arxiv.org/html/2601.03192v2)), and injects relevant experience into future sessions through Claude Code hooks.

## Key Features

- **Failure Memory** — First-class failure tracking with `avoid_hint`, `hint_quality`, and Q-value scoring
- **Q-Value Learning** — MemRL EMA formula (`Q ← Q + α(r - Q)`) with time decay. Useful hints rise, useless ones sink
- **Cross-Project Learning** — Failures seen in 2+ projects auto-promote to global knowledge
- **Context Injection** — L0/L1 layered loading at session start (~3000 tokens budget)
- **Real-time Detection** — PostToolUse hook catches Bash failures and warns against known patterns
- **Decision Log** — Records rationale, alternatives, and status (active/superseded)
- **Rules Engine** — Per-project constraints with enforcement modes (block/warn/log)

## How It Works

```
Session Start (hook)     Session End (hook)       Mid-session (hook)
  forge resume             forge writeback          forge detect
    ↓                        ↓                        ↓
  Query SQLite             Parse transcript        Match stderr
    ↓                        ↓                        ↓
  Build L0/L1 context      Extract failures        Warn if known
    ↓                        ↓                        pattern
  Inject into Claude       Update Q-values
                           Check promotions
```

## Install

```bash
pip install -e .
forge init
forge install-hooks
```

## Quick Start

```bash
# Record a failure
forge record failure \
  -p "async_connection_leak" \
  -h "Use async with for session scope" \
  -q near_miss \
  -t fastapi -t async

# Record a decision
forge record decision \
  --statement "Use FastAPI over Flask" \
  --rationale "async support, auto docs"

# Record a rule
forge record rule \
  --text "Run tests before commit" \
  --mode warn

# View experiences
forge list --type failure --sort q
forge detail async_connection_leak
forge search -t fastapi
forge stats
```

## Claude Code Integration

After `forge install-hooks`, three hooks are registered:

| Hook | Event | What it does |
|------|-------|-------------|
| `forge resume` | SessionStart | Injects L0/L1 experience context |
| `forge writeback` | SessionEnd | Parses transcript, updates Q-values |
| `forge detect` | PostToolUse (Bash) | Real-time failure pattern warning |

## Q-Value System

Based on [MemRL](https://arxiv.org/html/2601.03192v2) EMA with convergence guarantee:

```
Q ← Q + α(r - Q)     α = 0.1

r = 1.0  →  Warning helped (failure avoided)
r = 0.0  →  Warning failed (same error again)
r = 0.5  →  Unrelated work (neutral)

Time decay: Q *= (1 - 0.005) ^ days_since_last_used
```

Initial Q by hint quality: `near_miss: 0.6` / `preventable: 0.5` / `environmental: 0.3`

## Configuration

`~/.forge/config.yml` (all optional, defaults apply):

```yaml
context:
  max_tokens: 3000
  l0_max_entries: 50
  l1_project_entries: 3
  l1_global_entries: 2

learning:
  alpha: 0.1
  decay_daily: 0.005
  q_min: 0.05
  promote_threshold: 2
```

## Tech Stack

- Python 3.10+
- SQLite (built-in)
- Typer (CLI)
- PyYAML (config)

---

# Project Forge (한국어)

**코딩 에이전트를 위한 경험 학습 CLI 도구.**

Project Forge는 코딩 세션에서 발생한 실패 패턴, 의사결정, 규칙, 지식을 구조화하여 축적하고, MemRL 기반 EMA로 경험의 가치를 갱신하며, Claude Code hooks를 통해 다음 세션에 관련 경험을 자동 주입합니다.

### 핵심 기능

- **실패 기억** — avoid_hint + hint_quality + Q값으로 실패 패턴 추적
- **Q값 학습** — MemRL EMA (`Q ← Q + α(r - Q)`). 유용한 힌트는 올라가고, 쓸모없는 건 가라앉음
- **크로스 프로젝트 학습** — 2개 이상 프로젝트에서 반복된 실패는 전역으로 자동 승격
- **컨텍스트 주입** — L0/L1 계층 로딩으로 세션 시작 시 ~3000 토큰 내 경험 주입
- **실시간 감지** — PostToolUse hook으로 Bash 실패 시 기존 패턴과 매칭하여 즉시 경고
- **의사결정 로그** — 근거, 대안, 상태(active/superseded) 기록
- **규칙 엔진** — 프로젝트별 제약 (block/warn/log)

### 설치 및 시작

```bash
pip install -e .
forge init
forge install-hooks
```

### 문서

- [아이디어 노트](docs/IDEA_NOTES.md)
- [PRD v0.2](docs/prd/PRD_v0.2.md)
- [Architecture v0.2](docs/architecture/ARCHITECTURE_v0.2.md)
- [TRD v0.2](docs/trd/TRD_v0.2.md)
