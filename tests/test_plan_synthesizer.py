"""Unit tests for ``graph_tool_call.plan.synthesizer``.

핵심 합성 시나리오 + Cycle/F2 fallback 의 user_input placeholder 출력.
"""
from __future__ import annotations

import pytest

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
                    "consumes": [
                        {"field_name": "keyword", "kind": "data", "required": True}
                    ],
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
                    "produces": [
                        {"field_name": "name", "json_path": "$.body.name"}
                    ],
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
        target="getProductDetail", entities={"keyword": "shoes"},
    )
    assert len(plan.steps) == 2, "검색 + 상세조회 2-step chain"
    assert plan.steps[0].tool == "searchProduct"
    assert plan.steps[1].tool == "getProductDetail"
    binding = plan.steps[1].args.get("goodsNo", "")
    # step_id 순서 정렬 후 binding 은 ${s1...} 로 rewrite — 첫 step 의 출력 가리킴
    assert binding.startswith("${"), "binding placeholder 형식이어야"
    assert "s1" in binding, f"첫 step (s1) 출력 binding 이어야, got {binding}"
    assert "goodsNo" in binding, "produces 필드 경로 포함"


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
                    "consumes": [
                        {"field_name": "mysteryField", "kind": "data", "required": True}
                    ],
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
