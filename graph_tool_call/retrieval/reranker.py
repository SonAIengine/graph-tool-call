"""Cross-encoder reranking for tool retrieval (optional dependency)."""

from __future__ import annotations

from typing import Any

from graph_tool_call.core.tool import ToolSchema


def _require_cross_encoder() -> Any:
    """Lazily import CrossEncoder with a friendly error message."""
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder
    except ImportError:
        raise ImportError(
            "sentence-transformers is required for cross-encoder reranking. "
            "Install with: pip install graph-tool-call[embedding]"
        )


class CrossEncoderReranker:
    """Reranks tool candidates using a cross-encoder model.

    Cross-encoders jointly encode (query, document) pairs for more precise
    relevance scoring than bi-encoder similarity. Best used as a second stage
    after initial retrieval to refine the top-N candidates.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _get_model(self) -> Any:
        """Lazy-load the cross-encoder model."""
        if self._model is None:
            ce_cls = _require_cross_encoder()
            self._model = ce_cls(self._model_name)
        return self._model

    def _tool_text(self, tool: ToolSchema) -> str:
        """Build a searchable text string from a ToolSchema."""
        parts = [tool.name, tool.description]
        parts.extend(tool.tags)
        parts.extend(p.name for p in tool.parameters)
        return " ".join(p for p in parts if p)

    def rerank(
        self,
        query: str,
        tools: list[ToolSchema],
        top_k: int | None = None,
    ) -> list[ToolSchema]:
        """Rerank tools by cross-encoder relevance score.

        Parameters
        ----------
        query:
            The search query.
        tools:
            Candidate tools from initial retrieval.
        top_k:
            Maximum number of results to return. If None, returns all reranked.
        """
        if not tools:
            return []

        model = self._get_model()
        pairs = [[query, self._tool_text(t)] for t in tools]
        scores = model.predict(pairs)

        scored = sorted(zip(tools, scores), key=lambda x: x[1], reverse=True)
        result = [t for t, _ in scored]
        if top_k is not None:
            result = result[:top_k]
        return result
