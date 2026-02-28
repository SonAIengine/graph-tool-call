"""Unified retrieval engine: graph traversal + optional embedding hybrid search."""

from __future__ import annotations

import re
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType
from graph_tool_call.retrieval.graph_search import GraphSearcher


class RetrievalEngine:
    """Combines keyword matching, graph traversal, and optional embedding for tool retrieval."""

    def __init__(
        self,
        graph: GraphEngine,
        tools: dict[str, ToolSchema],
        graph_weight: float = 0.7,
        keyword_weight: float = 0.3,
        embedding_weight: float = 0.0,
    ) -> None:
        self._graph = graph
        self._tools = tools
        self._searcher = GraphSearcher(graph)
        self._graph_weight = graph_weight
        self._keyword_weight = keyword_weight
        self._embedding_weight = embedding_weight
        self._embedding_index: Any = None

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
    ) -> list[ToolSchema]:
        """Retrieve the most relevant tools for a query.

        Steps:
        1. Keyword matching → seed tools
        2. Graph expansion from seeds
        3. Optional embedding similarity
        4. Score fusion → top-k
        """
        # Step 1: keyword-based seed selection
        keyword_scores = self._keyword_match(query)

        # Step 2: pick top seed tools and expand via graph
        seed_tools = [name for name, _ in sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)[:5]]
        graph_scores: dict[str, float] = {}
        if seed_tools:
            expanded = self._searcher.expand_from_seeds(
                seed_tools, max_depth=max_graph_depth, max_results=top_k * 3
            )
            graph_scores = dict(expanded)

        # Step 3: optional embedding scores
        embedding_scores: dict[str, float] = {}
        # (Phase 2: will integrate embedding_index.search here)

        # Step 4: fuse scores
        all_tools = set(keyword_scores) | set(graph_scores) | set(embedding_scores)
        final_scores: list[tuple[str, float]] = []

        for name in all_tools:
            # Only include tool nodes
            if not self._graph.has_node(name):
                continue
            attrs = self._graph.get_node_attrs(name)
            if attrs.get("node_type") != NodeType.TOOL:
                continue

            score = (
                self._keyword_weight * keyword_scores.get(name, 0.0)
                + self._graph_weight * graph_scores.get(name, 0.0)
                + self._embedding_weight * embedding_scores.get(name, 0.0)
            )
            final_scores.append((name, score))

        final_scores.sort(key=lambda x: x[1], reverse=True)

        result: list[ToolSchema] = []
        for name, _ in final_scores[:top_k]:
            if name in self._tools:
                result.append(self._tools[name])
        return result

    def _keyword_match(self, query: str) -> dict[str, float]:
        """Simple keyword overlap scoring between query and tool name/description."""
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return {}

        scores: dict[str, float] = {}
        for name, tool in self._tools.items():
            tool_tokens = set(self._tokenize(tool.name)) | set(self._tokenize(tool.description))
            tool_tokens.update(self._tokenize(t) for t in tool.tags)

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
