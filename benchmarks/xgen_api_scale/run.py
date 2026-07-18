"""XGEN-scale OpenAPI acceptance benchmark.

This runner is for real API collections such as X2BEE BO, where the product
problem is not a tiny fixture but a Swagger UI that expands into hundreds or
thousands of tools. It is opt-in because it can hit live URLs and build a large
graph. CI should cover the contract with small local specs instead.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from benchmarks.metrics import mrr, recall_at_k
from graph_tool_call import ToolGraph, __version__
from graph_tool_call.ingest.openapi import _load_spec, ingest_openapi
from graph_tool_call.tool_graph import _discover_spec_urls

DEFAULT_X2BEE_SWAGGER_URL = "https://api-bo.x2bee.com/api/bo/swagger-ui/index.html"
ROOT = Path(__file__).resolve().parent
DEFAULT_X2BEE_CASES_PATH = ROOT / "x2bee_cases.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


@dataclass
class LoadedSpec:
    source: str
    label: str
    spec: dict[str, Any]


@dataclass
class SpecProfile:
    label: str
    source: str
    title: str
    version: str
    openapi_version: str
    path_count: int
    operation_count: int
    operation_id_count: int
    missing_operation_id_count: int
    deprecated_operation_count: int
    request_body_count: int
    request_body_schema_count: int
    response_schema_count: int
    parameter_count: int
    methods: dict[str, int] = field(default_factory=dict)
    tags: dict[str, int] = field(default_factory=dict)


@dataclass
class SearchEvaluation:
    case_id: str
    query: str
    expected_tools: list[str]
    expected_any: list[str]
    retrieved: list[str]
    expected_ranks: dict[str, int | None]
    hit_at_k: float
    expected_tool_recall_at_k: float
    mrr: float
    latency_ms: float
    results: list[dict[str, Any]]
    issues: list[str]


def run_benchmark(
    *,
    swagger_url: str = DEFAULT_X2BEE_SWAGGER_URL,
    spec_sources: list[str | dict[str, Any]] | None = None,
    cases_path: Path | None = DEFAULT_X2BEE_CASES_PATH,
    top_k: int | None = None,
    detect_dependencies: bool = True,
    min_confidence: float = 0.7,
    min_spec_count: int = 1,
    min_unique_tools: int = 1000,
    max_build_seconds: float = 30.0,
    max_response_bytes: int = 5_000_000,
    allow_private_hosts: bool = False,
) -> dict[str, Any]:
    """Run the scale acceptance benchmark and return a JSON-serializable report."""
    started = time.perf_counter()
    loaded_specs = load_specs(
        swagger_url=swagger_url,
        spec_sources=spec_sources,
        max_response_bytes=max_response_bytes,
        allow_private_hosts=allow_private_hosts,
    )
    profiles = [profile_spec(loaded) for loaded in loaded_specs]
    tg, ingest_summary = build_scale_graph(
        loaded_specs,
        detect_dependencies=detect_dependencies,
        min_confidence=min_confidence,
    )
    build_seconds = round(time.perf_counter() - started, 3)

    cases_doc = load_cases(cases_path)
    selected_top_k = int(top_k or cases_doc.get("top_k") or 10)
    cases = [
        evaluate_search_case(case, tg=tg, top_k=selected_top_k)
        for case in cases_doc.get("cases", [])
    ]
    search_summary = summarize_search(cases, thresholds=cases_doc.get("thresholds") or {})
    scale_summary = summarize_scale(
        profiles,
        loaded_specs=loaded_specs,
        ingest_summary=ingest_summary,
        graph=tg,
        build_seconds=build_seconds,
        min_spec_count=min_spec_count,
        min_unique_tools=min_unique_tools,
        max_build_seconds=max_build_seconds,
    )
    status = "pass" if scale_summary["status"] == "pass" else "fail"
    if cases and search_summary.get("status") != "pass":
        status = "fail"

    return {
        "benchmark": cases_doc.get("name") or "XGEN API Scale Acceptance",
        "description": cases_doc.get("description") or "",
        "methodology": "xgen_large_openapi_acceptance",
        "model": "none",
        "graph_tool_call_version": __version__,
        "source_url": swagger_url,
        "top_k": selected_top_k,
        "detect_dependencies": detect_dependencies,
        "min_confidence": min_confidence,
        "status": status,
        "scale": scale_summary,
        "search": search_summary,
        "specs": [asdict(profile) for profile in profiles],
        "cases": [asdict(case) for case in cases],
    }


def load_specs(
    *,
    swagger_url: str,
    spec_sources: list[str | dict[str, Any]] | None,
    max_response_bytes: int,
    allow_private_hosts: bool,
) -> list[LoadedSpec]:
    """Load direct specs or discover specs from a Swagger UI URL."""
    sources: list[str | dict[str, Any]]
    if spec_sources:
        sources = list(spec_sources)
    else:
        sources = _discover_spec_urls(
            swagger_url,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )

    loaded: list[LoadedSpec] = []
    for index, source in enumerate(sources, start=1):
        spec = (
            source
            if isinstance(source, dict)
            else _load_spec(
                source,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )
        )
        loaded.append(
            LoadedSpec(
                source=f"inline:{index}" if isinstance(source, dict) else str(source),
                label=_spec_label(spec, source=source, index=index),
                spec=spec,
            )
        )
    return loaded


def profile_spec(loaded: LoadedSpec) -> SpecProfile:
    """Summarize one raw OpenAPI spec before graph-tool-call normalization."""
    operations = list(_iter_operations(loaded.spec))
    methods = Counter(method.upper() for method, _path, _operation in operations)
    tags: Counter[str] = Counter()
    operation_id_count = 0
    missing_operation_id_count = 0
    deprecated_operation_count = 0
    request_body_count = 0
    request_body_schema_count = 0
    response_schema_count = 0
    parameter_count = 0

    for _method, _path, operation in operations:
        if operation.get("operationId"):
            operation_id_count += 1
        else:
            missing_operation_id_count += 1
        if operation.get("deprecated"):
            deprecated_operation_count += 1
        for tag in operation.get("tags") or []:
            tags[str(tag)] += 1
        request_body = operation.get("requestBody") or {}
        if isinstance(request_body, dict) and request_body:
            request_body_count += 1
            if _content_has_schema(request_body.get("content") or {}):
                request_body_schema_count += 1
        if _response_has_schema(operation):
            response_schema_count += 1
        parameter_count += sum(1 for p in operation.get("parameters") or [] if isinstance(p, dict))

    info = loaded.spec.get("info") or {}
    return SpecProfile(
        label=loaded.label,
        source=loaded.source,
        title=str(info.get("title") or loaded.label),
        version=str(info.get("version") or ""),
        openapi_version=str(loaded.spec.get("openapi") or loaded.spec.get("swagger") or ""),
        path_count=len(loaded.spec.get("paths") or {}),
        operation_count=len(operations),
        operation_id_count=operation_id_count,
        missing_operation_id_count=missing_operation_id_count,
        deprecated_operation_count=deprecated_operation_count,
        request_body_count=request_body_count,
        request_body_schema_count=request_body_schema_count,
        response_schema_count=response_schema_count,
        parameter_count=parameter_count,
        methods=dict(sorted(methods.items())),
        tags=dict(tags.most_common(20)),
    )


def build_scale_graph(
    loaded_specs: list[LoadedSpec],
    *,
    detect_dependencies: bool,
    min_confidence: float,
) -> tuple[ToolGraph, dict[str, Any]]:
    """Ingest all specs, dedupe by tool name, and build one large ToolGraph."""
    unique_tools: dict[str, Any] = {}
    duplicate_tool_names: Counter[str] = Counter()
    ingested_tool_total = 0
    source_tool_counts: dict[str, int] = {}

    for loaded in loaded_specs:
        tools, _normalized = ingest_openapi(loaded.spec)
        ingested_tool_total += len(tools)
        source_tool_counts[loaded.label] = len(tools)
        for tool in tools:
            metadata = dict(tool.metadata or {})
            metadata["source_label"] = loaded.label
            metadata["source_url"] = loaded.source
            tool.metadata = metadata
            if tool.name in unique_tools:
                duplicate_tool_names[tool.name] += 1
                continue
            unique_tools[tool.name] = tool

    tg = ToolGraph()
    registered = tg.add_tools(
        list(unique_tools.values()),
        detect_dependencies=detect_dependencies,
        min_confidence=min_confidence,
    )
    return tg, {
        "ingested_tool_total": ingested_tool_total,
        "registered_tool_count": len(registered),
        "duplicate_tool_count": ingested_tool_total - len(unique_tools),
        "duplicate_tool_names": [
            {"name": name, "count": count + 1}
            for name, count in duplicate_tool_names.most_common(20)
        ],
        "source_tool_counts": source_tool_counts,
    }


def load_cases(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"name": "XGEN API Scale Acceptance", "top_k": 10, "cases": []}
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_search_case(
    case: dict[str, Any],
    *,
    tg: ToolGraph,
    top_k: int,
) -> SearchEvaluation:
    query = str(case["query"])
    expected_tools = [str(name) for name in case.get("expected_tools") or []]
    expected_any = [str(name) for name in case.get("expected_any") or []]
    expected_union = set(expected_tools) | set(expected_any)

    started = time.perf_counter()
    results = tg.retrieve_with_scores(query, top_k=top_k)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    retrieved = [result.tool.name for result in results]
    retrieved_set = set(retrieved)

    required_ok = set(expected_tools).issubset(retrieved_set) if expected_tools else True
    any_ok = bool(set(expected_any) & retrieved_set) if expected_any else True
    hit = 1.0 if required_ok and any_ok else 0.0
    recall_expected = (
        1.0
        if expected_any and not expected_tools and any_ok
        else recall_at_k(retrieved, expected_union, top_k)
    )
    expected_ranks = {name: _rank_of(retrieved, name) for name in sorted(expected_union)}
    issues = _case_issues(
        expected_tools=expected_tools,
        expected_any=expected_any,
        retrieved_set=retrieved_set,
    )

    return SearchEvaluation(
        case_id=str(case["id"]),
        query=query,
        expected_tools=expected_tools,
        expected_any=expected_any,
        retrieved=retrieved,
        expected_ranks=expected_ranks,
        hit_at_k=hit,
        expected_tool_recall_at_k=recall_expected,
        mrr=mrr(retrieved, expected_union),
        latency_ms=latency_ms,
        results=[_result_row(result) for result in results],
        issues=issues,
    )


def summarize_scale(
    profiles: list[SpecProfile],
    *,
    loaded_specs: list[LoadedSpec],
    ingest_summary: dict[str, Any],
    graph: ToolGraph,
    build_seconds: float,
    min_spec_count: int,
    min_unique_tools: int,
    max_build_seconds: float,
) -> dict[str, Any]:
    operation_ids = Counter(
        str(operation.get("operationId"))
        for loaded in loaded_specs
        for _method, _path, operation in _iter_operations(loaded.spec)
        if operation.get("operationId")
    )
    duplicate_tool_count = int(ingest_summary["duplicate_tool_count"])
    spec_count = len(profiles)
    operation_count = sum(profile.operation_count for profile in profiles)
    unique_tools = len(graph.tools)
    checks = {
        "min_spec_count": spec_count >= min_spec_count,
        "min_unique_tools": unique_tools >= min_unique_tools,
        "max_build_seconds": build_seconds <= max_build_seconds,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "spec_count": spec_count,
        "operation_count": operation_count,
        "path_count": sum(profile.path_count for profile in profiles),
        "operation_id_count": sum(profile.operation_id_count for profile in profiles),
        "missing_operation_id_count": sum(
            profile.missing_operation_id_count for profile in profiles
        ),
        "deprecated_operation_count": sum(
            profile.deprecated_operation_count for profile in profiles
        ),
        "request_body_count": sum(profile.request_body_count for profile in profiles),
        "request_body_schema_count": sum(profile.request_body_schema_count for profile in profiles),
        "response_schema_count": sum(profile.response_schema_count for profile in profiles),
        "parameter_count": sum(profile.parameter_count for profile in profiles),
        "ingested_tool_total": ingest_summary["ingested_tool_total"],
        "unique_tool_count": unique_tools,
        "duplicate_tool_count": duplicate_tool_count,
        "duplicate_operation_id_count": sum(count - 1 for count in operation_ids.values()),
        "edge_count": graph.graph.edge_count(),
        "build_seconds": build_seconds,
        "source_tool_counts": ingest_summary["source_tool_counts"],
        "duplicate_tool_names": ingest_summary["duplicate_tool_names"],
    }


def summarize_search(
    cases: list[SearchEvaluation],
    *,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    if not cases:
        return {"status": "skipped", "cases": 0}

    summary: dict[str, Any] = {
        "cases": len(cases),
        "case_hit_at_k": _mean(case.hit_at_k for case in cases),
        "expected_tool_recall_at_k": _mean(case.expected_tool_recall_at_k for case in cases),
        "mean_mrr": _mean(case.mrr for case in cases),
        "avg_latency_ms": round(_mean(case.latency_ms for case in cases), 3),
        "p50_latency_ms": _percentile([case.latency_ms for case in cases], 0.5),
        "max_latency_ms": max(case.latency_ms for case in cases),
        "issues": dict(Counter(issue for case in cases for issue in case.issues).most_common()),
    }
    if thresholds:
        checks = {
            metric: _threshold_passed(summary, metric, float(threshold))
            for metric, threshold in thresholds.items()
        }
        summary["checks"] = checks
        summary["status"] = "pass" if all(checks.values()) else "fail"
    else:
        summary["status"] = "pass"
    return summary


def _iter_operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            method_l = str(method).lower()
            if method_l in HTTP_METHODS and isinstance(operation, dict):
                operations.append((method_l, str(path), operation))
    return operations


def _content_has_schema(content: dict[str, Any]) -> bool:
    if not isinstance(content, dict):
        return False
    return any(isinstance(media, dict) and bool(media.get("schema")) for media in content.values())


def _response_has_schema(operation: dict[str, Any]) -> bool:
    responses = operation.get("responses") or {}
    if not isinstance(responses, dict):
        return False
    for response in responses.values():
        if isinstance(response, dict) and _content_has_schema(response.get("content") or {}):
            return True
    return False


def _case_issues(
    *,
    expected_tools: list[str],
    expected_any: list[str],
    retrieved_set: set[str],
) -> list[str]:
    issues: list[str] = []
    missing_required = [name for name in expected_tools if name not in retrieved_set]
    if missing_required:
        issues.append("missing_required_expected_tool")
    if expected_any and not (set(expected_any) & retrieved_set):
        issues.append("missing_any_expected_tool")
    return issues or ["pass"]


def _result_row(result: Any) -> dict[str, Any]:
    return {
        "name": result.tool.name,
        "description": result.tool.description,
        "score": round(float(result.score), 6),
        "score_breakdown": {
            "keyword": round(float(result.keyword_score), 6),
            "graph": round(float(result.graph_score), 6),
            "embedding": round(float(result.embedding_score), 6),
            "annotation": round(float(result.annotation_score), 6),
        },
    }


def _spec_label(spec: dict[str, Any], *, source: str | dict[str, Any], index: int) -> str:
    info = spec.get("info") or {}
    title = str(info.get("title") or "").strip()
    if not title and isinstance(source, str):
        title = unquote(source.rstrip("/").rsplit("/", 1)[-1])
    label = _slug(title) or f"spec-{index}"
    return label


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9가-힣._-]+", "", value)
    return value.strip("-_.")


def _rank_of(names: list[str], expected: str) -> int | None:
    try:
        return names.index(expected) + 1
    except ValueError:
        return None


def _mean(values: Any) -> float:
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 6)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vals = sorted(float(value) for value in values)
    index = min(len(vals) - 1, max(0, round((len(vals) - 1) * q)))
    return round(vals[index], 3)


def _threshold_passed(summary: dict[str, Any], metric: str, threshold: float) -> bool:
    if metric.startswith("max_"):
        value = float(summary.get(metric.removeprefix("max_"), 0.0))
        return value <= threshold
    return float(summary.get(metric, 0.0)) >= threshold


def _print_report(report: dict[str, Any]) -> None:
    scale = report["scale"]
    search = report["search"]
    print(report["benchmark"])
    print(
        "status={status} specs={specs} operations={ops} unique_tools={tools} "
        "duplicates={dupes} edges={edges} build={build:.2f}s".format(
            status=report["status"],
            specs=scale["spec_count"],
            ops=scale["operation_count"],
            tools=scale["unique_tool_count"],
            dupes=scale["duplicate_tool_count"],
            edges=scale["edge_count"],
            build=scale["build_seconds"],
        )
    )
    print(
        "schema: request_body={rb_schema}/{rb} response={resp}/{ops} params={params}".format(
            rb_schema=scale["request_body_schema_count"],
            rb=scale["request_body_count"],
            resp=scale["response_schema_count"],
            ops=scale["operation_count"],
            params=scale["parameter_count"],
        )
    )
    if search["status"] != "skipped":
        print(
            "search: status={status} cases={cases} hit@K={hit:.2f} recall@K={recall:.2f} "
            "mrr={mrr_:.2f} avg_latency={latency:.2f}ms".format(
                status=search["status"],
                cases=search["cases"],
                hit=search["case_hit_at_k"],
                recall=search["expected_tool_recall_at_k"],
                mrr_=search["mean_mrr"],
                latency=search["avg_latency_ms"],
            )
        )
        for case in report["cases"]:
            ranks = ", ".join(f"{name}:{rank}" for name, rank in case["expected_ranks"].items())
            print(
                "  {case_id}: hit={hit:.0f} ranks=[{ranks}] top={top}".format(
                    case_id=case["case_id"],
                    hit=case["hit_at_k"],
                    ranks=ranks,
                    top=", ".join(case["retrieved"][:3]),
                )
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swagger-url", default=DEFAULT_X2BEE_SWAGGER_URL)
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        help="Direct spec URL or local spec file. May be repeated. Skips Swagger discovery.",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_X2BEE_CASES_PATH)
    parser.add_argument("--no-cases", action="store_true")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--no-detect-dependencies", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--min-spec-count", type=int, default=1)
    parser.add_argument("--min-unique-tools", type=int, default=1000)
    parser.add_argument("--max-build-seconds", type=float, default=30.0)
    parser.add_argument("--max-response-bytes", type=int, default=5_000_000)
    parser.add_argument("--allow-private-hosts", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_benchmark(
        swagger_url=args.swagger_url,
        spec_sources=args.spec or None,
        cases_path=None if args.no_cases else args.cases,
        top_k=args.top_k,
        detect_dependencies=not args.no_detect_dependencies,
        min_confidence=args.min_confidence,
        min_spec_count=args.min_spec_count,
        min_unique_tools=args.min_unique_tools,
        max_build_seconds=args.max_build_seconds,
        max_response_bytes=args.max_response_bytes,
        allow_private_hosts=args.allow_private_hosts,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
