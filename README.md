# Project Forge

**Stateful memory runtime for coding agents.**

Project Forge helps coding agents resume long-running work across sessions, avoid repeated failures, preserve decision rationale, and enforce repo-specific rules.

## Problem

Coding agents are powerful but lose context between sessions. They repeat failed approaches, forget why decisions were made, and inconsistently apply project rules. Resuming work requires manually re-gathering scattered logs and files.

## What It Does

- **Task Memory** — Structured task state that persists across sessions
- **Failure Memory** — First-class failure tracking to prevent repeated mistakes
- **Decision Log** — Records rationale, alternatives, and tradeoffs for every key decision
- **Repo Rules** — Enforces project-specific constraints (test-first, no SQLite, etc.)
- **Vector Retrieval** — Semantic recall of relevant context via embeddings
- **Session Resume** — Auto-assembles minimal context to continue where you left off
- **Write-back Lifecycle** — Updates memory after execution and evaluation

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL
- **Vector DB**: Qdrant
- **Embeddings**: BGE-M3 or equivalent

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────┐
│  Agent/CLI   │────▶│  Memory API  │────▶│ Postgres│
│  Adapters    │     │  (FastAPI)   │────▶│ Qdrant  │
└─────────────┘     └──────────────┘     └─────────┘
       │                    │
       │              ┌─────┴──────┐
       └─────────────▶│  Resume    │
                      │  Context   │
                      │  Builder   │
                      └────────────┘
```

## Project Structure

```
project-forge/
├─ apps/
│  ├─ api/          # FastAPI application
│  └─ worker/       # Embedding & write-back workers
├─ domain/          # Core domain logic
├─ infra/           # DB, Qdrant, config
├─ adapters/        # Claude Code, Codex, generic CLI
├─ docs/            # PRD, ADR, API docs
├─ scripts/
└─ tests/
```

## Status

**v0.1 — Early Development**

## License

TBD
