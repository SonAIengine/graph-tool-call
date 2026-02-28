"""Graph serialization: save/load ontology to JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from graph_tool_call.core.graph import NetworkXGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema


def save_graph(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    path: str | Path,
) -> None:
    """Save graph structure and tool schemas to a JSON file."""
    data: dict[str, Any] = {
        "version": "0.1.0",
        "graph": graph.to_dict(),
        "tools": {name: tool.model_dump() for name, tool in tools.items()},
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def load_graph(path: str | Path) -> tuple[GraphEngine, dict[str, ToolSchema]]:
    """Load graph structure and tool schemas from a JSON file."""
    data = json.loads(Path(path).read_text())
    graph = NetworkXGraph.from_dict(data["graph"])
    tools = {name: ToolSchema(**schema) for name, schema in data.get("tools", {}).items()}
    return graph, tools
