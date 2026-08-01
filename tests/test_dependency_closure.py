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
    parameters: list[ToolParameter] | None = None,
) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=f"{name} description",
        parameters=parameters or [],
        metadata={
            "consumes": consumes or [],
            "produces": produces or [],
            "ai_metadata": {"canonical_action": action},
        },
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
    assert result.alternatives_by_field == {"getOrder.orderId": ["createOrder"]}


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
        "order detail",
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
        "order detail",
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
