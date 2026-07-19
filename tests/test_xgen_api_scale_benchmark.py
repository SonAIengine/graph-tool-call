from __future__ import annotations

import json

from benchmarks.xgen_api_scale.run import (
    DEFAULT_X2BEE_CASES_PATH,
    load_cases,
    run_benchmark,
    run_contract_signal_ablation,
    run_top_k_sweep,
)


def _spec(title: str, paths: dict):
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": "1.0.0"},
        "paths": paths,
    }


def _operation(operation_id: str, summary: str, *, method: str = "get"):
    return {
        method: {
            "operationId": operation_id,
            "summary": summary,
            "tags": ["test"],
            "parameters": [
                {
                    "name": "siteNo",
                    "in": "query",
                    "schema": {"type": "string"},
                    "description": "Site number",
                }
            ],
            "responses": {
                "200": {
                    "description": "OK",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}},
                            }
                        }
                    },
                }
            },
        }
    }


def _contract_operation(
    operation_id: str,
    summary: str,
    *,
    parameters: list[dict] | None = None,
    response_fields: dict[str, dict] | None = None,
):
    return {
        "get": {
            "operationId": operation_id,
            "summary": summary,
            "tags": ["contract"],
            "parameters": parameters or [],
            "responses": {
                "200": {
                    "description": "OK",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": response_fields or {"status": {"type": "string"}},
                            }
                        }
                    },
                }
            },
        }
    }


def test_xgen_api_scale_profiles_dedupes_and_searches(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Tiny Scale",
                "top_k": 3,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "expected_tool_recall_at_k": 1.0,
                    "max_avg_latency_ms": 50.0,
                },
                "cases": [
                    {
                        "id": "brand",
                        "query": "brand search",
                        "expected_tools": ["searchBrands"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    umbrella = _spec(
        "Umbrella",
        {
            "/brands": _operation("searchBrands", "Brand search"),
            "/orders": _operation("listOrders", "Order list"),
        },
    )
    duplicate_group = _spec(
        "Brand API",
        {
            "/brands": _operation("searchBrands", "Brand search"),
            "/products": _operation("searchProducts", "Product search"),
        },
    )

    report = run_benchmark(
        spec_sources=[umbrella, duplicate_group],
        cases_path=cases_path,
        min_unique_tools=3,
        max_build_seconds=10,
    )

    assert report["status"] == "pass"
    assert report["scale"]["spec_count"] == 2
    assert report["scale"]["operation_count"] == 4
    assert report["scale"]["unique_tool_count"] == 3
    assert report["scale"]["duplicate_tool_count"] == 1
    assert report["scale"]["duplicate_operation_id_count"] == 1
    assert report["scale"]["contract_request_tool_count"] == 4
    assert report["scale"]["contract_response_tool_count"] == 4
    assert report["scale"]["contract_consumes_field_count"] == 4
    assert report["scale"]["contract_produces_field_count"] == 4
    assert report["scale"]["contract_input_locations"]["query"] == 4
    assert report["search"]["case_hit_at_k"] == 1.0
    assert report["search"]["top_1_hit_at_k"] == 1.0
    assert report["search"]["top_3_hit_at_k"] == 1.0
    assert report["search"]["case_rank_buckets"]["top_1"] == 1
    assert report["search"]["rank_buckets"]["top_1"] == 1
    assert report["cases"][0]["expected_ranks"]["searchBrands"] == 1
    assert report["cases"][0]["best_expected_rank"] == 1
    assert report["cases"][0]["required_expected_found_at_k"] is True


def test_x2bee_default_cases_cover_product_level_domains():
    cases_doc = load_cases(DEFAULT_X2BEE_CASES_PATH)
    cases = cases_doc["cases"]
    case_ids = [case["id"] for case in cases]

    assert len(cases) >= 18
    assert len(case_ids) == len(set(case_ids))
    for required_id in {
        "member_list_ko",
        "member_mileage_history_ko",
        "event_list_ko",
        "goods_list_ko",
        "coupon_list_ko",
        "faq_list_ko",
        "notice_list_ko",
        "restock_notice_list_ko",
        "delivery_policy_list_ko",
        "promotion_list_ko",
        "market_display_list_ko",
    }:
        assert required_id in case_ids


def test_xgen_api_scale_can_promote_contract_signals(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Tiny Contract Promotion",
                "top_k": 2,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "expected_tool_recall_at_k": 1.0,
                },
                "cases": [
                    {
                        "id": "source_by_response_field",
                        "query": "opaque token id source",
                        "expected_tools": ["alphaSource"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Contract Promotion",
        {
            "/alpha": _contract_operation(
                "alphaSource",
                "Alpha source",
                response_fields={"opaqueTokenId": {"type": "string"}},
            ),
            "/beta": _contract_operation(
                "betaSink",
                "Beta sink",
                parameters=[
                    {
                        "name": "opaqueTokenId",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            ),
        },
    )

    report = run_benchmark(
        spec_sources=[spec],
        cases_path=cases_path,
        top_k=2,
        min_unique_tools=2,
        max_build_seconds=10,
        promote_contract_signals=True,
        contract_signal_options={"index_promoted_contract_fields": True},
    )

    promotion = report["scale"]["contract_signal_promotion"]
    assert promotion["enabled"] is True
    assert promotion["produces_added"] >= 1
    assert promotion["consumes_added"] >= 1
    assert report["search"]["case_hit_at_k"] == 1.0


def test_xgen_api_scale_contract_signal_ablation_reports_deltas(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Tiny Contract Ablation",
                "top_k": 1,
                "thresholds": {},
                "cases": [
                    {
                        "id": "source_by_response_field",
                        "query": "opaque token id source",
                        "expected_tools": ["alphaSource"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Contract Ablation",
        {
            "/alpha": _contract_operation(
                "alphaSource",
                "Alpha source",
                response_fields={"opaqueTokenId": {"type": "string"}},
            ),
            "/beta": _contract_operation(
                "betaSink",
                "Beta sink",
                parameters=[
                    {
                        "name": "opaqueTokenId",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            ),
        },
    )

    report = run_contract_signal_ablation(
        spec_sources=[spec],
        cases_path=cases_path,
        top_k=1,
        min_unique_tools=2,
        max_build_seconds=10,
        contract_signal_options={"index_promoted_contract_fields": True},
    )

    variants = {row["name"]: row for row in report["variants"]}
    assert report["methodology"] == "xgen_large_openapi_contract_signal_ablation"
    assert variants["baseline"]["scale"]["contract_signal_promotion"]["enabled"] is False
    assert variants["promoted"]["scale"]["contract_signal_promotion"]["enabled"] is True
    assert report["comparison"]["contract_signal_promotion"]["produces_added"] >= 1
    assert report["comparison"]["mean_mrr_delta"] >= 0


def test_xgen_api_scale_can_profile_without_cases():
    report = run_benchmark(
        spec_sources=[
            _spec(
                "Only Profile",
                {
                    "/orders": _operation("listOrders", "Order list"),
                    "/orders/{orderNo}": _operation("getOrder", "Order detail"),
                },
            )
        ],
        cases_path=None,
        min_unique_tools=2,
        max_build_seconds=10,
    )

    assert report["status"] == "pass"
    assert report["search"]["status"] == "skipped"
    assert report["scale"]["request_body_count"] == 0
    assert report["scale"]["response_schema_count"] == 2


def test_xgen_api_scale_top_k_sweep_uses_one_acceptance_k(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Tiny Sweep",
                "top_k": 3,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "expected_tool_recall_at_k": 1.0,
                    "max_avg_latency_ms": 50.0,
                },
                "cases": [
                    {
                        "id": "brand_and_order",
                        "query": "brand order",
                        "expected_tools": ["searchBrands", "listOrders"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = run_top_k_sweep(
        spec_sources=[
            _spec(
                "Sweep Profile",
                {
                    "/brands": _operation("searchBrands", "Brand search"),
                    "/orders": _operation("listOrders", "Order list"),
                    "/products": _operation("searchProducts", "Product search"),
                },
            )
        ],
        cases_path=cases_path,
        top_ks=[1, 3],
        acceptance_top_k=3,
        min_unique_tools=3,
        max_build_seconds=10,
    )

    assert report["status"] == "pass"
    assert report["methodology"] == "xgen_large_openapi_top_k_sweep"
    assert report["top_ks"] == [1, 3]
    assert report["acceptance_top_k"] == 3
    k1, k3 = report["sweep"]
    assert k1["top_k"] == 1
    assert k1["search"]["status"] == "diagnostic"
    assert k1["search"]["case_hit_at_k"] == 0.0
    assert k1["search"]["case_rank_buckets"]["top_1"] == 1
    assert k1["search"]["thresholds_applied"] is False
    assert k3["top_k"] == 3
    assert k3["search"]["case_hit_at_k"] == 1.0
    assert k3["search"]["case_rank_buckets"]["top_1"] == 1
    assert k3["search"]["thresholds_applied"] is True
