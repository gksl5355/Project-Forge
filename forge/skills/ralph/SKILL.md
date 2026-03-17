---
name: ralph
description: PRD-driven persistence loop that keeps working until all tasks in prd.json pass verification. Use when user wants guaranteed completion ("don't stop", "keep going until done"). Integrates with spawn-team's team approach.
triggers:
  - "ralph"
  - "don't stop"
  - "keep going until done"
  - "must complete"
  - "finish this completely"
  - "끝날 때까지"
  - "반드시 완료"
---

# Ralph: Team-Based Persistence Loop

PRD-driven completion guarantee integrated with spawn-team. Repeats until every user story passes verification.

**Use:** "don't stop until done", "must complete" / after spawn-team: "ralph mode until finished"
**Don't use:** one-off fixes, manual control, exploration/design (use spawn-team planner first)

## Step 1: PRD Setup

If no prd.json exists, create one:
```json
{
  "version": 1, "project": "{name}", "createdAt": "{ts}",
  "stories": [{
    "id": "S01", "name": "{story}", "description": "{what}",
    "acceptanceCriteria": ["{specific testable criterion}"],
    "assignedTo": null, "passes": false
  }]
}
```

**Criteria must be verifiable**: ❌ "implemented" → ✅ "vitest auth 12 tests PASS" / "`GET /api/products` returns 200 + list" / "negative stock returns 400"
If no team → run /spawn-team first.

## Step 2: Loop

```
while (passes:false exists):
  pick highest-priority incomplete story → Step 3 → Step 4
  pass → passes:true → next
  fail → spawn-team §8-3 feedback loop (2 retries → debugger → circuit breaker)
```

## Step 3: Delegate Implementation

SendMessage to assigned agent:
```
[Ralph - Story {ID}] Implement: {description}
Criteria: 1. {criterion-1}  2. {criterion-2}
On completion: TaskUpdate(completed) + report.
```
Delegate independent stories in parallel. Dependencies → blockedBy.

## Step 4: Verification (fresh evidence required)

unit-tester: report actual execution results for each criterion. "probably works" is not acceptable.
Pass → prd.json `passes:true`. Fail → apply spawn-team §8-3.

## Step 5: PRD Completion Check

`jq '[.stories[]|select(.passes==false)]|length' prd.json` → 0 means Step 6, otherwise Step 2.

## Step 6: Architect Review

- Small (changes <10 files): Leader direct review
- Medium/Large (10+): Codex (gpt-5.4) read-only
Pass → Step 7. Fail → feedback → re-implement → Step 4.

## Step 7: Done

```
Ralph Complete ✓
Stories: ✅ S01: {name} / ✅ S02: {name} ...
Verification: unit-tester {N} PASS | Architect: {method} passed
Team shutdown: shutdown_request → TeamDelete
```

## Operating Rules

- No scope reduction. No deleting tests.
- Same story fails 3 times → circuit breaker → user escalation.
- Delegate independent stories in parallel (no sequential processing). Verification always based on actual execution.
