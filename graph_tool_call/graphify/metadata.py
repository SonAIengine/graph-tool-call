"""Graphify collection metadata helpers.

These helpers keep product integrations from hand-rolling version/status
fields on persisted graphify JSON. They are intentionally product-neutral:
callers own storage, auth, UI, and execution adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

COLLECTION_GRAPH_VERSION = "1"


def detect_enrichment_status(tools: Mapping[str, Any] | None) -> str:
    """Return a coarse Pass-2 enrichment status for serialized tools.

    Status values are stable strings for UI/cache consumers:
    ``empty`` | ``not_started`` | ``partial`` | ``complete``.
    A tool is counted as enriched when ``metadata.ai_metadata`` contains a
    non-empty ``canonical_action``.
    """
    if not tools:
        return "empty"

    total = 0
    enriched = 0
    for tool in tools.values():
        total += 1
        metadata = _metadata_of(tool)
        ai_metadata = metadata.get("ai_metadata") if isinstance(metadata, dict) else {}
        if isinstance(ai_metadata, dict) and str(ai_metadata.get("canonical_action") or "").strip():
            enriched += 1

    if total == 0:
        return "empty"
    if enriched == 0:
        return "not_started"
    if enriched < total:
        return "partial"
    return "complete"


def annotate_graphify_metadata(
    graph_dict: dict[str, Any],
    *,
    enrichment_status: str | None = None,
    collection_graph_version: str = COLLECTION_GRAPH_VERSION,
    graph_tool_call_version: str | None = None,
    in_place: bool = False,
) -> dict[str, Any]:
    """Attach stable graphify metadata to a serialized collection graph.

    The fields are duplicated at the top level and under ``metadata`` so both
    JSONB-style product integrations and ``ToolGraph.load``-style consumers
    can read them without knowing each other's wrapper conventions.
    """
    from graph_tool_call import __version__

    out = graph_dict if in_place else deepcopy(graph_dict)
    version = graph_tool_call_version or __version__
    status = enrichment_status or detect_enrichment_status(out.get("tools"))

    out["graph_tool_call_version"] = version
    out["collection_graph_version"] = collection_graph_version
    out["enrichment_status"] = status

    metadata = dict(out.get("metadata") or {})
    metadata["graph_tool_call_version"] = version
    metadata["collection_graph_version"] = collection_graph_version
    metadata["enrichment_status"] = status
    out["metadata"] = metadata
    return out


def _metadata_of(tool: Any) -> dict[str, Any]:
    if hasattr(tool, "metadata"):
        metadata = getattr(tool, "metadata") or {}
        return metadata if isinstance(metadata, dict) else {}
    if isinstance(tool, dict):
        metadata = tool.get("metadata") or {}
        return metadata if isinstance(metadata, dict) else {}
    return {}


__all__ = [
    "COLLECTION_GRAPH_VERSION",
    "annotate_graphify_metadata",
    "detect_enrichment_status",
]
