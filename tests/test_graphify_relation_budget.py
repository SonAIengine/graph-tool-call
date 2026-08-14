from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import ingest_openapi_graphify


def _dense_tools(count: int) -> list[ToolSchema]:
    return [
        ToolSchema(
            name=f"getItem{index}",
            metadata={
                "method": "get",
                "path": f"/items/{index}",
                "response_schema": {"$ref": f"#/components/schemas/Group{index // 8}Envelope"},
            },
        )
        for index in range(count)
    ]


def test_graphify_reports_relation_budget_reached():
    graph, stats = ingest_openapi_graphify(
        _dense_tools(40),
        max_detected_relations=25,
    )

    assert graph.graph.edge_count() == 25
    assert stats["relation_budget"] == 25
    assert stats["relation_budget_reached"] is True


def test_graphify_small_catalog_does_not_report_truncation():
    tools = [
        ToolSchema(
            name=f"getItem{index}",
            metadata={
                "method": "get",
                "path": f"/items/{index}",
                "response_schema": {"$ref": "#/components/schemas/CommonEnvelope"},
            },
        )
        for index in range(3)
    ]
    _graph, stats = ingest_openapi_graphify(
        tools,
        max_detected_relations=25,
    )

    assert stats["relation_budget_reached"] is False
