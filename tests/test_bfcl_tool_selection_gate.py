from __future__ import annotations

import json
from pathlib import Path

from benchmarks.bfcl_tool_selection import gate


def test_gate_cli_passes_saved_pass_gate(tmp_path: Path, capsys):
    report_path = tmp_path / "pass.json"
    report_path.write_text(
        json.dumps({"summary": {"milestone_gate": {"profile": "xgen-0.27", "status": "pass"}}}),
        encoding="utf-8",
    )

    assert gate.main([str(report_path)]) == 0
    assert "status=pass" in capsys.readouterr().out


def test_gate_cli_fails_saved_failed_gate(tmp_path: Path, capsys):
    report_path = tmp_path / "fail.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "milestone_gate": {
                        "profile": "xgen-0.27",
                        "status": "fail",
                        "target_top_k": 5,
                        "metrics": {
                            "retrieved_exact_at_5": 0.5,
                            "retrieval_recall_at_5": 1.0,
                            "row_source_upper_bound_preservation": 0.5,
                            "parallel_multiple_exact_at_5": 0.5,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert gate.main([str(report_path), "--json"]) == 1
    assert '"status": "fail"' in capsys.readouterr().out


def test_gate_recomputes_when_saved_gate_is_missing(tmp_path: Path):
    report_path = tmp_path / "recompute.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "rows": [
                        _summary_row("row", exact=1.0),
                        _summary_row("retrieved", exact=1.0),
                    ],
                    "category_rows": [
                        _summary_row("retrieved", exact=1.0, category="parallel_multiple")
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    loaded = gate.load_gate(report_path)

    assert loaded["status"] == "pass"
    assert loaded["metrics"]["row_source_upper_bound_preservation"] == 1.0


def _summary_row(
    tool_source: str, *, exact: float, category: str | None = None
) -> dict[str, object]:
    row: dict[str, object] = {
        "repeat": 1,
        "tool_source": tool_source,
        "top_k": 5,
        "cases": 1,
        "retrieval_recall_at_k": 1.0,
        "model_tool_call_rate": 1.0,
        "strict_exact_match": exact,
        "evaluator_exact_match": exact,
        "equivalence_adjusted_exact_match": exact,
        "avg_latency_ms": 1.0,
    }
    if category is not None:
        row["category"] = category
    return row
