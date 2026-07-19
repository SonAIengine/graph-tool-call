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
    const: Any = None
    exclusive_minimum: Any = None
    exclusive_maximum: Any = None
    read_only: bool = False
    write_only: bool = False
    deprecated: bool = False
    schema_ref: str = ""
    schema_combinator: str = ""
    schema_branch: int | None = None
    schema_branch_count: int | None = None
    schema_branches: list[int] = field(default_factory=list)
    required_in_branch: bool = False
    discriminator_property: str = ""
    discriminator_value: Any = None
    discriminator_values: list[Any] = field(default_factory=list)
    additional_properties: bool = False
    map_value: bool = False
    map_key_placeholder: str = ""


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
    _discriminator_property: str = "",
    _discriminator_value: Any = None,
    _schema_ref: str = "",
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
    schema = _flatten_nullable_union(schema)
    schema_ref = _schema_ref or str(schema.get("x-graph-tool-call-ref") or "")
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
        discriminator_property=_discriminator_property,
        discriminator_value=_discriminator_value,
        schema_ref=schema_ref,
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
            parent_required=parent_required,
            parent_read_only=read_only,
            parent_write_only=write_only,
            parent_deprecated=deprecated,
            schema_combinator=_schema_combinator,
            schema_branch=_schema_branch,
            schema_branch_count=_schema_branch_count,
            alternative_branch=_alternative_branch,
            discriminator_property=_discriminator_property,
            discriminator_value=_discriminator_value,
            schema_ref=schema_ref,
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
            _discriminator_property=_discriminator_property,
            _discriminator_value=_discriminator_value,
            _schema_ref=schema_ref,
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
            enum=_schema_enum(schema),
            format=str(schema.get("format") or ""),
            default=schema.get("default"),
            example=schema.get("example"),
            nullable=_schema_nullable(schema),
            pattern=str(schema.get("pattern") or ""),
            minimum=schema.get("minimum"),
            maximum=schema.get("maximum"),
            const=schema.get("const"),
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
            schema_ref=schema_ref,
            schema_combinator=_schema_combinator,
            schema_branch=_schema_branch,
            schema_branch_count=_schema_branch_count,
            schema_branches=[_schema_branch] if _schema_branch is not None else [],
            required_in_branch=parent_required if _alternative_branch else False,
            discriminator_property=_discriminator_property,
            discriminator_value=_discriminator_value,
            discriminator_values=(
                [_discriminator_value] if _discriminator_value is not None else []
            ),
        )
    ]


def _walk_object(
    schema: dict[str, Any],
    base_path: str,
    max_depth: int,
    depth: int,
    *,
    parent_required: bool = False,
    parent_read_only: bool = False,
    parent_write_only: bool = False,
    parent_deprecated: bool = False,
    schema_combinator: str = "",
    schema_branch: int | None = None,
    schema_branch_count: int | None = None,
    alternative_branch: bool = False,
    discriminator_property: str = "",
    discriminator_value: Any = None,
    schema_ref: str = "",
) -> list[FieldLeaf]:
    leaves: list[FieldLeaf] = []
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
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
            _discriminator_property=discriminator_property,
            _discriminator_value=discriminator_value,
            _schema_ref=schema_ref,
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
                    enum=_schema_enum(prop_schema),
                    format=(
                        str(prop_schema.get("format") or "")
                        if isinstance(prop_schema, dict)
                        else ""
                    ),
                    default=prop_schema.get("default") if isinstance(prop_schema, dict) else None,
                    example=prop_schema.get("example") if isinstance(prop_schema, dict) else None,
                    nullable=_schema_nullable(prop_schema),
                    pattern=(
                        str(prop_schema.get("pattern") or "")
                        if isinstance(prop_schema, dict)
                        else ""
                    ),
                    minimum=prop_schema.get("minimum") if isinstance(prop_schema, dict) else None,
                    maximum=prop_schema.get("maximum") if isinstance(prop_schema, dict) else None,
                    const=prop_schema.get("const") if isinstance(prop_schema, dict) else None,
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
                    schema_ref=schema_ref
                    or (
                        str(prop_schema.get("x-graph-tool-call-ref") or "")
                        if isinstance(prop_schema, dict)
                        else ""
                    ),
                    schema_combinator=schema_combinator,
                    schema_branch=schema_branch,
                    schema_branch_count=schema_branch_count,
                    schema_branches=[schema_branch] if schema_branch is not None else [],
                    required_in_branch=is_required if alternative_branch else False,
                    discriminator_property=discriminator_property,
                    discriminator_value=discriminator_value,
                    discriminator_values=(
                        [discriminator_value] if discriminator_value is not None else []
                    ),
                )
            )
    leaves.extend(
        _walk_additional_properties(
            schema,
            base_path=base_path,
            max_depth=max_depth,
            depth=depth,
            parent_required=parent_required,
            parent_read_only=parent_read_only,
            parent_write_only=parent_write_only,
            parent_deprecated=parent_deprecated,
            schema_combinator=schema_combinator,
            schema_branch=schema_branch,
            schema_branch_count=schema_branch_count,
            alternative_branch=alternative_branch,
            discriminator_property=discriminator_property,
            discriminator_value=discriminator_value,
            schema_ref=schema_ref,
        )
    )
    return leaves


def _walk_additional_properties(
    schema: dict[str, Any],
    *,
    base_path: str,
    max_depth: int,
    depth: int,
    parent_required: bool,
    parent_read_only: bool,
    parent_write_only: bool,
    parent_deprecated: bool,
    schema_combinator: str,
    schema_branch: int | None,
    schema_branch_count: int | None,
    alternative_branch: bool,
    discriminator_property: str,
    discriminator_value: Any,
    schema_ref: str,
) -> list[FieldLeaf]:
    additional = schema.get("additionalProperties")
    if not isinstance(additional, dict) or not additional:
        return []

    map_path = f"{base_path}.*"
    leaves = extract_leaves(
        additional,
        base_path=map_path,
        parent_required=parent_required,
        max_depth=max_depth,
        _depth=depth + 1,
        _parent_read_only=parent_read_only,
        _parent_write_only=parent_write_only,
        _parent_deprecated=parent_deprecated,
        _schema_combinator=schema_combinator,
        _schema_branch=schema_branch,
        _schema_branch_count=schema_branch_count,
        _alternative_branch=alternative_branch,
        _discriminator_property=discriminator_property,
        _discriminator_value=discriminator_value,
        _schema_ref=schema_ref or str(additional.get("x-graph-tool-call-ref") or ""),
    )

    parent_field_name = _last_path_segment(base_path)
    if not leaves and parent_field_name:
        leaves = [
            FieldLeaf(
                json_path=map_path,
                field_name=parent_field_name,
                field_type=_schema_type(additional) or "object",
                required=parent_required and not alternative_branch,
                description=str(additional.get("description") or "")[:200],
                enum=_schema_enum(additional),
                format=str(additional.get("format") or ""),
                default=additional.get("default"),
                example=additional.get("example"),
                nullable=_schema_nullable(additional),
                pattern=str(additional.get("pattern") or ""),
                minimum=additional.get("minimum"),
                maximum=additional.get("maximum"),
                const=additional.get("const"),
                exclusive_minimum=additional.get("exclusiveMinimum"),
                exclusive_maximum=additional.get("exclusiveMaximum"),
                min_length=additional.get("minLength"),
                max_length=additional.get("maxLength"),
                min_items=additional.get("minItems"),
                max_items=additional.get("maxItems"),
                min_properties=additional.get("minProperties"),
                max_properties=additional.get("maxProperties"),
                multiple_of=additional.get("multipleOf"),
                read_only=parent_read_only or bool(additional.get("readOnly", False)),
                write_only=parent_write_only or bool(additional.get("writeOnly", False)),
                deprecated=parent_deprecated or bool(additional.get("deprecated", False)),
                schema_ref=schema_ref or str(additional.get("x-graph-tool-call-ref") or ""),
                schema_combinator=schema_combinator,
                schema_branch=schema_branch,
                schema_branch_count=schema_branch_count,
                schema_branches=[schema_branch] if schema_branch is not None else [],
                required_in_branch=parent_required if alternative_branch else False,
                discriminator_property=discriminator_property,
                discriminator_value=discriminator_value,
                discriminator_values=(
                    [discriminator_value] if discriminator_value is not None else []
                ),
            )
        ]

    normalized: list[FieldLeaf] = []
    for source_leaf in leaves:
        leaf = replace(source_leaf)
        if leaf.field_name == "*" and parent_field_name:
            leaf.field_name = parent_field_name
        elif leaf.field_name == "*":
            continue
        leaf.required = False
        leaf.required_in_branch = False
        leaf.additional_properties = True
        leaf.map_value = True
        leaf.map_key_placeholder = "*"
        if not leaf.schema_ref:
            leaf.schema_ref = schema_ref or str(additional.get("x-graph-tool-call-ref") or "")
        normalized.append(leaf)
    return normalized


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
    discriminator_property: str,
    discriminator_value: Any,
    schema_ref: str,
) -> list[FieldLeaf] | None:
    """Return unioned leaves for ``oneOf``/``anyOf`` without globalizing branch requireds."""
    for key in ("oneOf", "anyOf"):
        raw_candidates = schema.get(key)
        if not isinstance(raw_candidates, list) or not raw_candidates:
            continue
        candidates = [
            candidate
            for candidate in raw_candidates
            if isinstance(candidate, dict) and not _is_null_schema(candidate)
        ]
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
                    _discriminator_property="",
                    _discriminator_value=None,
                    _schema_ref=schema_ref,
                )
            )

        branch_count = len(candidates)
        discriminator_property = _discriminator_property_name(schema)
        discriminator_values: list[Any] = []
        for index, candidate_schema in enumerate(candidates):
            candidate_ref = str(candidate_schema.get("x-graph-tool-call-ref") or schema_ref)
            discriminator_value = _branch_discriminator_value(
                schema,
                candidate_schema,
                index=index,
                branch_count=branch_count,
                discriminator_property=discriminator_property,
            )
            if discriminator_value is not None:
                discriminator_values.append(discriminator_value)
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
                    _discriminator_property=discriminator_property,
                    _discriminator_value=discriminator_value,
                    _schema_ref=candidate_ref,
                )
            )
        if discriminator_property:
            _apply_discriminator_leaf_metadata(
                leaves,
                base_path=base_path,
                field_name=discriminator_property,
                values=discriminator_values,
                schema_combinator=key,
                branch_count=branch_count,
            )
        return _merge_duplicate_leaves(leaves)
    return None


def _apply_discriminator_leaf_metadata(
    leaves: list[FieldLeaf],
    *,
    base_path: str,
    field_name: str,
    values: list[Any],
    schema_combinator: str,
    branch_count: int,
) -> None:
    matching = [leaf for leaf in leaves if leaf.field_name == field_name]
    if not matching:
        leaves.append(
            FieldLeaf(
                json_path=f"{base_path}.{field_name}",
                field_name=field_name,
                field_type="string",
                required=False,
                enum=_merge_list_values([], values),
                schema_combinator=schema_combinator,
                schema_branch_count=branch_count,
                schema_branches=list(range(branch_count)),
                required_in_branch=True,
                discriminator_property=field_name,
                discriminator_values=_merge_list_values([], values),
            )
        )
        return
    for leaf in matching:
        leaf.discriminator_property = field_name
        leaf.discriminator_values = _merge_list_values(leaf.discriminator_values, values)
        leaf.enum = _merge_list_values(leaf.enum, values)
        if not leaf.schema_combinator:
            leaf.schema_combinator = schema_combinator
        if leaf.schema_branch_count is None:
            leaf.schema_branch_count = branch_count
        if not leaf.schema_branches:
            leaf.schema_branches = list(range(branch_count))


def _discriminator_property_name(schema: dict[str, Any]) -> str:
    discriminator = schema.get("discriminator")
    if not isinstance(discriminator, dict):
        return ""
    return str(discriminator.get("propertyName") or "").strip()


def _branch_discriminator_value(
    schema: dict[str, Any],
    candidate_schema: dict[str, Any],
    *,
    index: int,
    branch_count: int,
    discriminator_property: str,
) -> Any:
    if not discriminator_property or not isinstance(candidate_schema, dict):
        return None

    prop_schema = {}
    properties = candidate_schema.get("properties")
    if isinstance(properties, dict) and isinstance(properties.get(discriminator_property), dict):
        prop_schema = properties[discriminator_property]
        if "const" in prop_schema:
            return prop_schema.get("const")
        enum = prop_schema.get("enum")
        if isinstance(enum, list) and len(enum) == 1:
            return enum[0]

    discriminator = schema.get("discriminator")
    mapping = discriminator.get("mapping") if isinstance(discriminator, dict) else {}
    if isinstance(mapping, dict) and mapping:
        schema_ref = str(candidate_schema.get("x-graph-tool-call-ref") or "")
        for value, ref in mapping.items():
            if schema_ref and str(ref) == schema_ref:
                return value
        if len(mapping) == branch_count:
            return list(mapping)[index]
    return None


def _has_extractable_shape(schema: dict[str, Any], *, base_path: str) -> bool:
    if not isinstance(schema, dict) or not schema:
        return False
    if isinstance(schema.get("properties"), dict) and schema["properties"]:
        return True
    if isinstance(schema.get("additionalProperties"), dict) and schema["additionalProperties"]:
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
        existing.discriminator_values = _merge_list_values(
            existing.discriminator_values,
            leaf.discriminator_values,
        )
        if existing.schema_branch != leaf.schema_branch:
            existing.schema_branch = None
        if existing.discriminator_value != leaf.discriminator_value:
            existing.discriminator_value = None
        for attr in (
            "description",
            "format",
            "default",
            "example",
            "nullable",
            "pattern",
            "minimum",
            "maximum",
            "const",
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
            "schema_ref",
            "schema_combinator",
            "schema_branch_count",
            "discriminator_property",
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
            if (
                isinstance(resolved_sub.get("additionalProperties"), dict)
                and "additionalProperties" not in out
            ):
                out["additionalProperties"] = resolved_sub["additionalProperties"]
        if merged_props:
            out["type"] = "object"
            out["properties"] = merged_props
        if merged_required:
            out["required"] = merged_required
        return out

    return schema


def _flatten_nullable_union(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    nullable = _schema_nullable(out)
    for key in ("anyOf", "oneOf"):
        candidates = out.get(key)
        if not isinstance(candidates, list):
            continue
        non_null = [
            candidate
            for candidate in candidates
            if not (isinstance(candidate, dict) and _is_null_schema(candidate))
        ]
        if len(non_null) == len(candidates):
            continue
        nullable = True
        if len(non_null) == 1 and isinstance(non_null[0], dict):
            merged = {
                **{k: v for k, v in out.items() if k not in {"anyOf", "oneOf"}},
                **non_null[0],
            }
            merged["nullable"] = True
            return merged
        out[key] = non_null
    if nullable:
        out["nullable"] = True
    return out


def _is_null_schema(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("type") == "null"


def _normalize_type(t: Any) -> str:
    """JSON Schema 'type' can be str or list. Pick first non-null."""
    if isinstance(t, list):
        return next((x for x in t if x and x != "null"), "")
    return t or ""


def _schema_nullable(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if schema.get("nullable") or schema.get("x-nullable"):
        return True
    schema_type = schema.get("type")
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for key in ("anyOf", "oneOf"):
        candidates = schema.get(key)
        if isinstance(candidates, list) and any(
            _is_null_schema(candidate) for candidate in candidates
        ):
            return True
    return False


def _schema_enum(schema: Any) -> list[Any]:
    if not isinstance(schema, dict):
        return []
    values = list(schema.get("enum") or [])
    if "const" in schema and schema.get("const") not in values:
        values.append(schema.get("const"))
    return values


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
            enum_vals = _schema_enum(p)
        else:
            param_schema = p.get("schema") or {}
            ftype = _schema_type(param_schema) or "string"
            # OpenAPI 3.x — enum lives under ``schema``.
            enum_vals = _schema_enum(param_schema)
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
