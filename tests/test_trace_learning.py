from __future__ import annotations

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import (
    derive_plan_trace_edges,
    retrieve_graphify,
    select_target_candidate,
)
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    scrub_trace_payload,
)
from graph_tool_call.tool_graph import ToolGraph


def _plan() -> dict:
    return {
        "id": "p1",
        "steps": [
            {"id": "s1", "tool": "searchGoods", "args": {"keyword": "셔츠"}},
            {"id": "s2", "tool": "getGoodsDetail", "args": {"goodsNo": "${s1.items[0].goodsNo}"}},
        ],
    }


def test_scrub_trace_payload_redacts_secrets_and_raw_body():
    payload = {
        "Authorization": "Bearer abc.def.ghi",
        "cookie": "SESSION=secret",
        "user_id": "son@example.com",
        "phone": "010-1234-5678",
        "request_body": {"name": "raw should not be stored"},
        "safe": "상품 조회",
    }

    clean = scrub_trace_payload(payload)

    assert clean["Authorization"] == "[REDACTED]"
    assert clean["cookie"] == "[REDACTED]"
    assert clean["user_id"] == "[REDACTED]"
    assert clean["request_body"] == "[REDACTED]"
    assert clean["phone"] == "[REDACTED_PHONE]"
    assert clean["safe"] == "상품 조회"


def test_derive_learning_suggestions_from_successful_plan_trace():
    trace_edges = derive_plan_trace_edges(_plan(), [{"id": "s1"}, {"id": "s2"}])
    record = build_trace_learning_record(
        query="셔츠 상세 조회",
        collection_id="c1",
        session_id="user-session-1",
        selected_target="getGoodsDetail",
        llm_target="getGeneralGoodsInfo",
        plan=_plan(),
        success=True,
        target_selector={"selected_target": "getGoodsDetail", "raw_body": {"secret": "x"}},
        trace_edges=trace_edges,
        created_at="2026-07-23T00:00:00+00:00",
    )

    suggestions = derive_learning_suggestions(record)
    by_type = {row["type"]: row for row in suggestions}

    assert record["session_id_hash"] != "user-session-1"
    assert by_type["target_preference"]["target"] == "getGoodsDetail"
    assert by_type["plan_path"]["plan_tools"] == ["searchGoods", "getGoodsDetail"]
    assert by_type["data_flow_edge"]["edge"]["data_flow"]["to_field"] == "goodsNo"
    assert by_type["target_preference"]["status"] == "suggested"


def test_failure_chain_requires_repeated_success_before_promotable():
    failures = [
        build_trace_learning_record(
            query="셔츠 상세 조회",
            collection_id="c1",
            selected_target="getGeneralGoodsInfo",
            failure_reason="http_4xx",
            success=False,
            created_at="2026-07-23T00:00:00+00:00",
        ),
        build_trace_learning_record(
            query="셔츠 상세 조회",
            collection_id="c1",
            selected_target="getGoodsList",
            failure_reason="llm_target_mismatch",
            success=False,
            created_at="2026-07-23T00:01:00+00:00",
        ),
    ]
    first_success = build_trace_learning_record(
        query="셔츠 상세 조회",
        collection_id="c1",
        selected_target="getGoodsDetail",
        plan=_plan(),
        success=True,
        created_at="2026-07-23T00:02:00+00:00",
    )

    first = derive_learning_suggestions(first_success, history=failures)
    target_first = next(row for row in first if row["type"] == "target_preference")
    assert target_first["status"] == "suggested"
    assert target_first["prior_failure_count"] == 2

    second_success = build_trace_learning_record(
        query="셔츠 상세 조회",
        collection_id="c1",
        selected_target="getGoodsDetail",
        plan=_plan(),
        success=True,
        created_at="2026-07-23T00:03:00+00:00",
    )
    second = derive_learning_suggestions(
        second_success,
        history=[*failures, first_success],
        existing_suggestions=first,
    )
    target_second = next(row for row in second if row["type"] == "target_preference")

    assert target_second["status"] == "promotable"
    assert target_second["observations"] == 2


def test_promoted_target_preference_adds_selector_learning_evidence():
    record = build_trace_learning_record(
        query="셔츠 상세 조회",
        collection_id="c1",
        selected_target="getGoodsDetail",
        plan=_plan(),
        success=True,
        created_at="2026-07-23T00:00:00+00:00",
    )
    suggestion = next(
        row for row in derive_learning_suggestions(record) if row["type"] == "target_preference"
    )
    suggestion["status"] = "promoted"

    tools = {
        "getGeneralGoodsInfo": {
            "metadata": {"ai_metadata": {"canonical_action": "read", "result_shape": "single"}}
        },
        "getGoodsDetail": {
            "metadata": {"ai_metadata": {"canonical_action": "read", "result_shape": "single"}}
        },
    }

    result = select_target_candidate(
        "셔츠 상세 조회",
        [
            {"name": "getGeneralGoodsInfo", "score": 0.02},
            {"name": "getGoodsDetail", "score": 0.019},
        ],
        tools,
        llm_target="getGeneralGoodsInfo",
        learning_suggestions=[suggestion],
    )
    learned = next(row for row in result["rank_signals"] if row["name"] == "getGoodsDetail")

    assert result["learning_applied"] is True
    assert any(row["source"] == "learning" for row in learned["evidence"])


def test_apply_learning_suggestions_can_run_in_shadow_mode():
    record = build_trace_learning_record(
        query="셔츠 상세 조회",
        collection_id="c1",
        selected_target="getGoodsDetail",
        success=True,
    )
    suggestion = next(
        row for row in derive_learning_suggestions(record) if row["type"] == "target_preference"
    )

    shadow = apply_learning_suggestions(
        "셔츠 상세 조회",
        [{"name": "getGoodsDetail", "score": 0.01}],
        [suggestion],
        mode="shadow",
    )

    assert shadow["applied_count"] == 1
    assert shadow["candidates"][0]["score"] > 0.01


def test_retrieve_graphify_reports_promoted_learning_evidence():
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="getGeneralGoodsInfo", description="셔츠 상세 조회 일반 정보"))
    tg.add_tool(ToolSchema(name="getGoodsDetail", description="상품 상세"))
    record = build_trace_learning_record(
        query="셔츠 상세 조회",
        collection_id="c1",
        selected_target="getGoodsDetail",
        success=True,
    )
    suggestion = next(
        row for row in derive_learning_suggestions(record) if row["type"] == "target_preference"
    )
    suggestion["status"] = "promoted"

    result = retrieve_graphify(
        tg,
        "셔츠 상세 조회",
        top_k=2,
        include_evidence=True,
        learning_suggestions=[suggestion],
    )
    learned = next(row for row in result["results"] if row["name"] == "getGoodsDetail")

    assert result["stats"]["learning_applied"] is True
    assert learned["score_breakdown"]["learning"] > 0
    assert learned["learning_evidence"]["source"] == "learning"
