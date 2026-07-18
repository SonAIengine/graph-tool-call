from __future__ import annotations

from benchmarks.xgen_tool_graph.run import build_benchmark_graph, run_benchmark
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


def test_xgen_tool_graph_benchmark_checks_korean_query_chain():
    report = run_benchmark()
    graph_pipeline = next(p for p in report["pipelines"] if p["name"] == "graph_with_producers")
    cases = {row["case_id"]: row for row in graph_pipeline["cases"]}
    case = cases["inventory_chain_ko"]

    assert case["target_rank"] is not None
    assert case["plan_steps"] == ["searchProducts", "getProductDetail", "getInventory"]
    assert case["binding_accuracy"] == 1.0
    assert case["evidence_coverage"] == 1.0
