"""Graph serialization: save/load ontology to JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_tool_call.core.dict_graph import DictGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema

# Serialization format version — bump when schema changes
_FORMAT_VERSION = "1"


def save_graph(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    path: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
    retrieval_state: dict[str, Any] | None = None,
) -> None:
    """Save graph structure and tool schemas to a JSON file.

    Parameters
    ----------
    metadata:
        Optional build metadata (source_urls, build_options, etc.).
        Automatically includes ``built_at`` timestamp.
    """
    from graph_tool_call import __version__

    build_meta: dict[str, Any] = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "tool_count": len(tools),
    }
    if metadata:
        build_meta.update(metadata)

    data: dict[str, Any] = {
        "format_version": _FORMAT_VERSION,
        "library_version": __version__,
        "metadata": build_meta,
        "graph": graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in tools.items()},
    }
    if retrieval_state:
        data["retrieval_state"] = retrieval_state
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    except PermissionError:
        msg = f"Permission denied: {path}. Check directory permissions."
        raise PermissionError(msg) from None
    except OSError as e:
        msg = f"Failed to save graph to {path}: {e}"
        raise OSError(msg) from None


def load_graph(
    path: str | Path,
) -> tuple[GraphEngine, dict[str, ToolSchema], dict[str, Any], dict[str, Any]]:
    """Load graph structure, tool schemas, and build metadata from a JSON file.

    Returns
    -------
    tuple[GraphEngine, dict[str, ToolSchema], dict[str, Any], dict[str, Any]]
        (graph, tools, metadata, retrieval_state). Metadata includes ``built_at``,
        ``source_urls``, ``tool_count``, etc.
    """
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

    graph = DictGraph.from_dict(data["graph"])
    tools = {name: ToolSchema(**schema) for name, schema in data.get("tools", {}).items()}
    metadata = data.get("metadata", {})
    retrieval_state = data.get("retrieval_state", {})
    return graph, tools, metadata, retrieval_state
