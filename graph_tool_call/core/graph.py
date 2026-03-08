"""NetworkX-based GraphEngine implementation."""

from __future__ import annotations

from collections import deque
from typing import Any

import networkx as nx


class NetworkXGraph:
    """GraphEngine backed by NetworkX DiGraph."""

    def __init__(self, graph: nx.DiGraph | None = None) -> None:
        self._g: nx.DiGraph = graph if graph is not None else nx.DiGraph()

    # --- nodes ---

    def add_node(self, node_id: str, **attrs: Any) -> None:
        self._g.add_node(node_id, **attrs)

    def remove_node(self, node_id: str) -> None:
        self._g.remove_node(node_id)

    def has_node(self, node_id: str) -> bool:
        return self._g.has_node(node_id)

    def get_node_attrs(self, node_id: str) -> dict[str, Any]:
        return dict(self._g.nodes[node_id])

    def set_node_attrs(self, node_id: str, **attrs: Any) -> None:
        self._g.nodes[node_id].update(attrs)

    def nodes(self) -> list[str]:
        return list(self._g.nodes)

    # --- edges ---

    def add_edge(self, source: str, target: str, **attrs: Any) -> None:
        self._g.add_edge(source, target, **attrs)

    def remove_edge(self, source: str, target: str) -> None:
        self._g.remove_edge(source, target)

    def has_edge(self, source: str, target: str) -> bool:
        return self._g.has_edge(source, target)

    def get_edge_attrs(self, source: str, target: str) -> dict[str, Any]:
        return dict(self._g.edges[source, target])

    def edges(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [(u, v, dict(d)) for u, v, d in self._g.edges(data=True)]

    # --- traversal ---

    def get_neighbors(self, node_id: str, direction: str = "both") -> list[str]:
        result: set[str] = set()
        if direction in ("out", "both"):
            result.update(self._g.successors(node_id))
        if direction in ("in", "both"):
            result.update(self._g.predecessors(node_id))
        return list(result)

    def get_edges_from(
        self, node_id: str, direction: str = "both"
    ) -> list[tuple[str, str, dict[str, Any]]]:
        result: list[tuple[str, str, dict[str, Any]]] = []
        if direction in ("out", "both"):
            for _, v, d in self._g.out_edges(node_id, data=True):
                result.append((node_id, v, dict(d)))
        if direction in ("in", "both"):
            for u, _, d in self._g.in_edges(node_id, data=True):
                result.append((u, node_id, dict(d)))
        return result

    def subgraph(self, node_ids: list[str]) -> NetworkXGraph:
        sg = self._g.subgraph(node_ids).copy()
        return NetworkXGraph(sg)

    def bfs(self, start: str, max_depth: int = 2) -> list[str]:
        if not self._g.has_node(start):
            return []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        result: list[str] = []

        while queue:
            node, depth = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            result.append(node)
            if depth < max_depth:
                for neighbor in self.get_neighbors(node, direction="both"):
                    if neighbor not in visited:
                        queue.append((neighbor, depth + 1))
        return result

    # --- stats ---

    def node_count(self) -> int:
        return self._g.number_of_nodes()

    def edge_count(self) -> int:
        return self._g.number_of_edges()

    # --- serialization ---

    def to_dict(self) -> dict[str, Any]:
        nodes = []
        for nid in self._g.nodes:
            attrs = dict(self._g.nodes[nid])
            nodes.append({"id": nid, **attrs})
        edges = []
        for u, v, d in self._g.edges(data=True):
            edges.append({"source": u, "target": v, **d})
        return {"nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkXGraph:
        g = nx.DiGraph()
        for node in data.get("nodes", []):
            nid = node["id"]
            attrs = {k: v for k, v in node.items() if k != "id"}
            g.add_node(nid, **attrs)
        for edge in data.get("edges", []):
            src = edge["source"]
            tgt = edge["target"]
            attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
            g.add_edge(src, tgt, **attrs)
        return cls(g)
