"""Context Builder: L0/L1/Rules 포맷 빌더 (순수 로직)."""

from __future__ import annotations

from forge.config import ForgeConfig
from forge.storage.models import Decision, Failure, Knowledge, Rule, TeamRun


def format_l0(failures: list[Failure], variant: str = "default") -> str:
    """L0: 한 줄 요약 포맷.

    형식: [WARN] {pattern} | {quality} | Q:{q} | seen:{n} helped:{n}
    variant != "default" 이면 prompt_optimizer의 A/B 포맷 사용.
    """
    if variant != "default":
        from forge.engines.prompt_optimizer import generate_ab_format
        return "\n".join(generate_ab_format(f, variant) for f in failures)

    lines = []
    for f in failures:
        lines.append(
            f"[WARN] {f.pattern} | {f.hint_quality} | Q:{f.q:.2f} | "
            f"seen:{f.times_seen} helped:{f.times_helped}"
        )
    return "\n".join(lines)


def format_l1(failures: list[Failure], variant: str = "default") -> str:
    """L1: L0 한 줄 + avoid_hint 상세.

    variant != "default" 이면 prompt_optimizer의 A/B 포맷 사용.
    """
    if variant != "default":
        from forge.engines.prompt_optimizer import generate_ab_format
        return "\n".join(generate_ab_format(f, variant) for f in failures)

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
    variant: str = "default",
    sort_by_injection_score: bool = False,
) -> str:
    """L0 + L1 + Decisions + Knowledge + Rules → 예산 내 포맷된 문자열 반환.

    variant: A/B 포맷 변형 ("default" | "concise" | "detailed")
    sort_by_injection_score: True면 injection_score 기준으로 failures 정렬 후 포맷
    """
    parts: list[str] = []

    # Optional: injection score 기반 정렬
    ordered = failures
    if sort_by_injection_score:
        from forge.engines.prompt_optimizer import compute_injection_score
        ordered = sorted(failures, key=lambda f: compute_injection_score(f), reverse=True)

    # L0: 전체 목록 (l0_max_entries 상한)
    l0_failures = ordered[: config.l0_max_entries]
    if l0_failures:
        parts.append("## Past Failures (L0)")
        parts.append(format_l0(l0_failures, variant=variant))

    # L1: Q 상위 N개 상세
    l1_count = config.l1_project_entries + config.l1_global_entries
    l1_failures = sorted(ordered, key=lambda f: f.q, reverse=True)[:l1_count]
    if l1_failures:
        parts.append("\n## Top Failures — Details (L1)")
        parts.append(format_l1(l1_failures, variant=variant))

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


def format_team_runs(runs: list[TeamRun]) -> str:
    """Format team runs for context output.

    형식: [TEAM] {run_id} | {complexity} | config:{team_config} | success:{success_rate:.0%}
    Include verdict if present.
    """
    lines = []
    for r in runs:
        verdict_str = f" | verdict:{r.verdict}" if r.verdict else ""
        success_pct = f"{r.success_rate:.0%}" if r.success_rate is not None else "N/A"
        lines.append(
            f"[TEAM] {r.run_id} | {r.complexity} | config:{r.team_config} | "
            f"success:{success_pct}{verdict_str}"
        )
    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Simple token estimation: len(text) // 4 (rough char-to-token ratio)."""
    return len(text) // 4


def trim_to_budget(text: str, max_tokens: int) -> str:
    """Trim text to fit within token budget.

    If estimated tokens exceed max_tokens, truncate lines from bottom.
    Add "... (truncated)" marker.
    """
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text

    lines = text.split("\n")
    while lines and estimate_tokens("\n".join(lines)) > max_tokens:
        lines.pop()

    if lines:
        return "\n".join(lines) + "\n... (truncated)"
    return "... (truncated)"


def build_unified_context(
    failures: list[Failure],
    rules: list[Rule],
    config: ForgeConfig,
    decisions: list[Decision] | None = None,
    knowledge_list: list[Knowledge] | None = None,
    team_runs: list[TeamRun] | None = None,
    team_failures: list[Failure] | None = None,
    variant: str = "default",
    sort_by_injection_score: bool = False,
) -> str:
    """Build unified context combining forge experience and team history.

    - Calls build_context for forge section, trims to forge_context_tokens
    - Builds team section (recent runs + team-related failures), trims to team_context_tokens
    - Dedup: if a team_failure pattern exists in forge failures, skip it
    - Combines under '## Forge Experience' and '## Team History' headers
    - Total trimmed to total_max_tokens

    Args:
        variant: A/B format variant ("default" | "concise" | "detailed")
        sort_by_injection_score: True to sort failures by injection score before building context
    """
    # Build forge experience section
    forge_context = build_context(failures, rules, config, decisions, knowledge_list, variant=variant, sort_by_injection_score=sort_by_injection_score)
    trimmed_forge = trim_to_budget(forge_context, config.forge_context_tokens)

    # Build team section
    team_parts: list[str] = []

    # Add team runs if available
    if team_runs:
        team_parts.append("### Recent Team Runs")
        team_parts.append(format_team_runs(team_runs))

    # Add team-specific failures (dedup with forge failures)
    forge_patterns = {f.pattern for f in failures}
    if team_failures:
        filtered_team_failures = [f for f in team_failures if f.pattern not in forge_patterns]
        if filtered_team_failures:
            team_parts.append("### Team-Related Failures")
            team_parts.append(format_l1(filtered_team_failures))

    team_section = "\n".join(team_parts)
    trimmed_team = trim_to_budget(team_section, config.team_context_tokens)

    # Combine with headers
    final_parts: list[str] = []
    if trimmed_forge:
        final_parts.append("## Forge Experience")
        final_parts.append(trimmed_forge)
    if trimmed_team:
        final_parts.append("## Team History")
        final_parts.append(trimmed_team)

    combined = "\n".join(final_parts)
    result = trim_to_budget(combined, config.total_max_tokens)
    return result
