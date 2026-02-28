"""Optional embedding-based similarity search (Phase 2)."""

from __future__ import annotations

from typing import Any


class EmbeddingIndex:
    """Stores tool embeddings for similarity search.

    Phase 2 feature — requires numpy and an embedding model.
    """

    def __init__(self) -> None:
        self._embeddings: dict[str, list[float]] = {}

    def add(self, tool_name: str, embedding: list[float]) -> None:
        self._embeddings[tool_name] = embedding

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        """Cosine similarity search against stored embeddings."""
        try:
            import numpy as np
        except ImportError:
            raise ImportError(
                "numpy is required for embedding search. "
                "Install with: pip install graph-tool-call[embedding]"
            )

        if not self._embeddings:
            return []

        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm

        results: list[tuple[str, float]] = []
        for name, emb in self._embeddings.items():
            v = np.array(emb, dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm == 0:
                continue
            v = v / v_norm
            sim = float(np.dot(q, v))
            results.append((name, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    @property
    def size(self) -> int:
        return len(self._embeddings)
