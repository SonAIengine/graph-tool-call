"""Graph serialization: save/load ontology to JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from graph_tool_call.core.graph import NetworkXGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema

# Serialization format version — bump when schema changes
_FORMAT_VERSION = "1"


def save_graph(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    path: str | Path,
) -> None:
    """Save graph structure and tool schemas to a JSON file."""
    from graph_tool_call import __version__

    data: dict[str, Any] = {
        "format_version": _FORMAT_VERSION,
        "library_version": __version__,
        "graph": graph.to_dict(),
        "tools": {name: tool.model_dump() for name, tool in tools.items()},
    }
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    except PermissionError:
        msg = f"Permission denied: {path}. Check directory permissions."
        raise PermissionError(msg) from None
    except OSError as e:
        msg = f"Failed to save graph to {path}: {e}"
        raise OSError(msg) from None


def load_graph(path: str | Path) -> tuple[GraphEngine, dict[str, ToolSchema]]:
    """Load graph structure and tool schemas from a JSON file."""
    path = Path(path)
    if not path.exists():
        msg = f"Graph file not found: {path}"
        raise FileNotFoundError(msg)

    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in {path}: {e}"
        raise ValueError(msg) from None

    # Support both old ("version") and new ("format_version") keys
    fmt = data.get("format_version") or data.get("version", "0")
    if fmt not in ("0", "0.1.0", _FORMAT_VERSION):
        msg = f"Unsupported graph format version '{fmt}' in {path}. Expected '{_FORMAT_VERSION}'."
        raise ValueError(msg)

    if "graph" not in data:
        msg = f"Missing 'graph' key in {path}. File may be corrupted."
        raise ValueError(msg)

    graph = NetworkXGraph.from_dict(data["graph"])
    tools = {name: ToolSchema(**schema) for name, schema in data.get("tools", {}).items()}
    return graph, tools
