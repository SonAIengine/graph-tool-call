from __future__ import annotations

import json

from benchmarks.xgen_api_scale.run import run_benchmark


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
    assert report["search"]["case_hit_at_k"] == 1.0
    assert report["cases"][0]["expected_ranks"]["searchBrands"] == 1


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
