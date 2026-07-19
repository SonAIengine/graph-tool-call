"""Build persisted OpenAPI collection artifacts for product adapters.

The helpers in this module are product-neutral. They assemble the public
graphify/readiness pieces into one JSON-serializable payload that a product such
as XGEN can store as an API Collection build artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_tool_call.analyze.openapi_readiness import analyze_openapi_tools
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify.ingest import ingest_openapi_graphify
from graph_tool_call.graphify.metadata import (
    COLLECTION_GRAPH_VERSION,
    annotate_graphify_metadata,
)
from graph_tool_call.ingest.openapi import _load_spec, ingest_openapi
from graph_tool_call.tool_graph import _discover_spec_urls

_HTTP_PREFIXES = ("http://", "https://")
_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


@dataclass(frozen=True)
class _LoadedOpenAPISpec:
    source: str
    label: str
    spec: dict[str, Any]


def build_openapi_collection_artifact(
    source: dict[str, Any] | str | Sequence[dict[str, Any] | str],
    *,
    required_only: bool = False,
    skip_deprecated: bool = True,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
    promote_contract_signals: bool = True,
    contract_signal_options: dict[str, Any] | None = None,
    max_contract_producers_per_field: int = 3,
    user_input_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    context_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    auth_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    paging_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    search_filter_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    collection_graph_version: str = COLLECTION_GRAPH_VERSION,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a storage-ready OpenAPI/API Collection graph artifact.

    The returned dict uses the normal ``ToolGraph.save`` JSON shape
    (``graph`` + ``tools`` + ``metadata``) and adds product-facing build facts:
    ``readiness_report``, ``source_snapshot_manifest``, ``ingest_summary``, and
    ``edge_stats``. ``ToolGraph.load`` can still read the artifact because the
    added fields are top-level metadata extensions.

    Remote Swagger UI URLs use the same spec discovery as ``ToolGraph.from_url``.
    Runtime credentials, DB IDs, auth tokens, and UI state are intentionally out
    of scope for this helper.
    """

    loaded_specs = _load_openapi_collection_sources(
        source,
        allow_private_hosts=allow_private_hosts,
        max_response_bytes=max_response_bytes,
    )
    unique_tools, ingest_summary = _ingest_unique_tools(
        loaded_specs,
        required_only=required_only,
        skip_deprecated=skip_deprecated,
        allow_private_hosts=allow_private_hosts,
        max_response_bytes=max_response_bytes,
    )

    raw_spec_for_refs = loaded_specs[0].spec if len(loaded_specs) == 1 else None
    tg, edge_stats = ingest_openapi_graphify(
        unique_tools,
        raw_spec=raw_spec_for_refs,
        promote_contract_signals=promote_contract_signals,
        contract_signal_options=contract_signal_options,
        max_contract_producers_per_field=max_contract_producers_per_field,
        user_input_field_names=user_input_field_names,
        context_field_names=context_field_names,
        auth_field_names=auth_field_names,
        paging_field_names=paging_field_names,
        search_filter_field_names=search_filter_field_names,
    )
    readiness_report = analyze_openapi_tools(
        unique_tools,
        graph=tg.graph,
        context_field_names=context_field_names,
        paging_field_names=paging_field_names,
        search_filter_field_names=search_filter_field_names,
    )
    snapshot_manifest = _source_snapshot_manifest(loaded_specs)

    build_options = {
        "required_only": bool(required_only),
        "skip_deprecated": bool(skip_deprecated),
        "promote_contract_signals": bool(promote_contract_signals),
        "max_contract_producers_per_field": int(max_contract_producers_per_field),
        "allow_private_hosts": bool(allow_private_hosts),
        "max_response_bytes": int(max_response_bytes),
        "context_field_names": _sorted_names(context_field_names),
        "paging_field_names": _sorted_names(paging_field_names),
        "search_filter_field_names": _sorted_names(search_filter_field_names),
        "auth_field_names": _sorted_names(auth_field_names),
        "user_input_field_names": _sorted_names(user_input_field_names),
    }
    if contract_signal_options:
        build_options["contract_signal_options"] = dict(contract_signal_options)

    artifact_metadata: dict[str, Any] = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "tool_count": len(tg.tools),
        "source_count": len(loaded_specs),
        "source_url": loaded_specs[0].source if len(loaded_specs) == 1 else "",
        "spec_urls": [loaded.source for loaded in loaded_specs],
        "source_snapshot_manifest": snapshot_manifest,
        "readiness_summary": dict(readiness_report.summary),
        "ingest_summary": ingest_summary,
        "edge_stats": edge_stats,
        "build_options": build_options,
    }
    if metadata:
        artifact_metadata.update(metadata)

    from graph_tool_call import __version__

    graph_payload: dict[str, Any] = {
        "format_version": "1",
        "library_version": __version__,
        "metadata": artifact_metadata,
        "graph": tg.graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in tg.tools.items()},
        "readiness_report": readiness_report.to_dict(),
        "source_snapshot_manifest": snapshot_manifest,
        "ingest_summary": ingest_summary,
        "edge_stats": edge_stats,
    }
    return annotate_graphify_metadata(
        graph_payload,
        collection_graph_version=collection_graph_version,
        in_place=True,
    )


def _load_openapi_collection_sources(
    source: dict[str, Any] | str | Sequence[dict[str, Any] | str],
    *,
    allow_private_hosts: bool,
    max_response_bytes: int,
) -> list[_LoadedOpenAPISpec]:
    requested = _requested_sources(source)
    expanded: list[dict[str, Any] | str] = []
    for item in requested:
        if isinstance(item, str) and item.startswith(_HTTP_PREFIXES):
            expanded.extend(
                _discover_spec_urls(
                    item,
                    allow_private_hosts=allow_private_hosts,
                    max_response_bytes=max_response_bytes,
                )
            )
        else:
            expanded.append(item)

    loaded: list[_LoadedOpenAPISpec] = []
    for index, item in enumerate(expanded, start=1):
        spec = (
            item
            if isinstance(item, dict)
            else _load_spec(
                item,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )
        )
        source_ref = f"inline:{index}" if isinstance(item, dict) else str(item)
        loaded.append(
            _LoadedOpenAPISpec(
                source=source_ref,
                label=_spec_label(spec, source=source_ref, index=index),
                spec=spec,
            )
        )
    return loaded


def _requested_sources(
    source: dict[str, Any] | str | Sequence[dict[str, Any] | str],
) -> list[dict[str, Any] | str]:
    if isinstance(source, (str, dict)):
        return [source]
    values = list(source)
    if not values:
        msg = "source must contain at least one OpenAPI spec source"
        raise ValueError(msg)
    if not all(isinstance(item, (str, dict)) for item in values):
        msg = "source sequence must contain only OpenAPI spec dicts or string sources"
        raise TypeError(msg)
    return values


def _ingest_unique_tools(
    loaded_specs: Sequence[_LoadedOpenAPISpec],
    *,
    required_only: bool,
    skip_deprecated: bool,
    allow_private_hosts: bool,
    max_response_bytes: int,
) -> tuple[list[ToolSchema], dict[str, Any]]:
    unique_tools: dict[str, ToolSchema] = {}
    duplicate_tool_names: Counter[str] = Counter()
    source_tool_counts: dict[str, int] = {}
    ingested_tool_total = 0

    for loaded in loaded_specs:
        tools, _normalized = ingest_openapi(
            loaded.spec,
            required_only=required_only,
            skip_deprecated=skip_deprecated,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
        source_tool_counts[loaded.label] = len(tools)
        ingested_tool_total += len(tools)
        for tool in tools:
            tool.metadata = dict(tool.metadata or {})
            tool.metadata["source_label"] = loaded.label
            tool.metadata["source_url"] = loaded.source
            if tool.name in unique_tools:
                duplicate_tool_names[tool.name] += 1
                continue
            unique_tools[tool.name] = tool

    return list(unique_tools.values()), {
        "ingested_tool_total": ingested_tool_total,
        "registered_tool_count": len(unique_tools),
        "duplicate_tool_count": ingested_tool_total - len(unique_tools),
        "duplicate_tool_names": [
            {"name": name, "count": count + 1}
            for name, count in duplicate_tool_names.most_common(20)
        ],
        "source_tool_counts": source_tool_counts,
    }


def _source_snapshot_manifest(loaded_specs: Sequence[_LoadedOpenAPISpec]) -> dict[str, Any]:
    specs = []
    for index, loaded in enumerate(loaded_specs, start=1):
        digest, byte_count = _canonical_spec_digest(loaded.spec)
        info = loaded.spec.get("info") if isinstance(loaded.spec.get("info"), dict) else {}
        specs.append(
            {
                "index": index,
                "label": loaded.label,
                "source": loaded.source,
                "sha256": digest,
                "bytes": byte_count,
                "title": str(info.get("title") or loaded.label),
                "version": str(info.get("version") or ""),
                "openapi_version": str(
                    loaded.spec.get("openapi") or loaded.spec.get("swagger") or ""
                ),
                "path_count": len(loaded.spec.get("paths") or {}),
                "operation_count": _operation_count(loaded.spec),
            }
        )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hash_algorithm": "sha256:canonical-json",
        "spec_count": len(specs),
        "operation_count": sum(int(row["operation_count"]) for row in specs),
        "path_count": sum(int(row["path_count"]) for row in specs),
        "specs": specs,
    }


def _canonical_spec_digest(spec: dict[str, Any]) -> tuple[str, int]:
    encoded = json.dumps(
        spec,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def _operation_count(spec: dict[str, Any]) -> int:
    count = 0
    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method in _METHODS:
            if isinstance(path_item.get(method), dict):
                count += 1
    return count


def _spec_label(spec: dict[str, Any], *, source: str, index: int) -> str:
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    title = str(info.get("title") or "").strip()
    if title:
        return title
    if source.startswith("inline:"):
        return f"spec-{index}"
    try:
        return Path(source).stem or f"spec-{index}"
    except (OSError, ValueError):
        return f"spec-{index}"


def _sorted_names(values: set[str] | list[str] | tuple[str, ...] | None) -> list[str]:
    return sorted({str(value) for value in values or [] if str(value).strip()})


__all__ = ["build_openapi_collection_artifact"]
