from __future__ import annotations

import pytest

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.semantic_scorer import (
    compute_semantic_scores,
    infer_query_action,
    infer_query_result_shape,
    semantic_rank_multiplier,
)


def _tool(
    name: str,
    *,
    description: str,
    action: str,
    resource: str,
    shape: str,
) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=description,
        metadata={
            "ai_metadata": {
                "canonical_action": action,
                "primary_resource": resource,
                "result_shape": shape,
            },
            "openapi": {"path_module": f"/api/{resource}"},
        },
    )


@pytest.mark.parametrize(
    ("query", "shape", "action"),
    [
        ("이벤트 목록을 보여줘", "list", "search"),
        ("show patient details", "single", "read"),
        ("invoice count", "count", ""),
        ("문서를 삭제해줘", "mutation", "delete"),
        ("account information", "single", "read"),
    ],
)
def test_query_semantics_are_domain_independent(query, shape, action):
    assert infer_query_result_shape(query) == shape
    assert infer_query_action(query) == action


def test_korean_list_query_prefers_list_shape_among_event_siblings():
    tg = ToolGraph()
    tg.add_tool(
        _tool(
            "getEventStatus",
            description="이벤트 조회",
            action="read",
            resource="event",
            shape="single",
        )
    )
    tg.add_tool(
        _tool(
            "getEventList",
            description="이벤트 조회",
            action="search",
            resource="event",
            shape="list",
        )
    )

    results = tg.retrieve_with_scores("이벤트 목록 조회", top_k=2)

    assert [row.tool.name for row in results] == ["getEventList", "getEventStatus"]
    assert results[0].semantic_score > results[1].semantic_score


def test_count_query_prefers_count_shape_in_healthcare_catalog():
    count_tool = _tool(
        "countPatients",
        description="Patient statistics",
        action="read",
        resource="patient",
        shape="count",
    )
    list_tool = _tool(
        "listPatients",
        description="Patient statistics",
        action="search",
        resource="patient",
        shape="list",
    )

    count_multiplier, _ = semantic_rank_multiplier(count_tool, "patient count")
    list_multiplier, _ = semantic_rank_multiplier(list_tool, "patient count")

    assert count_multiplier > list_multiplier


def test_ambiguous_query_does_not_invent_shape_or_action_preference():
    list_tool = _tool(
        "listFiles",
        description="File operations",
        action="search",
        resource="file",
        shape="list",
    )
    detail_tool = _tool(
        "getFile",
        description="File operations",
        action="read",
        resource="file",
        shape="single",
    )

    list_multiplier, list_evidence = semantic_rank_multiplier(list_tool, "file")
    detail_multiplier, detail_evidence = semantic_rank_multiplier(detail_tool, "file")

    assert list_evidence["query_result_shape"] == ""
    assert detail_evidence["query_action"] == ""
    assert list_multiplier == detail_multiplier


def test_structured_semantic_channel_prefers_matching_summary_and_shape():
    target = _tool(
        "listEvents",
        description="이벤트 관리 목록 조회",
        action="search",
        resource="event",
        shape="list",
    )
    sibling = _tool(
        "checkEvent",
        description="이벤트 진행 상태 확인",
        action="read",
        resource="event",
        shape="single",
    )

    scores = compute_semantic_scores(
        "진행 중인 이벤트 목록을 조회해줘",
        {target.name: target, sibling.name: sibling},
    )

    assert scores[target.name] > scores[sibling.name]


def test_structured_semantic_channel_is_not_domain_specific():
    count_tool = _tool(
        "countInvoices",
        description="Invoice count",
        action="read",
        resource="invoice",
        shape="count",
    )
    list_tool = _tool(
        "listInvoices",
        description="Invoice list",
        action="search",
        resource="invoice",
        shape="list",
    )

    scores = compute_semantic_scores(
        "invoice count",
        {count_tool.name: count_tool, list_tool.name: list_tool},
    )

    assert scores[count_tool.name] > scores[list_tool.name]
