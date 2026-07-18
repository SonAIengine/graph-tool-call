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

from dataclasses import dataclass, field, replace
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
    format: str = ""
    default: Any = None
    example: Any = None
    nullable: bool = False
    pattern: str = ""
    minimum: Any = None
    maximum: Any = None
    min_length: int | None = None
    max_length: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    min_properties: int | None = None
    max_properties: int | None = None
    multiple_of: Any = None
    exclusive_minimum: Any = None
    exclusive_maximum: Any = None
    read_only: bool = False
    write_only: bool = False
    deprecated: bool = False
    schema_combinator: str = ""
    schema_branch: int | None = None
    schema_branch_count: int | None = None
    schema_branches: list[int] = field(default_factory=list)
    required_in_branch: bool = False


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
    _parent_read_only: bool = False,
    _parent_write_only: bool = False,
    _parent_deprecated: bool = False,
    _schema_combinator: str = "",
    _schema_branch: int | None = None,
    _schema_branch_count: int | None = None,
    _alternative_branch: bool = False,
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
    read_only = _parent_read_only or bool(schema.get("readOnly", False))
    write_only = _parent_write_only or bool(schema.get("writeOnly", False))
    deprecated = _parent_deprecated or bool(schema.get("deprecated", False))

    alternative_leaves = _extract_alternative_leaves(
        schema,
        base_path=base_path,
        parent_required=parent_required,
        max_depth=max_depth,
        depth=_depth,
        read_only=read_only,
        write_only=write_only,
        deprecated=deprecated,
        schema_combinator=_schema_combinator,
        schema_branch=_schema_branch,
        schema_branch_count=_schema_branch_count,
        alternative_branch=_alternative_branch,
    )
    if alternative_leaves is not None:
        return alternative_leaves

    schema_type = _normalize_type(schema.get("type"))

    # Object: walk properties
    if schema_type == "object" or "properties" in schema:
        return _walk_object(
            schema,
            base_path,
            max_depth,
            _depth,
            parent_read_only=read_only,
            parent_write_only=write_only,
            parent_deprecated=deprecated,
            schema_combinator=_schema_combinator,
            schema_branch=_schema_branch,
            schema_branch_count=_schema_branch_count,
            alternative_branch=_alternative_branch,
        )

    # Array: walk items with [*] suffix
    if schema_type == "array":
        items = schema.get("items") or {}
        return extract_leaves(
            items,
            base_path=f"{base_path}[*]",
            parent_required=parent_required,
            max_depth=max_depth,
            _depth=_depth + 1,
            _parent_read_only=read_only,
            _parent_write_only=write_only,
            _parent_deprecated=deprecated,
            _schema_combinator=_schema_combinator,
            _schema_branch=_schema_branch,
            _schema_branch_count=_schema_branch_count,
            _alternative_branch=_alternative_branch,
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
            required=parent_required and not _alternative_branch,
            description=str(schema.get("description") or "")[:200],
            enum=list(schema.get("enum") or []),
            format=str(schema.get("format") or ""),
            default=schema.get("default"),
            example=schema.get("example"),
            nullable=bool(schema.get("nullable", False)),
            pattern=str(schema.get("pattern") or ""),
            minimum=schema.get("minimum"),
            maximum=schema.get("maximum"),
            exclusive_minimum=schema.get("exclusiveMinimum"),
            exclusive_maximum=schema.get("exclusiveMaximum"),
            min_length=schema.get("minLength"),
            max_length=schema.get("maxLength"),
            min_items=schema.get("minItems"),
            max_items=schema.get("maxItems"),
            min_properties=schema.get("minProperties"),
            max_properties=schema.get("maxProperties"),
            multiple_of=schema.get("multipleOf"),
            read_only=read_only,
            write_only=write_only,
            deprecated=deprecated,
            schema_combinator=_schema_combinator,
            schema_branch=_schema_branch,
            schema_branch_count=_schema_branch_count,
            schema_branches=[_schema_branch] if _schema_branch is not None else [],
            required_in_branch=parent_required if _alternative_branch else False,
        )
    ]


def _walk_object(
    schema: dict[str, Any],
    base_path: str,
    max_depth: int,
    depth: int,
    *,
    parent_read_only: bool = False,
    parent_write_only: bool = False,
    parent_deprecated: bool = False,
    schema_combinator: str = "",
    schema_branch: int | None = None,
    schema_branch_count: int | None = None,
    alternative_branch: bool = False,
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
            _parent_read_only=parent_read_only,
            _parent_write_only=parent_write_only,
            _parent_deprecated=parent_deprecated,
            _schema_combinator=schema_combinator,
            _schema_branch=schema_branch,
            _schema_branch_count=schema_branch_count,
            _alternative_branch=alternative_branch,
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
                    required=is_required and not alternative_branch,
                    description=(
                        str(prop_schema.get("description") or "")[:200]
                        if isinstance(prop_schema, dict)
                        else ""
                    ),
                    enum=(
                        list(prop_schema.get("enum") or []) if isinstance(prop_schema, dict) else []
                    ),
                    format=(
                        str(prop_schema.get("format") or "")
                        if isinstance(prop_schema, dict)
                        else ""
                    ),
                    default=prop_schema.get("default") if isinstance(prop_schema, dict) else None,
                    example=prop_schema.get("example") if isinstance(prop_schema, dict) else None,
                    nullable=(
                        bool(prop_schema.get("nullable", False))
                        if isinstance(prop_schema, dict)
                        else False
                    ),
                    pattern=(
                        str(prop_schema.get("pattern") or "")
                        if isinstance(prop_schema, dict)
                        else ""
                    ),
                    minimum=prop_schema.get("minimum") if isinstance(prop_schema, dict) else None,
                    maximum=prop_schema.get("maximum") if isinstance(prop_schema, dict) else None,
                    exclusive_minimum=(
                        prop_schema.get("exclusiveMinimum")
                        if isinstance(prop_schema, dict)
                        else None
                    ),
                    exclusive_maximum=(
                        prop_schema.get("exclusiveMaximum")
                        if isinstance(prop_schema, dict)
                        else None
                    ),
                    min_length=(
                        prop_schema.get("minLength") if isinstance(prop_schema, dict) else None
                    ),
                    max_length=(
                        prop_schema.get("maxLength") if isinstance(prop_schema, dict) else None
                    ),
                    min_items=(
                        prop_schema.get("minItems") if isinstance(prop_schema, dict) else None
                    ),
                    max_items=(
                        prop_schema.get("maxItems") if isinstance(prop_schema, dict) else None
                    ),
                    min_properties=(
                        prop_schema.get("minProperties") if isinstance(prop_schema, dict) else None
                    ),
                    max_properties=(
                        prop_schema.get("maxProperties") if isinstance(prop_schema, dict) else None
                    ),
                    multiple_of=(
                        prop_schema.get("multipleOf") if isinstance(prop_schema, dict) else None
                    ),
                    read_only=parent_read_only
                    or (
                        bool(prop_schema.get("readOnly", False))
                        if isinstance(prop_schema, dict)
                        else False
                    ),
                    write_only=parent_write_only
                    or (
                        bool(prop_schema.get("writeOnly", False))
                        if isinstance(prop_schema, dict)
                        else False
                    ),
                    deprecated=parent_deprecated
                    or (
                        bool(prop_schema.get("deprecated", False))
                        if isinstance(prop_schema, dict)
                        else False
                    ),
                    schema_combinator=schema_combinator,
                    schema_branch=schema_branch,
                    schema_branch_count=schema_branch_count,
                    schema_branches=[schema_branch] if schema_branch is not None else [],
                    required_in_branch=is_required if alternative_branch else False,
                )
            )
    return leaves


def _extract_alternative_leaves(
    schema: dict[str, Any],
    *,
    base_path: str,
    parent_required: bool,
    max_depth: int,
    depth: int,
    read_only: bool,
    write_only: bool,
    deprecated: bool,
    schema_combinator: str,
    schema_branch: int | None,
    schema_branch_count: int | None,
    alternative_branch: bool,
) -> list[FieldLeaf] | None:
    """Return unioned leaves for ``oneOf``/``anyOf`` without globalizing branch requireds."""
    for key in ("oneOf", "anyOf"):
        raw_candidates = schema.get(key)
        if not isinstance(raw_candidates, list) or not raw_candidates:
            continue
        candidates = [candidate for candidate in raw_candidates if isinstance(candidate, dict)]
        if not candidates:
            continue

        leaves: list[FieldLeaf] = []
        base_schema = {k: v for k, v in schema.items() if k not in {"oneOf", "anyOf"}}
        if _has_extractable_shape(base_schema, base_path=base_path):
            leaves.extend(
                extract_leaves(
                    base_schema,
                    base_path=base_path,
                    parent_required=parent_required,
                    max_depth=max_depth,
                    _depth=depth,
                    _parent_read_only=read_only,
                    _parent_write_only=write_only,
                    _parent_deprecated=deprecated,
                    _schema_combinator=schema_combinator,
                    _schema_branch=schema_branch,
                    _schema_branch_count=schema_branch_count,
                    _alternative_branch=alternative_branch,
                )
            )

        branch_count = len(candidates)
        for index, candidate_schema in enumerate(candidates):
            leaves.extend(
                extract_leaves(
                    candidate_schema,
                    base_path=base_path,
                    parent_required=parent_required,
                    max_depth=max_depth,
                    _depth=depth + 1,
                    _parent_read_only=read_only,
                    _parent_write_only=write_only,
                    _parent_deprecated=deprecated,
                    _schema_combinator=key,
                    _schema_branch=index,
                    _schema_branch_count=branch_count,
                    _alternative_branch=True,
                )
            )
        return _merge_duplicate_leaves(leaves)
    return None


def _has_extractable_shape(schema: dict[str, Any], *, base_path: str) -> bool:
    if not isinstance(schema, dict) or not schema:
        return False
    if isinstance(schema.get("properties"), dict) and schema["properties"]:
        return True
    if _normalize_type(schema.get("type")) == "array" and isinstance(schema.get("items"), dict):
        return True
    if base_path != "$" and (
        _normalize_type(schema.get("type")) not in ("", "object", "array") or schema.get("enum")
    ):
        return True
    return False


def _merge_duplicate_leaves(leaves: list[FieldLeaf]) -> list[FieldLeaf]:
    merged: list[FieldLeaf] = []
    by_key: dict[tuple[str, str], FieldLeaf] = {}
    for leaf in leaves:
        key = (leaf.json_path, leaf.field_name)
        existing = by_key.get(key)
        if existing is None:
            merged.append(leaf)
            by_key[key] = leaf
            continue
        existing.required = existing.required or leaf.required
        existing.required_in_branch = existing.required_in_branch or leaf.required_in_branch
        existing.enum = _merge_list_values(existing.enum, leaf.enum)
        existing.schema_branches = _merge_list_values(
            existing.schema_branches,
            leaf.schema_branches,
        )
        if existing.schema_branch != leaf.schema_branch:
            existing.schema_branch = None
        for attr in (
            "description",
            "format",
            "default",
            "example",
            "nullable",
            "pattern",
            "minimum",
            "maximum",
            "exclusive_minimum",
            "exclusive_maximum",
            "min_length",
            "max_length",
            "min_items",
            "max_items",
            "min_properties",
            "max_properties",
            "multiple_of",
            "read_only",
            "write_only",
            "deprecated",
            "schema_combinator",
            "schema_branch_count",
        ):
            existing_value = getattr(existing, attr)
            leaf_value = getattr(leaf, attr)
            if existing_value in (None, "", [], False) and leaf_value not in (None, "", []):
                setattr(existing, attr, leaf_value)
    return merged


def _merge_list_values(left: list[Any], right: list[Any]) -> list[Any]:
    merged = list(left or [])
    for value in right or []:
        if value not in merged:
            merged.append(value)
    return merged


def _resolve_combinators(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``allOf``.

    ``oneOf`` / ``anyOf`` are handled by the walker as additive branch unions so
    we do not lose valid request/response fields after the first branch.
    """
    if "allOf" in schema and isinstance(schema["allOf"], list):
        merged_props: dict[str, Any] = dict(schema.get("properties") or {})
        merged_required: list[str] = list(schema.get("required") or [])
        out = {k: v for k, v in schema.items() if k != "allOf"}
        for sub in schema["allOf"]:
            if not isinstance(sub, dict):
                continue
            resolved_sub = _resolve_combinators(sub)
            merged_props.update(resolved_sub.get("properties") or {})
            for r in resolved_sub.get("required") or []:
                if r not in merged_required:
                    merged_required.append(r)
            for key in ("oneOf", "anyOf"):
                sub_candidates = resolved_sub.get(key)
                if isinstance(sub_candidates, list) and sub_candidates:
                    out.setdefault(key, [])
                    if isinstance(out[key], list):
                        out[key].extend(sub_candidates)
            for key in ("readOnly", "writeOnly", "deprecated", "nullable"):
                if resolved_sub.get(key) and key not in out:
                    out[key] = resolved_sub[key]
        if merged_props:
            out["type"] = "object"
            out["properties"] = merged_props
        if merged_required:
            out["required"] = merged_required
        return out

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
    return [leaf for leaf in extract_leaves(response_schema, base_path="$") if not leaf.write_only]


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
            # Swagger 2.0 — enum lives directly on the parameter object.
            enum_vals = p.get("enum") or []
        else:
            param_schema = p.get("schema") or {}
            ftype = _schema_type(param_schema) or "string"
            # OpenAPI 3.x — enum lives under ``schema``.
            enum_vals = param_schema.get("enum") or [] if isinstance(param_schema, dict) else []
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
                enum=list(enum_vals),
            )
        )

    # request body (flattened)
    body_schema = _pick_request_body_schema(operation, is_swagger2=is_swagger2)
    if body_schema:
        for leaf in extract_leaves(body_schema, base_path="$"):
            if leaf.read_only:
                continue
            if required_only and not leaf.required:
                continue
            if leaf.field_name in seen_names:
                continue
            seen_names.add(leaf.field_name)
            leaves.append(replace(leaf, json_path=leaf.field_name))  # flat for consumes

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
        for content_type, media in content.items():
            if isinstance(content_type, str) and content_type.endswith("+json"):
                return media.get("schema") if isinstance(media, dict) else None
        if "*/*" in content:
            media = content["*/*"]
            return media.get("schema") if isinstance(media, dict) else None
        for media in content.values():
            if isinstance(media, dict) and media.get("schema"):
                return media["schema"]
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
