"""Deterministic OpenAPI collection readiness reporting.

The report in this module is intentionally static: it does not call an LLM,
does not execute API requests, and does not inspect runtime credentials. It
summarizes the OpenAPI facts already preserved on ``ToolSchema.metadata`` so
callers can decide whether an API collection is ready for graph search,
Planflow synthesis, and HTTP execution adapters.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Literal

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema

IssueSeverity = Literal["blocker", "warning", "info"]
ReadinessStatus = Literal["ready", "warning", "blocked"]

_HTTP_PREFIXES = ("http://", "https://")
_METHODS_WITH_BODY = {"post", "put", "patch", "delete"}
_NO_BODY_SUCCESS_STATUSES = {"204", "205", "304"}
_SUPPORTED_REQUEST_MEDIA_TYPES = {
    "*/*",
    "application/json",
    "application/octet-stream",
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
}
_SEVERITY_RANK = {"blocker": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class OpenAPIReadinessIssue:
    """One deterministic readiness issue for an OpenAPI collection."""

    severity: IssueSeverity
    code: str
    tool: str | None
    message: str
    evidence: dict[str, Any]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        """Convert the issue to a JSON-serializable dict."""
        return asdict(self)


@dataclass(frozen=True)
class OpenAPICollectionReport:
    """Serializable OpenAPI readiness report."""

    summary: dict[str, Any]
    coverage: dict[str, Any]
    graph_readiness: dict[str, Any]
    issues: list[OpenAPIReadinessIssue]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert the report to a JSON-serializable dict."""
        return {
            "summary": dict(self.summary),
            "coverage": dict(self.coverage),
            "graph_readiness": dict(self.graph_readiness),
            "issues": [issue.to_dict() for issue in self.issues],
            "recommendations": list(self.recommendations),
        }


def analyze_openapi_collection(
    source_or_tools: dict[str, Any] | str | Mapping[str, ToolSchema] | Sequence[ToolSchema],
    *,
    graph: GraphEngine | None = None,
    required_only: bool = False,
    skip_deprecated: bool = True,
    detect_dependencies: bool = True,
    min_confidence: float = 0.7,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
    context_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    paging_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    search_filter_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
) -> OpenAPICollectionReport:
    """Analyze an OpenAPI source or ingested tools for XGEN-style readiness.

    ``source_or_tools`` may be a raw OpenAPI dict, file path, URL, mapping of
    tool names to :class:`ToolSchema`, or a sequence of ``ToolSchema`` objects.
    URL loading uses the same private-host safety default as OpenAPI ingest.
    """

    tools, effective_graph = _coerce_tools_and_graph(
        source_or_tools,
        graph=graph,
        required_only=required_only,
        skip_deprecated=skip_deprecated,
        detect_dependencies=detect_dependencies,
        min_confidence=min_confidence,
        allow_private_hosts=allow_private_hosts,
        max_response_bytes=max_response_bytes,
    )
    return analyze_openapi_tools(
        tools,
        graph=effective_graph,
        context_field_names=context_field_names,
        paging_field_names=paging_field_names,
        search_filter_field_names=search_filter_field_names,
    )


def analyze_openapi_tools(
    tools: Mapping[str, ToolSchema] | Sequence[ToolSchema],
    *,
    graph: GraphEngine | None = None,
    context_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    paging_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    search_filter_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
) -> OpenAPICollectionReport:
    """Analyze already-ingested OpenAPI ``ToolSchema`` objects."""

    tool_list = _normalize_tools(tools)
    context_names = _canonical_names(context_field_names)
    paging_names = _canonical_names(paging_field_names)
    search_filter_names = _canonical_names(search_filter_field_names)

    coverage = _empty_coverage()
    issues: list[OpenAPIReadinessIssue] = []
    operation_ids: set[str] = set()
    deprecated_count = 0

    for tool in tool_list:
        metadata = _metadata(tool)
        openapi = _openapi(metadata)
        contract = _api_contract(metadata)
        if _is_openapi_operation(tool, metadata):
            operation_id = _operation_id(tool, openapi, metadata)
            if operation_id:
                operation_ids.add(operation_id)
        if openapi.get("deprecated"):
            deprecated_count += 1

        produces = _rows(contract.get("produces"))
        consumes = _rows(contract.get("consumes"))
        links = _rows(contract.get("links"))

        _update_coverage(
            coverage,
            tool=tool,
            openapi=openapi,
            produces=produces,
            consumes=consumes,
            links=links,
            context_names=context_names,
            paging_names=paging_names,
            search_filter_names=search_filter_names,
        )
        issues.extend(
            _tool_issues(
                tool,
                openapi,
                produces=produces,
                consumes=consumes,
                links=links,
            )
        )

    from graph_tool_call.graphify.semantics import summarize_openapi_semantics

    semantic_summary = summarize_openapi_semantics(tool_list)
    coverage.update(
        {
            "semantic_action_known_count": semantic_summary["canonical_action_known_count"],
            "semantic_action_known_rate": semantic_summary["canonical_action_known_rate"],
            "semantic_resource_assigned_count": semantic_summary["primary_resource_assigned_count"],
            "semantic_resource_assigned_rate": semantic_summary["primary_resource_assigned_rate"],
            "semantic_module_assigned_count": semantic_summary["path_module_assigned_count"],
            "semantic_module_assigned_rate": semantic_summary["path_module_assigned_rate"],
            "semantic_confidence_counts": semantic_summary["semantic_confidence_counts"],
            "semantic_unknown_samples": semantic_summary["unknown_samples"],
        }
    )

    graph_readiness = _graph_readiness(graph, tool_list)
    issues.extend(_graph_issues(graph_readiness, tool_count=len(tool_list)))
    issues.extend(_semantic_issues(semantic_summary))
    issues.extend(_edge_quality_issues(graph_readiness))
    issues.sort(key=lambda issue: (_SEVERITY_RANK[issue.severity], issue.tool or "", issue.code))

    blocker_count = sum(1 for issue in issues if issue.severity == "blocker")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    score = max(0, min(100, 100 - blocker_count * 15 - warning_count * 5))
    status: ReadinessStatus
    if blocker_count:
        status = "blocked"
    elif warning_count or score < 90:
        status = "warning"
    else:
        status = "ready"

    summary = {
        "tool_count": len(tool_list),
        "operation_count": sum(
            1 for tool in tool_list if _is_openapi_operation(tool, _metadata(tool))
        ),
        "unique_tool_count": len({tool.name for tool in tool_list}),
        "unique_operation_count": len(operation_ids),
        "deprecated_tool_count": deprecated_count,
        "readiness_score": score,
        "status": status,
    }
    recommendations = _recommendations(issues)
    return OpenAPICollectionReport(
        summary=summary,
        coverage=coverage,
        graph_readiness=graph_readiness,
        issues=issues,
        recommendations=recommendations,
    )


def _coerce_tools_and_graph(
    source_or_tools: dict[str, Any] | str | Mapping[str, ToolSchema] | Sequence[ToolSchema],
    *,
    graph: GraphEngine | None,
    required_only: bool,
    skip_deprecated: bool,
    detect_dependencies: bool,
    min_confidence: float,
    allow_private_hosts: bool,
    max_response_bytes: int,
) -> tuple[list[ToolSchema], GraphEngine | None]:
    if isinstance(source_or_tools, str):
        from graph_tool_call import ToolGraph

        if source_or_tools.startswith(_HTTP_PREFIXES):
            tg = ToolGraph.from_url(
                source_or_tools,
                required_only=required_only,
                skip_deprecated=skip_deprecated,
                detect_dependencies=detect_dependencies,
                min_confidence=min_confidence,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )
        else:
            tg = ToolGraph()
            tg.ingest_openapi(
                source_or_tools,
                required_only=required_only,
                skip_deprecated=skip_deprecated,
                detect_dependencies=detect_dependencies,
                min_confidence=min_confidence,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )
        return list(tg.tools.values()), graph or tg.graph

    if isinstance(source_or_tools, dict) and _looks_like_openapi_spec(source_or_tools):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.ingest_openapi(
            source_or_tools,
            required_only=required_only,
            skip_deprecated=skip_deprecated,
            detect_dependencies=detect_dependencies,
            min_confidence=min_confidence,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
        return list(tg.tools.values()), graph or tg.graph

    return _normalize_tools(source_or_tools), graph


def _normalize_tools(tools: Mapping[str, ToolSchema] | Sequence[ToolSchema]) -> list[ToolSchema]:
    values: Any
    if isinstance(tools, Mapping):
        values = list(tools.values())
    else:
        values = list(tools)
    if not all(isinstance(tool, ToolSchema) for tool in values):
        msg = "tools must be ToolSchema objects or a raw OpenAPI spec dict"
        raise TypeError(msg)
    return list(values)


def _looks_like_openapi_spec(value: dict[str, Any]) -> bool:
    return "paths" in value and ("openapi" in value or "swagger" in value)


def _empty_coverage() -> dict[str, Any]:
    return {
        "request_body_tool_count": 0,
        "request_schema_tool_count": 0,
        "response_schema_tool_count": 0,
        "consumes_field_count": 0,
        "produces_field_count": 0,
        "auth_field_count": 0,
        "context_field_count": 0,
        "enum_field_count": 0,
        "example_inferred_field_count": 0,
        "response_envelope_tool_count": 0,
        "body_view_candidate_count": 0,
        "openapi_link_count": 0,
    }


def _update_coverage(
    coverage: dict[str, int],
    *,
    tool: ToolSchema,
    openapi: dict[str, Any],
    produces: list[dict[str, Any]],
    consumes: list[dict[str, Any]],
    links: list[dict[str, Any]],
    context_names: set[str],
    paging_names: set[str],
    search_filter_names: set[str],
) -> None:
    request_body = _dict(openapi.get("request_body"))
    response = _dict(openapi.get("response"))
    if _has_request_body(request_body):
        coverage["request_body_tool_count"] += 1
    if _dict(request_body.get("schema")) or _rows(request_body.get("fields")):
        coverage["request_schema_tool_count"] += 1
    if (
        _dict(response.get("schema"))
        or _rows(response.get("fields"))
        or _rows(response.get("headers"))
    ):
        coverage["response_schema_tool_count"] += 1
    if _dict(response.get("envelope")):
        coverage["response_envelope_tool_count"] += 1

    coverage["consumes_field_count"] += len(consumes)
    coverage["produces_field_count"] += len(produces)
    coverage["openapi_link_count"] += len(links)

    for row in [*produces, *consumes]:
        if isinstance(row.get("enum"), list) and row["enum"]:
            coverage["enum_field_count"] += 1
        if _is_example_inferred(row):
            coverage["example_inferred_field_count"] += 1

    for row in consumes:
        kind = _classified_consume_kind(
            row,
            context_names=context_names,
            paging_names=paging_names,
            search_filter_names=search_filter_names,
        )
        if kind == "auth":
            coverage["auth_field_count"] += 1
        elif kind == "context":
            coverage["context_field_count"] += 1

    for row in produces:
        if _is_body_view_candidate(row):
            coverage["body_view_candidate_count"] += 1

    # Keep linters honest when only top-level metadata matters in future edits.
    _ = tool


def _tool_issues(
    tool: ToolSchema,
    openapi: dict[str, Any],
    *,
    produces: list[dict[str, Any]],
    consumes: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[OpenAPIReadinessIssue]:
    issues: list[OpenAPIReadinessIssue] = []
    method = str(_metadata(tool).get("method") or "").lower()
    path = str(_metadata(tool).get("path") or "")
    request_body = _dict(openapi.get("request_body"))
    response = _dict(openapi.get("response"))

    if openapi.get("operation_id_generated"):
        issues.append(
            _issue(
                "warning",
                "missing_operation_id",
                tool.name,
                "OperationId was generated from method and path.",
                {"method": method, "path": path, "operation_id": openapi.get("operation_id")},
                "Add a stable operationId so tool names and saved plans stay stable.",
            )
        )

    if openapi.get("operation_id_duplicate"):
        issues.append(
            _issue(
                "warning",
                "duplicate_operation_id",
                tool.name,
                "OperationId is duplicated and the tool name was deduped.",
                {
                    "operation_id": openapi.get("operation_id"),
                    "duplicate_count": openapi.get("operation_id_duplicate_count"),
                    "duplicate_index": openapi.get("operation_id_duplicate_index"),
                    "deduped_name": openapi.get("operation_id_deduped_name"),
                },
                "Make operationId values unique, or use operationRef for ambiguous OpenAPI links.",
            )
        )

    issues.extend(_request_body_issues(tool.name, method, path, request_body))
    issues.extend(_response_issues(tool.name, method, path, response))
    issues.extend(_auth_issues(tool.name, consumes))
    issues.extend(_content_type_issues(tool.name, request_body))
    issues.extend(_array_alignment_issues(tool.name, request_body))

    if _dict(response.get("envelope")):
        issues.append(
            _issue(
                "info",
                "response_envelope_detected",
                tool.name,
                "Success response appears to use a wrapper envelope.",
                {"envelope": response.get("envelope")},
                "Keep body_view/value-path metadata when forwarding runtime responses.",
            )
        )

    if not produces and not consumes and not links:
        issues.append(
            _issue(
                "warning",
                "no_contract_fields",
                tool.name,
                "No request, response, auth, or link contract fields were extracted.",
                {"method": method, "path": path},
                "Add request/response schemas or examples so graph search has contract evidence.",
            )
        )

    return issues


def _request_body_issues(
    tool_name: str,
    method: str,
    path: str,
    request_body: dict[str, Any],
) -> list[OpenAPIReadinessIssue]:
    if not _has_request_body(request_body):
        return []
    required = bool(request_body.get("required"))
    schema = _dict(request_body.get("schema"))
    content_types = _rows(request_body.get("content_types"))

    if required and not schema and content_types:
        return [
            _issue(
                "blocker",
                "missing_request_schema",
                tool_name,
                "Required request body declares content but no schema.",
                {
                    "method": method,
                    "path": path,
                    "content_types": _content_type_names(content_types),
                },
                "Add a requestBody schema or concrete request examples for executable fields.",
            )
        ]

    if _is_generic_object_schema(schema):
        example_count = sum(len(_rows(row.get("example_fields"))) for row in content_types)
        severity: IssueSeverity = "warning" if example_count else "blocker"
        return [
            _issue(
                severity,
                "generic_request_body",
                tool_name,
                "Request body schema is a generic object without declared properties.",
                {
                    "method": method,
                    "path": path,
                    "required": required,
                    "example_field_count": example_count,
                },
                (
                    "Declare body properties in schema; examples are useful but should not "
                    "be the only contract."
                ),
            )
        ]

    return []


def _response_issues(
    tool_name: str,
    method: str,
    path: str,
    response: dict[str, Any],
) -> list[OpenAPIReadinessIssue]:
    status = str(response.get("status") or "")
    if _success_status_can_skip_body(status):
        return []
    schema = _dict(response.get("schema"))
    fields = _rows(response.get("fields"))
    headers = _rows(response.get("headers"))
    if schema or fields or headers:
        return []
    return [
        _issue(
            "warning",
            "missing_response_schema",
            tool_name,
            "No success response schema or response fields were extracted.",
            {"method": method, "path": path, "status": status or None},
            (
                "Add a 2xx response schema or examples so producer search and plan binding "
                "can use outputs."
            ),
        )
    ]


def _auth_issues(tool_name: str, consumes: list[dict[str, Any]]) -> list[OpenAPIReadinessIssue]:
    rows = [
        row
        for row in consumes
        if _classified_consume_kind(
            row,
            context_names=set(),
            paging_names=set(),
            search_filter_names=set(),
        )
        == "auth"
        and bool(row.get("security_required"))
    ]
    if not rows:
        return []
    return [
        _issue(
            "warning",
            "auth_required",
            tool_name,
            "OpenAPI security is required for execution.",
            {
                "schemes": sorted(
                    {
                        str(scheme)
                        for row in rows
                        for scheme in (row.get("security_schemes") or [row.get("security_scheme")])
                        if scheme
                    }
                ),
                "credentials": sorted(
                    {str(row.get("credential_name") or row.get("field_name")) for row in rows}
                ),
            },
            (
                "Provide credentials in the XGEN adapter or executor layer; do not store "
                "secrets in the graph."
            ),
        )
    ]


def _content_type_issues(
    tool_name: str,
    request_body: dict[str, Any],
) -> list[OpenAPIReadinessIssue]:
    issues: list[OpenAPIReadinessIssue] = []
    for row in _rows(request_body.get("content_types")):
        content_type = str(row.get("content_type") or "").strip()
        if not content_type or _is_supported_request_media_type(content_type):
            continue
        issues.append(
            _issue(
                "warning",
                "unsupported_content_type",
                tool_name,
                "Request body declares a media type outside the built-in executor renderers.",
                {"content_type": content_type},
                (
                    "Add an adapter renderer for this media type or prefer "
                    "JSON/form/multipart/raw body."
                ),
            )
        )
    return issues


def _array_alignment_issues(
    tool_name: str,
    request_body: dict[str, Any],
) -> list[OpenAPIReadinessIssue]:
    array_paths = sorted(
        {
            str(row.get("json_path") or "")
            for row in [
                *_rows(request_body.get("fields")),
                *_rows(request_body.get("all_fields")),
            ]
            if "[*]" in str(row.get("json_path") or "")
        }
    )
    if not array_paths:
        return []
    return [
        _issue(
            "info",
            "array_leaf_alignment_required",
            tool_name,
            "Request body contains array leaf fields that require row-wise alignment.",
            {"array_paths": array_paths},
            (
                "Forward array diagnostics from HttpExecutor so missing indexes can be "
                "resumed precisely."
            ),
        )
    ]


def _graph_readiness(graph: GraphEngine | None, tools: list[ToolSchema]) -> dict[str, Any]:
    from graph_tool_call.graphify.semantics import summarize_edge_quality

    relation_counts: dict[str, int] = {}
    producer_edge_count = 0
    orphan_tools: list[str] = []
    if graph is not None:
        for _source, _target, attrs in graph.edges():
            relation = _label(attrs.get("relation", "unknown")).lower()
            relation_counts[relation] = relation_counts.get(relation, 0) + 1
            if relation in {"requires", "precedes", "produces_for"} or attrs.get("data_flow"):
                producer_edge_count += 1
        for tool in tools:
            if graph.has_node(tool.name) and not graph.get_neighbors(tool.name, direction="both"):
                orphan_tools.append(tool.name)

    candidate_count = _producer_consumer_candidate_count(tools)
    edge_quality_summary = summarize_edge_quality(graph)
    return {
        "edge_count": graph.edge_count() if graph is not None else 0,
        "relation_counts": dict(sorted(relation_counts.items())),
        "producer_edge_count": producer_edge_count,
        "orphan_tool_count": len(orphan_tools),
        "isolated_tool_count": len(orphan_tools),
        "orphan_tools": sorted(orphan_tools),
        "producer_consumer_candidate_count": candidate_count,
        "graph_available": graph is not None,
        "edge_quality_summary": edge_quality_summary,
    }


def _graph_issues(
    graph_readiness: dict[str, Any],
    *,
    tool_count: int,
) -> list[OpenAPIReadinessIssue]:
    if not graph_readiness.get("graph_available") or tool_count <= 1:
        return []
    if (
        graph_readiness.get("producer_consumer_candidate_count", 0) > 0
        and graph_readiness.get("producer_edge_count", 0) == 0
    ):
        return [
            _issue(
                "warning",
                "low_graph_connectivity",
                None,
                "Contract fields suggest producer/consumer pairs, but no data-flow edges exist.",
                {
                    "producer_consumer_candidate_count": graph_readiness[
                        "producer_consumer_candidate_count"
                    ],
                    "edge_count": graph_readiness["edge_count"],
                },
                (
                    "Enable graphify contract promotion or relink the collection before "
                    "Planflow rollout."
                ),
            )
        ]
    if graph_readiness.get("orphan_tool_count", 0) == tool_count and tool_count > 1:
        return [
            _issue(
                "warning",
                "low_graph_connectivity",
                None,
                "All tools are isolated in the graph.",
                {"orphan_tool_count": graph_readiness["orphan_tool_count"]},
                (
                    "Run dependency detection or graphify ingestion so retrieval can use "
                    "graph expansion."
                ),
            )
        ]
    return []


def _semantic_issues(semantic_summary: dict[str, Any]) -> list[OpenAPIReadinessIssue]:
    tool_count = int(semantic_summary.get("tool_count") or 0)
    if tool_count <= 1:
        return []

    issues: list[OpenAPIReadinessIssue] = []
    action_rate = float(semantic_summary.get("canonical_action_known_rate") or 0.0)
    resource_rate = float(semantic_summary.get("primary_resource_assigned_rate") or 0.0)
    module_rate = float(semantic_summary.get("path_module_assigned_rate") or 0.0)
    unknown_samples = list(semantic_summary.get("unknown_samples") or [])[:10]
    if action_rate < 0.9:
        issues.append(
            _issue(
                "warning",
                "semantic_action_unknown_rate_high",
                None,
                "Canonical action coverage is below the XGEN semantic graph target.",
                {
                    "canonical_action_known_rate": action_rate,
                    "target": 0.9,
                    "unknown_samples": unknown_samples,
                },
                (
                    "Add operationId verbs, summaries, or adapter action_aliases so search "
                    "can distinguish search/read/write/action tools."
                ),
            )
        )
    if resource_rate < 0.75:
        issues.append(
            _issue(
                "warning",
                "semantic_resource_unassigned_rate_high",
                None,
                "Primary resource coverage is below the XGEN semantic graph target.",
                {
                    "primary_resource_assigned_rate": resource_rate,
                    "target": 0.75,
                    "unknown_samples": unknown_samples,
                },
                (
                    "Use tags, stable path modules, or adapter resource_aliases so the graph "
                    "can cluster tools by business resource."
                ),
            )
        )
    top_modules = semantic_summary.get("top_modules") or []
    largest = top_modules[0] if top_modules and isinstance(top_modules[0], dict) else {}
    largest_rate = float(largest.get("rate") or 0.0)
    if tool_count >= 100 and (largest_rate >= 0.5 or module_rate < 0.95):
        issues.append(
            _issue(
                "info",
                "module_cluster_too_large",
                None,
                "One module cluster is large enough to reduce graph browsing value.",
                {
                    "largest_module": largest,
                    "path_module_assigned_rate": module_rate,
                },
                (
                    "Pass module_aliases or improve path grouping so XGEN can show smaller "
                    "collection map clusters before rendering node-level graphs."
                ),
            )
        )
    return issues


def _edge_quality_issues(graph_readiness: dict[str, Any]) -> list[OpenAPIReadinessIssue]:
    edge_count = int(graph_readiness.get("edge_count") or 0)
    if edge_count <= 0:
        return []
    quality = (
        graph_readiness.get("edge_quality_summary")
        if isinstance(graph_readiness.get("edge_quality_summary"), dict)
        else {}
    )
    strong = int(quality.get("strong_deterministic_evidence") or 0)
    if strong > 0:
        return []
    return [
        _issue(
            "warning",
            "weak_edge_evidence",
            None,
            "Graph has edges, but none carry strong deterministic evidence.",
            {"edge_count": edge_count, "edge_quality_summary": quality},
            (
                "Prefer api_contract/openapi_link/manual/run evidence for Planflow graph "
                "edges and keep name-based edges as low-trust expansion hints."
            ),
        )
    ]


def _producer_consumer_candidate_count(tools: list[ToolSchema]) -> int:
    producer_keys: set[tuple[str, str]] = set()
    producer_names: dict[tuple[str, str], set[str]] = {}
    for tool in tools:
        for row in _rows(_api_contract(_metadata(tool)).get("produces")):
            for key in _field_keys(row):
                producer_keys.add(key)
                producer_names.setdefault(key, set()).add(tool.name)

    count = 0
    for tool in tools:
        for row in _rows(_api_contract(_metadata(tool)).get("consumes")):
            if (
                _classified_consume_kind(
                    row,
                    context_names=set(),
                    paging_names=set(),
                    search_filter_names=set(),
                )
                != "data"
            ):
                continue
            if not bool(row.get("required")) and str(row.get("location") or "") != "path":
                continue
            for key in _field_keys(row):
                if key in producer_keys and any(name != tool.name for name in producer_names[key]):
                    count += 1
                    break
    return count


def _field_keys(row: dict[str, Any]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    semantic = str(row.get("semantic_tag") or "").strip()
    field = str(row.get("field_name") or "").strip()
    if semantic:
        keys.append(("semantic", _canonical_key(semantic)))
    if field:
        keys.append(("field", _canonical_key(field)))
    return [key for key in keys if key[1]]


def _recommendations(issues: list[OpenAPIReadinessIssue]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        text = issue.recommendation
        if text not in seen:
            ordered.append(text)
            seen.add(text)
    if not ordered:
        ordered.append("Collection is ready for graph search and Planflow smoke testing.")
    return ordered


def _issue(
    severity: IssueSeverity,
    code: str,
    tool: str | None,
    message: str,
    evidence: dict[str, Any],
    recommendation: str,
) -> OpenAPIReadinessIssue:
    return OpenAPIReadinessIssue(
        severity=severity,
        code=code,
        tool=tool,
        message=message,
        evidence=evidence,
        recommendation=recommendation,
    )


def _metadata(tool: ToolSchema) -> dict[str, Any]:
    return tool.metadata if isinstance(tool.metadata, dict) else {}


def _openapi(metadata: dict[str, Any]) -> dict[str, Any]:
    openapi = _dict(metadata.get("openapi"))
    if openapi:
        return openapi
    if not _looks_like_persisted_openapi_metadata(metadata):
        return {}

    contract = _api_contract(metadata)
    consumes = _rows(contract.get("consumes"))
    produces = _rows(contract.get("produces"))
    links = _rows(contract.get("links"))
    request_body_fields = [
        row for row in consumes if str(row.get("location") or "").lower() == "body"
    ]
    parameter_rows = [
        _parameter_row_from_contract(row)
        for row in consumes
        if str(row.get("location") or "").lower() in {"path", "query", "header", "cookie"}
        and str(row.get("kind") or "data").lower() != "auth"
    ]
    response_fields = [
        row
        for row in produces
        if str(row.get("location") or "response").lower() != "response_header"
    ]
    response_headers = [
        row for row in produces if str(row.get("location") or "").lower() == "response_header"
    ]

    return {
        "tool_name": metadata.get("tool_name") or metadata.get("name") or "",
        "operation_id": metadata.get("operation_id") or metadata.get("operationId") or "",
        "summary": metadata.get("summary") or "",
        "description": metadata.get("description") or "",
        "deprecated": bool(metadata.get("deprecated", False)),
        "parameters": parameter_rows,
        "request_body": {
            "required": any(bool(row.get("required")) for row in request_body_fields),
            "fields": request_body_fields,
            "all_fields": request_body_fields,
        },
        "response": {
            "status": metadata.get("response_status") or metadata.get("status") or "",
            "fields": response_fields,
            **({"headers": response_headers} if response_headers else {}),
            **({"links": links} if links else {}),
        },
    }


def _looks_like_persisted_openapi_metadata(metadata: dict[str, Any]) -> bool:
    if str(metadata.get("source") or "").lower() == "openapi":
        return True
    if metadata.get("method") and metadata.get("path"):
        return True
    return False


def _parameter_row_from_contract(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "name": str(row.get("field_name") or row.get("name") or ""),
        "in": str(row.get("location") or row.get("in") or ""),
        "required": bool(row.get("required")),
        "field_type": str(row.get("field_type") or "string"),
    }
    for key in (
        "json_path",
        "enum",
        "description",
        "schema_expanded_from",
        "schema_expansion",
        "content_type",
        "style",
        "explode",
        "allowReserved",
    ):
        value = row.get(key)
        if value not in (None, "", []):
            out[key] = value
    return out


def _operation_id(tool: ToolSchema, openapi: dict[str, Any], metadata: dict[str, Any]) -> str:
    return str(
        openapi.get("operation_id")
        or metadata.get("operation_id")
        or metadata.get("operationId")
        or openapi.get("tool_name")
        or metadata.get("tool_name")
        or tool.name
        or ""
    ).strip()


def _is_openapi_operation(tool: ToolSchema, metadata: dict[str, Any]) -> bool:
    openapi = _openapi(metadata)
    if openapi:
        return True
    return _operation_id(tool, openapi, metadata) != "" and _looks_like_persisted_openapi_metadata(
        metadata
    )


def _api_contract(metadata: dict[str, Any]) -> dict[str, Any]:
    return _dict(metadata.get("api_contract"))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _has_request_body(request_body: dict[str, Any]) -> bool:
    return bool(
        request_body.get("required")
        or _dict(request_body.get("schema"))
        or _rows(request_body.get("content_types"))
        or _rows(request_body.get("fields"))
        or _rows(request_body.get("all_fields"))
        or _dict(request_body.get("root"))
    )


def _is_generic_object_schema(schema: dict[str, Any]) -> bool:
    if not schema:
        return False
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)
    if schema_type not in (None, "object"):
        return False
    structural_keys = (
        "properties",
        "additionalProperties",
        "items",
        "oneOf",
        "anyOf",
        "allOf",
    )
    return not any(schema.get(key) for key in structural_keys)


def _success_status_can_skip_body(status: str) -> bool:
    if not status:
        return False
    upper = status.upper()
    return upper in _NO_BODY_SUCCESS_STATUSES or upper.startswith("3")


def _content_type_names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("content_type")) for row in rows if row.get("content_type")]


def _is_supported_request_media_type(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media in _SUPPORTED_REQUEST_MEDIA_TYPES or media.endswith("+json")


def _is_example_inferred(row: dict[str, Any]) -> bool:
    return bool(
        row.get("schema_inferred_from") == "example"
        or row.get("example_source")
        or row.get("example_name")
    )


def _is_body_view_candidate(row: dict[str, Any]) -> bool:
    return bool(
        row.get("response_envelope_path")
        or row.get("response_collection_path")
        or row.get("response_item_path")
        or row.get("value_path_aliases")
    )


def _classified_consume_kind(
    row: dict[str, Any],
    *,
    context_names: set[str],
    paging_names: set[str],
    search_filter_names: set[str],
) -> str:
    raw_kind = str(row.get("kind") or "").strip().lower()
    if raw_kind == "auth" or row.get("security_scheme") or row.get("security_schemes"):
        return "auth"
    field_name = str(row.get("field_name") or "")
    if (
        raw_kind == "context"
        or _matches(field_name, context_names)
        or _matches(field_name, paging_names)
    ):
        return "context"
    if _matches(field_name, search_filter_names):
        return "data"
    return raw_kind if raw_kind in {"data", "context", "auth"} else "data"


def _canonical_names(values: set[str] | list[str] | tuple[str, ...] | None) -> set[str]:
    return {_canonical_key(value) for value in values or [] if _canonical_key(value)}


def _matches(field_name: str, names: set[str]) -> bool:
    key = _canonical_key(field_name)
    return bool(key and key in names)


def _canonical_key(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _label(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


__all__ = [
    "OpenAPICollectionReport",
    "OpenAPIReadinessIssue",
    "analyze_openapi_collection",
    "analyze_openapi_tools",
]
