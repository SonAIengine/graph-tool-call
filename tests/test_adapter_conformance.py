"""Contract tests for the deterministic E0 adapter-conformance benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.adapter_conformance import run_adapter_conformance
from benchmarks.adapter_conformance.expectations import (
    ToolExpectation,
    inspect_source_expectations,
    schema_signatures,
)
from benchmarks.adapter_conformance.run import (
    _contract_consumes_preserved,
    _contract_produces_preserved,
    _execution_template_ready,
    _request_preserved,
    _response_preserved,
)
from benchmarks.experiment.artifact import validate_artifact
from graph_tool_call import ingest_source
from graph_tool_call.core.tool import ToolSchema


def test_openapi_expectations_are_derived_from_source_declared_facts() -> None:
    source = {
        "openapi": "3.0.0",
        "info": {"title": "Orders", "version": "1"},
        "security": [{"bearerAuth": []}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            },
            "schemas": {
                "Order": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "status": {"type": "string"},
                    },
                }
            },
        },
        "paths": {
            "/orders/{orderId}": {
                "get": {
                    "operationId": "getOrder",
                    "parameters": [
                        {
                            "name": "orderId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/Order",
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }

    expectation = inspect_source_expectations(
        source,
        source_type="openapi",
    ).tools["GET /orders/{orderId}"]

    assert expectation.request_fields == frozenset({"orderId"})
    assert expectation.response_signatures == frozenset(
        {
            ("$.id", "string"),
            ("$.status", "string"),
        }
    )
    assert expectation.auth_schemes == frozenset({"bearerAuth"})
    assert expectation.required_auth_schemes == frozenset({"bearerAuth"})
    assert expectation.auth_scheme_facts == frozenset(
        {
            (
                "bearerAuth",
                "http",
                "",
                "",
                "bearer",
                "",
                "",
                "",
            )
        }
    )
    assert expectation.auth_requirements == ((("bearerAuth", ()),),)
    assert expectation.consume_fields == frozenset({"orderId"})
    assert expectation.produce_fields == frozenset({"id", "status"})
    assert expectation.execution_transport == "http"
    assert expectation.consumes_expected is True
    assert expectation.produces_expected is True


def test_schema_signatures_are_bounded_without_inventing_unknown_failures() -> None:
    cyclic_document = {
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "child": {"$ref": "#/components/schemas/Node"},
                    },
                }
            }
        }
    }

    signatures = schema_signatures(
        {"$ref": "#/components/schemas/Node"},
        document=cyclic_document,
    )

    assert signatures == frozenset({("$.name", "string")})
    assert all(field_type != "unknown" for _, field_type in signatures)


def test_mcp_expectations_distinguish_absent_output_schema_from_failure() -> None:
    expectations = inspect_source_expectations(
        [
            {
                "name": "read_file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            }
        ],
        source_type="mcp",
    )

    expectation = expectations.tools["read_file"]
    assert expectation.request_applicable is True
    assert expectation.response_applicable is False
    assert expectation.consumes_expected is True
    assert expectation.produces_expected is False


def test_contract_metrics_reject_partial_field_extraction() -> None:
    expectation = ToolExpectation(
        key="GET /orders",
        consume_fields=frozenset({"customerId", "status"}),
        produce_fields=frozenset({"orderId", "total"}),
        required_auth_schemes=frozenset({"bearerAuth"}),
        consumes_expected=True,
        produces_expected=True,
    )

    assert (
        _contract_consumes_preserved(
            expectation,
            [{"field_name": "customerId", "kind": "data"}],
        )
        is False
    )
    assert (
        _contract_produces_preserved(
            expectation,
            [{"field_name": "orderId"}],
        )
        is False
    )
    assert _contract_consumes_preserved(
        expectation,
        [
            {"field_name": "customerId", "kind": "data"},
            {"field_name": "status", "kind": "data"},
            {
                "field_name": "Authorization",
                "kind": "auth",
                "security_schemes": ["bearerAuth"],
            },
        ],
    )
    assert _contract_produces_preserved(
        expectation,
        [{"field_name": "orderId"}, {"field_name": "total"}],
    )


def test_mcp_execution_template_requires_argument_and_client_binding() -> None:
    expectation = ToolExpectation(
        key="lookup_order",
        execution_transport="mcp",
    )
    tool = ToolSchema(
        name="lookup_order",
        description="Look up an order",
        metadata={
            "execution": {
                "transport": "mcp",
                "method": "tools/call",
                "tool_name": "lookup_order",
            }
        },
    )

    assert _execution_template_ready(expectation, tool) is False
    tool.metadata["execution"].update(
        {
            "arguments_binding": "parameters_to_arguments",
            "requires_client_binding": True,
        }
    )
    assert _execution_template_ready(expectation, tool) is True


def test_graphql_expectations_preserve_nested_input_and_return_type() -> None:
    root = Path(__file__).resolve().parents[1]
    source = json.loads(
        (root / "benchmarks/corpus/sources/graphql_commerce.json").read_text(encoding="utf-8")
    )
    options = {"endpoint_url": "https://example.invalid/graphql"}
    expectation = inspect_source_expectations(
        source,
        source_type="graphql-introspection",
        ingest_options=options,
    ).tools["mutation:updateCustomer"]
    result = ingest_source(
        source,
        format_hint="graphql-introspection",
        **options,
    )
    tool = next(
        row for row in result.tools if row.metadata["graphql"]["root_field"] == "updateCustomer"
    )

    assert expectation.request_field_types == frozenset({("input", "object", True)})
    assert expectation.consume_fields == frozenset({"id", "name"})
    assert expectation.produce_fields == frozenset({"id", "name", "status"})
    assert expectation.graphql_return_type == "Customer!"
    assert _request_preserved("graphql-introspection", expectation, tool)
    assert _response_preserved("graphql-introspection", expectation, tool)
    assert _contract_consumes_preserved(
        expectation,
        tool.metadata["api_contract"]["consumes"],
    )
    assert _contract_produces_preserved(
        expectation,
        tool.metadata["api_contract"]["produces"],
    )


def test_train_adapter_conformance_emits_valid_replayable_artifact(
    tmp_path: Path,
) -> None:
    artifact = run_adapter_conformance(
        splits=("train",),
        output_path=tmp_path / "adapter-conformance.json",
        created_at="2026-07-30T00:00:00+00:00",
    )

    assert validate_artifact(artifact).valid is True
    assert artifact.dataset["held_out_accessed"] is False
    assert artifact.summary["source_count"] == 2
    assert artifact.summary["tool_count"] == 28
    for metric in artifact.summary["metrics"].values():
        assert metric["passed"] == metric["applicable"]
        assert metric["micro_rate"] == 1.0
    diagnostics = artifact.summary["structured_unsupported_diagnostics"]
    assert diagnostics["passed"] == diagnostics["applicable"] == 6
    assert diagnostics["rate"] == 1.0


def test_test_split_requires_explicit_held_out_access(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Held-out test access"):
        run_adapter_conformance(
            splits=("test",),
            output_path=tmp_path / "held-out.json",
        )
