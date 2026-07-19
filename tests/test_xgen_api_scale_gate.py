from __future__ import annotations

import json
from pathlib import Path

from benchmarks.xgen_api_scale import gate


def test_xgen_scale_gate_cli_passes_saved_acceptance_artifact(tmp_path: Path, capsys):
    report_path = tmp_path / "pass.json"
    report_path.write_text(json.dumps(_acceptance_report(status="pass")), encoding="utf-8")

    assert gate.main([str(report_path)]) == 0
    output = capsys.readouterr().out
    assert "status=pass" in output
    assert "unique_tools=1084" in output


def test_xgen_scale_gate_cli_fails_saved_search_gate(tmp_path: Path, capsys):
    report = _acceptance_report(status="fail")
    report["search"]["status"] = "fail"
    report["search"]["checks"]["target_selector_exact_at_k"] = False
    report_path = tmp_path / "fail.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert gate.main([str(report_path), "--json"]) == 1
    loaded = json.loads(capsys.readouterr().out)
    assert loaded["status"] == "fail"
    assert "search_gate_failed" in loaded["issues"]
    assert loaded["checks"]["search"]["target_selector_exact_at_k"] is False


def test_xgen_scale_gate_uses_acceptance_top_k_for_sweep(tmp_path: Path):
    report_path = tmp_path / "sweep.json"
    report_path.write_text(json.dumps(_sweep_report()), encoding="utf-8")

    loaded = gate.load_gate(report_path)

    assert loaded["status"] == "pass"
    assert loaded["acceptance_top_k"] == 10
    assert loaded["search_status"] == "pass"
    assert loaded["metrics"]["expected_tool_recall_at_k"] == 0.9


def test_xgen_scale_gate_fails_when_sweep_acceptance_run_is_missing(tmp_path: Path):
    report = _sweep_report()
    report["status"] = "fail"
    report["sweep"] = [row for row in report["sweep"] if row["top_k"] != 10]
    report_path = tmp_path / "missing.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    loaded = gate.load_gate(report_path)

    assert loaded["status"] == "fail"
    assert "acceptance_run_missing" in loaded["issues"]


def _acceptance_report(*, status: str) -> dict[str, object]:
    return {
        "benchmark": "X2BEE BO API Scale Acceptance",
        "methodology": "xgen_large_openapi_acceptance",
        "graph_tool_call_version": "0.27.0",
        "status": status,
        "source_url": "https://api-bo.x2bee.com/api/bo/swagger-ui/index.html",
        "top_k": 10,
        "scale": _scale(status="pass"),
        "search": _search(status="pass"),
    }


def _sweep_report() -> dict[str, object]:
    return {
        "benchmark": "X2BEE BO API Scale Acceptance",
        "methodology": "xgen_large_openapi_top_k_sweep",
        "graph_tool_call_version": "0.27.0",
        "status": "pass",
        "source_url": "https://api-bo.x2bee.com/api/bo/swagger-ui/index.html",
        "top_ks": [3, 5, 10],
        "acceptance_top_k": 10,
        "scale": _scale(status="pass"),
        "sweep": [
            {"top_k": 3, "search": _search(status="diagnostic", thresholds_applied=False)},
            {"top_k": 10, "search": _search(status="pass", thresholds_applied=True)},
        ],
    }


def _scale(*, status: str) -> dict[str, object]:
    return {
        "status": status,
        "checks": {
            "min_spec_count": True,
            "min_unique_tools": True,
            "max_build_seconds": True,
        },
        "spec_count": 1,
        "operation_count": 1200,
        "unique_tool_count": 1084,
        "duplicate_tool_count": 116,
        "edge_count": 300,
        "build_seconds": 7.5,
    }


def _search(*, status: str, thresholds_applied: bool = True) -> dict[str, object]:
    return {
        "status": status,
        "thresholds_applied": thresholds_applied,
        "cases": 19,
        "checks": {
            "case_hit_at_k": True,
            "expected_tool_recall_at_k": True,
            "target_selector_exact_at_k": True,
            "avg_required_input_coverage": True,
            "avg_required_input_resolution_coverage": True,
            "max_unresolved_required_input_count": True,
            "max_avg_candidate_count": True,
            "max_candidate_count": True,
            "max_avg_latency_ms": True,
        },
        "case_hit_at_k": 1.0,
        "expected_tool_recall_at_k": 0.9,
        "target_selector_exact_at_k": 1.0,
        "avg_candidate_count": 2.16,
        "max_candidate_count": 7,
        "avg_required_input_coverage": 1.0,
        "avg_required_input_resolution_coverage": 1.0,
        "unresolved_required_input_count": 0,
        "avg_latency_ms": 2.0,
    }
