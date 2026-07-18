"""Run BFCL-compatible model benchmark sweeps.

This module repeatedly calls ``benchmarks.bfcl_tool_selection.llm_loop`` across
tool sources and top-K values, then writes one JSON artifact containing every
run summary. It is intended for publish-candidate benchmark collection where a
single smoke number is too thin.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks.bfcl_tool_selection.llm_loop import (
    BFCL_RESULT_ARGUMENT_FORMATS,
    DEFAULT_MODEL,
    DEFAULT_OFFICIAL_MODEL_NAME,
    run_model_benchmark,
    write_bfcl_result_files,
)
from benchmarks.bfcl_tool_selection.run import BFCL_REF, DEFAULT_CATEGORIES, _parse_categories
from benchmarks.xgen_tool_graph.llm_loop import DEFAULT_OLLAMA_URL


def run_sweep(
    *,
    model: str = DEFAULT_MODEL,
    llm_url: str = DEFAULT_OLLAMA_URL,
    categories: list[str] | None = None,
    data_root: Path | None = None,
    ref: str = BFCL_REF,
    top_ks: list[int] | None = None,
    limit: int | None = None,
    tool_sources: list[str] | None = None,
    evaluator: str = "local",
    official_model_name: str = DEFAULT_OFFICIAL_MODEL_NAME,
    cache_dir: Path | None = None,
    refresh_cache: bool = False,
    repeats: int = 1,
    timeout: int = 180,
    disable_thinking: bool = False,
    concurrency: int = 1,
    progress: bool = False,
    progress_every: int = 25,
) -> dict[str, Any]:
    selected_categories = categories or list(DEFAULT_CATEGORIES)
    selected_top_ks = top_ks or [3, 5, 10]
    selected_tool_sources = tool_sources or ["row", "retrieved"]
    runs: list[dict[str, Any]] = []

    for repeat_index in range(max(1, repeats)):
        cache_namespace = f"repeat-{repeat_index + 1}" if max(1, repeats) > 1 else ""
        for tool_source in selected_tool_sources:
            for top_k in selected_top_ks:
                report = run_model_benchmark(
                    model=model,
                    llm_url=llm_url,
                    categories=selected_categories,
                    data_root=data_root,
                    ref=ref,
                    top_k=top_k,
                    limit=limit,
                    tool_source=tool_source,
                    evaluator=evaluator,
                    official_model_name=official_model_name,
                    cache_dir=cache_dir,
                    cache_namespace=cache_namespace,
                    refresh_cache=refresh_cache,
                    timeout=timeout,
                    disable_thinking=disable_thinking,
                    concurrency=concurrency,
                    progress=progress,
                    progress_every=progress_every,
                )
                runs.append(
                    {
                        "repeat": repeat_index + 1,
                        "tool_source": tool_source,
                        "top_k": top_k,
                        "report": report,
                    }
                )

    return {
        "benchmark": "BFCL v4 Model Tool Call Sweep",
        "methodology": "bfcl_compatible_model_tool_call_sweep",
        "model": model,
        "llm_url": runs[0]["report"]["llm_url"] if runs else llm_url,
        "categories": selected_categories,
        "tool_sources": selected_tool_sources,
        "top_ks": selected_top_ks,
        "limit": limit,
        "repeats": max(1, repeats),
        "concurrency": max(1, concurrency),
        "progress": progress,
        "evaluator": evaluator,
        "official_model_name": official_model_name if evaluator == "official" else "",
        "cache_dir": str(cache_dir) if cache_dir else "",
        "bfcl_ref": ref,
        "runs": runs,
        "summary": _summarize_sweep(runs),
    }


def _summarize_sweep(runs: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failure_totals: Counter[str] = Counter()
    for run in runs:
        report = run["report"]
        summary = report["summary"]
        failure_totals.update(summary.get("failure_breakdown") or {})
        rows.append(
            {
                "repeat": run["repeat"],
                "tool_source": run["tool_source"],
                "top_k": run["top_k"],
                "cases": summary["cases"],
                "retrieval_recall_at_k": summary["retrieval_recall_at_k"],
                "model_tool_call_rate": summary["model_tool_call_rate"],
                "strict_exact_match": summary["strict_exact_match"],
                "evaluator_exact_match": summary["evaluator_exact_match"],
                "avg_latency_ms": summary["avg_latency_ms"],
                "failure_breakdown": summary.get("failure_breakdown") or {},
            }
        )
    return {
        "run_count": len(runs),
        "rows": rows,
        "repeat_groups": _summarize_repeat_groups(rows),
        "failure_breakdown": dict(sorted(failure_totals.items())),
        "best_retrieved": _best_retrieved(rows),
    }


def _best_retrieved(rows: list[dict[str, Any]]) -> dict[str, Any]:
    retrieved_rows = [row for row in rows if row["tool_source"] == "retrieved"]
    if not retrieved_rows:
        return {}
    return max(
        retrieved_rows,
        key=lambda row: (
            row["evaluator_exact_match"],
            row["retrieval_recall_at_k"],
            -row["avg_latency_ms"],
        ),
    )


def _summarize_repeat_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["tool_source"]), int(row["top_k"]))
        grouped.setdefault(key, []).append(row)

    summaries: list[dict[str, Any]] = []
    for (tool_source, top_k), group_rows in sorted(grouped.items()):
        summaries.append(
            {
                "tool_source": tool_source,
                "top_k": top_k,
                "repeat_count": len(group_rows),
                "cases_per_repeat": [int(row["cases"]) for row in group_rows],
                "retrieval_recall_at_k": _metric_stats(
                    row["retrieval_recall_at_k"] for row in group_rows
                ),
                "evaluator_exact_match": _metric_stats(
                    row["evaluator_exact_match"] for row in group_rows
                ),
                "strict_exact_match": _metric_stats(
                    row["strict_exact_match"] for row in group_rows
                ),
                "avg_latency_ms": _metric_stats(row["avg_latency_ms"] for row in group_rows),
            }
        )
    return summaries


def _metric_stats(values: Any) -> dict[str, float]:
    vals = [float(value) for value in values]
    if not vals:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": round(statistics.mean(vals), 6),
        "std": round(statistics.pstdev(vals), 6),
        "min": round(min(vals), 6),
        "max": round(max(vals), 6),
    }


def write_sweep_bfcl_result_files(
    report: dict[str, Any],
    output_dir: Path,
    *,
    official_model_name: str | None = None,
    argument_format: str = "json-string",
) -> list[Path]:
    """Write one BFCL-compatible result directory per sweep run."""
    selected_model_name = official_model_name or str(
        report.get("official_model_name") or DEFAULT_OFFICIAL_MODEL_NAME
    )
    written: list[Path] = []
    for run in report.get("runs") or []:
        run_dir = (
            output_dir
            / f"repeat-{int(run.get('repeat') or 1)}"
            / f"{run.get('tool_source')}-k{int(run.get('top_k') or 0)}"
        )
        written.extend(
            write_bfcl_result_files(
                run["report"],
                run_dir,
                official_model_name=selected_model_name,
                argument_format=argument_format,
            )
        )
    return written


def print_report(report: dict[str, Any]) -> None:
    print(report["benchmark"])
    print(
        f"model={report['model']} evaluator={report['evaluator']} "
        f"categories={','.join(report['categories'])} repeats={report['repeats']}"
    )
    for row in report["summary"]["rows"]:
        failures = _format_failure_breakdown(row.get("failure_breakdown") or {})
        print(
            "{source:9s} k={top_k:<2} repeat={repeat:<2} cases={cases:<4} "
            "retrieval@K={retrieval:.2f} exact={exact:.2f} strict={strict:.2f} "
            "latency={latency:.1f}ms failures={failures}".format(
                source=row["tool_source"],
                top_k=row["top_k"],
                repeat=row["repeat"],
                cases=row["cases"],
                retrieval=row["retrieval_recall_at_k"],
                exact=row["evaluator_exact_match"],
                strict=row["strict_exact_match"],
                latency=row["avg_latency_ms"],
                failures=failures,
            )
        )
    best = report["summary"].get("best_retrieved") or {}
    if best:
        print(
            "best_retrieved: k={top_k} exact={exact:.2f} retrieval@K={retrieval:.2f}".format(
                top_k=best["top_k"],
                exact=best["evaluator_exact_match"],
                retrieval=best["retrieval_recall_at_k"],
            )
        )
    for group in report["summary"].get("repeat_groups") or []:
        if group["repeat_count"] <= 1:
            continue
        exact = group["evaluator_exact_match"]
        retrieval = group["retrieval_recall_at_k"]
        latency = group["avg_latency_ms"]
        print(
            "repeat_summary {source:9s} k={top_k:<2} repeats={repeats:<2} "
            "exact_mean={exact_mean:.2f} exact_std={exact_std:.3f} "
            "retrieval_mean={retrieval_mean:.2f} latency_mean={latency_mean:.1f}ms".format(
                source=group["tool_source"],
                top_k=group["top_k"],
                repeats=group["repeat_count"],
                exact_mean=exact["mean"],
                exact_std=exact["std"],
                retrieval_mean=retrieval["mean"],
                latency_mean=latency["mean"],
            )
        )


def _format_failure_breakdown(breakdown: dict[str, int]) -> str:
    if not breakdown:
        return "-"
    return ",".join(f"{name}:{count}" for name, count in sorted(breakdown.items()))


def _parse_ints(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _parse_strings(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--llm-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES))
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--ref", default=BFCL_REF)
    parser.add_argument("--top-ks", default="3,5,10")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--tool-sources", default="row,retrieved")
    parser.add_argument("--evaluator", choices=["local", "official"], default="local")
    parser.add_argument("--official-model-name", default=DEFAULT_OFFICIAL_MODEL_NAME)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of BFCL cases to evaluate concurrently within each category.",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Print per-category progress to stderr while cases are running.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Progress print interval in completed cases.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--bfcl-result-dir",
        type=Path,
        default=None,
        help="Optional root directory for per-run BFCL-compatible result JSONL files.",
    )
    parser.add_argument(
        "--bfcl-result-argument-format",
        choices=BFCL_RESULT_ARGUMENT_FORMATS,
        default="json-string",
        help="Use json-string for BFCL OpenAI/Qwen FC handlers, decoded for direct AST input.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_sweep(
            model=args.model,
            llm_url=args.llm_url,
            categories=_parse_categories(args.categories),
            data_root=args.data_root,
            ref=args.ref,
            top_ks=_parse_ints(args.top_ks),
            limit=args.limit,
            tool_sources=_parse_strings(args.tool_sources),
            evaluator=args.evaluator,
            official_model_name=args.official_model_name,
            cache_dir=args.cache_dir,
            refresh_cache=args.refresh_cache,
            repeats=args.repeats,
            timeout=args.timeout,
            disable_thinking=args.disable_thinking,
            concurrency=args.concurrency,
            progress=args.progress,
            progress_every=args.progress_every,
        )
    except ImportError as exc:
        parser.error(str(exc))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.bfcl_result_dir:
        write_sweep_bfcl_result_files(
            report,
            args.bfcl_result_dir,
            official_model_name=args.official_model_name,
            argument_format=args.bfcl_result_argument_format,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
