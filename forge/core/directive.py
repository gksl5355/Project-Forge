"""Directive model — atomic units extracted from markdown documents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Directive:
    """Represents an atomic unit of knowledge extracted from markdown."""
    source_file: str         # "CLAUDE.md", "SKILL.md", etc.
    section: str             # "## Coding Rules", "### 7-pre", etc.
    directive_id: str        # stable ID: "{source}:{section}:{hash[:8]}"
    content: str             # actual text
    directive_type: str      # "rule" | "threshold" | "workflow" | "description" | "constraint"
    tokens: int = 0          # estimated token count
    dependencies: list[str] = field(default_factory=list)  # references to other directive_ids
