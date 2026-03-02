"""Tests for graph_tool_call.ingest.openapi."""

from __future__ import annotations

import json
from pathlib import Path

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
