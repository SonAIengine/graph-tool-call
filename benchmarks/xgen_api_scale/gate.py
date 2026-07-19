"""Check XGEN scale acceptance gates from saved artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_GATE_PROFILE = "xgen-scale-0.27"
SUPPORTED_METHODOLOGIES = {
    "xgen_large_openapi_acceptance",
    "xgen_large_openapi_top_k_sweep",
}


def load_gate(
    report_path: Path,
    *,
    profile: str = DEFAULT_GATE_PROFILE,
) -> dict[str, Any]:
    """Load and normalize an XGEN scale gate from an acceptance artifact."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return evaluate_gate(report, profile=profile)


def evaluate_gate(
    report: dict[str, Any],
    *,
    profile: str = DEFAULT_GATE_PROFILE,
) -> dict[str, Any]:
    """Evaluate a saved XGEN scale report without rebuilding the live graph."""
    methodology = str(report.get("methodology") or "unknown")
    scale = report.get("scale") if isinstance(report.get("scale"), dict) else {}
    search = _acceptance_search(report)
    issues = _gate_issues(report, methodology=methodology, scale=scale, search=search)
    status = "pass" if not issues else "fail"

    return {
        "profile": profile,
        "status": status,
        "methodology": methodology,
        "artifact_status": report.get("status"),
        "benchmark": report.get("benchmark"),
        "source_url": report.get("source_url"),
        "graph_tool_call_version": report.get("graph_tool_call_version"),
        "acceptance_top_k": _acceptance_top_k(report),
        "scale_status": scale.get("status"),
        "search_status": search.get("status"),
        "checks": {
            "methodology_supported": methodology in SUPPORTED_METHODOLOGIES,
            "artifact_status_consistent": report.get("status") == status,
            "scale": dict(scale.get("checks") or {}),
            "search": dict(search.get("checks") or {}),
        },
        "metrics": _gate_metrics(scale, search),
        "issues": issues,
    }


def _acceptance_search(report: dict[str, Any]) -> dict[str, Any]:
    if isinstance(report.get("search"), dict):
        return dict(report["search"])
    sweep = report.get("sweep") if isinstance(report.get("sweep"), list) else []
    acceptance_top_k = _acceptance_top_k(report)
    for run in sweep:
        if not isinstance(run, dict):
            continue
        if run.get("top_k") == acceptance_top_k and isinstance(run.get("search"), dict):
            return dict(run["search"])
    for run in sweep:
        if isinstance(run, dict) and isinstance(run.get("search"), dict):
            search = dict(run["search"])
            if search.get("thresholds_applied"):
                return search
    return {"status": "skipped", "cases": 0}


def _acceptance_top_k(report: dict[str, Any]) -> int | None:
    value = report.get("acceptance_top_k", report.get("top_k"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _gate_issues(
    report: dict[str, Any],
    *,
    methodology: str,
    scale: dict[str, Any],
    search: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if methodology not in SUPPORTED_METHODOLOGIES:
        issues.append("unsupported_methodology")
    if methodology == "xgen_large_openapi_top_k_sweep" and _sweep_acceptance_run_missing(report):
        issues.append("acceptance_run_missing")
    if scale.get("status") != "pass":
        issues.append("scale_gate_failed")
    search_cases = int(search.get("cases") or 0)
    if search_cases > 0 and search.get("status") != "pass":
        issues.append("search_gate_failed")
    if report.get("status") not in {None, "pass"}:
        issues.append("artifact_status_failed")
    return issues


def _gate_metrics(scale: dict[str, Any], search: dict[str, Any]) -> dict[str, Any]:
    metric_names = [
        "case_hit_at_k",
        "expected_tool_recall_at_k",
        "target_selector_exact_at_k",
        "top_1_hit_at_k",
        "top_3_hit_at_k",
        "mean_mrr",
        "avg_candidate_count",
        "max_candidate_count",
        "avg_required_input_coverage",
        "avg_required_input_resolution_coverage",
        "unresolved_required_input_count",
        "avg_latency_ms",
        "avg_candidate_tool_fraction",
        "avg_tool_surface_reduction",
        "max_candidate_tool_fraction",
        "min_tool_surface_reduction",
        "full_tool_schema_chars",
        "avg_candidate_schema_chars",
        "max_candidate_schema_chars",
        "avg_candidate_schema_char_fraction",
        "avg_schema_context_reduction",
        "min_schema_context_reduction",
    ]
    metrics: dict[str, Any] = {
        "spec_count": scale.get("spec_count"),
        "operation_count": scale.get("operation_count"),
        "unique_tool_count": scale.get("unique_tool_count"),
        "duplicate_tool_count": scale.get("duplicate_tool_count"),
        "edge_count": scale.get("edge_count"),
        "build_seconds": scale.get("build_seconds"),
        "cases": search.get("cases"),
    }
    metrics.update({name: search.get(name) for name in metric_names if name in search})
    return metrics


def _sweep_acceptance_run_missing(report: dict[str, Any]) -> bool:
    if not isinstance(report.get("sweep"), list):
        return True
    acceptance_top_k = _acceptance_top_k(report)
    return not any(
        isinstance(run, dict)
        and run.get("top_k") == acceptance_top_k
        and isinstance(run.get("search"), dict)
        for run in report["sweep"]
    )


def format_gate(gate: dict[str, Any]) -> str:
    """Format a compact human-readable gate summary."""
    metrics = gate.get("metrics") or {}
    return (
        "xgen-scale gate profile={profile} status={status} methodology={methodology} "
        "acceptance_top_k={top_k} unique_tools={tools} cases={cases} "
        "recall@K={recall} selector={selector} candidates={candidates} "
        "issues={issues}"
    ).format(
        profile=gate.get("profile"),
        status=gate.get("status"),
        methodology=gate.get("methodology"),
        top_k=gate.get("acceptance_top_k"),
        tools=metrics.get("unique_tool_count"),
        cases=metrics.get("cases"),
        recall=metrics.get("expected_tool_recall_at_k"),
        selector=metrics.get("target_selector_exact_at_k"),
        candidates=metrics.get("avg_candidate_count"),
        issues=gate.get("issues") or ["pass"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="XGEN scale JSON artifact to check.")
    parser.add_argument(
        "--profile",
        default=DEFAULT_GATE_PROFILE,
        help="Gate profile label to record in the normalized output.",
    )
    parser.add_argument("--json", action="store_true", help="Print the gate as JSON.")
    args = parser.parse_args(argv)

    gate = load_gate(args.report, profile=args.profile)
    if args.json:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
    else:
        print(format_gate(gate))
    return 0 if gate.get("status") == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
