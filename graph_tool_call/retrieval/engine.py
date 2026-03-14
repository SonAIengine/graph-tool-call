"""Unified retrieval engine: graph traversal + optional embedding hybrid search."""

from __future__ import annotations

import re
from dataclasses import dataclass
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


@dataclass
class RetrievalResult:
    """A single retrieval result with score breakdown.

    Provides transparency into why a tool was ranked at a certain position,
    enabling LLMs to make more informed tool selection decisions.
    """

    tool: ToolSchema
    score: float = 0.0
    keyword_score: float = 0.0
    graph_score: float = 0.0
    embedding_score: float = 0.0
    annotation_score: float = 0.0

    @property
    def confidence(self) -> str:
        """Human-readable confidence level."""
        if self.score >= 0.02:
            return "high"
        if self.score >= 0.01:
            return "medium"
        return "low"


class RetrievalEngine:
    """Combines keyword matching, graph traversal, and optional embedding for tool retrieval."""

    def __init__(
        self,
        graph: GraphEngine,
        tools: dict[str, ToolSchema],
        graph_weight: float = 0.5,
        keyword_weight: float = 0.5,
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
        self._reranker: Any = None
        self._diversity_lambda: float | None = None

    def _get_bm25(self) -> BM25Scorer:
        """Lazy-initialize BM25 scorer."""
        if self._bm25 is None:
            self._bm25 = BM25Scorer(self._tools)
        return self._bm25

    def set_embedding_index(self, index: Any) -> None:
        """Attach an EmbeddingIndex for hybrid search."""
        self._embedding_index = index
        # Rebalance weights when embedding is available.
        # Boost embedding to cover semantic/cross-language gaps;
        # keep keyword strong for exact matches; reduce graph noise.
        if self._embedding_weight == 0.0:
            self._graph_weight = 0.45
            self._keyword_weight = 0.25
            self._embedding_weight = 0.3

    def set_weights(
        self,
        *,
        keyword: float | None = None,
        graph: float | None = None,
        embedding: float | None = None,
        annotation: float | None = None,
    ) -> None:
        """Manually set wRRF fusion weights."""
        if keyword is not None:
            self._keyword_weight = keyword
        if graph is not None:
            self._graph_weight = graph
        if embedding is not None:
            self._embedding_weight = embedding
        if annotation is not None:
            self._annotation_weight = annotation

    def set_reranker(self, reranker: Any) -> None:
        """Attach a CrossEncoderReranker for second-stage reranking."""
        self._reranker = reranker

    def set_diversity(self, lambda_: float = 0.7) -> None:
        """Enable MMR diversity reranking.

        Parameters
        ----------
        lambda_:
            Balance between relevance (1.0) and diversity (0.0). Default 0.7.
        """
        self._diversity_lambda = lambda_

    def _run_pipeline(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
        history: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Core retrieval pipeline. Returns results with full score breakdown."""
        if isinstance(mode, str):
            mode = SearchMode(mode)

        # --- History-aware query augmentation ---
        effective_query = query
        if history:
            history_context = []
            for tool_name in history:
                if tool_name in self._tools:
                    t = self._tools[tool_name]
                    history_context.append(f"{t.name} {t.description}")
            if history_context:
                effective_query = query + " " + " ".join(history_context)

        # --- BASIC pipeline (always runs) ---
        keyword_scores = self._get_bm25().score(effective_query)
        if not keyword_scores:
            keyword_scores = self._keyword_match(query)

        # Graph expansion from keyword seeds + history seeds
        sorted_by_score = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        seed_tools = [name for name, _ in sorted_by_score[:10]]
        if history:
            for tool_name in history:
                if tool_name in self._tools and tool_name not in seed_tools:
                    seed_tools.append(tool_name)
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

        # Embedding-augmented graph seeds: add top embedding hits as extra seeds
        # so graph expansion benefits from semantic matches, not just BM25 keywords.
        if embedding_scores:
            emb_top = sorted(embedding_scores.items(), key=lambda x: x[1], reverse=True)
            for name, _ in emb_top[:3]:
                if name not in seed_tools:
                    seed_tools.append(name)
            if seed_tools and not graph_scores:
                expanded = self._searcher.expand_from_seeds(
                    seed_tools, max_depth=max_graph_depth, max_results=top_k * 3
                )
                graph_scores = dict(expanded)
            elif seed_tools:
                extra = self._searcher.expand_from_seeds(
                    seed_tools, max_depth=max_graph_depth, max_results=top_k * 3
                )
                for name, score in extra:
                    if name not in graph_scores or score > graph_scores[name]:
                        graph_scores[name] = score

        # Annotation-aware scoring
        from graph_tool_call.retrieval.annotation_scorer import compute_annotation_scores
        from graph_tool_call.retrieval.intent import classify_intent

        query_intent = classify_intent(query)
        annotation_scores = compute_annotation_scores(query_intent, self._tools)

        # Collect all score sources for wRRF (use configured weights)
        score_sources: list[tuple[dict[str, float], float]] = [
            (keyword_scores, self._keyword_weight),
            (graph_scores, self._graph_weight),
            (embedding_scores, self._embedding_weight),
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
        final_scores: dict[str, float] = {}
        for name, score in fused_scores.items():
            if not self._graph.has_node(name):
                continue
            attrs = self._graph.get_node_attrs(name)
            if attrs.get("node_type") != NodeType.TOOL:
                continue
            final_scores[name] = score

        # History boost: slightly demote already-used tools to favor new discoveries
        if history:
            for tool_name in history:
                if tool_name in final_scores:
                    final_scores[tool_name] *= 0.8

        ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)

        # Determine how many candidates to pass to post-processing
        rerank_pool = top_k * 3 if (self._reranker or self._diversity_lambda) else top_k
        candidates: list[RetrievalResult] = []
        for name, fused_score in ranked[:rerank_pool]:
            if name in self._tools:
                candidates.append(
                    RetrievalResult(
                        tool=self._tools[name],
                        score=fused_score,
                        keyword_score=keyword_scores.get(name, 0.0),
                        graph_score=graph_scores.get(name, 0.0),
                        embedding_score=embedding_scores.get(name, 0.0),
                        annotation_score=annotation_scores.get(name, 0.0),
                    )
                )

        # --- Cross-encoder reranking ---
        if self._reranker is not None and candidates:
            tools_only = [r.tool for r in candidates]
            reranked = self._reranker.rerank(query, tools_only, top_k=top_k * 2)
            reranked_names = {t.name for t in reranked}
            candidates = [r for r in candidates if r.tool.name in reranked_names]
            name_to_result = {r.tool.name: r for r in candidates}
            candidates = [name_to_result[t.name] for t in reranked if t.name in name_to_result]

        # --- MMR diversity reranking ---
        if self._diversity_lambda is not None and candidates:
            from graph_tool_call.retrieval.diversity import mmr_rerank

            tools_only = [r.tool for r in candidates]
            diverse = mmr_rerank(
                tools_only,
                final_scores,
                lambda_=self._diversity_lambda,
                top_k=top_k,
                embedding_index=self._embedding_index,
            )
            diverse_names = [t.name for t in diverse]
            name_to_result = {r.tool.name: r for r in candidates}
            candidates = [name_to_result[n] for n in diverse_names if n in name_to_result]

        return candidates[:top_k]

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
        history: list[str] | None = None,
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
        history:
            Optional list of previously called tool names in the current session.
            Enables history-aware retrieval: boosts tools related to prior calls
            and uses them as additional graph seeds.
        """
        results = self._run_pipeline(
            query, top_k=top_k, max_graph_depth=max_graph_depth, mode=mode, llm=llm, history=history
        )
        return [r.tool for r in results]

    def retrieve_with_scores(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
        history: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve tools with full score breakdown.

        Same as ``retrieve()`` but returns ``RetrievalResult`` objects
        containing per-source scores and confidence levels.
        """
        return self._run_pipeline(
            query, top_k=top_k, max_graph_depth=max_graph_depth, mode=mode, llm=llm, history=history
        )

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
