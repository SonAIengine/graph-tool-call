"""Evaluate dependency closure over automatically constructed OpenAPI graphs.

The expected target is supplied only after retrieval so this benchmark isolates
OpenAPI contract extraction and graph construction quality. Ground-truth
producers are used for scoring and are never passed to graph construction or
dependency completion.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from benchmarks.corpus.manifest import (
    DEFAULT_MANIFEST_PATH,
    load_corpus_manifest,
    validate_corpus_manifest,
)
from benchmarks.experiment.artifact import (
    ExperimentArtifact,
    finalize_artifact,
    validate_artifact,
    write_artifact,
)
from benchmarks.metrics import confidence_interval
from graph_tool_call import ingest_source
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import (
    DEPENDENCY_CLOSURE_POLICY_REVISION,
    complete_target_dependencies,
    ingest_openapi_graphify,
)

OPENAPI_CLOSURE_METHODOLOGY = "oracle-target-automatic-openapi-closure-v1"
OPENAPI_CLOSURE_PROMOTION_POLICY = "openapi-closure-promotion-v1"
MIN_DEPENDENCY_CASES = 30
MIN_REQUIRED_PRODUCER_RECALL = 0.80
MIN_ALL_REQUIRED_FOUND_RATE = 0.70
MAX_UNEXPECTED_DEPENDENCIES_PER_CASE = 1.0


def run_openapi_dependency_closure(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    splits: tuple[str, ...] = ("train", "dev"),
    output_path: str | Path = "/tmp/graph-tool-call-openapi-closure.json",
    allow_held_out: bool = False,
    max_hops: int = 3,
    consumer_aligned: bool = True,
    bootstrap_resamples: int = 1000,
    seed: int = 17,
    created_at: str | None = None,
) -> ExperimentArtifact:
    """Evaluate automatic OpenAPI dependency closure on the public corpus."""
    normalized_splits = tuple(dict.fromkeys(value.strip() for value in splits if value.strip()))
    invalid = sorted(set(normalized_splits) - {"train", "dev", "test"})
    if not normalized_splits or invalid:
        raise ValueError(f"splits must contain train, dev, or test; invalid={invalid}")
    if "test" in normalized_splits and not allow_held_out:
        raise ValueError("Held-out test access requires --allow-held-out.")
    if max_hops < 0:
        raise ValueError("max_hops must be non-negative.")
    if bootstrap_resamples <= 0:
        raise ValueError("bootstrap_resamples must be greater than zero.")

    manifest_file = Path(manifest_path).resolve()
    report = validate_corpus_manifest(manifest_file, verify_hashes=True, verify_ingest=True)
    if not report.integrity_ready:
        blockers = [
            issue.code
            for issue in report.issues
            if issue.scope == "integrity" and issue.severity == "blocker"
        ]
        raise ValueError(f"Corpus integrity validation failed: {blockers}")

    manifest = load_corpus_manifest(manifest_file)
    manifest_root = manifest_file.parent
    cases: list[dict[str, Any]] = []
    source_summaries: dict[str, dict[str, Any]] = {}
    selected_sources = [
        source
        for source in manifest.get("sources") or []
        if source.get("source_type") == "openapi"
        and source.get("split") in normalized_splits
        and source.get("audit_status") != "excluded"
    ]
    for source in selected_sources:
        source_cases, source_summary = _evaluate_source(
            source,
            manifest_root=manifest_root,
            max_hops=max_hops,
            consumer_aligned=consumer_aligned,
        )
        cases.extend(source_cases)
        source_summaries[str(source["id"])] = source_summary

    summary = _summarize(cases, source_summaries)
    dependency_cases = [case for case in cases if case["expected_required_producers"]]
    scored_cases = dependency_cases or cases
    recall_values = [float(case["metrics"]["required_producer_recall"]) for case in scored_cases]
    all_required_values = [float(case["metrics"]["all_required_found"]) for case in scored_cases]
    statistics = {
        "method": "case_bootstrap",
        "resamples": bootstrap_resamples,
        "confidence": 0.95,
        "required_producer_recall": _mean_interval(
            recall_values,
            seed=seed,
            bootstrap_resamples=bootstrap_resamples,
        ),
        "all_required_found": _mean_interval(
            all_required_values,
            seed=seed + 1,
            bootstrap_resamples=bootstrap_resamples,
        ),
    }
    manifest_sha256 = _sha256(manifest_file)
    replay_command = [
        "poetry",
        "run",
        "python",
        "-m",
        "benchmarks.openapi_dependency_closure",
        "--manifest",
        str(manifest_path),
        "--splits",
        ",".join(normalized_splits),
        "--max-hops",
        str(max_hops),
        "--bootstrap-resamples",
        str(bootstrap_resamples),
        "--seed",
        str(seed),
        "--out",
        str(output_path),
    ]
    if allow_held_out:
        replay_command.append("--allow-held-out")
    if not consumer_aligned:
        replay_command.append("--no-consumer-aligned")

    artifact = ExperimentArtifact(
        benchmark="automatic-openapi-dependency-closure",
        methodology=OPENAPI_CLOSURE_METHODOLOGY,
        run_kind="deterministic",
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        seed=seed,
        dataset={
            "id": str(manifest.get("corpus_id") or "openapi-corpus"),
            "split": _artifact_split(normalized_splits),
            "splits": list(normalized_splits),
            "manifest_sha256": manifest_sha256,
            "source_count": len(selected_sources),
            "family_count": len({source.get("family_id") for source in selected_sources}),
            "case_count": len(cases),
            "source_types": ["openapi"],
            "automatic_graph_construction_evaluated": True,
            "oracle_target_used_for_retrieval": False,
            "oracle_target_used_for_closure_isolation": True,
        },
        config={
            "policy_revision": DEPENDENCY_CLOSURE_POLICY_REVISION,
            "methodology_revision": OPENAPI_CLOSURE_METHODOLOGY,
            "graph_builder": (
                "ingest_openapi_graphify:consumer_aligned_contract"
                if consumer_aligned
                else "ingest_openapi_graphify:default"
            ),
            "derive_semantic_metadata": True,
            "promote_contract_signals": True,
            "contract_signal_options": _contract_signal_options(consumer_aligned),
            "max_hops": max_hops,
            "ground_truth_producers_used_for_completion": False,
            "ground_truth_producers_used_for_scoring": True,
            "evaluation_roles": {
                "target": "oracle_after_retrieval",
                "dependencies": "automatic_graph_and_contract_only",
                "available_fields": "none_provided",
            },
        },
        replay={"command": replay_command, "working_directory": "."},
        summary=summary,
        statistics=statistics,
        cases=cases,
        source={"type": "public_corpus_manifest", "sha256": manifest_sha256},
    )
    finalize_artifact(artifact)
    validation = validate_artifact(artifact)
    if not validation.valid:
        codes = ", ".join(issue.code for issue in validation.issues)
        raise ValueError(f"Generated experiment artifact is invalid: {codes}")
    write_artifact(output_path, artifact)
    return artifact


def evaluate_openapi_dependency_cases(
    tools: list[ToolSchema],
    ground_truth_cases: list[dict[str, Any]],
    *,
    source_id: str,
    split: str,
    max_hops: int = 3,
    consumer_aligned: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evaluate already-ingested tools without exposing labels to graph build."""
    started = time.perf_counter()
    graph, graph_stats = ingest_openapi_graphify(
        _clone_tools(tools),
        promote_contract_signals=True,
        contract_signal_options=_contract_signal_options(consumer_aligned),
        derive_semantic_metadata=True,
    )
    graph_build_ms = (time.perf_counter() - started) * 1000
    available_names = set(graph.tools)
    evaluated: list[dict[str, Any]] = []
    for raw_case in ground_truth_cases:
        targets = [str(value) for value in raw_case.get("expected_targets") or [] if str(value)]
        expected = {str(value) for value in raw_case.get("required_producers") or [] if str(value)}
        fallback_target = targets[0] if targets else ""
        target = next((name for name in targets if name in available_names), fallback_target)
        started = time.perf_counter()
        closure = complete_target_dependencies(
            target,
            graph.tools,
            graph=graph,
            max_hops=max_hops,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        actual = list(closure.required_dependencies)
        found = sorted(expected.intersection(actual))
        missing = sorted(expected.difference(actual))
        unexpected = sorted(set(actual).difference(expected))
        recall = len(found) / len(expected) if expected else 1.0
        evaluated.append(
            {
                "case_id": str(raw_case.get("case_id") or ""),
                "source_id": source_id,
                "split": split,
                "query": str(raw_case.get("query") or ""),
                "expected_targets": targets,
                "oracle_target": target,
                "expected_required_producers": sorted(expected),
                "automatic_required_dependencies": actual,
                "metrics": {
                    "required_producer_recall": recall,
                    "all_required_found": float(not missing),
                    "unexpected_dependency_count": len(unexpected),
                    "closure_complete": float(closure.complete),
                    "latency_ms": latency_ms,
                },
                "diagnostics": {
                    "found_required_producers": found,
                    "missing_required_producers": missing,
                    "unexpected_dependencies": unexpected,
                    "unresolved_fields": closure.unresolved_fields,
                    "cycles": closure.cycles,
                    "evidence": closure.evidence,
                    "policy_revision": closure.policy_revision,
                },
            }
        )
    return evaluated, {
        "source_id": source_id,
        "tool_count": len(graph.tools),
        "edge_count": int(graph_stats.get("edge_count") or 0),
        "graph_build_ms": graph_build_ms,
        "graph_stats": graph_stats,
    }


def _evaluate_source(
    source: dict[str, Any],
    *,
    manifest_root: Path,
    max_hops: int,
    consumer_aligned: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for key in ("id", "split", "snapshot_path", "ground_truth_path"):
        if not source.get(key):
            raise ValueError(f"OpenAPI corpus source is missing required field: {key}")
    snapshot = _read_json(manifest_root / str(source["snapshot_path"]))
    ingest_options = dict(source.get("ingest_options") or {})
    if "format_hint" in ingest_options:
        raise ValueError("ingest_options must not override source adapter format_hint.")
    ingest_result = ingest_source(
        snapshot,
        format_hint=str(source.get("adapter") or "openapi"),
        **ingest_options,
    )
    unique = {tool.name: tool for tool in ingest_result.tools}
    ground_truth = _read_json(manifest_root / str(source["ground_truth_path"]))
    if not isinstance(ground_truth.get("cases"), list) or not ground_truth["cases"]:
        raise ValueError(f"OpenAPI ground truth must contain non-empty cases: {source['id']}")
    return evaluate_openapi_dependency_cases(
        sorted(unique.values(), key=lambda tool: (tool.name.casefold(), tool.name)),
        list(ground_truth.get("cases") or []),
        source_id=str(source["id"]),
        split=str(source["split"]),
        max_hops=max_hops,
        consumer_aligned=consumer_aligned,
    )


def _summarize(
    cases: list[dict[str, Any]],
    source_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    dependency_cases = [case for case in cases if case["expected_required_producers"]]
    scored = dependency_cases

    def mean(metric: str, rows: list[dict[str, Any]] = scored) -> float:
        return fmean(float(case["metrics"][metric]) for case in rows) if rows else 0.0

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_source[str(case["source_id"])].append(case)
    result = {
        "case_count": len(cases),
        "dependency_case_count": len(dependency_cases),
        "source_count": len(source_summaries),
        "required_producer_recall": mean("required_producer_recall"),
        "all_required_found_rate": mean("all_required_found"),
        "closure_complete_rate": mean("closure_complete", cases),
        "dependency_closure_complete_rate": mean("closure_complete", dependency_cases),
        "unexpected_dependency_count": sum(
            int(case["metrics"]["unexpected_dependency_count"]) for case in cases
        ),
        "unexpected_dependency_count_on_dependency_cases": sum(
            int(case["metrics"]["unexpected_dependency_count"]) for case in dependency_cases
        ),
        "per_source": {
            source_id: {
                **source_summaries[source_id],
                "case_count": len(rows),
                "dependency_case_count": sum(
                    bool(case["expected_required_producers"]) for case in rows
                ),
                "required_producer_recall": mean(
                    "required_producer_recall",
                    [case for case in rows if case["expected_required_producers"]],
                ),
                "all_required_found_rate": mean(
                    "all_required_found",
                    [case for case in rows if case["expected_required_producers"]],
                ),
            }
            for source_id, rows in sorted(by_source.items())
        },
    }
    result["promotion_gate"] = _promotion_gate(result, dependency_cases)
    return result


def _promotion_gate(
    summary: dict[str, Any],
    dependency_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    dependency_count = len(dependency_cases)
    unexpected = sum(
        int(case["metrics"]["unexpected_dependency_count"]) for case in dependency_cases
    )
    unexpected_per_case = unexpected / dependency_count if dependency_count else 0.0
    checks = {
        "minimum_dependency_cases": {
            "actual": dependency_count,
            "threshold": MIN_DEPENDENCY_CASES,
            "passed": dependency_count >= MIN_DEPENDENCY_CASES,
        },
        "required_producer_recall": {
            "actual": float(summary["required_producer_recall"]),
            "threshold": MIN_REQUIRED_PRODUCER_RECALL,
            "passed": float(summary["required_producer_recall"]) >= MIN_REQUIRED_PRODUCER_RECALL,
        },
        "all_required_found_rate": {
            "actual": float(summary["all_required_found_rate"]),
            "threshold": MIN_ALL_REQUIRED_FOUND_RATE,
            "passed": float(summary["all_required_found_rate"]) >= MIN_ALL_REQUIRED_FOUND_RATE,
        },
        "unexpected_dependencies_per_case": {
            "actual": unexpected_per_case,
            "threshold": MAX_UNEXPECTED_DEPENDENCIES_PER_CASE,
            "passed": unexpected_per_case <= MAX_UNEXPECTED_DEPENDENCIES_PER_CASE,
        },
    }
    return {
        "policy_revision": OPENAPI_CLOSURE_PROMOTION_POLICY,
        "passed": all(row["passed"] for row in checks.values()),
        "checks": checks,
    }


def _mean_interval(
    values: list[float],
    *,
    seed: int,
    bootstrap_resamples: int,
) -> dict[str, float]:
    low, high = confidence_interval(values, n_bootstrap=bootstrap_resamples, seed=seed)
    return {"mean": fmean(values) if values else 0.0, "ci95_low": low, "ci95_high": high}


def _clone_tools(tools: list[ToolSchema]) -> list[ToolSchema]:
    return copy.deepcopy(tools)


def _contract_signal_options(consumer_aligned: bool) -> dict[str, Any]:
    if not consumer_aligned:
        return {}
    return {
        "promote_consumer_aligned_produces": True,
        "max_consumer_aligned_paths_per_field": 1,
    }


def _artifact_split(splits: tuple[str, ...]) -> str:
    return splits[0] if len(splits) == 1 else "mixed"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_splits(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--splits", type=_parse_splits, default=("train", "dev"))
    parser.add_argument("--out", default="/tmp/graph-tool-call-openapi-closure.json")
    parser.add_argument("--allow-held-out", action="store_true")
    parser.add_argument("--max-hops", type=int, default=3)
    parser.add_argument(
        "--consumer-aligned",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args(argv)
    artifact = run_openapi_dependency_closure(
        args.manifest,
        splits=args.splits,
        output_path=args.out,
        allow_held_out=args.allow_held_out,
        max_hops=args.max_hops,
        consumer_aligned=args.consumer_aligned,
        bootstrap_resamples=args.bootstrap_resamples,
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                key: artifact.summary[key]
                for key in (
                    "case_count",
                    "dependency_case_count",
                    "source_count",
                    "required_producer_recall",
                    "all_required_found_rate",
                    "closure_complete_rate",
                    "unexpected_dependency_count",
                    "promotion_gate",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
