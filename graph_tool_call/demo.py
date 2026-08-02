"""Dependency-free, reproducible public demonstrations."""

from __future__ import annotations

import json
import math
from typing import Any

from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.graphify import assemble_tool_bundle, select_target_candidate
from graph_tool_call.tool_graph import ToolGraph

DEPENDENCY_CHAIN_QUERY = "Refund the order for alice@example.com"


def run_dependency_chain_demo(query: str = DEPENDENCY_CHAIN_QUERY) -> dict[str, Any]:
    """Run the launch demo through retrieval, selection, and contract closure."""

    tools = _dependency_chain_tools()
    graph = ToolGraph()
    graph.add_tools(tools)
    retrieval = graph.retrieve_with_scores(query, top_k=5)
    retrieval_rows = [
        {
            "name": row.tool.name,
            "score": round(float(row.score), 6),
            "rank": index,
        }
        for index, row in enumerate(retrieval, 1)
    ]
    candidate_names = [row["name"] for row in retrieval_rows]
    tool_index = {tool.name: tool for tool in tools}
    selector = select_target_candidate(
        query,
        candidate_names,
        tool_index,
        retrieval_results=retrieval_rows,
    )
    target = str(selector["selected_target"])
    bundle = assemble_tool_bundle(
        query,
        target,
        tool_index,
        available_fields={"email"},
    )
    execution_order = [*reversed(bundle.required_tools), target]
    full_catalog_tokens = _estimate_catalog_tokens(tools)
    admitted_tokens = int(bundle.token_budget["used"])
    reduction = 1 - (admitted_tokens / full_catalog_tokens)
    return {
        "scenario": "dependency-chain",
        "query": query,
        "catalog_tool_count": len(tools),
        "retrieved_candidates": candidate_names,
        "target": target,
        "target_confidence": selector["confidence"],
        "target_reason_codes": list(selector["reason_codes"]),
        "required_producers": list(bundle.required_tools),
        "execution_order": execution_order,
        "dependency_evidence": list(bundle.closure["evidence"]),
        "closure_status": bundle.closure_status,
        "context": {
            "accounting": bundle.token_budget["accounting"],
            "full_catalog_estimated_tokens": full_catalog_tokens,
            "admitted_estimated_tokens": admitted_tokens,
            "estimated_reduction": round(reduction, 4),
        },
    }


def render_dependency_chain_demo(result: dict[str, Any]) -> str:
    """Render a compact terminal explanation from :func:`run_dependency_chain_demo`."""

    producer = str((result.get("required_producers") or ["none"])[0])
    evidence = (result.get("dependency_evidence") or [{}])[0]
    field_key = str(evidence.get("field_key") or "required input")
    sources = ", ".join(str(value) for value in evidence.get("sources") or []) or "contract"
    context = result["context"]
    reduction = round(float(context["estimated_reduction"]) * 100)
    lines = [
        "graph-tool-call dependency-chain demo",
        "",
        f'Query: "{result["query"]}"',
        "",
        "Selected target:",
        f"  {result['target']}({field_key})",
        "",
        "Required producer:",
        f"  {producer}(email) -> {field_key}",
        f"  evidence: {sources}",
        "",
        "Execution order:",
    ]
    lines.extend(f"  {index}. {name}" for index, name in enumerate(result["execution_order"], 1))
    lines.extend(
        [
            "",
            "Planner context:",
            f"  {result['catalog_tool_count']} catalog tools -> "
            f"{len(result['execution_order'])} required tools",
            f"  estimated tokens: {context['full_catalog_estimated_tokens']} -> "
            f"{context['admitted_estimated_tokens']} ({reduction}% fewer)",
        ]
    )
    return "\n".join(lines)


def _dependency_chain_tools() -> list[ToolSchema]:
    return [
        _tool(
            "refundOrder",
            "Refund an existing customer order after its order ID has been resolved.",
            action="action",
            method="POST",
            resource="refund",
            consumes=[_field("orderId", "order_id", required=True)],
            parameters=[
                ToolParameter(
                    "orderId",
                    description="Order ID returned by an order lookup.",
                    required=True,
                )
            ],
        ),
        _tool(
            "findOrdersByEmail",
            "Find customer orders by email and return matching order IDs.",
            action="search",
            method="GET",
            resource="order",
            consumes=[_field("email", "email", required=True)],
            produces=[
                _field(
                    "orderId",
                    "order_id",
                    evidence_sources=["api_contract", "openapi_link"],
                )
            ],
            parameters=[
                ToolParameter(
                    "email",
                    description="Customer email used to find orders.",
                    required=True,
                )
            ],
        ),
        _tool(
            "getOrderDetail",
            "Read one order by its order ID.",
            action="read",
            method="GET",
            resource="order",
            consumes=[_field("orderId", "order_id", required=True)],
            produces=[_field("paymentId", "payment_id")],
        ),
        _tool(
            "cancelOrder",
            "Cancel an existing order by order ID.",
            action="action",
            method="POST",
            resource="order",
            consumes=[_field("orderId", "order_id", required=True)],
        ),
        _tool(
            "listRefundReasons",
            "List the supported refund reason codes.",
            action="search",
            method="GET",
            resource="refund_reason",
            produces=[_field("reasonCode", "reason_code")],
        ),
        _tool(
            "createSupportTicket",
            "Create a customer support ticket.",
            action="create",
            method="POST",
            resource="support_ticket",
            consumes=[_field("message", "message", required=True)],
        ),
    ]


def _tool(
    name: str,
    description: str,
    *,
    action: str,
    method: str,
    resource: str,
    consumes: list[dict[str, Any]] | None = None,
    produces: list[dict[str, Any]] | None = None,
    parameters: list[ToolParameter] | None = None,
) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=description,
        parameters=parameters or [],
        metadata={
            "ai_metadata": {
                "canonical_action": action,
                "primary_resource": resource,
                "one_line_summary": description,
            },
            "openapi": {"method": method, "summary": description},
            "consumes": consumes or [],
            "produces": produces or [],
        },
    )


def _field(
    name: str,
    semantic_tag: str,
    *,
    required: bool = False,
    evidence_sources: list[str] | None = None,
) -> dict[str, Any]:
    row = {
        "field_name": name,
        "semantic_tag": semantic_tag,
        "field_type": "string",
        "required": required,
        "kind": "data",
        "contract_source": "api_contract",
    }
    if evidence_sources:
        row["evidence_sources"] = list(evidence_sources)
    return row


def _estimate_catalog_tokens(tools: list[ToolSchema]) -> int:
    payload = [tool.to_dict() for tool in tools]
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return math.ceil(len(serialized.encode("utf-8")) / 3)
