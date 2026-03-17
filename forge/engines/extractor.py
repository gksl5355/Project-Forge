"""LLM-based failure/decision extraction from transcripts."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("forge")


def llm_extract(
    transcript_path: Path,
    model: str = "claude-haiku-4-5-20251001",
) -> list[dict[str, Any]]:
    """Extract failures and decisions from a transcript using Claude API.

    Returns list of dicts with keys:
        type: "failure" | "decision"
        pattern: str (for failures)
        statement: str (for decisions)
        hint: str (avoid_hint for failures)
        quality: str (hint_quality for failures)
        rationale: str (for decisions)
        tags: list[str]
        source: "llm_extract"

    Returns empty list if:
        - anthropic package not installed
        - API key not set
        - API call fails
    """
    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Try config file
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
        logger.info("[forge] No API key found, skipping LLM extraction")
        return []

    # Try importing anthropic
    try:
        import anthropic
    except ImportError:
        logger.info("[forge] anthropic package not installed, skipping LLM extraction")
        return []

    # Read transcript
    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("[forge] Failed to read transcript: %s", e)
        return []

    # Truncate to ~100K chars to stay within context limits
    if len(transcript_text) > 100_000:
        transcript_text = transcript_text[:100_000] + "\n... (truncated)"

    # Call Claude API
    prompt = _build_extraction_prompt(transcript_text)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        if not response.content:
            logger.warning("[forge] LLM extraction returned empty content")
            return []
        result_text = response.content[0].text
    except Exception as e:
        logger.warning("[forge] LLM extraction API call failed: %s", e)
        return []

    # Parse response
    return _parse_extraction_response(result_text)


def _build_extraction_prompt(transcript: str) -> str:
    """Build the extraction prompt for Claude."""
    return f"""Analyze this coding agent session transcript and extract failures and decisions.

For each failure found, provide:
- pattern: a snake_case identifier (e.g., "missing_dependency_xyz", "type_error_in_handler")
- hint: a concise avoidance hint (how to prevent this in the future)
- quality: one of "near_miss" (almost failed), "preventable" (could have been avoided), "environmental" (external cause)
- tags: relevant tags as list of strings

For each decision found, provide:
- statement: what was decided
- rationale: why
- tags: relevant tags

Return ONLY a JSON array. Each element must have a "type" field ("failure" or "decision").

Example output:
[
  {{"type": "failure", "pattern": "missing_import_pathlib", "hint": "Always import pathlib when working with file paths", "quality": "preventable", "tags": ["import", "python"]}},
  {{"type": "decision", "statement": "Use SQLite instead of PostgreSQL for local storage", "rationale": "Simpler deployment, no external dependencies", "tags": ["architecture", "storage"]}}
]

Transcript:
{transcript}

Return ONLY the JSON array, no other text."""


def _parse_extraction_response(text: str) -> list[dict[str, Any]]:
    """Parse the LLM response into structured data."""
    # Try to find JSON array in response
    text = text.strip()

    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            elif line.strip() == "```" and in_block:
                break
            elif in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find array within text
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                logger.warning("[forge] Failed to parse LLM extraction response")
                return []
        else:
            logger.warning("[forge] No JSON array found in LLM response")
            return []

    if not isinstance(data, list):
        return []

    # Validate and normalize entries
    results = []
    for item in data:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "failure":
            if not item.get("pattern") or not item.get("hint"):
                continue
            quality = item.get("quality", "preventable")
            if quality not in ("near_miss", "preventable", "environmental"):
                quality = "preventable"
            results.append({
                "type": "failure",
                "pattern": str(item["pattern"])[:200],
                "hint": str(item["hint"])[:2000],
                "quality": quality,
                "tags": [str(t) for t in item.get("tags", [])],
                "source": "llm_extract",
            })
        elif item_type == "decision":
            if not item.get("statement"):
                continue
            results.append({
                "type": "decision",
                "statement": str(item["statement"])[:500],
                "rationale": str(item.get("rationale", ""))[:2000],
                "tags": [str(t) for t in item.get("tags", [])],
                "source": "llm_extract",
            })

    return results
