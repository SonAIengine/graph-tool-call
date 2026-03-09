#!/usr/bin/env python3
"""Public benchmark for graph-tool-call retrieval engine.

Modes:
  retrieval  — Measure recall@K without LLM (fast, deterministic)
  e2e        — Full pipeline: Baseline vs Retrieve comparison with Ollama
  pipeline   — Multi-pipeline comparison matrix with baseline diff support

Usage:
    python -m benchmarks.run_benchmark                           # retrieval-only, all datasets
    python -m benchmarks.run_benchmark --dataset petstore        # single dataset
    python -m benchmarks.run_benchmark --mode e2e --model qwen3:4b  # with LLM
    python -m benchmarks.run_benchmark --mode legacy --dataset petstore_legacy  # old-style
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from benchmarks.config import DATASET_REGISTRY, BenchmarkConfig
from benchmarks.metrics import recall_at_k
from benchmarks.reporter import (
    BenchmarkReport,
    DatasetResult,
    QueryResult,
    compute_dataset_metrics,
    print_llm_report,
    print_retrieval_report,
    save_report,
)
from graph_tool_call import ToolGraph


def _load_ground_truth(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _build_tool_graph(sources: list[dict]) -> ToolGraph:
    """Build a ToolGraph from source configs."""
    tg = ToolGraph()
    for src in sources:
        src_type = src["type"]
        src_path = src["path"]

        if src_type == "openapi":
            tg.ingest_openapi(src_path)
        elif src_type == "mcp":
            with open(src_path) as f:
                mcp_data = json.load(f)
            tg.ingest_mcp_tools(mcp_data["tools"])
        else:
            print(f"  Warning: unknown source type '{src_type}', skipping")

    return tg


def run_retrieval_benchmark(
    config: BenchmarkConfig,
) -> BenchmarkReport:
    """Run retrieval-only benchmark — measure recall@K without LLM.

    Parameters
    ----------
    config:
        Benchmark configuration.

    Returns
    -------
    BenchmarkReport
        Results with recall@K per dataset.
    """
    report = BenchmarkReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        mode="retrieval_only",
        top_k=config.top_k,
    )

    for ds_name in config.datasets:
        reg = DATASET_REGISTRY.get(ds_name)
        if not reg or reg.get("legacy"):
            print(f"  Skipping '{ds_name}' (legacy or unknown)")
            continue

        gt = _load_ground_truth(reg["ground_truth"])
        tg = _build_tool_graph(reg["sources"])

        ds_result = DatasetResult(name=gt["name"], tool_count=gt.get("tool_count", len(tg._tools)))

        for q in gt["queries"]:
            results = tg.retrieve(q["query"], top_k=config.top_k)
            retrieved_names = [r.name for r in results]
            expected = set(q["expected_tools"])

            recall = recall_at_k(retrieved_names, expected, config.top_k)

            qr = QueryResult(
                query=q["query"],
                category=q.get("category", ""),
                difficulty=q.get("difficulty", ""),
                expected_tools=q["expected_tools"],
                recall_at_k=recall,
                retrieved_tools=retrieved_names,
            )
            ds_result.queries.append(qr)

            if config.verbose:
                mark = "✓" if recall == 1.0 else "✗"
                print(f"    {mark} [{recall:.0%}] {q['query']}")
                if recall < 1.0:
                    print(f"        expected: {q['expected_tools']}")
                    print(f"        got:      {retrieved_names}")

        compute_dataset_metrics(ds_result)
        report.datasets.append(ds_result)

    return report


def run_e2e_benchmark(config: BenchmarkConfig) -> BenchmarkReport:
    """Run end-to-end benchmark — Baseline vs Retrieve with LLM.

    Parameters
    ----------
    config:
        Benchmark configuration with model set.

    Returns
    -------
    BenchmarkReport
        Results comparing baseline and retrieve modes.
    """
    from benchmarks.llm_runner import (
        LLMResult,
        call_ollama,
        call_openai_compatible,
        extract_tool_name,
        tools_to_openai_format,
    )

    # Detect API format: OpenAI-compatible if URL contains /v1, else Ollama
    is_openai = "/v1" in config.ollama_url

    def _call_llm(query: str, tools: list[dict]) -> LLMResult:
        if is_openai:
            return call_openai_compatible(
                model=config.model,
                query=query,
                tools=tools,
                base_url=config.ollama_url,
                timeout=config.timeout,
            )
        return call_ollama(
            model=config.model,
            query=query,
            tools=tools,
            ollama_url=config.ollama_url,
            num_ctx=config.num_ctx,
            timeout=config.timeout,
        )

    report = BenchmarkReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        model=config.model,
        mode="e2e",
        top_k=config.top_k,
    )

    for ds_name in config.datasets:
        reg = DATASET_REGISTRY.get(ds_name)
        if not reg or reg.get("legacy"):
            continue

        gt = _load_ground_truth(reg["ground_truth"])
        tg = _build_tool_graph(reg["sources"])
        all_tools = list(tg._tools.values())
        all_tools_openai = tools_to_openai_format(all_tools)

        ds_result = DatasetResult(name=gt["name"], tool_count=len(all_tools))

        for i, q in enumerate(gt["queries"]):
            expected = set(q["expected_tools"])
            query = q["query"]

            print(f"    [{i + 1}/{len(gt['queries'])}] {query}")

            qr = QueryResult(
                query=query,
                category=q.get("category", ""),
                difficulty=q.get("difficulty", ""),
                expected_tools=q["expected_tools"],
            )

            # --- Retrieval ---
            retrieved = tg.retrieve(query, top_k=config.top_k)
            retrieved_names = [r.name for r in retrieved]
            qr.recall_at_k = recall_at_k(retrieved_names, expected, config.top_k)
            qr.retrieved_tools = retrieved_names

            # --- Baseline: all tools → LLM ---
            bl = _call_llm(query, all_tools_openai)
            bl_tool = extract_tool_name(bl)
            qr.baseline_tool = bl_tool
            qr.baseline_correct = bl_tool in expected if bl_tool else False
            qr.baseline_latency_ms = bl.latency * 1000
            qr.baseline_input_tokens = bl.input_tokens

            # --- Retrieve: filtered tools → LLM ---
            filtered_tools_openai = tools_to_openai_format(retrieved)
            rt = _call_llm(query, filtered_tools_openai)
            rt_tool = extract_tool_name(rt)
            qr.retrieve_tool = rt_tool
            qr.retrieve_correct = rt_tool in expected if rt_tool else False
            qr.retrieve_latency_ms = rt.latency * 1000
            qr.retrieve_input_tokens = rt.input_tokens

            bl_mark = "✓" if qr.baseline_correct else "✗"
            rt_mark = "✓" if qr.retrieve_correct else "✗"
            print(f"      baseline={bl_mark}({bl_tool})  retrieve={rt_mark}({rt_tool})")

            ds_result.queries.append(qr)

        compute_dataset_metrics(ds_result)
        report.datasets.append(ds_result)

    return report


def run_legacy_benchmark(args: argparse.Namespace) -> None:
    """Run the original tier-based benchmark (backward compat)."""
    import time

    from benchmarks.datasets import petstore_dataset, synthetic_dataset
    from benchmarks.metrics import ndcg_at_k, precision_at_k, workflow_coverage
    from graph_tool_call.retrieval.engine import SearchMode

    if args.dataset == "petstore_legacy":
        tools, queries = petstore_dataset()
        label = "petstore"
    else:
        tools, queries = synthetic_dataset(n=args.n_tools)
        label = f"synthetic({args.n_tools})"

    tg = ToolGraph()
    for tool in tools:
        tg._tools[tool.name] = tool
        tg._builder.add_tool(tool)

    print(f"Dataset: {label}")
    print(f"Tools: {len(tools)}, Queries: {len(queries)}, top_k: {args.top_k}")
    print("=" * 70)

    for mode in [SearchMode.BASIC, SearchMode.ENHANCED, SearchMode.FULL]:
        precisions, recalls, ndcgs, coverages, latencies = [], [], [], [], []
        for case in queries:
            start = time.perf_counter()
            results = tg.retrieve(case.query, top_k=args.top_k, mode=mode)
            elapsed = time.perf_counter() - start
            names = [r.name for r in results]
            latencies.append(elapsed * 1000)
            precisions.append(precision_at_k(names, case.relevant_tools, args.top_k))
            recalls.append(recall_at_k(names, case.relevant_tools, args.top_k))
            ndcgs.append(ndcg_at_k(names, case.relevant_tools, args.top_k))
            if case.workflow:
                coverages.append(workflow_coverage(names, case.workflow))
        n = len(queries)
        print(f"\n{mode.value.upper()}")
        print(f"  Precision@{args.top_k}: {sum(precisions) / n:.3f}")
        print(f"  Recall@{args.top_k}:    {sum(recalls) / n:.3f}")
        print(f"  NDCG@{args.top_k}:      {sum(ndcgs) / n:.3f}")
        if coverages:
            print(f"  Workflow Coverage: {sum(coverages) / len(coverages):.3f}")
        print(f"  Avg Latency:       {sum(latencies) / n:.1f}ms")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="graph-tool-call public benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m benchmarks.run_benchmark                           # retrieval, all datasets
  python -m benchmarks.run_benchmark -d petstore               # single dataset
  python -m benchmarks.run_benchmark --mode e2e -m qwen3:4b    # with LLM
  python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b  # pipeline comparison
  python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5
  python -m benchmarks.run_benchmark --mode pipeline --save-baseline  # save as baseline
  python -m benchmarks.run_benchmark --mode pipeline --diff          # compare vs baseline
  python -m benchmarks.run_benchmark --mode legacy             # old-style tier benchmark
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["retrieval", "e2e", "pipeline", "legacy"],
        default="retrieval",
        help="Benchmark mode (default: retrieval)",
    )
    parser.add_argument(
        "-d",
        "--dataset",
        nargs="+",
        default=None,
        help="Datasets to benchmark (default: all non-legacy)",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Top-K for retrieval")
    parser.add_argument("-m", "--model", type=str, default="qwen3:4b", help="Ollama model for e2e")
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434/api/chat",
        help="LLM API URL (Ollama or OpenAI-compatible /v1)",
    )
    parser.add_argument("--num-ctx", type=int, default=8192, help="Context window size")
    parser.add_argument("--timeout", type=int, default=120, help="LLM timeout in seconds")
    parser.add_argument("--n-tools", type=int, default=500, help="Tool count for synthetic")
    parser.add_argument("--save", action="store_true", help="Save results as JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show per-query details")

    # Pipeline mode arguments
    parser.add_argument(
        "--pipelines",
        nargs="+",
        default=None,
        help="Pipeline presets for pipeline mode (default: baseline retrieve-k5)",
    )
    parser.add_argument(
        "--embedding",
        type=str,
        default=None,
        help="Embedding model for pipeline mode (e.g. 'ollama/nomic-embed-text')",
    )
    parser.add_argument(
        "--save-baseline", action="store_true", help="Save pipeline results as baseline"
    )
    parser.add_argument(
        "--diff", action="store_true", help="Compare pipeline results against saved baseline"
    )
    parser.add_argument(
        "--failures", action="store_true", help="Show divergent/failed queries in pipeline mode"
    )
    parser.add_argument(
        "--organize",
        type=str,
        default=None,
        help="Organize mode for retrieval pipelines: 'auto', 'llm', or 'ollama/model'",
    )

    args = parser.parse_args()

    # Legacy mode
    if args.mode == "legacy":
        if not args.dataset:
            args.dataset = ["petstore_legacy"]
        args.top_k = args.top_k
        run_legacy_benchmark(args)
        return

    # Pipeline mode
    if args.mode == "pipeline":
        from benchmarks.baseline import diff_reports, load_baseline, print_diff, save_baseline
        from benchmarks.config import DEFAULT_PIPELINES, PIPELINE_PRESETS, PipelineConfig
        from benchmarks.pipeline import PipelineExecutor
        from benchmarks.reporter import print_pipeline_failures, print_pipeline_matrix

        # Determine pipelines
        pipeline_names = args.pipelines or DEFAULT_PIPELINES
        pipelines = []
        for name in pipeline_names:
            if name in PIPELINE_PRESETS:
                p = PIPELINE_PRESETS[name]
                # Apply overrides if specified
                if (args.embedding or args.organize) and p.use_retrieval:
                    p = PipelineConfig(
                        name=p.name,
                        use_retrieval=p.use_retrieval,
                        top_k=p.top_k,
                        embedding=args.embedding or p.embedding,
                        reranker=p.reranker,
                        weights=p.weights,
                        organize=args.organize or p.organize,
                    )
                pipelines.append(p)
            else:
                print(f"Unknown pipeline preset: {name}", file=sys.stderr)
                sys.exit(1)

        # Determine datasets
        datasets = args.dataset or None  # None = all non-legacy

        executor = PipelineExecutor(
            pipelines=pipelines,
            model=args.model,
            ollama_url=args.ollama_url,
            num_ctx=args.num_ctx,
            timeout=args.timeout,
        )
        report = executor.run_all(datasets=datasets, verbose=args.verbose)
        print_pipeline_matrix(report)

        if args.failures:
            print_pipeline_failures(report)

        if args.save_baseline:
            path = save_baseline(report)
            print(f"\n  Baseline saved: {path}")

        if args.diff:
            baseline = load_baseline()
            if baseline is None:
                print("\n  No baseline found. Run with --save-baseline first.")
            else:
                diffs = diff_reports(report, baseline)
                print_diff(diffs)

        if args.save:
            from pathlib import Path

            out = Path("benchmarks/results")
            out.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = out / f"pipeline_{ts}.json"
            path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            print(f"\n  Report saved: {path}")

        return

    # Determine datasets
    if args.dataset:
        datasets = args.dataset
    else:
        datasets = [k for k, v in DATASET_REGISTRY.items() if not v.get("legacy")]

    config = BenchmarkConfig(
        datasets=datasets,
        top_k=args.top_k,
        model=args.model if args.mode == "e2e" else None,
        ollama_url=args.ollama_url,
        num_ctx=args.num_ctx,
        timeout=args.timeout,
        save_json=args.save,
        verbose=args.verbose,
    )

    if args.mode == "retrieval":
        report = run_retrieval_benchmark(config)
        print_retrieval_report(report)
    elif args.mode == "e2e":
        report = run_e2e_benchmark(config)
        print_llm_report(report)
    else:
        print(f"Unknown mode: {args.mode}", file=sys.stderr)
        sys.exit(1)

    if config.save_json:
        save_report(report, config.output_dir)


if __name__ == "__main__":
    main()
