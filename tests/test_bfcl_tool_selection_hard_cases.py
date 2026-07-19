from __future__ import annotations

import json

from benchmarks.bfcl_tool_selection.hard_cases import (
    build_hard_case_bundle,
    main,
    write_hard_case_bundle,
)


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


def _report():
    return {
        "model": "qwen-test",
        "runs": [
            {
                "tool_source": "retrieved",
                "top_k": 5,
                "report": {
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
                },
            }
        ],
    }


def test_build_hard_case_bundle_summarizes_and_writes_reusable_files(tmp_path):
    bundle = build_hard_case_bundle(
        report=_report(),
        categories=["simple_python"],
        data_root=_bfcl_data_root(tmp_path),
        top_k=1,
        inspect_depth=3,
        failure_categories={"retrieval_miss"},
        tool_sources={"retrieved"},
        top_ks={5},
    )

    assert bundle["model"] == "qwen-test"
    assert bundle["summary"]["cases"] == 1
    assert bundle["summary"]["failure_categories"] == {"retrieval_miss": 1}
    assert bundle["summary"]["issues"]["reported_retrieval_miss"] == 1
    assert bundle["case_ids"] == ["simple_python_0"]

    paths = write_hard_case_bundle(bundle, tmp_path / "out")

    assert (tmp_path / "out" / "case_ids.txt").read_text(encoding="utf-8") == ("simple_python_0\n")
    assert (tmp_path / "out" / "failure_retrieval_miss.txt").read_text(
        encoding="utf-8"
    ) == "simple_python_0\n"
    assert (tmp_path / "out" / "issue_reported_retrieval_miss.txt").read_text(
        encoding="utf-8"
    ) == "simple_python_0\n"
    assert (
        json.loads((tmp_path / "out" / "bundle.json").read_text(encoding="utf-8"))["summary"][
            "cases"
        ]
        == 1
    )
    assert paths["case_ids"].endswith("case_ids.txt")


def test_hard_cases_cli_writes_bundle(tmp_path):
    data_root = _bfcl_data_root(tmp_path)
    report_path = tmp_path / "report.json"
    out_dir = tmp_path / "hard"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")

    exit_code = main(
        [
            "--report",
            str(report_path),
            "--out-dir",
            str(out_dir),
            "--data-root",
            str(data_root),
            "--categories",
            "simple_python",
            "--failure-categories",
            "retrieval_miss",
            "--tool-sources",
            "retrieved",
            "--top-ks",
            "5",
            "--top-k",
            "1",
            "--inspect-depth",
            "3",
        ]
    )

    assert exit_code == 0
    assert (out_dir / "case_ids.txt").exists()
    assert (
        json.loads((out_dir / "inspect.json").read_text(encoding="utf-8"))["benchmark"]
        == "BFCL v4 Failure Inspector"
    )
