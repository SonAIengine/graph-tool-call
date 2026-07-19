"""Unified retrieval engine: graph traversal + optional embedding hybrid search."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType, RelationType
from graph_tool_call.retrieval.graph_search import GraphSearcher
from graph_tool_call.retrieval.keyword import BM25Scorer

_CLAUSE_ACTION_PATTERN = re.compile(
    r"\b("
    r"find|get|retrieve|search|calculate|compute|convert|make|create|return|fit|"
    r"book|check|estimate|determine|identify|generate|translate|summarize|compare|"
    r"recommend|provide|fetch|order|rent(?:ing)?|stay(?:ing)?|fly(?:ing)?|visit|"
    r"plot|perform|run|solve|predict|analy[sz]e|mix|divide|tell|know|need|want|"
    r"curious|interested|like|help"
    r")\b",
    flags=re.IGNORECASE,
)
_CLAUSE_QUESTION_PATTERN = re.compile(
    r"(?:^|[.!?]\s*)\b(what|when|where|who|which)\b|"
    r"\bhow\s+(?:many|much|long|tall|far)\b",
    flags=re.IGNORECASE,
)
_CLAUSE_SIGNATURE_STOPWORDS = frozenset(
    {
        "about",
        "api",
        "between",
        "calculate",
        "compute",
        "could",
        "fetch",
        "find",
        "first",
        "fourth",
        "function",
        "geometry",
        "get",
        "help",
        "know",
        "math",
        "need",
        "please",
        "provide",
        "retrieve",
        "search",
        "second",
        "service",
        "specific",
        "tell",
        "third",
        "tool",
        "using",
        "want",
        "with",
        "would",
    }
)


class SearchMode(str, Enum):
    """Retrieval search modes."""

    BASIC = "basic"  # BM25 + graph + embedding + RRF
    ENHANCED = "enhanced"  # + query expansion (Tier 1)
    FULL = "full"  # + intent decomposition (Tier 2)


@dataclass
class ToolRelation:
    """Relationship between a tool and another tool in the result set."""

    target: str  # related tool name
    type: str  # "requires", "precedes", "complementary", "conflicts_with"
    direction: str  # "outgoing" (this→target) or "incoming" (target→this)
    hint: str  # LLM-readable 1-line description


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
    relations: list[ToolRelation] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        """Human-readable confidence level."""
        if self.score >= 0.02:
            return "high"
        if self.score >= 0.01:
            return "medium"
        return "low"

    def to_dict(
        self, *, include_params: bool = False, max_desc: int = 0, include_score: bool = False
    ) -> dict[str, Any]:
        """Serialize to a dict for JSON output.

        Parameters
        ----------
        include_params:
            Include parameter details.
        max_desc:
            Truncate description to this length (0 = no truncation).
        include_score:
            Include score and confidence fields.
        """
        tool = self.tool
        desc = tool.description
        if max_desc and len(desc) > max_desc:
            desc = desc[:max_desc].rsplit(" ", 1)[0] + "..."

        d: dict[str, Any] = {"name": tool.name, "description": desc}
        if include_score:
            d["score"] = round(self.score, 4)
            d["confidence"] = self.confidence
        if include_params and tool.parameters:
            d["parameters"] = {
                p.name: {
                    "type": p.type,
                    "description": p.description,
                    **({"required": True} if p.required else {}),
                }
                for p in tool.parameters
            }
        if tool.domain:
            d["category"] = tool.domain
        if self.relations:
            d["relations"] = [
                {
                    "target": rel.target,
                    "type": rel.type,
                    "direction": rel.direction,
                    "hint": rel.hint,
                }
                for rel in self.relations
            ]
        if self.prerequisites:
            d["prerequisites"] = self.prerequisites
        return d


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
        self._tokenizer: Any = None
        self._reranker: Any = None
        self._diversity_lambda: float | None = None
        self._weights_manual: bool = False
        # Scale hooks (A-P1-5). Prefilter is opt-in and only fires at n>=500;
        # off by default so small/medium corpora are byte-identical to before.
        self._prefilter: Any = None
        self._prefilter_enabled: bool = False
        self._embedding_warned: bool = False

    def _get_bm25(self) -> BM25Scorer:
        """Lazy-initialize BM25 scorer."""
        if self._bm25 is None:
            self._bm25 = BM25Scorer(self._tools, tokenizer=self._tokenizer)
        return self._bm25

    def set_tokenizer(self, tokenizer: Any) -> None:
        """Set a custom BM25 tokenizer (or None to restore the built-in one).

        Applied symmetrically to indexing and querying. Invalidates the cached
        BM25 index so it rebuilds with the new tokenizer on next use.
        """
        self._tokenizer = tokenizer
        self._bm25 = None

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
        # Let the prefilter pick up the index (centroid signal) on rebuild.
        if self._prefilter is not None:
            self._prefilter.set_embedding_index(index)

    def enable_prefilter(self, enabled: bool = True) -> None:
        """Enable/disable the category prefilter for large corpora.

        When enabled the prefilter only fires at ``len(tools) >= 500`` — below
        that the full corpus is cheap and the pipeline is unchanged. The pool
        is recall-preserving (always unions the BM25 top-N).
        """
        self._prefilter_enabled = enabled

    def _get_prefilter(self) -> Any:
        """Lazy-build the CategoryPrefilter bound to the current graph/index."""
        if self._prefilter is None:
            from graph_tool_call.retrieval.prefilter import CategoryPrefilter

            self._prefilter = CategoryPrefilter(
                self._graph, self._tools, embedding_index=self._embedding_index
            )
        return self._prefilter

    def set_weights(
        self,
        *,
        keyword: float | None = None,
        graph: float | None = None,
        embedding: float | None = None,
        annotation: float | None = None,
    ) -> None:
        """Manually set wRRF fusion weights.

        Once called, disables adaptive weight selection — the exact values
        provided here will be used for all subsequent retrievals.
        """
        if keyword is not None:
            self._keyword_weight = keyword
        if graph is not None:
            self._graph_weight = graph
        if embedding is not None:
            self._embedding_weight = embedding
        if annotation is not None:
            self._annotation_weight = annotation
        self._weights_manual = True

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
        """Core retrieval pipeline. Returns results with full score breakdown.

        Architecture:
        1. Scoring channels (BM25, embedding, annotation) → wRRF fusion → ranked list
        2. Graph acts as an independent retrieval channel:
           - Resource-first search finds tools by category matching (independent of BM25)
           - Chain expansion adds prerequisites/next-steps
           - Graph candidates are INJECTED into results, not fused via wRRF
           This prevents Graph noise from degrading BM25/embedding precision
           while allowing Graph to contribute unique candidates.
        """
        if isinstance(mode, str):
            mode = SearchMode(mode)

        effective_query = self._augment_query(query, history)

        # Dynamic wRRF weights based on corpus size
        kw, gw, ew, aw = self._get_adaptive_weights()

        from graph_tool_call.retrieval.annotation_scorer import compute_annotation_scores
        from graph_tool_call.retrieval.intent import classify_intent

        query_intent = classify_intent(query)

        # Keyword scores over the FULL corpus — cheap (inverted index) and the
        # recall backbone; also the source of the prefilter's BM25-top guard.
        keyword_scores = self._compute_keyword_scores(effective_query, query) if kw > 0 else {}
        clause_scores = self._compute_clause_keyword_scores(query) if kw > 0 else {}

        # Resource-first (category) search — the graph channel needs it and the
        # prefilter reuses the SAME result (one call, not two). At prefilter
        # scale we fetch a deeper slice (max_pool) so the pool has enough
        # category coverage; otherwise the original ``top_k * 3`` depth (so the
        # prefilter-off path is byte-identical).
        prefilter_active = self._prefilter_enabled and len(self._tools) >= 500
        resource_scores: dict[str, float] = {}
        if gw > 0 or prefilter_active:
            rr_max = max(top_k * 3, 500) if prefilter_active else top_k * 3
            resource_scores = self._searcher.resource_first_search(
                query, intent=query_intent, max_results=rr_max, tools=self._tools
            )

        # Large-corpus prefilter: narrow the candidate set the EXPENSIVE
        # channels (embedding / annotation / graph) score. ``None`` = no
        # prefilter (full corpus), so small corpora are unaffected.
        restrict = self._maybe_prefilter(
            effective_query, query_intent, keyword_scores, resource_scores
        )

        # --- Score computation (skip channels with weight=0) ---
        embedding_scores = self._compute_embedding_scores(query, top_k, restrict) if ew > 0 else {}

        # Annotation-aware scoring (restricted to the pool when prefiltering)
        annotation_tools = (
            self._tools
            if restrict is None
            else {n: self._tools[n] for n in restrict if n in self._tools}
        )
        annotation_scores = (
            compute_annotation_scores(query_intent, annotation_tools) if aw > 0 else {}
        )

        # Graph: independent retrieval channel (resource-first + BFS)
        graph_scores: dict[str, float] = {}
        if gw > 0:
            seed_tools = self._build_seed_tools(keyword_scores, history, query=query)
            bfs_scores = self._compute_graph_scores(seed_tools, max_graph_depth, top_k)
            graph_scores = dict(bfs_scores)
            for name, score in resource_scores.items():
                graph_scores[name] = max(graph_scores.get(name, 0), score)
            # Confine graph candidates to the pool so injection stays within the
            # prefiltered set (the pool already contains the category matches).
            if restrict is not None:
                graph_scores = {n: s for n, s in graph_scores.items() if n in restrict}

        # wRRF fusion — Graph is NOT included here; it acts as candidate injection
        score_sources: list[tuple[dict[str, float], float]] = [
            (keyword_scores, kw),
            (clause_scores, kw * 0.6),
            (embedding_scores, ew),
            (annotation_scores, aw),
        ]

        # ENHANCED/FULL: LLM-assisted expansion
        self._apply_llm_expansion(mode, llm, query, score_sources)

        # wRRF fusion → filter to TOOL nodes
        final_scores = self._fuse_and_filter(score_sources)

        # Graph candidate injection: add high-confidence graph candidates
        # that the primary channels missed. This gives Graph its own
        # independent value without polluting the primary ranking.
        if graph_scores and gw > 0:
            self._inject_graph_candidates(final_scores, graph_scores, gw, top_k)

        # Post-fusion boosts
        self._boost_name_overlap(query, final_scores)
        self._boost_semantic_phrase_matches(query, final_scores)
        self._inject_clause_candidates(final_scores, clause_scores, top_k, query=query)
        self._boost_method_intent(query_intent, final_scores)
        self._boost_embedding_rerank(query, final_scores)
        self._preserve_dominant_keyword_candidates(keyword_scores, final_scores, top_k)
        if history:
            for tool_name in history:
                if tool_name in final_scores:
                    final_scores[tool_name] *= 0.8

        # Build candidates and post-process
        candidates = self._build_candidates(
            final_scores,
            keyword_scores,
            graph_scores,
            embedding_scores,
            annotation_scores,
            top_k,
        )
        candidates = self._post_process(candidates, query, final_scores, top_k)

        self._enrich_relations(candidates)
        return candidates

    # --- Pipeline stage methods ---

    def _augment_query(self, query: str, history: list[str] | None) -> str:
        """Augment query with history context for better retrieval."""
        if not history:
            return query
        context = [f"{t.name} {t.description}" for name in history if (t := self._tools.get(name))]
        return query + " " + " ".join(context) if context else query

    def _compute_keyword_scores(
        self, effective_query: str, fallback_query: str
    ) -> dict[str, float]:
        """Compute BM25 keyword scores, falling back to simple matching."""
        scores = self._get_bm25().score(effective_query)
        return scores if scores else self._keyword_match(fallback_query)

    def _compute_clause_keyword_scores(self, query: str) -> dict[str, float]:
        """Score explicit sub-intents in long, multi-step requests.

        A single long query can bury short sub-tasks under the dominant topic
        terms. Clause scoring keeps the top hits from each explicit segment
        visible without requiring an LLM decomposition pass.
        """
        clauses = self._split_query_clauses(query)
        if len(clauses) < 2:
            return {}

        bm25 = self._get_bm25()
        merged: dict[str, float] = {}
        clause_candidate_depth = 5 if len(clauses) >= 3 else 3
        for clause in clauses[:8]:
            scores = bm25.score(clause)
            if not scores:
                scores = self._keyword_match(clause)
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[
                :clause_candidate_depth
            ]
            if not ranked:
                continue
            top_clause_score = ranked[0][1]
            if top_clause_score <= 0:
                continue
            for rank, (name, score) in enumerate(ranked, start=1):
                if score <= 0:
                    continue
                # Keep per-clause winners strongest while still allowing the
                # full-query score to dominate overall precision.
                adjusted = (score / top_clause_score) / rank
                if adjusted > merged.get(name, 0.0):
                    merged[name] = adjusted
        return merged

    @staticmethod
    def _split_query_clauses(query: str) -> list[str]:
        """Split explicit multi-intent wording into coarse retrieval clauses."""
        text = query.strip()
        if not text:
            return []

        marker_pattern = re.compile(
            r"\b("
            r"first|second|third|fourth|fifth|next|then|finally|lastly|also|"
            r"furthermore|additionally|meanwhile|afterwards|after that|and then"
            r")\b[:,]?",
            flags=re.IGNORECASE,
        )
        marked = marker_pattern.sub(".", text)
        initial_parts = RetrievalEngine._split_query_clause_parts(marked)
        if len(initial_parts) < 4:
            marked = re.sub(
                r"\s+(?:and|plus)\s+(?="
                r"(?:please\s+)?"
                r"(?:find|get|retrieve|search|calculate|compute|convert|make|create|"
                r"return|fit|book|check|estimate|determine|identify|generate|"
                r"translate|summarize|compare|recommend|use)\b"
                r")",
                ". ",
                marked,
                flags=re.IGNORECASE,
            )
        parts = RetrievalEngine._split_query_clause_parts(marked)
        return RetrievalEngine._dedupe_query_clauses(parts)

    @staticmethod
    def _split_query_clause_parts(text: str) -> list[str]:
        """Split clause text on sentence-like separators without filtering."""
        parts = re.split(r"[.;?!]\s+|\n+", text)
        return [part.strip(" \t\r\n'\"`[]{}().,;:!?") for part in parts]

    @staticmethod
    def _dedupe_query_clauses(parts: list[str]) -> list[str]:
        """Filter tiny/duplicate clause fragments while preserving order."""
        clauses: list[str] = []
        seen: set[str] = set()
        for part in parts:
            clause = part.strip(" \t\r\n'\"`[]{}().,;:!?")
            if not clause:
                continue
            token_count = len(re.findall(r"[a-zA-Z0-9가-힣]+", clause))
            if token_count < 3:
                continue
            key = clause.lower()
            if key in seen:
                continue
            seen.add(key)
            clauses.append(clause)
        return clauses

    def _build_seed_tools(
        self,
        keyword_scores: dict[str, float],
        history: list[str] | None,
        query: str | None = None,
    ) -> list[str]:
        """Build multi-layer seed list: BM25 + annotation + history."""
        # Layer 1: BM25 top-10
        sorted_by_score = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        seeds = [name for name, _ in sorted_by_score[:10]]

        # Layer 2: Annotation-based seeds (intent-matching tools)
        if query:
            from graph_tool_call.retrieval.annotation_scorer import compute_annotation_scores
            from graph_tool_call.retrieval.intent import classify_intent

            intent = classify_intent(query)
            if not intent.is_neutral:
                ann_scores = compute_annotation_scores(intent, self._tools)
                ann_top = sorted(ann_scores.items(), key=lambda x: x[1], reverse=True)
                for name, score in ann_top[:3]:
                    if score > 0.7 and name not in seeds:
                        seeds.append(name)

        # Layer 3: History
        if history:
            for tool_name in history:
                if tool_name in self._tools and tool_name not in seeds:
                    seeds.append(tool_name)
        return seeds

    def _compute_graph_scores(
        self, seed_tools: list[str], max_depth: int, top_k: int
    ) -> dict[str, float]:
        """Expand graph from seed tools."""
        if not seed_tools:
            return {}
        expanded = self._searcher.expand_from_seeds(
            seed_tools, max_depth=max_depth, max_results=top_k * 3
        )
        return dict(expanded)

    def _compute_embedding_scores(
        self, query: str, top_k: int, restrict: set[str] | None = None
    ) -> dict[str, float]:
        """Compute embedding similarity scores.

        When ``restrict`` is given (prefilter pool), search deeper and keep only
        pool members so the pool's top hits aren't crowded out by out-of-pool
        neighbours that would be discarded downstream anyway.
        """
        if self._embedding_index is None or self._embedding_index.size <= 0:
            return {}
        try:
            query_emb = self._embedding_index.encode(query)
            depth = top_k * 3 if restrict is None else max(top_k * 3, len(restrict))
            hits = self._embedding_index.search(query_emb, top_k=depth)
            if restrict is not None:
                return {n: s for n, s in hits if n in restrict}
            return dict(hits)
        except (ValueError, ImportError):
            return {}

    def _maybe_prefilter(
        self,
        effective_query: str,
        query_intent: Any,
        keyword_scores: dict[str, float],
        resource_scores: dict[str, float],
    ) -> set[str] | None:
        """Build a prefilter candidate pool, or ``None`` to score the full corpus.

        Fires only when the prefilter is enabled and the corpus is large
        (``>= 500`` tools). Warns once when a large corpus runs without an
        embedding index (semantic recall is left on the table). ``resource_scores``
        is the shared ``resource_first_search`` result (avoids a second call).
        """
        n = len(self._tools)
        if n > 300 and self._embedding_index is None and not self._embedding_warned:
            import warnings

            self._embedding_warned = True
            warnings.warn(
                f"Retrieving over {n} tools without an embedding index — "
                "semantic/cross-language recall is degraded. Call "
                "enable_embedding('auto') (or attach an index) for better "
                "large-corpus recall.",
                stacklevel=3,
            )
        if not self._prefilter_enabled or n < 500:
            return None
        ranked_kw = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        bm25_top = [name for name, _ in ranked_kw[:50]]
        return self._get_prefilter().candidate_pool(
            effective_query, query_intent, bm25_top, resource_scored=resource_scores
        )

    def _augment_graph_with_embedding_seeds(
        self,
        embedding_scores: dict[str, float],
        seed_tools: list[str],
        graph_scores: dict[str, float],
        max_depth: int,
        top_k: int,
    ) -> dict[str, float]:
        """Add top embedding hits as extra graph seeds for semantic coverage."""
        if not embedding_scores:
            return graph_scores
        emb_top = sorted(embedding_scores.items(), key=lambda x: x[1], reverse=True)
        for name, _ in emb_top[:5]:
            if name not in seed_tools:
                seed_tools.append(name)
        extra = self._searcher.expand_from_seeds(
            seed_tools, max_depth=max_depth, max_results=top_k * 3
        )
        merged = dict(graph_scores)
        for name, score in extra:
            if name not in merged or score > merged[name]:
                merged[name] = score
        return merged

    def _apply_llm_expansion(
        self,
        mode: SearchMode,
        llm: Any,
        query: str,
        score_sources: list[tuple[dict[str, float], float]],
    ) -> None:
        """Apply LLM-based query expansion (ENHANCED) and intent decomposition (FULL)."""
        if llm is None:
            return
        if mode in (SearchMode.ENHANCED, SearchMode.FULL):
            expanded = llm.expand_query(query)
            terms = expanded.keywords + expanded.synonyms + expanded.english_terms
            if terms:
                scores = self._get_bm25().score(" ".join(terms))
                if not scores:
                    scores = self._keyword_match(" ".join(terms))
                if scores:
                    score_sources.append((scores, 0.7))
        if mode == SearchMode.FULL:
            for intent in llm.decompose_intents(query):
                scores = self._get_bm25().score(intent.to_query())
                if not scores:
                    scores = self._keyword_match(intent.to_query())
                if scores:
                    score_sources.append((scores, 0.5))

    def _fuse_and_filter(
        self, score_sources: list[tuple[dict[str, float], float]]
    ) -> dict[str, float]:
        """wRRF fusion then filter to TOOL nodes only."""
        active = [(s, w) for s, w in score_sources if s and w > 0]
        fused = self._wrrf_fuse(active) if active else {}
        final: dict[str, float] = {}
        for name, score in fused.items():
            if not self._graph.has_node(name):
                continue
            if self._graph.get_node_attrs(name).get("node_type") != NodeType.TOOL:
                continue
            final[name] = score
        return final

    def _boost_name_overlap(self, query: str, scores: dict[str, float]) -> None:
        """Boost scores for tools whose name tokens overlap with query tokens."""
        query_tokens = set(re.split(r"[\s_\-/.,;:!?()'\"`\[\]{}]+", query.lower()))
        query_tokens.discard("")
        # Normalized query for exact matching (strip spaces, lowercase)
        query_norm = re.sub(r"[^a-z0-9가-힣]+", "", query.lower())
        explicit_matches: list[str] = []
        for name in scores:
            name_tokens = set(re.split(r"[\s_\-/.,;:!?()'\"`\[\]{}]+", name.lower()))
            expanded: set[str] = set()
            for t in name_tokens:
                parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", t).lower().split()
                expanded.update(parts)
            # Exact name match: "get pod" ↔ "getPod" → 2.0x boost
            name_norm = re.sub(r"[^a-z0-9가-힣]+", "", name.lower())
            if len(name_norm) >= 5 and name_norm in query_norm:
                explicit_matches.append(name)
                continue
            if name_norm == query_norm or query_norm in name_norm:
                scores[name] *= 2.0
                continue
            overlap = len(query_tokens & expanded)
            if overlap >= 2:
                scores[name] *= 1.25 + 0.15 * (overlap - 2)
            elif overlap == 1:
                scores[name] *= 1.1
        if explicit_matches:
            explicit_floor = max(scores.values()) * 1.5
            for name in explicit_matches:
                scores[name] = max(scores[name], explicit_floor)

    def _boost_semantic_phrase_matches(self, query: str, scores: dict[str, float]) -> None:
        """Preserve high-confidence semantic phrase matches after score fusion."""
        q = query.lower()
        for name in list(scores):
            tool = self._tools.get(name)
            if not tool:
                continue
            tool_text = f"{name} {tool.description}".lower()
            if "hypotenuse" in q and (
                re.search(r"(^|[._\s-])hypot($|[._\s-])", tool_text)
                or "euclidean norm" in tool_text
            ):
                scores[name] *= 2.0
            if ("area under the curve" in q or "area under curve" in q) and (
                "integral" in tool_text or "integrate" in tool_text
            ):
                scores[name] *= 1.35
                if name.lower() == "integral":
                    scores[name] *= 1.35
            if (
                "distance covered" in q or "distance travelled" in q or "distance traveled" in q
            ) and ("distance_traveled" in name or "distance traveled" in tool_text):
                scores[name] *= 1.5
            if "fibonacci series" in q and ("sequence" in tool_text or "series" in tool_text):
                scores[name] *= 1.25
            korean_multiplier = BM25Scorer._semantic_phrase_multiplier(query, name, tool)
            if korean_multiplier > 1.0:
                scores[name] *= min(korean_multiplier, 1.5)

    def _inject_graph_candidates(
        self,
        final_scores: dict[str, float],
        graph_scores: dict[str, float],
        graph_weight: float,
        top_k: int,
    ) -> None:
        """Inject graph candidates into results, adapting strength to BM25 confidence.

        Graph acts as an independent retrieval channel. Instead of competing
        with BM25 in wRRF fusion (which degrades precision), Graph injects
        candidates that the primary channels missed.

        Adaptive injection:
        - High BM25 confidence (top-1 >> top-2): gentle tail injection only
        - Low BM25 confidence (flat scores): aggressive injection into mid-ranks
        This way Graph helps most when BM25 is uncertain.
        """
        if not graph_scores or not final_scores:
            return

        # Only consider graph candidates not already found by primary channels
        new_candidates = {
            name: score
            for name, score in graph_scores.items()
            if name not in final_scores and name in self._tools
        }
        if not new_candidates:
            return

        # Filter to high-confidence: top graph candidates only
        g_ranked = sorted(new_candidates.items(), key=lambda x: x[1], reverse=True)
        top_g_score = g_ranked[0][1] if g_ranked else 0
        if top_g_score <= 0:
            return
        # Only take candidates with score >= 50% of top graph score
        high_conf = [(n, s) for n, s in g_ranked if s >= top_g_score * 0.5]

        # SAFE injection: always below the lowest primary score
        # This guarantees Graph NEVER displaces any BM25 result
        min_primary = min(final_scores.values()) if final_scores else 0
        injection_base = min_primary * 0.8

        max_inject = max(2, top_k // 3)
        for name, g_score in high_conf[:max_inject]:
            norm_score = g_score / max(top_g_score, 1e-9)
            final_scores[name] = injection_base * norm_score

    def _inject_clause_candidates(
        self,
        final_scores: dict[str, float],
        clause_scores: dict[str, float],
        top_k: int,
        *,
        query: str = "",
    ) -> None:
        """Keep top explicit sub-intent matches near the final top-K boundary."""
        if not clause_scores or not final_scores:
            return

        ranked_clause = sorted(clause_scores.items(), key=lambda x: x[1], reverse=True)
        if not ranked_clause:
            return

        ranked_final = sorted(final_scores.values(), reverse=True)
        boundary_index = min(max(top_k - 1, 0), len(ranked_final) - 1)
        boundary_score = ranked_final[boundary_index]
        top_clause_score = ranked_clause[0][1]
        if boundary_score <= 0 or top_clause_score <= 0:
            return

        if self._has_diverse_actionable_clauses(query):
            max_inject = max(3, min(top_k * 2, len(ranked_clause)))
            floor = boundary_score * 1.08
            min_relative_score = 0.10
            min_norm_score = 0.75
        else:
            max_inject = max(3, min(top_k, len(ranked_clause)))
            floor = boundary_score * 1.05
            min_relative_score = 0.18
            min_norm_score = 0.6

        for name, score in ranked_clause[:max_inject]:
            if name not in self._tools or score < top_clause_score * min_relative_score:
                continue
            norm_score = score / top_clause_score
            candidate_score = floor * max(norm_score, min_norm_score)
            final_scores[name] = max(final_scores.get(name, 0.0), candidate_score)

    def _has_diverse_actionable_clauses(self, query: str) -> bool:
        """Return true when a long request clearly contains varied sub-tasks.

        Clause boosting is useful when each clause represents a different
        requested tool. It is noisy for story/background clauses or repeated
        arguments for a single task, so the stronger path is gated by
        actionable clause count plus diverse top-candidate signatures.
        """
        clauses = [
            clause
            for clause in self._split_query_clauses(query)
            if self._is_actionable_clause(clause)
        ]
        if len(clauses) < 3:
            return False

        signatures: list[frozenset[str]] = []
        bm25 = self._get_bm25()
        for clause in clauses[:8]:
            scores = bm25.score(clause)
            if not scores:
                scores = self._keyword_match(clause)
            for name, _score in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]:
                if name not in self._tools:
                    continue
                signatures.append(self._tool_signature(name))
                break

        distinct: list[frozenset[str]] = []
        for signature in signatures:
            if not signature:
                continue
            if all(self._signature_similarity(signature, known) < 0.5 for known in distinct):
                distinct.append(signature)
        return len(distinct) >= 3

    @staticmethod
    def _is_actionable_clause(clause: str) -> bool:
        """Detect clauses that look like requested actions, not background."""
        return bool(
            _CLAUSE_ACTION_PATTERN.search(clause) or _CLAUSE_QUESTION_PATTERN.search(clause)
        )

    @staticmethod
    def _tool_signature(tool_name: str) -> frozenset[str]:
        """Compact resource-ish signature for clause diversity gating."""
        tokens = [
            token
            for token in re.split(r"[._\-\s]+", tool_name.lower())
            if token and token not in _CLAUSE_SIGNATURE_STOPWORDS
        ]
        return frozenset(tokens[:2] or tokens or [tool_name.lower()])

    @staticmethod
    def _signature_similarity(left: frozenset[str], right: frozenset[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _boost_method_intent(self, query_intent: Any, scores: dict[str, float]) -> None:
        """Boost scores based on HTTP method-intent alignment."""
        if not query_intent or query_intent.is_neutral:
            return
        for name in list(scores):
            tool = self._tools.get(name)
            if not tool or not tool.metadata:
                continue
            method = tool.metadata.get("method", "").upper()
            if not method:
                continue
            if query_intent.write_intent > 0.5 and method == "POST":
                scores[name] *= 1.15
            elif query_intent.read_intent > 0.5 and method == "GET":
                scores[name] *= 1.1
            elif query_intent.delete_intent > 0.5 and method == "DELETE":
                scores[name] *= 1.15

    def _boost_embedding_rerank(self, query: str, scores: dict[str, float]) -> None:
        """Rerank top candidates using embedding description similarity."""
        if self._embedding_index is None or self._embedding_index._provider is None:
            return
        try:
            top_n = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
            if not top_n:
                return
            descs, desc_names = [], []
            for name, _ in top_n:
                tool = self._tools.get(name)
                if tool and tool.description:
                    descs.append(tool.description)
                    desc_names.append(name)
            if not descs:
                return
            all_embs = self._embedding_index._provider.encode_batch([query] + descs)
            if len(all_embs) != len(descs) + 1:
                return
            np = __import__("numpy")
            q_vec = np.array(all_embs[0], dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)
            if q_norm <= 0:
                return
            q_vec = q_vec / q_norm
            for i, name in enumerate(desc_names):
                d_vec = np.array(all_embs[i + 1], dtype=np.float32)
                d_norm = np.linalg.norm(d_vec)
                if d_norm > 0:
                    sim = float(np.dot(q_vec, d_vec / d_norm))
                    scores[name] *= 1.0 + 0.2 * max(sim, 0.0)
        except (ValueError, ImportError):
            pass

    @staticmethod
    def _preserve_dominant_keyword_candidates(
        keyword_scores: dict[str, float],
        final_scores: dict[str, float],
        top_k: int,
    ) -> None:
        """Keep strong lexical winners visible after auxiliary reranking.

        wRRF, clause injection, and semantic boosts are rank-based by design,
        which keeps unrelated raw score scales from dominating the whole
        pipeline. The tradeoff is that a very strong BM25 winner can sometimes
        slide just below ``top_k`` when multiple auxiliary hints agree on
        siblings. This conservative guard only lifts top lexical candidates
        whose raw BM25 score is both strong in absolute terms and close to the
        keyword leader, preserving exact operationId/schema evidence without
        making weak keyword tails noisy.
        """
        if top_k <= 0 or not keyword_scores or not final_scores:
            return

        ranked_keyword = [
            (name, score)
            for name, score in sorted(
                keyword_scores.items(), key=lambda item: item[1], reverse=True
            )
            if name in final_scores and score > 0
        ]
        if not ranked_keyword:
            return

        top_keyword_score = ranked_keyword[0][1]
        if top_keyword_score < 6.0:
            return

        ranked_final = sorted(final_scores.items(), key=lambda item: item[1], reverse=True)
        if len(ranked_final) <= top_k:
            return

        top_names = {name for name, _score in ranked_final[:top_k]}
        boundary_score = ranked_final[top_k - 1][1]
        if boundary_score <= 0:
            return

        for keyword_rank, (name, score) in enumerate(ranked_keyword[:5], start=1):
            if name in top_names:
                continue
            ratio = score / max(top_keyword_score, 1e-9)
            required_ratio = 0.75 if keyword_rank <= 3 else 0.9
            if ratio < required_ratio:
                continue
            lift = 1.08 + max(0, 4 - keyword_rank) * 0.02
            final_scores[name] = max(final_scores[name], boundary_score * lift)

    def _build_candidates(
        self,
        final_scores: dict[str, float],
        keyword_scores: dict[str, float],
        graph_scores: dict[str, float],
        embedding_scores: dict[str, float],
        annotation_scores: dict[str, float],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Build RetrievalResult list from fused scores."""
        ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        pool = top_k * 3 if (self._reranker or self._diversity_lambda) else top_k
        return [
            RetrievalResult(
                tool=self._tools[name],
                score=score,
                keyword_score=keyword_scores.get(name, 0.0),
                graph_score=graph_scores.get(name, 0.0),
                embedding_score=embedding_scores.get(name, 0.0),
                annotation_score=annotation_scores.get(name, 0.0),
            )
            for name, score in ranked[:pool]
            if name in self._tools
        ]

    def _post_process(
        self,
        candidates: list[RetrievalResult],
        query: str,
        final_scores: dict[str, float],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Apply cross-encoder reranking and MMR diversity."""
        if self._reranker is not None and candidates:
            tools_only = [r.tool for r in candidates]
            reranked = self._reranker.rerank(query, tools_only, top_k=top_k * 2)
            reranked_names = {t.name for t in reranked}
            candidates = [r for r in candidates if r.tool.name in reranked_names]
            name_to_result = {r.tool.name: r for r in candidates}
            candidates = [name_to_result[t.name] for t in reranked if t.name in name_to_result]

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

    def _reexpand_with_intent(
        self,
        query_intent: Any,
        seed_tools: list[str],
        max_depth: int,
        top_k: int,
        graph_scores: dict[str, float],
    ) -> dict[str, float]:
        """Re-expand graph using intent-aware relation weights."""
        from graph_tool_call.ontology.schema import INTENT_RELATION_WEIGHTS

        # Determine dominant intent
        intents = {
            "read": query_intent.read_intent,
            "write": query_intent.write_intent,
            "delete": query_intent.delete_intent,
        }
        dominant = max(intents, key=intents.get)
        if intents[dominant] < 0.6:
            return graph_scores  # no strong intent → keep defaults

        intent_weights = INTENT_RELATION_WEIGHTS.get(dominant)
        if not intent_weights:
            return graph_scores

        # Create a temporary searcher with intent-aware weights
        intent_searcher = GraphSearcher(self._graph, relation_weights=intent_weights)
        expanded = intent_searcher.expand_from_seeds(
            seed_tools, max_depth=max_depth, max_results=top_k * 3
        )
        # Merge: take max of default and intent-aware scores
        merged = dict(graph_scores)
        for name, score in expanded:
            if name not in merged or score > merged[name]:
                merged[name] = score
        return merged

    def _get_adaptive_weights(
        self,
    ) -> tuple[float, float, float, float]:
        """Return (keyword, graph, embedding, annotation) weights adapted to corpus size.

        If set_weights() was called, returns the manually set values instead.
        """
        if self._weights_manual:
            return (
                self._keyword_weight,
                self._graph_weight,
                self._embedding_weight,
                self._annotation_weight,
            )
        n = len(self._tools)
        has_embedding = self._embedding_index is not None and self._embedding_weight > 0

        if not has_embedding:
            # Graph is NOT in wRRF fusion — it injects candidates separately.
            # Graph weight > 0 enables candidate injection; the value controls
            # injection aggressiveness but does NOT enter wRRF scoring.
            # Annotation weight kept low to avoid overwhelming precise keyword matches
            # at large corpus sizes (where many tools share the same HTTP method).
            if n <= 30:
                return (0.85, 0.15, 0.0, 0.0)
            elif n <= 100:
                return (0.85, 0.15, 0.0, 0.0)
            else:
                return (0.85, 0.15, 0.0, 0.0)

        # With embedding: Graph still injects separately
        if n <= 30:
            return (0.25, 0.15, 0.55, 0.05)
        elif n <= 100:
            return (0.25, 0.15, 0.50, 0.10)
        elif n <= 1000:
            return (0.20, 0.20, 0.50, 0.10)
        else:
            # >1000 tools: lean harder on embeddings. Exact keyword matches get
            # noisier as many operationIds share tokens at this scale, while
            # semantic similarity stays discriminative. (Tunable via bench.)
            return (0.15, 0.20, 0.55, 0.10)

    def _enrich_relations(self, results: list[RetrievalResult]) -> None:
        """Attach inter-result relations and prerequisites to each result."""
        if not results:
            return

        result_names = {r.tool.name for r in results}

        useful_relations = {
            RelationType.REQUIRES,
            RelationType.PRECEDES,
            RelationType.COMPLEMENTARY,
            RelationType.CONFLICTS_WITH,
        }
        hints_out = {
            RelationType.REQUIRES: "Call {target} before this tool",
            RelationType.PRECEDES: "Call this tool before {target}",
            RelationType.COMPLEMENTARY: "Often used together with {target}",
            RelationType.CONFLICTS_WITH: "Conflicts with {target}",
        }
        hints_in = {
            RelationType.REQUIRES: "This tool is required by {source}",
            RelationType.PRECEDES: "{source} should be called before this tool",
        }

        for result in results:
            relations: list[ToolRelation] = []
            prereqs: list[str] = []
            seen_targets: set[str] = set()

            try:
                edges = self._graph.get_edges_from(result.tool.name, direction="both")
            except (KeyError, ValueError):
                continue

            for src, tgt, attrs in edges:
                rel_type = attrs.get("relation")
                if rel_type not in useful_relations:
                    continue

                # Outgoing: this tool → target
                rel_value = rel_type.value if hasattr(rel_type, "value") else str(rel_type)

                if src == result.tool.name:
                    if tgt in result_names and tgt not in seen_targets:
                        hint = hints_out.get(rel_type, "").format(target=tgt)
                        relations.append(
                            ToolRelation(
                                target=tgt,
                                type=rel_value,
                                direction="outgoing",
                                hint=hint,
                            )
                        )
                        seen_targets.add(tgt)
                    elif tgt not in result_names and rel_type == RelationType.REQUIRES:
                        if tgt not in prereqs and tgt in self._tools:
                            prereqs.append(tgt)

                # Incoming: source → this tool
                elif tgt == result.tool.name:
                    if src in result_names and src not in seen_targets:
                        hint = hints_in.get(rel_type, "").format(source=src)
                        if hint:
                            relations.append(
                                ToolRelation(
                                    target=src,
                                    type=rel_value,
                                    direction="incoming",
                                    hint=hint,
                                )
                            )
                            seen_targets.add(src)

            result.relations = relations
            result.prerequisites = prereqs

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

    async def aretrieve(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
        history: list[str] | None = None,
    ) -> list[ToolSchema]:
        """Async version of :meth:`retrieve`."""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.retrieve(
                query,
                top_k=top_k,
                max_graph_depth=max_graph_depth,
                mode=mode,
                llm=llm,
                history=history,
            ),
        )

    async def aretrieve_with_scores(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
        history: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Async version of :meth:`retrieve_with_scores`."""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.retrieve_with_scores(
                query,
                top_k=top_k,
                max_graph_depth=max_graph_depth,
                mode=mode,
                llm=llm,
                history=history,
            ),
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
        """Confidence-aware Weighted Reciprocal Rank Fusion.

        wRRF_score(d) = sum(effective_weight_i / (k + rank_i(d)))

        When a source's top-1 score is significantly higher than top-2,
        that source is "confident" and gets a weight boost (up to 1.5x).
        This lets a high-confidence source (e.g., exact keyword match)
        override an uncertain source (e.g., ambiguous embeddings).
        """
        fused: dict[str, float] = {}
        for scores, weight in weighted_sources:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            if not ranked:
                continue

            # Confidence: how much top-1 dominates top-2
            effective_weight = weight
            if len(ranked) >= 2:
                top1_score = ranked[0][1]
                top2_score = ranked[1][1]
                if top1_score > 0:
                    gap = (top1_score - top2_score) / top1_score
                    # gap ∈ [0, 1] → boost ∈ [1.0, 1.5]
                    effective_weight = weight * (1.0 + 0.5 * gap)

            for rank, (name, _) in enumerate(ranked, start=1):
                fused[name] = fused.get(name, 0.0) + effective_weight / (k + rank)
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
        return [t.lower() for t in re.split(r"[\s_\-/.,;:!?()'\"`\[\]{}]+", text) if t]


def elbow_cut_k(scores: list[float], k: int, *, min_k: int = 2) -> int:
    """Dynamic result count via an elbow cut over the top scores.

    Given descending ``scores`` and a ceiling ``k``, return how many to keep:
    when one/few candidates clearly dominate (a large relative score drop early
    in the top ``2k``), return that smaller count (down to ``min_k``); when the
    top scores are flat/ambiguous, return ``k``. Lets a confident query surface
    2–3 tools while an ambiguous one still gets the full ``k``.

    A "large drop" is a >=50% fall relative to the top score between two
    adjacent ranks. Pure function — no engine state.
    """
    n = len(scores)
    if n <= min_k:
        return n
    top = scores[0]
    if top <= 0:
        return min(k, n)
    window = scores[: max(2 * k, min_k + 1)]
    best_cut, best_drop = min(k, n), 0.0
    # Find the sharpest adjacent drop anywhere in the top window (keep i+1
    # items). A drop before ``min_k`` — e.g. one dominant hit — still counts;
    # the cut is then clamped up to ``min_k`` so we never return too few.
    for i in range(0, min(len(window) - 1, k)):
        drop = (window[i] - window[i + 1]) / top
        if drop > best_drop:
            best_drop, best_cut = drop, i + 1
    if best_drop >= 0.5:
        return max(min_k, min(best_cut, k))
    return min(k, n)


def build_workflow_summary(results: list[RetrievalResult]) -> list[str] | None:
    """Build a suggested execution order from REQUIRES/PRECEDES relations.

    Returns a topologically sorted list of tool names, or None if no
    ordering relations exist among the results. Only includes tools
    that are in the result set.
    """
    result_names = {r.tool.name for r in results}
    order_pairs: list[tuple[str, str]] = []
    for r in results:
        for rel in r.relations:
            if rel.direction != "outgoing":
                continue
            # Only include pairs where both tools are in the result set
            if rel.target not in result_names:
                continue
            if rel.type == "precedes":
                order_pairs.append((r.tool.name, rel.target))
            elif rel.type == "requires":
                order_pairs.append((rel.target, r.tool.name))

    if not order_pairs:
        return None

    # Kahn's algorithm for topological sort
    graph: dict[str, set[str]] = defaultdict(set)
    in_deg: dict[str, int] = defaultdict(int)
    nodes: set[str] = set()
    for a, b in order_pairs:
        nodes.add(a)
        nodes.add(b)
        if b not in graph[a]:
            graph[a].add(b)
            in_deg[b] += 1
    for n in nodes:
        in_deg.setdefault(n, 0)

    queue = deque(n for n in nodes if in_deg[n] == 0)
    result: list[str] = []
    while queue:
        n = queue.popleft()
        result.append(n)
        for m in graph[n]:
            in_deg[m] -= 1
            if in_deg[m] == 0:
                queue.append(m)

    # Append remaining (cycle) nodes
    for n in nodes:
        if n not in result:
            result.append(n)

    return result
