"""GraphEngine protocol — abstract interface for graph backends."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GraphEngine(Protocol):
    """Minimal interface that any graph backend must implement."""

    def add_node(self, node_id: str, **attrs: Any) -> None:
        """Add a node with optional attributes."""
        ...

    def remove_node(self, node_id: str) -> None:
        """Remove a node and its edges."""
        ...

    def has_node(self, node_id: str) -> bool:
        ...

    def get_node_attrs(self, node_id: str) -> dict[str, Any]:
        """Return all attributes of a node."""
        ...

    def set_node_attrs(self, node_id: str, **attrs: Any) -> None:
        """Update attributes of a node."""
        ...

    def nodes(self) -> list[str]:
        """Return all node IDs."""
        ...

    def add_edge(self, source: str, target: str, **attrs: Any) -> None:
        """Add a directed edge with optional attributes."""
        ...

    def remove_edge(self, source: str, target: str) -> None:
        ...

    def has_edge(self, source: str, target: str) -> bool:
        ...

    def get_edge_attrs(self, source: str, target: str) -> dict[str, Any]:
        ...

    def edges(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Return all edges as (source, target, attrs) tuples."""
        ...

    def get_neighbors(self, node_id: str, direction: str = "both") -> list[str]:
        """Get neighbor node IDs.

        direction: "out" | "in" | "both"
        """
        ...

    def get_edges_from(self, node_id: str, direction: str = "both") -> list[tuple[str, str, dict[str, Any]]]:
        """Get edges connected to a node."""
        ...

    def subgraph(self, node_ids: list[str]) -> "GraphEngine":
        """Return a new graph containing only the specified nodes and edges between them."""
        ...

    def bfs(self, start: str, max_depth: int = 2) -> list[str]:
        """Breadth-first search from start, returning node IDs up to max_depth."""
        ...

    def node_count(self) -> int:
        ...

    def edge_count(self) -> int:
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEngine":
        """Deserialize from a dict."""
        ...
