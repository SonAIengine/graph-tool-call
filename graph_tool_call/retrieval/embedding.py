"""Optional embedding-based similarity search (Phase 2)."""

from __future__ import annotations

from typing import Any


def _require_numpy() -> Any:
    """Lazily import numpy with a friendly error message."""
    try:
        import numpy as np

        return np
    except ImportError:
        raise ImportError(
            "numpy is required for embedding search. "
            "Install with: pip install graph-tool-call[embedding]"
        )


def _require_sentence_transformers() -> Any:
    """Lazily import sentence-transformers with a friendly error message."""
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers is required for automatic embedding. "
            "Install with: pip install graph-tool-call[embedding]"
        )


class EmbeddingIndex:
    """Stores tool embeddings for similarity search.

    Supports two modes:
    1. Manual: call ``add(name, embedding)`` directly.
    2. Automatic: call ``build_from_tools(tools)`` with a sentence-transformers model.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._embeddings: dict[str, list[float]] = {}
        self._model_name = model_name
        self._model: Any = None

    def _get_model(self) -> Any:
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            if self._model_name is None:
                raise ValueError("No model_name specified. Pass model_name to EmbeddingIndex().")
            st_cls = _require_sentence_transformers()
            self._model = st_cls(self._model_name)
        return self._model

    def _tool_text(self, tool: Any) -> str:
        """Build a searchable text string from a ToolSchema."""
        parts = [tool.name, tool.description]
        parts.extend(tool.tags)
        parts.extend(p.name for p in tool.parameters)
        return " ".join(p for p in parts if p)

    def encode(self, text: str) -> list[float]:
        """Encode a text string using the loaded model."""
        model = self._get_model()
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def build_from_tools(self, tools: dict[str, Any]) -> None:
        """Build embeddings for all tools using the sentence-transformers model."""
        if not tools:
            return
        model = self._get_model()
        texts = []
        names = []
        for name, tool in tools.items():
            names.append(name)
            texts.append(self._tool_text(tool))
        embeddings = model.encode(texts, convert_to_numpy=True)
        for name, emb in zip(names, embeddings):
            self._embeddings[name] = emb.tolist()

    def add(self, tool_name: str, embedding: list[float]) -> None:
        self._embeddings[tool_name] = embedding

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        """Cosine similarity search against stored embeddings."""
        np = _require_numpy()

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
