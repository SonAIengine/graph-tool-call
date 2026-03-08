"""Benchmark result reporting — console table + JSON output."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class QueryResult:
    """Result for a single benchmark query."""

    query: str = ""
    category: str = ""
    difficulty: str = ""
    expected_tools: list[str] = field(default_factory=list)

    # Retrieval metrics
    recall_at_k: float = 0.0
    retrieved_tools: list[str] = field(default_factory=list)

    # LLM metrics (None if retrieval-only mode)
    baseline_tool: str | None = None
    baseline_correct: bool | None = None
    baseline_latency_ms: float = 0.0
    baseline_input_tokens: int = 0

    retrieve_tool: str | None = None
    retrieve_correct: bool | None = None
    retrieve_latency_ms: float = 0.0
    retrieve_input_tokens: int = 0

    error: str | None = None


@dataclass
class DatasetResult:
    """Aggregated results for one dataset."""

    name: str = ""
    tool_count: int = 0
    query_count: int = 0
    queries: list[QueryResult] = field(default_factory=list)

    # Retrieval-only metrics
    avg_recall_at_k: float = 0.0

    # LLM comparison metrics
    baseline_accuracy: float = 0.0
    retrieve_accuracy: float = 0.0
    avg_token_reduction: float = 0.0
    avg_baseline_latency_ms: float = 0.0
    avg_retrieve_latency_ms: float = 0.0


@dataclass
class BenchmarkReport:
    """Full benchmark report."""

    timestamp: str = ""
    model: str | None = None
    mode: str = "retrieval_only"
    top_k: int = 5
    datasets: list[DatasetResult] = field(default_factory=list)


def compute_dataset_metrics(ds: DatasetResult) -> None:
    """Compute aggregate metrics from individual query results."""
    if not ds.queries:
        return

    n = len(ds.queries)
    ds.query_count = n

    # Recall@K
    ds.avg_recall_at_k = sum(q.recall_at_k for q in ds.queries) / n

    # LLM metrics (only if present)
    baseline_results = [q for q in ds.queries if q.baseline_correct is not None]
    retrieve_results = [q for q in ds.queries if q.retrieve_correct is not None]

    if baseline_results:
        ds.baseline_accuracy = sum(1 for q in baseline_results if q.baseline_correct) / len(
            baseline_results
        )
    if retrieve_results:
        ds.retrieve_accuracy = sum(1 for q in retrieve_results if q.retrieve_correct) / len(
            retrieve_results
        )

    # Token reduction
    token_pairs = [
        (q.baseline_input_tokens, q.retrieve_input_tokens)
        for q in ds.queries
        if q.baseline_input_tokens > 0 and q.retrieve_input_tokens > 0
    ]
    if token_pairs:
        reductions = [(b - r) / b for b, r in token_pairs]
        ds.avg_token_reduction = sum(reductions) / len(reductions)

    # Latency
    baseline_lats = [q.baseline_latency_ms for q in ds.queries if q.baseline_latency_ms > 0]
    retrieve_lats = [q.retrieve_latency_ms for q in ds.queries if q.retrieve_latency_ms > 0]
    if baseline_lats:
        ds.avg_baseline_latency_ms = sum(baseline_lats) / len(baseline_lats)
    if retrieve_lats:
        ds.avg_retrieve_latency_ms = sum(retrieve_lats) / len(retrieve_lats)


def print_retrieval_report(report: BenchmarkReport) -> None:
    """Print retrieval-only benchmark results as a console table."""
    print(f"\n{'=' * 70}")
    print(f"  Retrieval Benchmark  |  top_k={report.top_k}")
    print(f"{'=' * 70}")

    for ds in report.datasets:
        print(f"\n  {ds.name}  ({ds.tool_count} tools, {ds.query_count} queries)")
        print(f"  {'─' * 50}")
        print(f"  {'Recall@' + str(report.top_k):<20} {ds.avg_recall_at_k:.1%}")

        # Breakdown by category
        cats: dict[str, list[float]] = {}
        for q in ds.queries:
            cats.setdefault(q.category, []).append(q.recall_at_k)
        if len(cats) > 1:
            for cat, scores in sorted(cats.items()):
                avg = sum(scores) / len(scores)
                print(f"    {cat:<18} {avg:.1%}  ({len(scores)} queries)")

        # Breakdown by difficulty
        diffs: dict[str, list[float]] = {}
        for q in ds.queries:
            diffs.setdefault(q.difficulty, []).append(q.recall_at_k)
        if len(diffs) > 1:
            print()
            for diff in ["easy", "medium", "hard"]:
                if diff in diffs:
                    scores = diffs[diff]
                    avg = sum(scores) / len(scores)
                    print(f"    {diff:<18} {avg:.1%}  ({len(scores)} queries)")

    print(f"\n{'=' * 70}")


def print_llm_report(report: BenchmarkReport) -> None:
    """Print full LLM comparison benchmark results."""
    print(f"\n{'=' * 70}")
    print(f"  LLM Benchmark  |  model={report.model}  top_k={report.top_k}")
    print(f"{'=' * 70}")

    for ds in report.datasets:
        print(f"\n  {ds.name}  ({ds.tool_count} tools, {ds.query_count} queries)")
        print(f"  {'─' * 60}")
        print(f"  {'Metric':<25} {'Baseline':>12} {'Retrieve':>12} {'Delta':>10}")
        print(f"  {'─' * 60}")

        ba = f"{ds.baseline_accuracy:.1%}"
        ra = f"{ds.retrieve_accuracy:.1%}"
        print(f"  {'Tool Accuracy':<25} {ba:>12} {ra:>12}", end="")
        delta = ds.retrieve_accuracy - ds.baseline_accuracy
        sign = "+" if delta >= 0 else ""
        print(f" {sign}{delta:>8.1%}")

        if ds.avg_token_reduction > 0:
            print(f"  {'Token Reduction':<25} {'—':>12} {ds.avg_token_reduction:>11.1%}")

        if ds.avg_baseline_latency_ms > 0 and ds.avg_retrieve_latency_ms > 0:
            bl = ds.avg_baseline_latency_ms
            rl = ds.avg_retrieve_latency_ms
            speedup = (bl - rl) / bl if bl > 0 else 0
            print(f"  {'Avg Latency':<25} {bl:>10.0f}ms {rl:>10.0f}ms {speedup:>9.1%}")

        print(f"  {'Recall@' + str(report.top_k):<25} {'—':>12} {ds.avg_recall_at_k:>11.1%}")

    print(f"\n{'=' * 70}")

    # Per-query detail for failures
    failures = []
    for ds in report.datasets:
        for q in ds.queries:
            if q.retrieve_correct is False:
                failures.append((ds.name, q))

    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for ds_name, q in failures:
            print(f'    [{ds_name}] "{q.query}"')
            print(f"      expected: {q.expected_tools}  got: {q.retrieve_tool}")


def save_report(report: BenchmarkReport, output_dir: str) -> Path:
    """Save benchmark report as JSON."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    mode = report.mode
    filename = f"benchmark_{mode}_{ts}.json"
    path = out / filename

    data = asdict(report)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  Report saved: {path}")
    return path
