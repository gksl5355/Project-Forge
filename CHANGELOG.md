# Changelog

## [1.2.0] - 2026-03-24

### Added
- **PyPI distribution**: `pip install forge-memory`
- **`forge score`** — Forge Score with clean output (`--detail` for full breakdown)
- **`forge config`** — tiered settings (`--advanced` for all 40+ params, `--set KEY=VALUE`)
- **Adaptive warning formats**: 4 variants (essential/annotated/concise/detailed) with A/B testing
- **Recency decay options**: exponential, exponential_slow, linear
- **pip-only install support**: requirements.txt, Makefile (auto-detects uv/pip)
- **CI**: dual testing (uv + pip), auto-publish to PyPI on tag push
- **Circuit breaker**: auto-detect stuck sessions
- **Model routing**: learn best model per task category

### Changed
- KPI weights optimized via parameter sweep
- `forge measure` → hidden (use `forge score` instead)
- Internal tuning tools removed from public distribution
- README fully rewritten: user-first structure with benefits, caveats, step-by-step install

## [1.1.0] - 2026-03-17

### Added
- Interactive `forge setup` — shows changes, asks before applying (`-y` to skip)
- Skills bundled (spawn-team, doctor, debate, ralph)
- MIT LICENSE
- English-first README with Korean translation

### Changed
- `forge setup` replaces `forge init` + `forge install-hooks` as single entry point
- Settings merge: append-only for hooks, warn on env conflicts, auto-backup

## [1.0.0] - 2026-03-17

### Added
- Experiment tracking (Schema v4): unified fitness
- `forge trend` — fitness trend visualization
- `forge research` — AutoResearch with experiment recording
- `forge recommend` — team config recommendation
- `forge ingest` — team orchestration data collection
- `forge measure` — unified metrics

## [0.2.0] - 2026-03-15

### Added
- AutoResearch optimizer (`forge optimize`)
- Measurement engine (`forge measure`)
- Vector search (sqlite-vec)
- LLM extraction: auto-extract from transcripts
- Auto-dedup in writeback pipeline

## [0.1.0] - 2026-03-13

### Added
- Core Q-value system (MemRL EMA)
- Failure, Decision, Rule, Knowledge models
- L0/L1 context injection
- Real-time failure detection
- Writeback pipeline
- SQLite storage with schema migration
