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
    issue = next(issue for issue in result.issues if issue.code == "unsupported_capability")
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
