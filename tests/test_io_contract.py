"""Unit tests for ``graph_tool_call.ingest.io_contract``.

특히 query/path parameter 의 enum 추출 (리뷰에서 빠뜨려진 부분) 확인.
"""

from __future__ import annotations

from graph_tool_call.ingest.io_contract import (
    extract_consumes_for_operation,
    extract_leaves,
    extract_produces_for_operation,
)

# ─── extract_leaves ──


def test_extract_leaves_object_with_primitives():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
    }
    leaves = extract_leaves(schema, base_path="$")
    by_name = {leaf.field_name: leaf for leaf in leaves}
    assert by_name["name"].required is True
    assert by_name["name"].field_type == "string"
    assert by_name["age"].required is False


def test_extract_leaves_array_of_objects():
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        },
    }
    leaves = extract_leaves(schema, base_path="$.body")
    paths = {leaf.json_path for leaf in leaves}
    assert any("[*]" in p for p in paths), "array → [*] wildcard 경로"


def test_extract_leaves_captures_enum():
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "shipped"]},
        },
    }
    leaves = extract_leaves(schema, base_path="$")
    status = next(leaf for leaf in leaves if leaf.field_name == "status")
    assert status.enum == ["pending", "shipped"]


# ─── consumes — enum 추출 회귀 (리뷰 🟢 항목) ──


def test_query_param_enum_extracted_openapi3():
    """OpenAPI 3.x query param 의 schema.enum 이 FieldLeaf.enum 에 들어가야."""
    operation = {
        "parameters": [
            {
                "name": "sort",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "enum": ["asc", "desc"]},
            },
        ],
        "responses": {"200": {"description": "OK"}},
    }
    leaves = extract_consumes_for_operation(operation)
    by_name = {leaf.field_name: leaf for leaf in leaves}
    assert "sort" in by_name
    assert by_name["sort"].enum == ["asc", "desc"]


def test_query_param_enum_extracted_swagger2():
    """Swagger 2.0 query param 의 enum (parameter level) 도 잡아야."""
    operation = {
        "parameters": [
            {
                "name": "type",
                "in": "query",
                "required": True,
                "type": "string",
                "enum": ["A", "B", "C"],
            },
        ],
        "responses": {"200": {"description": "OK"}},
    }
    leaves = extract_consumes_for_operation(operation, is_swagger2=True)
    type_leaf = next(leaf for leaf in leaves if leaf.field_name == "type")
    assert type_leaf.enum == ["A", "B", "C"]


def test_path_param_enum_extracted():
    """Path param 의 enum 도 동일."""
    operation = {
        "parameters": [
            {
                "name": "kind",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "enum": ["x", "y"]},
            },
        ],
        "responses": {"200": {"description": "OK"}},
    }
    leaves = extract_consumes_for_operation(operation)
    kind = next(leaf for leaf in leaves if leaf.field_name == "kind")
    assert kind.enum == ["x", "y"]


def test_param_without_enum_has_empty_list():
    """enum 없는 일반 param 은 enum=[] 으로 들어가야 (None 아님)."""
    operation = {
        "parameters": [
            {"name": "page", "in": "query", "schema": {"type": "integer"}},
        ],
        "responses": {"200": {"description": "OK"}},
    }
    leaves = extract_consumes_for_operation(operation, required_only=False)
    page = next(leaf for leaf in leaves if leaf.field_name == "page")
    assert page.enum == []


# ─── produces ──


def test_extract_produces_walks_response_body():
    operation = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "data": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }
    leaves = extract_produces_for_operation(operation)
    paths = {leaf.json_path for leaf in leaves}
    assert "$.data.id" in paths


def test_consumes_skips_optional_when_required_only():
    operation = {
        "parameters": [
            {"name": "must", "in": "query", "required": True, "schema": {"type": "string"}},
            {"name": "maybe", "in": "query", "required": False, "schema": {"type": "string"}},
        ],
        "responses": {"200": {"description": "OK"}},
    }
    leaves = extract_consumes_for_operation(operation)
    names = {leaf.field_name for leaf in leaves}
    assert "must" in names
    assert "maybe" not in names
