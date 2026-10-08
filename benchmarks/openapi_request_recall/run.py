"""Natural-request recall benchmark for persisted OpenAPI collection graphs.

Measures whether a user request retrieves an acceptable endpoint in the
top-k results. It uses the same public path a product adapter uses:
``build_openapi_collection_artifact`` -> ``ToolGraph.load`` ->
``retrieve_with_scores``. Only the public API is imported, so the script can
be run against an installed release for a baseline::

    uv run --no-project --with graph-tool-call==0.46.0 \
        python benchmarks/openapi_request_recall/run.py \
        --cases cases.json --spec gitea=gitea.json --output out.json

Case format (JSON list or ``{"cases": [...]}``)::

    {"id": "...", "system": "gitea", "language": "en", "query": "...",
     "primary": {"method": "get", "path": "/user/repos"} | null,
     "alternatives": [{"method": "get", "path": "..."}]}

Cases with ``primary: null`` are unsupported requests and are excluded from
recall metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import graph_tool_call
from graph_tool_call import ToolGraph
from graph_tool_call.graphify.collection_artifact import build_openapi_collection_artifact


def _load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    for case in cases:
        if "primary" not in case and "expected_path" in case:
            case["primary"] = {"method": case["expected_method"], "path": case["expected_path"]}
            case.setdefault("alternatives", [])
    return cases


def _accepted(case: dict[str, Any]) -> set[tuple[str, str]]:
    labels = [case["primary"], *case.get("alternatives", [])]
    return {(label["method"].lower(), label["path"]) for label in labels}


def _build_graph(spec_paths: list[Path]) -> tuple[ToolGraph, float]:
    specs = [json.loads(path.read_text(encoding="utf-8")) for path in spec_paths]
    started = time.perf_counter()
    artifact = build_openapi_collection_artifact(specs if len(specs) > 1 else specs[0])
    with tempfile.TemporaryDirectory(prefix="gtc-recall-") as directory:
        path = Path(directory) / "graph.json"
        path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
        graph = ToolGraph.load(path)
    return graph, time.perf_counter() - started


def _endpoint(tool: Any) -> tuple[str, str]:
    metadata = tool.metadata or {}
    return (str(metadata.get("method", "")).lower(), str(metadata.get("path", "")))


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row["supported"]]
    if not scored:
        return {"n": 0}
    return {
        "n": len(scored),
        "hit1": sum(row["rank"] == 1 for row in scored),
        "hit5": sum(row["rank"] is not None for row in scored),
        "mrr5": round(sum(1 / row["rank"] for row in scored if row["rank"]) / len(scored), 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument(
        "--spec",
        action="append",
        required=True,
        help="system=path[,path...]; repeat per system",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    spec_map: dict[str, list[Path]] = {}
    for item in args.spec:
        system, _, paths = item.partition("=")
        spec_map[system] = [Path(path) for path in paths.split(",")]

    cases = _load_cases(args.cases)
    rows: list[dict[str, Any]] = []
    build: dict[str, Any] = {}
    for system in sorted({case["system"] for case in cases}):
        graph, seconds = _build_graph(spec_map[system])
        endpoints = {_endpoint(tool) for tool in graph.tools.values()}
        build[system] = {"tools": len(graph.tools), "build_seconds": round(seconds, 2)}
        for case in (case for case in cases if case["system"] == system):
            supported = case.get("primary") is not None
            accepted = _accepted(case) if supported else set()
            started = time.perf_counter()
            hits = graph.retrieve_with_scores(case["query"], top_k=args.top_k)
            elapsed = time.perf_counter() - started
            candidates = [_endpoint(hit.tool) for hit in hits]
            rank = next(
                (index for index, endpoint in enumerate(candidates, 1) if endpoint in accepted),
                None,
            )
            rows.append(
                {
                    "id": case["id"],
                    "system": system,
                    "language": case.get("language"),
                    "supported": supported,
                    "indexed": bool(accepted & endpoints) if supported else None,
                    "rank": rank,
                    "candidates": [hit.tool.name for hit in hits],
                    "seconds": round(elapsed, 4),
                }
            )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[f"{row['system']}/{row['language']}"].append(row)
    latencies = [row["seconds"] for row in rows]
    result = {
        "graph_tool_call_version": graph_tool_call.__version__,
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "top_k": args.top_k,
        "build": build,
        "summary": {
            "all": _summarize(rows),
            "groups": {key: _summarize(value) for key, value in sorted(groups.items())},
            "latency_median_seconds": round(statistics.median(latencies), 4),
        },
        "rows": rows,
    }
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.quiet:
        print(
            json.dumps(
                {"version": result["graph_tool_call_version"], **result["summary"]},
                ensure_ascii=False,
                indent=1,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
