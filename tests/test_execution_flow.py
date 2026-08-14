from __future__ import annotations

import json

from graph_tool_call.graphify import (
    EXECUTION_FLOW_SCHEMA_VERSION,
    classify_execution_edge,
    derive_execution_flow,
)
from graph_tool_call.learning import build_trace_learning_record


def _plan() -> dict:
    return {
        "id": "plan-1",
        "goal": "Cancel the selected order",
        "steps": [
            {
                "id": "s1",
                "tool": "listOrders",
                "args": {"Authorization": "Bearer should-not-survive"},
                "rationale": "Find the order",
            },
            {
                "id": "s2",
                "tool": "cancelOrder",
                "args": {"orderId": "${s1.items[0].orderId}"},
                "depends_on": ["s1"],
                "rationale": "Cancel it",
            },
        ],
    }


def test_data_flow_requires_is_producer_to_consumer() -> None:
    edge = classify_execution_edge(
        {
            "source": "listOrders",
            "target": "cancelOrder",
            "relation": "requires",
            "kind": "data",
            "conf_score": 0.9,
            "evidence_sources": ["api_contract"],
        },
        selected_tool="cancelOrder",
    )

    assert edge["direction"] == "source_to_target"
    assert edge["role"] == "predecessor"
    assert edge["counterpart"] == "listOrders"
    assert edge["evidence_type"] == "contract"


def test_structural_requires_is_consumer_to_prerequisite() -> None:
    edge = classify_execution_edge(
        {
            "source": "createRefund",
            "target": "getOrderDetail",
            "relation": "requires",
            "evidence_sources": ["structural"],
        },
        selected_tool="createRefund",
    )

    assert edge["direction"] == "target_to_source"
    assert edge["role"] == "predecessor"
    assert edge["counterpart"] == "getOrderDetail"


def test_semantic_pair_stays_unordered() -> None:
    edge = classify_execution_edge(
        {
            "source": "getOrder",
            "target": "getCustomer",
            "relation": "pairs_well_with",
            "evidence_sources": ["llm_curated"],
        },
        selected_tool="getOrder",
    )

    assert edge["direction"] == "undirected"
    assert edge["ordered"] is False
    assert edge["role"] == "related"


def test_observed_plan_flow_keeps_only_structural_binding_evidence() -> None:
    events = [
        {"type": "step.completed", "step_id": "s1", "duration_ms": 120},
        {"type": "step.completed", "step_id": "s2", "duration_ms": 210},
        {"type": "plan.completed", "plan_id": "plan-1", "output": {"token": "secret"}},
    ]

    flow = derive_execution_flow(plan=_plan(), runner_events=events)
    serialized = json.dumps(flow)

    assert flow["schema_version"] == EXECUTION_FLOW_SCHEMA_VERSION
    assert flow["mode"] == "observed"
    assert flow["status"] == "completed"
    assert [step["status"] for step in flow["steps"]] == ["completed", "completed"]
    assert [step["duration_ms"] for step in flow["steps"]] == [120, 210]
    assert flow["steps"][1]["bindings"] == [
        {
            "field": "orderId",
            "kind": "binding",
            "source_step": "s1",
            "source_tool": None,
            "path": "items[0].orderId",
        }
    ]
    assert flow["transitions"] == [
        {
            "source_step": "s1",
            "target_step": "s2",
            "source_tool": "listOrders",
            "target_tool": "cancelOrder",
            "relation": "data_flow",
            "evidence_type": "observed",
            "field": "orderId",
            "path": "items[0].orderId",
        }
    ]
    assert "should-not-survive" not in serialized
    assert "secret" not in serialized


def test_inferred_candidates_separate_ordered_related_and_conflicting_edges() -> None:
    flow = derive_execution_flow(
        selected_tool="cancelOrder",
        graph_edges=[
            {
                "source": "listOrders",
                "target": "cancelOrder",
                "relation": "requires",
                "evidence_sources": ["run"],
                "data_flow": {
                    "observed_count": 3,
                    "to_field": "orderId",
                    "sample_value": "customer-secret-value",
                },
            },
            {
                "source": "cancelOrder",
                "target": "getOrder",
                "relation": "precedes",
                "evidence_sources": ["api_contract"],
            },
            {
                "source": "cancelOrder",
                "target": "refundOrder",
                "relation": "pairs_well_with",
                "evidence_sources": ["manual"],
            },
            {
                "source": "lookupCustomer",
                "target": "cancelOrder",
                "relation": "requires",
                "evidence_sources": ["structural"],
                "execution_direction": "source_to_target",
            },
            {
                "source": "cancelOrder",
                "target": "lookupCustomer",
                "relation": "precedes",
                "evidence_sources": ["structural"],
            },
        ],
    )

    assert flow["mode"] == "inferred"
    assert [row["tool"] for row in flow["candidates"]["predecessors"]] == ["listOrders"]
    assert flow["candidates"]["predecessors"][0]["evidence_type"] == "observed"
    assert "customer-secret-value" not in json.dumps(flow)
    assert [row["tool"] for row in flow["candidates"]["successors"]] == ["getOrder"]
    assert [row["tool"] for row in flow["candidates"]["related"]] == ["refundOrder"]
    assert flow["candidates"]["ambiguous"][0]["tool"] == "lookupCustomer"
    assert flow["diagnostics"] == ["ambiguous_graph_direction"]


def test_learning_record_can_persist_compact_execution_flow() -> None:
    flow = derive_execution_flow(plan=_plan())
    record = build_trace_learning_record(
        query="cancel my order",
        selected_target="cancelOrder",
        plan=_plan(),
        execution_flow=flow,
        success=True,
    )

    assert record["execution_flow"]["mode"] == "planned"
    assert record["execution_flow"]["steps"][1]["tool"] == "cancelOrder"
    assert "should-not-survive" not in json.dumps(record)
