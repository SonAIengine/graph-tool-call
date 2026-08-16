from __future__ import annotations

from benchmarks.arazzo_long_horizon.run import run_benchmark


def test_arazzo_completes_three_step_goal_that_plain_openapi_cannot_bind():
    report = run_benchmark(catalog_size=40, workflow_lengths=(3,))
    row = report["cases"][0]

    assert row["baseline"]["evaluation"]["goal_completed"] is False
    assert row["with_arazzo"]["evaluation"]["goal_completed"] is True
    assert row["with_arazzo"]["plan_order_exact"] == 1.0
    assert row["with_arazzo"]["execution_order_exact"] == 1.0
    assert row["with_arazzo"]["evaluation"]["metrics"]["binding_accuracy"] == 1.0
    assert row["with_arazzo"]["workflow_summary"]["relation_count"] == 2


def test_arazzo_horizon_gate_covers_3_10_30_steps_in_1000_tool_catalogs():
    report = run_benchmark(catalog_size=1000)
    summary = report["summary"]

    assert report["workflow_lengths"] == [3, 10, 30]
    assert summary["status"] == "pass"
    assert summary["with_arazzo"]["target_hit_at_k"] == 1.0
    assert summary["with_arazzo"]["selected_target_exact"] == 1.0
    assert summary["with_arazzo"]["candidate_required_tool_recall"] == 1.0
    assert summary["with_arazzo"]["plan_required_tool_recall"] == 1.0
    assert summary["with_arazzo"]["execution_required_tool_recall"] == 1.0
    assert summary["with_arazzo"]["goal_completion_rate"] == 1.0
    assert summary["with_arazzo"]["plan_order_exact"] == 1.0
    assert summary["with_arazzo"]["execution_order_exact"] == 1.0
    assert summary["with_arazzo"]["binding_accuracy"] == 1.0
    assert summary["goal_completion_lift"] > 0
    assert summary["with_arazzo"]["latency_ms"]["retrieve"]["p95"] > 0
    assert summary["with_arazzo"]["token_budget_used"]["average"] > 0
    assert summary["with_arazzo"]["token_budget_used"]["max"] <= report["token_budget"]
    assert [row["with_arazzo"]["executed_call_count"] for row in report["cases"]] == [3, 10, 30]
