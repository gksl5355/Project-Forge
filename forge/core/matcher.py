"""Pattern Matcher (P1): stderr → 패턴 매칭/제안."""

from __future__ import annotations

import re
import sqlite3

from forge.config import ForgeConfig
from forge.storage.models import Failure

# Python 예외 클래스명 추출용 패턴
_ERROR_CLASS_RE = re.compile(
    r'\b([A-Z][a-zA-Z]*(?:Error|Exception|Warning|Fault|Interrupt))\b'
)
_MODULE_NOT_FOUND_RE = re.compile(
    r"ModuleNotFoundError: No module named '([^']+)'"
)
_IMPORT_ERROR_RE = re.compile(
    r"ImportError: No module named '([^']+)'"
)


def extract_errors_from_stderr(stderr: str) -> list[str]:
    """stderr에서 에러 클래스/메시지 추출 (regex)."""
    results: list[str] = []

    for m in _MODULE_NOT_FOUND_RE.finditer(stderr):
        results.append(f"missing_module_{m.group(1).replace('.', '_')}")

    for m in _IMPORT_ERROR_RE.finditer(stderr):
        candidate = f"missing_module_{m.group(1).replace('.', '_')}"
        if candidate not in results:
            results.append(candidate)

    for m in _ERROR_CLASS_RE.finditer(stderr):
        snake = _to_snake_case(m.group(1))
        if snake not in results:
            results.append(snake)

    return results


def suggest_pattern_name(stderr: str) -> str:
    """stderr에서 패턴명 자동 제안.

    우선순위:
    1. ModuleNotFoundError → missing_module_X
    2. 에러 클래스명 → snake_case
    3. 첫 줄 정규화 → snake_case
    """
    if not stderr.strip():
        return "unknown_error"

    m = _MODULE_NOT_FOUND_RE.search(stderr)
    if m:
        return f"missing_module_{m.group(1).replace('.', '_')}"

    m = _IMPORT_ERROR_RE.search(stderr)
    if m:
        return f"missing_module_{m.group(1).replace('.', '_')}"

    m = _ERROR_CLASS_RE.search(stderr)
    if m:
        return _to_snake_case(m.group(1))

    first_line = stderr.strip().splitlines()[0]
    return _normalize_to_snake(first_line)


def match_pattern(stderr: str, failures: list[Failure]) -> Failure | None:
    """stderr를 기존 패턴 목록과 exact match."""
    if not failures:
        return None

    extracted = extract_errors_from_stderr(stderr)
    for failure in failures:
        if failure.pattern in extracted:
            return failure

    # 패턴명 제안으로 추가 시도
    suggested = suggest_pattern_name(stderr)
    for failure in failures:
        if failure.pattern == suggested:
            return failure

    return None


def _to_snake_case(name: str) -> str:
    """CamelCase → snake_case 변환."""
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', s)
    return s.lower()


def _normalize_to_snake(text: str) -> str:
    """일반 텍스트 → snake_case 정규화 (최대 50자)."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text[:50] if text else "unknown_error"


def match_pattern_v2(
    query_text: str, failures: list[Failure], db: sqlite3.Connection, config: ForgeConfig
) -> list[tuple[Failure, float]]:
    """Match pattern using P1 + P2 hybrid (exact match + vector search).

    Returns list of (failure, score) tuples sorted by score DESC.
    - P1: Exact pattern match (score 1.0)
    - P2: Vector search with hybrid scoring if embeddings available
    """
    if not failures:
        return []

    # Try P1 exact match first
    extracted = extract_errors_from_stderr(query_text)
    for failure in failures:
        if failure.pattern in extracted:
            return [(failure, 1.0)]

    suggested = suggest_pattern_name(query_text)
    for failure in failures:
        if failure.pattern == suggested:
            return [(failure, 1.0)]

    # P2: Vector search (if available)
    if not config.vector_search_enabled:
        return []

    from forge.core.embedding import embed_text, get_embedding

    # Try to embed query
    query_embedding = embed_text(query_text)
    if query_embedding is None:
        return []

    # Gather embeddings and Q values for all failures
    embeddings_with_q: list[tuple[Failure, list[float], float]] = []
    for f in failures:
        emb = get_embedding(db, f.id)
        if emb:
            embeddings_with_q.append((f, emb, f.q))

    if not embeddings_with_q:
        return []

    # Compute cosine similarity and hybrid scores
    import math
    import statistics

    def _cosine_sim(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    scores: list[tuple[Failure, float]] = []

    # Compute similarities and Q values for z-score normalization
    similarities = []
    q_values = []
    for f, emb, q in embeddings_with_q:
        sim = _cosine_sim(query_embedding, emb)
        similarities.append(sim)
        q_values.append(q)

    # Z-score normalize (handle edge cases)
    if len(similarities) > 1:
        sim_mean = statistics.mean(similarities)
        sim_stdev = statistics.stdev(similarities)
        if sim_stdev == 0:
            sim_stdev = 1.0
        q_mean = statistics.mean(q_values)
        q_stdev = statistics.stdev(q_values)
        if q_stdev == 0:
            q_stdev = 1.0

        for (f, _, _), sim, q in zip(embeddings_with_q, similarities, q_values):
            z_sim = (sim - sim_mean) / sim_stdev
            z_q = (q - q_mean) / q_stdev
            hybrid = (1 - config.lambda_weight) * z_sim + config.lambda_weight * z_q
            scores.append((f, hybrid))
    else:
        for (f, _, _), sim, q in zip(embeddings_with_q, similarities, q_values):
            scores.append((f, 0.5))

    # Sort by score DESC
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores
