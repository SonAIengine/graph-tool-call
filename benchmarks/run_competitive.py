#!/usr/bin/env python3
"""Competitive retrieval benchmark: ablation study across retrieval strategies.

Compares 6 retrieval strategies on the same datasets, measuring Recall@5, MRR, MAP.
No LLM required — pure retrieval accuracy comparison.

Usage:
    poetry run python -m benchmarks.run_competitive
    poetry run python -m benchmarks.run_competitive --datasets petstore k8s
    poetry run python -m benchmarks.run_competitive --no-embedding  # skip embedding pipelines
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from benchmarks.config import DATASET_REGISTRY
from benchmarks.metrics import average_precision, mrr, ndcg_at_k, recall_at_k
from graph_tool_call import ToolGraph


@dataclass
class StrategyResult:
    """Aggregated results for one strategy on one dataset."""

    recall_5: float = 0.0
    mrr: float = 0.0
    map: float = 0.0
    ndcg_5: float = 0.0
    miss_rate: float = 0.0
    avg_latency_ms: float = 0.0
    query_count: int = 0


@dataclass
class Strategy:
    """A retrieval strategy configuration."""

    name: str
    label: str  # display label
    embedding: str | None = None
    weights: dict[str, float] | None = None


# 6 strategies for competitive comparison
STRATEGIES = [
    Strategy(
        name="vector-only",
        label="Vector Only (≈bigtool)",
        embedding="ollama/qwen3-embedding:0.6b",
        weights={"keyword": 0.0, "graph": 0.0, "embedding": 1.0, "annotation": 0.0},
    ),
    Strategy(
        name="bm25-only",
        label="BM25 Only",
        weights={"keyword": 1.0, "graph": 0.0, "embedding": 0.0, "annotation": 0.0},
    ),
    Strategy(
        name="graph-only",
        label="Graph Only",
        weights={"keyword": 0.0, "graph": 1.0, "embedding": 0.0, "annotation": 0.0},
    ),
    Strategy(
        name="bm25+graph",
        label="BM25 + Graph (default)",
    ),
    Strategy(
        name="vector+bm25",
        label="Vector + BM25 (hybrid)",
        embedding="ollama/qwen3-embedding:0.6b",
        weights={"keyword": 0.5, "graph": 0.0, "embedding": 0.5, "annotation": 0.0},
    ),
    Strategy(
        name="full",
        label="Full Pipeline (ours)",
        embedding="ollama/qwen3-embedding:0.6b",
    ),
]


def _build_tool_graph(sources: list[dict]) -> ToolGraph:
    tg = ToolGraph()
    for src in sources:
        if src["type"] == "openapi":
            tg.ingest_openapi(src["path"])
        elif src["type"] == "mcp":
            with open(src["path"]) as f:
                mcp_data = json.load(f)
            tg.ingest_mcp_tools(mcp_data["tools"])
    return tg


def run_strategy(
    tg_base: ToolGraph,
    strategy: Strategy,
    queries: list[dict],
    top_k: int = 5,
    verbose: bool = False,
) -> StrategyResult:
    """Run a single strategy on a set of queries."""
    # Clone the base graph for each strategy (to avoid contamination)
    # Re-build from scratch to ensure clean state
    tg = ToolGraph()
    for name, tool in tg_base.tools.items():
        tg._tools[name] = tool
        tg._builder.add_tool(tool)
    tg._register_tools_batch(list(tg_base.tools.values()))

    # Apply embedding if needed
    if strategy.embedding:
        try:
            tg.enable_embedding(strategy.embedding)
        except Exception as e:
            print(f"    ⚠ Embedding failed for {strategy.name}: {e}")
            return StrategyResult()

    # Apply custom weights if specified
    if strategy.weights:
        tg.set_weights(**strategy.weights)

    recalls = []
    mrrs = []
    aps = []
    ndcgs = []
    latencies = []

    for q in queries:
        expected = set(q["expected_tools"]) if isinstance(q["expected_tools"], list) else set()

        start = time.perf_counter()
        results = tg.retrieve_with_scores(q["query"], top_k=top_k)
        elapsed = (time.perf_counter() - start) * 1000

        retrieved = [r.tool.name for r in results]
        r = recall_at_k(retrieved, expected, top_k)
        m = mrr(retrieved, expected)
        ap = average_precision(retrieved, expected)
        nd = ndcg_at_k(retrieved, expected, top_k)

        recalls.append(r)
        mrrs.append(m)
        aps.append(ap)
        ndcgs.append(nd)
        latencies.append(elapsed)

        if verbose:
            mark = "✓" if r == 1.0 else "✗"
            print(f"      {mark} [{r:.0%}] {q['query'][:60]}")

    n = len(queries)
    miss_count = sum(1 for r in recalls if r == 0.0)
    return StrategyResult(
        recall_5=sum(recalls) / n,
        mrr=sum(mrrs) / n,
        map=sum(aps) / n,
        ndcg_5=sum(ndcgs) / n,
        miss_rate=miss_count / n,
        avg_latency_ms=sum(latencies) / n,
        query_count=n,
    )


def print_comparison(
    dataset_name: str,
    tool_count: int,
    query_count: int,
    results: dict[str, StrategyResult],
    strategies: list[Strategy],
) -> None:
    """Print a comparison table."""
    print(f"\n{'═' * 90}")
    print(f"  {dataset_name}  ({tool_count} tools, {query_count} queries)")
    print(f"{'═' * 90}")
    print(
        f"  {'Strategy':<28} {'Recall@5':>8}  {'MRR':>7}  {'MAP':>7}"
        f"  {'NDCG@5':>7}  {'Miss%':>6}  {'Latency':>8}"
    )
    print(f"  {'─' * 84}")

    # Find best values for highlighting
    best_recall = max(r.recall_5 for r in results.values())
    best_mrr = max(r.mrr for r in results.values())

    for s in strategies:
        r = results.get(s.name)
        if not r or r.query_count == 0:
            continue

        recall_str = f"{r.recall_5:.1%}"
        mrr_str = f"{r.mrr:.3f}"
        map_str = f"{r.map:.3f}"
        ndcg_str = f"{r.ndcg_5:.3f}"
        miss_str = f"{r.miss_rate:.1%}"
        lat_str = f"{r.avg_latency_ms:.1f}ms"

        # Mark best with star
        if r.recall_5 == best_recall:
            recall_str = f"*{recall_str}"
        if r.mrr == best_mrr:
            mrr_str = f"*{mrr_str}"

        print(
            f"  {s.label:<28} {recall_str:>8}  {mrr_str:>7}  {map_str:>7}"
            f"  {ndcg_str:>7}  {miss_str:>6}  {lat_str:>8}"
        )

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Competitive retrieval benchmark")
    parser.add_argument(
        "--datasets",
        "-d",
        nargs="+",
        default=None,
        help="Datasets to benchmark (default: all non-legacy)",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-embedding", action="store_true", help="Skip embedding strategies")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--save", action="store_true", help="Save results as JSON")
    args = parser.parse_args()

    dataset_names = args.datasets or [k for k, v in DATASET_REGISTRY.items() if not v.get("legacy")]

    active_strategies = [s for s in STRATEGIES if not (args.no_embedding and s.embedding)]

    print("\n  Competitive Retrieval Benchmark")
    print(f"  Strategies: {len(active_strategies)}")
    print(f"  Datasets: {len(dataset_names)}")
    if any(s.embedding for s in active_strategies):
        print("  Embedding: ollama/qwen3-embedding:0.6b")
    print()

    all_results: dict[str, dict[str, StrategyResult]] = {}

    for ds_name in dataset_names:
        reg = DATASET_REGISTRY.get(ds_name)
        if not reg or reg.get("legacy"):
            continue

        with open(reg["ground_truth"]) as f:
            gt = json.load(f)

        print(f"  [{ds_name}] Building graph...", end="", flush=True)
        tg_base = _build_tool_graph(reg["sources"])
        print(f" {len(tg_base.tools)} tools, {len(gt['queries'])} queries")

        ds_results: dict[str, StrategyResult] = {}
        for strategy in active_strategies:
            print(f"    → {strategy.label}...", end="", flush=True)
            result = run_strategy(
                tg_base,
                strategy,
                gt["queries"],
                top_k=args.top_k,
                verbose=args.verbose,
            )
            ds_results[strategy.name] = result
            print(f" Recall={result.recall_5:.1%} MRR={result.mrr:.3f}")

        print_comparison(
            gt["name"],
            gt.get("tool_count", len(tg_base.tools)),
            len(gt["queries"]),
            ds_results,
            active_strategies,
        )
        all_results[ds_name] = ds_results

    # Summary: average across all datasets
    if len(all_results) > 1:
        print(f"\n{'═' * 90}")
        print(f"  OVERALL AVERAGE (across {len(all_results)} datasets)")
        print(f"{'═' * 90}")
        print(
            f"  {'Strategy':<28} {'Recall@5':>8}  {'MRR':>7}  {'MAP':>7}"
            f"  {'Miss%':>6}  {'Latency':>8}"
        )
        print(f"  {'─' * 72}")

        avg_results: dict[str, StrategyResult] = {}
        for s in active_strategies:
            vals = [all_results[ds].get(s.name) for ds in all_results if s.name in all_results[ds]]
            vals = [v for v in vals if v and v.query_count > 0]
            if not vals:
                continue
            avg = StrategyResult(
                recall_5=sum(v.recall_5 for v in vals) / len(vals),
                mrr=sum(v.mrr for v in vals) / len(vals),
                map=sum(v.map for v in vals) / len(vals),
                miss_rate=sum(v.miss_rate for v in vals) / len(vals),
                avg_latency_ms=sum(v.avg_latency_ms for v in vals) / len(vals),
            )
            avg_results[s.name] = avg

        best_recall = max(r.recall_5 for r in avg_results.values())
        best_mrr = max(r.mrr for r in avg_results.values())

        for s in active_strategies:
            r = avg_results.get(s.name)
            if not r:
                continue
            rc = f"{'*' if r.recall_5 == best_recall else ''}{r.recall_5:.1%}"
            mr = f"{'*' if r.mrr == best_mrr else ''}{r.mrr:.3f}"
            mp = f"{r.map:.3f}"
            ms = f"{r.miss_rate:.1%}"
            lt = f"{r.avg_latency_ms:.1f}ms"
            print(f"  {s.label:<28} {rc:>8}  {mr:>7}  {mp:>7}  {ms:>6}  {lt:>8}")

        print(f"\n{'═' * 90}")

    if args.save:
        from pathlib import Path

        out = Path("benchmarks/results")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        save_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategies": [s.name for s in active_strategies],
            "datasets": {
                ds: {
                    sname: {
                        "recall_5": r.recall_5,
                        "mrr": r.mrr,
                        "map": r.map,
                        "ndcg_5": r.ndcg_5,
                        "miss_rate": r.miss_rate,
                        "avg_latency_ms": r.avg_latency_ms,
                        "query_count": r.query_count,
                    }
                    for sname, r in results.items()
                }
                for ds, results in all_results.items()
            },
        }
        path = out / f"competitive_{ts}.json"
        path.write_text(json.dumps(save_data, indent=2, ensure_ascii=False))
        print(f"\n  Results saved: {path}")


if __name__ == "__main__":
    main()
