"""0.25 graphify/Planflow public contract tests."""

from __future__ import annotations

from dataclasses import asdict

from graph_tool_call import __version__
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import (
    COLLECTION_GRAPH_VERSION,
    build_io_contract,
    derive_plan_trace_edges,
    expand_candidates_with_producers,
    merge_graph_edges,
    normalize_graph_edge,
    retrieve_graphify,
)
from graph_tool_call.ontology.schema import RelationType
from graph_tool_call.plan import (
    PathSynthesizer,
    Plan,
    PlanRunner,
    PlanStep,
    PlanSynthesisError,
)
from graph_tool_call.tool_graph import ToolGraph


def test_graphify_public_contract_imports():
    assert COLLECTION_GRAPH_VERSION == "2"
    assert callable(build_io_contract)
    assert callable(expand_candidates_with_producers)
    assert callable(normalize_graph_edge)
    assert callable(merge_graph_edges)
    assert callable(derive_plan_trace_edges)
    assert callable(retrieve_graphify)


def test_build_io_contract_preserves_kind_required_enum_and_semantics():
    response_schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"goodsNo": {"type": "string"}},
                },
            }
        },
    }
    request_body_schema = {
        "type": "object",
        "properties": {
            "quantity": {"type": "integer"},
            "status": {"type": "string", "enum": ["open", "closed"]},
        },
        "required": ["quantity"],
    }
    parameters = [
        {"name": "goodsNo", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "siteNo", "in": "query", "schema": {"type": "string"}},
        {"name": "pageNo", "in": "query", "required": True, "schema": {"type": "integer"}},
        {"name": "Authorization", "in": "header", "required": True, "schema": {"type": "string"}},
    ]
    tool_metadata = {
        "ai_metadata": {
            "produces_semantics": [{"semantic": "product_id", "json_path": "$.items[*].goodsNo"}],
            "consumes_semantics": [
                {"semantic": "product_id", "field": "goodsNo", "kind": "data"},
                {"semantic": "site_id", "field": "siteNo", "kind": "context"},
            ],
        }
    }

    produces, consumes = build_io_contract(
        response_schema=response_schema,
        request_body_schema=request_body_schema,
        parameters=parameters,
        context_field_names={"siteNo"},
        auth_field_names={"Authorization"},
        paging_field_names={"pageNo"},
        tool_metadata=tool_metadata,
    )

    by_produce = {p["field_name"]: p for p in produces}
    by_consume = {c["field_name"]: c for c in consumes}
    assert by_produce["goodsNo"]["semantic_tag"] == "product_id"
    assert by_consume["goodsNo"]["required"] is True
    assert by_consume["goodsNo"]["kind"] == "data"
    assert by_consume["goodsNo"]["semantic_tag"] == "product_id"
    assert by_consume["quantity"]["required"] is True
    assert by_consume["status"]["enum"] == ["open", "closed"]
    assert by_consume["siteNo"]["kind"] == "context"
    assert by_consume["siteNo"]["required"] is False
    assert by_consume["pageNo"]["kind"] == "context"
    assert by_consume["pageNo"]["required"] is False
    assert by_consume["Authorization"]["kind"] == "auth"
    assert by_consume["Authorization"]["required"] is False


def test_expand_candidates_with_producers_uses_required_data_only_and_action_priority():
    tools = {
        "getProductDetail": {
            "metadata": {
                "consumes": [
                    {"field_name": "goodsNo", "semantic_tag": "product_id", "required": True},
                    {"field_name": "siteNo", "kind": "context", "required": True},
                ]
            }
        },
        "searchProduct": {
            "metadata": {
                "produces": [{"field_name": "goodsNo", "semantic_tag": "product_id"}],
                "ai_metadata": {"canonical_action": "search"},
            }
        },
        "readProduct": {
            "metadata": {
                "produces": [{"field_name": "goodsNo", "semantic_tag": "product_id"}],
                "ai_metadata": {"canonical_action": "read"},
            }
        },
        "getSite": {"metadata": {"produces": [{"field_name": "siteNo"}]}},
    }

    expanded = expand_candidates_with_producers(
        ["getProductDetail"],
        tools,
        max_producers_per_field=2,
    )

    assert expanded == ["getProductDetail", "searchProduct", "readProduct"]


def test_edge_normalize_merge_and_trace_derivation_contract():
    structural = normalize_graph_edge(
        {
            "source": "searchProduct",
            "target": "getProductDetail",
            "relation": "requires",
            "confidence": "EXTRACTED",
            "conf_score": 0.9,
            "evidence": "schema field match",
        }
    )
    run = normalize_graph_edge(
        {
            "source": "searchProduct",
            "target": "getProductDetail",
            "relation": "requires",
            "confidence": "INFERRED",
            "conf_score": 0.5,
            "evidence_sources": ["run"],
            "data_flow": {"from_path": "items[0].goodsNo", "to_field": "goodsNo"},
        }
    )
    merged = merge_graph_edges(structural, run)
    assert merged["kind"] == "data"
    assert merged["evidence_sources"] == ["structural", "run"]
    assert merged["conf_score"] > 0.9

    plan = Plan(
        id="p1",
        goal="detail",
        steps=[
            PlanStep(id="s1", tool="searchProduct", args={"keyword": "셔츠"}),
            PlanStep(id="s2", tool="getProductDetail", args={"goodsNo": "${s1.items[0].goodsNo}"}),
        ],
    )
    trace_edges = derive_plan_trace_edges(plan)
    assert trace_edges == [
        {
            "source": "searchProduct",
            "target": "getProductDetail",
            "relation": "requires",
            "weight": 1.0,
            "confidence": "INFERRED",
            "conf_score": 0.5,
            "layer": 5,
            "evidence": "run-observed data flow: s1.items[0].goodsNo -> goodsNo",
            "kind": "data",
            "evidence_sources": ["run"],
            "data_flow": {
                "from_path": "items[0].goodsNo",
                "to_field": "goodsNo",
                "observed_count": 1,
            },
            "is_manual": False,
            "deleted_by_user": False,
        }
    ]


def test_retrieve_graphify_evidence_contract():
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="searchProduct", description="상품 검색"))
    tg.add_tool(ToolSchema(name="readOpaque", description=""))
    tg.add_relation(
        "searchProduct",
        "readOpaque",
        RelationType.PRECEDES,
        confidence="EXTRACTED",
        conf_score=0.95,
        evidence="search result supplies goodsNo",
    )

    result = retrieve_graphify(tg, "상품 검색", top_k=2, include_evidence=True)
    by_name = {row["name"]: row for row in result["results"]}

    assert "searchProduct" in by_name
    assert "readOpaque" in by_name
    assert by_name["searchProduct"]["score_breakdown"]["seed"] > 0
    assert by_name["readOpaque"]["expanded_from"] == "searchProduct"
    assert by_name["readOpaque"]["edge_evidence"][0]["evidence"] == (
        "search result supplies goodsNo"
    )
    assert result["stats"]["token_budget_used"] >= 0


def test_retrieve_with_scores_indexes_ai_metadata_and_io_contract_terms():
    tg = ToolGraph()
    tg.add_tool(
        ToolSchema(
            name="opaque001",
            description="",
            metadata={
                "ai_metadata": {
                    "one_line_summary": "상품 상세 조회",
                    "when_to_use": "상품 번호로 상품 상세 정보를 확인할 때 사용",
                    "canonical_action": "read",
                    "primary_resource": "product",
                },
                "consumes": [
                    {
                        "field_name": "goodsNo",
                        "semantic_tag": "product_id",
                        "kind": "data",
                        "required": True,
                    }
                ],
                "produces": [{"field_name": "goodsNm", "semantic_tag": "product_name"}],
            },
        )
    )
    tg.add_tool(ToolSchema(name="opaque002", description="주문 취소"))

    results = tg.retrieve_with_scores("상품 상세 조회", top_k=1)

    assert results[0].tool.name == "opaque001"
    assert results[0].keyword_score > 0


def test_plan_synthesis_diagnostics_and_runner_event_metadata():
    graph = {
        "tools": {
            "searchProduct": {
                "metadata": {
                    "consumes": [{"field_name": "keyword", "kind": "data", "required": True}],
                    "produces": [
                        {
                            "field_name": "goodsNo",
                            "json_path": "$.items[*].goodsNo",
                            "semantic_tag": "product_id",
                        }
                    ],
                    "ai_metadata": {"canonical_action": "search"},
                }
            },
            "getProductDetail": {
                "metadata": {
                    "consumes": [
                        {
                            "field_name": "goodsNo",
                            "semantic_tag": "product_id",
                            "kind": "data",
                            "required": True,
                        }
                    ],
                    "produces": [],
                    "ai_metadata": {"canonical_action": "read"},
                }
            },
        }
    }
    synthesizer = PathSynthesizer(graph)
    plan = synthesizer.synthesize(target="getProductDetail", entities={})
    synthesis = plan.metadata["synthesis"]
    assert synthesis["selected_producers"][0]["producer"] == "searchProduct"
    assert synthesis["fallbacks"][0]["reason"] == "user_input_fallback"
    assert "getProductDetail.goodsNo" in synthesis["candidate_signals"]

    try:
        synthesizer.synthesize(target="ghostTool")
    except PlanSynthesisError as exc:
        diagnostic = exc.to_dict()
    else:  # pragma: no cover
        raise AssertionError("expected PlanSynthesisError")
    assert diagnostic["stage"] == "synthesize"
    assert diagnostic["reason"] == "unknown_target"
    assert diagnostic["target"] == "ghostTool"

    runner = PlanRunner(lambda name, args: {"ok": True, "args": args})
    events = [
        asdict(event)
        for event in runner.run_stream(
            Plan(id="p1", goal="g", steps=[PlanStep(id="s1", tool="x")]),
            trace_metadata={"collection_id": "c1"},
        )
    ]
    assert events[0]["stage"] == "runner"
    assert events[0]["graph_tool_call_version"] == __version__
    assert events[1]["plan_id"] == "p1"
    assert events[1]["trace_metadata"] == {"collection_id": "c1"}
