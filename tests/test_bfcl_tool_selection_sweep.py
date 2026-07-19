from __future__ import annotations

import json

from benchmarks.bfcl_tool_selection import sweep
from benchmarks.bfcl_tool_selection.sweep import run_sweep, write_sweep_bfcl_result_files


def test_sweep_runs_top_k_and_source_matrix(monkeypatch):
    calls = []

    def fake_run_model_benchmark(**kwargs):
        calls.append(kwargs)
        exact = 1.0 if kwargs["tool_source"] == "row" else kwargs["top_k"] / 10
        return {
            "llm_url": "http://redacted",
            "summary": {
                "cases": 2,
                "retrieval_recall_at_k": kwargs["top_k"] / 10,
                "model_tool_call_rate": 1.0,
                "strict_exact_match": exact,
                "evaluator_exact_match": exact,
                "avg_latency_ms": 100 + kwargs["top_k"],
                "failure_breakdown": {
                    "pass": int(exact == 1.0),
                    "retrieval_miss": int(exact < 1.0),
                },
            },
        }

    monkeypatch.setattr(sweep, "run_model_benchmark", fake_run_model_benchmark)

    report = run_sweep(
        model="fake",
        llm_url="http://fake/v1",
        categories=["simple_python"],
        top_ks=[3, 5],
        tool_sources=["row", "retrieved"],
        case_ids={"simple_python_0"},
        repeats=2,
        concurrency=3,
        progress=True,
        progress_every=2,
        retrieval_rank_hints=True,
        candidate_selection_guidance=True,
        cohesive_namespace_candidates=True,
    )

    assert len(calls) == 8
    assert all(call["concurrency"] == 3 for call in calls)
    assert all(call["progress"] is True for call in calls)
    assert all(call["progress_every"] == 2 for call in calls)
    assert all(call["retrieval_rank_hints"] is True for call in calls)
    assert all(call["candidate_selection_guidance"] is True for call in calls)
    assert all(call["cohesive_namespace_candidates"] is True for call in calls)
    assert all(call["case_ids"] == {"simple_python_0"} for call in calls)
    assert report["retrieval_rank_hints"] is True
    assert report["candidate_selection_guidance"] is True
    assert report["cohesive_namespace_candidates"] is True
    assert [call["cache_namespace"] for call in calls[:4]] == ["repeat-1"] * 4
    assert [call["cache_namespace"] for call in calls[4:]] == ["repeat-2"] * 4
    assert report["summary"]["run_count"] == 8
    assert report["concurrency"] == 3
    assert report["summary"]["best_retrieved"]["top_k"] == 5
    assert report["summary"]["best_retrieved"]["evaluator_exact_match"] == 0.5
    assert report["summary"]["failure_breakdown"]["retrieval_miss"] == 4
    repeat_groups = report["summary"]["repeat_groups"]
    retrieved_k5 = next(
        group
        for group in repeat_groups
        if group["tool_source"] == "retrieved" and group["top_k"] == 5
    )
    assert retrieved_k5["repeat_count"] == 2
    assert retrieved_k5["cases_per_repeat"] == [2, 2]
    assert retrieved_k5["evaluator_exact_match"] == {
        "mean": 0.5,
        "std": 0.0,
        "min": 0.5,
        "max": 0.5,
    }
    assert report["summary"]["milestone_gate"]["status"] == "incomplete"
    assert "parallel_multiple_exact_at_5" in report["summary"]["milestone_gate"]["missing_metrics"]


def test_sweep_milestone_gate_reports_xgen_027_bottlenecks():
    summary = sweep._summarize_sweep(
        [
            _sweep_run(
                tool_source="row",
                top_k=5,
                exact=0.90,
                retrieval=0.91,
                parallel_multiple_exact=0.80,
            ),
            _sweep_run(
                tool_source="retrieved",
                top_k=5,
                exact=0.84,
                retrieval=0.96,
                parallel_multiple_exact=0.74,
            ),
        ]
    )

    gate = summary["milestone_gate"]

    assert gate["profile"] == "xgen-0.27"
    assert gate["status"] == "fail"
    assert gate["metrics"]["retrieved_exact_at_5"] == 0.84
    assert gate["metrics"]["retrieval_recall_at_5"] == 0.96
    assert gate["metrics"]["row_source_exact_at_5"] == 0.9
    assert gate["metrics"]["row_source_upper_bound_preservation"] == 0.933333
    assert gate["metrics"]["parallel_multiple_exact_at_5"] == 0.74
    assert {row["metric"] for row in gate["failed_gates"]} == {
        "retrieved_exact_at_5",
        "row_source_upper_bound_preservation",
        "parallel_multiple_exact_at_5",
    }
    assert summary["category_repeat_groups"][0]["category"] == "parallel_multiple"


def test_sweep_summary_pairs_row_and_retrieved_failures():
    summary = sweep._summarize_sweep(
        [
            _paired_case_run(
                "row",
                [
                    ("simple_python_1", "pass"),
                    ("simple_python_2", "pass"),
                    ("simple_python_3", "argument_value_mismatch"),
                    ("simple_python_4", "call_count_mismatch"),
                ],
            ),
            _paired_case_run(
                "retrieved",
                [
                    ("simple_python_1", "pass"),
                    (
                        "simple_python_2",
                        "candidate_ambiguity",
                        ["near_duplicate_tool_surface"],
                    ),
                    ("simple_python_3", "pass"),
                    ("simple_python_4", "retrieval_miss"),
                ],
            ),
        ]
    )

    delta = summary["row_vs_retrieved_deltas"][0]

    assert delta["paired_cases"] == 4
    assert delta["both_pass"] == 1
    assert delta["row_pass_retrieved_fail"] == 1
    assert delta["row_fail_retrieved_pass"] == 1
    assert delta["both_fail"] == 1
    assert delta["row_pass_count"] == 2
    assert delta["retrieved_exact_on_row_pass"] == 0.5
    assert delta["row_pass_retrieved_fail_rate"] == 0.5
    assert delta["row_pass_retrieved_fail_breakdown"] == {"candidate_ambiguity": 1}
    assert delta["row_pass_retrieved_fail_tags"] == {"near_duplicate_tool_surface": 1}
    assert delta["both_fail_retrieved_breakdown"] == {"retrieval_miss": 1}
    assert delta["row_pass_retrieved_fail_case_ids"] == ["simple_python_2"]
    assert delta["both_fail_case_ids"] == ["simple_python_4"]
    assert summary["failure_tag_breakdown"] == {"near_duplicate_tool_surface": 1}


def test_write_sweep_bfcl_result_files_separates_runs(tmp_path):
    report = {
        "official_model_name": "qwen3-32b-FC",
        "runs": [
            {
                "repeat": 1,
                "tool_source": "row",
                "top_k": 5,
                "report": _single_case_report("row"),
            },
            {
                "repeat": 1,
                "tool_source": "retrieved",
                "top_k": 5,
                "report": _single_case_report("retrieved"),
            },
        ],
    }

    written = write_sweep_bfcl_result_files(report, tmp_path)

    assert len(written) == 2
    row_path = tmp_path / "repeat-1" / "row-k5" / "qwen3-32b-FC" / "non_live"
    retrieved_path = tmp_path / "repeat-1" / "retrieved-k5" / "qwen3-32b-FC" / "non_live"
    assert (row_path / "BFCL_v4_multiple_result.json").exists()
    retrieved_row = json.loads(
        (retrieved_path / "BFCL_v4_multiple_result.json").read_text(encoding="utf-8")
    )
    assert retrieved_row["graph_tool_call"]["tool_source"] == "retrieved"


def _paired_case_run(tool_source: str, cases: list[tuple]) -> dict[str, object]:
    passed = sum(1 for row in cases if row[1] == "pass")
    failure_tag_breakdown = {}
    for row in cases:
        for tag in row[2] if len(row) > 2 else []:
            failure_tag_breakdown[tag] = failure_tag_breakdown.get(tag, 0) + 1
    return {
        "repeat": 1,
        "tool_source": tool_source,
        "top_k": 5,
        "report": {
            "summary": {
                "cases": len(cases),
                "retrieval_recall_at_k": 1.0,
                "model_tool_call_rate": 1.0,
                "strict_exact_match": passed / len(cases),
                "evaluator_exact_match": passed / len(cases),
                "avg_latency_ms": 100.0,
                "failure_breakdown": {"pass": passed},
                "failure_tag_breakdown": failure_tag_breakdown,
            },
            "categories": [
                {
                    "category": "simple_python",
                    "summary": {
                        "cases": len(cases),
                        "retrieval_recall_at_k": 1.0,
                        "model_tool_call_rate": 1.0,
                        "strict_exact_match": passed / len(cases),
                        "evaluator_exact_match": passed / len(cases),
                        "avg_latency_ms": 100.0,
                        "failure_breakdown": {"pass": passed},
                        "failure_tag_breakdown": failure_tag_breakdown,
                    },
                    "cases": [
                        {
                            "case_id": row[0],
                            "failure_category": row[1],
                            "evaluator_exact_match": 1.0 if row[1] == "pass" else 0.0,
                            "failure_tags": row[2] if len(row) > 2 else [],
                        }
                        for row in cases
                    ],
                }
            ],
        },
    }


def _single_case_report(tool_source: str):
    return {
        "official_model_name": "qwen3-32b-FC",
        "tool_source": tool_source,
        "top_k": 5,
        "categories": [
            {
                "category": "multiple",
                "cases": [
                    {
                        "case_id": "multiple_0",
                        "predicted_calls": [
                            {"name": "triangle_properties.get", "arguments": {"side1": 5}}
                        ],
                    }
                ],
            }
        ],
    }


def _sweep_run(
    *,
    tool_source: str,
    top_k: int,
    exact: float,
    retrieval: float,
    parallel_multiple_exact: float,
):
    return {
        "repeat": 1,
        "tool_source": tool_source,
        "top_k": top_k,
        "report": {
            "summary": {
                "cases": 10,
                "retrieval_recall_at_k": retrieval,
                "model_tool_call_rate": 1.0,
                "strict_exact_match": exact,
                "evaluator_exact_match": exact,
                "avg_latency_ms": 100.0,
                "failure_breakdown": {"pass": int(exact * 10)},
            },
            "categories": [
                {
                    "category": "parallel_multiple",
                    "summary": {
                        "cases": 5,
                        "retrieval_recall_at_k": retrieval,
                        "model_tool_call_rate": 1.0,
                        "strict_exact_match": parallel_multiple_exact,
                        "evaluator_exact_match": parallel_multiple_exact,
                        "avg_latency_ms": 100.0,
                        "failure_breakdown": {"pass": int(parallel_multiple_exact * 5)},
                    },
                }
            ],
        },
    }
