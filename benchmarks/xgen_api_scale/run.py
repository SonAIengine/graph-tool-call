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
from benchmarks.xgen_api_scale.gate import DEFAULT_GATE_PROFILE, evaluate_gate
from benchmarks.xgen_api_scale.manifest import load_snapshot_manifest
from graph_tool_call import ToolGraph, __version__
from graph_tool_call.core.contract_matching import description_alias_key
from graph_tool_call.graphify import (
    annotate_openapi_tool_semantics,
    build_candidate_set,
    promote_api_contract_signals,
    summarize_edge_quality,
    summarize_openapi_semantics,
    target_action_priority_for_query,
)
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
class PreparedScaleGraph:
    loaded_specs: list[LoadedSpec]
    profiles: list[SpecProfile]
    graph: ToolGraph
    ingest_summary: dict[str, Any]
    build_seconds: float


@dataclass
class SearchEvaluation:
    case_id: str
    query: str
    expected_tools: list[str]
    expected_any: list[str]
    expected_producers: list[str]
    expected_plan: list[str]
    retrieved: list[str]
    selected_target: str
    target_selector_candidates: list[str]
    target_selector_rank: int | None
    target_selector_exact: float
    target_action_priority: dict[str, int]
    target_equivalence_groups: list[dict[str, Any]]
    target_equivalence_group_count: int
    plan_candidates: list[str]
    producer_candidates: list[str]
    producer_added_count: int
    candidate_count: int
    candidate_schema_chars: int
    full_tool_schema_chars: int
    candidate_schema_char_fraction: float
    schema_context_reduction: float
    target_data_input_count: int
    target_required_data_input_count: int
    target_producible_input_count: int
    target_required_producible_input_count: int
    target_required_resolved_input_count: int
    producible_input_coverage: float
    required_input_coverage: float
    required_input_resolution_coverage: float
    producer_recall_at_k: float
    candidate_plan_coverage: float
    input_support: list[dict[str, Any]]
    expected_ranks: dict[str, int | None]
    primary_expected_rank: int | None
    best_expected_rank: int | None
    required_expected_found_at_k: bool
    any_expected_found_at_k: bool
    top_1_hit: float
    top_3_hit: float
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
    promote_contract_signals: bool = False,
    contract_signal_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the scale acceptance benchmark and return a JSON-serializable report."""
    prepared = prepare_scale_graph(
        swagger_url=swagger_url,
        spec_sources=spec_sources,
        max_response_bytes=max_response_bytes,
        allow_private_hosts=allow_private_hosts,
        detect_dependencies=detect_dependencies,
        min_confidence=min_confidence,
        promote_contract_signals=promote_contract_signals,
        contract_signal_options=contract_signal_options,
    )

    cases_doc = load_cases(cases_path)
    selected_top_k = int(top_k or cases_doc.get("top_k") or 10)
    tools_by_name = _tools_by_name(prepared.graph)
    schema_char_counts = _tool_schema_char_counts(tools_by_name)
    full_schema_chars = sum(schema_char_counts.values())
    producer_index = _contract_producer_index(tools_by_name)
    cases = [
        evaluate_search_case(
            case,
            tg=prepared.graph,
            tools_by_name=tools_by_name,
            producer_index=producer_index,
            top_k=selected_top_k,
            schema_char_counts=schema_char_counts,
            full_schema_chars=full_schema_chars,
        )
        for case in cases_doc.get("cases", [])
    ]
    search_summary = summarize_search(
        cases,
        thresholds=cases_doc.get("thresholds") or {},
        full_tool_count=len(prepared.graph.tools),
    )
    scale_summary = summarize_scale(
        prepared.profiles,
        loaded_specs=prepared.loaded_specs,
        ingest_summary=prepared.ingest_summary,
        graph=prepared.graph,
        build_seconds=prepared.build_seconds,
        min_spec_count=min_spec_count,
        min_unique_tools=min_unique_tools,
        max_build_seconds=max_build_seconds,
    )
    status = "pass" if scale_summary["status"] == "pass" else "fail"
    if cases and search_summary.get("status") != "pass":
        status = "fail"

    report = {
        "benchmark": cases_doc.get("name") or "XGEN API Scale Acceptance",
        "description": cases_doc.get("description") or "",
        "methodology": "xgen_large_openapi_acceptance",
        "model": "none",
        "graph_tool_call_version": __version__,
        "source_url": swagger_url,
        "top_k": selected_top_k,
        "detect_dependencies": detect_dependencies,
        "min_confidence": min_confidence,
        "promote_contract_signals": promote_contract_signals,
        "status": status,
        "scale": scale_summary,
        "search": search_summary,
        "specs": [asdict(profile) for profile in prepared.profiles],
        "cases": [asdict(case) for case in cases],
    }
    report["gate"] = evaluate_gate(report)
    return report


def run_top_k_sweep(
    *,
    swagger_url: str = DEFAULT_X2BEE_SWAGGER_URL,
    spec_sources: list[str | dict[str, Any]] | None = None,
    cases_path: Path | None = DEFAULT_X2BEE_CASES_PATH,
    top_ks: list[int] | None = None,
    acceptance_top_k: int | None = None,
    detect_dependencies: bool = True,
    min_confidence: float = 0.7,
    min_spec_count: int = 1,
    min_unique_tools: int = 1000,
    max_build_seconds: float = 30.0,
    max_response_bytes: int = 5_000_000,
    allow_private_hosts: bool = False,
    promote_contract_signals: bool = False,
    contract_signal_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one large graph build and compare multiple retrieval top-K settings."""
    prepared = prepare_scale_graph(
        swagger_url=swagger_url,
        spec_sources=spec_sources,
        max_response_bytes=max_response_bytes,
        allow_private_hosts=allow_private_hosts,
        detect_dependencies=detect_dependencies,
        min_confidence=min_confidence,
        promote_contract_signals=promote_contract_signals,
        contract_signal_options=contract_signal_options,
    )
    cases_doc = load_cases(cases_path)
    selected_top_ks = _normalize_top_ks(top_ks or [3, 5, int(cases_doc.get("top_k") or 10)])
    selected_acceptance_top_k = int(
        acceptance_top_k or cases_doc.get("top_k") or max(selected_top_ks)
    )
    if selected_acceptance_top_k not in selected_top_ks:
        selected_top_ks = _normalize_top_ks([*selected_top_ks, selected_acceptance_top_k])

    scale_summary = summarize_scale(
        prepared.profiles,
        loaded_specs=prepared.loaded_specs,
        ingest_summary=prepared.ingest_summary,
        graph=prepared.graph,
        build_seconds=prepared.build_seconds,
        min_spec_count=min_spec_count,
        min_unique_tools=min_unique_tools,
        max_build_seconds=max_build_seconds,
    )
    thresholds = cases_doc.get("thresholds") or {}
    tools_by_name = _tools_by_name(prepared.graph)
    schema_char_counts = _tool_schema_char_counts(tools_by_name)
    full_schema_chars = sum(schema_char_counts.values())
    producer_index = _contract_producer_index(tools_by_name)
    sweep: list[dict[str, Any]] = []
    acceptance_search_status = "skipped"
    for top_k in selected_top_ks:
        cases = [
            evaluate_search_case(
                case,
                tg=prepared.graph,
                tools_by_name=tools_by_name,
                producer_index=producer_index,
                top_k=top_k,
                schema_char_counts=schema_char_counts,
                full_schema_chars=full_schema_chars,
            )
            for case in cases_doc.get("cases", [])
        ]
        search_summary = summarize_search(
            cases,
            thresholds=thresholds if top_k == selected_acceptance_top_k else {},
            full_tool_count=len(prepared.graph.tools),
        )
        search_summary["thresholds_applied"] = bool(
            top_k == selected_acceptance_top_k and thresholds
        )
        if top_k != selected_acceptance_top_k and search_summary["status"] != "skipped":
            search_summary["status"] = "diagnostic"
        if top_k == selected_acceptance_top_k:
            acceptance_search_status = str(search_summary["status"])
        sweep.append(
            {
                "top_k": top_k,
                "search": search_summary,
                "cases": [asdict(case) for case in cases],
            }
        )

    status = "pass" if scale_summary["status"] == "pass" else "fail"
    if cases_doc.get("cases") and acceptance_search_status != "pass":
        status = "fail"

    report = {
        "benchmark": cases_doc.get("name") or "XGEN API Scale Acceptance",
        "description": cases_doc.get("description") or "",
        "methodology": "xgen_large_openapi_top_k_sweep",
        "model": "none",
        "graph_tool_call_version": __version__,
        "source_url": swagger_url,
        "top_ks": selected_top_ks,
        "acceptance_top_k": selected_acceptance_top_k,
        "detect_dependencies": detect_dependencies,
        "min_confidence": min_confidence,
        "promote_contract_signals": promote_contract_signals,
        "status": status,
        "scale": scale_summary,
        "sweep": sweep,
        "specs": [asdict(profile) for profile in prepared.profiles],
    }
    report["gate"] = evaluate_gate(report)
    return report


def run_contract_signal_ablation(
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
    contract_signal_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare large-OpenAPI retrieval with and without contract promotion.

    Specs are loaded once, then two graphs are built from the same input:
    baseline raw OpenAPI metadata and promoted contract metadata. This keeps
    the experiment cheap enough for day-to-day ranking work and makes deltas
    attributable to the promotion policy rather than live Swagger drift.
    """
    load_started = time.perf_counter()
    loaded_specs = load_specs(
        swagger_url=swagger_url,
        spec_sources=spec_sources,
        max_response_bytes=max_response_bytes,
        allow_private_hosts=allow_private_hosts,
    )
    load_seconds = round(time.perf_counter() - load_started, 3)
    profiles = [profile_spec(loaded) for loaded in loaded_specs]
    cases_doc = load_cases(cases_path)
    selected_top_k = int(top_k or cases_doc.get("top_k") or 10)
    thresholds = cases_doc.get("thresholds") or {}

    variants: list[dict[str, Any]] = []
    for name, promote in (("baseline", False), ("promoted", True)):
        build_started = time.perf_counter()
        graph, ingest_summary = build_scale_graph(
            loaded_specs,
            detect_dependencies=detect_dependencies,
            min_confidence=min_confidence,
            promote_contract_signals=promote,
            contract_signal_options=contract_signal_options if promote else None,
        )
        build_seconds = round(time.perf_counter() - build_started, 3)
        scale_summary = summarize_scale(
            profiles,
            loaded_specs=loaded_specs,
            ingest_summary=ingest_summary,
            graph=graph,
            build_seconds=build_seconds,
            min_spec_count=min_spec_count,
            min_unique_tools=min_unique_tools,
            max_build_seconds=max_build_seconds,
        )
        tools_by_name = _tools_by_name(graph)
        schema_char_counts = _tool_schema_char_counts(tools_by_name)
        full_schema_chars = sum(schema_char_counts.values())
        producer_index = _contract_producer_index(tools_by_name)
        cases = [
            evaluate_search_case(
                case,
                tg=graph,
                tools_by_name=tools_by_name,
                producer_index=producer_index,
                top_k=selected_top_k,
                schema_char_counts=schema_char_counts,
                full_schema_chars=full_schema_chars,
            )
            for case in cases_doc.get("cases", [])
        ]
        search_summary = summarize_search(
            cases,
            thresholds=thresholds,
            full_tool_count=len(graph.tools),
        )
        variant_status = "pass" if scale_summary["status"] == "pass" else "fail"
        if cases and search_summary.get("status") != "pass":
            variant_status = "fail"
        variants.append(
            {
                "name": name,
                "promote_contract_signals": promote,
                "status": variant_status,
                "scale": scale_summary,
                "search": search_summary,
                "cases": [asdict(case) for case in cases],
            }
        )

    promoted = next(v for v in variants if v["name"] == "promoted")
    return {
        "benchmark": cases_doc.get("name") or "XGEN API Scale Acceptance",
        "description": cases_doc.get("description") or "",
        "methodology": "xgen_large_openapi_contract_signal_ablation",
        "model": "none",
        "graph_tool_call_version": __version__,
        "source_url": swagger_url,
        "top_k": selected_top_k,
        "detect_dependencies": detect_dependencies,
        "min_confidence": min_confidence,
        "load_seconds": load_seconds,
        "status": promoted["status"],
        "comparison": _compare_contract_signal_variants(variants),
        "variants": variants,
        "specs": [asdict(profile) for profile in profiles],
    }


def prepare_scale_graph(
    *,
    swagger_url: str,
    spec_sources: list[str | dict[str, Any]] | None,
    max_response_bytes: int,
    allow_private_hosts: bool,
    detect_dependencies: bool,
    min_confidence: float,
    promote_contract_signals: bool = False,
    contract_signal_options: dict[str, Any] | None = None,
) -> PreparedScaleGraph:
    """Load, profile, ingest, and graph a large OpenAPI collection once."""
    started = time.perf_counter()
    loaded_specs = load_specs(
        swagger_url=swagger_url,
        spec_sources=spec_sources,
        max_response_bytes=max_response_bytes,
        allow_private_hosts=allow_private_hosts,
    )
    profiles = [profile_spec(loaded) for loaded in loaded_specs]
    graph, ingest_summary = build_scale_graph(
        loaded_specs,
        detect_dependencies=detect_dependencies,
        min_confidence=min_confidence,
        promote_contract_signals=promote_contract_signals,
        contract_signal_options=contract_signal_options,
    )
    return PreparedScaleGraph(
        loaded_specs=loaded_specs,
        profiles=profiles,
        graph=graph,
        ingest_summary=ingest_summary,
        build_seconds=round(time.perf_counter() - started, 3),
    )


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
    promote_contract_signals: bool = False,
    contract_signal_options: dict[str, Any] | None = None,
) -> tuple[ToolGraph, dict[str, Any]]:
    """Ingest all specs, dedupe by tool name, and build one large ToolGraph."""
    unique_tools: dict[str, Any] = {}
    duplicate_tool_names: Counter[str] = Counter()
    ingested_tool_total = 0
    source_tool_counts: dict[str, int] = {}
    contract_request_tool_count = 0
    contract_response_tool_count = 0
    contract_consumes_field_count = 0
    contract_produces_field_count = 0
    contract_input_locations: Counter[str] = Counter()

    for loaded in loaded_specs:
        tools, _normalized = ingest_openapi(loaded.spec)
        ingested_tool_total += len(tools)
        source_tool_counts[loaded.label] = len(tools)
        for tool in tools:
            metadata = dict(tool.metadata or {})
            metadata["source_label"] = loaded.label
            metadata["source_url"] = loaded.source
            api_contract = metadata.get("api_contract") or {}
            consumes = api_contract.get("consumes") or []
            produces = api_contract.get("produces") or []
            if consumes:
                contract_request_tool_count += 1
                contract_consumes_field_count += len(consumes)
            if produces:
                contract_response_tool_count += 1
                contract_produces_field_count += len(produces)
            for location, names in (metadata.get("input_locations") or {}).items():
                if isinstance(names, list):
                    contract_input_locations[str(location)] += len(names)
            tool.metadata = metadata
            if tool.name in unique_tools:
                duplicate_tool_names[tool.name] += 1
                continue
            unique_tools[tool.name] = tool

    unique_tool_list = list(unique_tools.values())
    annotate_openapi_tool_semantics(unique_tool_list)
    semantic_metadata = summarize_openapi_semantics(unique_tool_list)
    contract_signal_promotion: dict[str, Any] = {
        "enabled": bool(promote_contract_signals),
        "tools_promoted": 0,
        "produces_added": 0,
        "consumes_added": 0,
        "produces_skipped": 0,
        "consumes_skipped": 0,
    }
    if promote_contract_signals:
        contract_signal_promotion.update(
            promote_api_contract_signals(
                unique_tool_list,
                **(contract_signal_options or {}),
            )
        )

    tg = ToolGraph()
    registered = tg.add_tools(
        unique_tool_list,
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
        "contract_request_tool_count": contract_request_tool_count,
        "contract_response_tool_count": contract_response_tool_count,
        "contract_consumes_field_count": contract_consumes_field_count,
        "contract_produces_field_count": contract_produces_field_count,
        "contract_input_locations": dict(sorted(contract_input_locations.items())),
        "contract_signal_promotion": contract_signal_promotion,
        "semantic_metadata": semantic_metadata,
    }


def load_cases(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"name": "XGEN API Scale Acceptance", "top_k": 10, "cases": []}
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_search_case(
    case: dict[str, Any],
    *,
    tg: ToolGraph,
    tools_by_name: dict[str, dict[str, Any]],
    producer_index: dict[str, list[str]],
    top_k: int,
    schema_char_counts: dict[str, int] | None = None,
    full_schema_chars: int = 0,
) -> SearchEvaluation:
    query = str(case["query"])
    expected_tools = [str(name) for name in case.get("expected_tools") or []]
    expected_any = [str(name) for name in case.get("expected_any") or []]
    expected_producers = [str(name) for name in case.get("expected_producers") or []]
    expected_plan = [str(name) for name in case.get("expected_plan") or []]
    expected_union = set(expected_tools) | set(expected_any)

    started = time.perf_counter()
    results = tg.retrieve_with_scores(query, top_k=top_k)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    retrieved = [result.tool.name for result in results]
    retrieved_set = set(retrieved)
    target_action_priority = target_action_priority_for_query(query)
    selector_set = build_candidate_set(
        retrieved,
        tools_by_name,
        target_action_priority=target_action_priority,
        max_hops=0,
    )
    selector_candidates = [str(name) for name in selector_set.get("target_candidates") or []]
    selected_target = selector_candidates[0] if selector_candidates else ""
    target_equivalence_groups = [
        dict(row)
        for row in selector_set.get("target_equivalence_groups") or []
        if isinstance(row, dict)
    ]
    readiness = _plan_readiness(
        selected_target,
        tools_by_name,
        producer_index=producer_index,
    )
    plan_candidates = [str(name) for name in readiness["plan_candidates"]]
    candidate_schema_chars = sum(
        (schema_char_counts or {}).get(name, 0) for name in plan_candidates
    )
    schema_char_fraction = _ratio(candidate_schema_chars, full_schema_chars)
    schema_context_reduction = round(1.0 - schema_char_fraction, 6)

    required_ok = set(expected_tools).issubset(retrieved_set) if expected_tools else True
    any_ok = bool(set(expected_any) & retrieved_set) if expected_any else True
    hit = 1.0 if required_ok and any_ok else 0.0
    recall_expected = (
        1.0
        if expected_any and not expected_tools and any_ok
        else recall_at_k(retrieved, expected_union, top_k)
    )
    expected_ranks = {name: _rank_of(retrieved, name) for name in sorted(expected_union)}
    target_selector_rank = _best_rank(selector_candidates, expected_union)
    target_selector_exact = 1.0 if not expected_union or selected_target in expected_union else 0.0
    producer_recall = recall_at_k(
        readiness["plan_candidates"],
        set(expected_producers),
        len(readiness["plan_candidates"]),
    )
    candidate_plan_coverage = recall_at_k(
        readiness["plan_candidates"],
        set(expected_plan),
        len(readiness["plan_candidates"]),
    )
    primary_expected_rank = _rank_of(retrieved, expected_tools[0]) if expected_tools else None
    ranked_expected = [rank for rank in expected_ranks.values() if rank is not None]
    best_expected_rank = min(ranked_expected) if ranked_expected else None
    issues = _case_issues(
        expected_tools=expected_tools,
        expected_any=expected_any,
        retrieved_set=retrieved_set,
        best_expected_rank=best_expected_rank,
    )
    if target_selector_exact < 1.0:
        issues = [issue for issue in issues if issue != "pass"]
        issues.append("target_selector_miss")
    if (
        int(readiness["target_required_data_input_count"]) > 0
        and float(readiness["required_input_coverage"]) < 1.0
    ):
        issues = [issue for issue in issues if issue != "pass"]
        issues.append("required_input_not_producible")

    return SearchEvaluation(
        case_id=str(case["id"]),
        query=query,
        expected_tools=expected_tools,
        expected_any=expected_any,
        expected_producers=expected_producers,
        expected_plan=expected_plan,
        retrieved=retrieved,
        selected_target=selected_target,
        target_selector_candidates=selector_candidates,
        target_selector_rank=target_selector_rank,
        target_selector_exact=target_selector_exact,
        target_action_priority=target_action_priority,
        target_equivalence_groups=target_equivalence_groups,
        target_equivalence_group_count=len(target_equivalence_groups),
        plan_candidates=plan_candidates,
        producer_candidates=[str(name) for name in readiness["producer_candidates"]],
        producer_added_count=int(readiness["producer_added_count"]),
        candidate_count=int(readiness["candidate_count"]),
        candidate_schema_chars=candidate_schema_chars,
        full_tool_schema_chars=int(full_schema_chars),
        candidate_schema_char_fraction=schema_char_fraction,
        schema_context_reduction=schema_context_reduction,
        target_data_input_count=int(readiness["target_data_input_count"]),
        target_required_data_input_count=int(readiness["target_required_data_input_count"]),
        target_producible_input_count=int(readiness["target_producible_input_count"]),
        target_required_producible_input_count=int(
            readiness["target_required_producible_input_count"]
        ),
        target_required_resolved_input_count=int(readiness["target_required_resolved_input_count"]),
        producible_input_coverage=float(readiness["producible_input_coverage"]),
        required_input_coverage=float(readiness["required_input_coverage"]),
        required_input_resolution_coverage=float(readiness["required_input_resolution_coverage"]),
        producer_recall_at_k=producer_recall,
        candidate_plan_coverage=candidate_plan_coverage,
        input_support=[dict(row) for row in readiness["input_support"]],
        expected_ranks=expected_ranks,
        primary_expected_rank=primary_expected_rank,
        best_expected_rank=best_expected_rank,
        required_expected_found_at_k=required_ok,
        any_expected_found_at_k=any_ok,
        top_1_hit=1.0 if best_expected_rank == 1 else 0.0,
        top_3_hit=1.0 if best_expected_rank is not None and best_expected_rank <= 3 else 0.0,
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
    semantic_summary = summarize_openapi_semantics(graph.tools)
    edge_quality_summary = summarize_edge_quality(graph.graph)
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
        "contract_request_tool_count": ingest_summary["contract_request_tool_count"],
        "contract_response_tool_count": ingest_summary["contract_response_tool_count"],
        "contract_consumes_field_count": ingest_summary["contract_consumes_field_count"],
        "contract_produces_field_count": ingest_summary["contract_produces_field_count"],
        "contract_input_locations": ingest_summary["contract_input_locations"],
        "contract_signal_promotion": ingest_summary["contract_signal_promotion"],
        "semantic_summary": semantic_summary,
        "edge_quality_summary": edge_quality_summary,
        "canonical_action_known_rate": semantic_summary["canonical_action_known_rate"],
        "primary_resource_assigned_rate": semantic_summary["primary_resource_assigned_rate"],
        "path_module_assigned_rate": semantic_summary["path_module_assigned_rate"],
        "strong_deterministic_edge_rate": edge_quality_summary[
            "strong_deterministic_evidence_rate"
        ],
    }


def summarize_search(
    cases: list[SearchEvaluation],
    *,
    thresholds: dict[str, Any],
    full_tool_count: int | None = None,
) -> dict[str, Any]:
    if not cases:
        return {"status": "skipped", "cases": 0}

    summary: dict[str, Any] = {
        "cases": len(cases),
        "case_hit_at_k": _mean(case.hit_at_k for case in cases),
        "expected_tool_recall_at_k": _mean(case.expected_tool_recall_at_k for case in cases),
        "target_selector_exact_at_k": _mean(case.target_selector_exact for case in cases),
        "target_selector_miss_count": sum(1 for case in cases if case.target_selector_exact < 1.0),
        "avg_target_equivalence_group_count": _mean(
            case.target_equivalence_group_count for case in cases
        ),
        "target_equivalence_group_case_count": sum(
            1 for case in cases if case.target_equivalence_group_count > 0
        ),
        "avg_candidate_count": _mean(case.candidate_count for case in cases),
        "max_candidate_count": max((case.candidate_count for case in cases), default=0),
        "full_tool_schema_chars": max((case.full_tool_schema_chars for case in cases), default=0),
        "avg_candidate_schema_chars": _mean(case.candidate_schema_chars for case in cases),
        "max_candidate_schema_chars": max(
            (case.candidate_schema_chars for case in cases), default=0
        ),
        "avg_candidate_schema_char_fraction": _mean(
            case.candidate_schema_char_fraction for case in cases
        ),
        "avg_schema_context_reduction": _mean(case.schema_context_reduction for case in cases),
        "min_schema_context_reduction": min(
            (case.schema_context_reduction for case in cases), default=0.0
        ),
        "avg_producer_added_count": _mean(case.producer_added_count for case in cases),
        "producer_added_case_count": sum(1 for case in cases if case.producer_added_count > 0),
        "expected_producer_case_count": sum(1 for case in cases if case.expected_producers),
        "producer_recall_at_k": _mean(
            case.producer_recall_at_k for case in cases if case.expected_producers
        ),
        "expected_plan_case_count": sum(1 for case in cases if case.expected_plan),
        "candidate_plan_coverage": _mean(
            case.candidate_plan_coverage for case in cases if case.expected_plan
        ),
        "avg_target_data_input_count": _mean(case.target_data_input_count for case in cases),
        "avg_target_required_data_input_count": _mean(
            case.target_required_data_input_count for case in cases
        ),
        "avg_producible_input_coverage": _mean(case.producible_input_coverage for case in cases),
        "avg_required_input_coverage": _mean(case.required_input_coverage for case in cases),
        "avg_required_input_resolution_coverage": _mean(
            case.required_input_resolution_coverage for case in cases
        ),
        "required_input_ready_case_count": sum(
            1 for case in cases if case.required_input_coverage >= 1.0
        ),
        "required_input_resolved_case_count": sum(
            1 for case in cases if case.required_input_resolution_coverage >= 1.0
        ),
        "unresolved_required_input_count": sum(
            1
            for case in cases
            for row in case.input_support
            if row.get("required") and row.get("resolution") == "unresolved"
        ),
        "input_resolution_counts": dict(
            Counter(
                row["resolution"]
                for case in cases
                for row in case.input_support
                if row.get("required") and row.get("resolution")
            ).most_common()
        ),
        "readiness_issue_counts": dict(
            Counter(
                row["issue_code"]
                for case in cases
                for row in case.input_support
                if row.get("issue_code")
            ).most_common()
        ),
        "top_1_hit_at_k": _mean(case.top_1_hit for case in cases),
        "top_3_hit_at_k": _mean(case.top_3_hit for case in cases),
        "mean_mrr": _mean(case.mrr for case in cases),
        "mean_best_expected_rank": _mean(
            case.best_expected_rank for case in cases if case.best_expected_rank is not None
        ),
        "max_best_expected_rank": max(
            (case.best_expected_rank for case in cases if case.best_expected_rank is not None),
            default=None,
        ),
        "avg_latency_ms": round(_mean(case.latency_ms for case in cases), 3),
        "p50_latency_ms": _percentile([case.latency_ms for case in cases], 0.5),
        "max_latency_ms": max(case.latency_ms for case in cases),
        "case_rank_buckets": _case_rank_buckets(cases),
        "target_selector_rank_buckets": _selector_rank_buckets(cases),
        "rank_buckets": _rank_buckets(cases),
        "missing_expected_tools": _missing_expected_tools(cases),
        "issues": dict(Counter(issue for case in cases for issue in case.issues).most_common()),
    }
    _add_tool_surface_reduction(summary, full_tool_count=full_tool_count)
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


def _add_tool_surface_reduction(
    summary: dict[str, Any],
    *,
    full_tool_count: int | None,
) -> None:
    if not full_tool_count or full_tool_count <= 0:
        return
    avg_fraction = _ratio(float(summary.get("avg_candidate_count", 0.0)), full_tool_count)
    max_fraction = _ratio(float(summary.get("max_candidate_count", 0.0)), full_tool_count)
    summary.update(
        {
            "full_tool_count": int(full_tool_count),
            "avg_candidate_tool_fraction": avg_fraction,
            "avg_tool_surface_reduction": round(1.0 - avg_fraction, 6),
            "max_candidate_tool_fraction": max_fraction,
            "min_tool_surface_reduction": round(1.0 - max_fraction, 6),
        }
    )


def _compare_contract_signal_variants(variants: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {variant["name"]: variant for variant in variants}
    baseline = by_name.get("baseline") or {}
    promoted = by_name.get("promoted") or {}
    base_search = baseline.get("search") or {}
    promoted_search = promoted.get("search") or {}
    metric_names = [
        "case_hit_at_k",
        "expected_tool_recall_at_k",
        "top_1_hit_at_k",
        "top_3_hit_at_k",
        "mean_mrr",
        "avg_latency_ms",
        "p50_latency_ms",
        "target_selector_exact_at_k",
        "avg_candidate_count",
        "producer_recall_at_k",
        "candidate_plan_coverage",
        "avg_required_input_coverage",
        "avg_required_input_resolution_coverage",
    ]
    deltas = {
        f"{metric}_delta": round(
            float(promoted_search.get(metric) or 0.0) - float(base_search.get(metric) or 0.0),
            6,
        )
        for metric in metric_names
    }
    promoted_scale = promoted.get("scale") or {}
    return {
        **deltas,
        "baseline_status": baseline.get("status", "missing"),
        "promoted_status": promoted.get("status", "missing"),
        "contract_signal_promotion": promoted_scale.get("contract_signal_promotion") or {},
    }


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
    best_expected_rank: int | None,
) -> list[str]:
    issues: list[str] = []
    missing_required = [name for name in expected_tools if name not in retrieved_set]
    if missing_required:
        issues.append("missing_required_expected_tool")
    if expected_any and not (set(expected_any) & retrieved_set):
        issues.append("missing_any_expected_tool")
    if best_expected_rank is not None and best_expected_rank > 1:
        issues.append("best_expected_below_top_1")
    if best_expected_rank is not None and best_expected_rank > 3:
        issues.append("best_expected_below_top_3")
    return issues or ["pass"]


def _plan_readiness(
    selected_target: str,
    tools_by_name: dict[str, dict[str, Any]],
    *,
    producer_index: dict[str, list[str]],
    max_producers_per_field: int = 3,
) -> dict[str, Any]:
    target_tool = tools_by_name.get(selected_target) or {}
    consumes = _data_consumes(target_tool)
    input_support: list[dict[str, Any]] = []
    supported = 0
    required_total = 0
    required_supported = 0
    required_resolved = 0
    required_producer_choices: list[list[str]] = []

    for consume in consumes:
        required = bool(consume.get("required"))
        if required:
            required_total += 1
        producers = _producer_candidates_for_field(
            consume,
            producer_index=producer_index,
            tools_by_name=tools_by_name,
            exclude={selected_target},
            max_producers=max_producers_per_field,
        )
        if producers:
            supported += 1
            if required:
                required_supported += 1
                required_producer_choices.append(producers)
        issue_code = _readiness_issue_code(consume, supported=bool(producers))
        resolution = _input_resolution(issue_code, supported=bool(producers))
        if required and resolution != "unresolved":
            required_resolved += 1
        input_support.append(
            {
                "field_name": str(consume.get("field_name") or ""),
                "semantic_tag": str(consume.get("semantic_tag") or ""),
                "location": str(consume.get("location") or ""),
                "field_type": str(consume.get("field_type") or ""),
                "required": required,
                "producer_candidates": producers,
                "supported": bool(producers),
                "issue_code": issue_code,
                "resolution": resolution,
            }
        )

    producers = _select_representative_producers(required_producer_choices, tools_by_name)
    plan_candidates = _dedupe([selected_target, *producers])
    return {
        "plan_candidates": plan_candidates,
        "producer_candidates": producers,
        "producer_added_count": len(producers),
        "candidate_count": len(plan_candidates),
        "target_data_input_count": len(consumes),
        "target_required_data_input_count": required_total,
        "target_producible_input_count": supported,
        "target_required_producible_input_count": required_supported,
        "target_required_resolved_input_count": required_resolved,
        "producible_input_coverage": _ratio(supported, len(consumes)),
        "required_input_coverage": _ratio(required_supported, required_total),
        "required_input_resolution_coverage": _ratio(required_resolved, required_total),
        "input_support": input_support,
    }


def _input_resolution(issue_code: str, *, supported: bool) -> str:
    if supported:
        return "producer"
    if issue_code == "required_request_wrapper":
        return "request_wrapper"
    if issue_code == "required_context_input":
        return "context"
    if issue_code in {"required_enum_input", "required_filter_input"}:
        return "user_input"
    return "unresolved"


def _readiness_issue_code(consume: dict[str, Any], *, supported: bool) -> str:
    if supported or not bool(consume.get("required")):
        return ""
    if _is_request_wrapper_input(consume):
        return "required_request_wrapper"
    if _is_context_like_input(consume):
        return "required_context_input"
    if consume.get("enum"):
        return "required_enum_input"
    if _is_filter_like_input(consume):
        return "required_filter_input"
    return "required_producer_missing"


def _is_request_wrapper_input(row: dict[str, Any]) -> bool:
    name = _normalized_field_name(row.get("field_name"))
    description = str(row.get("description") or "").lower()
    return name.endswith("request") or " request" in description


def _is_context_like_input(row: dict[str, Any]) -> bool:
    name = _normalized_field_name(row.get("field_name"))
    return name in {
        "systemtype",
        "systype",
        "sysgbcd",
        "siteno",
        "tenantid",
        "langcd",
        "locale",
        "channel",
    }


def _is_filter_like_input(row: dict[str, Any]) -> bool:
    name = _normalized_field_name(row.get("field_name"))
    description = str(row.get("description") or "").lower()
    if str(row.get("location") or "").lower() != "query":
        return False
    return (
        "search" in name
        or "filter" in name
        or "date" in name
        or name.endswith("type")
        or name.endswith("cd")
        or "검색" in description
        or "코드" in description
    )


def _normalized_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").strip().lower())


def _data_consumes(tool: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _contract_rows(tool, "consumes")
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        kind = str(row.get("kind") or "data").strip().lower()
        if kind != "data":
            continue
        key = (
            str(row.get("field_name") or ""),
            str(row.get("semantic_tag") or ""),
            str(row.get("location") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _contract_producer_index(
    tools_by_name: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for name, tool in tools_by_name.items():
        for produce in _contract_rows(tool, "produces"):
            for token in _contract_tokens(produce):
                index.setdefault(token, []).append(name)
    return {token: _dedupe(names) for token, names in index.items()}


def _producer_candidates_for_field(
    consume: dict[str, Any],
    *,
    producer_index: dict[str, list[str]],
    tools_by_name: dict[str, dict[str, Any]],
    exclude: set[str],
    max_producers: int,
) -> list[str]:
    producers: list[str] = []
    for token in _contract_tokens(consume):
        producers.extend(name for name in producer_index.get(token, []) if name not in exclude)
    return _rank_producer_candidates(_dedupe(producers), tools_by_name)[: max(0, max_producers)]


def _rank_producer_candidates(
    producer_names: list[str],
    tools_by_name: dict[str, dict[str, Any]],
) -> list[str]:
    return sorted(
        producer_names,
        key=lambda name: (
            -_producer_quality_score(name, tools_by_name),
            producer_names.index(name),
            name,
        ),
    )


def _select_representative_producers(
    per_field_candidates: list[list[str]],
    tools_by_name: dict[str, dict[str, Any]],
) -> list[str]:
    selected: list[str] = []
    uncovered = {index for index, candidates in enumerate(per_field_candidates) if any(candidates)}
    while uncovered:
        scored: list[tuple[int, int, int, str]] = []
        candidate_names = _dedupe(
            [
                name
                for index in sorted(uncovered)
                for name in per_field_candidates[index]
                if name not in selected
            ]
        )
        if not candidate_names:
            break
        for name in candidate_names:
            covered = {index for index in uncovered if name in per_field_candidates[index]}
            if not covered:
                continue
            first_rank = min(per_field_candidates[index].index(name) for index in covered)
            scored.append(
                (
                    len(covered),
                    _producer_quality_score(name, tools_by_name),
                    -first_rank,
                    name,
                )
            )
        if not scored:
            break
        _coverage, _quality, _rank, name = max(scored)
        selected.append(name)
        uncovered = {index for index in uncovered if name not in per_field_candidates[index]}
    return selected


def _producer_quality_score(name: str, tools_by_name: dict[str, dict[str, Any]]) -> int:
    tool = tools_by_name.get(name) or {}
    metadata = tool.get("metadata") or {}
    ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
    action = str(ai.get("canonical_action") or "").strip().lower()
    method = str(metadata.get("method") or "").strip().lower()
    lower_name = name.lower()
    score = 0
    if action in {"search", "list", "lookup"}:
        score += 80
    elif action == "read":
        score += 70
    elif action in {"create", "update", "delete"}:
        score -= 60
    elif action == "action":
        score -= 20
    if lower_name.startswith(("get", "list", "search", "find", "query", "select", "fetch")):
        score += 40
    if any(term in lower_name for term in ("list", "search", "query", "lookup")):
        score += 15
    if lower_name.startswith(
        (
            "save",
            "insert",
            "update",
            "modify",
            "delete",
            "remove",
            "reject",
            "withdraw",
            "approve",
            "cancel",
            "create",
            "register",
            "send",
            "upload",
        )
    ):
        score -= 50
    if method == "get":
        score += 10
    return score


def _contract_rows(tool: dict[str, Any], key: str) -> list[dict[str, Any]]:
    metadata = tool.get("metadata") or {}
    rows = [dict(row) for row in metadata.get(key) or [] if isinstance(row, dict)]
    api_contract = metadata.get("api_contract") or {}
    rows.extend(dict(row) for row in api_contract.get(key) or [] if isinstance(row, dict))
    return rows


def _contract_tokens(row: dict[str, Any]) -> list[str]:
    values = [
        row.get("semantic_tag"),
        row.get("field_name"),
        row.get("json_path"),
        *(row.get("value_path_aliases") or []),
    ]
    tokens: list[str] = []
    description_key = description_alias_key(row)
    if description_key:
        tokens.append(f"description:{description_key}")
    for value in values:
        if not value:
            continue
        text = str(value).strip().lower()
        if not text:
            continue
        tokens.append(text)
        normalized = re.sub(r"[^a-z0-9가-힣]+", "", text)
        if normalized:
            tokens.append(normalized)
    return _dedupe(tokens)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 6)


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


def _best_rank(names: list[str], expected_names: set[str]) -> int | None:
    ranks = [_rank_of(names, name) for name in expected_names]
    found = [rank for rank in ranks if rank is not None]
    return min(found) if found else None


def _tools_by_name(graph: ToolGraph) -> dict[str, dict[str, Any]]:
    return {name: tool.to_dict() for name, tool in graph.tools.items()}


def _tool_schema_char_counts(tools_by_name: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        name: len(
            json.dumps(
                tool,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )
        for name, tool in tools_by_name.items()
    }


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


def _rank_buckets(cases: list[SearchEvaluation]) -> dict[str, int]:
    buckets = {"top_1": 0, "top_3": 0, "top_5": 0, "top_10": 0, "missing": 0}
    for case in cases:
        for rank in case.expected_ranks.values():
            if rank == 1:
                buckets["top_1"] += 1
            elif rank is not None and rank <= 3:
                buckets["top_3"] += 1
            elif rank is not None and rank <= 5:
                buckets["top_5"] += 1
            elif rank is not None and rank <= 10:
                buckets["top_10"] += 1
            else:
                buckets["missing"] += 1
    return buckets


def _case_rank_buckets(cases: list[SearchEvaluation]) -> dict[str, int]:
    buckets = {"top_1": 0, "top_3": 0, "top_5": 0, "top_10": 0, "missing": 0}
    for case in cases:
        rank = case.best_expected_rank
        if rank == 1:
            buckets["top_1"] += 1
        elif rank is not None and rank <= 3:
            buckets["top_3"] += 1
        elif rank is not None and rank <= 5:
            buckets["top_5"] += 1
        elif rank is not None and rank <= 10:
            buckets["top_10"] += 1
        else:
            buckets["missing"] += 1
    return buckets


def _selector_rank_buckets(cases: list[SearchEvaluation]) -> dict[str, int]:
    buckets = {"top_1": 0, "top_3": 0, "top_5": 0, "top_10": 0, "missing": 0}
    for case in cases:
        rank = case.target_selector_rank
        if rank == 1:
            buckets["top_1"] += 1
        elif rank is not None and rank <= 3:
            buckets["top_3"] += 1
        elif rank is not None and rank <= 5:
            buckets["top_5"] += 1
        elif rank is not None and rank <= 10:
            buckets["top_10"] += 1
        else:
            buckets["missing"] += 1
    return buckets


def _missing_expected_tools(cases: list[SearchEvaluation]) -> dict[str, int]:
    missing = Counter(
        name
        for case in cases
        for name, rank in case.expected_ranks.items()
        if rank is None and name in set(case.expected_tools)
    )
    return dict(missing.most_common())


def _threshold_passed(summary: dict[str, Any], metric: str, threshold: float) -> bool:
    if metric.startswith("max_"):
        source_metric = metric if metric in summary else metric.removeprefix("max_")
        value = float(summary.get(source_metric, 0.0))
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
    print(
        "contract: request_tools={req_tools} response_tools={resp_tools} "
        "consumes={consumes} produces={produces}".format(
            req_tools=scale["contract_request_tool_count"],
            resp_tools=scale["contract_response_tool_count"],
            consumes=scale["contract_consumes_field_count"],
            produces=scale["contract_produces_field_count"],
        )
    )
    _print_contract_promotion(scale)
    if search["status"] != "skipped":
        print(
            "search: status={status} cases={cases} hit@K={hit:.2f} recall@K={recall:.2f} "
            "selector={selector:.2f} top1={top1:.2f} top3={top3:.2f} "
            "mrr={mrr_:.2f} candidates={candidates:.2f} producers={producers:.2f} "
            "tool_reduction={reduction:.2%} schema_reduction={schema_reduction:.2%} "
            "required_inputs={required:.2f} resolved_inputs={resolved:.2f} "
            "avg_latency={latency:.2f}ms".format(
                status=search["status"],
                cases=search["cases"],
                hit=search["case_hit_at_k"],
                recall=search["expected_tool_recall_at_k"],
                selector=search["target_selector_exact_at_k"],
                top1=search["top_1_hit_at_k"],
                top3=search["top_3_hit_at_k"],
                mrr_=search["mean_mrr"],
                candidates=search["avg_candidate_count"],
                producers=search["avg_producer_added_count"],
                reduction=search.get("avg_tool_surface_reduction", 0.0),
                schema_reduction=search.get("avg_schema_context_reduction", 0.0),
                required=search["avg_required_input_coverage"],
                resolved=search["avg_required_input_resolution_coverage"],
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
            print(
                "    selector={selected} selector_rank={rank} candidates={count} "
                "producers={producers} required_inputs={required:.2f} "
                "resolved_inputs={resolved:.2f}".format(
                    selected=case["selected_target"],
                    rank=case["target_selector_rank"],
                    count=case["candidate_count"],
                    producers=case["producer_added_count"],
                    required=case["required_input_coverage"],
                    resolved=case["required_input_resolution_coverage"],
                )
            )
        if search.get("readiness_issue_counts"):
            print(f"readiness issues: {search['readiness_issue_counts']}")
        if search.get("input_resolution_counts"):
            print(f"input resolutions: {search['input_resolution_counts']}")


def _print_sweep_report(report: dict[str, Any]) -> None:
    scale = report["scale"]
    print(report["benchmark"])
    print(
        "status={status} specs={specs} operations={ops} unique_tools={tools} "
        "duplicates={dupes} edges={edges} build={build:.2f}s acceptance_k={acceptance}".format(
            status=report["status"],
            specs=scale["spec_count"],
            ops=scale["operation_count"],
            tools=scale["unique_tool_count"],
            dupes=scale["duplicate_tool_count"],
            edges=scale["edge_count"],
            build=scale["build_seconds"],
            acceptance=report["acceptance_top_k"],
        )
    )
    print(
        "contract: request_tools={req_tools} response_tools={resp_tools} "
        "consumes={consumes} produces={produces}".format(
            req_tools=scale["contract_request_tool_count"],
            resp_tools=scale["contract_response_tool_count"],
            consumes=scale["contract_consumes_field_count"],
            produces=scale["contract_produces_field_count"],
        )
    )
    _print_contract_promotion(scale)
    for run in report["sweep"]:
        search = run["search"]
        if search["status"] == "skipped":
            print(f"k={run['top_k']}: search skipped")
            continue
        suffix = " acceptance" if run["top_k"] == report["acceptance_top_k"] else ""
        print(
            "k={top_k:<2}{suffix}: status={status} hit@K={hit:.2f} recall@K={recall:.2f} "
            "selector={selector:.2f} top1={top1:.2f} top3={top3:.2f} "
            "mrr={mrr_:.2f} candidates={candidates:.2f} producers={producers:.2f} "
            "tool_reduction={reduction:.2%} schema_reduction={schema_reduction:.2%} "
            "required_inputs={required:.2f} resolved_inputs={resolved:.2f} "
            "avg_latency={latency:.2f}ms issues={issues} readiness={readiness} "
            "resolutions={resolutions}".format(
                top_k=run["top_k"],
                suffix=suffix,
                status=search["status"],
                hit=search["case_hit_at_k"],
                recall=search["expected_tool_recall_at_k"],
                selector=search["target_selector_exact_at_k"],
                top1=search["top_1_hit_at_k"],
                top3=search["top_3_hit_at_k"],
                mrr_=search["mean_mrr"],
                candidates=search["avg_candidate_count"],
                producers=search["avg_producer_added_count"],
                reduction=search.get("avg_tool_surface_reduction", 0.0),
                schema_reduction=search.get("avg_schema_context_reduction", 0.0),
                required=search["avg_required_input_coverage"],
                resolved=search["avg_required_input_resolution_coverage"],
                latency=search["avg_latency_ms"],
                issues=search["issues"],
                readiness=search["readiness_issue_counts"],
                resolutions=search["input_resolution_counts"],
            )
        )


def _print_ablation_report(report: dict[str, Any]) -> None:
    print(report["benchmark"])
    print(
        "status={status} methodology={methodology} load={load:.2f}s top_k={top_k}".format(
            status=report["status"],
            methodology=report["methodology"],
            load=report["load_seconds"],
            top_k=report["top_k"],
        )
    )
    for variant in report["variants"]:
        scale = variant["scale"]
        search = variant["search"]
        print(
            "[{name}] status={status} promote={promote} edges={edges} build={build:.2f}s".format(
                name=variant["name"],
                status=variant["status"],
                promote=variant["promote_contract_signals"],
                edges=scale["edge_count"],
                build=scale["build_seconds"],
            )
        )
        _print_contract_promotion(scale)
        if search["status"] != "skipped":
            print(
                "  search: hit@K={hit:.2f} recall@K={recall:.2f} top1={top1:.2f} "
                "top3={top3:.2f} selector={selector:.2f} mrr={mrr_:.2f} "
                "candidates={candidates:.2f} producers={producers:.2f} "
                "tool_reduction={reduction:.2%} schema_reduction={schema_reduction:.2%} "
                "required_inputs={required:.2f} resolved_inputs={resolved:.2f} "
                "avg_latency={latency:.2f}ms".format(
                    hit=search["case_hit_at_k"],
                    recall=search["expected_tool_recall_at_k"],
                    top1=search["top_1_hit_at_k"],
                    top3=search["top_3_hit_at_k"],
                    selector=search["target_selector_exact_at_k"],
                    mrr_=search["mean_mrr"],
                    candidates=search["avg_candidate_count"],
                    producers=search["avg_producer_added_count"],
                    reduction=search.get("avg_tool_surface_reduction", 0.0),
                    schema_reduction=search.get("avg_schema_context_reduction", 0.0),
                    required=search["avg_required_input_coverage"],
                    resolved=search["avg_required_input_resolution_coverage"],
                    latency=search["avg_latency_ms"],
                )
            )
    comparison = report["comparison"]
    print("Deltas promoted-baseline:")
    for key, value in comparison.items():
        if key == "contract_signal_promotion":
            continue
        print(f"  {key}: {value}")


def _print_contract_promotion(scale: dict[str, Any]) -> None:
    promotion = scale.get("contract_signal_promotion") or {}
    if not promotion.get("enabled"):
        return
    print(
        "promotion: tools={tools} produces_added={produces} consumes_added={consumes} "
        "skipped_produces={skipped_p} skipped_consumes={skipped_c}".format(
            tools=promotion.get("tools_promoted", 0),
            produces=promotion.get("produces_added", 0),
            consumes=promotion.get("consumes_added", 0),
            skipped_p=promotion.get("produces_skipped", 0),
            skipped_c=promotion.get("consumes_skipped", 0),
        )
    )


def _normalize_top_ks(values: list[int]) -> list[int]:
    normalized = sorted({int(value) for value in values if int(value) > 0})
    if not normalized:
        msg = "top-K sweep requires at least one positive integer"
        raise ValueError(msg)
    return normalized


def _parse_top_ks(value: str | None) -> list[int] | None:
    if not value:
        return None
    return _normalize_top_ks([int(part.strip()) for part in value.split(",") if part.strip()])


def _parse_csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def _contract_signal_options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    options = {
        "user_input_field_names": _parse_csv_set(args.user_input_fields),
        "context_field_names": _parse_csv_set(args.context_fields),
        "auth_field_names": _parse_csv_set(args.auth_fields),
        "paging_field_names": _parse_csv_set(args.paging_fields),
        "search_filter_field_names": _parse_csv_set(args.search_filter_fields),
    }
    if args.promote_rare_produces:
        options["promote_rare_produces"] = True
    if args.index_promoted_contract_fields:
        options["index_promoted_contract_fields"] = True
    return {key: value for key, value in options.items() if value}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swagger-url", default=DEFAULT_X2BEE_SWAGGER_URL)
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        help="Direct spec URL or local spec file. May be repeated. Skips Swagger discovery.",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="Snapshot manifest JSON from benchmarks.xgen_api_scale.snapshot. May be repeated.",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_X2BEE_CASES_PATH)
    parser.add_argument("--no-cases", action="store_true")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument(
        "--promote-contract-signals",
        action="store_true",
        help="Promote selected OpenAPI contract fields into retrieval metadata before graphing.",
    )
    parser.add_argument(
        "--compare-contract-signals",
        action="store_true",
        help="Build baseline/promoted graphs from the same loaded specs and compare search deltas.",
    )
    parser.add_argument(
        "--top-ks",
        default=None,
        help="Comma-separated top-K values to compare after one graph build, e.g. 3,5,10.",
    )
    parser.add_argument(
        "--acceptance-top-k",
        type=int,
        default=None,
        help="Top-K value whose thresholds determine sweep exit status.",
    )
    parser.add_argument("--no-detect-dependencies", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--min-spec-count", type=int, default=1)
    parser.add_argument("--min-unique-tools", type=int, default=1000)
    parser.add_argument("--max-build-seconds", type=float, default=30.0)
    parser.add_argument("--max-response-bytes", type=int, default=5_000_000)
    parser.add_argument("--allow-private-hosts", action="store_true")
    parser.add_argument(
        "--context-fields",
        default=None,
        help="Comma-separated field names to classify as ambient context during promotion.",
    )
    parser.add_argument(
        "--auth-fields",
        default=None,
        help="Comma-separated field names to classify as auth during promotion.",
    )
    parser.add_argument(
        "--paging-fields",
        default=None,
        help="Comma-separated paging field names for promotion.",
    )
    parser.add_argument(
        "--search-filter-fields",
        default=None,
        help="Comma-separated optional search/filter field names for promotion.",
    )
    parser.add_argument(
        "--user-input-fields",
        default=None,
        help="Comma-separated optional fields that should remain user-provided data.",
    )
    parser.add_argument(
        "--promote-rare-produces",
        action="store_true",
        help="Also promote rare non-identifier response fields. Diagnostic; may add noise.",
    )
    parser.add_argument(
        "--index-promoted-contract-fields",
        action="store_true",
        help="Index promoted raw contract fields in BM25. Diagnostic; may add target-search noise.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--gate-profile",
        default=DEFAULT_GATE_PROFILE,
        help="Gate profile to embed in acceptance/sweep reports.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    contract_signal_options = _contract_signal_options_from_args(args)
    spec_sources, snapshot_manifests = _spec_sources_from_args(args)

    if args.compare_contract_signals:
        report = run_contract_signal_ablation(
            swagger_url=args.swagger_url,
            spec_sources=spec_sources,
            cases_path=None if args.no_cases else args.cases,
            top_k=args.top_k,
            detect_dependencies=not args.no_detect_dependencies,
            min_confidence=args.min_confidence,
            min_spec_count=args.min_spec_count,
            min_unique_tools=args.min_unique_tools,
            max_build_seconds=args.max_build_seconds,
            max_response_bytes=args.max_response_bytes,
            allow_private_hosts=args.allow_private_hosts,
            contract_signal_options=contract_signal_options,
        )
    elif args.top_ks:
        report = run_top_k_sweep(
            swagger_url=args.swagger_url,
            spec_sources=spec_sources,
            cases_path=None if args.no_cases else args.cases,
            top_ks=_parse_top_ks(args.top_ks),
            acceptance_top_k=args.acceptance_top_k,
            detect_dependencies=not args.no_detect_dependencies,
            min_confidence=args.min_confidence,
            min_spec_count=args.min_spec_count,
            min_unique_tools=args.min_unique_tools,
            max_build_seconds=args.max_build_seconds,
            max_response_bytes=args.max_response_bytes,
            allow_private_hosts=args.allow_private_hosts,
            promote_contract_signals=args.promote_contract_signals,
            contract_signal_options=contract_signal_options,
        )
    else:
        report = run_benchmark(
            swagger_url=args.swagger_url,
            spec_sources=spec_sources,
            cases_path=None if args.no_cases else args.cases,
            top_k=args.top_k,
            detect_dependencies=not args.no_detect_dependencies,
            min_confidence=args.min_confidence,
            min_spec_count=args.min_spec_count,
            min_unique_tools=args.min_unique_tools,
            max_build_seconds=args.max_build_seconds,
            max_response_bytes=args.max_response_bytes,
            allow_private_hosts=args.allow_private_hosts,
            promote_contract_signals=args.promote_contract_signals,
            contract_signal_options=contract_signal_options,
        )
    if snapshot_manifests:
        report["snapshot_manifests"] = snapshot_manifests
    if "gate" in report:
        report["gate"] = evaluate_gate(report, profile=args.gate_profile)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.compare_contract_signals:
        _print_ablation_report(report)
    elif args.top_ks:
        _print_sweep_report(report)
    else:
        _print_report(report)
    return 0 if report["status"] == "pass" else 1


def _spec_sources_from_args(
    args: argparse.Namespace,
) -> tuple[list[str] | None, list[dict[str, Any]]]:
    sources: list[str] = []
    snapshot_manifests: list[dict[str, Any]] = []
    for manifest_path in args.manifest or []:
        manifest = load_snapshot_manifest(manifest_path)
        sources.extend(str(row["path"]) for row in manifest["specs"])
        snapshot_manifests.append(_snapshot_manifest_provenance(manifest))
    sources.extend(args.spec or [])
    return sources or None, snapshot_manifests


def _snapshot_manifest_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    spec_keys = [
        "index",
        "label",
        "source",
        "path",
        "sha256",
        "bytes",
        "title",
        "version",
        "openapi_version",
        "path_count",
        "operation_count",
    ]
    return {
        "snapshot": manifest.get("snapshot"),
        "manifest_path": manifest.get("manifest_path"),
        "created_at": manifest.get("created_at"),
        "graph_tool_call_version": manifest.get("graph_tool_call_version"),
        "source_url": manifest.get("source_url"),
        "spec_count": manifest.get("spec_count"),
        "operation_count": manifest.get("operation_count"),
        "path_count": manifest.get("path_count"),
        "specs_csv": manifest.get("specs_csv"),
        "specs": [
            {key: row.get(key) for key in spec_keys if key in row}
            for row in manifest.get("specs", [])
            if isinstance(row, dict)
        ],
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
