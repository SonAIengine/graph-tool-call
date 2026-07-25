"""Contract tests for the source-agnostic ingest adapter SPI."""

from __future__ import annotations

from typing import Any

import pytest

from graph_tool_call import (
    AmbiguousIngestAdapterError,
    IngestAdapterRegistry,
    IngestCapabilities,
    IngestConformanceError,
    IngestResult,
    UnknownIngestAdapterError,
    ingest_source,
)
from graph_tool_call.core.tool import ToolSchema


def _openapi_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Orders", "version": "1.0.0"},
        "paths": {
            "/orders": {
                "get": {
                    "operationId": "listOrders",
                    "summary": "List orders",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


def _mcp_tool(name: str = "read_file") -> dict[str, Any]:
    return {
        "name": name,
        "description": "Read a file",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }


def test_public_ingest_source_detects_openapi_and_adds_provenance() -> None:
    result = ingest_source(_openapi_spec())

    assert result.adapter == "openapi"
    assert result.ready is True
    assert [tool.name for tool in result.tools] == ["listOrders"]
    assert "output_schema" in result.capabilities.features
    assert result.tools[0].metadata["ingest"]["adapter"] == "openapi"
    assert result.to_dict()["tool_count"] == 1


def test_ingest_source_detects_mcp_before_generic_tool_catalog() -> None:
    result = ingest_source([_mcp_tool()], server_name="filesystem")

    assert result.adapter == "mcp-tools"
    assert result.tools[0].metadata["mcp_server"] == "filesystem"
    assert result.metadata["server_name"] == "filesystem"
    assert "annotations" in result.capabilities.features


def test_mcp_adapter_preserves_output_contract_and_catalog_summary() -> None:
    tool = _mcp_tool("lookup_customer")
    tool["title"] = "Customer lookup"
    tool["outputSchema"] = {
        "type": "object",
        "properties": {"customerId": {"type": "string"}},
        "required": ["customerId"],
    }
    tool["execution"] = {"taskSupport": "required"}

    result = ingest_source(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [tool],
                "serverInfo": {"name": "crm", "version": "1.2.3"},
            },
        }
    )

    assert result.adapter == "mcp-tools"
    assert result.ready is True
    assert result.metadata["server_name"] == "crm"
    assert result.metadata["server_version"] == "1.2.3"
    assert result.metadata["output_schema_coverage"] == 1.0
    assert result.tools[0].metadata["response_schema"] == tool["outputSchema"]
    assert "output_schema" in result.capabilities.features


def test_mcp_adapter_blocks_incomplete_paginated_catalog_by_default() -> None:
    result = ingest_source(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [_mcp_tool()],
                "nextCursor": "page-2",
            },
        }
    )

    assert result.ready is False
    issue = next(issue for issue in result.issues if issue.code == "mcp_catalog_incomplete")
    assert issue.evidence["next_cursor_present"] is True

    partial = ingest_source(
        {
            "tools": [_mcp_tool()],
            "nextCursor": "page-2",
        },
        allow_partial_catalog=True,
    )
    assert partial.ready is True
    assert any(issue.code == "mcp_catalog_partial" for issue in partial.issues)


def test_mcp_adapter_deduplicates_names_and_reports_invalid_schemas() -> None:
    duplicate = _mcp_tool("read_file")
    invalid = _mcp_tool("broken")
    invalid["inputSchema"] = {"type": "string"}

    result = ingest_source([_mcp_tool("read_file"), duplicate, invalid])

    assert [tool.name for tool in result.tools] == ["read_file"]
    assert result.ready is False
    assert any(issue.code == "duplicate_mcp_tool_name" for issue in result.issues)
    assert any(issue.code == "invalid_mcp_input_schema" for issue in result.issues)


def test_mcp_adapter_ignores_invalid_optional_output_schema() -> None:
    tool = _mcp_tool("read_file")
    tool["outputSchema"] = {
        "type": "object",
        "properties": "not-an-object",
    }

    result = ingest_source([tool])

    assert result.ready is True
    assert result.metadata["output_schema_coverage"] == 0.0
    assert "response_schema" not in result.tools[0].metadata
    assert any(issue.code == "invalid_mcp_output_schema" for issue in result.issues)


def test_mcp_adapter_enforces_catalog_tool_limit() -> None:
    result = ingest_source(
        [_mcp_tool(f"tool_{index}") for index in range(3)],
        max_tools=2,
    )

    assert [tool.name for tool in result.tools] == ["tool_0", "tool_1"]
    assert result.ready is False
    issue = next(issue for issue in result.issues if issue.code == "mcp_tool_limit_exceeded")
    assert issue.evidence == {"actual": 3, "limit": 2}


def test_mcp_adapter_blocks_oversized_schema_shape() -> None:
    schema: dict[str, Any] = {"type": "object"}
    current = schema
    for index in range(8):
        child = {"type": "object"}
        current["properties"] = {f"level_{index}": child}
        current = child
    tool = _mcp_tool("deep_tool")
    tool["inputSchema"] = schema

    result = ingest_source([tool], max_schema_depth=5)

    assert result.ready is False
    issue = next(issue for issue in result.issues if issue.code == "mcp_schema_limit_exceeded")
    assert issue.tool == "deep_tool"
    assert issue.evidence["schema"] == "inputSchema"


def test_ingest_source_accepts_python_functions() -> None:
    def add(left: int, right: int) -> int:
        """Add two integers."""

        return left + right

    result = ingest_source(add)

    assert result.adapter == "python-functions"
    assert result.tools[0].get_callable() is add
    assert [parameter.type for parameter in result.tools[0].parameters] == [
        "integer",
        "integer",
    ]


def test_generic_tool_catalog_is_a_supported_fallback() -> None:
    result = ingest_source(
        [
            {
                "type": "function",
                "function": {
                    "name": "lookup_customer",
                    "description": "Look up a customer",
                    "parameters": {
                        "type": "object",
                        "properties": {"customer_id": {"type": "string"}},
                        "required": ["customer_id"],
                    },
                },
            }
        ]
    )

    assert result.adapter == "tool-catalog"
    assert result.tools[0].name == "lookup_customer"
    assert result.tools[0].metadata["ingest"]["source_type"] == "tool-catalog"


def test_unknown_source_requires_hint_or_registered_adapter() -> None:
    with pytest.raises(UnknownIngestAdapterError, match="register an adapter"):
        ingest_source({"asyncapi": "3.0.0", "channels": {}})


def test_unknown_explicit_format_hint_does_not_fall_back_to_detection() -> None:
    with pytest.raises(UnknownIngestAdapterError, match="missing-adapter"):
        ingest_source(_openapi_spec(), format_hint="missing-adapter")


def test_required_capability_is_reported_instead_of_silently_dropped() -> None:
    result = ingest_source(
        [_mcp_tool()],
        required_capabilities={"output_schema"},
    )

    assert result.ready is False
    issue = next(issue for issue in result.issues if issue.code == "incomplete_required_capability")
    assert issue.evidence["capability"] == "output_schema"

    with pytest.raises(IngestConformanceError) as exc_info:
        ingest_source(
            [_mcp_tool()],
            required_capabilities={"output_schema"},
            strict=True,
        )
    assert exc_info.value.result.adapter == "mcp-tools"


class _AsyncAPIAdapter:
    name = "asyncapi-test"
    capabilities = IngestCapabilities(
        source_type="asyncapi",
        features=frozenset({"input_schema", "output_schema", "streaming"}),
        transports=frozenset({"kafka", "websocket"}),
    )

    def detect(self, source: Any) -> float:
        return 1.0 if isinstance(source, dict) and "asyncapi" in source else 0.0

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        del source, options
        return IngestResult(
            tools=[ToolSchema(name="publish_order", description="Publish an order event")],
            adapter=self.name,
            capabilities=self.capabilities,
        )


def test_third_party_adapter_can_extend_the_registry_without_engine_changes() -> None:
    registry = IngestAdapterRegistry()
    registry.register(_AsyncAPIAdapter())

    result = registry.ingest({"asyncapi": "3.0.0", "channels": {}})

    assert result.adapter == "asyncapi-test"
    assert result.tools[0].name == "publish_order"
    assert result.tools[0].metadata["ingest"]["source_type"] == "asyncapi"
    assert "streaming" in result.capabilities.features


class _DuplicateAdapter(_AsyncAPIAdapter):
    name = "duplicate-test"

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        del source, options
        return IngestResult(
            tools=[
                ToolSchema(name="same", description="First"),
                ToolSchema(name="same", description="Second"),
            ],
            adapter=self.name,
            capabilities=self.capabilities,
        )


def test_conformance_gate_blocks_duplicate_canonical_names() -> None:
    registry = IngestAdapterRegistry()
    registry.register(_DuplicateAdapter())

    result = registry.ingest({"asyncapi": "3.0.0"})

    assert result.ready is False
    assert [issue.code for issue in result.issues] == ["duplicate_tool_name"]


class _InvalidToolAdapter(_AsyncAPIAdapter):
    name = "invalid-tool-test"

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        del source, options
        return IngestResult(
            tools=[
                ToolSchema(name="", description="Missing canonical name"),
                {"name": "not-a-schema"},  # type: ignore[list-item]
            ],
            adapter=self.name,
            capabilities=self.capabilities,
        )


def test_conformance_gate_structures_invalid_third_party_output() -> None:
    registry = IngestAdapterRegistry()
    registry.register(_InvalidToolAdapter())

    result = registry.ingest({"asyncapi": "3.0.0"})

    assert result.tools == []
    assert result.ready is False
    assert [issue.code for issue in result.issues] == [
        "invalid_tool_name",
        "invalid_tool_schema",
        "empty_tool_catalog",
    ]


class _EquallyConfidentAdapter(_AsyncAPIAdapter):
    name = "asyncapi-tie"


def test_ambiguous_detection_requires_explicit_format_hint() -> None:
    registry = IngestAdapterRegistry()
    registry.register(_AsyncAPIAdapter())
    registry.register(_EquallyConfidentAdapter())

    with pytest.raises(AmbiguousIngestAdapterError, match="format_hint"):
        registry.ingest({"asyncapi": "3.0.0"})

    result = registry.ingest(
        {"asyncapi": "3.0.0"},
        format_hint="asyncapi-test",
    )
    assert result.adapter == "asyncapi-test"
