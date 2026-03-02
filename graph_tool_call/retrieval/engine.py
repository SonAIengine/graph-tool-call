"""Unified retrieval engine: graph traversal + optional embedding hybrid search."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType
from graph_tool_call.retrieval.graph_search import GraphSearcher
from graph_tool_call.retrieval.keyword import BM25Scorer


class SearchMode(str, Enum):
    """Retrieval search modes."""

    BASIC = "basic"  # BM25 + graph + embedding + RRF
    ENHANCED = "enhanced"  # + query expansion (Tier 1)
    FULL = "full"  # + intent decomposition (Tier 2)


class RetrievalEngine:
    """Combines keyword matching, graph traversal, and optional embedding for tool retrieval."""

    def __init__(
        self,
        graph: GraphEngine,
        tools: dict[str, ToolSchema],
        graph_weight: float = 0.7,
        keyword_weight: float = 0.3,
        embedding_weight: float = 0.0,
        annotation_weight: float = 0.2,
    ) -> None:
        self._graph = graph
        self._tools = tools
        self._searcher = GraphSearcher(graph)
        self._graph_weight = graph_weight
        self._keyword_weight = keyword_weight
        self._embedding_weight = embedding_weight
        self._annotation_weight = annotation_weight
        self._embedding_index: Any = None
        self._bm25: BM25Scorer | None = None

    def _get_bm25(self) -> BM25Scorer:
        """Lazy-initialize BM25 scorer."""
        if self._bm25 is None:
            self._bm25 = BM25Scorer(self._tools)
        return self._bm25

    def set_embedding_index(self, index: Any) -> None:
        """Attach an EmbeddingIndex for hybrid search."""
        self._embedding_index = index
        # Rebalance weights when embedding is available
        if self._embedding_weight == 0.0:
            self._graph_weight = 0.5
            self._keyword_weight = 0.2
            self._embedding_weight = 0.3

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
    ) -> list[ToolSchema]:
        """Retrieve the most relevant tools for a query.

        Parameters
        ----------
        query:
            Natural language search query.
        top_k:
            Maximum number of results.
        max_graph_depth:
            BFS depth for graph expansion.
        mode:
            Search mode: BASIC, ENHANCED, or FULL.
        llm:
            Optional SearchLLM for ENHANCED/FULL modes.
            If None, ENHANCED/FULL fall back to BASIC.
        """
        if isinstance(mode, str):
            mode = SearchMode(mode)

        # --- BASIC pipeline (always runs) ---
        keyword_scores = self._get_bm25().score(query)
        if not keyword_scores:
            keyword_scores = self._keyword_match(query)

        # Graph expansion from keyword seeds
        sorted_by_score = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        seed_tools = [name for name, _ in sorted_by_score[:5]]
        graph_scores: dict[str, float] = {}
        if seed_tools:
            expanded = self._searcher.expand_from_seeds(
                seed_tools, max_depth=max_graph_depth, max_results=top_k * 3
            )
            graph_scores = dict(expanded)

        # Optional embedding scores
        embedding_scores: dict[str, float] = {}
        if self._embedding_index is not None and self._embedding_index.size > 0:
            try:
                query_emb = self._embedding_index.encode(query)
                emb_results = self._embedding_index.search(query_emb, top_k=top_k * 3)
                embedding_scores = dict(emb_results)
            except (ValueError, ImportError):
                pass

        # Embedding fallback: keyword+graph 모두 빈 결과일 때 embedding으로 seed 생성
        if not keyword_scores and not graph_scores and embedding_scores:
            emb_seeds = [
                name
                for name, _ in sorted(embedding_scores.items(), key=lambda x: x[1], reverse=True)[
                    :5
                ]
            ]
            expanded = self._searcher.expand_from_seeds(
                emb_seeds, max_depth=max_graph_depth, max_results=top_k * 3
            )
            graph_scores = dict(expanded)

        # Annotation-aware scoring
        from graph_tool_call.retrieval.annotation_scorer import compute_annotation_scores
        from graph_tool_call.retrieval.intent import classify_intent

        query_intent = classify_intent(query)
        annotation_scores = compute_annotation_scores(query_intent, self._tools)

        # Collect all score sources for wRRF
        score_sources: list[tuple[dict[str, float], float]] = [
            (keyword_scores, 1.0),
            (graph_scores, 1.0),
            (embedding_scores, 1.0),
            (annotation_scores, self._annotation_weight),
        ]

        # --- ENHANCED: query expansion (Tier 1) ---
        if mode in (SearchMode.ENHANCED, SearchMode.FULL) and llm is not None:
            expanded = llm.expand_query(query)
            expanded_terms = expanded.keywords + expanded.synonyms + expanded.english_terms
            if expanded_terms:
                expanded_query = " ".join(expanded_terms)
                expanded_scores = self._get_bm25().score(expanded_query)
                if not expanded_scores:
                    expanded_scores = self._keyword_match(expanded_query)
                if expanded_scores:
                    score_sources.append((expanded_scores, 0.7))

        # --- FULL: intent decomposition (Tier 2) ---
        if mode == SearchMode.FULL and llm is not None:
            intents = llm.decompose_intents(query)
            for intent in intents:
                intent_query = intent.to_query()
                intent_scores = self._get_bm25().score(intent_query)
                if not intent_scores:
                    intent_scores = self._keyword_match(intent_query)
                if intent_scores:
                    score_sources.append((intent_scores, 0.5))

        # --- wRRF fusion ---
        active_sources = [(s, w) for s, w in score_sources if s]
        if active_sources:
            fused_scores = self._wrrf_fuse(active_sources)
        else:
            fused_scores = {}

        # Filter to TOOL nodes only and sort
        final_scores: list[tuple[str, float]] = []
        for name, score in fused_scores.items():
            if not self._graph.has_node(name):
                continue
            attrs = self._graph.get_node_attrs(name)
            if attrs.get("node_type") != NodeType.TOOL:
                continue
            final_scores.append((name, score))

        final_scores.sort(key=lambda x: x[1], reverse=True)

        result: list[ToolSchema] = []
        for name, _ in final_scores[:top_k]:
            if name in self._tools:
                result.append(self._tools[name])
        return result

    @staticmethod
    def _rrf_fuse(
        *score_dicts: dict[str, float],
        k: int = 60,
    ) -> dict[str, float]:
        """Reciprocal Rank Fusion over multiple score dictionaries.

        For each scoring method, sort by score descending to get rank.
        RRF_score(d) = sum(1/(k + rank_i(d)))
        """
        fused: dict[str, float] = {}
        for scores in score_dicts:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            for rank, (name, _) in enumerate(ranked, start=1):
                fused[name] = fused.get(name, 0.0) + 1.0 / (k + rank)
        return fused

    @staticmethod
    def _wrrf_fuse(
        weighted_sources: list[tuple[dict[str, float], float]],
        k: int = 60,
    ) -> dict[str, float]:
        """Weighted Reciprocal Rank Fusion.

        Each source has an associated weight.
        wRRF_score(d) = sum(weight_i / (k + rank_i(d)))
        """
        fused: dict[str, float] = {}
        for scores, weight in weighted_sources:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            for rank, (name, _) in enumerate(ranked, start=1):
                fused[name] = fused.get(name, 0.0) + weight / (k + rank)
        return fused

    def _keyword_match(self, query: str) -> dict[str, float]:
        """Simple keyword overlap scoring between query and tool name/description.

        Kept as fallback for when BM25 returns empty results.
        """
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return {}

        scores: dict[str, float] = {}
        for name, tool in self._tools.items():
            tool_tokens = set(self._tokenize(tool.name)) | set(self._tokenize(tool.description))
            for t in tool.tags:
                tool_tokens.update(self._tokenize(t))

            if not tool_tokens:
                continue

            overlap = len(query_tokens & tool_tokens)
            score = overlap / max(len(query_tokens), 1)
            if score > 0:
                scores[name] = min(score, 1.0)

        return scores

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split text into lowercase tokens."""
        return [t.lower() for t in re.split(r"[\s_\-/.,;:!?()]+", text) if t]
