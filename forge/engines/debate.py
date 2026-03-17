"""Debate Engine: 외부 LLM을 이용한 설계 검토 (Adversarial Architecture Review)."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path

from forge.config import ForgeConfig
from forge.storage.models import Decision
from forge.storage.queries import (
    insert_decision,
    list_decisions,
    list_failures,
    list_knowledge,
    search_by_tags,
)

logger = logging.getLogger("forge")


@dataclass
class DebateResult:
    topic: str
    proposal: str
    critiques: list[dict] = field(default_factory=list)
    has_blocks: bool = False
    rounds: int = 1
    result_path: str = ""
    decision_id: int | None = None


def run_debate(
    topic: str,
    workspace_id: str,
    db: sqlite3.Connection,
    config: ForgeConfig,
    save_result: bool = True,
) -> DebateResult:
    """Adversarial architecture review: proposal → critique → decision."""
    # 1. Collect Forge context
    context_items = _collect_context(topic, workspace_id, db)

    # 2. Build proposal
    proposal = _build_proposal(topic, context_items)

    # 3. Get critique from external LLM
    raw_critique = _get_critique(proposal, config)

    # 4. Parse critique
    critiques = _parse_critique(raw_critique)
    has_blocks = any(c["severity"] == "BLOCK" for c in critiques)

    result = DebateResult(
        topic=topic,
        proposal=proposal,
        critiques=critiques,
        has_blocks=has_blocks,
        rounds=1,
    )

    # 5. Save result file
    result.result_path = _save_result_file(result)

    # 6. Save to forge.db
    if save_result:
        result.decision_id = _save_decision(topic, workspace_id, critiques, db, config)

    return result


def _collect_context(
    topic: str, workspace_id: str, db: sqlite3.Connection
) -> list[str]:
    """Collect relevant Forge context for the topic."""
    context: list[str] = []
    tags = _extract_tags(topic)

    # Tag-based failure search
    if tags:
        failures = search_by_tags(db, workspace_id, tags)
        for f in failures[:5]:
            context.append(f"[FAILURE] {f.pattern}: {f.avoid_hint}")

    # Recent decisions
    decisions = list_decisions(db, workspace_id, status="active")
    for d in decisions[:3]:
        context.append(f"[DECISION] {d.statement}")

    # Knowledge
    knowledge = list_knowledge(db, workspace_id)
    for k in knowledge[:3]:
        context.append(f"[KNOWLEDGE] {k.title}: {k.content[:100]}")

    return context


def _extract_tags(topic: str) -> list[str]:
    """Extract searchable tags from topic string."""
    stopwords = {"a", "an", "the", "is", "are", "and", "or", "of", "to", "in", "vs", "for"}
    words = topic.lower().split()
    return [w for w in words if len(w) > 2 and w not in stopwords]


def _build_proposal(topic: str, context_items: list[str]) -> str:
    """Build proposal document with Forge context. Max 3000 chars."""
    context_section = ""
    if context_items:
        context_section = "### Forge Context:\n" + "\n".join(f"  - {c}" for c in context_items)

    proposal = f"""## Decision subject: {topic}

{context_section}

## Proposed direction:
{topic}

## Risk assessment:
- Uncertainty: 2/3 (moderate)
- Impact: 2/3 (moderate)
- Complexity: 2/3 (moderate)

## Request:
Review this architectural decision considering the context above.
Identify potential blocks, tradeoffs, and acceptable improvements.
"""
    return proposal[:3000]


_CRITIQUE_PROMPT = """You are an adversarial architecture reviewer. Review this proposal and provide critique.

For each issue found, output ONE line in this format:
[BLOCK|TRADEOFF|ACCEPT] category: one-line summary

- BLOCK: Core requirement unmet, ship-blocking (data integrity, security, SLO)
- TRADEOFF: Met but increased cost/complexity
- ACCEPT: Immediately actionable improvement

Then provide detail for each:
- Problem / Impact / Fix / Risk-if-ignored

Proposal:
{proposal}"""


def _get_critique(proposal: str, config: ForgeConfig) -> str:
    """Try codex → anthropic → empty (manual mode)."""
    # Try Codex CLI
    critique = _call_codex(proposal, config.codex_model)
    if critique:
        print("[forge] Critique from Codex")
        return critique

    # Try Anthropic API
    critique = _call_anthropic(proposal, config)
    if critique:
        print("[forge] Critique from Anthropic API")
        return critique

    print("[forge] No LLM available — manual review mode (proposal saved)")
    return ""


def _call_codex(proposal: str, model: str) -> str | None:
    """Call Codex CLI for critique."""
    if not shutil.which("codex"):
        return None

    input_path = Path("/tmp/debate-input.md")
    input_path.write_text(proposal, encoding="utf-8")

    prompt = _CRITIQUE_PROMPT.format(proposal=proposal)

    try:
        result = subprocess.run(
            ["codex", "exec", "-m", model, "-s", "read-only", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        logger.debug("Codex failed: %s", result.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("Codex call failed: %s", e)

    return None


def _call_anthropic(proposal: str, config: ForgeConfig) -> str | None:
    """Fallback to Anthropic API."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        config_path = Path.home() / ".forge" / "config.yml"
        if config_path.exists():
            try:
                import yaml
                with config_path.open() as f:
                    cfg = yaml.safe_load(f) or {}
                api_key = cfg.get("anthropic_api_key")
            except Exception:
                pass

    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    prompt = _CRITIQUE_PROMPT.format(proposal=proposal)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=config.llm_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("[forge] Anthropic debate call failed: %s", e)
        return None


def _parse_critique(raw_text: str) -> list[dict]:
    """Parse [BLOCK|TRADEOFF|ACCEPT] category: summary lines."""
    critiques: list[dict] = []
    if not raw_text:
        return critiques

    for line in raw_text.splitlines():
        line = line.strip()
        for severity in ("BLOCK", "TRADEOFF", "ACCEPT"):
            prefix = f"[{severity}]"
            if line.startswith(prefix):
                rest = line[len(prefix):].strip()
                if ":" in rest:
                    category, summary = rest.split(":", 1)
                else:
                    category, summary = rest, ""
                critiques.append({
                    "severity": severity,
                    "category": category.strip(),
                    "summary": summary.strip(),
                })
                break

    return critiques


def _save_result_file(result: DebateResult) -> str:
    """Save detailed result to /tmp/debate-result-{timestamp}.md."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/debate-result-{timestamp}.md"

    adopted = "REJECTED" if result.has_blocks else "ADOPTED"
    lines = [
        f"## Debate Result (Round {result.rounds})",
        f"**Topic:** {result.topic}",
        f"**Adopted:** {adopted} | **BLOCKs:** {result.has_blocks}",
        "",
        "### Critiques:",
    ]

    if result.critiques:
        for c in result.critiques:
            lines.append(f"- **[{c['severity']}] {c['category']}:** {c['summary']}")
    else:
        lines.append("*(No critiques — manual review needed)*")

    lines.extend(["", "### Proposal:", "", "```", result.proposal, "```"])

    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return path


def _save_decision(
    topic: str,
    workspace_id: str,
    critiques: list[dict],
    db: sqlite3.Connection,
    config: ForgeConfig,
) -> int:
    """Save debate result as a Decision in forge.db."""
    has_blocks = any(c["severity"] == "BLOCK" for c in critiques)
    status = "revisiting" if has_blocks else "active"

    critique_summary = "; ".join(
        f"[{c['severity']}] {c['category']}: {c['summary']}" for c in critiques
    ) if critiques else "No external critique (manual review)"

    decision = Decision(
        workspace_id=workspace_id,
        statement=f"[Debate] {topic}",
        rationale=f"Adversarial review result: {critique_summary}",
        tags=_extract_tags(topic) + ["debate"],
        q=config.initial_q_decision,
        status=status,
    )
    return insert_decision(db, decision)
