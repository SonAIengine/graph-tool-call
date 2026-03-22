"""Graph-based search strategies for tool retrieval."""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.ontology.schema import DEFAULT_RELATION_WEIGHTS, NodeType, RelationType


class GraphSearcher:
    """Traverses the ontology graph to find relevant tools."""

    def __init__(
        self,
        graph: GraphEngine,
        relation_weights: dict[str, float] | None = None,
    ) -> None:
        self._graph = graph
        self._weights = relation_weights or DEFAULT_RELATION_WEIGHTS
        self._category_index: dict[str, str] | None = None

    @staticmethod
    def _stem_simple(word: str) -> str:
        """Minimal stemming for category matching (plural → singular)."""
        if len(word) <= 3:
            return word
        if word.endswith("ies") and len(word) > 4:
            return word[:-3] + "y"
        if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word

    def _get_category_index(self) -> dict[str, str]:
        """Build token → category_node mapping for resource-first search.

        Dynamically indexes all CATEGORY nodes in the graph, mapping their
        name tokens, stemmed forms, and description keywords. This is fully
        generic — works with any OpenAPI/MCP schema, not just specific APIs.
        """
        if self._category_index is not None:
            return self._category_index

        index: dict[str, str] = {}
        for node in self._graph.nodes():
            attrs = self._graph.get_node_attrs(node)
            if attrs.get("node_type") != NodeType.CATEGORY:
                continue
            # Tokenize category name and map each token + stemmed form
            tokens = re.split(r"[\s_\-/.,;:!?()]+", node.lower())
            for t in tokens:
                if t and len(t) >= 2:
                    index[t] = node
                    # Also map plural/singular variants
                    stemmed = self._stem_simple(t)
                    if stemmed != t:
                        index[stemmed] = node
                    # Add plural if category is singular
                    if not t.endswith("s"):
                        index[t + "s"] = node
            # Also map the full name
            index[node.lower()] = node

            # Index description keywords for broader matching
            desc = attrs.get("description", "")
            if desc:
                desc_tokens = re.split(r"[\s_\-/.,;:!?()]+", desc.lower())
                for t in desc_tokens:
                    if t and len(t) >= 3 and t not in index:
                        index[t] = node

            # Reverse-index: tool name + description tokens → their parent category
            # e.g., "refund" from requestRefund → orders category
            #        "starred" from listStargazers desc → activity category
            for neighbor in self._graph.get_neighbors(node, direction="in"):
                n_attrs = self._graph.get_node_attrs(neighbor)
                if n_attrs.get("node_type") != NodeType.TOOL:
                    continue
                # Split camelCase and snake_case tool names
                name_parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", neighbor)
                name_tokens = re.split(r"[\s_\-/]+", name_parts.lower())
                for t in name_tokens:
                    t = self._stem_simple(t)
                    if t and len(t) >= 3 and t not in index:
                        index[t] = node
                # Also index distinctive description keywords
                tool_desc = n_attrs.get("description", "")
                if tool_desc:
                    desc_toks = re.split(r"[\s_\-/.,;:!?()]+", tool_desc.lower())
                    for t in desc_toks:
                        t = self._stem_simple(t)
                        if t and len(t) >= 4 and t not in index:
                            index[t] = node

        self._category_index = index
        return index

    def resource_first_search(
        self,
        query: str,
        intent: Any | None = None,
        max_results: int = 15,
        tools: dict | None = None,
    ) -> dict[str, float]:
        """Resource-first graph search: find tools by matching query to graph categories.

        Unlike expand_from_seeds (which starts from BM25 results), this method
        directly matches query tokens to CATEGORY nodes in the graph, then scores
        all tools in those categories. This provides an independent retrieval signal
        that can find tools BM25 misses (e.g., "close issue" → issues/update).

        Scoring:
        - Category match: base score from token overlap ratio
        - Intent alignment: tools whose HTTP method matches query intent get boosted
        - Name relevance: tools whose name contains query tokens get boosted
        """
        cat_index = self._get_category_index()
        query_lower = query.lower()
        query_tokens = set(re.split(r"[\s_\-/.,;:!?()]+", query_lower))
        query_tokens -= {"a", "an", "the", "of", "for", "to", "in", "by", "is", "and", "or", "my",
                         "all", "this", "that", "with", "from"}
        query_tokens.discard("")

        if not query_tokens:
            return {}

        # Step 1: Find matching categories (try multiple token variants)
        matched_categories: dict[str, float] = {}
        for token in query_tokens:
            # Try: original, stemmed, and common suffixes stripped
            variants = [token, self._stem_simple(token)]
            # Handle -ed, -ing, -er suffixes more aggressively
            if token.endswith("ed") and len(token) > 4:
                variants.append(token[:-2])  # starred → starr
                variants.append(token[:-1])  # starred → starre
                variants.append(token[:-2] + token[-3])  # doubled consonant
            if token.endswith("ing") and len(token) > 5:
                variants.append(token[:-3])
            if token.endswith("er") and len(token) > 4:
                variants.append(token[:-2])
                variants.append(token[:-1])
            for variant in variants:
                if variant in cat_index:
                    cat_node = cat_index[variant]
                    matched_categories[cat_node] = matched_categories.get(cat_node, 0) + 1.0
                    break

        if not matched_categories:
            return {}

        # Step 2: Get tools from matched categories, scored by relevance
        scores: dict[str, float] = {}
        for cat_node, cat_score in matched_categories.items():
            cat_tools = self._graph.get_neighbors(cat_node, direction="in")
            for tool_node in cat_tools:
                t_attrs = self._graph.get_node_attrs(tool_node)
                if t_attrs.get("node_type") != NodeType.TOOL:
                    continue

                # Base score from category match strength
                base = cat_score / max(len(matched_categories), 1)

                # Name token overlap boost: tools whose name matches query tokens
                name_tokens = set(re.split(r"[\s_\-/.,;:!?()]+", tool_node.lower()))
                name_overlap = len(query_tokens & name_tokens)
                name_boost = 1.0 + 0.5 * name_overlap

                # Intent alignment: check HTTP method from tool metadata
                intent_boost = self._compute_intent_boost(intent, tool_node, tools)

                # Description keyword boost
                desc_boost = self._compute_desc_boost(query_tokens, tool_node, tools)

                score = base * name_boost * intent_boost * desc_boost
                scores[tool_node] = max(scores.get(tool_node, 0), score)

        # Step 3: Chain expansion — follow REQUIRES/PRECEDES for top-scored tools
        chain_additions = self._expand_chains(scores, max_chain_depth=2)
        for name, score in chain_additions.items():
            scores[name] = max(scores.get(name, 0), score)

        # Sort and limit
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return dict(ranked[:max_results])

    @staticmethod
    def _compute_intent_boost(
        intent: Any | None, tool_node: str, tools: dict | None
    ) -> float:
        """Score boost based on query intent vs tool's HTTP method/name."""
        if not intent or intent.is_neutral or not tools:
            return 1.0

        tool_obj = tools.get(tool_node)
        method = ""
        if tool_obj and tool_obj.metadata:
            method = tool_obj.metadata.get("method", "").upper()

        name_lower = tool_node.lower()
        boost = 1.0

        if intent.write_intent > 0.5:
            if method in ("POST", "PUT", "PATCH"):
                boost = 1.8
            for verb in ("create", "add", "set", "update", "enable",
                         "register", "upload", "submit", "request",
                         "fork", "star", "follow", "lock", "merge",
                         "close", "open", "transfer", "approve",
                         "checkout", "cancel", "clear"):
                if verb in name_lower:
                    boost = max(boost, 1.5)
        elif intent.read_intent > 0.5:
            if method == "GET":
                boost = 1.5
            for verb in ("get", "list", "check", "download", "search",
                         "validate", "calculate"):
                if verb in name_lower:
                    boost = max(boost, 1.3)
        elif intent.delete_intent > 0.5:
            if method == "DELETE":
                boost = 1.8
            for verb in ("delete", "remove", "revoke", "cancel"):
                if verb in name_lower:
                    boost = max(boost, 1.5)

        return boost

    @staticmethod
    def _compute_desc_boost(
        query_tokens: set[str], tool_node: str, tools: dict | None
    ) -> float:
        """Boost tools whose description contains query keywords."""
        if not tools:
            return 1.0
        tool_obj = tools.get(tool_node)
        if not tool_obj or not tool_obj.description:
            return 1.0
        desc_lower = tool_obj.description.lower()
        desc_hits = sum(1 for t in query_tokens if t in desc_lower)
        if desc_hits >= 2:
            return 1.0 + 0.3 * desc_hits
        return 1.0

    def _expand_chains(
        self,
        scores: dict[str, float],
        max_chain_depth: int = 2,
    ) -> dict[str, float]:
        """Follow REQUIRES/PRECEDES edges from top-scored tools to find chain members.

        When a user queries "process a refund", we find requestRefund via category
        matching. This method then follows REQUIRES edges to discover getOrder
        (prerequisite) and PRECEDES edges to discover getPayment (next step).

        Chain tools get a decayed score so they rank below the primary match
        but above unrelated tools.
        """
        if not scores:
            return {}

        # Only expand from top-scored tools to avoid noise
        top_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
        chain_scores: dict[str, float] = {}

        for tool_name, base_score in top_tools:
            if not self._graph.has_node(tool_name):
                continue

            # BFS through REQUIRES/PRECEDES only
            visited: set[str] = {tool_name}
            queue: deque[tuple[str, int]] = deque([(tool_name, 0)])

            while queue:
                node, depth = queue.popleft()
                if depth >= max_chain_depth:
                    continue

                for edge in self._graph.get_edges_from(node, direction="both"):
                    src, tgt, attrs = edge
                    neighbor = tgt if src == node else src
                    relation = str(attrs.get("relation", ""))

                    # Only follow workflow edges
                    if "REQUIRES" not in relation and "PRECEDES" not in relation:
                        continue

                    if neighbor in visited:
                        continue
                    visited.add(neighbor)

                    n_attrs = self._graph.get_node_attrs(neighbor)
                    if n_attrs.get("node_type") != NodeType.TOOL:
                        continue

                    # Decayed score: prerequisites get 60% at depth 1, 36% at depth 2
                    decay = 0.6 ** (depth + 1)
                    chain_score = base_score * decay
                    chain_scores[neighbor] = max(
                        chain_scores.get(neighbor, 0), chain_score
                    )
                    queue.append((neighbor, depth + 1))

        return chain_scores

    def expand_from_seeds(
        self,
        seed_tools: list[str],
        max_depth: int = 2,
        max_results: int = 20,
    ) -> list[tuple[str, float]]:
        """BFS expansion from seed tools, scoring by relation type and distance.

        Returns (tool_name, score) pairs sorted by score descending.
        """
        scores: dict[str, float] = {}

        # Seeds get highest score
        for seed in seed_tools:
            if self._graph.has_node(seed):
                scores[seed] = 1.0

        # BFS expansion
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        for seed in seed_tools:
            if self._graph.has_node(seed):
                queue.append((seed, 0))

        while queue:
            node, depth = queue.popleft()
            if node in visited:
                continue
            visited.add(node)

            if depth >= max_depth:
                continue

            for edge in self._graph.get_edges_from(node, direction="both"):
                src, tgt, attrs = edge
                neighbor = tgt if src == node else src

                if neighbor in visited:
                    continue

                neighbor_attrs = self._graph.get_node_attrs(neighbor)
                neighbor_type = neighbor_attrs.get("node_type")

                relation = attrs.get("relation", "")
                rel_weight = self._weights.get(relation, 0.3)

                # Distance decay — gentler curve to let depth-1/2 neighbors contribute
                decay = 1.0 / (0.5 * depth + 1)

                if neighbor_type == NodeType.TOOL:
                    score = rel_weight * decay
                    scores[neighbor] = max(scores.get(neighbor, 0), score)
                    queue.append((neighbor, depth + 1))
                elif neighbor_type in (NodeType.CATEGORY, NodeType.DOMAIN):
                    # Traverse through category/domain to find sibling tools
                    queue.append((neighbor, depth + 1))

        # Sort by score descending, filter to top_k
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:max_results]

    def get_category_siblings(self, tool_name: str) -> list[str]:
        """Get all tools in the same category as the given tool."""
        siblings: set[str] = set()
        for _, tgt, attrs in self._graph.get_edges_from(tool_name, direction="out"):
            if attrs.get("relation") != RelationType.BELONGS_TO:
                continue
            tgt_attrs = self._graph.get_node_attrs(tgt)
            if tgt_attrs.get("node_type") != NodeType.CATEGORY:
                continue
            # Find all tools in this category
            for neighbor in self._graph.get_neighbors(tgt, direction="in"):
                n_attrs = self._graph.get_node_attrs(neighbor)
                if n_attrs.get("node_type") == NodeType.TOOL and neighbor != tool_name:
                    siblings.add(neighbor)
        return list(siblings)
