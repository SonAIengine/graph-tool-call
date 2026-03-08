"""Baseline save/load/diff for pipeline benchmarks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from benchmarks.pipeline import PipelineBenchmarkReport, PipelineMetrics

BASELINE_DIR = Path("benchmarks/results")
BASELINE_FILE = BASELINE_DIR / "baseline.json"


def save_baseline(report: PipelineBenchmarkReport) -> Path:
    """Save current results as baseline for future comparison."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    BASELINE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return BASELINE_FILE


def load_baseline() -> PipelineBenchmarkReport | None:
    """Load saved baseline. Returns None if no baseline exists."""
    if not BASELINE_FILE.exists():
        return None
    data = json.loads(BASELINE_FILE.read_text())
    return PipelineBenchmarkReport.from_dict(data)


@dataclass
class DiffEntry:
    """A single metric difference between baseline and current."""

    dataset: str
    pipeline: str
    metric: str
    baseline_val: float
    current_val: float

    @property
    def delta(self) -> float:
        return self.current_val - self.baseline_val

    @property
    def improved(self) -> bool:
        # For accuracy/recall: higher is better
        # For latency/tokens: lower is better
        if self.metric in ("avg_latency_ms", "avg_input_tokens"):
            return self.delta < 0
        return self.delta > 0


def diff_reports(
    current: PipelineBenchmarkReport,
    baseline: PipelineBenchmarkReport,
) -> list[DiffEntry]:
    """Compare current results against baseline.

    Only compares datasets and pipelines that exist in both reports.
    """
    diffs: list[DiffEntry] = []

    # Build lookup: {dataset_name: {pipeline_name: PipelineMetrics}}
    baseline_lookup: dict[str, dict[str, PipelineMetrics]] = {}
    for ds in baseline.datasets:
        baseline_lookup[ds.name] = ds.metrics

    metrics_to_compare = [
        "accuracy",
        "avg_recall",
        "avg_input_tokens",
        "avg_latency_ms",
    ]

    for ds in current.datasets:
        if ds.name not in baseline_lookup:
            continue
        bl_metrics = baseline_lookup[ds.name]

        for pipeline_name, cur_m in ds.metrics.items():
            if pipeline_name not in bl_metrics:
                continue
            bl_m = bl_metrics[pipeline_name]

            for metric in metrics_to_compare:
                cur_val = getattr(cur_m, metric)
                bl_val = getattr(bl_m, metric)
                if cur_val != bl_val:
                    diffs.append(
                        DiffEntry(
                            dataset=ds.name,
                            pipeline=pipeline_name,
                            metric=metric,
                            baseline_val=bl_val,
                            current_val=cur_val,
                        )
                    )

    return diffs


def print_diff(diffs: list[DiffEntry]) -> None:
    """Print diff results as a table."""
    if not diffs:
        print("No differences found.")
        return

    # Group by dataset
    # Print table with columns: Pipeline | Metric | Baseline | Current | Delta
    # Use +/- for improved/degraded

    current_ds = ""
    for d in sorted(diffs, key=lambda x: (x.dataset, x.pipeline, x.metric)):
        if d.dataset != current_ds:
            current_ds = d.dataset
            print(f"\n  {d.dataset}")
            print(
                f"  {'Pipeline':<20s} {'Metric':<20s} "
                f"{'Baseline':>10s} {'Current':>10s} {'Delta':>10s}"
            )
            print(f"  {'─' * 70}")

        # Format values based on metric type
        if d.metric in ("accuracy", "avg_recall"):
            bl_str = f"{d.baseline_val:.1%}"
            cur_str = f"{d.current_val:.1%}"
            delta_str = f"{d.delta:+.1%}"
        elif d.metric == "avg_latency_ms":
            bl_str = f"{d.baseline_val:.0f}ms"
            cur_str = f"{d.current_val:.0f}ms"
            delta_str = f"{d.delta:+.0f}ms"
        else:
            bl_str = f"{d.baseline_val:.0f}"
            cur_str = f"{d.current_val:.0f}"
            delta_str = f"{d.delta:+.0f}"

        mark = "+" if d.improved else "-"
        print(
            f"  {d.pipeline:<20s} {d.metric:<20s} "
            f"{bl_str:>10s} {cur_str:>10s} {delta_str:>10s} {mark}"
        )
