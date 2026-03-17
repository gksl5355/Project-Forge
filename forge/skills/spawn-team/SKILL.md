---
name: spawn-team
description: This skill should be used when the user asks to "create a team", "spawn a team", "start team agents", "set up a dev team", or wants to begin parallel development with Claude Code Agent Teams. Analyzes the project, detects domains, and spawns an optimized team of agents dynamically.
triggers:
  - "spawn team"
  - "create a team"
  - "set up a team"
  - "start team agents"
  - "팀 구성"
  - "팀 스폰"
  - "팀 만들어"
argument-hint: "[project path]"
allowed-tools: Read, Glob, Grep, Bash(git *), Bash(codex *), Bash(find *), Bash(wc *), Bash(rg *), Bash(echo *), Bash(mkdir *), Bash(ln *), Bash(mv *), Bash(sync *), Bash(cat *), Bash(date *), Bash(printf *), Bash(ls *), Bash(tmux *), Bash(test *), Task, TaskCreate, TaskUpdate, TaskList, TeamCreate, TeamDelete, SendMessage, AskUserQuestion
---

## Roles

**Leader** = this skill running as the main Claude session. Not a spawned agent. Leader orchestrates the entire workflow: proposes teams, spawns agents, assigns tasks, reviews results, merges.

---

## Step 0: Init

**Tool preload** (single call, eliminates per-tool latency):
```
ToolSearch: "select:TeamCreate,TeamDelete,Agent,SendMessage,TaskCreate,TaskUpdate,TaskList,AskUserQuestion"
```

Cleanup (tmux mode): kill orphaned `claude-*` tmux sessions from previous runs. Preserve the current session.

Auto-scan (no questions unless needed): package.json/requirements.txt/go.mod → stack, src/app/lib → scale, .git → worktree availability.

Ask only if: non-standard structure can't be auto-detected, or request is ambiguous.

---

## Step 1: Project Analysis + Context Map

Run 1-1, 1-2, 1-3 concurrently (all use fast tools — `rg` preferred over grep, `find` for file listing).

### 1-1. Tech Stack
Detect from package.json, requirements.txt, go.mod, Cargo.toml, etc.

### 1-2. Domain Detection + Structure Type

| Type | Condition | Ownership Model |
|------|-----------|----------------|
| [A] Domain directories (default) | src/auth/**, src/products/** | Directory-level ownership |
| [B] Flat structure (fallback) | src/services/auth.ts, file-per-function | File-level MECE manifest |
| [C] Unclear/Legacy | Domain boundaries unidentifiable | architect-agent first → convert to [A] |

Detection failure → AskUserQuestion for manual spec, or assign 1 fullstack agent.

### 1-3. Context Map Generation (NEW)

Build a compact codebase snapshot using fast scanning. Target: ≤40 lines, generated once, injected into every agent prompt.

**Scan commands (run in parallel, optimized):**
```bash
# Symbol overview per domain (primary signal)
rg --type py "^(class|def |async def )" --with-filename | head -40
rg --type ts "^(export |class |function |interface )" --with-filename | head -40
rg --type go "^(func |type )" --with-filename | head -40

# LOC per domain (identify heavy domains)
find . -name "*.py" -o -name "*.ts" -o -name "*.go" | xargs wc -l 2>/dev/null | sort -rn | head -10
```

**Output format (store in memory as `CONTEXT_MAP`):**
```
## Context Map
stack: {lang} + {framework}

domains & symbols (per domain):
  {dir}/: {N symbols} — {top 3 class/function names}

heavy_files (>200 LOC — use offset+limit):
  {file}: {N} lines
```

**Usage:** Inject `CONTEXT_MAP` into every agent's spawn prompt verbatim.
Agents MUST NOT re-explore files already covered by Context Map.

### 1-4. Domain Scale → Ownership Manifest

- small (1-3 files): merge candidate
- medium (4-9): 1 independent agent
- large (10+): 1 agent (suggest split)

Each file/directory belongs to exactly 1 entry. Shared files → Leader owns.

---

## Step 2: Task-Based Routing

Decompose the user request into components before counting. Even compact requests ("add login") may involve multiple layers (BE, FE, DB, middleware, tests). Always decompose first, then count.

```
N_parallel  = number of tasks that can run simultaneously
N_files     = estimated files to create or modify
LOC_domain  = estimated LOC per domain (rough: small<100, medium 100-400, large 400+)
```

### Step 2-mechanical: Mechanical Transformation Detection

**Before routing:** Check if the task is a large-scale mechanical transformation (mass rename, format enforcement, bulk refactor, systematic code replacement across many files).

**If mechanical transformation detected:**
1. Inform user: suggest `/batch` as preferred tool
```
→ Detected large-scale mechanical transformation. /batch is optimized for this.
  Use: /batch "{instruction}" [--scope src/]
  Better than team: faster, lower token cost, no spawn overhead.
```
2. Ask: proceed with /batch, or override with team? If override → continue to Step 2-routing.

**Examples:** "replace all X with Y", "add logging everywhere", "migrate deprecated API across codebase", "enforce naming convention".
Repetitive identical changes across services (same pattern, different files) → mechanical, even if phrased as "add feature".

**Not mechanical:** "add unique feature per domain", "refactor architecture", "implement new domain".

### Step 2-routing: Routing Decision

```
N_parallel < 3  AND  N_files < 5              → SINGLE AGENT
N_parallel < 3  AND  N_files ≥ 5              → SINGLE AGENT (sequential dependency — team overhead > gain)
N_parallel ≥ 3  AND  N_files < 5              → SINGLE AGENT (overhead > gain for small files)
N_parallel ≥ 3  AND  N_files ≥ 5              → TEAM (coordination overhead justified)
reviewer-only tasks (read-only, no handoffs)  → TEAM (always wins regardless of LOC)
explicit plan request OR structure [C]        → TEAM (COMPLEX)

```

Alternative (legacy): `LOC_domain ≥ 200 → TEAM` still applies. Use file count as additional signal.

Benchmark basis: spawn overhead ~16s/agent; team breaks even at ~200 LOC/domain (~1,200 LOC total) OR ≥5 files.
Below that threshold, single agent is 1.6–3.9× faster due to spawn + messaging overhead.

**Examples:**
```
"Add /health to server.py"                 → 1 task,  1 file, ~10 LOC           → SINGLE (N_parallel < 3)
"Add 3 endpoints to server.py"             → 3 tasks, 1 file, ~90 LOC           → SINGLE (N_files < 5)
"Refactor payment error handling"          → 1 task,  6 files, ~400 LOC         → SINGLE (N_parallel < 3, sequential)
"Add healthcheck to all services"          → 5 tasks, 5 files, ~10 LOC each     → /batch (identical pattern, mechanical)
"Auth + products + orders API (small)"     → 3 tasks, 9 files, ~50 LOC/domain  → TEAM (N_files ≥ 5)
"Auth + products + orders API (full)"      → 3 tasks, 9 files, ~300 LOC/domain → TEAM
"Add login feature"                        → decompose: BE+FE+DB+middleware+test → 4 tasks, 8 files → TEAM
"Refactor all services to async"           → 5+ tasks, 10+ files               → TEAM (COMPLEX)
"Security audit across 3 domains"         → read-only parallel                 → TEAM
```

Ambiguous request → AskUserQuestion ×1, re-estimate, continue.

### Step 2-route: Single Agent Auto-Routing

If routing = SINGLE AGENT:

1. Inform user:
```
→ Small scope detected (spawn overhead > parallelism gain below ~200 LOC/domain).
  Routing to single agent (faster, lower token cost). Use --team to override.
```

2. Inject Context Map into agent prompt. Spawn one general-purpose Agent (no TeamCreate).
3. Agent completes:
   - Run /simplify once on changed files (quality pass)
   - Report results to user. Done. No run artifacts needed.

**Override:** `--team` flag or explicit team request → proceed to Step 5 with 2-agent minimum.

---

## Step 3: Scope Confirmation (MEDIUM/COMPLEX only)

AskUserQuestion ×1:
- **IN**: detected domains + files + shared
- **OUT**: external systems (mock only), CI/CD, performance tuning
- **DEFER**: low-priority domains

After confirmation → scope locked. Change attempts → warning + re-confirmation.

---

## Step 4: Planning (COMPLEX only)

**Opus sub-agent for planning:** Spawn one Opus sub-agent to handle 4-1 + 4-2. Leader (Sonnet) receives the plan and continues from 4-3.
```bash
echo "claude-opus-4-6" > /tmp/claude-team-model-planner
# spawn Agent: name="planner", prompt includes 4-1 interview + 4-2 wave decomp instructions
# Opus returns: interview answers + wave plan → Leader reviews → continues to 4-3
```
SIMPLE/MEDIUM: skip Opus entirely — Leader handles planning directly if needed.

### 4-1. Structured Interview (AskUserQuestion, 3-5 questions)
Q1 core objective / Q2 success criteria ×3 (measurable) / Q3 constraints / Q4 risks / Q5 ordering preference

### 4-2. Wave Decomposition

3–5 waves as needed:
```
Wave 1 (parallel): Foundation — types, schemas, shared interfaces
Wave 2 (parallel): Core — domain logic per agent
Wave 3 (sequential): Integration — cross-domain, shared files
Wave N (parallel): Verification — tests
Wave Final: merge (+ Codex review if requested)
```

**Task format (per task):**
```
Task: {verb} {target} → {expected output}
Accepts: {concrete testable criterion}
BlockedBy: {task-id | none}
```
Rules: ≤10 tasks per agent. Accepts missing → task not issued. Scope ≤200 LOC or 1 module.

### 4-3. Validation

4-criteria check (all must pass):
1. **Clarity** — every task has a concrete Accepts criterion
2. **Verifiability** — Accepts is testable/measurable
3. **Context sufficiency** — agent can execute without asking for missing info
4. **Wave coherence** — Wave order matches dependency direction, no circular deps

**Gap+Risk Review (self-check):** "3 requirements likely missed? 3 ways this plan could fail?" → resolve gaps, surface top risk to user.

---

## Step 5: Team Composition Proposal

**Hard cap: 5 agents. Fully flexible — adapt to the actual task.**

### Model Selection

| Model | Use for |
|-------|---------|
| **Opus** | COMPLEX Step 4 planning only (sub-agent, returns plan to Leader) + Debate. Never for implementation or orchestration. |
| **Sonnet** | Leader orchestration, coordination, judgment, multi-file decisions |
| **Haiku** | Simple/mechanical implementation, test execution, linting, format checks, repetitive verification, MECH sub-agents |
| **Codex (CLI)** | Purely mechanical, zero-context code generation — `gpt-5.4` (see Codex Offloading below) |
| **Codex review** | Debate + pre-merge final review only (read-only) — `gpt-5.4` (no xhigh) |
| **/batch (skill)** | Mechanical transformation of 5+ owned files — agent scopes to its domain, invokes /batch with explicit file list |
| **/simplify (skill)** | Post-implementation quality pass — run once at completion (SINGLE AGENT: after agent, TEAM: Step 8-5 after merge) |

### Team Composition (starting point — adapt freely)

| Task type | Typical composition |
|-----------|---------------------|
| Feature dev, small | fullstack(sonnet) + unit-tester(haiku) |
| Feature dev, medium | domain-be(sonnet) + domain-fe(sonnet) + unit-tester(haiku) |
| Feature dev, large | planner(sonnet) + domain-a(sonnet) + domain-b(sonnet) + tester(haiku) ×2 |
| Test-heavy | tester-unit(haiku) + tester-integration(haiku) + tester-e2e(sonnet) |
| Review/audit | security-reviewer(sonnet) + perf-reviewer(sonnet) + quality(haiku) |
| Migration/refactor | architect(sonnet) + coder-a(sonnet) + coder-b(sonnet) |

Mix freely. Only constraints: 5-agent cap, MECE scope ownership.

### Codex Offloading (use sparingly)

Delegate to Codex only when ALL hold: (1) zero codebase context required, (2) purely mechanical output, (3) result verifiable at a glance.

Good: standalone utility function with fixed signature, standard config file (.eslintrc, .gitignore), empty test file skeleton.
Bad: CRUD touching existing models, type defs referencing existing types, anything reading existing files first.

CLI: `codex exec -m gpt-5.4 --full-auto "{instruction}"`
Claude writes directly for everything else. Codex failure → write directly, no retry.

### Worktree

- 3+ agents → `isolation: "worktree"` (requires git). Apply uniformly, never partial.
- ≤2 agents → shared (omit isolation).
- Git unavailable → fallback to shared, cap ≤2 agents, notify user.

---

## Step 6: User Confirmation

**SIMPLE**: AskUserQuestion ×1 — team composition only. On confirm → spawn + auto-start original request.

**MEDIUM/COMPLEX**: AskUserQuestion ×1 — team composition (COMPLEX: include Wave plan + top risk from Gap+Risk Review). On confirm → spawn.

---

## Step 7: Spawn Team

### 7-entry. Preview Mode (F4)

At Step 7 entry, check for `--preview` flag in user request.

**If `--preview` detected:**
1. Run experience brief (7-pre) via Forge
2. Show preview output:
```
=== PREVIEW (no agents spawned) ===
Complexity: {SIMPLE|MEDIUM|COMPLEX} (score {N})
Team: {agent-list with models}
Ownership: {manifest summary}

Experience (if data exists):
  {experience brief from 7-pre}

Proceed? [y/n/adjust]
```
3. Do NOT create run directory or spawn agents
4. AskUserQuestion: proceed / adjust / cancel
   - proceed → continue to 7-0 (normal flow)
   - adjust → user modifies team/scope → re-preview
   - cancel → exit

**If no `--preview`:** continue to 7-pre → 7-0 (normal flow).

### 7-pre. Experience Brief (F3 — Forge-powered)

Before run initialization, query Forge for past team experience:

```bash
# Get recommended team config for detected complexity
RECOMMEND=$(forge recommend --workspace "$WORKSPACE" --complexity "$COMPLEXITY" 2>/dev/null) || true

# Get team experience brief (Q-ranked failures + recent runs)
BRIEF=$(forge resume --team-brief --workspace "$WORKSPACE" --session-id "team-$(date +%s)" 2>/dev/null) || true
```

If Forge returns data, present to user:

**Show brief summary:**
```
Experience brief (Forge):
  Recommended config: {RECOMMEND output}
  {BRIEF output — team-related failures + recent run history}
```

**Apply to team:**
- Forge `recommend` output → use as default team config proposal
- Team-related failures (high Q) → adjust scope or model to avoid known issues
- Recent run success rates → inform complexity assessment

If Forge returns no data, skip silently (no error, no message).

### 7-0. Run Initialization

Before spawning agents, Leader creates the run directory and initial artifacts.

**Run directory:**
```bash
RUN_DATE=$(date +%Y-%m-%d)
NNN=$(printf "%03d" $(($(ls -d .claude/runs/${RUN_DATE}-* 2>/dev/null | wc -l) + 1)))
RUN_ID="${RUN_DATE}-${NNN}"
RUN_DIR=".claude/runs/${RUN_ID}"
mkdir -p "${RUN_DIR}"
```

Write plan.yml, state.yml, events.yml using the **Write tool**. Symlink via Bash.

**plan.yml** (written once at spawn, never modified):
```yaml
run_id: "{RUN_ID}"
timestamp: "{ISO-8601}"
project: "{project-root}"
task: "{user request summary}"
complexity: SIMPLE | MEDIUM | COMPLEX
score: {4-12}

team:
  - name: {agent-name}
    role: {role}
    model: sonnet | haiku
    owns: ["{glob-patterns}"]

ownership_manifest:
  "{glob-pattern}": {agent-name}
  shared: ["{shared-files}"]
  shared_owner: leader
```

**state.yml** (initialized, then atomically updated throughout run):
```yaml
run_id: "{RUN_ID}"
state_version: 1
phase: PLANNING
updated_at: "{ISO-8601}"
agents: {}
completed: []
in_progress: []
blocked: []
shared_contracts: []
key_decisions: []
next: []
scope_violations: 0
```

**events.yml** (initialized, then append-only):
```yaml
events: []
```

**latest symlink:**
```bash
ln -sfn "${RUN_ID}" .claude/runs/latest
```

After initialization, proceed to agent spawning (7-1).

### 7-1. TeamCreate + Spawn Agents

```
TeamCreate: team_name, description
Spawn ALL agents in a single message (multiple Agent tool calls in one response).
Per agent: subagent_type: "general-purpose", team_name, name: "{domain}-{role}", run_in_background: true
```

**Model routing (via `teammate.sh`):**
Haiku agents: write signal file BEFORE spawn: `echo "claude-haiku-4-5" > /tmp/claude-team-model-{agent-name}`
(Requires: `CLAUDE_CODE_TEAMMATE_COMMAND=~/.claude/teammate.sh` via `install.sh`)

**After all agents spawned:**
- Append events to events.yml per spawned agent
- Update state.yml: add agents to map, set `phase: EXECUTING`
- On spawn failure: TeamDelete rollback, notify user

### 7-2. Agent Prompts

Read `${CLAUDE_SKILL_DIR}/prompts.md` → inject Common Header + role-specific prompt for each agent. Append Wave info (COMPLEX only).

**Always inject CONTEXT_MAP** (generated in Step 1-3) into every agent prompt:
```
## Codebase Context (pre-scanned — do NOT re-explore covered files)
{CONTEXT_MAP verbatim}
```

**Progressive tool disclosure** — include only role-relevant tools in agent prompt:
```
implementation agents:  Read, Edit, Write, Glob, Grep, Bash, /batch, /simplify
tester agents:          Read, Bash, Glob, Grep  (no Write/Edit)
reviewer agents:        Read, Glob, Grep         (no Write/Edit/Bash)
```

**Agent /batch guidance (inject into implementation agent prompts):**
```
- If your task involves large-scale mechanical changes within your scope, use /batch (scoped to your owned files only).
- /batch opens PRs — do NOT merge. Report PR list to Leader.
```

---

## Step 8: Execution & Feedback Loop

### 8-1. Task Distribution

COMPLEX: Task format (Task/Accepts/BlockedBy). MEDIUM: brief Accepts in description. SIMPLE: plain description.
Independent tasks → parallel. Dependent → blockedBy.
COMPLEX: Wave order enforced — Leader sends "WAVE {N} COMPLETE" to gate next Wave.

### 8-1.5. State Management Protocol

**state.yml — atomic write (CRITICAL: never write in-place):**
```
1. Write tool → .claude/runs/${RUN_ID}/state.yml.tmp   (full YAML content)
2. Bash: sync .claude/runs/${RUN_ID}/state.yml.tmp
3. Bash: mv .claude/runs/${RUN_ID}/state.yml.tmp .claude/runs/${RUN_ID}/state.yml
```
Increment `state_version` on every write. Agents detect stale reads by checking version.

**events.yml — append on every meaningful state change:**

Leader appends immediately (not batched). Each event has a monotonic `seq` counter.

Event types:
- Lifecycle: `agent_spawned`, `task_assigned`, `agent_done`, `wave_complete`
- State: `decision_promoted`, `contract_published`, `blocked`, `unblocked`
- Problems: `scope_drift`, `test_result` (FAIL/PASS), `escalation`

```yaml
- seq: {N}
  ts: "{HH:MM:SS}"
  type: {event_type}
  agent: {agent-name}        # if applicable
  detail: "{description}"    # if applicable
```

**Communication layers:**
```
SendMessage (tmux) = ephemeral hint, best-effort, can be lost
state.yml          = authority (Leader-managed, persistent decisions)
events.yml         = audit trail (immutable, append-only)
```

**Decision promotion flow:** Agent reports agreement via SendMessage → Leader writes to `shared_contracts` / `key_decisions` in state.yml → Leader appends `decision_promoted` event to events.yml.

**Agent reads:** state.yml only (for checkpoint: phase, blockers, contracts). Agents never read events.yml during execution.

### 8-2. Progress Updates (mandatory)

Report to user at: each agent completion ("{agent} done — {n}/{total}"), Wave transitions, FAIL escalations.

Mid-run summary file `/tmp/summary-{wave|final}.md` (cap 1500 chars): decisions / open issues / PASS·FAIL counts / next objective.
- COMPLEX: write after each Wave.
- MEDIUM: write once after all agents complete.
- SIMPLE: skip.

### 8-3. Implementation → Test Loop

```
Agent done → tester verifies
  PASS → next phase
  FAIL → report to Leader + agent → fix → re-verify
    2x FAIL → agent self-spawns debugger sub-agent (Haiku, depth-1, read-only) → relay findings → fix
    post-debugger FAIL → AskUserQuestion: "1) Leader intervenes 2) Skip 3) Abort"
```

Build failure: agent self-spawns build-fixer sub-agent (Haiku, depth-1, scoped). Failure → Leader escalation.

Structure [C] — architect-agent (Sonnet, once before coding): analyze legacy → design directory structure → Leader review → user approval → refactor → convert to [A]. Failure → fallback [B].

### 8-4. Merge Protocol

```
Pre-merge: git diff --numstat main → scope check only (no manual inspect; /simplify ran at agent completion)
Scope check: git diff --name-only main | grep -vE "{owned-pattern}" → out-of-scope → revert
/batch PRs: agent reports PR list → Leader merges sequentially in ownership order
Order: 1. shared (Leader) → 2. independent domains → 3. high-dependency → 4. tests
Post-merge: build check → FAIL → build-fixer
Conflicts: same file → AskUserQuestion / different files → Leader auto-resolves
```

Shared type/schema change: non-breaking → approve / breaking → consider Debate → pause affected agents → Leader edits → notify → unit-tester re-run.

### 8-5. Completion

1. scenario-tester → FAIL → fix → re-verify
2. Worktree merge (per 8-4)
3. Quality pass: run /simplify once on all changed files. Then Codex review opt-in only for security/architecture audit: AskUserQuestion: "Run Codex architecture review?" → yes: run ×1 (read-only, gpt-5.4). Failure → skip.
4. Write report.yml + freeze state.yml + lifecycle cleanup (see below)

**Shutdown conditions (AND):** all tasks completed + unit-tester PASS + scenario-tester PASS + (COMPLEX) all Wave criteria satisfied → shutdown_request to each agent individually (no broadcast) → TeamDelete.

**Shutdown procedure:** Send individual `shutdown_request` to each agent. If no `shutdown_approved` within 15 seconds → `Bash: tmux kill-pane -t {paneId}` as fallback. After all agents terminated → cleanup any leftover panes in current session → TeamDelete.

#### report.yml (written at completion)

Leader generates report.yml from events.yml + observed results:

```yaml
run_id: "{RUN_ID}"
duration_minutes: {elapsed}
status: COMPLETED | FAILED | ABORTED

agents:
  - name: {agent-name}
    tasks_completed: {N}
    tasks_failed: {N}
    retries: {N}
    files_changed: ["{file-paths}"]

judgment:
  success_rate: {tasks_completed / total_tasks}
  retry_rate: {tasks_with_retries / total_tasks}
  scope_violations: {count from events.yml}
  escalations: {count}
  verdict: "{one-line human-readable summary}"
```

#### State freeze

After report.yml is written:
- Update state.yml one final time: `phase: COMPLETED`, all agents → `CLEANED`
- No further state.yml writes after freeze

#### Forge ingest (F5 — replaces summary.yml)

After report.yml and state freeze, Leader ingests run data into Forge:

```bash
# Ingest current run data into forge.db
forge ingest --workspace "$WORKSPACE" --run-dir "$RUN_DIR" 2>/dev/null || {
    echo "Warning: forge ingest failed." >&2
}
```

Forge handles all pattern detection and learning:
- `scope_drift` events → Failure entries with Q-value tracking
- High retry counts → Failure entries (near_miss quality)
- Team composition + success rate → TeamRun + Knowledge entries
- Q-value EMA provides superior ranking vs simple occurrence counting
- Global promotion when patterns appear across multiple workspaces

No summary.yml is generated or maintained. Forge is the single source of truth.

#### Lifecycle cleanup

```
Per-agent (after merge):
  1. Delete worktree: git worktree remove {path} (if isolation: "worktree")
  2. Kill tmux pane: tmux kill-pane -t {paneId}
  3. Update state.yml: agent status → CLEANED

Post-run:
  1. state.yml frozen (phase: COMPLETED)
  2. events.yml closed (no more appends)
  3. TeamDelete
```

#### Run archival

Runs older than 7 days are archived:
```bash
# Move old runs to archive
mkdir -p .claude/runs/archive
for dir in .claude/runs/????-??-??-???; do
  age_days=$(( ($(date +%s) - $(date -d "$(basename $dir | cut -d- -f1-3)" +%s)) / 86400 ))
  if [ "$age_days" -gt 7 ]; then
    mv "$dir" .claude/runs/archive/
  fi
done
```

Archival runs on each new spawn (Step 7-0) — clean up before creating new run.

---

## Debate Mode

Adversarial architecture review via Codex (gpt-5.4). Details: `.claude/skills/debate/SKILL.md`.

Hard trigger: irreversible=true or impact=3. Soft: risk score 6+.
6-7 → Leader Judge. 8-9 or hard → User Judge.

---

## Operating Rules

- **Leader reads**: DONE items → `git diff --numstat` check only. High-risk (public API / auth / payment / 100+ LOC / post-FAIL fix) → inspect hunks directly.
- **Idle**: quota consumed only on message. Keep agents alive until done.
- **Messaging**: Use individual `SendMessage` per agent. Avoid `broadcast` — it may skip agents due to registration timing and costs scale with team size.
- **Quota**: 1 agent ≈ 7×. Hard cap: 5 agents. Sub-agents do NOT count toward cap.
- **Sub-agents**: depth-1 only (no nesting). ≤2 per agent. Haiku only. debugger=read-only, build-fixer=scoped edits.
- **File isolation**: own domain only. Shared → Leader. 1 agent per file (MECE). Violation → revert.
- **Testers**: report only, no edits. Peer comms: technical → direct, decisions → Leader.
- **/batch**: Agents invoke within owned scope only. Pass explicit directory or file list — never cross domain boundaries. /batch opens PRs; agent reports PR list to Leader, does NOT merge. Wave gating still applies: /batch in domain-A must complete before domain-B starts if dependency exists.
- **/simplify**: Leader runs once after all agents complete + merge (8-5). Not per-agent — avoids 3× sub-agent cost per implementation agent.
- **Tokens**: `wc -l` before Read → 500+ lines use offset+limit. Explore→Grep→Read (needed parts only). No repeat reads. Extract essentials from tool output. Leader embeds shared context (types, interfaces) into spawn prompts to avoid cross-agent duplicate exploration.
- **Worktree**: sequential merge only. No parallel merges. No direct work on main.
- **Planning**: SIMPLE = none, MEDIUM = scope only (Step 3), COMPLEX = interview + Wave. Scope locked after Step 3.
