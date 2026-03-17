---
name: debate
description: Adversarial architecture review using Codex (gpt-5.4). Standalone or auto-triggered within spawn-team. Use on "debate", "architecture review", "design review".
triggers:
  - "debate"
  - "architecture review"
  - "design review"
  - "아키텍처 토론"
  - "설계 검토"
allowed-tools: Read, Glob, Grep, Bash(codex *), Bash(cat > /tmp/debate*), AskUserQuestion
---

# Debate Mode — Adversarial Architecture Review

Submit a design proposal to Codex (gpt-5.4) for adversarial review to eliminate blind spots.

**Invoke:** `/debate "JWT vs Session Auth"` (standalone) or auto-enter via spawn-team hard/soft triggers.
Standalone: use argument as decision subject; if none, collect via AskUserQuestion.

## Step 1: Entry Decision

**Hard trigger (always):** irreversible=true (DB schema, external API, auth) or impact=3 (system-wide).
**Soft trigger (risk 6+):** explicit user request or 2+ technical alternatives & team-wide impact.

**Risk score (each 1-3, summed):**

| Axis | 1 | 2 | 3 |
|------|---|---|---|
| Uncertainty | Proven pattern | Partially uncertain | Experimental |
| Impact scope | Single service | ≤2 domains | System-wide |
| Complexity | Simple | Moderate | Cross-layer |

- 6-7 → Leader Judge (document rationale) / 8-9 or hard → User Judge
- impact=3 or irreversible=true → hard trigger regardless of score. On disagreement, adopt higher score.

## Step 2: Draft Proposal

### Required Fields
```
## Decision subject: {what}
## Context: {current state, 3 sentences max}
## Proposed direction: {direction + rationale}
## Alternatives: {rejection reason, one line each}
## Non-functional: perf/{X} | cost/{X} | security/{X} | availability/{X} | rollback/{X}
## Risk: uncertainty:{1-3} impact:{1-3} complexity:{1-3} = {sum}/9 | irreversible:{bool}
## Concerns: {self-critique}
```

Token budget: target 1500 chars, max 3000. If over, keep only decision subject / non-functional / risk.

## Step 3: Codex Critique

### CLI (file-based — prevents shell escaping issues)
```bash
cat > /tmp/debate-input.md << 'DEBATE_EOF'
{proposal}
DEBATE_EOF

codex exec -m gpt-5.4 -s read-only \
  "$(cat /tmp/debate-input.md)" 2>&1
```

### Critic Output Format (enforced)
```
[BLOCK|TRADEOFF|ACCEPT] {category}: {one-line summary}
- Problem / Impact / Rationale / Fix / Risk-if-ignored
```

- **BLOCK**: Core requirement unmet, ship-blocking (data integrity, security, SLO)
- **TRADEOFF**: Met but increased cost/complexity
- **ACCEPT**: Immediately actionable improvement

Format non-compliance → 1 retry. Unsupported critique → may dismiss. BLOCK dismissal disagreement → user escalation.

## Step 4: Round Processing (max 2 + 1 exception)

**R1**: Proposal → Codex → no BLOCK → early exit / BLOCK → R2.
**R2**: Address BLOCKs + verification plan → re-review → resolved → Judge / persistent → AskUserQuestion.
- R2 scope: **judge existing BLOCKs only**. New issues → document as TRADEOFF.
- Promoting new issue to BLOCK requires changed premise (exception R3).

**R3 (exception)**: Only when new constraints/facts change the premise. Otherwise → AskUserQuestion escalation.

## Step 5: Judge Decision

6-7 → Leader / 8-9 or hard → User / BLOCK dismissal disagreement → User.

Persistent BLOCK → AskUserQuestion: "1) Leader decides 2) Revisit direction 3) Additional round (new evidence only)" default: 2.

## Step 6: Document Result

```
## Debate Result (Round {N})
Adopted: {choice} | Risk: {X}/9 irreversible:{bool} → Judge: Leader/User
Accepted: [{category}] {critique} → {resolution} | Verification: {method}
Rebutted: [{category}] {critique} → {rationale}
Open TRADEOFFs: [{category}] {content} → {acceptance reason}
Rationale: {why this decision}
```

Standalone mode: save to `/tmp/debate-result-{timestamp}.md`.

## Codex Unavailable Fallback

- Soft (6-7): warn, Leader self-review
- Hard or 8+: AskUserQuestion → "1) Leader review (accept risk) 2) User decides 3) Defer"

## Operating Rules

- Codex input ≤3000 chars. Round cap: 2 + 1 exception.
- Entry: hard trigger or 6+. No infinite loops.
- Participants: Proposer (Leader/User) → Critic (Codex) → Judge (risk-based).
