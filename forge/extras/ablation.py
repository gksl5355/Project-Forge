"""Ablation engine — generate and apply directive variants for optimization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from forge.core.directive import Directive


@dataclass
class AblationCandidate:
    """Represents a variant of a directive for ablation testing."""
    directive_id: str
    action: str              # "remove" | "simplify" | "expand" | "reorder" | "rephrase"
    variant_content: str     # modified content ("" for remove)
    estimated_token_delta: int


def generate_ablation_candidates(
    directives: list[Directive],
    strategy: str = "systematic",  # systematic | random | targeted
) -> list[AblationCandidate]:
    """Generate variant candidates for each directive.

    Strategies:
    - systematic: try removing each one (ablation study)
    - targeted: prioritize low-impact directives based on previous data
    - random: random subset
    """
    candidates: list[AblationCandidate] = []

    if strategy == "systematic":
        for d in directives:
            # Remove variant
            candidates.append(AblationCandidate(
                directive_id=d.directive_id,
                action="remove",
                variant_content="",
                estimated_token_delta=-d.tokens,
            ))

            # Simplify variant (for rules and descriptions with > 20 tokens)
            if d.tokens > 20 and d.directive_type in ("rule", "description", "workflow"):
                simplified = _simplify(d.content)
                if simplified != d.content:
                    delta = _estimate_tokens(simplified) - d.tokens
                    candidates.append(AblationCandidate(
                        directive_id=d.directive_id,
                        action="simplify",
                        variant_content=simplified,
                        estimated_token_delta=delta,
                    ))

    elif strategy == "targeted":
        # Same as systematic but only for description/constraint types
        # (typically lower impact)
        for d in directives:
            if d.directive_type in ("description", "constraint"):
                candidates.append(AblationCandidate(
                    directive_id=d.directive_id,
                    action="remove",
                    variant_content="",
                    estimated_token_delta=-d.tokens,
                ))

    elif strategy == "random":
        import random
        sample_size = max(1, len(directives) // 3)
        sampled = random.sample(directives, min(sample_size, len(directives)))
        for d in sampled:
            candidates.append(AblationCandidate(
                directive_id=d.directive_id,
                action="remove",
                variant_content="",
                estimated_token_delta=-d.tokens,
            ))

    return candidates


def apply_ablation(
    original_path: Path,
    candidates: list[AblationCandidate],
    directives: list[Directive],
) -> str:
    """Apply ablation candidates to a document, returning modified content.

    Does NOT write to disk — returns the modified text.
    """
    if not original_path.exists():
        return ""

    original_text = original_path.read_text(encoding="utf-8")

    # Build lookup: directive_id -> candidate
    actions: dict[str, AblationCandidate] = {c.directive_id: c for c in candidates}

    # Build lookup: directive_id -> directive
    directive_map: dict[str, Directive] = {d.directive_id: d for d in directives}

    result = original_text
    # Apply in reverse order of content position to preserve offsets
    # Sort directives by their position (find in text)
    positioned: list[tuple[int, Directive]] = []
    for d in directives:
        if d.directive_id in actions and d.source_file == original_path.name:
            pos = result.find(d.content)
            if pos >= 0:
                positioned.append((pos, d))

    # Sort by position descending to apply from end to start
    positioned.sort(key=lambda x: x[0], reverse=True)

    for pos, d in positioned:
        candidate = actions[d.directive_id]
        if candidate.action == "remove":
            # Remove the directive content
            end = pos + len(d.content)
            # Also remove trailing newline if present
            if end < len(result) and result[end] == "\n":
                end += 1
            result = result[:pos] + result[end:]
        elif candidate.action in ("simplify", "rephrase", "expand"):
            # Replace content
            result = result[:pos] + candidate.variant_content + result[pos + len(d.content):]

    return result


def analyze_directive_impact(
    experiments: list,  # list of experiment-like objects with active_directives info
    directives: list[Directive],
) -> list[tuple[str, float]]:
    """Analyze each directive's contribution to fitness.

    Method: average fitness delta between experiments with/without each directive.
    Returns: [(directive_id, avg_fitness_delta), ...] sorted descending.
    """
    if not experiments or not directives:
        return []

    # Collect fitness values when directive is present vs absent
    impact: dict[str, list[float]] = {}
    for d in directives:
        present_fitness: list[float] = []
        absent_fitness: list[float] = []

        for exp in experiments:
            active = getattr(exp, "active_directives", set())
            fitness = getattr(exp, "unified_fitness", 0.0)
            if d.directive_id in active:
                present_fitness.append(fitness)
            else:
                absent_fitness.append(fitness)

        if present_fitness and absent_fitness:
            avg_present = sum(present_fitness) / len(present_fitness)
            avg_absent = sum(absent_fitness) / len(absent_fitness)
            impact[d.directive_id] = [avg_present - avg_absent]

    results: list[tuple[str, float]] = []
    for did, deltas in impact.items():
        avg_delta = sum(deltas) / len(deltas)
        results.append((did, avg_delta))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _simplify(content: str) -> str:
    """Simplify a directive by removing parenthetical explanations and examples."""
    # Remove parenthetical content
    simplified = re.sub(r"\s*\([^)]+\)", "", content)
    # Remove "e.g., ..." and "for example, ..."
    simplified = re.sub(r"\s*(e\.g\.,?|for example,?)\s*[^.]+\.", ".", simplified, flags=re.IGNORECASE)
    # Remove trailing whitespace
    simplified = simplified.strip()
    return simplified if simplified else content


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)
