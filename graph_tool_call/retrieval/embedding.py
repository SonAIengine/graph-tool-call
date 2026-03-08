"""Optional embedding-based similarity search (Phase 2).

Supports multiple embedding providers via ``wrap_embedding()`` auto-detection:

- ``"openai/text-embedding-3-large"`` — OpenAI Embeddings API
- ``"ollama/nomic-embed-text"`` — Ollama local embeddings
- ``"sentence-transformers/all-MiniLM-L6-v2"`` — local sentence-transformers
- ``"vllm/Qwen/Qwen3-0.6B"`` — vLLM (OpenAI-compatible, localhost:8000)
- ``"llamacpp/qwen3-0.6b"`` — llama.cpp server (localhost:8080)
- ``"vllm/model@http://host:port/v1"`` — custom URL
- ``"http://host:port/v1@model"`` — URL@model format (any server)
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
    """OpenAI-compatible Embeddings API provider.

    Works with any server that implements ``POST /v1/embeddings``:

    - OpenAI API (requires ``OPENAI_API_KEY``)
    - vLLM (``base_url="http://localhost:8000/v1"``)
    - llama.cpp server (``base_url="http://localhost:8080/v1"``)
    - LocalAI, LiteLLM proxy, etc.

    Examples::

        # OpenAI
        OpenAIEmbeddingProvider(model="text-embedding-3-large")
        # vLLM with any model
        OpenAIEmbeddingProvider(model="Qwen/Qwen3-0.6B", base_url="http://localhost:8000/v1")
        # llama.cpp
        OpenAIEmbeddingProvider(model="qwen3-0.6b", base_url="http://localhost:8080/v1")
    """

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
        self._is_local = not self.base_url.startswith("https://api.openai.com")

        if not api_key:
            import os

            api_key = os.environ.get("OPENAI_API_KEY", "")
        self.api_key = api_key

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not self._is_local and not self.api_key:
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
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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
        - ``"vllm/Qwen/Qwen3-0.6B"`` — vLLM on localhost:8000
        - ``"llamacpp/qwen3-0.6b"`` — llama.cpp on localhost:8080
        - ``"vllm/model@http://host:port/v1"`` — custom URL
        - ``"http://host:port/v1@model"`` — URL@model format

    Examples::

        wrap_embedding("openai/text-embedding-3-large")
        wrap_embedding("ollama/nomic-embed-text")
        wrap_embedding("vllm/Qwen/Qwen3-0.6B")
        wrap_embedding("llamacpp/qwen3@http://192.168.1.10:8080/v1")
        wrap_embedding("http://localhost:8000/v1@my-model")
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
    """Parse a 'provider/model' or 'url@model' string into an EmbeddingProvider.

    Supported formats::

        # Named providers
        "openai/text-embedding-3-large"
        "ollama/nomic-embed-text"
        "sentence-transformers/all-MiniLM-L6-v2"
        "litellm/text-embedding-3-large"

        # Local OpenAI-compatible servers (vLLM, llama.cpp, LocalAI, etc.)
        "vllm/Qwen/Qwen3-0.6B"                          # localhost:8000
        "vllm/Qwen/Qwen3-0.6B@http://gpu-box:8000/v1"   # custom URL
        "llamacpp/qwen3-0.6b"                            # localhost:8080
        "llamacpp/qwen3@http://192.168.1.10:8080/v1"     # custom URL
        "http://localhost:8000/v1@my-model"               # URL@model (any server)
    """
    # URL@model format: "http://host:port/v1@model-name"
    if spec.startswith(("http://", "https://")) and "@" in spec:
        url, model = spec.rsplit("@", 1)
        return OpenAIEmbeddingProvider(model=model, base_url=url)

    if "/" not in spec:
        msg = f"Embedding string must be 'provider/model', got: {spec!r}"
        raise ValueError(msg)

    provider, rest = spec.split("/", 1)
    provider = provider.lower()

    if provider == "openai":
        return OpenAIEmbeddingProvider(model=rest)

    if provider == "ollama":
        return OllamaEmbeddingProvider(model=rest)

    if provider in ("sentence-transformers", "st", "sbert"):
        return SentenceTransformerProvider(model_name=rest)

    # vLLM: "vllm/model" or "vllm/model@url"
    if provider == "vllm":
        default_url = "http://localhost:8000/v1"
        if "@" in rest:
            model, url = rest.rsplit("@", 1)
        else:
            model, url = rest, default_url
        return OpenAIEmbeddingProvider(model=model, base_url=url)

    # llama.cpp: "llamacpp/model" or "llamacpp/model@url"
    if provider in ("llamacpp", "llama-cpp", "llama_cpp"):
        default_url = "http://localhost:8080/v1"
        if "@" in rest:
            model, url = rest.rsplit("@", 1)
        else:
            model, url = rest, default_url
        return OpenAIEmbeddingProvider(model=model, base_url=url)

    # LocalAI: "localai/model" or "localai/model@url"
    if provider == "localai":
        default_url = "http://localhost:8080/v1"
        if "@" in rest:
            model, url = rest.rsplit("@", 1)
        else:
            model, url = rest, default_url
        return OpenAIEmbeddingProvider(model=model, base_url=url)

    if provider == "litellm":

        def _litellm_embed(texts: list[str]) -> list[list[float]]:
            try:
                import litellm
            except ImportError:
                raise ImportError(
                    "litellm is required for 'litellm/...' shorthand. "
                    "Install with: pip install litellm"
                )
            response = litellm.embedding(model=rest, input=texts)
            return [item["embedding"] for item in response.data]

        return CallableEmbeddingProvider(_litellm_embed)

    # Fallback: treat as OpenAI-compatible with provider as hint
    return OpenAIEmbeddingProvider(model=rest)


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
