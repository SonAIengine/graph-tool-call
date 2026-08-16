"""Merge explicit Arazzo workflow evidence into a tool graph.

Only operation names, step identifiers, dependency kinds, and response-path
bindings are persisted. Runtime parameter values and API payloads are never
copied into the graph artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from graph_tool_call.graphify.edges import (
    EVIDENCE_ARAZZO,
    merge_graph_edges,
    normalize_graph_edge,
)
from graph_tool_call.ingest.arazzo import ArazzoRelation, _load_spec, ingest_arazzo
from graph_tool_call.ontology.schema import Confidence, RelationType
from graph_tool_call.tool_graph import ToolGraph


def apply_arazzo_workflows(
    graph: ToolGraph,
    sources: dict[str, Any] | str | Sequence[dict[str, Any] | str],
    *,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """Apply one or more Arazzo descriptions as extracted workflow evidence."""

    requested = _requested_sources(sources)
    resolver = _operation_resolver(graph)
    relations: list[ArazzoRelation] = []
    manifests: list[dict[str, Any]] = []
    workflow_count = 0
    step_count = 0

    for index, source in enumerate(requested, start=1):
        spec = (
            source
            if isinstance(source, dict)
            else _load_spec(
                source,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )
        )
        canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        workflows = [row for row in spec.get("workflows") or [] if isinstance(row, dict)]
        workflow_count += len(workflows)
        step_count += sum(
            len([step for step in workflow.get("steps") or [] if isinstance(step, dict)])
            for workflow in workflows
        )
        manifests.append(
            {
                "index": index,
                "source": (
                    f"inline:{index}" if isinstance(source, dict) else _safe_source_label(source)
                ),
                "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "bytes": len(canonical.encode("utf-8")),
                "arazzo_version": str(spec.get("arazzo") or ""),
                "workflow_count": len(workflows),
            }
        )
        relations.extend(
            ingest_arazzo(
                spec,
                registered_tools=set(graph.tools),
                operation_resolver=resolver,
            )
        )

    edge_stats = apply_arazzo_relations(graph, relations)
    return {
        "source_count": len(requested),
        "workflow_count": workflow_count,
        "step_count": step_count,
        "relation_count": len(relations),
        "by_dependency_kind": dict(
            sorted(Counter(relation.dependency_kind for relation in relations).items())
        ),
        "edge_stats": edge_stats,
        "source_snapshot_manifest": {
            "spec_count": len(manifests),
            "specs": manifests,
        },
    }


def apply_arazzo_relations(
    graph: ToolGraph,
    relations: Sequence[ArazzoRelation],
) -> dict[str, int]:
    """Apply parsed relations while preserving graphify evidence metadata."""

    stats = {"added": 0, "merged": 0, "binding_aliases_added": 0}
    for relation in relations:
        bindings = [dict(binding) for binding in relation.bindings]
        incoming = normalize_graph_edge(
            {
                "source": relation.source,
                "target": relation.target,
                "relation": RelationType.PRECEDES,
                "confidence": Confidence.EXTRACTED,
                "conf_score": 1.0 if relation.dependency_kind != "sequential" else 0.95,
                "layer": 1,
                "evidence": (
                    f"arazzo workflow {relation.workflow}: "
                    f"{relation.source_step} -> {relation.target_step} "
                    f"({relation.dependency_kind})"
                ),
                "kind": "data" if bindings else "workflow",
                "evidence_sources": [EVIDENCE_ARAZZO],
                "execution_direction": "source_to_target",
                "data_flow": {
                    "workflow_id": relation.workflow,
                    "source_step_id": relation.source_step,
                    "target_step_id": relation.target_step,
                    "dependency_kind": relation.dependency_kind,
                    "from_operation": relation.source,
                    "to_operation": relation.target,
                    "parameters": bindings,
                    **_primary_binding(bindings),
                },
            },
            default_source=EVIDENCE_ARAZZO,
        )
        if graph.graph.has_edge(relation.source, relation.target):
            existing = graph.graph.get_edge_attrs(relation.source, relation.target)
            merged = merge_graph_edges(
                {"source": relation.source, "target": relation.target, **existing},
                incoming,
            )
            merged["execution_direction"] = "source_to_target"
            _put_edge(graph, relation.source, relation.target, merged)
            stats["merged"] += 1
        else:
            _put_edge(graph, relation.source, relation.target, incoming)
            stats["added"] += 1
        for binding in bindings:
            stats["binding_aliases_added"] += _promote_binding_alias(
                graph,
                producer=relation.source,
                binding=binding,
                relation=relation,
            )
    return stats


def _promote_binding_alias(
    graph: ToolGraph,
    *,
    producer: str,
    binding: dict[str, Any],
    relation: ArazzoRelation,
) -> int:
    field_name = str(binding.get("target_field") or "").strip()
    json_path = str(binding.get("source_path") or "").strip()
    if not field_name or not json_path or producer not in graph.tools:
        return 0
    tool = graph.tools[producer]
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    tool.metadata = metadata
    produces = metadata.setdefault("produces", [])
    if not isinstance(produces, list):
        produces = []
        metadata["produces"] = produces
    if any(
        isinstance(row, dict)
        and str(row.get("field_name") or "") == field_name
        and str(row.get("json_path") or "") == json_path
        for row in produces
    ):
        return 0
    consumer_contract = _consumer_contract_row(graph, relation.target, field_name)
    # Explicit Arazzo runtime bindings outrank generic OpenAPI leaf paths for
    # the same consumer field. PathSynthesizer preserves produces order when
    # resolving a field, so keep the workflow alias first.
    produces.insert(
        0,
        {
            "field_name": field_name,
            "json_path": json_path,
            "field_type": str(consumer_contract.get("field_type") or "string"),
            "required": False,
            "kind": "data",
            "search_signal": False,
            "contract_source": EVIDENCE_ARAZZO,
            "arazzo_workflow_id": relation.workflow,
            "arazzo_source_step_id": relation.source_step,
            "arazzo_source_output": binding.get("source_output"),
            **(
                {"semantic_tag": consumer_contract["semantic_tag"]}
                if consumer_contract.get("semantic_tag")
                else {}
            ),
        },
    )
    return 1


def _consumer_contract_row(graph: ToolGraph, consumer: str, field_name: str) -> dict[str, Any]:
    tool = graph.tools.get(consumer)
    if tool is None:
        return {}
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    for row in metadata.get("consumes") or []:
        if isinstance(row, dict) and str(row.get("field_name") or "") == field_name:
            return row
    return {}


def _operation_resolver(graph: ToolGraph):
    operation_ids: dict[str, str] = {}
    operation_refs: dict[str, str] = {}
    for name, tool in graph.tools.items():
        metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
        openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        operation_id = str(openapi.get("operation_id") or name).strip()
        if operation_id and operation_id not in operation_ids:
            operation_ids[operation_id] = name
        path = str(metadata.get("path") or openapi.get("path") or "").strip()
        method = str(metadata.get("method") or openapi.get("method") or "").strip().lower()
        if path and method:
            escaped = path.replace("~", "~0").replace("/", "~1")
            operation_refs[f"#/paths/{escaped}/{method}"] = name

    def resolve(step: dict[str, Any]) -> str | None:
        operation_id = str(step.get("operationId") or "").strip()
        if operation_id.startswith("$sourceDescriptions."):
            operation_id = operation_id.rsplit(".", 1)[-1]
        if operation_id:
            return operation_ids.get(operation_id, operation_id)
        operation_path = str(step.get("operationPath") or "").strip()
        if "#" in operation_path:
            operation_path = "#" + operation_path.split("#", 1)[1]
        return operation_refs.get(operation_path)

    return resolve


def _primary_binding(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    if not bindings:
        return {}
    binding = bindings[0]
    return {
        "from_path": binding.get("source_path") or "",
        "from_field": binding.get("source_output") or "",
        "to_field": binding.get("target_field") or "",
    }


def _put_edge(graph: ToolGraph, source: str, target: str, edge: dict[str, Any]) -> None:
    graph.graph.add_edge(
        source,
        target,
        **{key: value for key, value in edge.items() if key not in {"source", "target"}},
    )


def _requested_sources(
    source: dict[str, Any] | str | Sequence[dict[str, Any] | str],
) -> list[dict[str, Any] | str]:
    if isinstance(source, (dict, str)):
        return [source]
    values = list(source)
    if not values:
        raise ValueError("workflow sources must not be empty")
    if not all(isinstance(item, (dict, str)) for item in values):
        raise TypeError("workflow sources must contain only Arazzo dicts or string sources")
    return values


def _safe_source_label(source: str) -> str:
    value = str(source or "")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    return Path(value).name


__all__ = ["apply_arazzo_relations", "apply_arazzo_workflows"]
