"""Directive extractor — parse markdown documents into atomic directives."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from forge.core.directive import Directive


def extract_directives(file_path: Path) -> list[Directive]:
    """Parse a markdown file into a list of Directives.

    Decomposition rules:
    1. ## header -> section boundary
    2. - bullet / numbered list -> individual directive
    3. code block -> threshold/workflow directive
    4. table row -> individual directive
    5. pipe-separated inline rules -> constraint directive
    """
    if not file_path.exists():
        return []

    text = file_path.read_text(encoding="utf-8")
    source = file_path.name
    directives: list[Directive] = []

    current_section = "root"
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Section boundary (## or ### header)
        header_match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if header_match:
            current_section = line.strip()
            i += 1
            continue

        # Code block (``` ... ```)
        if line.strip().startswith("```"):
            block_lines = [line]
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block_lines.append(lines[i])
                i += 1
            if i < len(lines):
                block_lines.append(lines[i])
                i += 1
            content = "\n".join(block_lines)
            d_type = _classify_directive(content)
            directives.append(_make_directive(source, current_section, content, d_type))
            continue

        # Table row (starts with |)
        if line.strip().startswith("|") and not _is_table_separator(line):
            content = line.strip()
            # Skip header separator rows
            if not re.match(r"^\|[\s\-:|]+\|$", content):
                directives.append(
                    _make_directive(source, current_section, content, "constraint")
                )
            i += 1
            continue

        # Bullet or numbered list item
        list_match = re.match(r"^(\s*[-*+]|\s*\d+\.)\s+(.+)$", line)
        if list_match:
            content = line.strip()
            # Collect continuation lines (indented, non-empty, not a new list item)
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if (next_line.strip()
                        and not re.match(r"^(\s*[-*+]|\s*\d+\.)\s+", next_line)
                        and not re.match(r"^#{1,4}\s+", next_line)
                        and (next_line.startswith("  ") or next_line.startswith("\t"))):
                    content += "\n" + next_line.strip()
                    i += 1
                else:
                    break
            d_type = _classify_directive(content)
            directives.append(_make_directive(source, current_section, content, d_type))
            continue

        # Non-empty paragraph text (description)
        if line.strip():
            content = line.strip()
            directives.append(
                _make_directive(source, current_section, content, "description")
            )

        i += 1

    return directives


def classify_directive(content: str) -> str:
    """Public wrapper for directive type classification."""
    return _classify_directive(content)


def _classify_directive(content: str) -> str:
    """Classify directive type: rule | threshold | workflow | description | constraint."""
    lower = content.lower()

    # Threshold indicators
    if any(kw in lower for kw in [">=", "<=", ">", "<", "threshold", "cap:", "limit", "max", "min"]):
        return "threshold"

    # Workflow indicators (step-by-step or sequential)
    if any(kw in lower for kw in ["step", "→", "->", "flow", "pipeline", "then"]):
        return "workflow"

    # Rule indicators (imperatives, constraints)
    if any(kw in lower for kw in [
        "must", "never", "always", "required", "do not", "don't", "avoid",
        "prefer", "ensure", "check", "use", "run", "should",
    ]):
        return "rule"

    # Constraint indicators
    if "|" in content and content.count("|") >= 2:
        return "constraint"

    return "description"


def _is_table_separator(line: str) -> bool:
    """Check if a line is a markdown table separator (e.g., |---|---|)."""
    return bool(re.match(r"^\|[\s\-:|]+\|$", line.strip()))


def _make_directive(
    source: str, section: str, content: str, d_type: str
) -> Directive:
    """Create a Directive with a stable ID."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
    # Clean section for ID
    section_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", section.strip("#").strip())[:30]
    directive_id = f"{source}:{section_clean}:{content_hash}"
    tokens = _estimate_tokens(content)
    return Directive(
        source_file=source,
        section=section,
        directive_id=directive_id,
        content=content,
        directive_type=d_type,
        tokens=tokens,
    )


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def build_dependency_graph(directives: list[Directive]) -> dict[str, list[str]]:
    """Extract reference relationships between directives.

    Looks for section references and variable references within directive content.
    """
    graph: dict[str, list[str]] = {d.directive_id: [] for d in directives}

    # Build lookup: section name -> directive IDs in that section
    section_ids: dict[str, list[str]] = {}
    for d in directives:
        section_ids.setdefault(d.section, []).append(d.directive_id)

    for d in directives:
        # Look for references to other sections in content
        for other_section in section_ids:
            if other_section == d.section:
                continue
            # Check if section header text appears in content
            section_text = other_section.strip("#").strip()
            if section_text and len(section_text) > 3 and section_text.lower() in d.content.lower():
                for ref_id in section_ids[other_section]:
                    if ref_id != d.directive_id:
                        graph[d.directive_id].append(ref_id)

    # Update directive dependencies
    for d in directives:
        d.dependencies = graph.get(d.directive_id, [])

    return graph
