"""Resume Engine: context 생성 + session 기록."""

from __future__ import annotations

import logging
import sqlite3

from forge.config import ForgeConfig

logger = logging.getLogger("forge")
from forge.core.context import build_context, build_unified_context, format_decisions, format_knowledge
from forge.storage.models import Decision, Failure, Knowledge, Session
from forge.storage.queries import (
    insert_session,
    list_decisions,
    list_failures,
    list_knowledge,
    list_rules,
    list_team_runs,
)


def run_resume(
    workspace_id: str,
    session_id: str,
    db: sqlite3.Connection,
    config: ForgeConfig,
    team_brief: bool = False,
) -> str:
    """context 생성 + session 기록 + 포맷된 문자열 반환.

    Args:
        workspace_id: Workspace identifier
        session_id: Session identifier
        db: SQLite connection
        config: Forge configuration
        team_brief: If True, output only the Team History section

    Returns:
        Formatted context string for injection or team-only brief
    """
    raw_failures = list_failures(db, workspace_id)
    # Deduplicate by pattern: prefer project-local over global
    seen_patterns: dict[str, Failure] = {}
    for f in raw_failures:
        if f.pattern not in seen_patterns or f.workspace_id == workspace_id:
            seen_patterns[f.pattern] = f
    failures = list(seen_patterns.values())

    rules = list_rules(db, workspace_id)
    if rules:
        b = sum(1 for r in rules if r.enforcement_mode == "block")
        w = sum(1 for r in rules if r.enforcement_mode == "warn")
        l = sum(1 for r in rules if r.enforcement_mode == "log")
        logger.info("[forge] %d active rules loaded (%d block, %d warn, %d log)", len(rules), b, w, l)
    decisions = list_decisions(db, workspace_id, status="active")

    raw_knowledge = list_knowledge(db, workspace_id, include_global=True)
    # Deduplicate knowledge by title: prefer project-local
    seen_titles: dict[str, object] = {}
    for k in raw_knowledge:
        if k.title not in seen_titles or k.workspace_id == workspace_id:
            seen_titles[k.title] = k
    knowledge_list = list(seen_titles.values())

    # Load team runs (limit 5 as per spec)
    team_runs = list_team_runs(db, workspace_id, limit=5)

    # Separate team-related failures (tags containing "team") from regular failures
    team_related_failures: list[Failure] = []
    regular_failures: list[Failure] = []
    for f in failures:
        if "team" in f.tags:
            team_related_failures.append(f)
        else:
            regular_failures.append(f)

    # If team_brief=True, return only Team History section
    if team_brief:
        if not team_runs and not team_related_failures:
            return ""
        from forge.core.context import format_team_runs, format_l1
        team_parts: list[str] = []
        if team_runs:
            team_parts.append("### Recent Team Runs")
            team_parts.append(format_team_runs(team_runs))
        if team_related_failures:
            team_parts.append("### Team-Related Failures")
            team_parts.append(format_l1(team_related_failures))
        return "\n".join(team_parts)

    # Use unified context if team runs exist, otherwise fall back to old code path
    if team_runs:
        context = build_unified_context(
            failures=regular_failures,
            rules=rules,
            config=config,
            decisions=decisions,
            knowledge_list=knowledge_list,
            team_runs=team_runs,
            team_failures=team_related_failures,
        )
    else:
        # Fall back to original behavior when no team runs
        base_context = build_context(regular_failures, rules, config)

        # decisions + knowledge 섹션을 룰 앞에 삽입
        extra_parts: list[str] = []
        if decisions:
            extra_parts.append("## Active Decisions")
            extra_parts.append(format_decisions(decisions))
        if knowledge_list:
            extra_parts.append("## Knowledge")
            extra_parts.append(format_knowledge(knowledge_list))

        if extra_parts:
            # rules 섹션이 있으면 그 앞에, 없으면 base_context 뒤에 붙임
            rules_marker = "\n## Rules"
            if rules_marker in base_context:
                idx = base_context.index(rules_marker)
                context = (
                    base_context[:idx].rstrip()
                    + "\n\n"
                    + "\n".join(extra_parts)
                    + base_context[idx:]
                )
            else:
                sep = "\n\n" if base_context else ""
                context = base_context + sep + "\n".join(extra_parts)
        else:
            context = base_context

    # 주입한 경고 패턴 목록 기록
    warnings_injected = [f.pattern for f in failures]

    session = Session(
        session_id=session_id,
        workspace_id=workspace_id,
        warnings_injected=warnings_injected,
    )
    insert_session(db, session)

    return context
