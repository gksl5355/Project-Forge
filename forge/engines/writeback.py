"""Writeback Engine: transcript 파싱 → 패턴 매칭 → Q 갱신 → 감쇠 → 승격 (단일 트랜잭션)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from forge.config import ForgeConfig
from forge.core.matcher import match_pattern, suggest_pattern_name
from forge.core.promote import (
    check_global_promote,
    check_knowledge_promote,
    promote_to_global,
    promote_to_knowledge,
)
from forge.core.qvalue import ema_update, initial_q, time_decay
from forge.engines.transcript import parse_transcript
from forge.storage.models import Failure
from forge.storage.queries import (
    get_failure_by_pattern,
    get_session,
    insert_failure,
    insert_knowledge,
    list_failures,
    update_failure,
    update_session_end,
)


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
) -> None:
    """transcript 파싱 → Q 갱신 → 감쇠 → 승격 (단일 SQLite 트랜잭션)."""
    proxy = _NoCommitProxy(db)

    try:
        _do_writeback(workspace_id, session_id, transcript_path, proxy, config)
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
) -> None:
    """실제 writeback 로직 (proxy db 사용, commit 없음)."""
    bash_failures = parse_transcript(transcript_path)
    all_failures = list_failures(db, workspace_id)

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

        if check_knowledge_promote(failure, config):
            knowledge = promote_to_knowledge(failure)
            insert_knowledge(db, knowledge)

    # 5. 세션 종료 기록
    update_session_end(db, session_id)
