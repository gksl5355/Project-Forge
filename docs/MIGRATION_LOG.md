# Migration Log

## 2026-03-17: summary.yml Removal

### Removed
- `summary.yml` generation and read logic from Team Orchestrator
- Occurrence counting system (replaced by Q-value EMA)
- `warn_on_spawn` system (replaced by `forge resume --team-brief`)

### Reason
Forge Q-value EMA provides more accurate experience utility tracking than simple occurrence counting. Single source of truth principle: all learning data lives in forge.db.

### Overlap Resolution
| summary.yml concept | Forge equivalent |
|---------------------|-----------------|
| scope_drift | Failure with Q-value tracking |
| team_success | TeamRun + Knowledge records |
| retry_heavy | Failure with near_miss Q (0.6) |
| warn_on_spawn | `forge resume --team-brief` |
| stats | `forge measure` with TO metrics |
| config recommendation | `forge recommend --complexity X` |

### Replacement Mapping
| Old workflow | New workflow |
|-------------|-------------|
| Read summary.yml at spawn | `forge resume --team-brief` |
| Update summary.yml after run | `forge ingest --auto` (via writeback.sh) |
| Parse stats from summary.yml | `forge measure` |
| Config from summary.yml | `forge recommend` |

### Files Modified
- `docs/internal/PRD.md`: Removed F3/F5 summary.yml spec
- `docs/internal/TRD.md`: Removed "Learning | summary.yml" reference
- `docs/internal/SILOS.md`: Removed summary.yml silo reference
- `docs/getting-started.md`: Removed summary.yml explanation
- `docs/guide/spawn-team.md`: Removed summary.yml output example
- `docs/WORKFLOW.md`: Removed "→ summary.yml" reference
- `.claude/runs/summary.yml`: Deleted

## 2026-03-17: Experiment Tracking System (Schema v4)

### Added
- `experiments` table: DL-style experiment registry with unified fitness tracking
- `sessions` extension: config_hash, document_hash, unified_fitness columns
- Unified fitness function: auto-interpolates between forge-only and TO-integrated modes
- Config and document hashing for change detection
- Directive model: atomic document decomposition for optimization
- Ablation engine: systematic directive variant generation

### Reason
Enable DL-style hyperparameter optimization for both numeric config and document content (CLAUDE.md, SKILL.md). Track every configuration change and its impact on fitness.
