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
                    "target_selector_exact_at_k": 1.0,
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
    assert report["gate"]["status"] == "pass"
    assert report["gate"]["methodology"] == "xgen_large_openapi_acceptance"
    assert report["gate"]["metrics"]["unique_tool_count"] == 3
    assert report["gate"]["metrics"]["case_hit_at_k"] == 1.0
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
    assert report["search"]["target_selector_exact_at_k"] == 1.0
    assert report["search"]["target_selector_miss_count"] == 0
    assert "avg_target_equivalence_group_count" in report["search"]
    assert "target_equivalence_group_case_count" in report["search"]
    assert report["search"]["target_selector_rank_buckets"]["top_1"] == 1
    assert report["search"]["top_1_hit_at_k"] == 1.0
    assert report["search"]["top_3_hit_at_k"] == 1.0
    assert report["search"]["case_rank_buckets"]["top_1"] == 1
    assert report["search"]["rank_buckets"]["top_1"] == 1
    assert report["cases"][0]["expected_ranks"]["searchBrands"] == 1
    assert report["cases"][0]["selected_target"] == "searchBrands"
    assert report["cases"][0]["target_selector_exact"] == 1.0
    assert report["cases"][0]["target_selector_rank"] == 1
    assert report["cases"][0]["target_equivalence_group_count"] == len(
        report["cases"][0]["target_equivalence_groups"]
    )
    assert report["cases"][0]["best_expected_rank"] == 1
    assert report["cases"][0]["required_expected_found_at_k"] is True


def test_x2bee_default_cases_cover_product_level_domains():
    cases_doc = load_cases(DEFAULT_X2BEE_CASES_PATH)
    cases = cases_doc["cases"]
    case_ids = [case["id"] for case in cases]

    assert len(cases) >= 18
    assert cases_doc["thresholds"]["target_selector_exact_at_k"] >= 0.85
    assert cases_doc["thresholds"]["avg_required_input_coverage"] >= 0.85
    assert cases_doc["thresholds"]["avg_required_input_resolution_coverage"] >= 1.0
    assert cases_doc["thresholds"]["max_unresolved_required_input_count"] == 0
    assert cases_doc["thresholds"]["max_avg_candidate_count"] <= 3.0
    assert cases_doc["thresholds"]["max_candidate_count"] <= 8.0
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


def test_xgen_api_scale_reports_contract_plan_readiness(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Tiny Plan Readiness",
                "top_k": 2,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "target_selector_exact_at_k": 1.0,
                    "producer_recall_at_k": 1.0,
                    "candidate_plan_coverage": 1.0,
                    "avg_required_input_coverage": 1.0,
                },
                "cases": [
                    {
                        "id": "detail_from_search",
                        "query": "product detail",
                        "expected_tools": ["getProductDetail"],
                        "expected_producers": ["searchProducts"],
                        "expected_plan": ["searchProducts", "getProductDetail"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Plan Readiness",
        {
            "/products": _contract_operation(
                "searchProducts",
                "Product search",
                response_fields={"productId": {"type": "string"}},
            ),
            "/products/detail": _contract_operation(
                "getProductDetail",
                "Product detail",
                parameters=[
                    {
                        "name": "productId",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                response_fields={"skuId": {"type": "string"}},
            ),
        },
    )

    report = run_benchmark(
        spec_sources=[spec],
        cases_path=cases_path,
        top_k=2,
        min_unique_tools=2,
        max_build_seconds=10,
    )
    case = report["cases"][0]

    assert report["status"] == "pass"
    assert report["search"]["expected_producer_case_count"] == 1
    assert report["search"]["expected_plan_case_count"] == 1
    assert report["search"]["producer_recall_at_k"] == 1.0
    assert report["search"]["candidate_plan_coverage"] == 1.0
    assert report["search"]["avg_required_input_coverage"] == 1.0
    assert report["search"]["avg_required_input_resolution_coverage"] == 1.0
    assert report["search"]["required_input_ready_case_count"] == 1
    assert report["search"]["required_input_resolved_case_count"] == 1
    assert report["search"]["unresolved_required_input_count"] == 0
    assert report["search"]["input_resolution_counts"] == {"producer": 1}
    assert case["selected_target"] == "getProductDetail"
    assert case["target_equivalence_group_count"] == len(case["target_equivalence_groups"])
    assert case["producer_candidates"] == ["searchProducts"]
    assert case["plan_candidates"] == ["getProductDetail", "searchProducts"]
    assert case["target_required_data_input_count"] == 1
    assert case["target_required_producible_input_count"] == 1
    assert case["target_required_resolved_input_count"] == 1
    assert case["required_input_resolution_coverage"] == 1.0
    assert case["input_support"][0]["field_name"] == "productId"
    assert case["input_support"][0]["producer_candidates"] == ["searchProducts"]
    assert case["input_support"][0]["resolution"] == "producer"


def test_xgen_api_scale_keeps_optional_producers_out_of_plan_candidates(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Optional Producer Width",
                "top_k": 2,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "target_selector_exact_at_k": 1.0,
                    "max_avg_candidate_count": 1.0,
                    "max_candidate_count": 1.0,
                },
                "cases": [
                    {
                        "id": "optional_filter",
                        "query": "order summary",
                        "expected_tools": ["getOrderSummary"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Optional Producer Width",
        {
            "/campaigns": _contract_operation(
                "listCampaigns",
                "Campaign list",
                response_fields={"campaignId": {"type": "string"}},
            ),
            "/orders/summary": _contract_operation(
                "getOrderSummary",
                "Order summary",
                parameters=[
                    {
                        "name": "campaignId",
                        "in": "query",
                        "required": False,
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
    )
    case = report["cases"][0]

    assert report["status"] == "pass"
    assert report["search"]["avg_candidate_count"] == 1.0
    assert case["plan_candidates"] == ["getOrderSummary"]
    assert case["producer_candidates"] == []
    assert case["candidate_count"] == 1
    assert case["target_data_input_count"] == 1
    assert case["target_required_data_input_count"] == 0
    assert case["target_producible_input_count"] == 1
    assert case["input_support"][0]["required"] is False
    assert case["input_support"][0]["producer_candidates"] == ["listCampaigns"]
    assert case["input_support"][0]["supported"] is True


def test_xgen_api_scale_uses_representative_required_producer_per_field(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Representative Producers",
                "top_k": 3,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "target_selector_exact_at_k": 1.0,
                    "max_avg_candidate_count": 2.0,
                    "max_candidate_count": 2.0,
                },
                "cases": [
                    {
                        "id": "representative",
                        "query": "coupon detail",
                        "expected_tools": ["getCouponDetail"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Representative Producers",
        {
            "/coupons/save": _contract_operation(
                "saveCoupon",
                "Coupon save",
                response_fields={"couponId": {"type": "string"}},
            ),
            "/coupons/search": _contract_operation(
                "searchCoupons",
                "Coupon search",
                response_fields={"couponId": {"type": "string"}},
            ),
            "/coupons/list": _contract_operation(
                "listCoupons",
                "Coupon list",
                response_fields={"couponId": {"type": "string"}},
            ),
            "/coupons/detail": _contract_operation(
                "getCouponDetail",
                "Coupon detail",
                parameters=[
                    {
                        "name": "couponId",
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
        top_k=3,
        min_unique_tools=4,
        max_build_seconds=10,
    )
    case = report["cases"][0]

    assert report["status"] == "pass"
    assert report["search"]["avg_candidate_count"] == 2.0
    assert case["plan_candidates"] == ["getCouponDetail", "searchCoupons"]
    assert case["producer_candidates"] == ["searchCoupons"]
    assert case["input_support"][0]["producer_candidates"] == [
        "searchCoupons",
        "listCoupons",
        "saveCoupon",
    ]


def test_xgen_api_scale_representative_producers_cover_multiple_fields(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Representative Producer Set Cover",
                "top_k": 3,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "target_selector_exact_at_k": 1.0,
                    "max_avg_candidate_count": 2.0,
                    "max_candidate_count": 2.0,
                },
                "cases": [
                    {
                        "id": "set_cover",
                        "query": "coupon issue detail",
                        "expected_tools": ["issueCoupon"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Representative Producer Set Cover",
        {
            "/coupons/search": _contract_operation(
                "searchCoupons",
                "Coupon search",
                response_fields={
                    "couponId": {"type": "string"},
                    "promoNo": {"type": "string"},
                },
            ),
            "/coupons/list": _contract_operation(
                "listCoupons",
                "Coupon list",
                response_fields={"couponId": {"type": "string"}},
            ),
            "/promotions/list": _contract_operation(
                "listPromotions",
                "Promotion list",
                response_fields={"promoNo": {"type": "string"}},
            ),
            "/coupons/issue": _contract_operation(
                "issueCoupon",
                "Coupon issue detail",
                parameters=[
                    {
                        "name": "couponId",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "promoNo",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
            ),
        },
    )

    report = run_benchmark(
        spec_sources=[spec],
        cases_path=cases_path,
        top_k=3,
        min_unique_tools=4,
        max_build_seconds=10,
    )
    case = report["cases"][0]

    assert report["status"] == "pass"
    assert report["search"]["avg_candidate_count"] == 2.0
    assert case["plan_candidates"] == ["issueCoupon", "searchCoupons"]
    assert case["producer_candidates"] == ["searchCoupons"]
    assert case["input_support"][0]["producer_candidates"] == ["searchCoupons", "listCoupons"]
    assert case["input_support"][1]["producer_candidates"] == ["searchCoupons", "listPromotions"]


def test_xgen_api_scale_matches_identifier_description_aliases(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Description Alias Readiness",
                "top_k": 2,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "target_selector_exact_at_k": 1.0,
                    "avg_required_input_coverage": 1.0,
                    "avg_required_input_resolution_coverage": 1.0,
                    "max_unresolved_required_input_count": 0,
                },
                "cases": [
                    {
                        "id": "description_alias",
                        "query": "delivery amount info",
                        "expected_tools": ["getDeliveryAmountInfo"],
                        "expected_producers": ["getMarketDisplayList"],
                        "expected_plan": ["getMarketDisplayList", "getDeliveryAmountInfo"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Description Alias",
        {
            "/market-displays": _contract_operation(
                "getMarketDisplayList",
                "Market display list",
                response_fields={"mkdpNo": {"type": "string", "description": "기획전번호"}},
            ),
            "/delivery-amount": _contract_operation(
                "getDeliveryAmountInfo",
                "Delivery amount info",
                parameters=[
                    {
                        "name": "marketingDisplayNo",
                        "in": "query",
                        "required": True,
                        "description": "기획전번호",
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
    )
    case = report["cases"][0]

    assert report["status"] == "pass"
    assert report["search"]["avg_required_input_coverage"] == 1.0
    assert report["search"]["unresolved_required_input_count"] == 0
    assert case["producer_candidates"] == ["getMarketDisplayList"]
    assert case["target_required_producible_input_count"] == 1
    assert case["input_support"][0]["field_name"] == "marketingDisplayNo"
    assert case["input_support"][0]["producer_candidates"] == ["getMarketDisplayList"]
    assert case["input_support"][0]["resolution"] == "producer"


def test_xgen_api_scale_classifies_required_input_readiness_issues(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "name": "Tiny Readiness Issue Classes",
                "top_k": 1,
                "thresholds": {
                    "case_hit_at_k": 1.0,
                    "target_selector_exact_at_k": 1.0,
                },
                "cases": [
                    {
                        "id": "required_inputs",
                        "query": "missing readiness target",
                        "expected_tools": ["getMissingReadiness"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = _spec(
        "Readiness Issue Classes",
        {
            "/missing-readiness": _contract_operation(
                "getMissingReadiness",
                "Missing readiness target",
                parameters=[
                    {
                        "name": "memberSearchRequest",
                        "in": "query",
                        "required": True,
                        "description": "Member list Request",
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "systemType",
                        "in": "query",
                        "required": True,
                        "description": "System type",
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "searchDateType",
                        "in": "query",
                        "required": True,
                        "description": "검색기간 유형 코드",
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "marketingDisplayNo",
                        "in": "query",
                        "required": True,
                        "description": "Marketing display number",
                        "schema": {"type": "string"},
                    },
                ],
            )
        },
    )

    report = run_benchmark(
        spec_sources=[spec],
        cases_path=cases_path,
        top_k=1,
        min_unique_tools=1,
        max_build_seconds=10,
    )
    case = report["cases"][0]
    issues = {row["field_name"]: row["issue_code"] for row in case["input_support"]}
    resolutions = {row["field_name"]: row["resolution"] for row in case["input_support"]}

    assert report["status"] == "pass"
    assert report["search"]["avg_required_input_coverage"] == 0.0
    assert report["search"]["avg_required_input_resolution_coverage"] == 0.75
    assert report["search"]["unresolved_required_input_count"] == 1
    assert report["search"]["input_resolution_counts"] == {
        "request_wrapper": 1,
        "context": 1,
        "user_input": 1,
        "unresolved": 1,
    }
    assert report["search"]["readiness_issue_counts"] == {
        "required_request_wrapper": 1,
        "required_context_input": 1,
        "required_filter_input": 1,
        "required_producer_missing": 1,
    }
    assert "required_input_not_producible" in case["issues"]
    assert issues == {
        "memberSearchRequest": "required_request_wrapper",
        "systemType": "required_context_input",
        "searchDateType": "required_filter_input",
        "marketingDisplayNo": "required_producer_missing",
    }
    assert resolutions == {
        "memberSearchRequest": "request_wrapper",
        "systemType": "context",
        "searchDateType": "user_input",
        "marketingDisplayNo": "unresolved",
    }


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
    assert report["gate"]["status"] == "pass"
    assert report["gate"]["search_status"] == "skipped"
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
    assert report["gate"]["status"] == "pass"
    assert report["gate"]["acceptance_top_k"] == 3
    assert report["gate"]["metrics"]["case_hit_at_k"] == 1.0
    assert report["methodology"] == "xgen_large_openapi_top_k_sweep"
    assert report["top_ks"] == [1, 3]
    assert report["acceptance_top_k"] == 3
    k1, k3 = report["sweep"]
    assert k1["top_k"] == 1
    assert k1["search"]["status"] == "diagnostic"
    assert k1["search"]["case_hit_at_k"] == 0.0
    assert k1["search"]["target_selector_exact_at_k"] == 1.0
    assert k1["search"]["target_selector_miss_count"] == 0
    assert k1["search"]["case_rank_buckets"]["top_1"] == 1
    assert k1["search"]["thresholds_applied"] is False
    assert k3["top_k"] == 3
    assert k3["search"]["case_hit_at_k"] == 1.0
    assert k3["search"]["target_selector_exact_at_k"] == 1.0
    assert k3["search"]["case_rank_buckets"]["top_1"] == 1
    assert k3["search"]["thresholds_applied"] is True
