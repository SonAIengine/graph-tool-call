"""Public OpenAPI contract index helpers for collection builders.

This module exposes the OpenAPI facts already extracted by ``ingest_openapi``
in an operation-indexed shape. Product adapters such as XGEN can use this
instead of reaching into ingest internals or re-walking specs differently from
graph-tool-call.
"""

from __future__ import annotations

import copy
from typing import Any

from graph_tool_call.ingest.openapi import ingest_openapi


def extract_openapi_contract_index(
    source: dict[str, Any] | str,
    *,
    required_only: bool = False,
    skip_deprecated: bool = True,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """Return operation-level OpenAPI contract facts in a stable dict shape.

    The returned payload is JSON-serializable and intentionally redundant:
    callers can look up entries by operationId, tool name, or ``METHOD path``.
    Each operation includes request/response schema summaries plus the raw
    ``metadata.openapi`` and ``metadata.api_contract`` produced by the canonical
    ingest path.
    """

    tools, _spec = ingest_openapi(
        source,
        required_only=required_only,
        skip_deprecated=skip_deprecated,
        allow_private_hosts=allow_private_hosts,
        max_response_bytes=max_response_bytes,
    )

    operations: list[dict[str, Any]] = []
    by_operation_id: dict[str, str] = {}
    by_tool_name: dict[str, str] = {}
    by_method_path: dict[str, str] = {}

    for tool in tools:
        metadata = copy.deepcopy(getattr(tool, "metadata", None) or {})
        openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        api_contract = (
            metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
        )
        method = str(metadata.get("method") or openapi.get("method") or "").lower()
        path = str(metadata.get("path") or openapi.get("path") or "")
        operation_id = str(openapi.get("operation_id") or tool.name)
        key = _operation_key(method, path, operation_id, tool.name)

        request_body = (
            openapi.get("request_body") if isinstance(openapi.get("request_body"), dict) else {}
        )
        response = openapi.get("response") if isinstance(openapi.get("response"), dict) else {}
        operation: dict[str, Any] = {
            "key": key,
            "tool_name": tool.name,
            "operation_id": operation_id,
            "method": method,
            "path": path,
            "summary": str(openapi.get("summary") or ""),
            "description": str(openapi.get("description") or ""),
            "tags": list(getattr(tool, "tags", None) or []),
            "deprecated": bool(openapi.get("deprecated", False)),
            "parameters": copy.deepcopy(openapi.get("parameters") or []),
            "request_body_schema": copy.deepcopy(
                metadata.get("request_body_schema") or request_body.get("schema") or {}
            ),
            "response_schema": copy.deepcopy(
                metadata.get("response_schema") or response.get("schema") or {}
            ),
            "request_content_type": metadata.get("request_content_type")
            or request_body.get("content_type"),
            "response_content_type": metadata.get("response_content_type")
            or response.get("content_type"),
            "request_content_types": copy.deepcopy(request_body.get("content_types") or []),
            "responses": copy.deepcopy(openapi.get("responses") or []),
            "response": copy.deepcopy(response),
            "security": copy.deepcopy(openapi.get("security") or {}),
            "server": copy.deepcopy(openapi.get("server") or {}),
            "api_contract": copy.deepcopy(api_contract),
            "openapi": copy.deepcopy(openapi),
            "metadata": metadata,
            "annotations": tool.annotations.to_dict() if tool.annotations else {},
        }
        operations.append(operation)
        by_tool_name[tool.name] = key
        by_operation_id.setdefault(operation_id, key)
        if method and path:
            by_method_path[f"{method.upper()} {path}"] = key

    return {
        "version": 1,
        "operation_count": len(operations),
        "operations": operations,
        "by_operation_id": by_operation_id,
        "by_tool_name": by_tool_name,
        "by_method_path": by_method_path,
        "summary": _summary(operations),
    }


def _operation_key(method: str, path: str, operation_id: str, tool_name: str) -> str:
    if method and path:
        return f"{method.upper()} {path}"
    return operation_id or tool_name


def _summary(operations: list[dict[str, Any]]) -> dict[str, Any]:
    request_schema_count = 0
    response_schema_count = 0
    produces_count = 0
    consumes_count = 0
    auth_count = 0
    unsupported_content_type_count = 0

    for op in operations:
        if op.get("request_body_schema"):
            request_schema_count += 1
        if op.get("response_schema"):
            response_schema_count += 1
        contract = op.get("api_contract") if isinstance(op.get("api_contract"), dict) else {}
        produces = contract.get("produces") if isinstance(contract.get("produces"), list) else []
        consumes = contract.get("consumes") if isinstance(contract.get("consumes"), list) else []
        produces_count += len(produces)
        consumes_count += len(consumes)
        if any(isinstance(row, dict) and row.get("kind") == "auth" for row in consumes):
            auth_count += 1
        request_ct = str(op.get("request_content_type") or "")
        response_ct = str(op.get("response_content_type") or "")
        if _unsupported_json_content_type(request_ct) or _unsupported_json_content_type(
            response_ct
        ):
            unsupported_content_type_count += 1

    total = max(1, len(operations))
    return {
        "request_schema_tool_count": request_schema_count,
        "request_schema_coverage": round(request_schema_count / total, 4),
        "response_schema_tool_count": response_schema_count,
        "response_schema_coverage": round(response_schema_count / total, 4),
        "produces_field_count": produces_count,
        "consumes_field_count": consumes_count,
        "auth_tool_count": auth_count,
        "unsupported_content_type_count": unsupported_content_type_count,
    }


def _unsupported_json_content_type(content_type: str) -> bool:
    if not content_type:
        return False
    ct = content_type.split(";", 1)[0].strip().lower()
    if ct in {"application/json", "*/*"}:
        return False
    return not (ct.startswith("application/") and ct.endswith("+json"))


__all__ = ["extract_openapi_contract_index"]
