#!/usr/bin/env python3
"""Run retrieval benchmarks across search tiers.

Usage:
    python -m benchmarks.run_benchmark
    python -m benchmarks.run_benchmark --dataset petstore
    python -m benchmarks.run_benchmark --dataset synthetic --n-tools 500
"""

from __future__ import annotations

import argparse
import time

from benchmarks.datasets import QueryCase, petstore_dataset, synthetic_dataset
from benchmarks.metrics import ndcg_at_k, precision_at_k, recall_at_k, workflow_coverage
from graph_tool_call import ToolGraph
from graph_tool_call.retrieval.engine import SearchMode


def run_tier(
    tg: ToolGraph,
    queries: list[QueryCase],
    mode: SearchMode,
    top_k: int = 5,
) -> dict[str, float]:
    """Run a benchmark tier and return aggregated metrics."""
    precisions: list[float] = []
    recalls: list[float] = []
    ndcgs: list[float] = []
    coverages: list[float] = []
    latencies: list[float] = []

    for case in queries:
        start = time.perf_counter()
        results = tg.retrieve(case.query, top_k=top_k, mode=mode)
        elapsed = time.perf_counter() - start

        retrieved_names = [r.name for r in results]
        latencies.append(elapsed * 1000)  # ms

        precisions.append(precision_at_k(retrieved_names, case.relevant_tools, top_k))
        recalls.append(recall_at_k(retrieved_names, case.relevant_tools, top_k))
        ndcgs.append(ndcg_at_k(retrieved_names, case.relevant_tools, top_k))

        if case.workflow:
            coverages.append(workflow_coverage(retrieved_names, case.workflow))

    n = len(queries)
    return {
        "precision@k": sum(precisions) / n if n else 0,
        "recall@k": sum(recalls) / n if n else 0,
        "ndcg@k": sum(ndcgs) / n if n else 0,
        "workflow_coverage": sum(coverages) / len(coverages) if coverages else 0,
        "avg_latency_ms": sum(latencies) / n if n else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval benchmarks")
    parser.add_argument("--dataset", choices=["petstore", "synthetic"], default="petstore")
    parser.add_argument(
        "--n-tools",
        type=int,
        default=500,
        help="Tools count for synthetic dataset",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Top-K for retrieval")
    args = parser.parse_args()

    # Load dataset
    if args.dataset == "petstore":
        tools, queries = petstore_dataset()
    else:
        tools, queries = synthetic_dataset(n=args.n_tools)

    # Build ToolGraph
    tg = ToolGraph()
    for tool in tools:
        tg._tools[tool.name] = tool
        tg._builder.add_tool(tool)

    print(f"Dataset: {args.dataset}")
    print(f"Tools: {len(tools)}, Queries: {len(queries)}, top_k: {args.top_k}")
    print("=" * 70)

    # Run each tier
    for mode in [SearchMode.BASIC, SearchMode.ENHANCED, SearchMode.FULL]:
        metrics = run_tier(tg, queries, mode=mode, top_k=args.top_k)
        print(f"\n{mode.value.upper()}")
        print(f"  Precision@{args.top_k}: {metrics['precision@k']:.3f}")
        print(f"  Recall@{args.top_k}:    {metrics['recall@k']:.3f}")
        print(f"  NDCG@{args.top_k}:      {metrics['ndcg@k']:.3f}")
        if metrics["workflow_coverage"] > 0:
            print(f"  Workflow Coverage: {metrics['workflow_coverage']:.3f}")
        print(f"  Avg Latency:       {metrics['avg_latency_ms']:.1f}ms")


if __name__ == "__main__":
    main()
