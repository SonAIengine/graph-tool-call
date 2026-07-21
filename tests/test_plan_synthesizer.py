"""Unit tests for ``graph_tool_call.plan.synthesizer``.

핵심 합성 시나리오 + Cycle/F2 fallback 의 user_input placeholder 출력.
"""

from __future__ import annotations

import pytest

from graph_tool_call.plan import PlanRunner
from graph_tool_call.plan.synthesizer import (
    PathSynthesizer,
    PlanSynthesisError,
    _normalize_field_name,
)


def _basic_graph() -> dict:
    """포함:
    - 'searchProduct': 입력=keyword, 출력=goodsNo (semantic=goods.id)
    - 'getProductDetail': 입력=goodsNo (semantic=goods.id) → 의존
    """
    return {
        "tools": {
            "searchProduct": {
                "metadata": {
                    "method": "GET",
                    "path": "/api/v1/products",
                    "consumes": [{"field_name": "keyword", "kind": "data", "required": True}],
                    "produces": [
                        {
                            "field_name": "goodsNo",
                            "json_path": "$.body.items[*].goodsNo",
                            "semantic_tag": "goods.id",
                        }
                    ],
                    "ai_metadata": {
                        "canonical_action": "search",
                        "primary_resource": "product",
                    },
                },
            },
            "getProductDetail": {
                "metadata": {
                    "method": "GET",
                    "path": "/api/v1/products/{goodsNo}",
                    "consumes": [
                        {
                            "field_name": "goodsNo",
                            "semantic_tag": "goods.id",
                            "kind": "data",
                            "required": True,
                        }
                    ],
                    "produces": [{"field_name": "name", "json_path": "$.body.name"}],
                    "ai_metadata": {
                        "canonical_action": "read",
                        "primary_resource": "product",
                    },
                },
            },
        },
    }


# ─── normalize_field_name ──


def test_normalize_field_name_collapses_separators():
    assert _normalize_field_name("ord_no") == "ordno"
    assert _normalize_field_name("ORD-NO") == "ordno"
    assert _normalize_field_name("ordNo") == "ordno"


def test_normalize_field_name_keeps_token_roots_distinct():
    """ord ≠ order — token-level synonym mapping은 안 함."""
    assert _normalize_field_name("ordNo") != _normalize_field_name("orderNo")


def test_normalize_field_name_empty():
    assert _normalize_field_name("") == ""
    assert _normalize_field_name(None) == ""  # type: ignore[arg-type]


# ─── synthesizer 핵심 동작 ──


def test_synthesize_uses_entity_when_available():
    """user 가 keyword 를 entity 로 줬으면 검색 step 1개로 끝나야."""
    syn = PathSynthesizer(_basic_graph())
    plan = syn.synthesize(target="searchProduct", entities={"keyword": "shoes"})
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "searchProduct"
    assert plan.steps[0].args == {"keyword": "shoes"}


def test_synthesize_chains_producer_when_entity_missing():
    """getProductDetail 호출하려면 goodsNo 가 필요 — searchProduct 가 producer.

    keyword 만 entity 로 주면 chain: searchProduct → getProductDetail.
    합성 후 step 이름은 ``s1``/``s2`` 로 정렬되고, binding 도 그에 맞게 rewrite 됨.
    """
    syn = PathSynthesizer(_basic_graph())
    plan = syn.synthesize(
        target="getProductDetail",
        entities={"keyword": "shoes"},
    )
    assert len(plan.steps) == 2, "검색 + 상세조회 2-step chain"
    assert plan.steps[0].tool == "searchProduct"
    assert plan.steps[1].tool == "getProductDetail"
    binding = plan.steps[1].args.get("goodsNo", "")
    # step_id 순서 정렬 후 binding 은 ${s1...} 로 rewrite — 첫 step 의 출력 가리킴
    assert binding.startswith("${"), "binding placeholder 형식이어야"
    assert "s1" in binding, f"첫 step (s1) 출력 binding 이어야, got {binding}"
    assert "goodsNo" in binding, "produces 필드 경로 포함"


def test_synthesize_prefers_body_view_binding_for_response_envelope_producer():
    graph = {
        "tools": {
            "searchProducts": {
                "metadata": {
                    "consumes": [{"field_name": "keyword", "kind": "data", "required": True}],
                    "produces": [
                        {
                            "field_name": "goodsNo",
                            "json_path": "$.data.items[*].goodsNo",
                            "semantic_tag": "goods.id",
                            "response_envelope_path": "$.data",
                            "response_collection_path": "$.data.items[*]",
                            "response_item_path": "$.data.items[*]",
                        }
                    ],
                    "ai_metadata": {"canonical_action": "search"},
                },
            },
            "getProductDetail": {
                "metadata": {
                    "consumes": [
                        {
                            "field_name": "goodsNo",
                            "semantic_tag": "goods.id",
                            "kind": "data",
                            "required": True,
                        }
                    ],
                    "produces": [{"field_name": "goodsNm", "json_path": "$.body.goodsNm"}],
                    "ai_metadata": {"canonical_action": "read"},
                },
            },
        }
    }
    plan = PathSynthesizer(graph).synthesize(
        target="getProductDetail",
        entities={"keyword": "셔츠"},
    )

    assert [step.tool for step in plan.steps] == ["searchProducts", "getProductDetail"]
    assert plan.steps[1].args["goodsNo"] == "${s1.body_view.value[0].goodsNo}"

    def call_tool(name, args):
        if name == "searchProducts":
            return {
                "body": {
                    "code": "OK",
                    "data": {"items": [{"goodsNo": "G-1", "goodsNm": "Shirt"}]},
                },
                "body_view": {
                    "mode": "collection",
                    "source_path": "$.data.items[*]",
                    "value": [{"goodsNo": "G-1", "goodsNm": "Shirt"}],
                },
            }
        return {"args": args}

    trace = PlanRunner(call_tool).run(plan)

    assert trace.success is True
    assert trace.steps[1].args_resolved == {"goodsNo": "G-1"}
    assert trace.output == {"args": {"goodsNo": "G-1"}}


def test_synthesize_falls_back_to_user_input_placeholder():
    """필수 field 인데 entity 도 없고 producer 도 없으면 ``${user_input.X}`` 로 fallback.

    F2 + Cycle policy B 의 핵심 동작 — abort 대신 caller 에게 슬롯을 surface.
    runner 가 input_context 에 ``user_input`` 별칭으로 등록하므로
    plan 자체는 합성되고, 실행 시 caller 가 값을 공급하면 작동한다.
    """
    g = {
        "tools": {
            "needsX": {
                "metadata": {
                    "consumes": [{"field_name": "mysteryField", "kind": "data", "required": True}],
                    "produces": [],
                    "ai_metadata": {"canonical_action": "read"},
                },
            },
        },
    }
    syn = PathSynthesizer(g)
    plan = syn.synthesize(target="needsX", entities={})
    assert len(plan.steps) == 1
    assert plan.steps[0].args == {"mysteryField": "${user_input.mysteryField}"}


def test_user_input_slots_preserve_required_contract_metadata():
    g = {
        "tools": {
            "searchMembers": {
                "metadata": {
                    "consumes": [
                        {
                            "field_name": "loginId",
                            "field_type": "string",
                            "kind": "data",
                            "required": True,
                            "location": "query",
                            "json_path": "$.loginId",
                            "schema_expanded_from": "mbrMgmtSearchRequest",
                            "semantic_tag": "member_login_id",
                        }
                    ],
                    "produces": [],
                    "ai_metadata": {"canonical_action": "search"},
                },
            },
        },
    }

    plan = PathSynthesizer(g).synthesize(target="searchMembers", entities={})

    assert plan.metadata["user_input_slots"] == [
        {
            "step_id": "s1",
            "tool": "searchMembers",
            "field_name": "loginId",
            "required": True,
            "kind": "data",
            "field_type": "string",
            "location": "query",
            "json_path": "$.loginId",
            "semantic_tag": "member_login_id",
            "schema_expanded_from": "mbrMgmtSearchRequest",
            "reason": "user_input_fallback",
            "cause": "search_filter",
        }
    ]


def test_synthesize_unknown_target_raises():
    syn = PathSynthesizer(_basic_graph())
    with pytest.raises(PlanSynthesisError):
        syn.synthesize(target="ghostTool", entities={})


def test_synthesize_context_field_uses_collection_default():
    """kind=context 인 필드는 entity 없으면 context_defaults 에서 채움."""
    g = {
        "tools": {
            "needsLocale": {
                "metadata": {
                    "consumes": [
                        {
                            "field_name": "locale",
                            "kind": "context",
                            "required": True,
                        }
                    ],
                    "produces": [],
                    "ai_metadata": {"canonical_action": "read"},
                },
            },
        },
    }
    syn = PathSynthesizer(g, context_defaults={"locale": "ko_KR"})
    plan = syn.synthesize(target="needsLocale", entities={})
    assert plan.steps[0].args == {"locale": "ko_KR"}


# ─── search-leaf 정책 (조회 target 은 필터를 체인하지 않음) ──


def _search_filter_graph() -> dict:
    """검색 target 이 required 필터를 갖고, 그 필터를 만들 수 있는 producer 도 존재.

    - 'getCustomer' (read): 입력=name, 출력=customerId (semantic=customer.id)
    - 'searchOrders' (search): 입력=customerId(required, semantic=customer.id) +
      keyword(required). producer(getCustomer)가 customerId 를 만들 수 있지만,
      search-leaf 정책상 조회 target 의 필터는 체인하지 않고 user_input 슬롯으로.
    """
    return {
        "tools": {
            "getCustomer": {
                "metadata": {
                    "method": "GET",
                    "consumes": [{"field_name": "name", "kind": "data", "required": True}],
                    "produces": [
                        {
                            "field_name": "customerId",
                            "json_path": "$.body.customerId",
                            "semantic_tag": "customer.id",
                        }
                    ],
                    "ai_metadata": {"canonical_action": "read", "primary_resource": "customer"},
                },
            },
            "searchOrders": {
                "metadata": {
                    "method": "GET",
                    "consumes": [
                        {
                            "field_name": "customerId",
                            "semantic_tag": "customer.id",
                            "kind": "data",
                            "required": True,
                        },
                        {"field_name": "keyword", "kind": "data", "required": True},
                    ],
                    "produces": [],
                    "ai_metadata": {"canonical_action": "search", "primary_resource": "order"},
                },
            },
        },
    }


def test_search_target_does_not_chain_producer_for_required_filter():
    """조회(canonical_action=search) target 의 required 필터는 producer 가 있어도
    체인하지 않고 user_input 슬롯으로 남겨 단일 step 을 유지한다.

    (getGoodsList 류 검색이 12개 필터마다 producer 를 붙여 다단계 plan 으로
    폭발하던 회귀의 근본 방지.)
    """
    syn = PathSynthesizer(_search_filter_graph())
    plan = syn.synthesize(target="searchOrders", entities={})
    assert len(plan.steps) == 1, "검색은 단일 step (producer 체인 없음)"
    assert plan.steps[0].tool == "searchOrders"
    assert plan.steps[0].args == {
        "customerId": "${user_input.customerId}",
        "keyword": "${user_input.keyword}",
    }
    assert all(s.tool != "getCustomer" for s in plan.steps), "producer 는 plan 에 없어야"


def test_search_target_entity_filter_still_binds():
    """search-leaf 정책은 entity 매칭(1)보다 뒤 — 사용자가 준 필터값은 그대로 바인딩."""
    syn = PathSynthesizer(_search_filter_graph())
    plan = syn.synthesize(target="searchOrders", entities={"customerId": "C123"})
    assert len(plan.steps) == 1
    args = plan.steps[0].args
    assert args["customerId"] == "C123", "entity 로 준 필터는 user_input 이 아니라 실제 값"
    assert args["keyword"] == "${user_input.keyword}"


def test_read_target_still_chains_search_producer():
    """search-leaf 정책은 read target 에는 적용 안 됨 — read→detail 체인은 보존.

    getProductDetail(read) 은 goodsNo 를 searchProduct(search) 에서 체인하고,
    그 producer searchProduct 의 keyword 필터는 search-leaf 로 user_input 이 된다.
    """
    syn = PathSynthesizer(_basic_graph())
    plan = syn.synthesize(target="getProductDetail", entities={})
    assert len(plan.steps) == 2, "read 는 여전히 search producer 를 체인"
    assert plan.steps[0].tool == "searchProduct"
    assert plan.steps[1].tool == "getProductDetail"
    assert plan.steps[0].args == {"keyword": "${user_input.keyword}"}
    assert "s1" in plan.steps[1].args.get("goodsNo", "")
