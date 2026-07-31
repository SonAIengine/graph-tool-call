"""Offline clustered statistics for paired paper model-loop artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

from benchmarks.experiment.artifact import load_artifact, validate_artifact
from benchmarks.metrics import confidence_interval, stdev

from .catalog import B6B_BASELINE, B6C_BASELINE, MODEL_LOOP_BASELINES

MODEL_LOOP_ANALYSIS_REVISION = "paper-model-loop-clustered-repeat-v1"
EFFECTIVENESS_METRICS = (
    "selector_target_accuracy",
    "selector_producer_recall",
    "selector_required_tool_recall",
    "all_required_selected",
    "hydration_success",
    "plan_tool_validity",
    "argument_schema_validity",
    "required_input_accounting",
    "end_to_end_valid",
)


def pair_model_loop_cases(
    cases: list[dict[str, Any]],
) -> list[dict[str, dict[str, Any]]]:
    """Return complete B6b/B6c pairs and reject ambiguous condition rows."""
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for case in cases:
        context = case.get("context") or {}
        pair_key = str(context.get("pair_key") or "")
        baseline = str(context.get("baseline") or "")
        if not pair_key or baseline not in MODEL_LOOP_BASELINES:
            raise ValueError("Every model-loop condition requires a pair_key and known baseline.")
        if baseline in grouped[pair_key]:
            raise ValueError(f"Duplicate model-loop condition for {pair_key}: {baseline}")
        grouped[pair_key][baseline] = case

    expected = set(MODEL_LOOP_BASELINES)
    incomplete = sorted(pair_key for pair_key, pair in grouped.items() if set(pair) != expected)
    if incomplete:
        raise ValueError(f"Incomplete B6b/B6c pairs: {', '.join(incomplete)}")
    return [pair for _, pair in sorted(grouped.items())]


def summarize_paired_metric(
    paired_rows: list[dict[str, dict[str, Any]]],
    metric: str,
) -> dict[str, Any]:
    """Summarize one effectiveness metric over complete paired rows."""
    deltas = [_pair_delta(pair, metric) for pair in paired_rows]
    return {
        "mean_before": fmean(_metric(pair, B6B_BASELINE, metric) for pair in paired_rows)
        if paired_rows
        else 0.0,
        "mean_after": fmean(_metric(pair, B6C_BASELINE, metric) for pair in paired_rows)
        if paired_rows
        else 0.0,
        "mean_delta": fmean(deltas) if deltas else 0.0,
        "improvements": sum(delta > 0 for delta in deltas),
        "regressions": sum(delta < 0 for delta in deltas),
        "ties": sum(delta == 0 for delta in deltas),
    }


def analyze_paired_repeats(
    cases: list[dict[str, Any]],
    *,
    bootstrap_resamples: int,
    seed: int,
) -> dict[str, Any]:
    """Compute repeat stability and case-clustered paired bootstrap intervals."""
    if bootstrap_resamples <= 0:
        raise ValueError("bootstrap_resamples must be greater than zero.")
    paired_rows = pair_model_loop_cases(cases)
    if not paired_rows:
        raise ValueError("At least one complete B6b/B6c pair is required.")

    by_repeat: dict[int, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    by_cluster: dict[str, list[dict[str, dict[str, Any]]]] = defaultdict(list)
    cluster_repeats: dict[str, set[int]] = defaultdict(set)
    for pair in paired_rows:
        original_case_id, repeat = _pair_identity(pair)
        by_repeat[repeat].append(pair)
        by_cluster[original_case_id].append(pair)
        cluster_repeats[original_case_id].add(repeat)

    repeat_values = sorted(by_repeat)
    expected_cells = len(by_cluster) * len(repeat_values)
    observed_cells = sum(len(repeats) for repeats in cluster_repeats.values())
    repeat_summaries = [
        {
            "repeat": repeat,
            "pair_count": len(by_repeat[repeat]),
            "metrics": {
                metric: summarize_paired_metric(by_repeat[repeat], metric)
                for metric in EFFECTIVENESS_METRICS
            },
        }
        for repeat in repeat_values
    ]

    metric_stability: dict[str, dict[str, Any]] = {}
    clustered_bootstrap: dict[str, dict[str, Any]] = {}
    for metric in EFFECTIVENESS_METRICS:
        per_repeat_deltas = [
            summarize_paired_metric(by_repeat[repeat], metric)["mean_delta"]
            for repeat in repeat_values
        ]
        cluster_deltas = {
            case_id: [_pair_delta(pair, metric) for pair in pairs]
            for case_id, pairs in sorted(by_cluster.items())
        }
        cluster_means = [fmean(values) for values in cluster_deltas.values()]
        consistency_evaluable = [values for values in cluster_deltas.values() if len(values) >= 2]
        metric_stability[metric] = {
            "per_repeat_mean_deltas": per_repeat_deltas,
            "per_repeat_mean_delta_range": [min(per_repeat_deltas), max(per_repeat_deltas)],
            "mean_delta_stdev": stdev(per_repeat_deltas),
            "aggregate_mean_delta_exact_across_repeats": len(set(per_repeat_deltas)) == 1,
            "repeat_consistency_evaluable_cluster_count": len(consistency_evaluable),
            "repeat_consistency_unevaluable_cluster_count": (
                len(cluster_deltas) - len(consistency_evaluable)
            ),
            "pair_outcome_consistency_rate": (
                fmean(float(len(set(values)) == 1) for values in consistency_evaluable)
                if consistency_evaluable
                else None
            ),
        }
        clustered_bootstrap[metric] = {
            "confidence": 0.95,
            "n_resamples": bootstrap_resamples,
            "cluster_key": "original_case_id",
            "cluster_count": len(cluster_means),
            "repeated_pair_count": len(paired_rows),
            "within_cluster_aggregation": "mean_delta",
            "mean_delta": fmean(cluster_means),
            "mean_delta_ci": list(
                confidence_interval(
                    cluster_means,
                    n_bootstrap=bootstrap_resamples,
                    seed=seed,
                )
            ),
        }

    return {
        "revision": MODEL_LOOP_ANALYSIS_REVISION,
        "design": {
            "cluster_key": "original_case_id",
            "cluster_count": len(by_cluster),
            "repeat_count": len(repeat_values),
            "repeated_pair_count": len(paired_rows),
            "complete_repeat_grid_rate": observed_cells / expected_cells,
            "within_cluster_aggregation": "mean_delta",
        },
        "repeat_summaries": repeat_summaries,
        "metric_stability": metric_stability,
        "clustered_paired_bootstrap": clustered_bootstrap,
    }


def analyze_model_loop_artifact(
    artifact_path: str | Path,
    *,
    bootstrap_resamples: int = 10_000,
    seed: int | None = None,
) -> dict[str, Any]:
    """Analyze an existing model-loop artifact without making model calls."""
    path = Path(artifact_path).resolve()
    artifact = load_artifact(path)
    validation = validate_artifact(artifact, artifact_path=str(path))
    if not validation.valid:
        codes = ", ".join(issue.code for issue in validation.issues)
        raise ValueError(f"Model-loop artifact is invalid: {codes}")
    if artifact.run_kind != "model" or artifact.benchmark != (
        "public-heterogeneous-tool-selection-and-plan"
    ):
        raise ValueError("Artifact is not a paper model-loop run.")

    resolved_seed = artifact.seed if seed is None else seed
    analysis = analyze_paired_repeats(
        artifact.cases,
        bootstrap_resamples=bootstrap_resamples,
        seed=resolved_seed,
    )
    report: dict[str, Any] = {
        "analysis_revision": MODEL_LOOP_ANALYSIS_REVISION,
        "source": {
            "artifact_id": artifact.artifact_id,
            "run_id": artifact.run_id,
            "sha256": _sha256_file(path),
        },
        "config": {
            "bootstrap_resamples": bootstrap_resamples,
            "seed": resolved_seed,
            "model_calls_performed": 0,
        },
        "analysis": analysis,
    }
    report["analysis_id"] = f"analysis-{_digest(report)[:24]}"
    return report


def write_analysis(path: str | Path, report: dict[str, Any]) -> Path:
    """Write a deterministic offline analysis report."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _pair_identity(pair: dict[str, dict[str, Any]]) -> tuple[str, int]:
    identities = {
        (
            str((case.get("context") or {}).get("original_case_id") or ""),
            (case.get("context") or {}).get("repeat"),
        )
        for case in pair.values()
    }
    if len(identities) != 1:
        raise ValueError("Paired conditions must share original_case_id and repeat.")
    original_case_id, repeat = identities.pop()
    if not original_case_id or not isinstance(repeat, int) or isinstance(repeat, bool):
        raise ValueError("Paired conditions require original_case_id and integer repeat.")
    return original_case_id, repeat


def _metric(pair: dict[str, dict[str, Any]], baseline: str, metric: str) -> float:
    value = (pair[baseline].get("metrics") or {}).get(metric)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Paired condition is missing numeric metric: {metric}")
    return float(value)


def _pair_delta(pair: dict[str, dict[str, Any]], metric: str) -> float:
    return _metric(pair, B6C_BASELINE, metric) - _metric(pair, B6B_BASELINE, metric)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, help="Bootstrap seed; defaults to artifact.seed.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = analyze_model_loop_artifact(
        args.artifact,
        bootstrap_resamples=args.bootstrap_resamples,
        seed=args.seed,
    )
    output = write_analysis(args.out, report)
    print(f"analysis={output}")
    print(f"analysis_id={report['analysis_id']}")
    print(json.dumps(report["analysis"]["design"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
