from __future__ import annotations

import json

from benchmarks.bfcl_tool_selection.failures import extract_failure_cases, main


def test_extract_failure_cases_filters_sweep_runs():
    report = {
        "runs": [
            {
                "tool_source": "retrieved",
                "top_k": 5,
                "report": {
                    "categories": [
                        {
                            "category": "parallel_multiple",
                            "cases": [
                                {
                                    "case_id": "parallel_multiple_1",
                                    "failure_category": "retrieval_miss",
                                    "retrieval_recall_at_k": 0.0,
                                },
                                {
                                    "case_id": "parallel_multiple_2",
                                    "failure_category": "candidate_ambiguity",
                                    "retrieval_recall_at_k": 1.0,
                                },
                            ],
                        }
                    ]
                },
            },
            {
                "tool_source": "row",
                "top_k": 5,
                "report": {
                    "categories": [
                        {
                            "category": "parallel_multiple",
                            "cases": [
                                {"case_id": "parallel_multiple_3", "failure_category": "pass"}
                            ],
                        }
                    ]
                },
            },
        ]
    }

    rows = extract_failure_cases(
        report,
        failure_categories={"retrieval_miss"},
        categories={"parallel_multiple"},
        tool_sources={"retrieved"},
        top_ks={5},
    )

    assert rows == [
        {
            "case_id": "parallel_multiple_1",
            "category": "parallel_multiple",
            "failure_category": "retrieval_miss",
            "tool_source": "retrieved",
            "top_k": 5,
            "retrieval_recall_at_k": 0.0,
            "evaluator_exact_match": None,
        }
    ]


def test_failures_cli_writes_case_id_file(tmp_path):
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "ids.txt"
    report_path.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category": "simple_python",
                        "cases": [
                            {"case_id": "simple_python_0", "failure_category": "retrieval_miss"},
                            {"case_id": "simple_python_1", "failure_category": "pass"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(["--report", str(report_path), "--output", str(output_path)]) == 0
    assert output_path.read_text(encoding="utf-8") == "simple_python_0\n"
