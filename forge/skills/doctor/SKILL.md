---
name: doctor
description: Checks the environment for Claude Code Agent Teams prerequisites. Reports pass/fail for each check, proposes settings patches, and applies them after user confirmation.
triggers:
  - "doctor"
  - "/doctor"
  - "check environment"
  - "환경 확인"
  - "닥터"
allowed-tools: Bash(claude *), Bash(tmux *), Bash(which *), Bash(git *), Bash(jq *), Bash(codex *), Bash(test *), Bash(cp *), Bash(echo *), Read, Edit, AskUserQuestion
---

## Purpose

Verify that the host environment satisfies all prerequisites for Claude Code Agent Teams.
Output a clear ✓/✗ report, then offer to patch `~/.claude/settings.json` for any failed checks.

---

## Step 0: Read settings.json

Before running checks, read `~/.claude/settings.json` using the **Read tool** (not bash).
Store the content for use in checks 3-5,8. This avoids jq dependency for basic reads.

Also check jq availability (one bash call):
```bash
which jq 2>/dev/null && echo "jq:yes" || echo "jq:no"
```

If jq not available, extract values from the Read output using python3:
```bash
python3 -c "import json,sys; d=json.load(open('${HOME}/.claude/settings.json')); print(d.get('key',''))"
```
Or grep as last resort: `grep -o '"key": *"[^"]*"' ~/.claude/settings.json | head -1`

## Step 1: Run All Checks

Run all 8 checks in parallel (independent). Collect results before printing anything.

### Check 1 — Claude Code version
```bash
claude --version
```
- ✓ if exits 0 and prints a version string
- ✗ if command not found or exits non-zero

### Check 2 — tmux
```bash
tmux -V
```
- ✓ if exits 0 (tmux ≥ 3.0 recommended; warn if older but still pass)
- ✗ if command not found

### Check 3 — CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
Primary: check env var `$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`.
Fallback: extract from settings.json content read in Step 0.
```bash
echo "${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS}"
```
- ✓ if env var = `"1"`, OR settings.json has `"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"`
- ✗ otherwise (missing or wrong value)
- **Patchable**: add `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1"` to settings.json

### Check 4 — TEAMMATE_COMMAND executable
Extract `CLAUDE_CODE_TEAMMATE_COMMAND` from settings.json content (Step 0), then:
```bash
test -n "${TEAMMATE_CMD}" && test -x "${TEAMMATE_CMD}"
```
- ✓ if path set AND file exists and is executable
- ✗ if not set, file missing, or not executable
- Reason shown: which condition failed

### Check 5 — teammateMode in settings.json
Extract `teammateMode` from settings.json content read in Step 0.
- ✓ if value is `"tmux"`
- ✗ otherwise
- **Patchable**: set `teammateMode = "tmux"` in settings.json

### Check 6 — Codex CLI (optional)
```bash
which codex && codex --version
```
- ✓ if found and version prints
- ⚠ if not found (warn only — optional dependency, does not affect pass/fail)

### Check 7 — git
```bash
git --version
```
- ✓ if exits 0
- ✗ if command not found

### Check 8 — CLAUDE_CODE_SUBAGENT_MODEL
Extract from settings.json content (Step 0). Also check env var:
```bash
echo "${CLAUDE_CODE_SUBAGENT_MODEL}"
```
- ✓ if value is `"haiku"` (recommended default)
- ⚠ if not set (warn — system still works, defaults to Sonnet for sub-agents)
- ✗ if set to an unrecognized value
- **Patchable**: add `env.CLAUDE_CODE_SUBAGENT_MODEL = "haiku"` to settings.json

---

## Step 2: Print Report

Print results in this exact format:

```
Claude Code Agent Teams — Environment Check
============================================

  ✓ Claude Code        2.1.74
  ✓ tmux               3.3a
  ✓ Agent Teams flag   CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
  ✓ Teammate command   /home/user/.claude/teammate.sh (executable)
  ✓ Teammate mode      tmux
  ⚠ Codex CLI          not found (optional — debate/offload unavailable)
  ✓ git                2.43.0
  ⚠ Subagent model     not set (defaulting to Sonnet; recommend haiku)

Result: 6 pass, 0 fail, 2 warn
```

Rules:
- ✓ = pass (green intent)
- ✗ = fail (blocks team spawn)
- ⚠ = warn (degraded but functional)
- Always show the actual value or reason on the same line
- Print `Result:` summary line at the end

---

## Step 3: Settings Patch (if any fails or warns)

If any check is ✗ or ⚠ and is marked **Patchable**:

1. Show the proposed patch:
```
Proposed settings.json patch:
  + env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1"
  + teammateMode = "tmux"
  + env.CLAUDE_CODE_SUBAGENT_MODEL = "haiku"
```

2. AskUserQuestion: "Apply patch to ~/.claude/settings.json? (y/n)"

3. If yes:
   a. **Backup first** (always, before any write):
      ```bash
      cp ~/.claude/settings.json ~/.claude/settings.json.bak
      ```
   b. Read `~/.claude/settings.json` with the Read tool
   c. Merge required keys using the Edit tool (preserve all existing content)
   d. Confirm: "Backup saved to ~/.claude/settings.json.bak — patch applied."

4. If no: "No changes made."

### Merge rules for settings.json

- Use `jq` to merge if jq is available:
  ```bash
  jq '. * {"env": ((.env // {}) * {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1", "CLAUDE_CODE_SUBAGENT_MODEL": "haiku"}), "teammateMode": "tmux"}' ~/.claude/settings.json > /tmp/settings.json.new && mv /tmp/settings.json.new ~/.claude/settings.json
  ```
- Fallback (no jq): Read → Edit tool (manual JSON merge, preserve existing keys)
- Never overwrite keys that are already correct
- Never remove existing keys or permission entries

---

## Non-Patchable Failures

Some failures cannot be auto-patched — provide install guidance:

| Check | Guidance |
|-------|----------|
| Claude Code not found | Install from https://docs.anthropic.com/en/docs/claude-code |
| tmux not found | `sudo apt install tmux` / `brew install tmux` |
| TEAMMATE_COMMAND missing/not executable | Run `./install.sh` from the project root |
| git not found | `sudo apt install git` / `brew install git` |

Print the relevant guidance after the report for each ✗ non-patchable check.

---

## Operating Rules

- Run all checks before printing anything (no streaming partial results)
- Never modify settings.json without explicit user confirmation
- Always backup before patching
- Backup path is always `~/.claude/settings.json.bak` (overwrite previous backup — one backup is enough)
- If settings.json does not exist, create it as `{}` before patching (after user confirms)
- Codex and subagent model are never ✗ — only ⚠. They do not count as failures.
- Exit gracefully if ~/.claude/settings.json is missing or invalid JSON (report it, offer to create/fix)
