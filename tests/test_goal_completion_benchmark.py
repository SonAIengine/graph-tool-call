from __future__ import annotations

from benchmarks.goal_completion.run import run_benchmark


def test_goal_completion_benchmark_reports_full_engine_baseline():
    report = run_benchmark()
    summary = report["summary"]

    assert report["methodology"] == "natural_language_retrieve_plan_execute_goal_state"
    assert report["model"] == "none"
    assert report["scenario_count"] == 6
    assert summary["cases"] == 6
    assert summary["uncaught_error_count"] == 0
    assert summary["completed"] == 3
    assert summary["goal_completion_rate"] == 0.5
    assert 0.0 < summary["candidate_required_tool_recall"] < 1.0
    assert 0.0 < summary["plan_required_tool_recall"] < 1.0
    assert summary["binding_accuracy"] == 0.5
    assert summary["schema_valid_call_rate"] == 1.0
    assert 0.0 < summary["extraneous_call_rate"] < 0.2

    rows = {row["id"]: row for row in report["cases"]}
    assert rows["product_detail"]["evaluation"]["goal_completed"] is True
    assert rows["coupon_checkout"]["evaluation"]["goal_completed"] is True
    assert rows["create_review"]["evaluation"]["goal_completed"] is True
    assert rows["inventory_lookup"]["selected_target"] == "searchProducts"
    assert "missing_milestone" in rows["inventory_lookup"]["evaluation"]["failure_reason_codes"]
    assert rows["add_cart_item"]["selected_target"] == "getCart"
    assert rows["shipment_tracking"]["selected_target"] == "findOrders"


def test_goal_completion_benchmark_does_not_feed_gold_plan_to_engine():
    report = run_benchmark()

    for row in report["cases"]:
        assert "expected_plan" not in row
        assert row["planned_tools"] == row["executed_tools"]
