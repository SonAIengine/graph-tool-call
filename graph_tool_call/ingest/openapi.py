"""Ingest OpenAPI / Swagger specs into ToolSchema instances."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from graph_tool_call.core.tool import MCPAnnotations, ToolParameter, ToolSchema
from graph_tool_call.ingest.io_contract import FieldLeaf, extract_leaves
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
_MAX_EXAMPLES_PER_BLOCK = 5
_MAX_EXAMPLE_CHARS = 2_000
_SCHEMA_HINT_KEYS: tuple[tuple[str, str], ...] = (
    ("format", "format"),
    ("default", "default"),
    ("example", "example"),
    ("nullable", "nullable"),
    ("pattern", "pattern"),
    ("minimum", "minimum"),
    ("maximum", "maximum"),
    ("exclusiveMinimum", "exclusive_minimum"),
    ("exclusiveMaximum", "exclusive_maximum"),
    ("minLength", "min_length"),
    ("maxLength", "max_length"),
    ("minItems", "min_items"),
    ("maxItems", "max_items"),
    ("minProperties", "min_properties"),
    ("maxProperties", "max_properties"),
    ("multipleOf", "multiple_of"),
    ("readOnly", "read_only"),
    ("writeOnly", "write_only"),
    ("deprecated", "deprecated"),
)
_ROW_HINT_KEYS = tuple(row_key for _schema_key, row_key in _SCHEMA_HINT_KEYS)


def _schema_type(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type", "string") if isinstance(schema, dict) else "string"
    if isinstance(schema_type, list):
        schema_type = next((t for t in schema_type if t and t != "null"), "string")
    return _TYPE_MAP.get(str(schema_type or "string"), "string")


def _add_schema_hints(row: dict[str, Any], schema: dict[str, Any]) -> None:
    """Copy JSON Schema validation/example hints into compact metadata rows."""
    if not isinstance(schema, dict):
        return
    for schema_key, row_key in _SCHEMA_HINT_KEYS:
        if schema_key not in schema:
            continue
        value = schema[schema_key]
        if value in (None, ""):
            continue
        row[row_key] = _compact_openapi_value(value)


def _copy_row_hints(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in (*_ROW_HINT_KEYS, "description"):
        value = source.get(key)
        if value not in (None, "", []):
            target[key] = copy.deepcopy(value)


def _compact_openapi_value(value: Any, *, max_chars: int = _MAX_EXAMPLE_CHARS) -> Any:
    """Keep examples/defaults JSON-safe without letting one spec bloat metadata."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(value)
        return text if len(text) <= max_chars else text[: max_chars - 3] + "..."
    if len(encoded) <= max_chars:
        return value
    return encoded[: max_chars - 3] + "..."


def _is_json_media_type(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json") or media == "*/*"


def _example_rows(
    container: dict[str, Any],
    *,
    location: str,
    content_type: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize OpenAPI ``example`` / ``examples`` blocks into compact rows."""
    if not isinstance(container, dict):
        return []

    rows: list[dict[str, Any]] = []

    def add(name: str, value: Any = None, source: dict[str, Any] | None = None) -> None:
        if len(rows) >= _MAX_EXAMPLES_PER_BLOCK:
            return
        row: dict[str, Any] = {"name": name, "location": location}
        if content_type:
            row["content_type"] = content_type
        if status:
            row["status"] = status
        if source:
            summary = str(source.get("summary") or "").strip()
            description = str(source.get("description") or "").strip()
            if summary:
                row["summary"] = summary[:200]
            if description:
                row["description"] = description[:300]
            if source.get("externalValue"):
                row["external_value"] = str(source["externalValue"])[:500]
        if value is not None:
            row["value"] = _compact_openapi_value(value)
        if "value" in row or "external_value" in row:
            rows.append(row)

    if "example" in container:
        add("example", container.get("example"))

    examples = container.get("examples")
    if isinstance(examples, dict):
        for name, example in examples.items():
            if isinstance(example, dict):
                add(str(name), example.get("value"), example)
            else:
                add(str(name), example)
    return rows


def _content_type_rows(
    content: dict[str, Any],
    *,
    location: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Summarize every declared OpenAPI media type without duplicating schemas."""
    if not isinstance(content, dict) or not content:
        return []
    rows: list[dict[str, Any]] = []
    for content_type, media in content.items():
        media = media if isinstance(media, dict) else {}
        schema = media.get("schema") if isinstance(media.get("schema"), dict) else {}
        row: dict[str, Any] = {
            "content_type": str(content_type),
            "is_json": _is_json_media_type(str(content_type)),
            "has_schema": bool(schema),
        }
        if schema:
            row["schema_type"] = _schema_type(schema)
            if location == "request_body":
                top_level_fields = _request_body_top_level_rows(schema)
                fields = _schema_field_rows(schema, location="body")
                row["field_count"] = len(fields)
                if top_level_fields:
                    row["top_level_fields"] = top_level_fields
                if fields:
                    row["fields"] = fields
            else:
                row["field_count"] = len(_schema_field_rows(schema, location=location))
        encoding = media.get("encoding")
        if isinstance(encoding, dict) and encoding:
            row["encoding"] = _encoding_rows(encoding)
        examples = _example_rows(
            media,
            location=location,
            content_type=str(content_type),
            status=status,
        )
        if examples:
            row["examples"] = examples
            row["example_count"] = len(examples)
        rows.append(row)
    return rows


def _media_type_name_rows(media_types: list[Any], *, has_schema: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for media_type in media_types:
        if not media_type:
            continue
        content_type = str(media_type)
        rows.append(
            {
                "content_type": content_type,
                "is_json": _is_json_media_type(content_type),
                "has_schema": bool(has_schema),
            }
        )
    return rows


def _encoding_rows(encoding: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, enc in encoding.items():
        if not isinstance(enc, dict):
            continue
        row: dict[str, Any] = {"field_name": str(field_name)}
        for key in ("contentType", "style", "explode", "allowReserved"):
            if key in enc:
                row_key = "content_type" if key == "contentType" else key
                row[row_key] = enc[key]
        if len(row) > 1:
            rows.append(row)
    return rows


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
    schema, _content_type = _pick_content_schema_with_type(content)
    return schema


def _pick_content_schema_with_type(content: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return ``(schema, media_type)`` using the same preference as runtime ingest."""
    if not isinstance(content, dict) or not content:
        return {}, None
    if "application/json" in content and (content["application/json"] or {}).get("schema"):
        return (content["application/json"] or {}).get("schema") or {}, "application/json"
    for ct, val in content.items():
        if isinstance(ct, str) and ct.endswith("+json") and (val or {}).get("schema"):
            return (val or {}).get("schema") or {}, ct
    if "*/*" in content and (content["*/*"] or {}).get("schema"):
        return (content["*/*"] or {}).get("schema") or {}, "*/*"
    # Last resort: the first content type with a schema.
    for ct, val in content.items():
        if isinstance(val, dict) and val.get("schema"):
            return val["schema"], str(ct)
    if "application/json" in content:
        return {}, "application/json"
    return {}, None


def _iter_request_body_schemas(content: dict[str, Any]) -> list[tuple[str | None, dict[str, Any]]]:
    """Return request body schemas in execution preference order, without duplicates."""
    if not isinstance(content, dict) or not content:
        return []
    selected_schema, selected_content_type = _pick_content_schema_with_type(content)
    rows: list[tuple[str | None, dict[str, Any]]] = []
    seen: set[str] = set()
    if selected_schema:
        rows.append((selected_content_type, selected_schema))
        if selected_content_type:
            seen.add(selected_content_type)
    for content_type, media in content.items():
        if not isinstance(media, dict):
            continue
        schema = media.get("schema") if isinstance(media.get("schema"), dict) else {}
        if not schema or str(content_type) in seen:
            continue
        rows.append((str(content_type), schema))
        seen.add(str(content_type))
    return rows


def _merged_parameters(
    operation: dict[str, Any],
    path_item: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Merge path-level and operation-level parameters with operation override."""
    merged: list[dict[str, Any]] = []
    index_by_key: dict[tuple[str, str], int] = {}
    for parameters in (
        (path_item or {}).get("parameters") or [],
        operation.get("parameters") or [],
    ):
        for source in parameters:
            if not isinstance(source, dict) or "name" not in source:
                continue
            key = (str(source.get("in") or ""), str(source.get("name") or ""))
            if key in index_by_key:
                merged[index_by_key[key]] = source
                continue
            index_by_key[key] = len(merged)
            merged.append(source)
    return merged


# ---------------------------------------------------------------------------
# Operation -> ToolSchema
# ---------------------------------------------------------------------------


def _extract_params_swagger2(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    required_only: bool = False,
    path_item: dict[str, Any] | None = None,
) -> list[ToolParameter]:
    """Extract parameters from a Swagger 2.0 operation."""
    params: list[ToolParameter] = []
    for p in _merged_parameters(operation, path_item):
        location = p.get("in", "")
        if location == "body":
            # Expand body schema properties as individual params
            body_schema = p.get("schema", {})
            body_required = set(body_schema.get("required", []))
            for prop_name, prop_schema in body_schema.get("properties", {}).items():
                if isinstance(prop_schema, dict) and prop_schema.get("readOnly"):
                    continue
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
            # OpenAPI 3.x / Swagger 2.0: path 파라미터는 본질적으로 required.
            # 많은 spec이 명시 안 해도 URL placeholder라 호출 시 반드시 값이 있어야 함.
            # synthesizer가 required 안 보고 빈 entity로 plan 생성 → HTTP 호출 실패 케이스 차단.
            if location == "path":
                is_required = True
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
    path_item: dict[str, Any] | None = None,
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

    raw_parameters = _merged_parameters(operation, path_item)
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
        # OpenAPI 3.x: path 파라미터는 본질적으로 required (URL placeholder 채우려면 필수).
        # 많은 spec이 명시 안 해도 강제로 required 처리해야 synthesizer가 빈 entity를
        # UnsatisfiableFieldError로 raise → question.required popup으로 사용자에게 묻는다.
        if p.get("in") == "path":
            is_required = True
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
    seen_body_props: set[str] = set()
    for _content_type, body_schema in _iter_request_body_schemas(content):
        body_required = set(body_schema.get("required", []))
        for prop_name, prop_schema in body_schema.get("properties", {}).items():
            if isinstance(prop_schema, dict) and prop_schema.get("readOnly"):
                continue
            if prop_name in seen_body_props:
                continue
            seen_body_props.add(prop_name)
            is_required = prop_name in body_required
            if required_only and not is_required:
                continue
            desc = prop_schema.get("description") or ""
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


def _pick_request_body_schema_with_type(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    is_swagger2: bool = False,
    path_item: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None, bool]:
    """Return ``(schema, content_type, required)`` for a request body."""
    if is_swagger2:
        consumes = (
            operation.get("consumes")
            or (path_item or {}).get("consumes")
            or resolved_spec.get("consumes")
            or []
        )
        content_type = str(consumes[0]) if consumes else None
        for p in _merged_parameters(operation, path_item):
            if isinstance(p, dict) and p.get("in") == "body":
                return p.get("schema") or {}, content_type, bool(p.get("required", False))
        return {}, content_type, False

    request_body = operation.get("requestBody") or {}
    if not isinstance(request_body, dict):
        return {}, None, False
    schema, content_type = _pick_content_schema_with_type(request_body.get("content") or {})
    return schema, content_type, bool(request_body.get("required", False))


def _pick_response_schema_with_status_and_type(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    is_swagger2: bool = False,
    path_item: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Return the preferred success response schema with status and media type."""
    produces = (
        operation.get("produces")
        or (path_item or {}).get("produces")
        or resolved_spec.get("produces")
        or []
    )
    swagger_content_type = str(produces[0]) if produces else None
    responses = operation.get("responses", {})
    if not isinstance(responses, dict):
        return {}, None, None

    success_codes = sorted(
        code for code in responses if str(code).isdigit() and 200 <= int(str(code)) < 300
    )
    for code in [*success_codes, "default"]:
        if code not in responses:
            continue
        resp = responses[code] or {}
        if "schema" in resp and isinstance(resp.get("schema"), dict):
            return resp["schema"], str(code), swagger_content_type
        picked, content_type = _pick_content_schema_with_type(resp.get("content") or {})
        if picked:
            return picked, str(code), content_type
    return {}, None, None


def _request_body_content_types(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    is_swagger2: bool = False,
    path_item: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if is_swagger2:
        consumes = (
            operation.get("consumes")
            or (path_item or {}).get("consumes")
            or resolved_spec.get("consumes")
            or []
        )
        schema, _content_type, _required = _pick_request_body_schema_with_type(
            operation,
            resolved_spec,
            is_swagger2=True,
            path_item=path_item,
        )
        return _media_type_name_rows(list(consumes), has_schema=bool(schema))

    request_body = operation.get("requestBody") or {}
    if not isinstance(request_body, dict):
        return []
    return _content_type_rows(request_body.get("content") or {}, location="request_body")


def _openapi_response_rows(
    operation: dict[str, Any],
    resolved_spec: dict[str, Any],
    *,
    is_swagger2: bool = False,
    path_item: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Summarize all declared responses, including error bodies."""
    produces = (
        operation.get("produces")
        or (path_item or {}).get("produces")
        or resolved_spec.get("produces")
        or []
    )
    swagger_content_type = str(produces[0]) if produces else None
    responses = operation.get("responses", {})
    if not isinstance(responses, dict):
        return []

    rows: list[dict[str, Any]] = []
    sorted_responses = sorted(
        responses.items(),
        key=lambda item: _response_status_sort(item[0]),
    )
    for status, response in sorted_responses:
        response = response if isinstance(response, dict) else {}
        status_text = str(status)
        row: dict[str, Any] = {
            "status": status_text,
            "success": _is_success_response_status(status_text),
        }
        description = str(response.get("description") or "").strip()
        if description:
            row["description"] = description[:300]

        schema: dict[str, Any] = {}
        content_type: str | None = None
        if is_swagger2:
            schema = response.get("schema") if isinstance(response.get("schema"), dict) else {}
            content_type = swagger_content_type if schema else None
            content_types = _media_type_name_rows(list(produces), has_schema=bool(schema))
            if content_types:
                row["content_types"] = content_types
            examples = _swagger_response_examples(response, status=status_text)
        else:
            content = response.get("content") or {}
            content_types = _content_type_rows(content, location="response", status=status_text)
            if content_types:
                row["content_types"] = content_types
            schema, content_type = _pick_content_schema_with_type(content)
            examples = []
            for content_row in content_types:
                examples.extend(content_row.get("examples") or [])

        if schema:
            row["content_type"] = content_type
            row["schema_type"] = _schema_type(schema)
            row["field_count"] = len(extract_leaves(schema, base_path="$"))
        if examples:
            row["examples"] = examples[:_MAX_EXAMPLES_PER_BLOCK]
            row["example_count"] = len(row["examples"])
        rows.append(row)
    return rows


def _swagger_response_examples(response: dict[str, Any], *, status: str) -> list[dict[str, Any]]:
    examples = response.get("examples")
    if not isinstance(examples, dict):
        return []
    rows: list[dict[str, Any]] = []
    for content_type, value in examples.items():
        if len(rows) >= _MAX_EXAMPLES_PER_BLOCK:
            break
        rows.append(
            {
                "name": "example",
                "location": "response",
                "status": status,
                "content_type": str(content_type),
                "value": _compact_openapi_value(value),
            }
        )
    return rows


def _response_status_sort(status: Any) -> tuple[int, int | str]:
    text = str(status)
    if text.isdigit():
        return 0, int(text)
    if text == "default":
        return 1, text
    return 2, text


def _is_success_response_status(status: str) -> bool:
    return status.isdigit() and 200 <= int(status) < 300


def _operation_examples(
    *,
    parameter_rows: list[dict[str, Any]],
    request_body_content_types: list[dict[str, Any]],
    response_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    parameter_examples: list[dict[str, Any]] = []
    request_body_examples: list[dict[str, Any]] = []
    response_examples: list[dict[str, Any]] = []

    for row in parameter_rows:
        for example in row.get("examples") or []:
            example_row = dict(example)
            example_row.setdefault("name", str(row.get("name") or "example"))
            example_row.setdefault("parameter", row.get("name"))
            example_row.setdefault("location", row.get("in") or "parameter")
            parameter_examples.append(example_row)

    for row in request_body_content_types:
        request_body_examples.extend(dict(example) for example in row.get("examples") or [])

    for row in response_rows:
        response_examples.extend(dict(example) for example in row.get("examples") or [])

    return {
        "parameters": parameter_examples[:_MAX_EXAMPLES_PER_BLOCK],
        "request_body": request_body_examples[:_MAX_EXAMPLES_PER_BLOCK],
        "responses": response_examples[:_MAX_EXAMPLES_PER_BLOCK],
    }


def _security_metadata(operation: dict[str, Any], resolved_spec: dict[str, Any]) -> dict[str, Any]:
    """Expose declared OpenAPI security requirements without runtime secrets."""
    requirements = operation.get("security", resolved_spec.get("security", []))
    schemes = (
        resolved_spec.get("components", {}).get("securitySchemes", {})
        or resolved_spec.get("securityDefinitions", {})
        or {}
    )
    if not requirements and not schemes:
        return {}

    compact_schemes: dict[str, dict[str, Any]] = {}
    if isinstance(schemes, dict):
        for name, scheme in schemes.items():
            if not isinstance(scheme, dict):
                continue
            row: dict[str, Any] = {}
            for key in (
                "type",
                "scheme",
                "bearerFormat",
                "name",
                "in",
                "description",
                "openIdConnectUrl",
            ):
                value = scheme.get(key)
                if value not in (None, ""):
                    row_key = "bearer_format" if key == "bearerFormat" else key
                    row[row_key] = str(value)[:500]
            flows = scheme.get("flows")
            if isinstance(flows, dict) and flows:
                row["oauth_flows"] = sorted(str(flow_name) for flow_name in flows)
            if row:
                compact_schemes[str(name)] = row

    metadata: dict[str, Any] = {}
    if isinstance(requirements, list):
        metadata["requirements"] = copy.deepcopy(requirements)
    if compact_schemes:
        metadata["schemes"] = compact_schemes
    return metadata


def _openapi_parameter_rows(
    operation: dict[str, Any],
    *,
    is_swagger2: bool = False,
    path_item: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize non-body OpenAPI parameters for execution/ranking metadata."""
    rows: list[dict[str, Any]] = []
    for p in _merged_parameters(operation, path_item):
        if not isinstance(p, dict) or "name" not in p:
            continue
        location = str(p.get("in") or "")
        if location == "body":
            continue
        schema = p if is_swagger2 else p.get("schema") or {}
        if not isinstance(schema, dict):
            schema = {}
        required = bool(p.get("required", location == "path"))
        if location == "path":
            required = True
        enum = p.get("enum") if is_swagger2 else schema.get("enum")
        row: dict[str, Any] = {
            "name": str(p["name"]),
            "in": location,
            "required": required,
            "field_type": _schema_type(schema),
        }
        _add_schema_hints(row, schema)
        desc = str(p.get("description") or "").strip()
        if desc:
            row["description"] = desc[:300]
        if isinstance(enum, list):
            row["enum"] = list(enum)
        examples = [
            *_example_rows(p, location=location),
            *_example_rows(schema, location=location),
        ]
        if examples:
            row["examples"] = examples[:_MAX_EXAMPLES_PER_BLOCK]
        for key in ("style", "explode", "allowReserved", "deprecated"):
            if key in p:
                row[key] = p[key]
        rows.append(row)
    return rows


def _schema_field_rows(
    schema: dict[str, Any],
    *,
    location: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(schema, dict) or not schema:
        return rows
    for leaf in extract_leaves(schema, base_path="$"):
        if location in {"body", "request_body"} and leaf.read_only:
            continue
        if location == "response" and leaf.write_only:
            continue
        rows.append(_leaf_row(leaf, location=location))
    return rows


def _request_body_top_level_rows(schema: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(schema, dict) or not schema:
        return []
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return []
    required = set(schema.get("required") or [])
    rows: list[dict[str, Any]] = []
    for name, prop in properties.items():
        prop = prop if isinstance(prop, dict) else {}
        if prop.get("readOnly"):
            continue
        row: dict[str, Any] = {
            "field_name": str(name),
            "json_path": f"$.{name}",
            "field_type": _schema_type(prop),
            "required": name in required,
            "location": "body",
        }
        _add_schema_hints(row, prop)
        desc = str(prop.get("description") or "").strip()
        if desc:
            row["description"] = desc[:300]
        enum = prop.get("enum")
        if isinstance(enum, list):
            row["enum"] = list(enum)
        rows.append(row)
    return rows


def _leaf_row(leaf: FieldLeaf, *, location: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "field_name": leaf.field_name,
        "json_path": leaf.json_path,
        "field_type": leaf.field_type,
        "required": bool(leaf.required),
        "location": location,
    }
    if leaf.description:
        row["description"] = leaf.description
    if leaf.enum:
        row["enum"] = list(leaf.enum)
    for source_key, row_key in (
        ("format", "format"),
        ("default", "default"),
        ("example", "example"),
        ("nullable", "nullable"),
        ("pattern", "pattern"),
        ("minimum", "minimum"),
        ("maximum", "maximum"),
        ("exclusive_minimum", "exclusive_minimum"),
        ("exclusive_maximum", "exclusive_maximum"),
        ("min_length", "min_length"),
        ("max_length", "max_length"),
        ("min_items", "min_items"),
        ("max_items", "max_items"),
        ("min_properties", "min_properties"),
        ("max_properties", "max_properties"),
        ("multiple_of", "multiple_of"),
        ("read_only", "read_only"),
        ("write_only", "write_only"),
        ("deprecated", "deprecated"),
    ):
        value = getattr(leaf, source_key)
        if value not in (None, "", []):
            row[row_key] = _compact_openapi_value(value)
    return row


def _input_locations(
    parameter_rows: list[dict[str, Any]],
    body_top_level_rows: list[dict[str, Any]],
    body_leaf_rows: list[dict[str, Any]],
) -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {
        "path": [],
        "query": [],
        "header": [],
        "cookie": [],
        "body": [],
    }
    for row in parameter_rows:
        loc = str(row.get("in") or "")
        name = str(row.get("name") or "")
        if loc in locations and name and name not in locations[loc]:
            locations[loc].append(name)
    for row in [*body_top_level_rows, *body_leaf_rows]:
        name = str(row.get("field_name") or "")
        if name and name not in locations["body"]:
            locations["body"].append(name)
    return locations


def _merge_body_field_rows(
    primary_rows: list[dict[str, Any]],
    content_type_rows: list[dict[str, Any]],
    *,
    field_key: str,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, Any]) -> None:
        name = str(row.get("field_name") or "")
        json_path = str(row.get("json_path") or "")
        if not name:
            return
        key = (name, json_path)
        if key in seen:
            return
        seen.add(key)
        merged.append(row)

    for row in primary_rows:
        add(row)
    for content_row in content_type_rows:
        if not isinstance(content_row, dict):
            continue
        for row in content_row.get(field_key) or []:
            if isinstance(row, dict):
                add(row)
    return merged


def _api_contract_rows(
    *,
    parameter_rows: list[dict[str, Any]],
    body_leaf_rows: list[dict[str, Any]],
    response_leaf_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    produces = []
    for row in response_leaf_rows:
        produce = {
            "field_name": row["field_name"],
            "json_path": row["json_path"],
            "field_type": row["field_type"],
            **({"enum": row["enum"]} if row.get("enum") else {}),
        }
        _copy_row_hints(row, produce)
        produces.append(produce)

    consumes: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(row: dict[str, Any], *, name_key: str, location_key: str) -> None:
        name = str(row.get(name_key) or "")
        location = str(row.get(location_key) or "")
        if not name:
            return
        key = (name, location)
        if key in seen:
            return
        seen.add(key)
        consume = {
            "field_name": name,
            "field_type": str(row.get("field_type") or "string"),
            "required": bool(row.get("required", False)),
            "location": location,
            "kind": "data",
        }
        if row.get("json_path"):
            consume["json_path"] = row["json_path"]
        if row.get("enum"):
            consume["enum"] = list(row["enum"])
        _copy_row_hints(row, consume)
        consumes.append(consume)

    for row in parameter_rows:
        _add(row, name_key="name", location_key="in")
    for row in body_leaf_rows:
        _add(row, name_key="field_name", location_key="location")
    return produces, consumes


def _path_params(path: str) -> list[str]:
    return re.findall(r"{([^}/]+)}", path)


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
        parameters = _extract_params_swagger2(
            operation,
            resolved_spec,
            required_only=required_only,
            path_item=path_item,
        )
    else:
        parameters = _extract_params_openapi3(
            operation,
            resolved_spec,
            required_only=required_only,
            path_item=path_item,
        )

    request_body_schema, request_content_type, request_required = (
        _pick_request_body_schema_with_type(
            operation,
            resolved_spec,
            is_swagger2=is_swagger2,
            path_item=path_item,
        )
    )
    request_body_content_type_rows = _request_body_content_types(
        operation,
        resolved_spec,
        is_swagger2=is_swagger2,
        path_item=path_item,
    )
    response_schema, response_status, response_content_type = (
        _pick_response_schema_with_status_and_type(
            operation,
            resolved_spec,
            is_swagger2=is_swagger2,
            path_item=path_item,
        )
    )
    response_rows = _openapi_response_rows(
        operation,
        resolved_spec,
        is_swagger2=is_swagger2,
        path_item=path_item,
    )
    for row in request_body_content_type_rows:
        if row.get("content_type") == request_content_type:
            row["selected"] = True
    for row in response_rows:
        if row.get("status") == response_status:
            row["selected"] = True
            for content_row in row.get("content_types") or []:
                if (
                    isinstance(content_row, dict)
                    and content_row.get("content_type") == response_content_type
                ):
                    content_row["selected"] = True
    parameter_rows = _openapi_parameter_rows(
        operation,
        is_swagger2=is_swagger2,
        path_item=path_item,
    )
    body_top_level_rows = _request_body_top_level_rows(request_body_schema)
    body_leaf_rows = _schema_field_rows(request_body_schema, location="body")
    all_body_top_level_rows = _merge_body_field_rows(
        body_top_level_rows,
        request_body_content_type_rows,
        field_key="top_level_fields",
    )
    all_body_leaf_rows = _merge_body_field_rows(
        body_leaf_rows,
        request_body_content_type_rows,
        field_key="fields",
    )
    response_leaf_rows = _schema_field_rows(response_schema, location="response")
    produces, consumes = _api_contract_rows(
        parameter_rows=parameter_rows,
        body_leaf_rows=all_body_leaf_rows,
        response_leaf_rows=response_leaf_rows,
    )
    input_locations = _input_locations(parameter_rows, all_body_top_level_rows, all_body_leaf_rows)
    selected_response = next(
        (row for row in response_rows if row.get("status") == response_status),
        {},
    )
    examples = _operation_examples(
        parameter_rows=parameter_rows,
        request_body_content_types=request_body_content_type_rows,
        response_rows=response_rows,
    )
    security = _security_metadata(operation, resolved_spec)

    metadata: dict[str, Any] = {
        "source": "openapi",
        "method": method,
        "path": path,
        "api_contract": {
            "produces": produces,
            "consumes": consumes,
        },
        "openapi": {
            "operation_id": operation_id,
            "summary": operation.get("summary") or "",
            "description": operation.get("description") or "",
            "deprecated": bool(operation.get("deprecated", False)),
            "parameters": parameter_rows,
            "path_params": _path_params(path),
            "input_locations": input_locations,
            "request_body": {
                "required": request_required,
                "content_type": request_content_type,
                "content_types": request_body_content_type_rows,
                "schema": request_body_schema,
                "top_level_fields": body_top_level_rows,
                "fields": body_leaf_rows,
                "all_top_level_fields": all_body_top_level_rows,
                "all_fields": all_body_leaf_rows,
            },
            "response": {
                "status": response_status,
                "content_type": response_content_type,
                "description": selected_response.get("description", ""),
                "schema": response_schema,
                "fields": response_leaf_rows,
            },
            "responses": response_rows,
            "error_responses": [row for row in response_rows if not row.get("success")],
            "examples": examples,
        },
        "input_locations": input_locations,
    }
    if security:
        metadata["openapi"]["security"] = security
    if request_body_schema:
        metadata["request_body_schema"] = request_body_schema
    if request_content_type:
        metadata["request_content_type"] = request_content_type
    if response_schema:
        metadata["response_schema"] = response_schema
    if response_status:
        metadata["response_status"] = response_status
    if response_content_type:
        metadata["response_content_type"] = response_content_type

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
