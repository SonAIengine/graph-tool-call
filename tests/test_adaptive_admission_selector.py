import json

from graph_tool_call.graphify import (
    TARGET_ADMISSION_POLICY_REVISION,
    TARGET_SELECTOR_POLICY_REVISION,
    admit_target_candidates,
    select_target_candidate,
)


def _tool(
    name: str,
    *,
    resource: str,
    action: str = "read",
    description: str | None = None,
    consumes: list[dict] | None = None,
) -> dict:
    metadata = {
        "ai_metadata": {
            "canonical_action": action,
            "primary_resource": resource,
            "result_shape": "single",
        },
        "openapi": {
            "operation_id": name,
            "summary": description or name,
            "path": f"/api/{resource}/{name}",
            "path_module": resource,
        },
    }
    if consumes:
        metadata["api_contract"] = {"consumes": consumes}
    return {"name": name, "description": description or name, "metadata": metadata}


def test_adaptive_admission_expands_flat_boundary_beyond_fixed_top_five():
    names = [f"getRecordVariant{index}" for index in range(1, 9)]
    tools = {name: _tool(name, resource="record") for name in names}
    results = [{"name": name, "score": 0.02 - index * 0.0001} for index, name in enumerate(names)]

    admission = admit_target_candidates(
        "read record information",
        results,
        tools,
        retrieval_results=results,
        min_candidates=5,
        max_candidates=8,
    )

    assert admission["policy_revision"] == TARGET_ADMISSION_POLICY_REVISION
    assert admission["admitted_target_candidates"] == names
    assert names[5] in admission["admitted_target_candidates"]
    assert admission["score_cliff"] is None
    assert all(row["decision_reason"] == "admitted" for row in admission["admission_signals"])


def test_adaptive_admission_stops_at_strong_action_score_cliff():
    read_names = [f"getProfileVariant{index}" for index in range(1, 6)]
    delete_names = ["deleteProfile", "removeProfile", "revokeProfile"]
    names = [*read_names, *delete_names]
    tools = {
        **{name: _tool(name, resource="profile", action="read") for name in read_names},
        **{name: _tool(name, resource="profile", action="delete") for name in delete_names},
    }
    results = [{"name": name, "score": 0.02} for name in names]

    admission = admit_target_candidates(
        "show profile detail",
        results,
        tools,
        retrieval_results=results,
        min_candidates=5,
        max_candidates=8,
    )

    assert admission["admitted_target_candidates"] == read_names
    assert admission["score_cliff"]["after_rank"] == 5
    assert {row["reason"] for row in admission["dropped_target_candidates"]} == {"score_cliff"}
    assert "score_cliff_detected" in admission["reason_codes"]


def test_adaptive_admission_reports_ambiguous_hard_boundary_and_every_drop():
    names = [f"searchCatalogVariant{index}" for index in range(1, 9)]
    tools = {
        name: _tool(name, resource=f"catalog_{index}", action="search")
        for index, name in enumerate(names)
    }
    results = [{"name": name, "score": 0.02} for name in names]

    admission = admit_target_candidates(
        "search catalog list",
        results,
        tools,
        retrieval_results=results,
        min_candidates=3,
        max_candidates=5,
    )

    assert len(admission["admitted_target_candidates"]) == 5
    assert len(admission["dropped_target_candidates"]) == 3
    assert all(row["reason"] == "candidate_limit" for row in admission["dropped_target_candidates"])
    assert admission["needs_expansion"] is True
    assert admission["recommended_action"] == "expand_candidates"
    assert "ambiguous_admission_boundary" in admission["reason_codes"]


def test_adaptive_admission_preserves_missing_tool_as_structured_diagnostic():
    tools = {"getKnownRecord": _tool("getKnownRecord", resource="record")}

    admission = admit_target_candidates(
        "read record",
        ["getKnownRecord", "getMissingRecord"],
        tools,
        min_candidates=1,
        max_candidates=2,
    )

    assert admission["admitted_target_candidates"] == ["getKnownRecord"]
    assert admission["dropped_target_candidates"] == [
        {
            "name": "getMissingRecord",
            "reason": "tool_metadata_missing",
            "rank": None,
            "selector_score": None,
        }
    ]


def test_adaptive_admission_uses_soft_group_cap_to_reserve_a_distinct_family():
    sibling_names = [f"getAccountVariant{index}" for index in range(1, 7)]
    distinct_name = "getInvoiceRecord"
    names = [*sibling_names, distinct_name]
    tools = {
        **{name: _tool(name, resource="account") for name in sibling_names},
        distinct_name: _tool(distinct_name, resource="invoice"),
    }
    results = [{"name": name, "score": 0.02} for name in names]

    admission = admit_target_candidates(
        "read account and invoice information",
        results,
        tools,
        retrieval_results=results,
        min_candidates=5,
        max_candidates=7,
        max_candidates_per_group=3,
    )

    assert admission["admitted_target_candidates"] == [*sibling_names[:5], distinct_name]
    assert admission["dropped_target_candidates"][0]["reason"] == "semantic_group_cap"


def test_adaptive_admission_honors_projected_schema_token_budget():
    names = ["getAccount", "getInvoice", "getShipment"]
    tools = {name: _tool(name, resource=name.removeprefix("get").lower()) for name in names}

    admission = admit_target_candidates(
        "read account invoice and shipment",
        names,
        tools,
        min_candidates=1,
        max_candidates=3,
        token_budget=250,
        token_counter=lambda text: len(json.loads(text)) * 100,
    )

    assert admission["admitted_target_candidates"] == names[:2]
    assert admission["dropped_target_candidates"] == [
        {
            "name": "getShipment",
            "reason": "token_budget_exceeded",
            "rank": 3,
            "selector_score": admission["admission_signals"][2]["selector_score"],
        }
    ]
    assert admission["token_budget"]["used"] == 200
    assert "token_budget_limited" in admission["reason_codes"]
    assert admission["recommended_action"] == "increase_token_budget"


def test_adaptive_admission_always_keep_replaces_without_exceeding_hard_cap():
    names = [f"getLedgerVariant{index}" for index in range(1, 7)]
    tools = {name: _tool(name, resource="ledger") for name in names}

    admission = admit_target_candidates(
        "read ledger information",
        names,
        tools,
        min_candidates=3,
        max_candidates=3,
        always_keep={names[-1]},
    )

    assert len(admission["admitted_target_candidates"]) == 3
    assert names[-1] in admission["admitted_target_candidates"]
    assert admission["admitted_target_candidates"] == [names[0], names[1], names[-1]]


def test_risk_limited_selector_blocks_override_when_deterministic_winners_are_tied():
    identifier_contract = [
        {
            "field_name": "recordId",
            "semantic_tag": "record_id",
            "description": "Record identifier",
            "required": True,
            "kind": "data",
        }
    ]
    tools = {
        "getRecordDetail": _tool(
            "getRecordDetail",
            resource="record",
            description="Record detail by record id",
            consumes=identifier_contract,
        ),
        "fetchRecordDetail": _tool(
            "fetchRecordDetail",
            resource="record",
            description="Record detail by record id",
            consumes=identifier_contract,
        ),
        "getRecordInfo": _tool(
            "getRecordInfo",
            resource="record",
            description="General record information",
        ),
    }
    results = [
        {"name": "getRecordDetail", "score": 0.02},
        {"name": "fetchRecordDetail", "score": 0.02},
        {"name": "getRecordInfo", "score": 0.019},
    ]

    selection = select_target_candidate(
        "show record detail for record id 42",
        results,
        tools,
        retrieval_results=results,
        llm_target="getRecordInfo",
        policy="risk_limited",
    )

    assert selection["policy_revision"] == TARGET_SELECTOR_POLICY_REVISION
    assert selection["selected_target"] == "getRecordInfo"
    assert selection["overrode_llm"] is False
    assert selection["override_assessment"]["allowed"] is False
    assert "candidate_tie_override_blocked" in selection["reason_codes"]
    assert selection["needs_expansion"] is True
    assert selection["recommended_action"] == "expand_candidates"


def test_risk_limited_selector_allows_clear_contract_backed_override():
    tools = {
        "getRecordDetail": _tool(
            "getRecordDetail",
            resource="record",
            description="Record detail by record id",
            consumes=[
                {
                    "field_name": "recordId",
                    "semantic_tag": "record_id",
                    "description": "Record identifier",
                    "required": True,
                    "kind": "data",
                }
            ],
        ),
        "getRecordInfo": _tool(
            "getRecordInfo",
            resource="record",
            description="General record information",
        ),
    }
    results = [
        {"name": "getRecordDetail", "score": 0.02},
        {"name": "getRecordInfo", "score": 0.019},
    ]

    selection = select_target_candidate(
        "show record detail for record id 42",
        results,
        tools,
        retrieval_results=results,
        llm_target="getRecordInfo",
        policy="risk_limited",
    )

    assert selection["selected_target"] == "getRecordDetail"
    assert selection["overrode_llm"] is True
    assert selection["override_assessment"]["allowed"] is True
    assert "identifier_detail_contract" in selection["override_assessment"]["supporting_sources"]
    assert selection["decision"] == "override_llm"
    assert selection["needs_expansion"] is False
