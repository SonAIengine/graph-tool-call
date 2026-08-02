"""Contract tests for evidence-gated dependency completion."""

from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.graphify import (
    DependencyClosureResult,
    ToolBundle,
    assemble_tool_bundle,
    build_candidate_set,
    complete_target_dependencies,
)
from graph_tool_call.plan import PathSynthesizer


class CharacterCounter:
    def count(self, text: str) -> int:
        return len(text)


def _tool(
    name: str,
    *,
    consumes: list[dict] | None = None,
    produces: list[dict] | None = None,
    action: str = "read",
    method: str | None = None,
    parameters: list[ToolParameter] | None = None,
) -> ToolSchema:
    metadata = {
        "consumes": consumes or [],
        "produces": produces or [],
        "ai_metadata": {"canonical_action": action},
    }
    if method:
        metadata["openapi"] = {"method": method}
    return ToolSchema(
        name=name,
        description=f"{name} description",
        parameters=parameters or [],
        metadata=metadata,
    )


def _field(name: str, semantic: str, *, required: bool = True, kind: str = "data") -> dict:
    return {
        "field_name": name,
        "semantic_tag": semantic,
        "field_type": "string",
        "required": required,
        "kind": kind,
        "contract_source": "api_contract",
    }


def test_public_result_contracts_are_json_serializable():
    closure = DependencyClosureResult(target="target")
    bundle = ToolBundle(
        target="target",
        target_alternatives=[],
        required_tools=[],
        optional_tools=[],
        user_input_slots=[],
        projected_schemas={},
        admitted_tools=["target"],
        omitted_tools=[],
        token_budget={},
        closure_status="ready",
        closure=closure.to_dict(),
    )

    assert closure.to_dict()["complete"] is True
    assert bundle.to_dict()["target"] == "target"


def test_closure_completes_three_hop_required_contract_chain():
    tools = [
        _tool("getInventory", consumes=[_field("skuId", "sku_id")]),
        _tool(
            "getProduct",
            consumes=[_field("productId", "product_id")],
            produces=[_field("skuId", "sku_id", required=False)],
        ),
        _tool(
            "getCategory",
            consumes=[_field("categoryId", "category_id")],
            produces=[_field("productId", "product_id", required=False)],
        ),
        _tool(
            "searchCategories",
            produces=[_field("categoryId", "category_id", required=False)],
            action="search",
        ),
    ]

    result = complete_target_dependencies("getInventory", tools, max_hops=3)

    assert result.complete is True
    assert result.required_dependencies == [
        "getProduct",
        "getCategory",
        "searchCategories",
    ]
    assert [row["producer"] for row in result.dependency_paths] == [
        "getProduct",
        "getCategory",
        "searchCategories",
    ]


def test_closure_excludes_context_auth_and_rejects_incompatible_types():
    target = _tool(
        "getOrder",
        consumes=[
            _field("orderId", "order_id"),
            _field("siteNo", "site_no", kind="context"),
            _field("authorization", "auth", kind="auth"),
        ],
    )
    bad = _tool(
        "countOrders",
        produces=[
            {
                **_field("orderId", "order_id", required=False),
                "field_type": "integer",
            }
        ],
    )

    result = complete_target_dependencies("getOrder", [target, bad])

    assert result.required_dependencies == []
    assert result.unresolved_fields == [
        {
            "tool": "getOrder",
            "field": "orderId",
            "field_key": "order_id",
            "reason": "no_producer",
            "alternatives": [],
        }
    ]


def test_closure_prefers_read_producer_and_keeps_other_producer_as_alternative():
    tools = [
        _tool("getOrder", consumes=[_field("orderId", "order_id")]),
        _tool(
            "searchOrders",
            produces=[_field("orderId", "order_id", required=False)],
            action="search",
        ),
        _tool(
            "createOrder",
            produces=[_field("orderId", "order_id", required=False)],
            action="create",
        ),
    ]

    result = complete_target_dependencies("getOrder", tools)

    assert result.required_dependencies == ["searchOrders"]
    assert result.alternatives_by_field == {}
    assert any(row["reason"] == "mutation_dependency_blocked" for row in result.diagnostics)


def test_read_bundle_blocks_mutating_dependency_and_exposes_safe_input_slot():
    tools = [
        _tool("getSecret", consumes=[_field("secretName", "secret_name")]),
        _tool(
            "createSecret",
            produces=[_field("secretName", "secret_name", required=False)],
            action="create",
            method="POST",
        ),
    ]

    bundle = assemble_tool_bundle("Read the selected secret.", "getSecret", tools)

    assert bundle.required_tools == []
    assert bundle.optional_tools == []
    assert bundle.closure_status == "incomplete"
    assert bundle.user_input_slots == [
        {
            "tool": "getSecret",
            "field": "secretName",
            "field_key": "secret_name",
            "reason": "mutation_not_allowed",
            "blocked_producers": ["createSecret"],
        }
    ]
    assert bundle.closure["safety"] == {
        "allow_mutation": False,
        "mutation_dependencies_allowed": False,
        "query_intent": "read",
    }


def test_bundle_allows_mutating_dependency_only_with_explicit_opt_in():
    tools = [
        _tool("getSecret", consumes=[_field("secretName", "secret_name")]),
        _tool(
            "createSecret",
            produces=[_field("secretName", "secret_name", required=False)],
            action="create",
            method="POST",
        ),
    ]

    bundle = assemble_tool_bundle(
        "Create a secret, then inspect it.",
        "getSecret",
        tools,
        allow_mutation=True,
    )

    assert bundle.required_tools == ["createSecret"]
    assert bundle.closure_status == "ready"
    assert bundle.closure["safety"] == {
        "allow_mutation": True,
        "mutation_dependencies_allowed": True,
        "query_intent": "write",
    }


def test_mutation_opt_in_does_not_override_read_only_query_intent():
    tools = [
        _tool("getSecret", consumes=[_field("secretName", "secret_name")]),
        _tool(
            "createSecret",
            produces=[_field("secretName", "secret_name", required=False)],
            action="create",
            method="POST",
        ),
    ]

    bundle = assemble_tool_bundle(
        "Read the selected secret.",
        "getSecret",
        tools,
        allow_mutation=True,
    )

    assert bundle.required_tools == []
    assert bundle.closure["safety"] == {
        "allow_mutation": True,
        "mutation_dependencies_allowed": False,
        "query_intent": "read",
    }


def test_scope_contract_is_user_input_instead_of_an_automatic_api_call():
    scope_field = {
        **_field("namespace", "namespace"),
        "location": "path",
        "description": "Object name and auth scope for the current request.",
    }
    tools = [
        _tool("listSecrets", consumes=[scope_field]),
        _tool(
            "listNamespaces",
            produces=[_field("namespace", "namespace", required=False)],
            action="search",
        ),
    ]

    result = complete_target_dependencies(
        "listSecrets",
        tools,
        query="List secrets in a namespace.",
    )

    assert result.required_dependencies == []
    assert result.complete is True
    assert result.user_input_slots == [
        {
            "tool": "listSecrets",
            "field": "namespace",
            "field_key": "namespace",
            "reason": "context_input_required",
            "location": "path",
        }
    ]


def test_generic_project_scope_description_does_not_force_context_classification():
    field = {
        **_field("projectId", "project_id"),
        "description": "Identifier defining the project scope of the resource.",
    }
    tools = [
        _tool("getBuild", consumes=[field]),
        _tool(
            "findProjects",
            produces=[_field("projectId", "project_id", required=False)],
            action="search",
        ),
    ]

    result = complete_target_dependencies(
        "getBuild",
        tools,
        query="Find a project and inspect its build.",
    )

    assert result.required_dependencies == ["findProjects"]
    assert result.user_input_slots == []


def test_post_search_semantics_are_not_treated_as_mutation():
    tools = [
        _tool("getOrder", consumes=[_field("orderId", "order_id")]),
        _tool(
            "searchOrders",
            produces=[_field("orderId", "order_id", required=False)],
            action="search",
            method="POST",
        ),
    ]

    result = complete_target_dependencies("getOrder", tools, query="Find an order.")

    assert result.required_dependencies == ["searchOrders"]
    assert result.complete is True


def test_concrete_read_query_keeps_contract_field_as_input_instead_of_cross_resource_call():
    tools = [
        _tool("getPet", consumes=[_field("petId", "pet_id")]),
        _tool(
            "getOrder",
            produces=[_field("petId", "pet_id", required=False)],
            action="read",
        ),
    ]

    result = complete_target_dependencies(
        "getPet",
        tools,
        query="Get the pet with identifier 42.",
    )

    assert result.required_dependencies == []
    assert result.complete is True
    assert result.user_input_slots == [
        {
            "tool": "getPet",
            "field": "petId",
            "field_key": "pet_id",
            "reason": "query_input_required",
            "location": "",
        }
    ]


def test_create_body_fields_are_inputs_without_explicit_discovery_flow():
    tools = [
        _tool("createPet", consumes=[_field("name", "name")], action="create"),
        _tool(
            "listPets",
            produces=[_field("name", "name", required=False)],
            action="search",
        ),
    ]

    result = complete_target_dependencies(
        "createPet",
        tools,
        query="Add a new dog to the pet store.",
    )

    assert result.required_dependencies == []
    assert result.complete is True
    assert result.user_input_slots[0]["reason"] == "query_input_required"


def test_listing_noun_does_not_count_as_an_explicit_discovery_command():
    tools = [
        _tool("getListing", consumes=[_field("listingId", "listing_id")]),
        _tool(
            "searchListings",
            produces=[_field("listingId", "listing_id", required=False)],
            action="search",
        ),
    ]

    result = complete_target_dependencies(
        "getListing",
        tools,
        query="Get the listing details for identifier 42.",
    )

    assert result.required_dependencies == []
    assert result.user_input_slots[0]["reason"] == "query_input_required"


def test_omitted_query_keeps_v1_contract_admission_for_backward_compatibility():
    tools = [
        _tool("getOrder", consumes=[_field("orderId", "order_id")]),
        _tool(
            "searchOrders",
            produces=[_field("orderId", "order_id", required=False)],
            action="search",
        ),
    ]

    result = complete_target_dependencies("getOrder", tools)

    assert result.required_dependencies == ["searchOrders"]
    assert result.safety == {
        "allow_mutation": False,
        "mutation_dependencies_allowed": False,
        "query_intent": "unknown",
    }


def test_name_only_graph_evidence_is_optional_not_auto_selected():
    tools = [_tool("target"), _tool("guessedProducer")]
    graph = {
        "edges": [
            {
                "source": "target",
                "target": "guessedProducer",
                "relation": "requires",
                "confidence": "INFERRED",
                "conf_score": 0.4,
                "evidence_sources": ["name_based"],
            }
        ]
    }

    result = complete_target_dependencies("target", tools, graph=graph)

    assert result.required_dependencies == []
    assert result.optional_dependencies == []


def test_manual_graph_closure_is_directional_and_detects_cycles():
    tools = [_tool("a"), _tool("b"), _tool("c")]
    graph = {"a": ["b"], "b": ["c"], "c": ["a"]}

    result = complete_target_dependencies("a", tools, graph=graph, max_hops=3)

    assert result.required_dependencies == ["b", "c"]
    assert result.cycles == [["a", "b", "c", "a"]]
    assert result.complete is False


def test_produces_for_edge_is_followed_only_from_consumer_to_producer():
    tools = [_tool("producer"), _tool("consumer")]
    graph = {
        "edges": [
            {
                "source": "producer",
                "target": "consumer",
                "relation": "produces_for",
                "confidence": "EXTRACTED",
                "conf_score": 0.9,
            }
        ]
    }

    consumer = complete_target_dependencies("consumer", tools, graph=graph)
    producer = complete_target_dependencies("producer", tools, graph=graph)

    assert consumer.required_dependencies == ["producer"]
    assert producer.required_dependencies == []


def test_unscoped_structural_requires_is_only_an_optional_hint():
    tools = [_tool("target"), _tool("structuralGuess")]
    graph = {
        "edges": [
            {
                "source": "target",
                "target": "structuralGuess",
                "relation": "requires",
                "confidence": "EXTRACTED",
                "conf_score": 0.9,
            }
        ]
    }

    result = complete_target_dependencies("target", tools, graph=graph)

    assert result.required_dependencies == []
    assert result.optional_dependencies == ["structuralGuess"]


def test_manual_requires_edge_remains_auto_selectable():
    tools = [_tool("target"), _tool("manualProducer")]
    graph = {
        "edges": [
            {
                "source": "target",
                "target": "manualProducer",
                "relation": "requires",
                "confidence": "EXTRACTED",
                "conf_score": 0.9,
                "evidence_sources": ["manual"],
                "is_manual": True,
            }
        ]
    }

    result = complete_target_dependencies("target", tools, graph=graph)

    assert result.required_dependencies == ["manualProducer"]


def test_blocked_mutating_graph_hint_is_diagnostic_not_an_unresolved_contract():
    tools = [_tool("target"), _tool("createResource", action="create", method="POST")]
    graph = {"target": ["createResource"]}

    result = complete_target_dependencies(
        "target",
        tools,
        graph=graph,
        query="Inspect the resource.",
    )

    assert result.required_dependencies == []
    assert result.unresolved_fields == []
    assert result.complete is True
    assert result.diagnostics == [
        {
            "reason": "mutation_dependency_blocked",
            "consumer": "target",
            "producer": "createResource",
            "field_key": "__graph__",
            "query_intent": "read",
            "evidence_tier": 1,
        }
    ]


def test_contract_graph_evidence_is_scoped_to_its_required_field():
    tools = [
        _tool(
            "target",
            consumes=[_field("customerId", "customer_id"), _field("orderId", "order_id")],
        ),
        _tool("findCustomer", produces=[_field("customerId", "customer_id", required=False)]),
        _tool("findOrder", produces=[_field("orderId", "order_id", required=False)]),
    ]
    graph = {
        "edges": [
            {
                "source": "target",
                "target": "findCustomer",
                "relation": "requires",
                "confidence": "INFERRED",
                "conf_score": 0.82,
                "evidence_sources": ["api_contract"],
                "data_flow": {
                    "to_field": "customerId",
                    "semantic_tag": "customer_id",
                },
            }
        ]
    }

    result = complete_target_dependencies("target", tools, graph=graph)

    assert result.required_dependencies == ["findCustomer", "findOrder"]
    assert result.complete is True


def test_structural_merge_does_not_bypass_query_conditioned_contract_admission():
    tools = [
        _tool("deleteService", consumes=[_field("name", "service_name")], action="delete"),
        _tool(
            "listServices",
            produces=[_field("name", "service_name", required=False)],
            action="search",
        ),
    ]
    graph = {
        "edges": [
            {
                "source": "deleteService",
                "target": "listServices",
                "relation": "requires",
                "confidence": "EXTRACTED",
                "conf_score": 0.95,
                "evidence_sources": ["api_contract", "structural"],
                "data_flow": {
                    "to_field": "name",
                    "semantic_tag": "service_name",
                },
            }
        ]
    }

    result = complete_target_dependencies(
        "deleteService",
        tools,
        graph=graph,
        query="Delete service alpha.",
    )

    assert result.required_dependencies == []
    assert result.complete is True
    assert result.user_input_slots[0]["reason"] == "query_input_required"


def test_explicit_openapi_link_is_not_suppressed_when_merged_with_contract_evidence():
    tools = [_tool("target"), _tool("linkedProducer")]
    graph = {
        "edges": [
            {
                "source": "target",
                "target": "linkedProducer",
                "relation": "requires",
                "confidence": "EXTRACTED",
                "conf_score": 0.95,
                "evidence_sources": ["api_contract", "openapi_link"],
                "data_flow": {"to_field": "resourceId"},
            }
        ]
    }

    result = complete_target_dependencies("target", tools, graph=graph)

    assert result.required_dependencies == ["linkedProducer"]


def test_zero_hop_budget_does_not_admit_direct_dependency():
    tools = [_tool("target"), _tool("producer")]

    result = complete_target_dependencies(
        "target",
        tools,
        graph={"target": ["producer"]},
        max_hops=0,
    )

    assert result.required_dependencies == []
    assert result.unresolved_fields[0]["reason"] == "max_depth"


def test_available_field_prevents_unnecessary_producer_expansion():
    tools = [
        _tool("getOrder", consumes=[_field("orderId", "order_id")]),
        _tool("searchOrders", produces=[_field("orderId", "order_id", required=False)]),
    ]

    result = complete_target_dependencies(
        "getOrder",
        tools,
        available_fields={"order_id"},
    )

    assert result.required_dependencies == []
    assert result.resolved_fields[0]["source"] == "available_field"


def test_bundle_reserves_budget_for_target_and_required_dependencies():
    tools = [
        _tool(
            "getOrder",
            consumes=[_field("orderId", "order_id")],
            parameters=[ToolParameter("orderId", required=True)],
        ),
        _tool(
            "searchOrders",
            produces=[_field("orderId", "order_id", required=False)],
            parameters=[ToolParameter("keyword", required=True)],
        ),
        _tool("otherTarget", parameters=[ToolParameter("verbose")]),
    ]
    counter = CharacterCounter()
    full = assemble_tool_bundle(
        "Find an order and inspect its details.",
        "getOrder",
        tools,
        target_alternatives=["otherTarget"],
        token_counter=counter,
    )
    required_budget = counter.count(
        __import__("json").dumps(
            [
                full.projected_schemas["getOrder"],
                full.projected_schemas["searchOrders"],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    bundle = assemble_tool_bundle(
        "Find an order and inspect its details.",
        "getOrder",
        tools,
        target_alternatives=["otherTarget"],
        token_budget=required_budget,
        token_counter=counter,
    )

    assert bundle.closure_status == "ready"
    assert bundle.admitted_tools == ["getOrder", "searchOrders"]
    assert bundle.omitted_tools == ["otherTarget"]
    assert bundle.token_budget["admitted_required_tool_count"] == 2


def test_bundle_reports_budget_insufficient_instead_of_silent_partial_closure():
    tools = [
        _tool("target", consumes=[_field("id", "resource_id")]),
        _tool("producer", produces=[_field("id", "resource_id", required=False)]),
    ]

    bundle = assemble_tool_bundle(
        "query",
        "target",
        tools,
        token_budget=1,
        token_counter=CharacterCounter(),
    )

    assert bundle.closure_status == "budget_insufficient"
    assert bundle.admitted_tools == []
    assert bundle.diagnostics[-1]["reason"] == "budget_insufficient"


def test_bundle_stops_when_later_required_dependency_exceeds_budget():
    tools = [
        _tool("target"),
        _tool("firstProducer"),
        _tool(
            "secondProducer",
            parameters=[ToolParameter("veryLongRequiredFieldName", required=True)],
        ),
        _tool("optional"),
    ]
    unlimited = assemble_tool_bundle(
        "query",
        "target",
        tools,
        graph={"target": ["firstProducer"], "firstProducer": ["secondProducer"]},
        target_alternatives=["optional"],
        token_counter=CharacterCounter(),
    )
    required_prefix = [
        unlimited.projected_schemas["target"],
        unlimited.projected_schemas["firstProducer"],
    ]
    budget = CharacterCounter().count(
        __import__("json").dumps(
            required_prefix,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    bundle = assemble_tool_bundle(
        "query",
        "target",
        tools,
        graph={"target": ["firstProducer"], "firstProducer": ["secondProducer"]},
        target_alternatives=["optional"],
        token_budget=budget,
        token_counter=CharacterCounter(),
    )

    assert bundle.admitted_tools == ["target", "firstProducer"]
    assert bundle.omitted_tools == ["secondProducer", "optional"]
    assert bundle.closure_status == "budget_insufficient"


def test_candidate_set_can_opt_into_target_preserving_dependency_closure():
    tools = {
        "target": _tool("target", consumes=[_field("id", "resource_id")]).to_dict(),
        "producer": _tool(
            "producer", produces=[_field("id", "resource_id", required=False)]
        ).to_dict(),
        "otherTarget": _tool("otherTarget").to_dict(),
    }

    result = build_candidate_set(
        ["target", "otherTarget"],
        tools,
        expansion_seed=["target"],
        use_dependency_closure=True,
        max_hops=3,
    )

    assert result["target_candidates"] == ["target", "otherTarget"]
    assert result["candidates"] == ["target", "producer"]
    assert result["producer_candidates"] == ["producer"]
    assert result["dependency_closure_applied"] is True
    assert result["dependency_closure"]["complete"] is True


def test_candidate_set_keeps_mutating_dependency_out_without_explicit_opt_in():
    tools = {
        "target": _tool("target", consumes=[_field("id", "resource_id")]).to_dict(),
        "createResource": _tool(
            "createResource",
            produces=[_field("id", "resource_id", required=False)],
            action="create",
            method="POST",
        ).to_dict(),
    }

    result = build_candidate_set(
        ["target"],
        tools,
        expansion_seed=["target"],
        use_dependency_closure=True,
        query="Read the resource.",
    )

    assert result["candidates"] == ["target"]
    assert result["dependency_closure"]["safety"]["query_intent"] == "read"
    assert result["dependency_closure"]["unresolved_fields"][0]["reason"] == (
        "mutation_not_allowed"
    )


def test_candidate_set_propagates_context_field_names_to_dependency_closure():
    tools = {
        "target": _tool("target", consumes=[_field("workspaceId", "workspace_id")]).to_dict(),
        "listWorkspaces": _tool(
            "listWorkspaces",
            produces=[_field("workspaceId", "workspace_id", required=False)],
            action="search",
        ).to_dict(),
    }

    result = build_candidate_set(
        ["target"],
        tools,
        expansion_seed=["target"],
        use_dependency_closure=True,
        query="Find a workspace and inspect the target.",
        context_field_names={"workspace_id"},
    )

    assert result["candidates"] == ["target"]
    assert result["dependency_closure"]["user_input_slots"][0]["reason"] == (
        "context_input_required"
    )


def test_path_synthesizer_honors_evidence_gated_closure_preference():
    tools = {
        "target": _tool("target", consumes=[_field("id", "resource_id")]).to_dict(),
        "aProducer": _tool(
            "aProducer",
            produces=[{**_field("id", "resource_id", required=False), "json_path": "$.id"}],
        ).to_dict(),
        "bProducer": _tool(
            "bProducer",
            produces=[{**_field("id", "resource_id", required=False), "json_path": "$.id"}],
        ).to_dict(),
    }
    closure = {
        "target": "target",
        "resolved_fields": [
            {
                "tool": "target",
                "field": "id",
                "field_key": "resource_id",
                "source": "producer",
                "producer": "bProducer",
            }
        ],
    }

    plan = PathSynthesizer({"tools": tools}).synthesize(
        target="target",
        dependency_closure=closure,
    )

    assert [step.tool for step in plan.steps] == ["bProducer", "target"]
    synthesis = plan.metadata["synthesis"]
    assert synthesis["dependency_closure"]["target"] == "target"
    assert synthesis["selected_producers"][0]["producer"] == "bProducer"
