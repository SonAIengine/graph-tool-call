from benchmarks.openapi_dependency_closure import (
    OPENAPI_CLOSURE_METHODOLOGY,
    _promotion_gate,
    _summarize,
    evaluate_openapi_dependency_cases,
)
from graph_tool_call import ingest_source


def _commerce_spec():
    return {
        "openapi": "3.0.0",
        "info": {"title": "Orders", "version": "1"},
        "paths": {
            "/customers": {
                "get": {
                    "operationId": "findCustomers",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"customerId": {"type": "string"}},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/orders/{customerId}": {
                "get": {
                    "operationId": "listCustomerOrders",
                    "parameters": [
                        {
                            "name": "customerId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"orderId": {"type": "string"}},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }


def test_automatic_openapi_closure_recovers_required_producer_without_label_leakage():
    tools = ingest_source(_commerce_spec(), format_hint="openapi").tools

    cases, source = evaluate_openapi_dependency_cases(
        tools,
        [
            {
                "case_id": "orders-by-customer",
                "query": "Find the customer and list their orders.",
                "expected_targets": ["listCustomerOrders"],
                "required_producers": ["findCustomers"],
            }
        ],
        source_id="commerce",
        split="dev",
    )

    assert source["tool_count"] == 2
    assert source["edge_count"] >= 1
    assert cases[0]["automatic_required_dependencies"] == ["findCustomers"]
    assert cases[0]["metrics"]["required_producer_recall"] == 1.0
    assert cases[0]["diagnostics"]["missing_required_producers"] == []


def test_openapi_closure_methodology_is_frozen():
    assert OPENAPI_CLOSURE_METHODOLOGY == "oracle-target-automatic-openapi-closure-v1"


def test_no_consumer_aligned_profile_still_evaluates_explicit_contracts():
    tools = ingest_source(_commerce_spec(), format_hint="openapi").tools
    case = {
        "case_id": "orders-by-customer",
        "query": "Find the customer and list their orders.",
        "expected_targets": ["listCustomerOrders"],
        "required_producers": ["findCustomers"],
    }

    default, _ = evaluate_openapi_dependency_cases(
        tools,
        [case],
        source_id="commerce",
        split="dev",
        consumer_aligned=False,
    )

    assert default[0]["metrics"]["required_producer_recall"] == 1.0
    assert default[0]["automatic_required_dependencies"] == ["findCustomers"]
    assert default[0]["diagnostics"]["evidence"][0]["sources"] == ["api_contract"]


def test_promotion_gate_blocks_small_or_over_expanded_samples():
    cases = [
        {
            "metrics": {
                "unexpected_dependency_count": 2,
            }
        }
    ]
    gate = _promotion_gate(
        {
            "required_producer_recall": 1.0,
            "all_required_found_rate": 1.0,
        },
        cases,
    )

    assert gate["passed"] is False
    assert gate["checks"]["minimum_dependency_cases"]["passed"] is False
    assert gate["checks"]["unexpected_dependencies_per_case"]["passed"] is False


def test_promotion_gate_passes_a_large_accurate_sample():
    cases = [
        {
            "metrics": {"unexpected_dependency_count": 0},
        }
        for _ in range(30)
    ]

    gate = _promotion_gate(
        {
            "required_producer_recall": 0.9,
            "all_required_found_rate": 0.8,
        },
        cases,
    )

    assert gate["passed"] is True


def test_summary_does_not_treat_no_dependency_cases_as_perfect_recall():
    cases = [
        {
            "source_id": "read-only",
            "expected_required_producers": [],
            "metrics": {
                "required_producer_recall": 1.0,
                "all_required_found": 1.0,
                "unexpected_dependency_count": 0,
                "closure_complete": 1.0,
            },
        }
    ]

    summary = _summarize(cases, {"read-only": {"tool_count": 1}})

    assert summary["required_producer_recall"] == 0.0
    assert summary["all_required_found_rate"] == 0.0
    assert summary["closure_complete_rate"] == 1.0
    assert summary["dependency_closure_complete_rate"] == 0.0
