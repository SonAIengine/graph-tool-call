"""Tests for graph_tool_call.ingest.openapi."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ingest.openapi import ingest_openapi

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Basic ingestion per spec version
# ---------------------------------------------------------------------------


class TestIngestPetstoreSwagger2:
    def test_ingest_petstore_swagger2(self) -> None:
        tools, spec = ingest_openapi(str(FIXTURES / "petstore_swagger2.json"))
        assert len(tools) == 5
        names = {t.name for t in tools}
        assert names == {"listPets", "createPet", "getPet", "updatePet", "deletePet"}

    def test_tool_parameters(self) -> None:
        """Verify parameter extraction for path, query, and body params."""
        tools, _ = ingest_openapi(str(FIXTURES / "petstore_swagger2.json"))
        tools_by_name = {t.name: t for t in tools}

        # listPets has a query param 'limit'
        list_pets = tools_by_name["listPets"]
        param_names = {p.name for p in list_pets.parameters}
        assert "limit" in param_names
        limit_param = next(p for p in list_pets.parameters if p.name == "limit")
        assert limit_param.type == "integer"
        assert limit_param.required is False

        # getPet has a path param 'petId'
        get_pet = tools_by_name["getPet"]
        param_names = {p.name for p in get_pet.parameters}
        assert "petId" in param_names
        pet_id_param = next(p for p in get_pet.parameters if p.name == "petId")
        assert pet_id_param.required is True

        # createPet has body params expanded from NewPet
        create_pet = tools_by_name["createPet"]
        param_names = {p.name for p in create_pet.parameters}
        assert "name" in param_names

    def test_tool_metadata(self) -> None:
        tools, _ = ingest_openapi(str(FIXTURES / "petstore_swagger2.json"))
        tools_by_name = {t.name: t for t in tools}
        get_pet = tools_by_name["getPet"]
        assert get_pet.metadata["method"] == "get"
        assert get_pet.metadata["path"] == "/pets/{petId}"

    def test_tool_tags(self) -> None:
        tools, _ = ingest_openapi(str(FIXTURES / "petstore_swagger2.json"))
        for tool in tools:
            assert "pets" in tool.tags


class TestIngestOpenAPI30:
    def test_ingest_openapi30(self) -> None:
        tools, spec = ingest_openapi(str(FIXTURES / "minimal_openapi30.json"))
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"listUsers", "createUser", "getUser"}

    def test_request_body_params(self) -> None:
        """Verify requestBody fields are extracted as params."""
        tools, _ = ingest_openapi(str(FIXTURES / "minimal_openapi30.json"))
        create_user = next(t for t in tools if t.name == "createUser")
        param_names = {p.name for p in create_user.parameters}
        assert "name" in param_names
        assert "email" in param_names
        name_param = next(p for p in create_user.parameters if p.name == "name")
        assert name_param.required is True

    def test_rich_openapi_contract_metadata(self) -> None:
        """Ingest preserves request/response facts needed by graph/search/execution."""
        spec: dict = {
            "openapi": "3.0.0",
            "info": {"title": "Contract API", "version": "1.0.0"},
            "components": {
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                    },
                    "siteHeader": {
                        "type": "apiKey",
                        "in": "header",
                        "name": "X-Site-No",
                    },
                }
            },
            "security": [{"bearerAuth": []}],
            "paths": {
                "/tenants/{tenantId}/orders/{orderId}": {
                    "parameters": [
                        {
                            "name": "tenantId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "post": {
                        "operationId": "updateOrder",
                        "summary": "주문 수정",
                        "security": [{"siteHeader": []}],
                        "parameters": [
                            {
                                "name": "orderId",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                            {
                                "name": "preview",
                                "in": "query",
                                "style": "form",
                                "explode": False,
                                "allowReserved": True,
                                "schema": {"type": "boolean", "default": False},
                                "example": True,
                            },
                            {
                                "name": "X-Site-No",
                                "in": "header",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["status"],
                                        "properties": {
                                            "status": {
                                                "type": "string",
                                                "enum": ["paid", "cancelled"],
                                                "example": "paid",
                                            },
                                            "shipping": {
                                                "type": "object",
                                                "properties": {
                                                    "city": {
                                                        "type": "string",
                                                        "minLength": 2,
                                                        "pattern": "^[A-Za-z ]+$",
                                                    },
                                                },
                                            },
                                        },
                                    },
                                    "examples": {
                                        "paidOrder": {
                                            "summary": "Paid order",
                                            "value": {
                                                "status": "paid",
                                                "shipping": {"city": "Seoul"},
                                            },
                                        }
                                    },
                                },
                                "application/x-www-form-urlencoded": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"status": {"type": "string"}},
                                    }
                                },
                            },
                        },
                        "responses": {
                            "201": {
                                "description": "OK",
                                "content": {
                                    "*/*": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "data": {
                                                    "type": "object",
                                                    "properties": {
                                                        "orderId": {"type": "string"},
                                                        "status": {"type": "string"},
                                                    },
                                                }
                                            },
                                        },
                                        "example": {"data": {"orderId": "O-1", "status": "paid"}},
                                    }
                                },
                            },
                            "400": {
                                "description": "Invalid order update",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "errorCode": {
                                                    "type": "string",
                                                    "example": "ORDER_BAD",
                                                },
                                                "message": {"type": "string"},
                                            },
                                        },
                                        "examples": {
                                            "invalidStatus": {
                                                "value": {
                                                    "errorCode": "ORDER_BAD",
                                                    "message": "Invalid status",
                                                }
                                            }
                                        },
                                    }
                                },
                            },
                        },
                    },
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        metadata = tool.metadata
        openapi = metadata["openapi"]

        assert {p.name for p in tool.parameters} >= {
            "tenantId",
            "orderId",
            "preview",
            "X-Site-No",
            "status",
            "shipping",
        }
        assert metadata["request_content_type"] == "application/json"
        assert metadata["response_content_type"] == "*/*"
        assert metadata["response_status"] == "201"
        assert openapi["summary"] == "주문 수정"
        assert openapi["path_params"] == ["tenantId", "orderId"]
        assert openapi["input_locations"]["path"] == ["tenantId", "orderId"]
        assert openapi["input_locations"]["query"] == ["preview"]
        assert openapi["input_locations"]["header"] == ["X-Site-No"]
        assert "status" in openapi["input_locations"]["body"]
        assert openapi["request_body"]["required"] is True
        assert openapi["request_body"]["fields"][0]["location"] == "body"
        assert any(
            row["json_path"] == "$.shipping.city" for row in openapi["request_body"]["fields"]
        )
        preview = next(row for row in openapi["parameters"] if row["name"] == "preview")
        assert preview["style"] == "form"
        assert preview["explode"] is False
        assert preview["allowReserved"] is True
        assert preview["default"] is False
        assert preview["examples"][0]["value"] is True
        body_content_types = openapi["request_body"]["content_types"]
        assert [row["content_type"] for row in body_content_types] == [
            "application/json",
            "application/x-www-form-urlencoded",
        ]
        assert body_content_types[0]["selected"] is True
        assert body_content_types[0]["examples"][0]["value"]["status"] == "paid"
        city = next(row for row in openapi["request_body"]["fields"] if row["field_name"] == "city")
        assert city["min_length"] == 2
        assert city["pattern"] == "^[A-Za-z ]+$"
        assert any(row["json_path"] == "$.data.orderId" for row in openapi["response"]["fields"])
        assert openapi["response"]["description"] == "OK"
        responses = {row["status"]: row for row in openapi["responses"]}
        assert responses["201"]["success"] is True
        assert responses["201"]["selected"] is True
        assert responses["400"]["success"] is False
        assert responses["400"]["field_count"] == 2
        assert openapi["error_responses"][0]["status"] == "400"
        assert openapi["examples"]["request_body"][0]["name"] == "paidOrder"
        assert {row["status"] for row in openapi["examples"]["responses"]} == {"201", "400"}
        assert openapi["security"]["requirements"] == [{"siteHeader": []}]
        assert openapi["security"]["schemes"]["siteHeader"]["in"] == "header"
        assert openapi["security"]["schemes"]["bearerAuth"]["scheme"] == "bearer"
        assert any(row["field_name"] == "orderId" for row in metadata["api_contract"]["produces"])
        assert all(row["field_name"] != "errorCode" for row in metadata["api_contract"]["produces"])
        assert any(
            row["field_name"] == "preview" and row["location"] == "query"
            for row in metadata["api_contract"]["consumes"]
        )


class TestIngestOpenAPI31:
    def test_ingest_openapi31(self) -> None:
        tools, spec = ingest_openapi(str(FIXTURES / "minimal_openapi31.json"))
        # listOrders + auto-named post_orders
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "listOrders" in names

    def test_auto_operationid(self) -> None:
        tools, _ = ingest_openapi(str(FIXTURES / "minimal_openapi31.json"))
        names = {t.name for t in tools}
        # POST /orders has no operationId -> auto-generated
        assert "post_orders" in names


# ---------------------------------------------------------------------------
# Feature tests
# ---------------------------------------------------------------------------


class TestSkipDeprecated:
    def test_skip_deprecated(self) -> None:
        spec = _load("petstore_swagger2.json")
        # Mark one operation as deprecated
        spec["paths"]["/pets"]["get"]["deprecated"] = True
        tools, _ = ingest_openapi(spec, skip_deprecated=True)
        names = {t.name for t in tools}
        assert "listPets" not in names

    def test_include_deprecated_when_disabled(self) -> None:
        spec = _load("petstore_swagger2.json")
        spec["paths"]["/pets"]["get"]["deprecated"] = True
        tools, _ = ingest_openapi(spec, skip_deprecated=False)
        names = {t.name for t in tools}
        assert "listPets" in names


class TestResolveRefs:
    def test_resolve_refs(self) -> None:
        """$ref pointers should be resolved (e.g., response schemas)."""
        tools, _ = ingest_openapi(str(FIXTURES / "petstore_swagger2.json"))
        tools_by_name = {t.name: t for t in tools}
        get_pet = tools_by_name["getPet"]
        # response_schema should be the resolved Pet, not a $ref
        resp_schema = get_pet.metadata.get("response_schema", {})
        assert "$ref" not in resp_schema
        assert resp_schema.get("type") == "object"


class TestIngestFromDict:
    def test_ingest_from_dict(self) -> None:
        spec = _load("minimal_openapi30.json")
        tools, normalized = ingest_openapi(spec)
        assert len(tools) == 3
        assert all(isinstance(t, ToolSchema) for t in tools)


class TestRemoteSafety:
    def test_private_host_blocked_by_default(self) -> None:
        with pytest.raises(ConnectionError, match="private or local host"):
            ingest_openapi("http://127.0.0.1/openapi.json")

    def test_private_host_allowed_with_opt_in(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "summary": "List items",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(spec).encode()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "http://127.0.0.1/openapi.json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            tools, _ = ingest_openapi(
                "http://127.0.0.1/openapi.json",
                allow_private_hosts=True,
            )
        assert len(tools) == 1

    def test_response_size_limit(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = (
            b'{"openapi":"3.0.0","info":{"title":"x","version":"1"},"paths":{}}'
        )
        mock_resp.headers = {"Content-Type": "application/json", "Content-Length": "9999999"}
        mock_resp.geturl.return_value = "https://api.example.com/openapi.json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            with pytest.raises(ValueError, match="too large"):
                ingest_openapi(
                    "https://api.example.com/openapi.json",
                    max_response_bytes=64,
                )


class TestDescriptionFallback:
    def test_empty_description_gets_fallback(self) -> None:
        """Operations with no summary/description get auto-generated description."""
        spec: dict = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "tags": ["items"],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        assert len(tools) == 1
        assert tools[0].description == "GET /items [items]"

    def test_empty_description_no_tags(self) -> None:
        """Fallback without tags."""
        spec: dict = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/items/{id}": {
                    "delete": {
                        "operationId": "deleteItem",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        assert tools[0].description == "DELETE /items/{id}"

    def test_has_summary_no_fallback(self) -> None:
        """Operations with summary should keep it, not generate fallback."""
        spec: dict = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "summary": "List all items",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        assert tools[0].description == "List all items"

    def test_whitespace_only_description_gets_fallback(self) -> None:
        """Description that's only whitespace should trigger fallback."""
        spec: dict = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "post": {
                        "operationId": "createItem",
                        "summary": "   ",
                        "description": "  ",
                        "tags": ["items", "crud"],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        assert tools[0].description == "POST /items [items, crud]"


class TestMalformedParameters:
    def test_malformed_param_without_name_skipped(self) -> None:
        """Parameters missing the 'name' field should be silently skipped."""
        spec: dict = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "summary": "List items",
                        "parameters": [
                            # Malformed: missing 'name' field
                            {"in": "query", "schema": {"type": "string"}},
                            # Valid parameter
                            {
                                "name": "limit",
                                "in": "query",
                                "schema": {"type": "integer"},
                                "required": False,
                            },
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        assert len(tools) == 1
        tool = tools[0]
        assert tool.name == "listItems"
        # Only the valid 'limit' parameter should be present
        param_names = [p.name for p in tool.parameters]
        assert param_names == ["limit"]
