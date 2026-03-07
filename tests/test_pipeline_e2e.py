"""End-to-end tests for the full pipeline: lint → ingest → LLM organize."""

from __future__ import annotations

import json
from unittest.mock import patch

from graph_tool_call.ontology.llm_provider import OntologyLLM
from graph_tool_call.tool_graph import ToolGraph


def _mock_spec() -> dict:
    """A minimal but complete OpenAPI spec for testing."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Commerce API", "version": "1.0.0"},
        "paths": {
            "/orders": {
                "get": {
                    "operationId": "listOrders",
                    "summary": "List orders",
                    "tags": ["orders"],
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "operationId": "createOrder",
                    "summary": "Create order",
                    "tags": ["orders"],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"type": "object", "properties": {}}}
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                },
            },
            "/orders/{orderId}": {
                "get": {
                    "operationId": "getOrder",
                    "summary": "Get order by ID",
                    "tags": ["orders"],
                    "parameters": [{"name": "orderId", "in": "path", "required": True}],
                    "responses": {"200": {"description": "OK"}},
                },
                "delete": {
                    "operationId": "cancelOrder",
                    "summary": "Cancel order",
                    "tags": ["orders"],
                    "parameters": [{"name": "orderId", "in": "path", "required": True}],
                    "responses": {"204": {"description": "No Content"}},
                },
            },
            "/products": {
                "get": {
                    "operationId": "listProducts",
                    "summary": "List products",
                    "tags": ["products"],
                    "responses": {"200": {"description": "OK"}},
                },
            },
        },
    }


class MockLLM(OntologyLLM):
    """Mock LLM that returns predictable responses."""

    def generate(self, prompt: str) -> str:
        if "relationship" in prompt.lower() or "relation" in prompt.lower():
            return json.dumps(
                [
                    {
                        "source": "createOrder",
                        "target": "getOrder",
                        "relation": "PRECEDES",
                        "confidence": 0.9,
                        "reason": "Create before get",
                    },
                ]
            )
        if "categor" in prompt.lower():
            return json.dumps(
                {
                    "categories": {
                        "order-management": [
                            "listOrders",
                            "createOrder",
                            "getOrder",
                            "cancelOrder",
                        ],
                        "catalog": ["listProducts"],
                    }
                }
            )
        if "keyword" in prompt.lower():
            return json.dumps(
                {
                    "listOrders": ["orders", "list", "query", "search"],
                    "createOrder": ["order", "create", "new", "purchase"],
                    "getOrder": ["order", "detail", "fetch", "retrieve"],
                    "cancelOrder": ["cancel", "void", "refund", "delete"],
                    "listProducts": ["products", "catalog", "items", "inventory"],
                }
            )
        return "{}"


def test_pipeline_no_extras():
    """Basic pipeline without lint or LLM — should match existing behavior."""
    tg = ToolGraph()
    tg.ingest_openapi(_mock_spec())

    assert len(tg.tools) == 5
    results = tg.retrieve("create order", top_k=3)
    names = [t.name for t in results]
    assert "createOrder" in names


def test_pipeline_with_llm():
    """Pipeline with LLM should add categories and keywords."""
    tg = ToolGraph()
    tg.ingest_openapi(_mock_spec())
    tg.auto_organize(llm=MockLLM())

    # Check that keywords were enriched
    attrs = tg.graph.get_node_attrs("cancelOrder")
    tags = attrs.get("tags", [])
    assert any(k in tags for k in ["cancel", "void", "refund"]), (
        f"Expected enriched keywords, got: {tags}"
    )


def test_pipeline_from_url_with_llm():
    """from_url() with llm should run auto_organize after ingest."""
    spec_json = json.dumps(_mock_spec()).encode("utf-8")

    class FakeResp:
        def read(self):
            return spec_json

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        tg = ToolGraph.from_url(
            "https://example.com/openapi.json",
            llm=MockLLM(),
        )

    assert len(tg.tools) == 5
    # LLM should have organized categories
    attrs = tg.graph.get_node_attrs("listProducts")
    tags = attrs.get("tags", [])
    assert any(k in tags for k in ["products", "catalog", "items"]), (
        f"Expected enriched keywords, got: {tags}"
    )
