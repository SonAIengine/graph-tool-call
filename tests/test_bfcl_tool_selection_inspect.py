from __future__ import annotations

import json

from benchmarks.bfcl_tool_selection.inspect import inspect_failures, main


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _tool(name: str, description: str):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }


def _bfcl_data_root(tmp_path):
    data_root = tmp_path / "bfcl"
    answer_root = data_root / "possible_answer"
    answer_root.mkdir(parents=True)
    functions = [
        _tool("alpha_tool", "Use alpha signals"),
        _tool("beta_tool", "Use beta signals"),
        _tool("alpha_beta_noise", "Use alpha beta distractor signals"),
    ]
    _write_jsonl(
        data_root / "BFCL_v4_simple_python.json",
        [
            {
                "id": "simple_python_0",
                "question": [[{"role": "user", "content": "Use alpha and beta signals"}]],
                "function": functions,
            }
        ],
    )
    _write_jsonl(
        answer_root / "BFCL_v4_simple_python.json",
        [
            {
                "id": "simple_python_0",
                "ground_truth": [{"alpha_tool": {}}, {"beta_tool": {}}],
            }
        ],
    )
    return data_root


def test_inspect_failures_reports_expected_ranks_and_distractors(tmp_path):
    data_root = _bfcl_data_root(tmp_path)
    report = {
        "categories": [
            {
                "category": "simple_python",
                "cases": [
                    {
                        "case_id": "simple_python_0",
                        "failure_category": "retrieval_miss",
                        "retrieved": ["alpha_beta_noise"],
                    }
                ],
            }
        ]
    }

    inspected = inspect_failures(
        report=report,
        categories=["simple_python"],
        data_root=data_root,
        top_k=1,
        inspect_depth=3,
        failure_categories={"retrieval_miss"},
    )

    assert inspected["summary"]["cases"] == 1
    assert inspected["summary"]["expected_tool_mentions"] == 2
    assert inspected["cases"][0]["case_id"] == "simple_python_0"
    assert inspected["cases"][0]["missing_at_k"]
    assert inspected["cases"][0]["expected"][0]["matches"]
    assert inspected["summary"]["issues"]["reported_retrieval_miss"] == 1


def test_inspect_cli_writes_json_output(tmp_path):
    data_root = _bfcl_data_root(tmp_path)
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "inspect.json"
    report_path.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category": "simple_python",
                        "cases": [
                            {
                                "case_id": "simple_python_0",
                                "failure_category": "candidate_ambiguity",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--report",
            str(report_path),
            "--data-root",
            str(data_root),
            "--categories",
            "simple_python",
            "--top-k",
            "1",
            "--inspect-depth",
            "3",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["benchmark"] == "BFCL v4 Failure Inspector"
    assert payload["summary"]["failure_categories"] == {"candidate_ambiguity": 1}
