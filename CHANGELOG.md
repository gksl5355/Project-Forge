# Changelog

## [1.1.0] - 2026-03-17

### Added
- Interactive `forge setup` — shows changes, asks before applying (`-y` to skip)
- Skills bundled (spawn-team, doctor, debate, ralph) — no separate repo needed
- Routing config: `routing_n_parallel_min`, `routing_n_files_min`, `max_agents`
- MIT LICENSE
- English-first README with Korean translation (README.ko.md)
- Acknowledgements (MemRL, OpenViking, Claude Code)

### Changed
- `forge setup` replaces `forge init` + `forge install-hooks` as single entry point
- Settings merge: append-only for hooks, warn on env conflicts, auto-backup

### Removed
- Internal docs (IDEA_NOTES, PRDs, architecture, TRD, migration log)
- summary.yml references from Team Orchestrator integration

## [1.0.0] - 2026-03-17

### Added
- Experiment tracking (Schema v4): `experiments` table, unified fitness
- `forge trend` — fitness trend visualization
- `forge research` — extended AutoResearch with experiment recording
- Unified fitness function: auto-interpolates forge-only and TO-integrated modes
- Config/document hashing (SHA256[:12]) for change detection
- Directive model: atomic document decomposition for optimization
- Ablation engine: systematic directive variant generation
- `forge recommend` — team config recommendation from history
- `forge ingest` — team orchestration data collection
- `forge measure` — unified metrics (QWHR + TO success/retry/scope)
- teammate.sh: per-agent model selection via signal files

### Changed
- Schema v3 → v4: experiments table, sessions extension
- `compute_composite_fitness` delegates to `compute_unified_fitness`

## [0.2.0] - 2026-03-15

### Added
- AutoResearch optimizer (`forge optimize`): greedy sweep over config parameters
- Measurement engine (`forge measure`): QWHR, promotion precision, token efficiency
- Vector search (sqlite-vec): cosine similarity for pattern dedup
- LLM extraction: auto-extract failures/decisions from transcripts
- Output analyzer: scriptable pattern learning from tool outputs
- Auto-dedup and auto-ingest in writeback pipeline

## [0.1.0] - 2026-03-13

### Added
- Core Q-value system (MemRL EMA)
- Failure, Decision, Rule, Knowledge models
- L0/L1 context injection via SessionStart hook
- Real-time Bash failure detection via PostToolUse hook
- Writeback pipeline: transcript parsing, Q-update, time decay, promotion
- CLI: record, list, search, detail, edit, promote, stats, decay
- SQLite storage with schema migration (v1 → v2 → v3)
