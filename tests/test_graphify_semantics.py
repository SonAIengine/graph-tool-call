from __future__ import annotations

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import (
    annotate_openapi_tool_semantics,
    derive_openapi_tool_semantics,
    summarize_openapi_semantics,
)
from graph_tool_call.ingest.openapi import ingest_openapi


def _bo_semantic_spec() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "BO Semantic API", "version": "1.0.0"},
        "paths": {
            "/api/bo/v2/goods/goodsCommonApi/getGoodsList": {
                "get": {
                    "operationId": "getGoodsList",
                    "summary": "상품 목록 조회",
                    "responses": {"200": _ok_response("goodsNo")},
                }
            },
            "/api/bo/v1/order/orderQuery/getOrderQueryList": {
                "get": {
                    "operationId": "getOrderQueryList",
                    "summary": "주문 목록 조회",
                    "responses": {"200": _ok_response("ordNo")},
                }
            },
            "/api/bo/v1/customer/faq/saveFaqList": {
                "post": {
                    "operationId": "saveFaqList",
                    "summary": "FAQ 목록 저장",
                    "requestBody": _body("faqNo"),
                    "responses": {"200": _ok_response("faqNo")},
                }
            },
            "/api/bo/v1/claim/return/withdrawalReturn": {
                "post": {
                    "operationId": "withdrawalReturn",
                    "summary": "반품 철회 처리",
                    "requestBody": _body("ordNo"),
                    "responses": {"200": _ok_response("claimNo")},
                }
            },
            "/api/bo/v1/member/pageRole/getButtonByPageRoleList": {
                "get": {
                    "operationId": "getButtonByPageRoleList",
                    "summary": "페이지 권한 버튼 목록 조회",
                    "responses": {"200": _ok_response("buttonNo")},
                }
            },
        },
    }


def _body(field_name: str) -> dict:
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": [field_name],
                    "properties": {field_name: {"type": "string"}},
                }
            }
        },
    }


def _ok_response(field_name: str) -> dict:
    return {
        "description": "OK",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {field_name: {"type": "string"}},
                }
            }
        },
    }


def test_derive_openapi_tool_semantics_for_bo_style_names_and_paths() -> None:
    tools, _ = ingest_openapi(_bo_semantic_spec())
    by_name = {tool.name: derive_openapi_tool_semantics(tool) for tool in tools}

    assert by_name["getGoodsList"]["ai_metadata"]["canonical_action"] == "search"
    assert by_name["getGoodsList"]["ai_metadata"]["primary_resource"] == "goods"
    assert by_name["getGoodsList"]["openapi"]["path_module"] == "goods/goods_common"

    assert by_name["getOrderQueryList"]["ai_metadata"]["canonical_action"] == "search"
    assert by_name["getOrderQueryList"]["ai_metadata"]["primary_resource"] == "order"
    assert by_name["getOrderQueryList"]["openapi"]["path_module"] == "order/order_query"

    assert by_name["saveFaqList"]["ai_metadata"]["canonical_action"] == "update"
    assert by_name["saveFaqList"]["ai_metadata"]["primary_resource"] == "customer"

    assert by_name["withdrawalReturn"]["ai_metadata"]["canonical_action"] == "action"
    assert by_name["withdrawalReturn"]["ai_metadata"]["primary_resource"] == "claim"

    assert by_name["getButtonByPageRoleList"]["ai_metadata"]["canonical_action"] == "search"
    assert by_name["getButtonByPageRoleList"]["ai_metadata"]["primary_resource"] == "member"


def test_annotate_openapi_tool_semantics_preserves_existing_ai_metadata() -> None:
    tool = ToolSchema(
        name="getGoodsList",
        description="상품 목록 조회",
        metadata={
            "method": "get",
            "path": "/api/bo/v2/goods/goodsCommonApi/getGoodsList",
            "openapi": {"operation_id": "getGoodsList", "summary": "상품 목록 조회"},
            "ai_metadata": {
                "canonical_action": "read",
                "primary_resource": "manual_goods",
            },
        },
    )

    annotate_openapi_tool_semantics([tool])

    ai = tool.metadata["ai_metadata"]
    assert ai["canonical_action"] == "read"
    assert ai["primary_resource"] == "manual_goods"
    assert ai["one_line_summary"] == "상품 목록 조회"
    assert tool.metadata["openapi"]["path_module"] == "goods/goods_common"


def test_summarize_openapi_semantics_reports_coverage_without_mutating() -> None:
    tools, _ = ingest_openapi(_bo_semantic_spec())
    summary = summarize_openapi_semantics(tools)

    assert summary["canonical_action_known_rate"] == 1.0
    assert summary["primary_resource_assigned_rate"] == 1.0
    assert summary["path_module_assigned_rate"] == 1.0
    assert summary["action_counts"]["search"] == 3
    assert summary["action_counts"]["update"] == 1
    assert summary["action_counts"]["action"] == 1
    assert not any("ai_metadata" in tool.metadata for tool in tools)
