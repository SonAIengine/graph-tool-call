import json
from pathlib import Path

from graph_tool_call.graphify import (
    contrast_target_candidates,
    select_target_candidate,
)

FIXTURE = Path(__file__).parent / "fixtures" / "contrastive_sibling_cases.json"


def _contract_rows(fields: list[str], *, direction: str) -> list[dict]:
    return [
        {
            "field_name": field,
            "semantic_tag": field,
            "description": field,
            "required": direction == "consumes",
            "kind": "data",
        }
        for field in fields
    ]


def _tool(resource: str, row: dict) -> dict:
    consumes = _contract_rows(row.get("consumes") or [], direction="consumes")
    produces = _contract_rows(row.get("produces") or [], direction="produces")
    return {
        "name": row["name"],
        "description": row["summary"],
        "metadata": {
            "ai_metadata": {
                "canonical_action": row["action"],
                "primary_resource": resource,
                "result_shape": row["shape"],
                "one_line_summary": row["summary"],
            },
            "openapi": {
                "operation_id": row["name"],
                "summary": row["summary"],
                "path": f"/api/{resource}/{row['name']}",
                "path_module": resource,
            },
            "api_contract": {"consumes": consumes, "produces": produces},
        },
    }


def _load_cases() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_contrastive_fixture_covers_ten_domains_and_thirty_sibling_pairs():
    cases = _load_cases()

    assert len(cases) == 10
    assert len({case["resource"] for case in cases}) == 10
    assert sum(len(case["candidates"]) * (len(case["candidates"]) - 1) // 2 for case in cases) == 30
    assert any(any("가" <= char <= "힣" for char in case["query"]) for case in cases)
    assert any(case["query"].isascii() for case in cases)


def test_contrastive_selector_resolves_multidomain_sibling_targets():
    for case in _load_cases():
        tools = {row["name"]: _tool(case["resource"], row) for row in case["candidates"]}
        retrieval = [
            {"name": row["name"], "score": round(0.03 - index * 0.001, 6)}
            for index, row in enumerate(case["candidates"])
        ]

        result = select_target_candidate(
            case["query"],
            retrieval,
            tools,
            retrieval_results=retrieval,
            llm_target=case["llm_target"],
            policy="risk_limited",
        )

        assert result["selected_target"] == case["expected"], case["id"]
        assert result["overrode_llm"] is True, case["id"]
        assert result["why_selected"]["name"] == case["expected"]
        assert result["why_selected"]["reason_codes"]
        assert any(row["name"] == case["llm_target"] for row in result["why_rejected"])


def test_contrastive_api_reports_query_facets_and_candidate_differences():
    case = next(row for row in _load_cases() if row["id"] == "storage_file_metadata")
    tools = {row["name"]: _tool(case["resource"], row) for row in case["candidates"]}

    result = contrast_target_candidates(case["query"], list(tools), tools)

    assert result["query_facets"]["canonical_action"] == "read"
    assert result["query_facets"]["result_shape"] == "single"
    assert result["query_facets"]["identifier_present"] is True
    assert "abc" not in json.dumps(result["query_facets"])
    by_name = {row["name"]: row for row in result["candidate_contrasts"]}
    assert "metadata" in by_name["getFileMetadata"]["matched_qualifiers"]
    assert "content" in by_name["downloadFile"]["unrequested_qualifiers"]
    assert by_name["getFileMetadata"]["response_contract_matches"] == ["metadata"]


def test_true_equivalents_remain_ambiguous_without_harmful_override():
    tools = {
        name: _tool(
            "event",
            {
                "name": name,
                "summary": "Event list",
                "action": "search",
                "shape": "list",
            },
        )
        for name in ("getEventList", "getEventListV2")
    }
    retrieval = [
        {"name": "getEventList", "score": 0.02},
        {"name": "getEventListV2", "score": 0.02},
    ]

    result = select_target_candidate(
        "list active events",
        retrieval,
        tools,
        retrieval_results=retrieval,
        llm_target="getEventListV2",
        policy="risk_limited",
    )

    assert result["selected_target"] == "getEventListV2"
    assert result["overrode_llm"] is False
    assert result["ambiguous"] is True
    assert set(result["ambiguity_set"]) == {"getEventList", "getEventListV2"}
    assert "insufficient_contrastive_evidence" in result["reason_codes"]


def test_empty_selector_keeps_contrastive_output_contract_stable():
    result = select_target_candidate("read account", [], {})

    assert result["selected_target"] == ""
    assert result["ambiguity_set"] == []
    assert result["why_selected"]["reason_codes"] == ["no_candidates"]
    assert result["why_rejected"] == []


def test_unrequested_specialization_is_decisive_negative_evidence():
    tools = {
        "listUsers": _tool(
            "user",
            {
                "name": "listUsers",
                "summary": "List users",
                "action": "search",
                "shape": "list",
            },
        ),
        "listArchivedAdminUsers": _tool(
            "user",
            {
                "name": "listArchivedAdminUsers",
                "summary": "List archived admin users",
                "action": "search",
                "shape": "list",
            },
        ),
    }
    retrieval = [
        {"name": "listArchivedAdminUsers", "score": 0.02},
        {"name": "listUsers", "score": 0.02},
    ]

    result = select_target_candidate(
        "list users",
        retrieval,
        tools,
        retrieval_results=retrieval,
        llm_target="listArchivedAdminUsers",
        policy="risk_limited",
    )

    assert result["selected_target"] == "listUsers"
    assert result["overrode_llm"] is True
    assert (
        "contrastive_unrequested_qualifier" in result["override_assessment"]["supporting_sources"]
    )


def test_audit_query_with_identifier_prefers_single_result_shape():
    tools = {
        "listAuditLogs": _tool(
            "audit",
            {
                "name": "listAuditLogs",
                "summary": "List audit logs",
                "action": "search",
                "shape": "list",
            },
        ),
        "getAuditLog": _tool(
            "audit",
            {
                "name": "getAuditLog",
                "summary": "Read one audit record by audit id",
                "action": "read",
                "shape": "single",
                "consumes": ["audit_id"],
            },
        ),
    }
    retrieval = [
        {"name": "listAuditLogs", "score": 0.02},
        {"name": "getAuditLog", "score": 0.02},
    ]

    result = select_target_candidate(
        "audit record id AUD-123",
        retrieval,
        tools,
        retrieval_results=retrieval,
        llm_target="listAuditLogs",
        policy="risk_limited",
    )

    assert result["query_facets"]["result_shape"] == "single"
    assert result["selected_target"] == "getAuditLog"
