"""Lightweight dict-based GraphEngine — zero external dependencies."""

from __future__ import annotations

from collections import deque
from typing import Any


class DictGraph:
    """GraphEngine backed by plain Python dicts.

    Internal structure:
        _nodes: {node_id: {attr_key: attr_val, ...}}
        _out:   {src: {tgt: {attr_key: attr_val, ...}}}
        _in:    {tgt: {src: {attr_key: attr_val, ...}}}
    """

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._out: dict[str, dict[str, dict[str, Any]]] = {}
        self._in: dict[str, dict[str, dict[str, Any]]] = {}

    # --- nodes ---

    def add_node(self, node_id: str, **attrs: Any) -> None:
        if node_id in self._nodes:
            self._nodes[node_id].update(attrs)
        else:
            self._nodes[node_id] = dict(attrs)
            self._out.setdefault(node_id, {})
            self._in.setdefault(node_id, {})

    def remove_node(self, node_id: str) -> None:
        # Remove outgoing edges
        for tgt in list(self._out.get(node_id, {})):
            del self._in[tgt][node_id]
        # Remove incoming edges
        for src in list(self._in.get(node_id, {})):
            del self._out[src][node_id]
        self._nodes.pop(node_id, None)
        self._out.pop(node_id, None)
        self._in.pop(node_id, None)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def get_node_attrs(self, node_id: str) -> dict[str, Any]:
        return dict(self._nodes[node_id])

    def set_node_attrs(self, node_id: str, **attrs: Any) -> None:
        self._nodes[node_id].update(attrs)

    def nodes(self) -> list[str]:
        return list(self._nodes)

    # --- edges ---

    def add_edge(self, source: str, target: str, **attrs: Any) -> None:
        # Auto-create nodes if they don't exist
        if source not in self._nodes:
            self.add_node(source)
        if target not in self._nodes:
            self.add_node(target)
        self._out[source][target] = dict(attrs)
        self._in[target][source] = self._out[source][target]  # same dict object

    def remove_edge(self, source: str, target: str) -> None:
        del self._out[source][target]
        del self._in[target][source]

    def has_edge(self, source: str, target: str) -> bool:
        return target in self._out.get(source, {})

    def get_edge_attrs(self, source: str, target: str) -> dict[str, Any]:
        return dict(self._out[source][target])

    def edges(self) -> list[tuple[str, str, dict[str, Any]]]:
        result: list[tuple[str, str, dict[str, Any]]] = []
        for src, targets in self._out.items():
            for tgt, attrs in targets.items():
                result.append((src, tgt, dict(attrs)))
        return result

    # --- traversal ---

    def get_neighbors(self, node_id: str, direction: str = "both") -> list[str]:
        result: set[str] = set()
        if direction in ("out", "both"):
            result.update(self._out.get(node_id, {}))
        if direction in ("in", "both"):
            result.update(self._in.get(node_id, {}))
        return list(result)

    def get_edges_from(
        self, node_id: str, direction: str = "both"
    ) -> list[tuple[str, str, dict[str, Any]]]:
        result: list[tuple[str, str, dict[str, Any]]] = []
        if direction in ("out", "both"):
            for tgt, attrs in self._out.get(node_id, {}).items():
                result.append((node_id, tgt, dict(attrs)))
        if direction in ("in", "both"):
            for src, attrs in self._in.get(node_id, {}).items():
                result.append((src, node_id, dict(attrs)))
        return result

    def subgraph(self, node_ids: list[str]) -> DictGraph:
        node_set = set(node_ids)
        sg = DictGraph()
        for nid in node_ids:
            if nid in self._nodes:
                sg.add_node(nid, **self._nodes[nid])
        for src in node_ids:
            for tgt, attrs in self._out.get(src, {}).items():
                if tgt in node_set:
                    sg.add_edge(src, tgt, **attrs)
        return sg

    def bfs(self, start: str, max_depth: int = 2) -> list[str]:
        if start not in self._nodes:
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
        return len(self._nodes)

    def edge_count(self) -> int:
        return sum(len(targets) for targets in self._out.values())

    # --- serialization ---

    def to_dict(self) -> dict[str, Any]:
        nodes = []
        for nid, attrs in self._nodes.items():
            nodes.append({"id": nid, **attrs})
        edges = []
        for src, targets in self._out.items():
            for tgt, attrs in targets.items():
                edges.append({"source": src, "target": tgt, **attrs})
        return {"nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DictGraph:
        g = cls()
        for node in data.get("nodes", []):
            nid = node["id"]
            attrs = {k: v for k, v in node.items() if k != "id"}
            g.add_node(nid, **attrs)
        for edge in data.get("edges", []):
            src = edge["source"]
            tgt = edge["target"]
            attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
            g.add_edge(src, tgt, **attrs)
        return g
