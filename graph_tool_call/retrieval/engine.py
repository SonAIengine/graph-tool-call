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

        effective_query = self._augment_query(query, history)

        # --- Score computation ---
        keyword_scores = self._compute_keyword_scores(effective_query, query)
        seed_tools = self._build_seed_tools(keyword_scores, history, query=query)
        graph_scores = self._compute_graph_scores(seed_tools, max_graph_depth, top_k)
        embedding_scores = self._compute_embedding_scores(query, top_k)

        # Re-expand graph with embedding seeds
        graph_scores = self._augment_graph_with_embedding_seeds(
            embedding_scores, seed_tools, graph_scores, max_graph_depth, top_k
        )

        # Annotation-aware scoring
        from graph_tool_call.retrieval.annotation_scorer import compute_annotation_scores
        from graph_tool_call.retrieval.intent import classify_intent

        query_intent = classify_intent(query)

        # Re-expand graph with intent-aware weights if intent is clear
        if query_intent and not query_intent.is_neutral:
            graph_scores = self._reexpand_with_intent(
                query_intent, seed_tools, max_graph_depth, top_k, graph_scores
            )

        annotation_scores = compute_annotation_scores(query_intent, self._tools)

        # Dynamic wRRF weights based on corpus size
        kw, gw, ew, aw = self._get_adaptive_weights()

        # Collect all score sources for wRRF
        score_sources: list[tuple[dict[str, float], float]] = [
            (keyword_scores, kw),
            (graph_scores, gw),
            (embedding_scores, ew),
            (annotation_scores, aw),
        ]

        # ENHANCED/FULL: LLM-assisted expansion
        self._apply_llm_expansion(mode, llm, query, score_sources)

        # wRRF fusion → filter to TOOL nodes
        final_scores = self._fuse_and_filter(score_sources)

        # Post-fusion boosts
        self._boost_name_overlap(query, final_scores)
        self._boost_method_intent(query_intent, final_scores)
        self._boost_embedding_rerank(query, final_scores)
        if history:
            for tool_name in history:
                if tool_name in final_scores:
                    final_scores[tool_name] *= 0.8

        # Build candidates and post-process
        candidates = self._build_candidates(
            final_scores, keyword_scores, graph_scores, embedding_scores, annotation_scores, top_k
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

    def _compute_embedding_scores(self, query: str, top_k: int) -> dict[str, float]:
        """Compute embedding similarity scores."""
        if self._embedding_index is None or self._embedding_index.size <= 0:
            return {}
        try:
            query_emb = self._embedding_index.encode(query)
            return dict(self._embedding_index.search(query_emb, top_k=top_k * 3))
        except (ValueError, ImportError):
            return {}

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
        active = [(s, w) for s, w in score_sources if s]
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
        query_tokens = set(re.split(r"[\s_\-/.,;:!?()]+", query.lower()))
        query_tokens.discard("")
        # Normalized query for exact matching (strip spaces, lowercase)
        query_norm = re.sub(r"[\s_\-]+", "", query.lower())
        for name in scores:
            name_tokens = set(re.split(r"[\s_\-/.,;:!?()]+", name.lower()))
            expanded: set[str] = set()
            for t in name_tokens:
                parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", t).lower().split()
                expanded.update(parts)
            # Exact name match: "get pod" ↔ "getPod" → 2.0x boost
            name_norm = re.sub(r"[\s_\-]+", "", name.lower())
            if name_norm == query_norm or query_norm in name_norm:
                scores[name] *= 2.0
                continue
            overlap = len(query_tokens & expanded)
            if overlap >= 2:
                scores[name] *= 1.25 + 0.15 * (overlap - 2)
            elif overlap == 1:
                scores[name] *= 1.1

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
        """Return (keyword, graph, embedding, annotation) weights adapted to corpus size."""
        n = len(self._tools)
        has_embedding = self._embedding_index is not None and self._embedding_weight > 0

        if not has_embedding:
            return (self._keyword_weight, self._graph_weight, 0.0, self._annotation_weight)

        # Dynamic adjustment based on corpus size
        if n <= 30:
            return (0.25, 0.20, 0.45, 0.10)
        elif n <= 100:
            return (0.25, 0.25, 0.35, 0.15)
        else:
            return (0.20, 0.25, 0.35, 0.20)

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
        return [t.lower() for t in re.split(r"[\s_\-/.,;:!?()]+", text) if t]


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
