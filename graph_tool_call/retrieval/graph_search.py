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

        Maps both original and stemmed forms so that "pets" matches category "pet"
        and "issues" matches category "issue".
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

        # Step 1: Find matching categories (try both original and stemmed tokens)
        matched_categories: dict[str, float] = {}
        for token in query_tokens:
            for variant in (token, self._stem_simple(token)):
                if variant in cat_index:
                    cat_node = cat_index[variant]
                    matched_categories[cat_node] = matched_categories.get(cat_node, 0) + 1.0
                    break

        # Also check multi-word matches ("pull request" → "pulls")
        _RESOURCE_ALIASES: dict[str, str] = {
            "pull request": "pulls",
            "pr": "pulls",
            "issue": "issues",
            "repo": "repos",
            "repository": "repos",
            "workflow": "actions",
            "action": "actions",
            "gist": "gists",
            "user": "users",
            "team": "teams",
            "org": "orgs",
            "organization": "orgs",
            "package": "packages",
            "project": "projects",
            "release": "repos",
            "branch": "repos",
            "commit": "repos",
            "webhook": "repos",
            "codespace": "codespaces",
            "copilot": "copilot",
            "dependabot": "dependabot",
            "secret": "actions",
            "runner": "actions",
            "deploy": "repos",
            "migration": "migrations",
            "ssh key": "users",
            "gpg key": "users",
            "label": "issues",
            "milestone": "issues",
            "comment": "issues",
            "review": "pulls",
            "check": "checks",
            "star": "activity",
            "watch": "activity",
            "fork": "repos",
            "tag": "repos",
            "scan": "code-scanning",
            "alert": "dependabot",
            "billing": "billing",
        }
        for alias, cat_name in _RESOURCE_ALIASES.items():
            if alias in query_lower:
                if self._graph.has_node(cat_name):
                    matched_categories[cat_name] = matched_categories.get(cat_name, 0) + 1.5

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
                intent_boost = 1.0
                if intent and not intent.is_neutral and tools:
                    tool_obj = tools.get(tool_node)
                    if tool_obj and tool_obj.metadata:
                        method = tool_obj.metadata.get("method", "").upper()
                        # Also check tool name for action verbs
                        name_lower = tool_node.lower()
                        if intent.write_intent > 0.5:
                            if method in ("POST", "PUT", "PATCH"):
                                intent_boost = 1.8
                            # Specific verb matching in tool name
                            for verb in ("create", "add", "set", "update", "enable",
                                         "register", "upload", "submit", "request",
                                         "fork", "star", "follow", "lock", "merge",
                                         "close", "open", "transfer", "approve"):
                                if verb in name_lower:
                                    intent_boost = max(intent_boost, 1.5)
                        elif intent.read_intent > 0.5:
                            if method == "GET":
                                intent_boost = 1.5
                            for verb in ("get", "list", "check", "download", "search"):
                                if verb in name_lower:
                                    intent_boost = max(intent_boost, 1.3)
                        elif intent.delete_intent > 0.5:
                            if method == "DELETE":
                                intent_boost = 1.8
                            for verb in ("delete", "remove", "revoke", "cancel"):
                                if verb in name_lower:
                                    intent_boost = max(intent_boost, 1.5)

                # Description keyword boost: check if query keywords appear in description
                desc_boost = 1.0
                if tools:
                    tool_obj = tools.get(tool_node)
                    if tool_obj and tool_obj.description:
                        desc_lower = tool_obj.description.lower()
                        desc_hits = sum(1 for t in query_tokens if t in desc_lower)
                        if desc_hits >= 2:
                            desc_boost = 1.0 + 0.3 * desc_hits

                score = base * name_boost * intent_boost * desc_boost
                scores[tool_node] = max(scores.get(tool_node, 0), score)

        # Sort and limit
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return dict(ranked[:max_results])

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
