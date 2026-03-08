#!/usr/bin/env python3
"""Embedding benchmark — compare BM25-only vs BM25+Embedding retrieval.

Usage:
    python -m benchmarks.run_embedding_benchmark
    python -m benchmarks.run_embedding_benchmark --embedding "vllm/qwen3-0.6b@http://localhost:8100/v1"
    python -m benchmarks.run_embedding_benchmark --embedding "ollama/nomic-embed-text"
"""

from __future__ import annotations

import argparse
import json
import time

from benchmarks.config import DATASET_REGISTRY
from benchmarks.metrics import recall_at_k
from graph_tool_call import ToolGraph


def _load_ground_truth(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


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


def run_comparison(
    datasets: list[str],
    embedding_spec: str,
    top_k: int = 5,
    verbose: bool = False,
) -> None:
    """Run BM25-only vs BM25+Embedding comparison."""

    print(f"Embedding: {embedding_spec}")
    print(f"Top-K: {top_k}")
    print(f"{'=' * 80}")

    for ds_name in datasets:
        reg = DATASET_REGISTRY.get(ds_name)
        if not reg or reg.get("legacy"):
            continue

        gt = _load_ground_truth(reg["ground_truth"])
        queries = gt["queries"]

        # --- Build graph WITHOUT embedding ---
        tg_bm25 = _build_tool_graph(reg["sources"])

        # --- Build graph WITH embedding (via public API) ---
        tg_emb = _build_tool_graph(reg["sources"])

        t0 = time.perf_counter()
        tg_emb.enable_embedding(embedding_spec)
        build_time = (time.perf_counter() - t0) * 1000

        print(f"\n  {gt['name']}  ({gt.get('tool_count', len(tg_emb._tools))} tools)")
        print(f"  Embedding build: {build_time:.0f}ms")
        print(f"  {'─' * 70}")

        bm25_recalls = []
        emb_recalls = []
        improved = []
        degraded = []

        for q in queries:
            expected = set(q["expected_tools"])

            # BM25 only
            r1 = tg_bm25.retrieve(q["query"], top_k=top_k)
            names1 = [r.name for r in r1]
            recall1 = recall_at_k(names1, expected, top_k)
            bm25_recalls.append(recall1)

            # BM25 + Embedding
            r2 = tg_emb.retrieve(q["query"], top_k=top_k)
            names2 = [r.name for r in r2]
            recall2 = recall_at_k(names2, expected, top_k)
            emb_recalls.append(recall2)

            if verbose:
                if recall2 > recall1:
                    mark = "⬆"
                elif recall2 < recall1:
                    mark = "⬇"
                else:
                    mark = " "
                print(f"    {mark} [{recall1:.0%}→{recall2:.0%}] {q['query']}")
                if recall2 > recall1:
                    print(f"        BM25: {names1}")
                    print(f"        +Emb: {names2}")

            if recall2 > recall1:
                improved.append(q["query"])
            elif recall2 < recall1:
                degraded.append(q["query"])

        n = len(queries)
        avg_bm25 = sum(bm25_recalls) / n
        avg_emb = sum(emb_recalls) / n
        delta = avg_emb - avg_bm25

        print(f"\n  {'Metric':<30} {'BM25':>10} {'BM25+Emb':>10} {'Delta':>10}")
        print(f"  {'─' * 62}")
        sign = "+" if delta >= 0 else ""
        recall_label = f"Recall@{top_k}"
        print(f"  {recall_label:<30} {avg_bm25:>9.1%} {avg_emb:>9.1%} {sign}{delta:>8.1%}")
        print(f"  {'Improved queries':<30} {len(improved):>10}")
        print(f"  {'Degraded queries':<30} {len(degraded):>10}")
        print(f"  {'No change':<30} {n - len(improved) - len(degraded):>10}")

        if improved:
            print("\n  Improved:")
            for q in improved:
                print(f"    + {q}")
        if degraded:
            print("\n  Degraded:")
            for q in degraded:
                print(f"    - {q}")

    print(f"\n{'=' * 80}")


def main() -> None:
    parser = argparse.ArgumentParser(description="BM25 vs BM25+Embedding benchmark")
    parser.add_argument(
        "--embedding",
        type=str,
        default="vllm/qwen3-0.6b@http://localhost:8100/v1",
        help="Embedding spec (e.g. 'vllm/model@url', 'ollama/model')",
    )
    parser.add_argument("-d", "--dataset", nargs="+", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    datasets = args.dataset or [k for k, v in DATASET_REGISTRY.items() if not v.get("legacy")]

    run_comparison(datasets, args.embedding, top_k=args.top_k, verbose=args.verbose)


if __name__ == "__main__":
    main()
