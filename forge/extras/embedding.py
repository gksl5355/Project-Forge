"""Embedding module for vector search (M2). Uses sentence-transformers with graceful degradation."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger("forge")

_embedder: Any = None
_embedder_initialized = False


def get_embedder() -> Any:
    """Get or initialize the embedding model. Returns None if not available."""
    global _embedder, _embedder_initialized
    if _embedder_initialized:
        return _embedder
    _embedder_initialized = True
    try:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        logger.info("Embedding model loaded: all-MiniLM-L6-v2 (384 dims)")
        return _embedder
    except ImportError:
        logger.warning("sentence-transformers not installed; vector search disabled")
        return None
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        return None


def embed_text(text: str) -> list[float] | None:
    """Embed a single text. Returns None if unavailable."""
    embedder = get_embedder()
    if embedder is None:
        return None
    try:
        embedding = embedder.encode(text, convert_to_tensor=False)
        return embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
    except Exception as e:
        logger.error(f"Failed to embed text: {e}")
        return None


def embed_batch(texts: list[str]) -> list[list[float]] | None:
    """Batch embed multiple texts. Returns None if unavailable."""
    embedder = get_embedder()
    if embedder is None:
        return None
    try:
        embeddings = embedder.encode(texts, convert_to_tensor=False)
        return [e.tolist() if hasattr(e, "tolist") else list(e) for e in embeddings]
    except Exception as e:
        logger.error(f"Failed to embed batch: {e}")
        return None


def store_embedding(db: sqlite3.Connection, failure_id: int, embedding: list[float]) -> bool:
    """Store embedding in failure_embeddings table. Returns True if successful."""
    if not embedding:
        return False
    try:
        # Try to use sqlite-vec if available
        db.execute(
            "INSERT OR REPLACE INTO failure_embeddings (failure_id, embedding) VALUES (?, ?)",
            (failure_id, embedding),
        )
        db.commit()
        return True
    except sqlite3.OperationalError:
        # Table doesn't exist or vec0 not available; silently skip
        logger.debug(f"failure_embeddings table not available, skipping embedding {failure_id}")
        return False
    except Exception as e:
        logger.error(f"Failed to store embedding: {e}")
        return False


def get_embedding(db: sqlite3.Connection, failure_id: int) -> list[float] | None:
    """Retrieve embedding from failure_embeddings. Returns None if not found."""
    try:
        row = db.execute(
            "SELECT embedding FROM failure_embeddings WHERE failure_id = ?",
            (failure_id,),
        ).fetchone()
        if row:
            embedding = row[0]
            # Handle both binary and list formats
            if isinstance(embedding, bytes):
                import struct
                # Unpack 384 floats (4 bytes each)
                return list(struct.unpack(f"{384}f", embedding))
            return embedding if isinstance(embedding, list) else None
        return None
    except sqlite3.OperationalError:
        # Table doesn't exist
        return None
    except Exception as e:
        logger.error(f"Failed to retrieve embedding: {e}")
        return None


def search_similar(
    db: sqlite3.Connection, query_embedding: list[float], limit: int = 10
) -> list[tuple[int, float]]:
    """Search for similar failures by cosine distance. Returns (failure_id, distance) pairs."""
    if not query_embedding:
        return []
    try:
        rows = db.execute(
            """
            SELECT failure_id, distance FROM failure_embeddings
            WHERE embedding MATCH ?
            ORDER BY distance ASC
            LIMIT ?
            """,
            (query_embedding, limit),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
    except sqlite3.OperationalError:
        # sqlite-vec not available or query syntax wrong
        logger.debug("Vector search not available")
        return []
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return []


def embed_failures(db: sqlite3.Connection, workspace_id: str) -> int:
    """Embed all unembedded failures in a workspace. Returns count of newly embedded."""
    from forge.storage.queries import list_failures

    failures = list_failures(db, workspace_id, include_global=False, active_only=True)
    count = 0
    embedder = get_embedder()
    if embedder is None:
        return 0

    # Batch embed for efficiency
    unembedded = []
    for f in failures:
        existing = get_embedding(db, f.id)
        if existing is None:
            unembedded.append(f)

    if not unembedded:
        return 0

    # Extract text for embedding (pattern + avoid_hint)
    texts = [f"{f.pattern}: {f.avoid_hint}" for f in unembedded]
    embeddings = embed_batch(texts)
    if embeddings is None:
        return 0

    for failure, embedding in zip(unembedded, embeddings):
        if store_embedding(db, failure.id, embedding):
            count += 1

    return count
