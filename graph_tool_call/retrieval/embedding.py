"""Optional embedding-based similarity search (Phase 2).

Supports multiple embedding providers via ``wrap_embedding()`` auto-detection:

- ``"openai/text-embedding-3-large"`` — OpenAI Embeddings API
- ``"ollama/nomic-embed-text"`` — Ollama local embeddings
- ``"sentence-transformers/all-MiniLM-L6-v2"`` — local sentence-transformers
- ``callable(list[str]) -> list[list[float]]`` — custom function
- ``EmbeddingIndex`` instance — pass-through
"""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
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


# ---------------------------------------------------------------------------
# Embedding Provider ABC
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts into embeddings."""

    def encode(self, text: str) -> list[float]:
        """Encode a single text."""
        return self.encode_batch([text])[0]


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class SentenceTransformerProvider(EmbeddingProvider):
    """Local sentence-transformers provider."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for local embedding. "
                    "Install with: pip install graph-tool-call[embedding]"
                )
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = model.encode(texts, convert_to_numpy=True)
        return [emb.tolist() for emb in embeddings]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI Embeddings API provider."""

    def __init__(
        self,
        model: str = "text-embedding-3-large",
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        batch_size: int = 100,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size

        if not api_key:
            import os

            api_key = os.environ.get("OPENAI_API_KEY", "")
        self.api_key = api_key

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            msg = "OPENAI_API_KEY required for OpenAI embeddings."
            raise ValueError(msg)

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            all_embeddings.extend(self._call_api(batch))
        return all_embeddings

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        payload = json.dumps({"model": self.model, "input": texts}).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())
        data = sorted(result["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in data]


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama local embedding provider."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        # Ollama /api/embed supports batch input
        url = f"{self.base_url}/api/embed"
        payload = json.dumps({"model": self.model, "input": texts}).encode()
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())
        return result["embeddings"]


class CallableEmbeddingProvider(EmbeddingProvider):
    """Wraps a callable as an embedding provider."""

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        result = self._fn(texts)
        return [list(emb) for emb in result]


# ---------------------------------------------------------------------------
# Auto-wrap
# ---------------------------------------------------------------------------


def wrap_embedding(embedding: Any) -> EmbeddingProvider:
    """Auto-detect embedding type and wrap as EmbeddingProvider.

    Supported inputs:

    - ``EmbeddingProvider`` instance — returned as-is
    - ``callable(list[str]) -> list[list[float]]`` — wrapped
    - ``str`` shorthand — parsed as ``provider/model``:
        - ``"openai/text-embedding-3-large"``
        - ``"ollama/nomic-embed-text"``
        - ``"sentence-transformers/all-MiniLM-L6-v2"``

    Examples::

        wrap_embedding("openai/text-embedding-3-large")
        wrap_embedding("ollama/nomic-embed-text")
        wrap_embedding(lambda texts: my_embed(texts))
    """
    if isinstance(embedding, EmbeddingProvider):
        return embedding

    if isinstance(embedding, str):
        return _wrap_embedding_string(embedding)

    if callable(embedding):
        return CallableEmbeddingProvider(embedding)

    msg = (
        f"Cannot auto-wrap {type(embedding).__name__} as EmbeddingProvider. "
        "Pass a string like 'openai/text-embedding-3-large', "
        "a callable(list[str]) -> list[list[float]], "
        "or an EmbeddingProvider instance."
    )
    raise TypeError(msg)


def _wrap_embedding_string(spec: str) -> EmbeddingProvider:
    """Parse a 'provider/model' string into an EmbeddingProvider."""
    if "/" not in spec:
        msg = f"Embedding string must be 'provider/model', got: {spec!r}"
        raise ValueError(msg)

    provider, model = spec.split("/", 1)
    provider = provider.lower()

    if provider == "openai":
        return OpenAIEmbeddingProvider(model=model)

    if provider == "ollama":
        return OllamaEmbeddingProvider(model=model)

    if provider in ("sentence-transformers", "st", "sbert"):
        return SentenceTransformerProvider(model_name=model)

    if provider == "litellm":

        def _litellm_embed(texts: list[str]) -> list[list[float]]:
            try:
                import litellm
            except ImportError:
                raise ImportError(
                    "litellm is required for 'litellm/...' shorthand. "
                    "Install with: pip install litellm"
                )
            response = litellm.embedding(model=model, input=texts)
            return [item["embedding"] for item in response.data]

        return CallableEmbeddingProvider(_litellm_embed)

    # Fallback: treat as OpenAI-compatible with provider as hint
    return OpenAIEmbeddingProvider(model=model)


# ---------------------------------------------------------------------------
# EmbeddingIndex
# ---------------------------------------------------------------------------


class EmbeddingIndex:
    """Stores tool embeddings for similarity search.

    Supports two modes:
    1. Manual: call ``add(name, embedding)`` directly.
    2. Automatic: call ``build_from_tools(tools)`` with a provider.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self._embeddings: dict[str, list[float]] = {}
        self._provider = provider
        # Backward compat: model_name without provider → sentence-transformers
        if provider is None and model_name is not None:
            self._provider = SentenceTransformerProvider(model_name=model_name)

    def _tool_text(self, tool: Any) -> str:
        """Build a searchable text string from a ToolSchema."""
        parts = [tool.name, tool.description]
        parts.extend(tool.tags)
        parts.extend(p.name for p in tool.parameters)
        return " ".join(p for p in parts if p)

    def encode(self, text: str) -> list[float]:
        """Encode a text string using the provider."""
        if self._provider is None:
            raise ValueError("No embedding provider configured.")
        return self._provider.encode(text)

    def build_from_tools(self, tools: dict[str, Any]) -> None:
        """Build embeddings for all tools."""
        if not tools or self._provider is None:
            return

        texts = []
        names = []
        for name, tool in tools.items():
            names.append(name)
            texts.append(self._tool_text(tool))

        embeddings = self._provider.encode_batch(texts)
        for name, emb in zip(names, embeddings):
            self._embeddings[name] = emb

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
