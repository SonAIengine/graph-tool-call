from __future__ import annotations

from benchmarks.xgen_tool_graph.run import (
    SUITE_CONFIGS,
    build_benchmark_graph,
    run_benchmark,
    run_benchmark_suite,
)
from graph_tool_call.graphify import COLLECTION_GRAPH_VERSION


def test_xgen_tool_graph_benchmark_metadata_and_contracts():
    tg, graph_payload, _raw_spec = build_benchmark_graph()

    assert len(tg.tools) == 11
    assert graph_payload["collection_graph_version"] == COLLECTION_GRAPH_VERSION
    assert graph_payload["enrichment_status"] == "complete"

    detail = graph_payload["tools"]["getProductDetail"]["metadata"]
    consumes = {row["field_name"]: row for row in detail["consumes"]}
    produces = {row["field_name"]: row for row in detail["produces"]}
    assert consumes["productId"]["semantic_tag"] == "product_id"
    assert consumes["productId"]["required"] is True
    assert consumes["siteNo"]["kind"] == "context"
    assert produces["skuId"]["semantic_tag"] == "sku_id"


def test_xgen_tool_graph_benchmark_graph_pipeline_passes_thresholds():
    report = run_benchmark()
    pipelines = {row["name"]: row for row in report["pipelines"]}
    seed = pipelines["target_only"]["summary"]
    graph = pipelines["graph_with_producers"]["summary"]

    assert graph["status"] == "pass"
    assert graph["target_recall_at_k"] == 1.0
    assert graph["producer_recall"] > seed["producer_recall"]
    assert graph["candidate_plan_coverage"] > seed["candidate_plan_coverage"]
    assert graph["candidate_binding_support"] > seed["candidate_binding_support"]
    assert graph["plan_exact_match"] >= 0.8
    assert graph["binding_accuracy"] >= 0.9
    assert report["improvements"]["producer_recall_delta"] > 0
    assert report["improvements"]["candidate_plan_coverage_delta"] > 0
    assert report["improvements"]["candidate_binding_support_delta"] > 0
    lift = report["producer_expansion_lift"]
    assert lift["baseline_pipeline"] == "target_only"
    assert lift["expanded_pipeline"] == "graph_with_producers"
    assert lift["producer_recall"]["delta"] == report["improvements"]["producer_recall_delta"]
    assert (
        lift["candidate_plan_coverage"]["delta"]
        == report["improvements"]["candidate_plan_coverage_delta"]
    )
    assert (
        lift["candidate_binding_support"]["delta"]
        == report["improvements"]["candidate_binding_support_delta"]
    )
    assert lift["producer_needed_cases"] == lift["lifted_cases"]["any"]
    assert lift["unneeded_expansion_cases"] == 0


def test_xgen_tool_graph_all_fixture_suites_pass_thresholds():
    report = run_benchmark_suite(suite="all")
    summary = report["summary"]

    assert summary["status"] == "pass"
    assert summary["fixture_families"] == list(SUITE_CONFIGS)
    assert summary["suite_count"] == 3
    assert summary["cases"] == 15
    assert summary["target_recall_at_k"] == 1.0
    assert summary["target_selector_exact"] == 1.0
    assert summary["target_selector_miss_count"] == 0
    assert summary["producer_recall"] == 1.0
    assert summary["candidate_plan_coverage"] == 1.0
    assert summary["plan_exact_match"] >= 0.9
    assert summary["synthesis_diagnostics_coverage"] == 1.0
    assert summary["user_input_slot_case_count"] == 1
    assert summary["missing_field_count"] == 2
    assert summary["producer_needed_case_count"] == 12
    assert summary["adaptive_expansion_case_count"] == 12
    assert summary["unneeded_expansion_case_count"] == 0
    assert summary["producer_expansion_producer_recall_delta"] == 0.8
    assert summary["producer_expansion_candidate_plan_coverage_delta"] == 0.5
    assert summary["producer_expansion_binding_support_delta"] == 0.8
    assert summary["producer_expansion_lifted_cases"] == 12
    assert report["producer_expansion_lift"]["cases"] == 15
    assert report["producer_expansion_lift"]["producer_needed_cases"] == 12
    assert report["producer_expansion_lift"]["adaptive_expansion_cases"] == 12
    assert report["producer_expansion_lift"]["unneeded_expansion_cases"] == 0
    assert report["producer_expansion_lift"]["lifted_cases"]["any"] == 12

    for suite_report in report["suites"]:
        graph = next(
            row for row in suite_report["pipelines"] if row["name"] == "graph_with_producers"
        )
        assert graph["summary"]["status"] == "pass"


def test_xgen_tool_graph_direct_queries_do_not_expand_producers():
    report = run_benchmark_suite(suite="all")

    for suite_report in report["suites"]:
        graph_pipeline = next(
            row for row in suite_report["pipelines"] if row["name"] == "graph_with_producers"
        )
        direct_cases = [row for row in graph_pipeline["cases"] if not row["producer_needed"]]
        assert len(direct_cases) == 1
        for case in direct_cases:
            assert case["selected_target"] == case["expected_target"]
            assert case["target_selector_exact"] == 1.0
            assert case["expansion_seed"] == [case["expected_target"]]
            assert case["candidates"] == [case["expected_target"]]
            assert case["producer_added_count"] == 0
            assert case["adaptive_expansion_applied"] is False
            assert case["unneeded_expansion_applied"] is False


def test_xgen_tool_graph_benchmark_checks_korean_query_chain():
    report = run_benchmark()
    graph_pipeline = next(p for p in report["pipelines"] if p["name"] == "graph_with_producers")
    cases = {row["case_id"]: row for row in graph_pipeline["cases"]}
    case = cases["inventory_chain_ko"]

    assert case["target_rank"] is not None
    assert case["selected_target"] == "getInventory"
    assert case["target_selector_rank"] == 1
    assert case["plan_steps"] == ["searchProducts", "getProductDetail", "getInventory"]
    assert case["binding_accuracy"] == 1.0
    assert case["evidence_coverage"] == 1.0


def test_xgen_tool_graph_records_synthesis_diagnostics_for_user_input_slots():
    report = run_benchmark()
    graph_pipeline = next(p for p in report["pipelines"] if p["name"] == "graph_with_producers")
    cases = {row["case_id"]: row for row in graph_pipeline["cases"]}
    case = cases["review_user_slots_ko"]
    diagnostics = case["synthesis_diagnostics"]

    assert diagnostics["stage"] == "synthesize"
    assert diagnostics["target"] == "createProductReview"
    assert diagnostics["plan_id"]
    assert diagnostics["failure"] == {}
    assert diagnostics["retrieval_evidence"]["target_rank"] == case["target_rank"]
    assert diagnostics["target_selector"]["selected_target"] == case["selected_target"]
    assert diagnostics["target_selector"]["target_selector_exact"] == 1.0
    assert (
        diagnostics["target_selector"]["target_equivalence_group_count"]
        == case["target_equivalence_group_count"]
    )
    assert isinstance(diagnostics["target_selector"]["target_equivalence_groups"], list)
    assert {row["producer"] for row in diagnostics["selected_producers"]} == {"searchProducts"}
    assert "createProductReview.productId" in diagnostics["candidate_signals"]

    missing = {row["field_name"]: row for row in diagnostics["missing_fields"]}
    assert set(missing) == {"rating", "comment"}
    assert missing["rating"]["reason"] == "user_input_fallback"
    assert missing["comment"]["stage"] == "synthesize"


def test_xgen_tool_graph_reports_target_selector_exactness_separately_from_target_recall():
    report = run_benchmark_suite(suite="all")
    graph_cases = []
    for suite_report in report["suites"]:
        graph = next(
            row for row in suite_report["pipelines"] if row["name"] == "graph_with_producers"
        )
        graph_cases.extend(graph["cases"])

    assert report["summary"]["target_recall_at_k"] == 1.0
    assert report["summary"]["target_selector_exact"] == 1.0
    assert report["summary"]["target_selector_miss_count"] == 0
    assert "avg_target_equivalence_group_count" in report["summary"]
    assert "target_equivalence_group_case_count" in report["summary"]
    for case in graph_cases:
        assert case["selected_target"] == case["expected_target"]
        assert case["target_selector_exact"] == 1.0
        selector = case["synthesis_diagnostics"]["target_selector"]
        assert selector["strategy"] == "query_action_priority"
        assert selector["selected_target"] == case["selected_target"]
        assert selector["expected_target"] == case["expected_target"]
        assert selector["target_candidates"] == case["target_selector_candidates"]
        assert selector["target_equivalence_group_count"] == case["target_equivalence_group_count"]
        assert isinstance(selector["target_equivalence_groups"], list)
