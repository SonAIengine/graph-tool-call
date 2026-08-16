from __future__ import annotations

from unittest.mock import patch

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import apply_arazzo_workflows


def _workflow_spec() -> dict:
    return {
        "arazzo": "1.1.0",
        "info": {"title": "Order flow", "version": "1.0.0"},
        "sourceDescriptions": [],
        "workflows": [
            {
                "workflowId": "read-order",
                "steps": [
                    {"stepId": "list", "operationId": "listOrders"},
                    {"stepId": "read", "operationId": "getOrder"},
                ],
            }
        ],
    }


def test_remote_source_manifest_drops_credentials_query_and_fragment() -> None:
    graph = ToolGraph()
    graph.add_tool(ToolSchema(name="listOrders"))
    graph.add_tool(ToolSchema(name="getOrder"))
    source = "https://user:password@example.com/flow.yaml?token=secret#fragment"

    with patch(
        "graph_tool_call.graphify.workflow_evidence._load_spec",
        return_value=_workflow_spec(),
    ):
        summary = apply_arazzo_workflows(graph, source)

    manifest = summary["source_snapshot_manifest"]["specs"][0]
    assert manifest["source"] == "https://example.com/flow.yaml"
    assert "password" not in str(summary)
    assert "secret" not in str(summary)
    assert graph.graph.has_edge("listOrders", "getOrder")
