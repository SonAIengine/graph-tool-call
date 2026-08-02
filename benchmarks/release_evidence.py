"""Build deterministic, reviewable evidence for public release claims."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmarks.xgen_tool_graph.run import (
    DEFAULT_CASES_PATH,
    DEFAULT_SPEC_PATH,
    load_json,
    run_benchmark_suite,
)
from graph_tool_call import __version__

EVIDENCE_SCHEMA_VERSION = "launch-evidence-v1"
DEFAULT_OUTPUT = Path("benchmarks/results/releases/v0.36.0/dependency-chain-evidence.json")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_release_evidence() -> dict[str, Any]:
    """Return a stable subset of the commerce benchmark suitable for publication."""

    report = run_benchmark_suite(suite="commerce")
    pipelines = {row["name"]: row for row in report["pipelines"]}
    baseline = pipelines["target_only"]
    expanded = pipelines["graph_with_producers"]
    baseline_cases = {row["case_id"]: row for row in baseline["cases"]}
    expanded_cases = {row["case_id"]: row for row in expanded["cases"]}
    cases_doc = load_json(DEFAULT_CASES_PATH)
    lift = report["producer_expansion_lift"]

    cases = []
    for expected in cases_doc["cases"]:
        case_id = str(expected["id"])
        before = baseline_cases[case_id]
        after = expanded_cases[case_id]
        cases.append(
            {
                "case_id": case_id,
                "query": expected["query"],
                "expected_target": expected["expected_target"],
                "expected_producers": list(expected.get("expected_producers") or []),
                "retrieved": list(after["retrieved"]),
                "selected_target": after["selected_target"],
                "target_only_candidates": list(before["candidates"]),
                "expanded_candidates": list(after["candidates"]),
                "target_only": _case_metrics(before),
                "graph_with_producers": _case_metrics(after),
            }
        )

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "release_ref": "v0.36.0",
        "graph_tool_call_version": __version__,
        "benchmark": report["benchmark"],
        "methodology": report["methodology"],
        "model": report["model"],
        "replay": {
            "command": "make launch-evidence",
            "check_command": "make launch-evidence-check",
        },
        "dataset": {
            "spec_path": str(DEFAULT_SPEC_PATH.relative_to(REPOSITORY_ROOT)),
            "spec_sha256": _sha256(DEFAULT_SPEC_PATH),
            "cases_path": str(DEFAULT_CASES_PATH.relative_to(REPOSITORY_ROOT)),
            "cases_sha256": _sha256(DEFAULT_CASES_PATH),
            "case_count": len(cases),
            "tool_count": report["tool_count"],
            "edge_count": report["edge_count"],
        },
        "claims": {
            "target_recall_at_5": expanded["summary"]["target_recall_at_k"],
            "target_selector_exact": expanded["summary"]["target_selector_exact"],
            "producer_recall": dict(lift["producer_recall"]),
            "candidate_plan_coverage": dict(lift["candidate_plan_coverage"]),
            "candidate_binding_support": dict(lift["candidate_binding_support"]),
            "producer_needed_cases": lift["producer_needed_cases"],
            "unneeded_expansion_cases": lift["unneeded_expansion_cases"],
            "expanded_pipeline_status": expanded["summary"]["status"],
        },
        "limitations": [
            "Deterministic engine regression; no LLM is used.",
            "Seven curated commerce cases; not a population-level accuracy estimate.",
            "Measures retrieval, target selection, dependency expansion, and plan coverage.",
        ],
        "cases": cases,
    }


def _case_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_recall_at_k": row["target_recall_at_k"],
        "target_selector_exact": row["target_selector_exact"],
        "producer_recall": row["producer_recall"],
        "candidate_plan_coverage": row["candidate_plan_coverage"],
        "candidate_binding_support": row["candidate_binding_support"],
        "producer_added_count": row["producer_added_count"],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    evidence = build_release_evidence()
    rendered = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            print(f"Release evidence is stale: {args.output}")
            return 1
        print(f"Release evidence is reproducible: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote release evidence: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
