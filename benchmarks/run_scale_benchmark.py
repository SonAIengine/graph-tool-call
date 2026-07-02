#!/usr/bin/env python3
"""Scale benchmark for retrieval at thousands of tools (A-P1-5).

Builds a large synthetic corpus by *namespace-replicating* the bundled real
specs (github + k8s + ecommerce) across many services — e.g. ``svc7_listPods``
— so category structure and token distribution stay realistic while the tool
count reaches 3k / 5k. Ground-truth queries name the service + operation, so
the right variant is findable.

Reports, per corpus size, **prefilter off vs on**:
  - recall@5 (the recall-preservation gate: on >= off)
  - latency p50 / p95 (ms)
  - avg search_tools response size (chars ≈ tokens*4) — dynamic-k shrinks this

No network, no LLM. Runnable as::

    python -m benchmarks.run_scale_benchmark
    python -m benchmarks.run_scale_benchmark --sizes 3000 5000 --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import warnings
from dataclasses import dataclass

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.retrieval.engine import elbow_cut_k

_SPECS = [
    "benchmarks/specs/github_subset.json",
    "benchmarks/specs/k8s_core_v1.json",
    "benchmarks/specs/ecommerce.json",
]


@dataclass
class QCase:
    query: str
    expected: str


def _base_tools() -> list[ToolSchema]:
    """Ingest the bundled specs once to harvest realistic base tools."""
    base = ToolGraph()
    for spec in _SPECS:
        try:
            base.ingest_openapi(spec)
        except Exception as exc:  # noqa: BLE001
            print(f"  warn: skip {spec}: {exc}")
    return list(base.tools.values())


def build_corpus(target_n: int) -> tuple[ToolGraph, list[QCase]]:
    """Namespace-replicate base tools up to ~target_n, with ground-truth queries."""
    base = _base_tools()
    if not base:
        raise RuntimeError("no base tools ingested — check benchmarks/specs/*")
    n_services = max(1, target_n // len(base))

    tg = ToolGraph()
    queries: list[QCase] = []
    for svc in range(n_services):
        svc_name = f"svc{svc}"
        for bt in base:
            name = f"{svc_name}_{bt.name}"
            domain = bt.domain or "general"
            tool = ToolSchema(
                name=name,
                description=f"{bt.description} (service {svc_name})",
                parameters=[ToolParameter(name=p.name, type=p.type) for p in bt.parameters],
                tags=list(bt.tags) + [svc_name],
                domain=domain,
            )
            tg.add_tool(tool)
            # Attach to a CATEGORY node (as OpenAPI ingest would) so the
            # category prefilter has structure to match.
            tg._builder.assign_category(name, domain)

    # Ground truth: sample a spread of (service, base tool) pairs. Query names
    # the service + a natural-language-ish description of the operation.
    step = max(1, (n_services * len(base)) // 60)
    flat = [(svc, bt) for svc in range(n_services) for bt in base]
    for svc, bt in flat[::step][:60]:
        queries.append(
            QCase(
                query=f"{bt.description} in service svc{svc}",
                expected=f"svc{svc}_{bt.name}",
            )
        )
    return tg, queries


def measure(tg: ToolGraph, queries: list[QCase], *, prefilter: bool, adaptive_k: bool) -> dict:
    if prefilter or adaptive_k:
        # tune_for_scale enables prefilter + diversity + dynamic-k together;
        # for an isolated read we toggle the engine flags directly.
        eng = tg._get_retrieval_engine()
        eng.enable_prefilter(prefilter)
        tg._adaptive_k_default = adaptive_k

    hits = 0
    lat: list[float] = []
    resp_sizes: list[int] = []
    for qc in queries:
        t0 = time.perf_counter()
        results = tg.retrieve_with_scores(qc.query, top_k=5)
        lat.append((time.perf_counter() - t0) * 1000)
        names = [r.tool.name for r in results]
        # dynamic-k trim (mirrors search_tools first page)
        if adaptive_k:
            k = elbow_cut_k([r.score for r in results], 5)
            names = names[:k]
            results = results[:k]
        hits += 1.0 if qc.expected in names else 0.0
        resp_sizes.append(
            len(json.dumps([r.to_dict(include_params=True) for r in results], ensure_ascii=False))
        )

    lat.sort()
    return {
        "recall@5": round(hits / len(queries), 4),
        "p50_ms": round(statistics.median(lat), 1),
        "p95_ms": round(lat[int(len(lat) * 0.95)], 1),
        "avg_resp_chars": int(statistics.mean(resp_sizes)),
    }


def run_size(target_n: int) -> dict:
    tg, queries = build_corpus(target_n)
    n = len(tg.tools)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        off = measure(tg, queries, prefilter=False, adaptive_k=False)
        on = measure(tg, queries, prefilter=True, adaptive_k=False)
        tuned = measure(tg, queries, prefilter=True, adaptive_k=True)
    return {
        "target_n": target_n,
        "actual_n": n,
        "n_queries": len(queries),
        "prefilter_off": off,
        "prefilter_on": on,
        "tuned_for_scale": tuned,
        "recall_delta_on_minus_off": round(on["recall@5"] - off["recall@5"], 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", type=int, nargs="+", default=[3000, 5000])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    reports = [run_size(n) for n in args.sizes]

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return

    for r in reports:
        print(f"\n=== Scale Benchmark: {r['actual_n']} tools ({r['n_queries']} queries) ===")
        hdr = f"{'variant':<18}{'recall@5':<11}{'p50 ms':<9}{'p95 ms':<9}{'resp chars':<11}"
        print(hdr)
        print("-" * len(hdr))
        for label, key in [
            ("prefilter OFF", "prefilter_off"),
            ("prefilter ON", "prefilter_on"),
            ("tune_for_scale", "tuned_for_scale"),
        ]:
            m = r[key]
            print(
                f"{label:<18}{m['recall@5']:<11}{m['p50_ms']:<9}{m['p95_ms']:<9}{m['avg_resp_chars']:<11}"
            )
        print(
            f"recall delta (on - off) = {r['recall_delta_on_minus_off']:+.4f}  "
            f"(gate: >= 0 → prefilter preserves recall)"
        )


if __name__ == "__main__":
    main()
