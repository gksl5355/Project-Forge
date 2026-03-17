"""Deduplication module for M2. Finds and merges duplicate failures by embedding similarity."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, UTC

from forge.config import ForgeConfig
from forge.core.embedding import embed_text, get_embedding, get_embedder
from forge.storage.models import Failure
from forge.storage.queries import list_failures, soft_delete_failure, update_failure

logger = logging.getLogger("forge")


def find_duplicates(
    db: sqlite3.Connection, workspace_id: str, threshold: float = 0.8
) -> list[tuple[Failure, Failure, float]]:
    """Find duplicate failures by cosine similarity. Returns list of (failure1, failure2, similarity)."""
    failures = list_failures(db, workspace_id, include_global=False, active_only=True)
    duplicates: list[tuple[Failure, Failure, float]] = []
    embedder = get_embedder()

    if embedder is None or not failures:
        return duplicates

    # Collect embeddings for all failures
    embeddings_map: dict[int, list[float]] = {}
    for f in failures:
        emb = get_embedding(db, f.id)
        if emb:
            embeddings_map[f.id] = emb

    if len(embeddings_map) < 2:
        return duplicates

    # Compute pairwise cosine similarity
    try:
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np
    except ImportError:
        logger.warning("sklearn/numpy not available; dedup requires vector dependencies")
        return duplicates

    failure_ids = list(embeddings_map.keys())
    embedding_vectors = np.array([embeddings_map[fid] for fid in failure_ids])
    similarity_matrix = cosine_similarity(embedding_vectors)

    # Build failures map for quick lookup
    failures_by_id = {f.id: f for f in failures}

    # Extract pairs above threshold (avoid duplicates and self-comparison)
    for i, fid1 in enumerate(failure_ids):
        for j in range(i + 1, len(failure_ids)):
            fid2 = failure_ids[j]
            sim = float(similarity_matrix[i, j])
            if sim >= threshold:
                f1, f2 = failures_by_id[fid1], failures_by_id[fid2]
                duplicates.append((f1, f2, sim))

    # Sort by similarity DESC
    duplicates.sort(key=lambda x: x[2], reverse=True)
    return duplicates


def merge_failures(db: sqlite3.Connection, keep: Failure, merge: Failure) -> None:
    """Merge merge into keep. Weighted average Q, sum times_seen/helped. Soft-delete merge."""
    if keep.id is None or merge.id is None:
        logger.error("Cannot merge failures without IDs")
        return

    # Weighted average Q
    total_seen = keep.times_seen + merge.times_seen
    if total_seen > 0:
        keep.q = (keep.q * keep.times_seen + merge.q * merge.times_seen) / total_seen

    # Sum counters
    keep.times_seen = total_seen
    keep.times_helped += merge.times_helped
    keep.times_warned += merge.times_warned

    # Preserve keep's avoid_hint (higher Q assumed)
    keep.updated_at = datetime.now(UTC)

    update_failure(db, keep)
    soft_delete_failure(db, merge.id)
    logger.info(f"Merged failure {merge.id} into {keep.id}")


def run_dedup(
    db: sqlite3.Connection, workspace_id: str, config: ForgeConfig, auto: bool = False
) -> list[dict]:
    """Run dedup and optionally auto-merge. Returns list of merge suggestions as dicts."""
    duplicates = find_duplicates(db, workspace_id, config.dedup_threshold)
    suggestions: list[dict] = []

    for f1, f2, sim in duplicates:
        suggestion: dict[str, object] = {
            "pattern_a": f1.pattern,
            "q_a": f1.q,
            "pattern_b": f2.pattern,
            "q_b": f2.q,
            "similarity": sim,
            "merged": False,
        }

        if auto:
            keep, merge = (f1, f2) if f1.q >= f2.q else (f2, f1)
            merge_failures(db, keep, merge)
            suggestion["merged"] = True

        suggestions.append(suggestion)

    return suggestions
