"""Ingest OpenAPI / Swagger specs into ToolSchema instances."""

from __future__ import annotations

import copy
import json
import urllib.request
from pathlib import Path
from typing import Any

from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.ingest.normalizer import NormalizedSpec, normalize

# ---------------------------------------------------------------------------
# YAML support (optional)
# ---------------------------------------------------------------------------

try:
    import yaml  # type: ignore[import-untyped]

    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

_HTTP_PREFIXES = ("http://", "https://")


def _load_spec(source: dict[str, Any] | str) -> dict[str, Any]:
    """Load a raw spec dict from *source* (dict, file path, or URL)."""
    if isinstance(source, dict):
        return source

    if not isinstance(source, str):
        msg = f"source must be dict or str, got {type(source)}"
        raise TypeError(msg)

    # URL
    if source.startswith(_HTTP_PREFIXES):
        with urllib.request.urlopen(source) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        # Try JSON first, then YAML
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if _HAS_YAML:
                return yaml.safe_load(raw)
            raise

    # File path
    path = Path(source)
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            msg = "PyYAML is required to load YAML files (pip install pyyaml)"
            raise ImportError(msg)
        return yaml.safe_load(text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------


def _resolve_refs(spec: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve internal ``$ref`` pointers.

    Handles ``#/definitions/...`` (Swagger 2.0) and ``#/components/schemas/...``
    (OpenAPI 3.x).  Circular references are detected and left as-is.
    """
    resolved = copy.deepcopy(spec)

    def _lookup(ref: str, root: dict[str, Any]) -> Any:
        """Walk the ref path and return the referenced object."""
        if not ref.startswith("#/"):
            return None
        parts = ref.lstrip("#/").split("/")
        node: Any = root
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        return node

    def _walk(node: Any, root: dict[str, Any], seen: set[str]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if ref in seen:
                    # Circular — return a stub
                    return {"type": "object", "description": f"(circular ref: {ref})"}
                target = _lookup(ref, root)
                if target is not None:
                    seen_copy = seen | {ref}
                    return _walk(copy.deepcopy(target), root, seen_copy)
                return node  # unresolvable ref, leave as-is
            return {k: _walk(v, root, seen) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item, root, seen) for item in node]
        return node

    return _walk(resolved, resolved, set())


# ---------------------------------------------------------------------------
# OpenAPI type -> ToolParameter type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


def _schema_type(schema: dict[str, Any]) -> str:
    return _TYPE_MAP.get(schema.get("type", "string"), "string")


# ---------------------------------------------------------------------------
# Operation -> ToolSchema
# ---------------------------------------------------------------------------


def _extract_params_swagger2(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    required_only: bool = False,
) -> list[ToolParameter]:
    """Extract parameters from a Swagger 2.0 operation."""
    params: list[ToolParameter] = []
    for p in operation.get("parameters", []):
        location = p.get("in", "")
        if location == "body":
            # Expand body schema properties as individual params
            body_schema = p.get("schema", {})
            body_required = set(body_schema.get("required", []))
            for prop_name, prop_schema in body_schema.get("properties", {}).items():
                is_required = prop_name in body_required
                if required_only and not is_required:
                    continue
                params.append(
                    ToolParameter(
                        name=prop_name,
                        type=_schema_type(prop_schema),
                        description=prop_schema.get("description", ""),
                        required=is_required,
                    )
                )
        else:
            is_required = p.get("required", False)
            if required_only and not is_required:
                continue
            params.append(
                ToolParameter(
                    name=p["name"],
                    type=_TYPE_MAP.get(p.get("type", "string"), "string"),
                    description=p.get("description", ""),
                    required=is_required,
                    enum=p.get("enum"),
                )
            )
    return params


def _extract_params_openapi3(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    required_only: bool = False,
) -> list[ToolParameter]:
    """Extract parameters from an OpenAPI 3.x operation."""
    params: list[ToolParameter] = []

    # Path / query / header / cookie parameters
    for p in operation.get("parameters", []):
        schema = p.get("schema", {})
        is_required = p.get("required", False)
        if required_only and not is_required:
            continue
        params.append(
            ToolParameter(
                name=p["name"],
                type=_schema_type(schema),
                description=p.get("description", ""),
                required=is_required,
                enum=schema.get("enum"),
            )
        )

    # requestBody
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    body_schema = json_content.get("schema", {})
    body_required = set(body_schema.get("required", []))
    for prop_name, prop_schema in body_schema.get("properties", {}).items():
        is_required = prop_name in body_required
        if required_only and not is_required:
            continue
        params.append(
            ToolParameter(
                name=prop_name,
                type=_schema_type(prop_schema),
                description=prop_schema.get("description", ""),
                required=is_required,
            )
        )

    return params


def _operation_to_tool(
    operation_id: str,
    operation: dict[str, Any],
    method: str,
    path: str,
    resolved_spec: dict[str, Any],
    *,
    is_swagger2: bool = False,
    required_only: bool = False,
) -> ToolSchema:
    """Convert a single OpenAPI operation into a ToolSchema."""
    description = operation.get("summary") or operation.get("description", "")

    if is_swagger2:
        parameters = _extract_params_swagger2(
            operation, resolved_spec, required_only=required_only
        )
    else:
        parameters = _extract_params_openapi3(
            operation, resolved_spec, required_only=required_only
        )

    tags = operation.get("tags", [])

    # Build response schema metadata
    responses = operation.get("responses", {})
    response_schema: dict[str, Any] = {}
    for code in ("200", "201", "default"):
        if code in responses:
            resp = responses[code]
            # Swagger 2.0
            if "schema" in resp:
                response_schema = resp["schema"]
                break
            # OpenAPI 3.x
            resp_content = resp.get("content", {})
            if "application/json" in resp_content:
                response_schema = resp_content["application/json"].get("schema", {})
                break

    metadata: dict[str, Any] = {
        "method": method,
        "path": path,
    }
    if response_schema:
        metadata["response_schema"] = response_schema

    return ToolSchema(
        name=operation_id,
        description=description,
        parameters=parameters,
        tags=tags,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Auto-categorize
# ---------------------------------------------------------------------------


def _auto_categorize(
    tools: list[ToolSchema],
    spec: NormalizedSpec,
) -> dict[str, str]:
    """Return a mapping of tool name -> category (domain).

    Uses tags first, then falls back to path prefix.
    """
    categories: dict[str, str] = {}
    for tool in tools:
        if tool.tags:
            categories[tool.name] = tool.tags[0]
        else:
            # Fallback: first path segment
            path = tool.metadata.get("path", "")
            segments = [s for s in path.strip("/").split("/") if not s.startswith("{")]
            if segments:
                categories[tool.name] = segments[0]
            else:
                categories[tool.name] = "general"
    return categories


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def ingest_openapi(
    source: dict[str, Any] | str,
    *,
    required_only: bool = False,
    skip_deprecated: bool = True,
) -> tuple[list[ToolSchema], NormalizedSpec]:
    """Ingest an OpenAPI/Swagger spec and return (tools, normalized_spec).

    Parameters
    ----------
    source:
        A raw spec dict, a file path (JSON/YAML), or a URL (http/https).
    required_only:
        If True, only include required parameters.
    skip_deprecated:
        If True (default), skip operations marked ``deprecated: true``.
    """
    raw_spec = _load_spec(source)
    spec = normalize(raw_spec)

    # Resolve refs on the raw spec so all $ref pointers are expanded
    from graph_tool_call.ingest.normalizer import SpecVersion

    is_swagger2 = spec.version == SpecVersion.SWAGGER_2_0
    resolved_raw = _resolve_refs(raw_spec)

    # We need resolved paths — re-normalize the resolved spec to get
    # auto-generated operationIds, then use the spec's paths for iteration
    resolved_spec = normalize(resolved_raw)

    tools: list[ToolSchema] = []
    for path, path_item in resolved_spec.paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in _METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            if skip_deprecated and operation.get("deprecated", False):
                continue
            operation_id = operation.get("operationId", "")
            if not operation_id:
                continue  # should not happen after normalization
            tool = _operation_to_tool(
                operation_id,
                operation,
                method,
                path,
                resolved_raw,
                is_swagger2=is_swagger2,
                required_only=required_only,
            )
            tools.append(tool)

    # Apply auto-categorization as domain
    categories = _auto_categorize(tools, spec)
    for tool in tools:
        tool.domain = categories.get(tool.name)

    return tools, spec
