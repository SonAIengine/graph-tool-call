"""Tests for graph_tool_call.ingest.openapi."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.execute import HttpExecutor
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

    def test_swagger2_basic_security_becomes_auth_contract_row(self) -> None:
        spec = {
            "swagger": "2.0",
            "info": {"title": "Secure Swagger API", "version": "1.0.0"},
            "host": "api.example.test",
            "basePath": "/v1",
            "schemes": ["https"],
            "securityDefinitions": {
                "basicAuth": {
                    "type": "basic",
                    "description": "HTTP Basic credentials",
                }
            },
            "security": [{"basicAuth": []}],
            "paths": {
                "/orders": {
                    "get": {
                        "operationId": "listOrders",
                        "responses": {
                            "200": {
                                "description": "OK",
                                "schema": {
                                    "type": "object",
                                    "properties": {"orderId": {"type": "string"}},
                                },
                            }
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        server = tools[0].metadata["openapi"]["server"]
        assert tools[0].metadata["base_url"] == "https://api.example.test/v1"
        assert server["source"] == "swagger2"
        assert server["scheme"] == "https"
        assert server["host"] == "api.example.test"
        assert server["base_path"] == "/v1"
        consumes = {
            (row["field_name"], row["location"]): row
            for row in tools[0].metadata["api_contract"]["consumes"]
        }
        auth = consumes[("Authorization", "header")]
        assert auth["kind"] == "auth"
        assert auth["required"] is False
        assert auth["auth_type"] == "basic"
        assert auth["scheme"] == "basic"
        assert auth["security_schemes"] == ["basicAuth"]


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
                                "headers": {
                                    "Location": {
                                        "description": "Created order URL",
                                        "schema": {"type": "string", "format": "uri"},
                                    },
                                    "X-Next-Cursor": {
                                        "schema": {
                                            "type": "string",
                                            "nullable": True,
                                        },
                                        "example": "cursor-2",
                                    },
                                },
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
        assert any(row["field_name"] == "city" for row in body_content_types[0]["fields"])
        assert body_content_types[1]["top_level_fields"][0]["field_name"] == "status"
        city = next(row for row in openapi["request_body"]["fields"] if row["field_name"] == "city")
        assert city["min_length"] == 2
        assert city["pattern"] == "^[A-Za-z ]+$"
        assert any(row["json_path"] == "$.data.orderId" for row in openapi["response"]["fields"])
        assert openapi["response"]["description"] == "OK"
        responses = {row["status"]: row for row in openapi["responses"]}
        assert responses["201"]["success"] is True
        assert responses["201"]["selected"] is True
        assert responses["201"]["header_count"] == 2
        assert responses["201"]["headers"][0]["field_name"] == "Location"
        assert responses["201"]["headers"][0]["json_path"] == "$.headers.Location"
        assert responses["201"]["headers"][0]["format"] == "uri"
        assert responses["201"]["headers"][1]["nullable"] is True
        assert openapi["response"]["headers"][0]["field_name"] == "Location"
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
        assert any(
            row["field_name"] == "Location"
            and row["location"] == "response_header"
            and row["json_path"] == "$.headers.Location"
            for row in metadata["api_contract"]["produces"]
        )
        site_auth = next(
            row for row in metadata["api_contract"]["consumes"] if row["field_name"] == "X-Site-No"
        )
        assert site_auth["kind"] == "auth"
        assert site_auth["required"] is False
        assert site_auth["parameter_required"] is True
        assert site_auth["security_required"] is True
        assert site_auth["security_scheme"] == "siteHeader"
        assert site_auth["security_schemes"] == ["siteHeader"]
        assert site_auth["auth_type"] == "apiKey"
        assert site_auth["credential_name"] == "X-Site-No"

    def test_security_requirements_become_auth_contract_rows(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Secure API", "version": "1.0.0"},
            "components": {
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                    },
                    "sessionCookie": {
                        "type": "apiKey",
                        "in": "cookie",
                        "name": "SESSION",
                    },
                }
            },
            "security": [{"bearerAuth": []}, {"sessionCookie": []}],
            "paths": {
                "/orders": {
                    "get": {
                        "operationId": "listOrders",
                        "parameters": [
                            {
                                "name": "keyword",
                                "in": "query",
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"orderId": {"type": "string"}},
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        consumes = {
            (row["field_name"], row["location"]): row
            for row in tools[0].metadata["api_contract"]["consumes"]
        }

        assert consumes[("keyword", "query")]["kind"] == "data"
        bearer = consumes[("Authorization", "header")]
        assert bearer["kind"] == "auth"
        assert bearer["required"] is False
        assert bearer["security_required"] is True
        assert bearer["security_schemes"] == ["bearerAuth"]
        assert bearer["auth_type"] == "http"
        assert bearer["scheme"] == "bearer"
        assert bearer["bearer_format"] == "JWT"
        cookie = consumes[("SESSION", "cookie")]
        assert cookie["kind"] == "auth"
        assert cookie["required"] is False
        assert cookie["security_schemes"] == ["sessionCookie"]
        assert cookie["credential_name"] == "SESSION"

    def test_status_range_responses_are_classified_for_contracts(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Status Range API", "version": "1.0.0"},
            "paths": {
                "/exports": {
                    "post": {
                        "operationId": "createExport",
                        "responses": {
                            "2XX": {
                                "description": "Any successful export response",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "exportId": {"type": "string"},
                                                "status": {"type": "string"},
                                            },
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
                            "default": {
                                "description": "Unexpected error",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"message": {"type": "string"}},
                                        }
                                    }
                                },
                            },
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        metadata = tools[0].metadata
        openapi = metadata["openapi"]
        responses = {row["status"]: row for row in openapi["responses"]}

        assert metadata["response_status"] == "2XX"
        assert openapi["response"]["status"] == "2XX"
        assert responses["2XX"]["success"] is True
        assert responses["4XX"]["success"] is False
        assert responses["default"]["success"] is False
        assert {row["status"] for row in openapi["error_responses"]} == {"4XX", "default"}
        assert any(row["field_name"] == "exportId" for row in metadata["api_contract"]["produces"])
        assert all(row["field_name"] != "errorCode" for row in metadata["api_contract"]["produces"])

    def test_server_variables_are_expanded_and_preserved(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Server Variable API", "version": "1.0.0"},
            "servers": [
                {
                    "url": "https://{stage}.example.com/{basePath}",
                    "description": "Spec server",
                    "variables": {
                        "stage": {
                            "default": "dev",
                            "enum": ["dev", "stage", "prod"],
                            "description": "Deployment stage",
                        },
                        "basePath": {"default": "api"},
                    },
                }
            ],
            "paths": {
                "/items": {
                    "servers": [
                        {
                            "url": "https://path.example.com/{basePath}",
                            "variables": {"basePath": {"default": "v2"}},
                        }
                    ],
                    "get": {
                        "operationId": "listItems",
                        "servers": [
                            {
                                "url": "https://{tenant}.example.com/{basePath}",
                                "description": "Operation server",
                                "variables": {
                                    "tenant": {
                                        "default": "acme",
                                        "enum": ["acme", "demo"],
                                    },
                                    "basePath": {"default": "admin"},
                                },
                            },
                            {"url": "https://fallback.example.com"},
                        ],
                        "responses": {"200": {"description": "OK"}},
                    },
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        metadata = tools[0].metadata
        server = metadata["openapi"]["server"]

        assert metadata["base_url"] == "https://acme.example.com/admin"
        assert server["source"] == "operation"
        assert server["url"] == "https://acme.example.com/admin"
        assert server["raw_url"] == "https://{tenant}.example.com/{basePath}"
        assert [row["url"] for row in server["servers"]] == [
            "https://acme.example.com/admin",
            "https://fallback.example.com",
        ]
        variables = {row["name"]: row for row in server["variables"]}
        assert variables["tenant"]["default"] == "acme"
        assert variables["tenant"]["enum"] == ["acme", "demo"]
        assert variables["basePath"]["default"] == "admin"

    def test_response_envelope_aliases_are_preserved_for_execution(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Commerce API", "version": "1.0.0"},
            "paths": {
                "/goods/search": {
                    "get": {
                        "operationId": "searchGoods",
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "code": {"type": "string"},
                                                "message": {"type": "string"},
                                                "data": {
                                                    "type": "object",
                                                    "properties": {
                                                        "items": {
                                                            "type": "array",
                                                            "items": {
                                                                "type": "object",
                                                                "properties": {
                                                                    "goodsNo": {"type": "string"},
                                                                    "goodsNm": {"type": "string"},
                                                                },
                                                            },
                                                        },
                                                        "totalCount": {"type": "integer"},
                                                    },
                                                },
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        metadata = tools[0].metadata
        response = metadata["openapi"]["response"]

        assert response["envelope"]["wrapper_path"] == "$.data"
        assert response["envelope"]["collection_path"] == "$.data.items[*]"
        assert response["envelope"]["metadata_fields"] == ["code", "message"]
        fields = {row["field_name"]: row for row in response["fields"]}
        goods_no = fields["goodsNo"]
        assert goods_no["response_envelope_path"] == "$.data"
        assert goods_no["response_collection_path"] == "$.data.items[*]"
        assert "$.body.data.items[*].goodsNo" in goods_no["value_path_aliases"]
        assert "$.items[*].goodsNo" in goods_no["value_path_aliases"]
        assert "$.goodsNo" in goods_no["value_path_aliases"]

        produces = {row["field_name"]: row for row in metadata["api_contract"]["produces"]}
        assert produces["goodsNo"]["response_envelope_path"] == "$.data"
        assert produces["goodsNo"]["response_collection_path"] == "$.data.items[*]"
        assert "$.body.data.items[*].goodsNo" in produces["goodsNo"]["value_path_aliases"]

    def test_generic_schemas_use_examples_for_io_contract_and_body_shape(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Example Commerce API", "version": "1.0.0"},
            "paths": {
                "/goods/search": {
                    "post": {
                        "operationId": "searchGoodsByExample",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"},
                                    "example": {
                                        "keyword": "shirt",
                                        "filters": {"brandNo": "B1"},
                                        "memo": "x" * 2500,
                                    },
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"},
                                        "example": {
                                            "code": "OK",
                                            "message": "success",
                                            "data": {
                                                "items": [
                                                    {
                                                        "goodsNo": "G1",
                                                        "goodsNm": "Oxford shirt",
                                                        "largeText": "x" * 2500,
                                                    }
                                                ],
                                                "totalCount": 1,
                                            },
                                        },
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        metadata = tool.metadata
        param_names = {param.name for param in tool.parameters}

        assert {"keyword", "filters"} <= param_names
        request_body = metadata["openapi"]["request_body"]
        request_fields = {row["field_name"]: row for row in request_body["fields"]}
        assert request_fields["brandNo"]["json_path"] == "$.filters.brandNo"
        assert request_fields["brandNo"]["schema_inferred_from"] == "example"
        assert request_fields["brandNo"]["example_source"] == "request_body_example"
        assert "brandNo" in metadata["openapi"]["input_locations"]["body"]

        response = metadata["openapi"]["response"]
        response_fields = {row["field_name"]: row for row in response["fields"]}
        assert response["envelope"]["wrapper_path"] == "$.data"
        assert response["envelope"]["collection_path"] == "$.data.items[*]"
        assert response_fields["goodsNo"]["json_path"] == "$.data.items[*].goodsNo"
        assert response_fields["goodsNo"]["schema_inferred_from"] == "example"
        assert response_fields["goodsNo"]["example_status"] == "200"

        produces = {row["field_name"]: row for row in metadata["api_contract"]["produces"]}
        consumes = {row["field_name"]: row for row in metadata["api_contract"]["consumes"]}
        assert produces["goodsNo"]["response_collection_path"] == "$.data.items[*]"
        assert consumes["brandNo"]["json_path"] == "$.filters.brandNo"
        assert consumes["brandNo"]["schema_inferred_from"] == "example"

        request = HttpExecutor("https://api.example.com").build_request(
            tool,
            {"keyword": "shirt", "brandNo": "B1"},
        )
        assert request.full_url == "https://api.example.com/goods/search"
        assert json.loads(request.data.decode("utf-8")) == {
            "keyword": "shirt",
            "filters": {"brandNo": "B1"},
        }

    def test_additional_properties_maps_are_preserved_in_contract_metadata(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Map Commerce API", "version": "1.0.0"},
            "paths": {
                "/goods/maps": {
                    "post": {
                        "operationId": "upsertGoodsMap",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["attributes"],
                                        "properties": {
                                            "attributes": {
                                                "type": "object",
                                                "additionalProperties": {
                                                    "type": "object",
                                                    "required": ["value"],
                                                    "properties": {
                                                        "value": {
                                                            "type": "string",
                                                            "description": "속성 값",
                                                        }
                                                    },
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "data": {
                                                    "type": "object",
                                                    "additionalProperties": {
                                                        "type": "object",
                                                        "properties": {
                                                            "goodsNo": {"type": "string"},
                                                            "goodsNm": {"type": "string"},
                                                        },
                                                    },
                                                }
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        openapi = tool.metadata["openapi"]
        request_fields = {row["field_name"]: row for row in openapi["request_body"]["fields"]}
        response_fields = {row["field_name"]: row for row in openapi["response"]["fields"]}

        assert request_fields["value"]["json_path"] == "$.attributes.*.value"
        assert request_fields["value"]["required"] is False
        assert request_fields["value"]["additional_properties"] is True
        assert request_fields["value"]["map_value"] is True
        assert response_fields["goodsNo"]["json_path"] == "$.data.*.goodsNo"
        assert response_fields["goodsNo"]["map_key_placeholder"] == "*"

        consumes = {row["field_name"]: row for row in tool.metadata["api_contract"]["consumes"]}
        produces = {row["field_name"]: row for row in tool.metadata["api_contract"]["produces"]}
        assert consumes["value"]["map_value"] is True
        assert consumes["value"]["required"] is False
        assert produces["goodsNo"]["additional_properties"] is True

        request = HttpExecutor("https://api.example.com").build_request(
            tool,
            {"attributes": {"color": {"value": "red"}}},
        )
        assert json.loads(request.data.decode("utf-8")) == {
            "attributes": {"color": {"value": "red"}}
        }

    def test_parameter_content_schema_is_preserved_for_json_query_parameter(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Parameter Content API", "version": "1.0.0"},
            "paths": {
                "/goods/search": {
                    "get": {
                        "operationId": "searchGoods",
                        "parameters": [
                            {
                                "name": "filter",
                                "in": "query",
                                "required": True,
                                "description": "검색 필터",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["status"],
                                            "properties": {
                                                "status": {
                                                    "type": "string",
                                                    "enum": ["SALE", "SOLD_OUT"],
                                                },
                                                "brandNo": {
                                                    "type": "string",
                                                    "description": "브랜드 번호",
                                                },
                                            },
                                        },
                                        "example": {"status": "SALE", "brandNo": "B1"},
                                    }
                                },
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        openapi = tool.metadata["openapi"]
        parameter_rows = {row["name"]: row for row in openapi["parameters"]}
        filter_param = next(param for param in tool.parameters if param.name == "filter")
        filter_row = parameter_rows["filter"]

        assert filter_param.type == "object"
        assert filter_param.required is True
        assert "brandNo" in filter_param.description
        assert filter_row["content_type"] == "application/json"
        assert filter_row["content_schema_type"] == "object"
        assert filter_row["content_types"][0]["selected"] is True
        assert filter_row["content_types"][0]["examples"][0]["value"] == {
            "status": "SALE",
            "brandNo": "B1",
        }
        content_fields = {row["field_name"]: row for row in filter_row["content_fields"]}
        assert content_fields["status"]["enum"] == ["SALE", "SOLD_OUT"]
        assert content_fields["brandNo"]["description"] == "브랜드 번호"
        assert openapi["input_locations"]["query"] == ["filter"]

        consumes = {row["field_name"]: row for row in tool.metadata["api_contract"]["consumes"]}
        assert consumes["filter"]["content_type"] == "application/json"
        assert consumes["filter"]["content_fields"][0]["location"] == "query"

        request = HttpExecutor("https://api.example.com").build_request(
            tool,
            {"filter": {"status": "SALE", "brandNo": "B1"}},
        )
        parsed = urlparse(request.full_url)
        assert parsed.path == "/goods/search"
        assert json.loads(parse_qs(parsed.query)["filter"][0]) == {
            "brandNo": "B1",
            "status": "SALE",
        }

    def test_nullable_openapi31_body_fields_are_preserved_and_executable(self) -> None:
        spec = {
            "openapi": "3.1.0",
            "info": {"title": "Nullable Order API", "version": "1.0.0"},
            "paths": {
                "/orders/{orderId}": {
                    "patch": {
                        "operationId": "updateOrderMemo",
                        "parameters": [
                            {
                                "name": "orderId",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["memo", "status"],
                                        "properties": {
                                            "memo": {
                                                "anyOf": [
                                                    {"type": "string"},
                                                    {"type": "null"},
                                                ],
                                                "description": "주문 메모",
                                            },
                                            "status": {"type": ["string", "null"]},
                                            "legacyCount": {
                                                "type": "integer",
                                                "x-nullable": True,
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        tools, normalized = ingest_openapi(spec)
        tool = tools[0]
        consumes = {row["field_name"]: row for row in tool.metadata["api_contract"]["consumes"]}
        params = {param.name: param for param in tool.parameters}

        assert (
            normalized.paths["/orders/{orderId}"]["patch"]["requestBody"]["content"][
                "application/json"
            ]["schema"]["properties"]["memo"]["nullable"]
            is True
        )
        assert params["memo"].required is True
        assert consumes["memo"]["nullable"] is True
        assert consumes["status"]["nullable"] is True
        assert consumes["legacyCount"]["nullable"] is True

        request = HttpExecutor("https://api.example.com").build_request(
            tool,
            {"orderId": "O1", "memo": None, "status": None},
        )

        assert json.loads(request.data.decode("utf-8")) == {
            "memo": None,
            "status": None,
        }

    def test_response_links_are_preserved_as_api_contract_evidence(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Linked API", "version": "1.0.0"},
            "paths": {
                "/signup-sessions": {
                    "post": {
                        "operationId": "createSignupSession",
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
                                        "operationId": "getProfile",
                                        "parameters": {
                                            "userId": "$response.body#/id",
                                            "traceId": "$response.header.X-Trace-Id",
                                        },
                                        "description": "Use the created user id.",
                                        "server": {
                                            "url": "https://{tenant}.example.com/profile",
                                            "variables": {
                                                "tenant": {
                                                    "default": "acme",
                                                    "enum": ["acme", "demo"],
                                                }
                                            },
                                        },
                                    }
                                },
                            }
                        },
                    }
                },
                "/profiles/{userId}": {
                    "get": {
                        "operationId": "getProfile",
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
        create = {tool.name: tool for tool in tools}["createSignupSession"]
        response_links = create.metadata["openapi"]["response"]["links"]
        contract_links = create.metadata["api_contract"]["links"]

        assert response_links[0]["operation_id"] == "getProfile"
        assert response_links[0]["parameters"][0] == {
            "field_name": "userId",
            "parameter": "userId",
            "expression": "$response.body#/id",
            "source": "response_body",
            "json_path": "$.id",
        }
        assert response_links[0]["parameters"][1]["source"] == "response_header"
        assert response_links[0]["parameters"][1]["header"] == "X-Trace-Id"
        assert response_links[0]["server_url"] == "https://acme.example.com/profile"
        assert response_links[0]["server"]["raw_url"] == "https://{tenant}.example.com/profile"
        assert response_links[0]["server"]["variables"][0]["default"] == "acme"
        assert contract_links[0]["source_operation_id"] == "createSignupSession"
        assert contract_links[0]["source_status"] == "201"
        assert contract_links[0]["success"] is True

    def test_query_object_parameter_metadata_expands_to_inner_fields(self) -> None:
        """Query DTO wrappers should not leak into graph/Planflow contracts."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Commerce BO API", "version": "1.0.0"},
            "paths": {
                "/goods/search": {
                    "get": {
                        "operationId": "searchGoods",
                        "parameters": [
                            {
                                "name": "searchRequest",
                                "in": "query",
                                "style": "form",
                                "explode": True,
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "brandNo": {
                                            "type": "string",
                                            "description": "브랜드 번호",
                                            "example": "B1",
                                        },
                                        "goodsNo": {
                                            "type": "string",
                                            "description": "상품 번호",
                                        },
                                        "saleStatusCd": {
                                            "type": "string",
                                            "enum": ["SALE", "SOLD_OUT"],
                                        },
                                    },
                                },
                            },
                            {
                                "name": "goodsNo",
                                "in": "query",
                                "schema": {"type": "string"},
                            },
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        openapi = tool.metadata["openapi"]

        assert {param.name for param in tool.parameters} == {
            "brandNo",
            "goodsNo",
            "saleStatusCd",
        }
        parameter_rows = {row["name"]: row for row in openapi["parameters"]}
        assert "searchRequest" not in parameter_rows
        assert parameter_rows["brandNo"]["in"] == "query"
        assert parameter_rows["brandNo"]["schema_expanded_from"] == "searchRequest"
        assert parameter_rows["brandNo"]["schema_expansion"] == "query_object_parameter"
        assert parameter_rows["brandNo"]["description"] == "브랜드 번호"
        assert parameter_rows["saleStatusCd"]["enum"] == ["SALE", "SOLD_OUT"]
        assert openapi["input_locations"]["query"] == ["brandNo", "saleStatusCd", "goodsNo"]

        consumes = {
            (row["field_name"], row["location"]): row
            for row in tool.metadata["api_contract"]["consumes"]
        }
        assert ("searchRequest", "query") not in consumes
        assert consumes[("brandNo", "query")]["schema_expanded_from"] == "searchRequest"
        assert consumes[("saleStatusCd", "query")]["enum"] == ["SALE", "SOLD_OUT"]

        request = HttpExecutor("https://api.example.com").build_request(
            tool,
            {"brandNo": "B1", "goodsNo": "G1"},
        )
        parsed = urlparse(request.full_url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.example.com"
        assert parsed.path == "/goods/search"
        assert parse_qs(parsed.query) == {"brandNo": ["B1"], "goodsNo": ["G1"]}

    def test_query_object_parameter_allof_metadata_expands_to_inner_fields(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Commerce BO API", "version": "1.0.0"},
            "paths": {
                "/goods/search": {
                    "get": {
                        "operationId": "searchGoods",
                        "parameters": [
                            {
                                "name": "searchRequest",
                                "in": "query",
                                "style": "form",
                                "explode": True,
                                "schema": {
                                    "allOf": [
                                        {
                                            "type": "object",
                                            "required": ["brandNo"],
                                            "properties": {
                                                "brandNo": {
                                                    "type": "string",
                                                    "description": "브랜드 번호",
                                                }
                                            },
                                        },
                                        {
                                            "type": "object",
                                            "properties": {
                                                "goodsNm": {
                                                    "type": "string",
                                                    "description": "상품명",
                                                }
                                            },
                                        },
                                    ]
                                },
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        openapi = tool.metadata["openapi"]

        params = {param.name: param for param in tool.parameters}
        assert set(params) == {"brandNo", "goodsNm"}
        assert params["brandNo"].required is True
        parameter_rows = {row["name"]: row for row in openapi["parameters"]}
        assert "searchRequest" not in parameter_rows
        assert parameter_rows["brandNo"]["required"] is True
        assert parameter_rows["goodsNm"]["schema_expanded_from"] == "searchRequest"

        consumes = {row["field_name"]: row for row in tool.metadata["api_contract"]["consumes"]}
        assert set(consumes) == {"brandNo", "goodsNm"}
        assert consumes["brandNo"]["required"] is True

    def test_deepobject_query_parameter_keeps_wrapper_contract(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Search API", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "searchItems",
                        "parameters": [
                            {
                                "name": "filter",
                                "in": "query",
                                "style": "deepObject",
                                "explode": True,
                                "schema": {
                                    "type": "object",
                                    "properties": {"status": {"type": "string"}},
                                },
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        openapi = tool.metadata["openapi"]

        assert [param.name for param in tool.parameters] == ["filter"]
        assert [row["name"] for row in openapi["parameters"]] == ["filter"]
        assert openapi["parameters"][0]["style"] == "deepObject"
        assert openapi["input_locations"]["query"] == ["filter"]
        assert tool.metadata["api_contract"]["consumes"][0]["field_name"] == "filter"

        request = HttpExecutor("https://api.example.com").build_request(
            tool,
            {"filter": {"status": "paid"}},
        )
        parsed = urlparse(request.full_url)
        assert parsed.path == "/items"
        assert parse_qs(parsed.query) == {"filter[status]": ["paid"]}

    def test_readonly_writeonly_fields_respect_request_response_direction(self) -> None:
        """Direction-only OpenAPI fields should not pollute inverse IO contracts."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Users API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["email", "password", "id"],
                                        "properties": {
                                            "id": {"type": "string", "readOnly": True},
                                            "email": {"type": "string"},
                                            "password": {"type": "string", "writeOnly": True},
                                            "profile": {
                                                "type": "object",
                                                "readOnly": True,
                                                "properties": {"displayName": {"type": "string"}},
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "201": {
                                "description": "Created",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "string", "readOnly": True},
                                                "email": {"type": "string"},
                                                "password": {
                                                    "type": "string",
                                                    "writeOnly": True,
                                                },
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        openapi = tool.metadata["openapi"]
        request_fields = {row["field_name"]: row for row in openapi["request_body"]["all_fields"]}
        top_level_fields = {
            row["field_name"]: row
            for row in openapi["request_body"]["content_types"][0]["top_level_fields"]
        }
        response_fields = {row["field_name"]: row for row in openapi["response"]["fields"]}
        consumes = {row["field_name"]: row for row in tool.metadata["api_contract"]["consumes"]}
        produces = {row["field_name"]: row for row in tool.metadata["api_contract"]["produces"]}

        assert {param.name for param in tool.parameters} >= {"email", "password"}
        assert "id" not in {param.name for param in tool.parameters}
        assert "profile" not in {param.name for param in tool.parameters}
        assert "id" not in request_fields
        assert "id" not in top_level_fields
        assert "profile" not in top_level_fields
        assert top_level_fields["password"]["write_only"] is True
        assert "displayName" not in request_fields
        assert request_fields["password"]["write_only"] is True
        assert "password" not in response_fields
        assert response_fields["id"]["read_only"] is True
        assert "id" not in consumes
        assert "displayName" not in consumes
        assert consumes["password"]["write_only"] is True
        assert "password" not in produces
        assert produces["id"]["read_only"] is True

    def test_oneof_request_body_exposes_all_variant_fields(self) -> None:
        """Request body alternatives should surface every valid branch field."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Payment API", "version": "1.0.0"},
            "paths": {
                "/payments": {
                    "post": {
                        "operationId": "createPayment",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "allOf": [
                                            {
                                                "type": "object",
                                                "required": ["merchantNo"],
                                                "properties": {"merchantNo": {"type": "string"}},
                                            },
                                            {
                                                "oneOf": [
                                                    {
                                                        "type": "object",
                                                        "required": ["paymentType", "cardNumber"],
                                                        "properties": {
                                                            "paymentType": {
                                                                "type": "string",
                                                                "enum": ["card"],
                                                            },
                                                            "cardNumber": {"type": "string"},
                                                        },
                                                    },
                                                    {
                                                        "type": "object",
                                                        "required": ["paymentType", "bankCode"],
                                                        "properties": {
                                                            "paymentType": {
                                                                "type": "string",
                                                                "enum": ["bank"],
                                                            },
                                                            "bankCode": {"type": "string"},
                                                        },
                                                    },
                                                ]
                                            },
                                        ],
                                    }
                                }
                            },
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        openapi = tool.metadata["openapi"]
        params = {param.name: param for param in tool.parameters}
        request_fields = {row["field_name"]: row for row in openapi["request_body"]["all_fields"]}
        top_level_fields = {
            row["field_name"]: row for row in openapi["request_body"]["all_top_level_fields"]
        }
        consumes = {row["field_name"]: row for row in tool.metadata["api_contract"]["consumes"]}

        assert set(params) == {"merchantNo", "paymentType", "cardNumber", "bankCode"}
        assert params["merchantNo"].required is True
        assert params["cardNumber"].required is False
        assert params["bankCode"].required is False
        assert request_fields["merchantNo"]["required"] is True
        assert request_fields["paymentType"]["enum"] == ["card", "bank"]
        assert request_fields["paymentType"]["required"] is False
        assert request_fields["paymentType"]["required_in_branch"] is True
        assert request_fields["paymentType"]["schema_combinator"] == "oneOf"
        assert request_fields["paymentType"]["schema_branches"] == [0, 1]
        assert top_level_fields["bankCode"]["schema_branch"] == 1
        assert consumes["merchantNo"]["required"] is True
        assert consumes["paymentType"]["enum"] == ["card", "bank"]
        assert consumes["cardNumber"]["required"] is False

    def test_discriminator_request_body_preserves_branch_selection_hints(self) -> None:
        """Discriminator mapping should survive $ref resolution into execution metadata."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Payment API", "version": "1.0.0"},
            "components": {
                "schemas": {
                    "CardPayment": {
                        "type": "object",
                        "required": ["cardNumber"],
                        "properties": {"cardNumber": {"type": "string"}},
                    },
                    "BankPayment": {
                        "type": "object",
                        "required": ["bankCode"],
                        "properties": {"bankCode": {"type": "string"}},
                    },
                }
            },
            "paths": {
                "/payments": {
                    "post": {
                        "operationId": "createPayment",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "oneOf": [
                                            {"$ref": "#/components/schemas/CardPayment"},
                                            {"$ref": "#/components/schemas/BankPayment"},
                                        ],
                                        "discriminator": {
                                            "propertyName": "paymentType",
                                            "mapping": {
                                                "card": "#/components/schemas/CardPayment",
                                                "bank": "#/components/schemas/BankPayment",
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        params = {param.name: param for param in tool.parameters}
        fields = {
            row["field_name"]: row for row in tool.metadata["openapi"]["request_body"]["all_fields"]
        }
        top_level = {
            row["field_name"]: row
            for row in tool.metadata["openapi"]["request_body"]["all_top_level_fields"]
        }
        consumes = {row["field_name"]: row for row in tool.metadata["api_contract"]["consumes"]}

        assert set(params) == {"paymentType", "cardNumber", "bankCode"}
        assert params["paymentType"].enum == ["card", "bank"]
        assert fields["paymentType"]["discriminator_values"] == ["card", "bank"]
        assert "discriminator_value" not in fields["paymentType"]
        assert fields["cardNumber"]["schema_ref"] == "#/components/schemas/CardPayment"
        assert fields["cardNumber"]["discriminator_value"] == "card"
        assert top_level["bankCode"]["schema_ref"] == "#/components/schemas/BankPayment"
        assert consumes["paymentType"]["enum"] == ["card", "bank"]
        assert consumes["bankCode"]["discriminator_value"] == "bank"

    def test_oneof_response_exposes_all_variant_fields(self) -> None:
        """Response alternatives should contribute produces for search and graph edges."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Payment API", "version": "1.0.0"},
            "paths": {
                "/payments/{paymentNo}": {
                    "get": {
                        "operationId": "getPayment",
                        "parameters": [
                            {
                                "name": "paymentNo",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "oneOf": [
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "paymentNo": {"type": "string"},
                                                        "cardApprovalNo": {"type": "string"},
                                                    },
                                                },
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "paymentNo": {"type": "string"},
                                                        "bankTransferNo": {"type": "string"},
                                                    },
                                                },
                                            ]
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        tools, _ = ingest_openapi(spec)
        response_fields = {
            row["field_name"]: row for row in tools[0].metadata["openapi"]["response"]["fields"]
        }
        produces = {row["field_name"]: row for row in tools[0].metadata["api_contract"]["produces"]}

        assert set(response_fields) == {"paymentNo", "cardApprovalNo", "bankTransferNo"}
        assert response_fields["paymentNo"]["schema_branches"] == [0, 1]
        assert produces["bankTransferNo"]["schema_branch"] == 1


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
