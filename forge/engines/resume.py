"""Resume Engine: context 생성 + session 기록."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

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

    # 1. A/B Variant Selection (prompt optimizer)
    variant = "default"
    if config.ab_enabled:
        try:
            from forge.engines.prompt_optimizer import get_best_format
            variant = get_best_format(db, workspace_id)
        except Exception as e:
            logger.debug("A/B variant selection failed: %s", e)

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
            variant=variant,
            sort_by_injection_score=config.injection_score_enabled,
        )
    else:
        # Fall back to original behavior when no team runs
        base_context = build_context(
            regular_failures,
            rules,
            config,
            variant=variant,
            sort_by_injection_score=config.injection_score_enabled,
        )

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

    # Compute config & document hashes for experiment tracking
    from forge.core.hashing import compute_config_hash, compute_combined_doc_hash, compute_doc_hashes
    config_hash = compute_config_hash(config)
    doc_hashes = compute_doc_hashes(Path(workspace_id) if Path(workspace_id).is_dir() else None)
    doc_hash = compute_combined_doc_hash(doc_hashes)

    session = Session(
        session_id=session_id,
        workspace_id=workspace_id,
        warnings_injected=warnings_injected,
        config_hash=config_hash,
        document_hash=doc_hash,
    )
    insert_session(db, session)

    # 3. Circuit Breaker Status Check
    if config.circuit_breaker_enabled:
        try:
            from forge.core.circuit_breaker import check_breaker
            breaker = check_breaker(db, session_id, config)
            if breaker.is_tripped:
                context = f"⚠️ [CIRCUIT BREAKER] {breaker.trip_reason}\n\n" + context
        except Exception as e:
            logger.debug("Circuit breaker check failed: %s", e)

    # 4. Agent Registration (main agent)
    if config.agent_manager_enabled:
        try:
            from forge.engines.agent_manager import register_agent
            register_agent(db, workspace_id, session_id, "main", "main")
        except Exception as e:
            logger.debug("Agent registration failed: %s", e)

    # 5. Model Routing Context (lightweight)
    if config.routing_enabled:
        try:
            from forge.engines.routing import get_routing_stats
            stats = get_routing_stats(workspace_id, db)
            if stats.get("categories"):
                routing_lines = ["## Model Routing"]
                for cat, info in stats["categories"].items():
                    if info.get("best_model"):
                        routing_lines.append(
                            f"  {cat}: {info['best_model']} (success: {info.get('success_rate', 0):.0%})"
                        )
                if len(routing_lines) > 1:
                    context = context + "\n\n" + "\n".join(routing_lines)
        except Exception as e:
            logger.debug("Model routing context failed: %s", e)

    return context
