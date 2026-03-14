"""Tests for automatic dependency detection."""

from __future__ import annotations

from graph_tool_call.analyze.dependency import DetectedRelation, detect_dependencies
from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.ontology.schema import RelationType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pet_tools() -> list[ToolSchema]:
    """Standard Petstore-like CRUD tools for structural tests."""
    return [
        ToolSchema(
            name="listPets",
            description="List all pets",
            metadata={"method": "get", "path": "/pets"},
        ),
        ToolSchema(
            name="createPet",
            description="Create a pet",
            metadata={"method": "post", "path": "/pets"},
        ),
        ToolSchema(
            name="getPet",
            description="Get a pet by ID",
            metadata={"method": "get", "path": "/pets/{petId}"},
        ),
        ToolSchema(
            name="updatePet",
            description="Update a pet",
            metadata={"method": "put", "path": "/pets/{petId}"},
        ),
        ToolSchema(
            name="deletePet",
            description="Delete a pet",
            metadata={"method": "delete", "path": "/pets/{petId}"},
        ),
    ]


def _find_relation(
    relations: list[DetectedRelation],
    source: str,
    target: str,
    relation_type: RelationType,
) -> DetectedRelation | None:
    """Find a specific relation in the list."""
    for r in relations:
        if r.source == source and r.target == target and r.relation_type == relation_type:
            return r
    return None


# ---------------------------------------------------------------------------
# Layer 1: Structural tests
# ---------------------------------------------------------------------------


def test_crud_requires():
    """POST → GET/{id} should produce REQUIRES."""
    tools = _pet_tools()
    relations = detect_dependencies(tools)
    rel = _find_relation(relations, "getPet", "createPet", RelationType.REQUIRES)
    assert rel is not None, "GET single should REQUIRE POST"
    assert rel.confidence >= 0.9
    assert rel.layer == 1


def test_crud_complementary():
    """POST → PUT should produce COMPLEMENTARY."""
    tools = _pet_tools()
    relations = detect_dependencies(tools)
    rel = _find_relation(relations, "createPet", "updatePet", RelationType.COMPLEMENTARY)
    assert rel is not None, "POST and PUT should be COMPLEMENTARY"
    assert rel.confidence >= 0.85
    assert rel.layer == 1


def test_crud_similar():
    """GET (list) and GET/{id} should produce SIMILAR_TO."""
    tools = _pet_tools()
    relations = detect_dependencies(tools)
    rel = _find_relation(relations, "listPets", "getPet", RelationType.SIMILAR_TO)
    assert rel is not None, "GET list and GET single should be SIMILAR_TO"
    assert rel.confidence >= 0.8
    assert rel.layer == 1


def test_crud_conflicts():
    """PUT and DELETE should produce CONFLICTS_WITH."""
    tools = _pet_tools()
    relations = detect_dependencies(tools)
    rel = _find_relation(relations, "updatePet", "deletePet", RelationType.CONFLICTS_WITH)
    assert rel is not None, "PUT and DELETE should CONFLICT"
    assert rel.confidence >= 0.75
    assert rel.layer == 1


def test_crud_precedes():
    """POST → GET ordering should produce PRECEDES."""
    tools = _pet_tools()
    relations = detect_dependencies(tools)
    rel = _find_relation(relations, "createPet", "getPet", RelationType.PRECEDES)
    assert rel is not None, "POST should PRECEDE GET in CRUD lifecycle"
    assert rel.relation_type == RelationType.PRECEDES
    assert rel.confidence >= 0.8
    assert rel.layer == 1


def test_path_hierarchy():
    """Nested paths should produce REQUIRES."""
    tools = [
        ToolSchema(
            name="listUsers",
            description="List users",
            metadata={"method": "get", "path": "/users"},
        ),
        ToolSchema(
            name="listUserOrders",
            description="List orders for a user",
            metadata={"method": "get", "path": "/users/{userId}/orders"},
        ),
    ]
    relations = detect_dependencies(tools)
    rel = _find_relation(relations, "listUserOrders", "listUsers", RelationType.REQUIRES)
    assert rel is not None, "Nested path tool should REQUIRE parent path tool"
    assert rel.confidence >= 0.9
    assert rel.layer == 1


def test_name_based_detection():
    """Creator (POST) tools with matching resource tokens should be detected as dependencies."""
    tools = [
        ToolSchema(
            name="createUser",
            description="Create a new user",
            metadata={"method": "post", "path": "/users"},
        ),
        ToolSchema(
            name="updateUserProfile",
            description="Update user profile",
            parameters=[
                ToolParameter(name="userId", type="string", required=True),
                ToolParameter(name="profileData", type="object", required=True),
            ],
        ),
    ]
    relations = detect_dependencies(tools)
    # "user" token from createUser's name should match "user" in updateUserProfile's params
    user_relations = [
        r
        for r in relations
        if r.layer == 2
        and r.source == "updateUserProfile"
        and r.target == "createUser"
        and r.relation_type == RelationType.REQUIRES
    ]
    assert len(user_relations) > 0, "Name-based detection should find creator dependency"


def test_min_confidence_filter():
    """Relations below min_confidence threshold should be excluded."""
    tools = _pet_tools()
    # With high threshold, some relations should be filtered out
    high_threshold = detect_dependencies(tools, min_confidence=0.99)
    low_threshold = detect_dependencies(tools, min_confidence=0.5)
    assert len(high_threshold) <= len(low_threshold), (
        "Higher threshold should yield fewer or equal relations"
    )
    # With max threshold, nothing should pass
    max_threshold = detect_dependencies(tools, min_confidence=1.0)
    assert len(max_threshold) == 0, "Threshold 1.0 should exclude all relations"


def test_no_self_reference():
    """Same tool should not relate to itself."""
    tools = _pet_tools()
    relations = detect_dependencies(tools, min_confidence=0.0)
    self_refs = [r for r in relations if r.source == r.target]
    assert len(self_refs) == 0, "No self-referencing relations should exist"


def test_response_request_data_flow():
    """Tool A's response schema matching Tool B's request schema → PRECEDES."""
    tools = [
        ToolSchema(
            name="createUser",
            description="Create a new user",
            metadata={
                "method": "post",
                "path": "/users",
                "response_schema": {"$ref": "#/components/schemas/User"},
            },
        ),
        ToolSchema(
            name="updateUser",
            description="Update user profile",
            metadata={
                "method": "put",
                "path": "/users/{userId}",
                "request_body": {"$ref": "#/components/schemas/User"},
            },
        ),
    ]
    relations = detect_dependencies(tools, min_confidence=0.7)
    rel = _find_relation(relations, "createUser", "updateUser", RelationType.PRECEDES)
    assert rel is not None, "POST→PUT should produce PRECEDES"
    assert rel.confidence >= 0.9


def test_response_flow_no_false_positive():
    """Tools with no shared response→request refs should not get PRECEDES from data flow."""
    tools = [
        ToolSchema(
            name="listOrders",
            description="List orders",
            metadata={
                "method": "get",
                "path": "/orders",
                "response_schema": {"$ref": "#/components/schemas/OrderList"},
            },
        ),
        ToolSchema(
            name="createPayment",
            description="Create payment",
            metadata={
                "method": "post",
                "path": "/payments",
                "request_body": {"$ref": "#/components/schemas/Payment"},
            },
        ),
    ]
    relations = detect_dependencies(tools, min_confidence=0.0)
    flow_rels = [r for r in relations if r.evidence and "response feeds into" in r.evidence]
    assert len(flow_rels) == 0, "No data flow PRECEDES between unrelated schemas"


def test_generic_params_filtered():
    """Generic param names like 'id' alone should not cause false matches."""
    tools = [
        ToolSchema(
            name="getItem",
            description="Get an item",
            parameters=[
                ToolParameter(name="id", type="string", required=True),
            ],
        ),
        ToolSchema(
            name="getOrder",
            description="Get an order",
            parameters=[
                ToolParameter(name="id", type="string", required=True),
                ToolParameter(name="status", type="string"),
            ],
        ),
    ]
    relations = detect_dependencies(tools, min_confidence=0.0)
    # Only "id" and "status" are generic — no resource-level overlap expected
    name_based = [r for r in relations if r.layer == 2]
    assert len(name_based) == 0, (
        "Generic params like 'id' and 'status' should not produce name-based relations"
    )
