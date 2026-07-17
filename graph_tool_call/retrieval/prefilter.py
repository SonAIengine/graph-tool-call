"""Category prefilter — narrow a thousands-tool corpus to a candidate pool.

At small corpus sizes every retrieval channel (BM25, embedding, annotation,
graph) scores the whole corpus cheaply. Past a few thousand tools that gets
wasteful: the answer almost always lives in a handful of resource categories
the query names, plus whatever BM25 already surfaced.

:class:`CategoryPrefilter` builds a *candidate pool* from two signals —

  * **category token match** — reuse ``GraphSearcher.resource_first_search``
    (which walks the CATEGORY index / ``_get_category_index``) to find tools in
    the categories the query mentions;
  * **embedding centroid match** *(only when an embedding index is attached)* —
    match the query against per-category centroids and pull in those members.

— then **unions the raw BM25 top-N** into it. That union is a hard
recall-preserving guard: any tool BM25 would have ranked highly is in the pool
no matter what the category signal did. When the signal is too weak to trust
(no category/centroid hit, or the pool would just be the whole corpus) it
returns ``None`` so the engine scores the full corpus unchanged.

Pool size is bounded to ``[min_pool, max_pool]``: widened via 1-hop graph
neighbours when too narrow (recall padding), capped when too broad (perf) —
capping never drops a BM25-top hit.
"""

from __future__ import annotations

from typing import Any

from graph_tool_call.ontology.schema import NodeType
from graph_tool_call.retrieval.graph_search import GraphSearcher

__all__ = ["CategoryPrefilter"]


class CategoryPrefilter:
    """Reduce a large tool corpus to a recall-preserving candidate pool."""

    def __init__(
        self,
        graph: Any,
        tools: dict[str, Any],
        *,
        min_pool: int = 150,
        max_pool: int = 500,
        embedding_index: Any = None,
    ) -> None:
        self._graph = graph
        self._tools = tools
        self._searcher = GraphSearcher(graph)
        self._min_pool = min_pool
        self._max_pool = max_pool
        self._embedding_index = embedding_index
        # Lazy caches — category membership and (embedding) centroids.
        self._category_members: dict[str, set[str]] | None = None
        self._centroids: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def candidate_pool(
        self,
        query: str,
        intent: Any,
        bm25_top: list[str] | None,
        *,
        resource_scored: dict[str, float] | None = None,
    ) -> set[str] | None:
        """Return a candidate-tool pool for *query*, or ``None`` to disable.

        ``bm25_top`` is the raw BM25 top-N (order irrelevant) — it is always
        unioned in as the recall guard. ``None`` means "no usable signal, score
        the full corpus" (the engine treats a ``None`` pool as no prefilter).

        ``resource_scored`` lets the caller pass an already-computed
        ``resource_first_search`` result (the engine shares one call between
        this prefilter and its graph channel) so the category match isn't run
        twice; when ``None`` it is computed here.
        """
        bm25_set = {t for t in (bm25_top or []) if t in self._tools}

        # Category token signal (reuses the CATEGORY index + resource scoring).
        if resource_scored is None:
            cat_scored = self._searcher.resource_first_search(
                query, intent=intent, max_results=self._max_pool, tools=self._tools
            )
        else:
            cat_scored = resource_scored
        signal: set[str] = set(cat_scored)
        # Embedding centroid signal (no-op without an attached index).
        emb_tools = self._centroid_matched_tools(query)
        signal |= emb_tools

        if not signal:
            return None  # weak signal → let the engine score the full corpus

        pool = signal | bm25_set  # recall guard: BM25-top always retained
        n = len(self._tools)
        if len(pool) >= n:
            return None  # pool ≈ whole corpus → prefiltering buys nothing

        if len(pool) < self._min_pool:
            self._widen(pool, cat_scored, bm25_set)
        if len(pool) > self._max_pool:
            pool = self._cap(cat_scored, emb_tools, bm25_set)

        return pool or None

    def set_embedding_index(self, index: Any) -> None:
        """Attach/replace the embedding index (invalidates centroid cache)."""
        self._embedding_index = index
        self._centroids = None

    # ------------------------------------------------------------------
    # pool shaping
    # ------------------------------------------------------------------

    def _widen(
        self,
        pool: set[str],
        cat_scored: dict[str, float],
        bm25_set: set[str],
    ) -> None:
        """Pad a too-narrow pool with 1-hop graph neighbours (in place).

        Adds tools related to the strongest category hits so embedding /
        annotation-only relevant tools nearby aren't excluded. Best-effort — if
        the graph is sparse the pool may stay below ``min_pool``.
        """
        seeds = [n for n, _ in sorted(cat_scored.items(), key=lambda x: -x[1])[:20]]
        if not seeds:
            seeds = list(bm25_set)[:20]
        if not seeds:
            return
        for name, _ in self._searcher.expand_from_seeds(
            seeds, max_depth=1, max_results=self._min_pool * 2
        ):
            if name in self._tools:
                pool.add(name)
            if len(pool) >= self._min_pool:
                break

    def _cap(
        self,
        cat_scored: dict[str, float],
        emb_tools: set[str],
        bm25_set: set[str],
    ) -> set[str]:
        """Cap a too-broad pool at ``max_pool``, never dropping a BM25-top hit.

        BM25-top is seeded first (recall guard), then the highest-scoring
        category tools, then any embedding members, until the cap is hit.
        """
        keep = set(bm25_set)
        for name, _ in sorted(cat_scored.items(), key=lambda x: -x[1]):
            if len(keep) >= self._max_pool:
                break
            keep.add(name)
        for name in emb_tools:
            if len(keep) >= self._max_pool:
                break
            keep.add(name)
        return keep

    # ------------------------------------------------------------------
    # embedding centroid matching (only when an index is attached)
    # ------------------------------------------------------------------

    def _centroid_matched_tools(self, query: str) -> set[str]:
        """Tools of the categories whose embedding centroid matches *query*.

        Returns an empty set when no embedding index is attached or anything
        goes wrong — the deterministic category-token path is the default.
        """
        idx = self._embedding_index
        if idx is None or getattr(idx, "size", 0) <= 0:
            return set()
        try:
            import numpy as np

            centroids = self._get_centroids()
            if not centroids:
                return set()
            q = np.asarray(idx.encode(query), dtype=np.float32)
            qn = float(np.linalg.norm(q))
            if qn == 0.0:
                return set()
            q = q / qn
            scored = sorted(
                ((cat, float(q @ vec)) for cat, vec in centroids.items()),
                key=lambda x: -x[1],
            )
            members = self._get_category_members()
            out: set[str] = set()
            for cat, sim in scored[:3]:
                if sim <= 0.2:
                    break
                out |= members.get(cat, set())
            return out
        except Exception:  # noqa: BLE001 — best-effort optional signal
            return set()

    def _get_category_members(self) -> dict[str, set[str]]:
        """Build ``category_node -> {tool names}`` from the graph (cached)."""
        if self._category_members is not None:
            return self._category_members
        members: dict[str, set[str]] = {}
        for node in self._graph.nodes():
            attrs = self._graph.get_node_attrs(node)
            if attrs.get("node_type") != NodeType.CATEGORY:
                continue
            tools: set[str] = set()
            for neighbor in self._graph.get_neighbors(node, direction="in"):
                n_attrs = self._graph.get_node_attrs(neighbor)
                if n_attrs.get("node_type") == NodeType.TOOL and neighbor in self._tools:
                    tools.add(neighbor)
            if tools:
                members[node] = tools
        self._category_members = members
        return members

    def _get_centroids(self) -> dict[str, Any]:
        """Mean-of-members embedding centroid per category (cached, normalized)."""
        if self._centroids is not None:
            return self._centroids
        idx = self._embedding_index
        centroids: dict[str, Any] = {}
        embeddings = getattr(idx, "_embeddings", None)
        if not embeddings:
            self._centroids = centroids
            return centroids
        import numpy as np

        for cat, tool_names in self._get_category_members().items():
            vecs = [embeddings[t] for t in tool_names if t in embeddings]
            if not vecs:
                continue
            mat = np.asarray(vecs, dtype=np.float32)
            mean = mat.mean(axis=0)
            norm = float(np.linalg.norm(mean))
            if norm > 0:
                centroids[cat] = mean / norm
        self._centroids = centroids
        return centroids
