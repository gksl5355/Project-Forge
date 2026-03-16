"""Context Builder: L0/L1/Rules 포맷 빌더 (순수 로직)."""

from __future__ import annotations

from forge.config import ForgeConfig
from forge.storage.models import Decision, Failure, Knowledge, Rule


def format_l0(failures: list[Failure]) -> str:
    """L0: 한 줄 요약 포맷.

    형식: [WARN] {pattern} | {quality} | Q:{q} | seen:{n} helped:{n}
    """
    lines = []
    for f in failures:
        lines.append(
            f"[WARN] {f.pattern} | {f.hint_quality} | Q:{f.q:.2f} | "
            f"seen:{f.times_seen} helped:{f.times_helped}"
        )
    return "\n".join(lines)


def format_l1(failures: list[Failure]) -> str:
    """L1: L0 한 줄 + avoid_hint 상세."""
    lines = []
    for f in failures:
        lines.append(
            f"[WARN] {f.pattern} | {f.hint_quality} | Q:{f.q:.2f} | "
            f"seen:{f.times_seen} helped:{f.times_helped}"
        )
        lines.append(f"  → {f.avoid_hint}")
    return "\n".join(lines)


def format_rules(rules: list[Rule]) -> str:
    """Rules: [RULE] {rule_text} ({mode}) 포맷."""
    lines = []
    for r in rules:
        lines.append(f"[RULE] {r.rule_text} ({r.enforcement_mode})")
    return "\n".join(lines)


def format_decisions(decisions: list[Decision]) -> str:
    """Format decisions for context output.

    형식: [DECISION] {statement} | Q:{q:.2f} | {status}
    """
    lines = []
    for d in decisions:
        lines.append(f"[DECISION] {d.statement} | Q:{d.q:.2f} | {d.status}")
    return "\n".join(lines)


def format_knowledge(knowledge_list: list[Knowledge]) -> str:
    """Format knowledge for context output.

    형식: [KNOWLEDGE] {title} | Q:{q:.2f}
    """
    lines = []
    for k in knowledge_list:
        lines.append(f"[KNOWLEDGE] {k.title} | Q:{k.q:.2f}")
    return "\n".join(lines)


def build_context(
    failures: list[Failure],
    rules: list[Rule],
    config: ForgeConfig,
    decisions: list[Decision] | None = None,
    knowledge_list: list[Knowledge] | None = None,
) -> str:
    """L0 + L1 + Decisions + Knowledge + Rules → 예산 내 포맷된 문자열 반환."""
    parts: list[str] = []

    # L0: 전체 목록 (l0_max_entries 상한)
    l0_failures = failures[: config.l0_max_entries]
    if l0_failures:
        parts.append("## Past Failures (L0)")
        parts.append(format_l0(l0_failures))

    # L1: Q 상위 N개 상세
    l1_count = config.l1_project_entries + config.l1_global_entries
    l1_failures = sorted(failures, key=lambda f: f.q, reverse=True)[:l1_count]
    if l1_failures:
        parts.append("\n## Top Failures — Details (L1)")
        parts.append(format_l1(l1_failures))

    # Decisions: active만
    active_decisions = [d for d in (decisions or []) if d.status == "active"]
    if active_decisions:
        parts.append("\n## Decisions")
        parts.append(format_decisions(active_decisions))

    # Knowledge
    if knowledge_list:
        parts.append("\n## Knowledge")
        parts.append(format_knowledge(knowledge_list))

    # Rules: active만, rules_max_entries 상한
    active_rules = [r for r in rules if r.active][: config.rules_max_entries]
    if active_rules:
        parts.append("\n## Rules")
        parts.append(format_rules(active_rules))

    return "\n".join(parts)
