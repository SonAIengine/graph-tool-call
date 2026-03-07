"""MMR (Maximal Marginal Relevance) diversity reranking."""

from __future__ import annotations

import re
from typing import Any

from graph_tool_call.core.tool import ToolSchema


def _tool_tokens(tool: ToolSchema) -> set[str]:
    """Extract token set from a tool for Jaccard similarity."""
    parts = [tool.name, tool.description]
    parts.extend(tool.tags)
    raw = " ".join(p for p in parts if p)
    return {t.lower() for t in re.split(r"[\s_\-/.,;:!?()]+", raw) if t}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr_rerank(
    tools: list[ToolSchema],
    scores: dict[str, float],
    *,
    lambda_: float = 0.7,
    top_k: int | None = None,
    embedding_index: Any = None,
) -> list[ToolSchema]:
    """Maximal Marginal Relevance reranking for diversity.

    Balances relevance (from initial scores) with diversity (dissimilarity
    to already-selected tools).

    Parameters
    ----------
    tools:
        Candidate tools in initial ranked order.
    scores:
        Relevance scores from wRRF fusion (tool_name -> score).
    lambda_:
        Balance between relevance (1.0) and diversity (0.0). Default 0.7.
    top_k:
        Maximum results. If None, reranks all.
    embedding_index:
        Optional EmbeddingIndex for embedding-based similarity.
        Falls back to Jaccard token similarity if not available.
    """
    if not tools:
        return []

    k = top_k if top_k is not None else len(tools)
    if k <= 0:
        return []

    # Precompute token sets for Jaccard fallback
    use_embedding = embedding_index is not None and embedding_index.size > 0 and _has_numpy()
    token_cache: dict[str, set[str]] = {}
    emb_cache: dict[str, Any] = {}

    if use_embedding:
        np = _get_numpy()
        for t in tools:
            emb = embedding_index._embeddings.get(t.name)
            if emb is not None:
                emb_cache[t.name] = np.array(emb, dtype=np.float32)
    else:
        for t in tools:
            token_cache[t.name] = _tool_tokens(t)

    # Normalize relevance scores to [0, 1]
    max_score = max(scores.values()) if scores else 1.0
    if max_score == 0:
        max_score = 1.0

    remaining = list(tools)
    selected: list[ToolSchema] = []

    while remaining and len(selected) < k:
        best_tool = None
        best_mmr = -float("inf")

        for candidate in remaining:
            rel = scores.get(candidate.name, 0.0) / max_score

            # Max similarity to any already-selected tool
            max_sim = 0.0
            for sel in selected:
                sim = _compute_similarity(candidate, sel, token_cache, emb_cache, use_embedding)
                if sim > max_sim:
                    max_sim = sim

            mmr_score = lambda_ * rel - (1 - lambda_) * max_sim
            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_tool = candidate

        if best_tool is not None:
            selected.append(best_tool)
            remaining.remove(best_tool)

    return selected


def _compute_similarity(
    a: ToolSchema,
    b: ToolSchema,
    token_cache: dict[str, set[str]],
    emb_cache: dict[str, Any],
    use_embedding: bool,
) -> float:
    """Compute similarity between two tools."""
    if use_embedding and a.name in emb_cache and b.name in emb_cache:
        np = _get_numpy()
        va = emb_cache[a.name]
        vb = emb_cache[b.name]
        norm_a = np.linalg.norm(va)
        norm_b = np.linalg.norm(vb)
        if norm_a > 0 and norm_b > 0:
            return float(np.dot(va, vb) / (norm_a * norm_b))
    # Fallback to Jaccard
    ta = token_cache.get(a.name) or _tool_tokens(a)
    tb = token_cache.get(b.name) or _tool_tokens(b)
    return _jaccard(ta, tb)


def _has_numpy() -> bool:
    try:
        import numpy as np  # noqa: F401

        return True
    except ImportError:
        return False


def _get_numpy() -> Any:
    import numpy as np

    return np
