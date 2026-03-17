"""Ingest Engine: TO 런 데이터를 forge.db로 수집."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import yaml

from forge.config import ForgeConfig
from forge.core.qvalue import initial_q
from forge.storage.models import Failure, Knowledge, TeamRun
from forge.storage.queries import (
    get_failure_by_pattern,
    get_team_run,
    insert_failure,
    insert_knowledge,
    insert_team_run,
    update_failure,
)

logger = logging.getLogger("forge")


def run_ingest(
    workspace_id: str,
    run_dir: Path,
    db: sqlite3.Connection,
    config: ForgeConfig,
) -> dict[str, int]:
    """TO 런 디렉토리에서 데이터를 수집하여 forge.db에 저장.

    Returns:
        {"team_runs": n, "failures": n, "knowledge": n} 수집 카운트
    """
    counts = {"team_runs": 0, "failures": 0, "knowledge": 0}

    report_path = run_dir / "report.yml"
    events_path = run_dir / "events.yml"

    # 1. report.yml → team_runs INSERT
    if report_path.exists():
        report = _load_yaml(report_path)
        if report:
            counts["team_runs"] += _ingest_report(workspace_id, report, db)

    # 2. events.yml → failures + knowledge
    if events_path.exists():
        events = _load_yaml(events_path)
        if isinstance(events, list):
            fc, kc = _ingest_events(workspace_id, events, db, config)
            counts["failures"] += fc
            counts["knowledge"] += kc

    return counts


def run_ingest_auto(
    workspace_id: str,
    runs_base: Path,
    db: sqlite3.Connection,
    config: ForgeConfig,
) -> dict[str, int]:
    """자동 감지: .claude/runs/ 아래 최신 런 디렉토리를 찾아 수집."""
    total = {"team_runs": 0, "failures": 0, "knowledge": 0}

    if not runs_base.exists():
        logger.warning("[forge] Runs directory not found: %s", runs_base)
        return total

    # latest 심볼릭 링크 또는 가장 최근 디렉토리
    latest = runs_base / "latest"
    if latest.is_symlink() or latest.is_dir():
        result = run_ingest(workspace_id, latest, db, config)
        for k in total:
            total[k] += result[k]
    else:
        # 모든 런 디렉토리를 순회 (이미 수집된 건 skip)
        for run_path in sorted(runs_base.iterdir()):
            if not run_path.is_dir() or run_path.name.startswith("."):
                continue
            result = run_ingest(workspace_id, run_path, db, config)
            for k in total:
                total[k] += result[k]

    return total


def _load_yaml(path: Path) -> dict | list | None:
    """YAML 파일 로드 (오류 시 None)."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        logger.warning("[forge] Failed to load %s: %s", path, e)
        return None


def _ingest_report(
    workspace_id: str, report: dict, db: sqlite3.Connection
) -> int:
    """report.yml → team_runs 테이블에 INSERT."""
    run_id = report.get("run_id") or report.get("id")
    if not run_id:
        logger.warning("[forge] report.yml missing run_id, skipping")
        return 0

    run_id = str(run_id)

    # 이미 수집된 런이면 skip
    existing = get_team_run(db, run_id)
    if existing:
        logger.info("[forge] Run %s already ingested, skipping", run_id)
        return 0

    team_run = TeamRun(
        workspace_id=workspace_id,
        run_id=run_id,
        complexity=report.get("complexity"),
        team_config=report.get("team_config") or report.get("config"),
        duration_min=_safe_float(report.get("duration_min") or report.get("duration")),
        success_rate=_safe_float(report.get("success_rate")),
        retry_rate=_safe_float(report.get("retry_rate")),
        scope_violations=int(report.get("scope_violations", 0)),
        verdict=report.get("verdict"),
        agents=report.get("agents", []),
    )
    insert_team_run(db, team_run)
    logger.info("[forge] Ingested team run: %s", run_id)
    return 1


def _ingest_events(
    workspace_id: str,
    events: list[dict],
    db: sqlite3.Connection,
    config: ForgeConfig,
) -> tuple[int, int]:
    """events.yml에서 failure/knowledge 추출.

    Returns: (failures_count, knowledge_count)
    """
    failures_added = 0
    knowledge_added = 0

    for event in events:
        if not isinstance(event, dict):
            continue

        event_type = event.get("type", "")

        # scope_drift → failure (preventable)
        if event_type == "scope_drift":
            pattern = f"scope_drift_{event.get('agent', 'unknown')}"
            description = event.get("description", "Scope violation detected")
            existing = get_failure_by_pattern(db, workspace_id, pattern)
            if existing:
                existing.times_seen += 1
                update_failure(db, existing)
            else:
                failure = Failure(
                    workspace_id=workspace_id,
                    pattern=pattern,
                    avoid_hint=f"TO scope drift: {description[:500]}",
                    hint_quality="preventable",
                    q=initial_q("preventable", config),
                    source="auto",
                    tags=["team", "scope_drift"],
                )
                insert_failure(db, failure)
                failures_added += 1

        # retry_heavy → failure (near_miss)
        elif event_type == "retry_heavy":
            agent = event.get("agent", "unknown")
            pattern = f"retry_heavy_{agent}"
            description = event.get("description", "Excessive retries")
            existing = get_failure_by_pattern(db, workspace_id, pattern)
            if existing:
                existing.times_seen += 1
                update_failure(db, existing)
            else:
                failure = Failure(
                    workspace_id=workspace_id,
                    pattern=pattern,
                    avoid_hint=f"TO retry issue: {description[:500]}",
                    hint_quality="near_miss",
                    q=initial_q("near_miss", config),
                    source="auto",
                    tags=["team", "retry"],
                )
                insert_failure(db, failure)
                failures_added += 1

        # team_success → knowledge (best team config)
        elif event_type == "team_success":
            title = f"team_config_{event.get('task_type', 'general')}"
            content = event.get("description", "")
            team_cfg = event.get("team_config", "")
            if team_cfg:
                content = f"Best config: {team_cfg}. {content}"
            knowledge = Knowledge(
                workspace_id=workspace_id,
                title=title,
                content=content[:2000],
                source="organic",
                q=config.initial_q_knowledge,
                tags=["team", "config"],
            )
            insert_knowledge(db, knowledge)
            knowledge_added += 1

    return failures_added, knowledge_added


def _safe_float(value: str | int | float | None) -> float | None:
    """Convert to float safely."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
