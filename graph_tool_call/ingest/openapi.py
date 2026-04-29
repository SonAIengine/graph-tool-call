"""Ingest OpenAPI / Swagger specs into ToolSchema instances."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from graph_tool_call.core.tool import MCPAnnotations, ToolParameter, ToolSchema
from graph_tool_call.ingest.normalizer import NormalizedSpec, normalize
from graph_tool_call.net import fetch_url_text

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


def _load_spec(
    source: dict[str, Any] | str,
    *,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """Load a raw spec dict from *source* (dict, file path, or URL)."""
    if isinstance(source, dict):
        return source

    if not isinstance(source, str):
        msg = f"source must be dict or str, got {type(source)}"
        raise TypeError(msg)

    # URL
    if source.startswith(_HTTP_PREFIXES):
        raw = fetch_url_text(
            source,
            timeout=30,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
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


def _pick_content_schema(content: dict[str, Any]) -> dict[str, Any]:
    """Pick a usable schema from an OpenAPI ``content`` object.

    OpenAPI 3.x lets a request body / response declare schemas under any
    media-type key. The preferred order is:

      1. ``application/json``                 — most common
      2. ``application/*+json`` (e.g. hal+json) — JSON variants
      3. ``*/*``                                — Spring/SpringDoc default when
                                                  the operation doesn't pin a
                                                  specific content type
      4. first available media-type            — last resort

    Returning the schema dict (possibly empty). The earlier code only
    looked at ``application/json`` and silently dropped everything else,
    which produced empty ``response_schema`` for every Spring endpoint
    that uses the default ``*/*`` (real-world failure: x2bee Order API,
    where this caused PathSynthesizer to find zero producers).
    """
    if not isinstance(content, dict) or not content:
        return {}
    if "application/json" in content:
        return (content["application/json"] or {}).get("schema") or {}
    for ct, val in content.items():
        if isinstance(ct, str) and ct.endswith("+json"):
            return (val or {}).get("schema") or {}
    if "*/*" in content:
        return (content["*/*"] or {}).get("schema") or {}
    # Last resort: the first content type with a schema.
    for val in content.values():
        if isinstance(val, dict) and val.get("schema"):
            return val["schema"]
    return {}


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


def _summarize_object_schema(schema: dict[str, Any], *, max_depth: int = 2) -> str:
    """Object/array schema의 nested properties를 사람/LLM이 읽기 좋게 요약.

    parameter type이 'object'/'array'인데 안의 필드명이 ToolParameter에 안 드러나면
    LLM이 필드명을 추측하게 된다. 이 함수는 properties + required + description을
    description 텍스트로 합쳐서 LLM 컨텍스트에 함께 노출되도록 한다.
    """
    if not isinstance(schema, dict):
        return ""

    def _walk(s: dict[str, Any], depth: int, indent: int) -> list[str]:
        if depth > max_depth or not isinstance(s, dict):
            return []
        out: list[str] = []
        prefix = "  " * indent

        # Unwrap array → items
        if s.get("type") == "array":
            items = s.get("items") or {}
            out.append(f"{prefix}[array of:]")
            out.extend(_walk(items, depth + 1, indent + 1))
            return out

        props = s.get("properties") or {}
        if not props:
            return out
        required = set(s.get("required") or [])
        for name, prop in props.items():
            if not isinstance(prop, dict):
                continue
            ptype = _schema_type(prop)
            req = "*" if name in required else ""
            desc = (prop.get("description") or "").strip()
            example = prop.get("example")
            line = f"{prefix}- {name}{req} ({ptype})"
            if desc:
                line += f": {desc}"
            if example is not None and not desc:
                line += f"  e.g. {example}"
            out.append(line)
            # Nested object/array 1단계 더 펼치기
            if depth < max_depth:
                if ptype == "object":
                    out.extend(_walk(prop, depth + 1, indent + 1))
                elif ptype == "array":
                    items = prop.get("items") or {}
                    if items.get("properties") or items.get("type") in ("object", "array"):
                        out.extend(_walk(items, depth + 1, indent + 1))
        return out

    lines = _walk(schema, 0, 0)
    return "\n".join(lines)


def _extract_params_openapi3(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    required_only: bool = False,
) -> list[ToolParameter]:
    """Extract parameters from an OpenAPI 3.x operation.

    Spring/SpringDoc gotcha: when a controller takes a `@ModelAttribute`
    DTO via query string, the spec sometimes lists BOTH the wrapper
    object AND its inner fields as separate query parameters
    (``regularOrderDetailRequest`` ``in=query`` ``type=object`` AND
    ``rglrDeliNo`` ``in=query`` ``type=string``). Treating the wrapper
    as a real input field poisons downstream producer matching: nothing
    in the API ever returns a value named after the wrapper class, so
    PathSynthesizer raises ``UnsatisfiableField`` on a phantom field.

    Strategy: drop wrapper parameters when their inner properties are
    already exposed as siblings; otherwise expand the wrapper into its
    leaf properties so callers see the real input names.
    """
    params: list[ToolParameter] = []

    raw_parameters = list(operation.get("parameters", []))
    # Pre-collect names from non-object parameters — used to detect when
    # a wrapper's inner property is already exposed alongside it.
    sibling_names: set[str] = {
        str(p.get("name") or "")
        for p in raw_parameters
        if isinstance(p, dict) and _schema_type(p.get("schema", {}) or {}) not in ("object",)
    }

    # Path / query / header / cookie parameters
    for p in raw_parameters:
        if "name" not in p:
            continue  # skip malformed parameters (missing required 'name' field)
        schema = p.get("schema", {})
        is_required = p.get("required", False)
        ptype = _schema_type(schema)

        # Wrapper-object/array query parameter handling.
        # type=object → wrapper itself (Spring @ModelAttribute style).
        # type=array of objects → wrapper used to send a list of structured
        # records (less common but seen in some Spring specs); we expand the
        # element schema's properties. Primitive arrays (array of integers /
        # strings) are real list inputs and are NOT expanded here — those
        # belong to the caller as a single multi-value field.
        if ptype in ("object", "array") and p.get("in") == "query":
            wrapper_props: dict[str, Any] = {}
            wrapper_required: set[str] = set()
            if ptype == "object":
                wrapper_props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
                wrapper_required = set(schema.get("required") or [])
            else:  # array
                items = (schema.get("items") or {}) if isinstance(schema, dict) else {}
                if isinstance(items, dict) and items.get("type") == "object":
                    wrapper_props = items.get("properties") or {}
                    wrapper_required = set(items.get("required") or [])
                # else: primitive-element array — don't expand, treat as real input
            if wrapper_props:
                # If every inner property is already a sibling parameter,
                # drop the wrapper entirely (deduplication).
                if all(prop in sibling_names for prop in wrapper_props):
                    continue
                # Otherwise expand the wrapper into individual leaves so
                # producer matching has real field names to chase.
                for prop_name, prop_schema in wrapper_props.items():
                    if prop_name in sibling_names:
                        continue  # don't double-list ones already exposed
                    inner_required = prop_name in wrapper_required
                    if required_only and not inner_required:
                        continue
                    inner_type = _schema_type(prop_schema or {})
                    inner_desc = (prop_schema or {}).get("description", "") or ""
                    params.append(
                        ToolParameter(
                            name=prop_name,
                            type=inner_type,
                            description=inner_desc,
                            required=inner_required,
                            enum=(prop_schema or {}).get("enum"),
                        )
                    )
                continue  # wrapper itself is not added

        if required_only and not is_required:
            continue
        desc = p.get("description", "") or ""
        # object/array 타입이면 nested fields를 description에 펼쳐서
        # LLM이 정확한 필드명(예: searchWord)을 알 수 있게 한다.
        if ptype in ("object", "array"):
            nested = _summarize_object_schema(schema)
            if nested:
                desc = (desc + "\nFields:\n" + nested).strip() if desc else f"Fields:\n{nested}"
        params.append(
            ToolParameter(
                name=p["name"],
                type=ptype,
                description=desc,
                required=is_required,
                enum=schema.get("enum"),
            )
        )

    # requestBody — pick the most specific schema across declared media types
    # (Spring/SpringDoc commonly emits */* — see _pick_content_schema notes).
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    body_schema = _pick_content_schema(content)
    body_required = set(body_schema.get("required", []))
    for prop_name, prop_schema in body_schema.get("properties", {}).items():
        is_required = prop_name in body_required
        if required_only and not is_required:
            continue
        desc = (prop_schema.get("description") or "")
        # nested object/array는 한 단계 더 펼치기
        if _schema_type(prop_schema) in ("object", "array"):
            nested = _summarize_object_schema(prop_schema)
            if nested:
                desc = (desc + "\nFields:\n" + nested).strip() if desc else f"Fields:\n{nested}"
        params.append(
            ToolParameter(
                name=prop_name,
                type=_schema_type(prop_schema),
                description=desc,
                required=is_required,
            )
        )

    return params


_ANNOTATION_BY_METHOD: dict[str, MCPAnnotations] = {
    "get": MCPAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True),
    "head": MCPAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True),
    "options": MCPAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True),
    "post": MCPAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False),
    "put": MCPAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True),
    "patch": MCPAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False),
    "delete": MCPAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True),
}


def _infer_annotations(method: str) -> MCPAnnotations | None:
    """Infer MCP annotations from HTTP method (RFC 7231)."""
    return _ANNOTATION_BY_METHOD.get(method.lower())


def _enrich_description(description: str, method: str, path: str) -> str:
    """Append path-derived context to short/generic descriptions.

    Many large APIs (e.g. Kubernetes) share identical descriptions across operations
    that differ only in scope or sub-resource. This enrichment adds discriminative
    signals that BM25 and embedding can use.

    Only activates when the path has enough depth (3+ segments) to indicate
    a complex API with scope disambiguation needs.
    """
    if not path:
        return description

    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    # Only enrich for complex paths — simple APIs (e.g. /items, /users/{id})
    # don't need scope/sub-resource disambiguation.
    if len(segments) < 3:
        return description

    suffixes: list[str] = []

    has_ns = "{namespace}" in path or "{ns}" in path
    has_name = "{name}" in path

    if has_ns:
        suffixes.append("namespaced")
    elif not has_name and method.lower() in ("get", "delete"):
        suffixes.append("cluster-wide")

    # Sub-resource detection from path suffix
    if segments:
        resource = segments[-1]
        sub_resources = {
            "exec",
            "attach",
            "portforward",
            "proxy",
            "log",
            "status",
            "scale",
            "finalize",
            "binding",
            "eviction",
            "ephemeralcontainers",
        }
        if resource.lower() in sub_resources and len(segments) >= 2:
            parent = segments[-2]
            suffixes.append(f"{resource} of {parent}")

    # Collection delete
    if method.lower() == "delete" and not has_name:
        suffixes.append("collection")

    if suffixes:
        return f"{description} ({', '.join(suffixes)})"
    return description


def _resolve_server_url(
    operation: dict[str, Any],
    path_item: dict[str, Any] | None,
    spec: dict[str, Any],
    *,
    is_swagger2: bool = False,
) -> str | None:
    """OpenAPI 우선순위: operation.servers > path.servers > spec.servers.

    Swagger 2.0은 ``host`` + ``basePath`` + ``schemes`` 조합으로 base_url 구성.
    """
    if is_swagger2:
        host = spec.get("host")
        if not host:
            return None
        scheme = (spec.get("schemes") or ["https"])[0]
        base_path = spec.get("basePath") or ""
        return f"{scheme}://{host}{base_path}".rstrip("/")

    for source in (operation, path_item or {}, spec):
        servers = source.get("servers") if isinstance(source, dict) else None
        if servers and isinstance(servers, list) and servers:
            url = (servers[0] or {}).get("url")
            if url:
                return str(url).rstrip("/")
    return None


def _operation_to_tool(
    operation_id: str,
    operation: dict[str, Any],
    method: str,
    path: str,
    resolved_spec: dict[str, Any],
    *,
    is_swagger2: bool = False,
    required_only: bool = False,
    path_item: dict[str, Any] | None = None,
) -> ToolSchema:
    """Convert a single OpenAPI operation into a ToolSchema."""
    description = operation.get("summary") or operation.get("description", "")
    tags = operation.get("tags", [])

    # Fallback: auto-generate description from method + path + tags
    if not description.strip():
        parts = [method.upper(), path]
        if tags:
            parts.append(f"[{', '.join(tags)}]")
        description = " ".join(parts)

    # Enrich generic descriptions with path-derived context
    description = _enrich_description(description, method, path)

    if is_swagger2:
        parameters = _extract_params_swagger2(operation, resolved_spec, required_only=required_only)
    else:
        parameters = _extract_params_openapi3(operation, resolved_spec, required_only=required_only)

    # Build response schema metadata. Walk responses in success-code order
    # and use _pick_content_schema so we don't drop schemas declared under
    # */*, application/*+json, or other non-JSON media types.
    responses = operation.get("responses", {})
    response_schema: dict[str, Any] = {}
    for code in ("200", "201", "default"):
        if code not in responses:
            continue
        resp = responses[code] or {}
        # Swagger 2.0 puts the schema directly on the response object.
        if "schema" in resp and isinstance(resp.get("schema"), dict):
            response_schema = resp["schema"]
            break
        # OpenAPI 3.x: inspect the content map.
        picked = _pick_content_schema(resp.get("content") or {})
        if picked:
            response_schema = picked
            break

    metadata: dict[str, Any] = {
        "source": "openapi",
        "method": method,
        "path": path,
    }
    if response_schema:
        metadata["response_schema"] = response_schema

    # spec/path/operation 단위의 servers field → tool 자체 base_url 부여.
    # 한 컬렉션에 다른 host를 가진 source들이 섞여 있을 때 executor가 tool마다
    # 알맞은 base_url로 호출할 수 있게 한다.
    server_url = _resolve_server_url(operation, path_item, resolved_spec, is_swagger2=is_swagger2)
    if server_url:
        metadata["base_url"] = server_url

    return ToolSchema(
        name=operation_id,
        description=description,
        parameters=parameters,
        tags=tags,
        metadata=metadata,
        annotations=_infer_annotations(method),
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
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
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
    raw_spec = _load_spec(
        source,
        allow_private_hosts=allow_private_hosts,
        max_response_bytes=max_response_bytes,
    )
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
                path_item=path_item,
            )
            tools.append(tool)

    # Apply auto-categorization as domain
    categories = _auto_categorize(tools, spec)
    for tool in tools:
        tool.domain = categories.get(tool.name)

    return tools, spec
