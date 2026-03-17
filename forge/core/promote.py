"""Promote Engine: 전역 승격, knowledge 승격 (순수 로직)."""

from __future__ import annotations

from datetime import datetime, UTC

from forge.config import ForgeConfig
from forge.storage.models import Failure, Knowledge


def check_global_promote(failure: Failure, config: ForgeConfig) -> bool:
    """projects_seen and times_seen both meet thresholds for global promotion."""
    return (
        len(failure.projects_seen) >= config.promote_threshold
        and failure.times_seen >= config.promote_min_times_seen
    )


def promote_to_global(
    failure: Failure,
    merge_from: list[Failure] | None = None,
) -> Failure:
    """failure의 __global__ workspace 복사본을 반환.

    merge_from이 제공되면 동일 패턴의 모든 워크스페이스 failure를 merge_q()로
    가중 평균하여 Q를 결정한다. caller는 proper Q merging을 위해
    동일 패턴의 모든 failure를 전달해야 한다.
    """
    q = merge_q(merge_from) if merge_from else failure.q
    return Failure(
        workspace_id="__global__",
        pattern=failure.pattern,
        avoid_hint=failure.avoid_hint,
        hint_quality=failure.hint_quality,
        q=q,
        times_seen=failure.times_seen,
        times_helped=failure.times_helped,
        times_warned=failure.times_warned,
        tags=list(failure.tags),
        projects_seen=list(failure.projects_seen),
        source=failure.source,
        review_flag=failure.review_flag,
        observed_error=failure.observed_error,
        likely_cause=failure.likely_cause,
        last_used=failure.last_used,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        id=None,
    )


def check_knowledge_promote(failure: Failure, config: ForgeConfig) -> bool:
    """Q와 times_helped가 임계값 이상이면 knowledge 승격 대상."""
    return (
        failure.q >= config.knowledge_promote_q
        and failure.times_helped >= config.knowledge_promote_helped
    )


def merge_q(failures: list[Failure]) -> float:
    """Weighted average of Q values, weighted by times_seen."""
    total_weight = sum(f.times_seen for f in failures)
    if total_weight == 0:
        return sum(f.q for f in failures) / len(failures) if failures else 0.0
    return sum(f.q * f.times_seen for f in failures) / total_weight


def promote_to_knowledge(failure: Failure) -> Knowledge:
    """failure → Knowledge 변환."""
    content_parts = [failure.avoid_hint]
    if failure.likely_cause:
        content_parts.append(f"\n원인: {failure.likely_cause}")
    if failure.observed_error:
        content_parts.append(f"\n관찰된 에러: {failure.observed_error}")

    return Knowledge(
        workspace_id=failure.workspace_id,
        title=failure.pattern,
        content="\n".join(content_parts),
        source="organic",
        q=failure.q,
        tags=list(failure.tags),
        promoted_from=failure.id,
        last_used=failure.last_used,
        created_at=datetime.now(UTC),
        id=None,
    )
