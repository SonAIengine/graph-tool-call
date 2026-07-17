"""Tests for graphify collection metadata helpers."""

from __future__ import annotations

from graph_tool_call import __version__
from graph_tool_call.graphify import (
    COLLECTION_GRAPH_VERSION,
    annotate_graphify_metadata,
    detect_enrichment_status,
)


def test_detect_enrichment_status_empty():
    assert detect_enrichment_status({}) == "empty"


def test_detect_enrichment_status_not_started_partial_complete():
    base_tool = {"metadata": {"ai_metadata": {}}}
    enriched_tool = {"metadata": {"ai_metadata": {"canonical_action": "read"}}}

    assert detect_enrichment_status({"a": base_tool}) == "not_started"
    assert detect_enrichment_status({"a": base_tool, "b": enriched_tool}) == "partial"
    assert detect_enrichment_status({"b": enriched_tool}) == "complete"


def test_annotate_graphify_metadata_adds_top_level_and_metadata_fields():
    graph = {
        "format_version": "1",
        "metadata": {"tool_count": 1},
        "graph": {"nodes": {}, "edges": []},
        "tools": {
            "getProduct": {
                "metadata": {"ai_metadata": {"canonical_action": "read"}},
            }
        },
    }

    annotated = annotate_graphify_metadata(graph)

    assert annotated is not graph
    assert annotated["graph_tool_call_version"] == __version__
    assert annotated["collection_graph_version"] == COLLECTION_GRAPH_VERSION
    assert annotated["enrichment_status"] == "complete"
    assert annotated["metadata"]["graph_tool_call_version"] == __version__
    assert annotated["metadata"]["collection_graph_version"] == COLLECTION_GRAPH_VERSION
    assert annotated["metadata"]["enrichment_status"] == "complete"
    assert "graph_tool_call_version" not in graph


def test_annotate_graphify_metadata_can_update_in_place():
    graph = {"metadata": {}, "tools": {}}

    annotated = annotate_graphify_metadata(
        graph,
        enrichment_status="not_started",
        graph_tool_call_version="9.9.9",
        in_place=True,
    )

    assert annotated is graph
    assert graph["graph_tool_call_version"] == "9.9.9"
    assert graph["enrichment_status"] == "not_started"
