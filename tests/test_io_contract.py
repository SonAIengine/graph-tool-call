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


def test_extract_leaves_preserves_schema_hints():
    schema = {
        "type": "object",
        "properties": {
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "default": "2026-01-01T00:00:00Z",
                "example": "2026-07-19T12:00:00Z",
                "nullable": True,
                "pattern": "^\\d{4}-",
                "minLength": 10,
                "maxLength": 30,
            },
            "quantity": {
                "type": "integer",
                "minimum": 1,
                "maximum": 99,
            },
        },
    }

    leaves = extract_leaves(schema, base_path="$")
    by_name = {leaf.field_name: leaf for leaf in leaves}

    assert by_name["createdAt"].format == "date-time"
    assert by_name["createdAt"].default == "2026-01-01T00:00:00Z"
    assert by_name["createdAt"].example == "2026-07-19T12:00:00Z"
    assert by_name["createdAt"].nullable is True
    assert by_name["createdAt"].pattern == "^\\d{4}-"
    assert by_name["createdAt"].min_length == 10
    assert by_name["createdAt"].max_length == 30
    assert by_name["quantity"].minimum == 1
    assert by_name["quantity"].maximum == 99


def test_extract_leaves_preserves_read_write_direction_hints():
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "readOnly": True},
            "password": {"type": "string", "writeOnly": True},
            "profile": {
                "type": "object",
                "readOnly": True,
                "properties": {"displayName": {"type": "string"}},
            },
            "auditEvents": {
                "type": "array",
                "writeOnly": True,
                "items": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                },
            },
            "oldField": {"type": "string", "deprecated": True},
        },
    }

    leaves = extract_leaves(schema, base_path="$")
    by_name = {leaf.field_name: leaf for leaf in leaves}

    assert by_name["id"].read_only is True
    assert by_name["password"].write_only is True
    assert by_name["displayName"].read_only is True
    assert by_name["reason"].write_only is True
    assert by_name["oldField"].deprecated is True


def test_extract_leaves_unions_oneof_branches_without_global_required():
    schema = {
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

    leaves = extract_leaves(schema, base_path="$")
    by_name = {leaf.field_name: leaf for leaf in leaves}

    assert set(by_name) == {"paymentType", "cardNumber", "bankCode"}
    assert by_name["paymentType"].enum == ["card", "bank"]
    assert by_name["paymentType"].required is False
    assert by_name["paymentType"].required_in_branch is True
    assert by_name["paymentType"].schema_combinator == "oneOf"
    assert by_name["paymentType"].schema_branch is None
    assert by_name["paymentType"].schema_branch_count == 2
    assert by_name["paymentType"].schema_branches == [0, 1]
    assert by_name["cardNumber"].required is False
    assert by_name["cardNumber"].required_in_branch is True
    assert by_name["cardNumber"].schema_branch == 0
    assert by_name["bankCode"].schema_branch == 1


def test_extract_leaves_unions_anyof_array_item_branches():
    schema = {
        "type": "array",
        "items": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"productNo": {"type": "string"}},
                },
                {
                    "type": "object",
                    "properties": {"couponNo": {"type": "string"}},
                },
            ]
        },
    }

    leaves = extract_leaves(schema, base_path="$.items")
    by_name = {leaf.field_name: leaf for leaf in leaves}

    assert set(by_name) == {"productNo", "couponNo"}
    assert by_name["productNo"].json_path == "$.items[*].productNo"
    assert by_name["productNo"].schema_combinator == "anyOf"
    assert by_name["couponNo"].schema_branch == 1


def test_extract_leaves_preserves_oneof_nested_under_allof():
    schema = {
        "allOf": [
            {
                "type": "object",
                "required": ["orderNo"],
                "properties": {"orderNo": {"type": "string"}},
            },
            {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["cancelReason"],
                        "properties": {"cancelReason": {"type": "string"}},
                    },
                    {
                        "type": "object",
                        "required": ["returnReason"],
                        "properties": {"returnReason": {"type": "string"}},
                    },
                ]
            },
        ]
    }

    leaves = extract_leaves(schema, base_path="$")
    by_name = {leaf.field_name: leaf for leaf in leaves}

    assert set(by_name) == {"orderNo", "cancelReason", "returnReason"}
    assert by_name["orderNo"].required is True
    assert by_name["cancelReason"].required is False
    assert by_name["cancelReason"].required_in_branch is True
    assert by_name["returnReason"].schema_branch == 1


def test_operation_extractors_filter_inverse_direction_fields():
    operation = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["id", "password"],
                        "properties": {
                            "id": {"type": "string", "readOnly": True},
                            "password": {"type": "string", "writeOnly": True},
                        },
                    }
                }
            }
        },
        "responses": {
            "200": {
                "description": "OK",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "readOnly": True},
                                "password": {"type": "string", "writeOnly": True},
                            },
                        }
                    }
                },
            }
        },
    }

    consumes = {leaf.field_name: leaf for leaf in extract_consumes_for_operation(operation)}
    produces = {leaf.field_name: leaf for leaf in extract_produces_for_operation(operation)}

    assert "id" not in consumes
    assert consumes["password"].write_only is True
    assert produces["id"].read_only is True
    assert "password" not in produces


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


def test_extract_produces_uses_wildcard_content_type():
    operation = {
        "responses": {
            "200": {
                "content": {
                    "*/*": {
                        "schema": {
                            "type": "object",
                            "properties": {"orderId": {"type": "string"}},
                        }
                    }
                }
            }
        }
    }
    leaves = extract_produces_for_operation(operation)
    assert [leaf.field_name for leaf in leaves] == ["orderId"]


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
