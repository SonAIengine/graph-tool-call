"""Tests for graph_tool_call.ingest.normalizer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_tool_call.ingest.normalizer import (
    NormalizedSpec,
    SpecVersion,
    detect_version,
    normalize,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# detect_version
# ---------------------------------------------------------------------------


class TestDetectVersion:
    def test_detect_swagger20(self) -> None:
        spec = _load("petstore_swagger2.json")
        assert detect_version(spec) == SpecVersion.SWAGGER_2_0

    def test_detect_openapi30(self) -> None:
        spec = _load("minimal_openapi30.json")
        assert detect_version(spec) == SpecVersion.OPENAPI_3_0

    def test_detect_openapi31(self) -> None:
        spec = _load("minimal_openapi31.json")
        assert detect_version(spec) == SpecVersion.OPENAPI_3_1

    def test_detect_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot detect spec version"):
            detect_version({"info": {"title": "no version"}})


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_normalize_swagger20_converts_definitions(self) -> None:
        spec = _load("petstore_swagger2.json")
        result = normalize(spec)
        assert isinstance(result, NormalizedSpec)
        assert result.version == SpecVersion.SWAGGER_2_0
        # definitions should be promoted to schemas
        assert "Pet" in result.schemas
        assert "NewPet" in result.schemas

    def test_normalize_swagger20_converts_host_to_servers(self) -> None:
        spec = _load("petstore_swagger2.json")
        result = normalize(spec)
        assert len(result.servers) >= 1
        assert result.servers[0]["url"] == "https://petstore.example.com/v1"

    def test_normalize_swagger20_preserves_consumes_produces(self) -> None:
        spec = _load("petstore_swagger2.json")
        result = normalize(spec)
        assert result.info.get("consumes") == ["application/json"]
        assert result.info.get("produces") == ["application/json"]

    def test_normalize_openapi31_nullable(self) -> None:
        spec = _load("minimal_openapi31.json")
        result = normalize(spec)
        assert result.version == SpecVersion.OPENAPI_3_1
        # anyOf with null should be converted to nullable
        new_order = result.schemas.get("NewOrder", {})
        note_prop = new_order.get("properties", {}).get("note", {})
        assert note_prop.get("nullable") is True
        assert note_prop.get("type") == "string"
        # anyOf should have been flattened away
        assert "anyOf" not in note_prop

    def test_normalize_nullable_dialect_variants(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Nullable API", "version": "1.0.0"},
            "paths": {
                "/orders": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "memo": {
                                                "type": ["string", "null"],
                                                "nullable": False,
                                            },
                                            "legacyCount": {
                                                "type": "integer",
                                                "x-nullable": True,
                                            },
                                            "status": {
                                                "oneOf": [
                                                    {"type": "string", "enum": ["READY"]},
                                                    {"type": "null"},
                                                ]
                                            },
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "NullableFilter": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": ["string", "null"]},
                            "amount": {"type": "number", "x-nullable": True},
                        },
                    }
                }
            },
        }

        result = normalize(spec)
        schema_props = result.schemas["NullableFilter"]["properties"]
        body_props = result.paths["/orders"]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]["properties"]

        assert schema_props["keyword"] == {"type": "string", "nullable": True}
        assert schema_props["amount"] == {"type": "number", "nullable": True}
        assert body_props["memo"] == {"type": "string", "nullable": True}
        assert body_props["legacyCount"] == {"type": "integer", "nullable": True}
        assert body_props["status"]["type"] == "string"
        assert body_props["status"]["nullable"] is True
        assert body_props["status"]["enum"] == ["READY"]
        assert "oneOf" not in body_props["status"]

    def test_normalize_swagger20_x_nullable(self) -> None:
        spec = {
            "swagger": "2.0",
            "info": {"title": "Legacy API", "version": "1.0.0"},
            "paths": {},
            "definitions": {
                "LegacyOrder": {
                    "type": "object",
                    "properties": {"memo": {"type": "string", "x-nullable": True}},
                }
            },
        }

        result = normalize(spec)

        assert result.schemas["LegacyOrder"]["properties"]["memo"] == {
            "type": "string",
            "nullable": True,
        }

    def test_auto_generate_operation_id(self) -> None:
        spec = _load("minimal_openapi31.json")
        result = normalize(spec)
        # The POST /orders has no operationId — should be auto-generated
        post_op = result.paths.get("/orders", {}).get("post", {})
        assert post_op.get("operationId") == "post_orders"

    def test_normalize_openapi30_passthrough(self) -> None:
        spec = _load("minimal_openapi30.json")
        result = normalize(spec)
        assert result.version == SpecVersion.OPENAPI_3_0
        assert "User" in result.schemas
        assert "/users" in result.paths
