"""Field-level IO contract extraction from OpenAPI / Swagger schemas.

Used by L0 Knowledge Base — **Pass 1, deterministic**. Walks request and
response schemas and emits leaf field descriptors with JsonPath. The output
feeds:

  - Tool Graph: produces × consumes field-name match → ``produces_for`` edge
  - Pass 2 enrichment: provides field list to LLM for ``semantic_tag`` assign
  - Stage 3 Runner: bindings reference these json_paths

This module assumes the input schema is **already $ref-resolved** (caller
runs ``_resolve_refs`` from ``graph_tool_call.ingest.openapi``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldLeaf:
    """A leaf field extracted from a JSON Schema.

    ``json_path`` is the dotted JSONPath from the schema root, with ``[*]``
    used as the array wildcard (for produces). For consumes, callers usually
    flatten to ``field_name`` since binding keys by name not path.
    """

    json_path: str
    field_name: str
    field_type: str
    required: bool = False
    description: str = ""
    enum: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schema walker
# ---------------------------------------------------------------------------


_DEFAULT_MAX_DEPTH = 8


def extract_leaves(
    schema: Any,
    *,
    base_path: str = "$",
    parent_required: bool = False,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    _depth: int = 0,
) -> list[FieldLeaf]:
    """Recursively walk a JSON Schema, emitting leaf field info.

    Parameters
    ----------
    schema:
        JSON Schema dict (already $ref-resolved).
    base_path:
        Starting JSONPath for this subtree (e.g. ``$``, ``$.body``).
    parent_required:
        Whether the containing field is required by its parent. Propagated to
        leaves so the caller can filter ``required-only`` consumes.
    max_depth:
        Hard recursion limit. Cyclic schemas or pathological nesting stop here.

    Returns
    -------
    list[FieldLeaf]
        One entry per primitive (or array-of-primitive) leaf reachable.
    """
    if not isinstance(schema, dict) or _depth > max_depth:
        return []

    schema = _resolve_combinators(schema)

    schema_type = _normalize_type(schema.get("type"))

    # Object: walk properties
    if schema_type == "object" or "properties" in schema:
        return _walk_object(schema, base_path, max_depth, _depth)

    # Array: walk items with [*] suffix
    if schema_type == "array":
        items = schema.get("items") or {}
        return extract_leaves(
            items,
            base_path=f"{base_path}[*]",
            parent_required=parent_required,
            max_depth=max_depth,
            _depth=_depth + 1,
        )

    # Primitive: emit a single leaf using the trailing path segment as name
    field_name = _last_path_segment(base_path)
    if not field_name:
        # At root with no parent name — nothing useful to emit
        return []
    return [
        FieldLeaf(
            json_path=base_path,
            field_name=field_name,
            field_type=schema_type or "string",
            required=parent_required,
            description=str(schema.get("description") or "")[:200],
            enum=list(schema.get("enum") or []),
        )
    ]


def _walk_object(
    schema: dict[str, Any],
    base_path: str,
    max_depth: int,
    depth: int,
) -> list[FieldLeaf]:
    leaves: list[FieldLeaf] = []
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return leaves
    required_set = set(schema.get("required") or [])

    for prop_name, prop_schema in properties.items():
        child_path = f"{base_path}.{prop_name}"
        is_required = prop_name in required_set
        child_leaves = extract_leaves(
            prop_schema,
            base_path=child_path,
            parent_required=is_required,
            max_depth=max_depth,
            _depth=depth + 1,
        )
        if child_leaves:
            leaves.extend(child_leaves)
        else:
            # Object/array with no resolvable children — keep as a generic leaf
            # so downstream knows the field exists (e.g. opaque additionalProps).
            leaves.append(
                FieldLeaf(
                    json_path=child_path,
                    field_name=prop_name,
                    field_type=_schema_type(prop_schema) or "object",
                    required=is_required,
                    description=(
                        str(prop_schema.get("description") or "")[:200]
                        if isinstance(prop_schema, dict)
                        else ""
                    ),
                )
            )
    return leaves


def _resolve_combinators(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``allOf`` / pick first ``oneOf`` / ``anyOf``.

    v1 strategy: best-effort. Doesn't handle JSON Schema combinator semantics
    fully — sufficient to surface field shapes for our planning use.
    """
    if "allOf" in schema and isinstance(schema["allOf"], list):
        merged_props: dict[str, Any] = dict(schema.get("properties") or {})
        merged_required: list[str] = list(schema.get("required") or [])
        for sub in schema["allOf"]:
            if not isinstance(sub, dict):
                continue
            merged_props.update(sub.get("properties") or {})
            for r in sub.get("required") or []:
                if r not in merged_required:
                    merged_required.append(r)
        out = dict(schema)
        out["type"] = "object"
        out["properties"] = merged_props
        out["required"] = merged_required
        return out

    for key in ("oneOf", "anyOf"):
        candidates = schema.get(key)
        if isinstance(candidates, list) and candidates:
            first = next((c for c in candidates if isinstance(c, dict)), None)
            if first is not None:
                # Merge the candidate as a base, parent fields override
                base = dict(first)
                base.update({k: v for k, v in schema.items() if k != key})
                return base
    return schema


def _normalize_type(t: Any) -> str:
    """JSON Schema 'type' can be str or list. Pick first non-null."""
    if isinstance(t, list):
        return next((x for x in t if x and x != "null"), "")
    return t or ""


def _schema_type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return ""
    return _normalize_type(schema.get("type"))


def _last_path_segment(path: str) -> str:
    """Extract trailing field name from a JsonPath like ``$.body.goods[*].goodsNo``."""
    if not path or path == "$":
        return ""
    last = path.rsplit(".", 1)[-1]
    if last.endswith("[*]"):
        last = last[:-3]
    return last


# ---------------------------------------------------------------------------
# Operation-level extraction (combines body + parameters)
# ---------------------------------------------------------------------------


def extract_produces_for_operation(
    operation: dict[str, Any],
    *,
    is_swagger2: bool = False,
) -> list[FieldLeaf]:
    """Walk operation's success response schema → leaf produces with JsonPath."""
    response_schema = _pick_response_schema(operation, is_swagger2=is_swagger2)
    if not response_schema:
        return []
    return extract_leaves(response_schema, base_path="$")


def extract_consumes_for_operation(
    operation: dict[str, Any],
    path_item: dict[str, Any] | None = None,
    *,
    is_swagger2: bool = False,
    required_only: bool = True,
) -> list[FieldLeaf]:
    """Combine query/path/header parameters and request body into a flat
    consume list.

    Body fields are flattened to field-name level (the LLM-visible name) —
    binding keys by name in Stage 2/3, not by nested path. The original
    nested structure for HTTP injection is handled separately via the
    existing ``leaf_path_map`` mechanism on the tool row.
    """
    leaves: list[FieldLeaf] = []
    seen_names: set[str] = set()

    # query / path / header parameters
    all_params = (operation.get("parameters") or []) + ((path_item or {}).get("parameters") or [])
    for p in all_params:
        if not isinstance(p, dict) or "name" not in p:
            continue
        loc = p.get("in")
        if loc not in ("query", "path", "header"):
            continue
        is_required = bool(p.get("required", loc == "path"))
        if required_only and not is_required:
            continue
        if is_swagger2:
            ftype = p.get("type") or "string"
        else:
            ftype = _schema_type(p.get("schema") or {}) or "string"
        if p["name"] in seen_names:
            continue
        seen_names.add(p["name"])
        leaves.append(
            FieldLeaf(
                json_path=p["name"],  # flat for consumes
                field_name=p["name"],
                field_type=ftype,
                required=is_required,
                description=str(p.get("description") or "")[:200],
            )
        )

    # request body (flattened)
    body_schema = _pick_request_body_schema(operation, is_swagger2=is_swagger2)
    if body_schema:
        for leaf in extract_leaves(body_schema, base_path="$"):
            if required_only and not leaf.required:
                continue
            if leaf.field_name in seen_names:
                continue
            seen_names.add(leaf.field_name)
            leaves.append(
                FieldLeaf(
                    json_path=leaf.field_name,  # flat for consumes
                    field_name=leaf.field_name,
                    field_type=leaf.field_type,
                    required=leaf.required,
                    description=leaf.description,
                    enum=leaf.enum,
                )
            )

    return leaves


def _pick_response_schema(
    operation: dict[str, Any],
    *,
    is_swagger2: bool = False,
) -> dict[str, Any] | None:
    responses = operation.get("responses") or {}
    for code in ("200", "201", "default"):
        resp = responses.get(code)
        if not isinstance(resp, dict):
            continue
        # Swagger 2.0
        if "schema" in resp:
            return resp["schema"]
        # OpenAPI 3.x
        content = resp.get("content") or {}
        if "application/json" in content:
            return content["application/json"].get("schema")
    return None


def _pick_request_body_schema(
    operation: dict[str, Any],
    *,
    is_swagger2: bool = False,
) -> dict[str, Any] | None:
    if is_swagger2:
        for p in operation.get("parameters") or []:
            if isinstance(p, dict) and p.get("in") == "body":
                return p.get("schema")
        return None
    body = operation.get("requestBody") or {}
    content = body.get("content") or {}
    if "application/json" in content:
        return content["application/json"].get("schema")
    if content:
        first = next(iter(content.values()))
        return first.get("schema") if isinstance(first, dict) else None
    return None


__all__ = [
    "FieldLeaf",
    "extract_leaves",
    "extract_produces_for_operation",
    "extract_consumes_for_operation",
]
