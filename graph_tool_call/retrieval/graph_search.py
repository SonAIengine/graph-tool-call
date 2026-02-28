"""Graph-based search strategies for tool retrieval."""

from __future__ import annotations

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

                # Distance decay
                decay = 1.0 / (depth + 1)

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
