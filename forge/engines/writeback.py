"""Writeback Engine: transcript 파싱 → 패턴 매칭 → Q 갱신 → 감쇠 → 승격 (단일 트랜잭션)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from forge.config import ForgeConfig
from forge.core.hashing import compute_config_hash, compute_combined_doc_hash, compute_doc_hashes
from forge.core.matcher import match_pattern, suggest_pattern_name
from forge.core.promote import (
    check_global_promote,
    check_knowledge_promote,
    promote_to_global,
    promote_to_knowledge,
)
from forge.core.qvalue import ema_update, initial_q, time_decay
from forge.engines.fitness import compute_unified_fitness
from forge.engines.transcript import parse_transcript
from forge.storage.models import Decision, Failure, Knowledge
from forge.storage.queries import (
    get_failure_by_pattern,
    get_session,
    insert_decision,
    insert_failure,
    insert_knowledge,
    list_failures,
    update_failure,
    update_session_metrics,
)

logger = logging.getLogger("forge")


class _NoCommitProxy:
    """sqlite3.Connection 프록시: helper 함수의 중간 commit()을 억제한다.

    writeback 전체를 단일 트랜잭션으로 만들기 위해 사용.
    run_writeback 마지막에 실제 conn.commit()을 호출한다.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        """중간 commit 억제 — 실제 커밋은 run_writeback에서 일괄 처리."""
        pass

    def rollback(self) -> None:
        self._conn.rollback()

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return self._conn.execute(sql, *args, **kwargs)

    def executemany(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return self._conn.executemany(sql, *args, **kwargs)

    def executescript(self, script: str) -> sqlite3.Cursor:
        return self._conn.executescript(script)


def run_writeback(
    workspace_id: str,
    session_id: str,
    transcript_path: Path,
    db: sqlite3.Connection,
    config: ForgeConfig,
    llm_extract: bool = False,
) -> None:
    """transcript 파싱 → Q 갱신 → 감쇠 → 승격 (단일 SQLite 트랜잭션)."""
    proxy = _NoCommitProxy(db)

    try:
        _do_writeback(workspace_id, session_id, transcript_path, proxy, config, llm_extract)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _do_writeback(
    workspace_id: str,
    session_id: str,
    transcript_path: Path,
    db: Any,
    config: ForgeConfig,
    llm_extract: bool = False,
) -> None:
    """실제 writeback 로직 (proxy db 사용, commit 없음)."""
    bash_failures = parse_transcript(transcript_path)
    all_failures = list_failures(db, workspace_id)

    n_failures = len(bash_failures)
    m_q_updates = 0
    p_promotions = 0

    # 1. 각 Bash 실패 → 패턴 매칭 또는 새 패턴 생성
    for bf in bash_failures:
        matched = match_pattern(bf.stderr, all_failures)
        if matched:
            matched.times_seen += 1
            matched.last_used = datetime.now(UTC)
            update_failure(db, matched)
        else:
            if not bf.stderr.strip():
                continue
            pattern_name = suggest_pattern_name(bf.stderr)
            existing = get_failure_by_pattern(db, workspace_id, pattern_name)
            if existing:
                existing.times_seen += 1
                existing.last_used = datetime.now(UTC)
                update_failure(db, existing)
            else:
                q0 = initial_q("preventable", config)
                new_failure = Failure(
                    workspace_id=workspace_id,
                    pattern=pattern_name,
                    avoid_hint=f"자동 감지: {bf.stderr[:200]}",
                    hint_quality="preventable",
                    q=q0,
                    source="auto",
                    observed_error=bf.stderr[:500] if bf.stderr else None,
                    last_used=datetime.now(UTC),
                )
                insert_failure(db, new_failure)

    # 최신 목록 재조회
    all_failures = list_failures(db, workspace_id)

    # 2. 주입 경고 vs 실제 발생 비교 → Q 갱신
    # NOTE: Decision Q 갱신은 v1으로 연기. v0에서는 수동 status 변경(cmd_edit) 시에만
    #       EMA 업데이트 적용 (cli.py 담당). 자동화된 writeback에서는 Failure Q만 처리.
    session = get_session(db, session_id)
    if session:
        for warned_pattern in session.warnings_injected:
            failure = get_failure_by_pattern(db, workspace_id, warned_pattern)
            if not failure:
                continue
            was_triggered = any(
                match_pattern(bf.stderr, [failure]) is not None
                for bf in bash_failures
            )
            if was_triggered:
                # 경고했지만 여전히 발생 → reward=0, review_flag 설정 (GAP-6)
                failure.q = ema_update(failure.q, 0.0, config.alpha)
                failure.times_warned += 1
                failure.review_flag = True
            else:
                # 경고 후 발생 안 함 → reward=1
                failure.q = ema_update(failure.q, 1.0, config.alpha)
                failure.times_helped += 1
                failure.times_warned += 1
            update_failure(db, failure)
            m_q_updates += 1

    # 3. 시간 감쇠 (last_used > 1일 이상)
    now = datetime.now(UTC)
    stale_failures = list_failures(db, workspace_id, include_global=False)
    for failure in stale_failures:
        if failure.last_used is None:
            continue
        days = (now - failure.last_used).total_seconds() / 86400.0
        if days > 1.0:
            failure.q = time_decay(failure.q, days, config.decay_daily, config.q_min)
            update_failure(db, failure)

    # 4. 전역 승격 / knowledge 승격 확인
    current_failures = list_failures(db, workspace_id, include_global=False)
    for failure in current_failures:
        if check_global_promote(failure, config):
            existing_global = get_failure_by_pattern(db, "__global__", failure.pattern)
            if not existing_global:
                global_copy = promote_to_global(failure)
                insert_failure(db, global_copy)
                logger.info("Global promoted: '%s' (Q: %.2f)", failure.pattern, failure.q)
                p_promotions += 1

        if check_knowledge_promote(failure, config):
            knowledge = promote_to_knowledge(failure)
            insert_knowledge(db, knowledge)
            logger.info("Knowledge candidate: '%s' → '%s' (Q: %.2f)", failure.pattern, knowledge.title, failure.q)
            p_promotions += 1

    # 4.5 LLM extraction (optional)
    if llm_extract and config.llm_extract_enabled:
        _llm_extract_step(workspace_id, transcript_path, db, config)

    # 4.6 Output analysis — scriptable pattern learning (v2)
    _output_analysis_step(workspace_id, transcript_path, db, config)

    # 4.7 Auto dedup (v2) — if interval configured and elapsed
    _auto_dedup_step(workspace_id, db, config)

    # 4.8 Auto ingest (v2) — collect TO run data if available
    _auto_ingest_step(workspace_id, db, config)

    # 5. 세션 종료 기록 (impact metrics 포함)
    update_session_metrics(db, session_id, n_failures, m_q_updates, p_promotions)

    # 5.1 Record experiment with unified fitness
    _record_experiment(workspace_id, db, config)

    logger.info("Writeback: %d failures processed, %d Q-updates, %d promotions", n_failures, m_q_updates, p_promotions)


def _llm_extract_step(
    workspace_id: str,
    transcript_path: Path,
    db: Any,
    config: ForgeConfig,
) -> None:
    """LLM-based extraction of failures and decisions from transcript."""
    from forge.engines.extractor import llm_extract

    extracted = llm_extract(transcript_path, model=config.llm_model)
    if not extracted:
        return

    for item in extracted:
        if item["type"] == "failure":
            # Check for duplicate pattern
            existing = get_failure_by_pattern(db, workspace_id, item["pattern"])
            if existing:
                continue
            failure = Failure(
                workspace_id=workspace_id,
                pattern=item["pattern"],
                avoid_hint=item["hint"],
                hint_quality=item["quality"],
                q=initial_q(item["quality"], config),
                source="llm_extract",
                tags=item.get("tags", []),
                last_used=datetime.now(UTC),
            )
            insert_failure(db, failure)
            logger.info("LLM extracted failure: %s", item['pattern'])

        elif item["type"] == "decision":
            decision = Decision(
                workspace_id=workspace_id,
                statement=item["statement"],
                rationale=item.get("rationale", ""),
                tags=item.get("tags", []),
                q=config.initial_q_decision,
            )
            insert_decision(db, decision)
            logger.info("LLM extracted decision: %s", item['statement'][:60])

    logger.info("LLM extraction: %d items extracted", len(extracted))


def _output_analysis_step(
    workspace_id: str,
    transcript_path: Path,
    db: Any,
    config: ForgeConfig,
) -> None:
    """Analyze tool outputs for scriptable patterns (v2)."""
    try:
        from forge.core.output_analyzer import analyze_transcript_outputs, generate_output_hints
    except ImportError:
        return

    patterns = analyze_transcript_outputs(transcript_path)
    if not patterns:
        return

    hints = generate_output_hints(patterns)
    for hint in hints:
        # Check if similar knowledge already exists
        existing = db.execute(
            "SELECT id FROM knowledge WHERE workspace_id = ? AND title = ?",
            (workspace_id, hint["title"]),
        ).fetchone()
        if existing:
            continue
        k = Knowledge(
            workspace_id=workspace_id,
            title=hint["title"],
            content=hint["content"],
            source="organic",
            q=config.initial_q_knowledge,
            tags=hint["tags"],
        )
        insert_knowledge(db, k)
        logger.info("Output pattern learned: %s", hint['title'])


def _auto_dedup_step(
    workspace_id: str,
    db: Any,
    config: ForgeConfig,
) -> None:
    """Auto dedup if interval elapsed (v2)."""
    if config.dedup_interval_days <= 0:
        return

    from forge.storage.queries import get_meta, set_meta

    last_dedup = get_meta(db, f"last_dedup_{workspace_id}")
    if last_dedup:
        try:
            last_dt = datetime.fromisoformat(last_dedup)
            days = (datetime.now(UTC) - last_dt).total_seconds() / 86400.0
            if days < config.dedup_interval_days:
                return
        except ValueError:
            pass

    try:
        from forge.core.dedup import run_dedup
        results = run_dedup(db, workspace_id, config, auto=True)
        if results:
            logger.info("Auto dedup: %d pair(s) merged", len(results))
        set_meta(db, f"last_dedup_{workspace_id}", datetime.now(UTC).isoformat())
    except Exception as e:
        logger.warning("Auto dedup skipped: %s", e)


def _auto_ingest_step(
    workspace_id: str,
    db: Any,
    config: ForgeConfig,
) -> None:
    """Auto ingest TO run data if available (v2)."""
    if not config.auto_ingest_enabled:
        return

    runs_dir = Path(workspace_id) / ".claude" / "runs"
    if not runs_dir.exists():
        return

    try:
        from forge.engines.ingest import run_ingest_auto
        counts = run_ingest_auto(workspace_id, runs_dir, db, config)
        total = sum(counts.values())
        if total > 0:
            logger.info("Auto ingest: %d runs, %d failures, %d knowledge", counts['team_runs'], counts['failures'], counts['knowledge'])
    except Exception as e:
        logger.warning("Auto ingest skipped: %s", e)


def _record_experiment(
    workspace_id: str,
    db: Any,
    config: ForgeConfig,
) -> None:
    """Record an experiment entry with current fitness metrics."""
    import json as json_mod
    from forge.engines.measure import run_measure
    from forge.storage.models import Experiment
    from forge.storage.queries import insert_experiment

    try:
        result = run_measure(workspace_id, db, config)

        config_hash = compute_config_hash(config)
        doc_hashes = compute_doc_hashes(
            Path(workspace_id) if Path(workspace_id).is_dir() else None
        )
        doc_hash = compute_combined_doc_hash(doc_hashes)

        experiment = Experiment(
            workspace_id=workspace_id,
            experiment_type="auto",
            config_snapshot=json_mod.dumps({
                "alpha": config.alpha,
                "decay_daily": config.decay_daily,
                "l0_max_entries": config.l0_max_entries,
                "forge_context_tokens": config.forge_context_tokens,
            }),
            config_hash=config_hash,
            document_hashes=doc_hashes,
            document_hash=doc_hash,
            unified_fitness=result.unified_fitness,
            qwhr=result.qwhr,
            token_efficiency=result.helped_per_1k_tokens / 1000.0 if result.helped_per_1k_tokens > 0 else 0.0,
            promotion_precision=result.promotion_precision,
            to_success_rate=result.to_avg_success_rate,
            to_retry_rate=result.to_avg_retry_rate,
            to_scope_violations=result.to_avg_scope_violations,
            sessions_evaluated=result.total_sessions,
            team_runs_evaluated=result.to_total_runs,
        )
        insert_experiment(db, experiment)
    except Exception as e:
        logger.warning("Failed to record experiment: %s", e)
