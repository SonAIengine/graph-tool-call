"""0.25 graphify/Planflow public contract tests."""

from __future__ import annotations

from dataclasses import asdict

from graph_tool_call import __version__
from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.graphify import (
    COLLECTION_GRAPH_VERSION,
    EVIDENCE_API_CONTRACT,
    EVIDENCE_OPENAPI_LINK,
    build_candidate_set,
    build_io_contract,
    derive_plan_trace_edges,
    expand_candidates_with_producers,
    ingest_openapi_graphify,
    merge_graph_edges,
    normalize_graph_edge,
    promote_api_contract_signals,
    retrieve_graphify,
)
from graph_tool_call.ingest.openapi import ingest_openapi
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
    assert callable(build_candidate_set)
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
    assert by_produce["goodsNo"]["response_collection_path"] == "$.items[*]"
    assert "$.goodsNo" in by_produce["goodsNo"]["value_path_aliases"]
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


def test_build_io_contract_filters_readonly_writeonly_by_direction():
    response_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "readOnly": True},
            "password": {"type": "string", "writeOnly": True},
        },
    }
    request_body_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "readOnly": True},
            "email": {"type": "string"},
            "password": {"type": "string", "writeOnly": True},
        },
    }

    produces, consumes = build_io_contract(
        response_schema=response_schema,
        request_body_schema=request_body_schema,
    )

    assert {row["field_name"] for row in produces} == {"id"}
    assert {row["field_name"] for row in consumes} == {"email", "password"}
    assert produces[0]["read_only"] is True
    assert next(row for row in consumes if row["field_name"] == "password")["write_only"] is True


def test_build_io_contract_unions_oneof_branch_fields():
    request_body_schema = {
        "oneOf": [
            {
                "type": "object",
                "required": ["paymentType", "cardNumber"],
                "properties": {
                    "paymentType": {"type": "string", "enum": ["card"]},
                    "cardNumber": {"type": "string"},
                },
            },
            {
                "type": "object",
                "required": ["paymentType", "bankCode"],
                "properties": {
                    "paymentType": {"type": "string", "enum": ["bank"]},
                    "bankCode": {"type": "string"},
                },
            },
        ]
    }
    response_schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"paymentId": {"type": "string"}},
            },
            {
                "type": "object",
                "properties": {"approvalNo": {"type": "string"}},
            },
        ]
    }

    produces, consumes = build_io_contract(
        response_schema=response_schema,
        request_body_schema=request_body_schema,
    )
    by_consume = {row["field_name"]: row for row in consumes}
    by_produce = {row["field_name"]: row for row in produces}

    assert set(by_consume) == {"paymentType", "cardNumber", "bankCode"}
    assert by_consume["paymentType"]["enum"] == ["card", "bank"]
    assert by_consume["paymentType"]["required"] is False
    assert by_consume["paymentType"]["required_in_branch"] is True
    assert by_consume["paymentType"]["schema_combinator"] == "oneOf"
    assert set(by_produce) == {"paymentId", "approvalNo"}
    assert by_produce["approvalNo"]["schema_combinator"] == "anyOf"


def test_build_io_contract_preserves_discriminator_hints():
    request_body_schema = {
        "oneOf": [
            {
                "type": "object",
                "x-graph-tool-call-ref": "#/components/schemas/CardPayment",
                "required": ["cardNumber"],
                "properties": {"cardNumber": {"type": "string"}},
            },
            {
                "type": "object",
                "x-graph-tool-call-ref": "#/components/schemas/BankPayment",
                "required": ["bankCode"],
                "properties": {"bankCode": {"type": "string"}},
            },
        ],
        "discriminator": {
            "propertyName": "paymentType",
            "mapping": {
                "card": "#/components/schemas/CardPayment",
                "bank": "#/components/schemas/BankPayment",
            },
        },
    }

    _produces, consumes = build_io_contract(request_body_schema=request_body_schema)
    by_consume = {row["field_name"]: row for row in consumes}

    assert set(by_consume) == {"paymentType", "cardNumber", "bankCode"}
    assert by_consume["paymentType"]["enum"] == ["card", "bank"]
    assert by_consume["paymentType"]["discriminator_property"] == "paymentType"
    assert by_consume["cardNumber"]["schema_ref"] == "#/components/schemas/CardPayment"
    assert by_consume["cardNumber"]["discriminator_value"] == "card"


def test_promote_api_contract_signals_selects_useful_fields_without_wrapper_noise():
    search = ToolSchema(
        name="searchProducts",
        metadata={
            "api_contract": {
                "produces": [
                    {"field_name": "status", "json_path": "$.status", "field_type": "string"},
                    {"field_name": "data", "json_path": "$.data", "field_type": "object"},
                    {
                        "field_name": "goodsNo",
                        "json_path": "$.data.items[*].goodsNo",
                        "field_type": "string",
                        "response_envelope_path": "$.data",
                        "response_collection_path": "$.data.items[*]",
                        "value_path_aliases": ["$.body.data.items[*].goodsNo"],
                    },
                    {
                        "field_name": "goodsNm",
                        "json_path": "$.data.items[*].goodsNm",
                        "field_type": "string",
                    },
                ],
                "consumes": [
                    {
                        "field_name": "keyword",
                        "field_type": "string",
                        "required": False,
                        "location": "query",
                    }
                ],
            }
        },
    )
    detail = ToolSchema(
        name="getProductDetail",
        metadata={
            "api_contract": {
                "produces": [],
                "consumes": [
                    {
                        "field_name": "goodsNo",
                        "field_type": "string",
                        "required": True,
                        "location": "path",
                    },
                    {
                        "field_name": "siteNo",
                        "field_type": "string",
                        "required": True,
                        "location": "query",
                    },
                    {
                        "field_name": "pageNo",
                        "field_type": "integer",
                        "required": False,
                        "location": "query",
                    },
                    {
                        "field_name": "giftMessage",
                        "field_type": "string",
                        "required": False,
                        "location": "body",
                    },
                ],
            }
        },
    )

    stats = promote_api_contract_signals(
        [search, detail],
        user_input_field_names={"gift_message"},
        context_field_names={"site_no"},
        paging_field_names={"pageNo"},
    )

    produces = {row["field_name"]: row for row in search.metadata["produces"]}
    consumes = {row["field_name"]: row for row in detail.metadata["consumes"]}
    assert "status" not in produces
    assert "data" not in produces
    assert "goodsNm" not in produces
    assert produces["goodsNo"]["semantic_tag"] == "goods_no"
    assert produces["goodsNo"]["semantic_inferred_from"] == "field_name"
    assert produces["goodsNo"]["search_signal"] is False
    assert produces["goodsNo"]["response_envelope_path"] == "$.data"
    assert produces["goodsNo"]["response_collection_path"] == "$.data.items[*]"
    assert produces["goodsNo"]["value_path_aliases"] == ["$.body.data.items[*].goodsNo"]
    assert consumes["goodsNo"]["kind"] == "data"
    assert consumes["goodsNo"]["required"] is True
    assert consumes["goodsNo"]["search_signal"] is False
    assert consumes["siteNo"]["kind"] == "context"
    assert consumes["siteNo"]["required"] is False
    assert consumes["pageNo"]["kind"] == "context"
    assert consumes["giftMessage"]["required"] is True
    assert stats["produces_added"] == 1
    assert stats["consumes_added"] == 5


def test_promote_api_contract_signals_preserves_openapi_security_auth_hints():
    tool = ToolSchema(
        name="listOrders",
        metadata={
            "api_contract": {
                "produces": [],
                "consumes": [
                    {
                        "field_name": "Authorization",
                        "field_type": "string",
                        "required": False,
                        "location": "header",
                        "kind": "auth",
                        "security_required": True,
                        "security_scheme": "bearerAuth",
                        "security_schemes": ["bearerAuth"],
                        "auth_type": "http",
                        "credential_name": "Authorization",
                        "scheme": "bearer",
                        "bearer_format": "JWT",
                        "requirement_indices": [0],
                    }
                ],
            }
        },
    )

    stats = promote_api_contract_signals([tool])

    assert stats["consumes_added"] == 1
    auth = tool.metadata["consumes"][0]
    assert auth["field_name"] == "Authorization"
    assert auth["kind"] == "auth"
    assert auth["required"] is False
    assert auth["contract_source"] == "api_contract"
    assert auth["security_required"] is True
    assert auth["security_scheme"] == "bearerAuth"
    assert auth["security_schemes"] == ["bearerAuth"]
    assert auth["auth_type"] == "http"
    assert auth["scheme"] == "bearer"
    assert auth["bearer_format"] == "JWT"
    assert auth["credential_name"] == "Authorization"
    assert auth["requirement_indices"] == [0]


def test_promote_api_contract_signals_skips_inverse_direction_fields():
    search = ToolSchema(
        name="searchUsers",
        metadata={
            "api_contract": {
                "produces": [
                    {
                        "field_name": "userId",
                        "json_path": "$.items[*].userId",
                        "field_type": "string",
                    },
                    {
                        "field_name": "password",
                        "json_path": "$.items[*].password",
                        "field_type": "string",
                        "write_only": True,
                    },
                ],
                "consumes": [],
            }
        },
    )
    create = ToolSchema(
        name="createUser",
        metadata={
            "api_contract": {
                "produces": [],
                "consumes": [
                    {
                        "field_name": "userId",
                        "field_type": "string",
                        "required": True,
                        "location": "body",
                        "read_only": True,
                    },
                    {
                        "field_name": "email",
                        "field_type": "string",
                        "required": True,
                        "location": "body",
                    },
                ],
            }
        },
    )

    promote_api_contract_signals([search, create], promote_rare_produces=True)

    assert {row["field_name"] for row in search.metadata["produces"]} == {"userId"}
    assert {row["field_name"] for row in create.metadata["consumes"]} == {"email"}


def test_ingest_openapi_graphify_can_promote_contracts_into_data_flow_edges():
    search = ToolSchema(
        name="searchProducts",
        description="상품 검색",
        metadata={
            "method": "get",
            "path": "/products",
            "api_contract": {
                "produces": [
                    {
                        "field_name": "goodsNo",
                        "json_path": "$.items[*].goodsNo",
                        "field_type": "string",
                    }
                ],
                "consumes": [
                    {
                        "field_name": "keyword",
                        "field_type": "string",
                        "required": False,
                        "location": "query",
                    }
                ],
            },
            "ai_metadata": {"canonical_action": "search"},
        },
    )
    detail = ToolSchema(
        name="getProductDetail",
        description="상품 상세",
        metadata={
            "method": "get",
            "path": "/products/{goodsNo}",
            "api_contract": {
                "produces": [],
                "consumes": [
                    {
                        "field_name": "goodsNo",
                        "field_type": "string",
                        "required": True,
                        "location": "path",
                    }
                ],
            },
            "ai_metadata": {"canonical_action": "read"},
        },
    )

    tg, stats = ingest_openapi_graphify(
        [search, detail],
        promote_contract_signals=True,
    )
    edge = tg.graph.get_edge_attrs("getProductDetail", "searchProducts")

    assert stats["contract_signals"]["produces_added"] == 1
    assert stats["contract_edges"]["added"] == 1
    assert edge["relation"] == "requires"
    assert edge["kind"] == "data"
    assert edge["evidence_sources"] == ["api_contract"]
    assert edge["data_flow"]["to_field"] == "goodsNo"

    graph_payload = {
        "graph": tg.graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in tg.tools.items()},
    }
    plan = PathSynthesizer(graph_payload).synthesize(target="getProductDetail", goal="상품 상세")
    assert [step.tool for step in plan.steps] == ["searchProducts", "getProductDetail"]
    assert plan.steps[-1].args["goodsNo"] == "${s1.items[0].goodsNo}"


def test_ingest_openapi_graphify_uses_openapi_links_for_cross_field_data_flow():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Linked API", "version": "1.0.0"},
        "paths": {
            "/signup-sessions": {
                "post": {
                    "operationId": "createSignupSession",
                    "summary": "회원 가입 세션 생성",
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"id": {"type": "string"}},
                                    }
                                }
                            },
                            "links": {
                                "GetProfileByUserId": {
                                    "operationRef": "#/paths/~1profiles~1{userId}/get",
                                    "parameters": {"userId": "$response.body#/id"},
                                }
                            },
                        }
                    },
                }
            },
            "/profiles/{userId}": {
                "get": {
                    "operationId": "getProfile",
                    "summary": "프로필 조회",
                    "parameters": [
                        {
                            "name": "userId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }
    tools, _ = ingest_openapi(spec)

    tg, stats = ingest_openapi_graphify(tools, promote_contract_signals=True)
    edge = tg.graph.get_edge_attrs("getProfile", "createSignupSession")
    create_tool = tg.tools["createSignupSession"]
    link_produces = [
        row
        for row in create_tool.metadata.get("produces", [])
        if row.get("contract_source") == EVIDENCE_OPENAPI_LINK
    ]

    assert stats["openapi_link_signals"]["produces_added"] == 1
    assert stats["openapi_link_edges"]["added"] == 1
    assert stats["contract_edges"]["merged"] == 1
    assert edge["relation"] == "requires"
    assert edge["confidence"] == "EXTRACTED"
    assert edge["evidence_sources"] == [EVIDENCE_OPENAPI_LINK, EVIDENCE_API_CONTRACT]
    assert edge["data_flow"]["to_field"] == "userId"
    assert edge["data_flow"]["from_path"] == "$.id"
    assert edge["data_flow"]["parameters"][0]["expression"] == "$response.body#/id"
    assert link_produces == [
        {
            "field_name": "userId",
            "json_path": "$.id",
            "field_type": "string",
            "required": False,
            "kind": "data",
            "search_signal": False,
            "contract_source": EVIDENCE_OPENAPI_LINK,
            "openapi_link_name": "GetProfileByUserId",
            "openapi_link_target_operation_id": None,
            "openapi_link_target_operation_ref": "#/paths/~1profiles~1{userId}/get",
            "openapi_link_source": "response_body",
            "source_field_name": "id",
            "value_path_aliases": ["$.body.id"],
        }
    ]

    graph_payload = {
        "graph": tg.graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in tg.tools.items()},
    }
    plan = PathSynthesizer(graph_payload).synthesize(target="getProfile", goal="프로필 조회")

    assert [step.tool for step in plan.steps] == ["createSignupSession", "getProfile"]
    assert plan.steps[-1].args["userId"] == "${s1.id}"


def test_ingest_openapi_graphify_uses_response_header_links_for_plan_binding():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Header Linked API", "version": "1.0.0"},
        "paths": {
            "/sessions": {
                "post": {
                    "operationId": "createSession",
                    "summary": "세션 생성",
                    "responses": {
                        "201": {
                            "description": "Created",
                            "headers": {
                                "X-Session-Token": {
                                    "description": "Temporary session token",
                                    "schema": {"type": "string"},
                                }
                            },
                            "links": {
                                "GetSession": {
                                    "operationId": "getSession",
                                    "parameters": {
                                        "sessionToken": "$response.header.X-Session-Token"
                                    },
                                }
                            },
                        }
                    },
                }
            },
            "/sessions/current": {
                "get": {
                    "operationId": "getSession",
                    "summary": "현재 세션 조회",
                    "parameters": [
                        {
                            "name": "sessionToken",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }

    tools, _ = ingest_openapi(spec)
    tg, stats = ingest_openapi_graphify(tools, promote_contract_signals=True)
    create_tool = tg.tools["createSession"]
    link_produces = [
        row
        for row in create_tool.metadata.get("produces", [])
        if row.get("contract_source") == EVIDENCE_OPENAPI_LINK
    ]

    assert stats["openapi_link_signals"]["produces_added"] == 1
    assert link_produces == [
        {
            "field_name": "sessionToken",
            "json_path": "$.headers.X-Session-Token",
            "field_type": "string",
            "required": False,
            "kind": "data",
            "search_signal": False,
            "contract_source": EVIDENCE_OPENAPI_LINK,
            "openapi_link_name": "GetSession",
            "openapi_link_target_operation_id": "getSession",
            "openapi_link_target_operation_ref": None,
            "openapi_link_source": "response_header",
            "source_field_name": "X-Session-Token",
        }
    ]
    edge = tg.graph.get_edge_attrs("getSession", "createSession")
    assert edge["relation"] == "requires"
    assert EVIDENCE_OPENAPI_LINK in edge["evidence_sources"]
    assert EVIDENCE_API_CONTRACT in edge["evidence_sources"]
    assert edge["data_flow"]["from_path"] == "$.headers.X-Session-Token"
    assert edge["data_flow"]["from_field"] == "X-Session-Token"
    assert edge["data_flow"]["to_field"] == "sessionToken"

    graph_payload = {
        "graph": tg.graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in tg.tools.items()},
    }
    plan = PathSynthesizer(graph_payload).synthesize(target="getSession", goal="세션 조회")
    assert [step.tool for step in plan.steps] == ["createSession", "getSession"]
    assert plan.steps[-1].args["sessionToken"] == "${s1.headers.X-Session-Token}"


def test_ingest_openapi_graphify_promotes_status_range_response_contracts():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Status Range API", "version": "1.0.0"},
        "paths": {
            "/exports": {
                "post": {
                    "operationId": "createExport",
                    "summary": "내보내기 생성",
                    "responses": {
                        "2XX": {
                            "description": "Any successful export response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"exportId": {"type": "string"}},
                                    }
                                }
                            },
                        },
                        "4XX": {
                            "description": "Client error",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"errorCode": {"type": "string"}},
                                    }
                                }
                            },
                        },
                    },
                }
            },
            "/exports/{exportId}": {
                "get": {
                    "operationId": "getExport",
                    "summary": "내보내기 조회",
                    "parameters": [
                        {
                            "name": "exportId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }

    tools, _ = ingest_openapi(spec)
    assert {row["status"] for row in tools[0].metadata["openapi"]["error_responses"]} == {"4XX"}

    tg, stats = ingest_openapi_graphify(tools, promote_contract_signals=True)
    edge = tg.graph.get_edge_attrs("getExport", "createExport")

    assert stats["contract_signals"]["produces_added"] == 1
    assert stats["contract_edges"]["merged"] == 1
    assert edge["relation"] == "requires"
    assert EVIDENCE_API_CONTRACT in edge["evidence_sources"]
    assert edge["data_flow"]["to_field"] == "exportId"

    graph_payload = {
        "graph": tg.graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in tg.tools.items()},
    }
    plan = PathSynthesizer(graph_payload).synthesize(target="getExport", goal="내보내기 조회")
    assert [step.tool for step in plan.steps] == ["createExport", "getExport"]
    assert plan.steps[-1].args["exportId"] == "${s1.exportId}"


def test_ingest_openapi_graphify_resolves_duplicate_operation_ids_by_operation_ref():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Duplicate Link API", "version": "1.0.0"},
        "paths": {
            "/tokens": {
                "post": {
                    "operationId": "createToken",
                    "summary": "토큰 생성",
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"id": {"type": "string"}},
                                    }
                                }
                            },
                            "links": {
                                "AmbiguousReadThing": {
                                    "operationId": "readThing",
                                    "parameters": {"tokenId": "$response.body#/id"},
                                },
                                "ReadSpecialThing": {
                                    "operationRef": "#/paths/~1things~1special/get",
                                    "parameters": {"tokenId": "$response.body#/id"},
                                },
                            },
                        }
                    },
                }
            },
            "/things/{thingId}": {
                "get": {
                    "operationId": "readThing",
                    "summary": "일반 대상 조회",
                    "parameters": [
                        {
                            "name": "thingId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/things/special": {
                "get": {
                    "operationId": "readThing",
                    "summary": "특수 대상 조회",
                    "parameters": [
                        {
                            "name": "tokenId",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }

    tools, _ = ingest_openapi(spec)
    assert {tool.name for tool in tools} == {
        "createToken",
        "readThing",
        "readThing__get_things_special",
    }

    tg, stats = ingest_openapi_graphify(tools, promote_contract_signals=True)

    assert stats["openapi_link_edges"]["skipped_unresolved"] == 1
    assert stats["openapi_link_edges"]["merged"] == 1
    edge = tg.graph.get_edge_attrs("readThing__get_things_special", "createToken")
    assert edge["relation"] == "requires"
    assert edge["confidence"] == "EXTRACTED"
    assert EVIDENCE_OPENAPI_LINK in edge["evidence_sources"]
    assert edge["data_flow"]["link_name"] == "ReadSpecialThing"
    assert edge["data_flow"]["to_field"] == "tokenId"
    assert not tg.graph.has_edge("readThing", "createToken")


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


def test_expand_candidates_with_producers_can_follow_target_specific_chain():
    tools = {
        "getInventory": {
            "metadata": {
                "consumes": [
                    {"field_name": "skuId", "semantic_tag": "sku_id", "required": True},
                ]
            }
        },
        "getProductDetail": {
            "metadata": {
                "consumes": [
                    {"field_name": "productId", "semantic_tag": "product_id", "required": True},
                ],
                "produces": [{"field_name": "skuId", "semantic_tag": "sku_id"}],
                "ai_metadata": {"canonical_action": "read"},
            }
        },
        "searchProducts": {
            "metadata": {
                "produces": [{"field_name": "productId", "semantic_tag": "product_id"}],
                "ai_metadata": {"canonical_action": "search"},
            }
        },
        "listProducts": {
            "metadata": {
                "produces": [{"field_name": "productId", "semantic_tag": "product_id"}],
                "ai_metadata": {"canonical_action": "read"},
            }
        },
    }

    one_hop = expand_candidates_with_producers(["getInventory"], tools, max_hops=1)
    two_hops = expand_candidates_with_producers(["getInventory"], tools, max_hops=2)

    assert one_hop == ["getInventory", "getProductDetail"]
    assert two_hops == ["getInventory", "getProductDetail", "searchProducts", "listProducts"]


def test_build_candidate_set_separates_target_candidates_from_producers():
    tools = {
        "searchProducts": {
            "metadata": {
                "produces": [{"field_name": "productId", "semantic_tag": "product_id"}],
                "ai_metadata": {"canonical_action": "search"},
            }
        },
        "getProductDetail": {
            "metadata": {
                "consumes": [
                    {"field_name": "productId", "semantic_tag": "product_id", "required": True},
                ],
            }
        },
        "getCart": {
            "metadata": {
                "consumes": [
                    {"field_name": "cartId", "semantic_tag": "cart_id", "required": True},
                ],
            }
        },
        "getCurrentCart": {
            "metadata": {
                "produces": [{"field_name": "cartId", "semantic_tag": "cart_id"}],
                "ai_metadata": {"canonical_action": "read"},
            }
        },
    }

    result = build_candidate_set(
        ["getProductDetail", "getCart"],
        tools,
        expansion_seed=["getProductDetail"],
        max_hops=1,
    )

    assert result["target_candidates"] == ["getProductDetail", "getCart"]
    assert result["expansion_seed"] == ["getProductDetail"]
    assert result["producer_candidates"] == ["searchProducts"]
    assert result["candidates"] == ["getProductDetail", "searchProducts"]
    assert result["target_candidate_count"] == 2
    assert result["candidate_count"] == 2
    assert result["producer_added_count"] == 1
    assert result["adaptive_expansion_applied"] is True


def test_build_candidate_set_can_cap_sibling_target_groups_without_touching_producers():
    tools = {
        "getButtonByPageRoleList": {
            "metadata": {
                "consumes": [
                    {"field_name": "pageRoleId", "semantic_tag": "page_role_id", "required": True}
                ],
                "ai_metadata": {"primary_resource": "page_role_button", "canonical_action": "read"},
            }
        },
        "getEnabledButtonByPageRoleList": {
            "metadata": {
                "ai_metadata": {"primary_resource": "page_role_button", "canonical_action": "read"},
            }
        },
        "getUserButtonByPageRoleList": {
            "metadata": {
                "ai_metadata": {"primary_resource": "page_role_button", "canonical_action": "read"},
            }
        },
        "getUserDetail": {
            "metadata": {
                "ai_metadata": {"primary_resource": "user", "canonical_action": "read"},
            }
        },
        "searchPageRoles": {
            "metadata": {
                "produces": [{"field_name": "pageRoleId", "semantic_tag": "page_role_id"}],
                "ai_metadata": {"primary_resource": "page_role", "canonical_action": "search"},
            }
        },
    }

    result = build_candidate_set(
        [
            "getButtonByPageRoleList",
            "getEnabledButtonByPageRoleList",
            "getUserButtonByPageRoleList",
            "getUserDetail",
        ],
        tools,
        expansion_seed=["getButtonByPageRoleList"],
        max_targets_per_group=2,
        max_hops=1,
    )

    assert result["raw_target_candidates"] == [
        "getButtonByPageRoleList",
        "getEnabledButtonByPageRoleList",
        "getUserButtonByPageRoleList",
        "getUserDetail",
    ]
    assert result["target_candidates"] == [
        "getButtonByPageRoleList",
        "getEnabledButtonByPageRoleList",
        "getUserDetail",
    ]
    assert result["suppressed_target_candidates"] == ["getUserButtonByPageRoleList"]
    assert result["sibling_control_applied"] is True
    assert result["producer_candidates"] == ["searchPageRoles"]
    assert result["candidates"] == ["getButtonByPageRoleList", "searchPageRoles"]
    page_role_group = next(
        row
        for row in result["target_candidate_groups"]
        if row["key"] == "resource_action:page_role_button:read"
    )
    assert page_role_group["member_count"] == 3
    assert page_role_group["suppressed_count"] == 1


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


def test_retrieve_with_scores_expands_korean_business_field_aliases():
    tg = ToolGraph()
    tg.add_tool(
        ToolSchema(
            name="opaqueGoodsDetail",
            description="",
            metadata={
                "consumes": [
                    {
                        "field_name": "goodsNo",
                        "semantic_tag": "product_id",
                        "kind": "data",
                    }
                ]
            },
        )
    )
    tg.add_tool(
        ToolSchema(
            name="opaqueOrderDetail",
            description="",
            metadata={
                "consumes": [
                    {
                        "field_name": "ordNo",
                        "semantic_tag": "order_id",
                        "kind": "data",
                    }
                ]
            },
        )
    )

    results = tg.retrieve_with_scores("상품번호로 상세 확인", top_k=1)

    assert results[0].tool.name == "opaqueGoodsDetail"
    assert results[0].keyword_score > 0


def test_retrieve_with_scores_maps_korean_inquiry_to_qa_label():
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="getProductQa", description="상품QA 목록 조회"))
    tg.add_tool(ToolSchema(name="getQnAStatus", description="상품문의 현황 조회"))
    tg.add_tool(ToolSchema(name="getProductReview", description="상품리뷰 목록 조회"))

    results = tg.retrieve_with_scores("상품 문의 조회", top_k=1)

    assert results[0].tool.name == "getProductQa"


def test_retrieve_with_scores_prefers_core_korean_action_phrase_over_subscope():
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="getOrderQueryList", description="주문/결제 > 주문관리 > 주문조회"))
    tg.add_tool(ToolSchema(name="getExchangeOrderList", description="교환주문목록 조회"))
    tg.add_tool(ToolSchema(name="getCustomerOrderPopup", description="고객 주문 목록 조회 팝업"))

    results = tg.retrieve_with_scores("주문 목록 조회", top_k=1)

    assert results[0].tool.name == "getOrderQueryList"


def test_retrieve_with_scores_keeps_exact_korean_list_phrase_above_subscope():
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="getMemberList", description="회원 목록 조회"))
    tg.add_tool(ToolSchema(name="getCouponIssuedMemberList", description="쿠폰 발급회원 조회"))
    tg.add_tool(ToolSchema(name="getMemberHistoryList", description="회원 이력 목록 조회"))

    results = tg.retrieve_with_scores("회원 목록 조회", top_k=1)

    assert results[0].tool.name == "getMemberList"


def test_retrieve_with_scores_indexes_parameter_descriptions_for_example_fields():
    tg = ToolGraph()
    tg.add_tool(
        ToolSchema(
            name="op001",
            description="",
            parameters=[
                ToolParameter(
                    name="filters",
                    type="object",
                    description="Fields:\n- brandNo (string)\n- saleStatusCd (string)",
                )
            ],
            metadata={"method": "post", "path": "/api/bo/goods/search"},
        )
    )
    tg.add_tool(
        ToolSchema(
            name="op002",
            description="상품 목록 조회",
            parameters=[ToolParameter(name="keyword", type="string")],
        )
    )

    results = tg.retrieve_with_scores("브랜드번호로 상품 검색", top_k=1)

    assert results[0].tool.name == "op001"
    assert results[0].keyword_score > 0


def test_retrieve_with_scores_skips_raw_contract_fields_without_search_signal():
    tg = ToolGraph()
    tg.add_tool(
        ToolSchema(
            name="source001",
            description="",
            metadata={
                "produces": [
                    {
                        "field_name": "opaqueTokenId",
                        "semantic_tag": "opaque_token_id",
                        "contract_source": "api_contract",
                        "search_signal": False,
                    }
                ]
            },
        )
    )
    tg.add_tool(ToolSchema(name="control001", description="opaque token id visible"))

    results = tg.retrieve_with_scores("opaque token id", top_k=1)

    assert results[0].tool.name == "control001"


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
