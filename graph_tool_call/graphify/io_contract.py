"""Product-neutral IO contract builder for graphify collections.

This module turns schema facts into the plain ``metadata.produces`` /
``metadata.consumes`` lists consumed by :class:`PathSynthesizer`. Callers can
pass product-specific field classifiers as sets or predicates; the library
keeps only the generic data shape and precedence rules.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from graph_tool_call.ingest.example_fields import EXAMPLE_FIELD_HINT_KEYS
from graph_tool_call.ingest.io_contract import extract_leaves
from graph_tool_call.ingest.response_shape import (
    RESPONSE_ENVELOPE_HINT_KEYS,
    annotate_response_path_aliases,
)

FieldPredicate = Callable[[str], bool]

_GENERIC_PRODUCE_FIELDS = frozenset(
    {
        "body",
        "content",
        "count",
        "data",
        "error",
        "errors",
        "items",
        "list",
        "message",
        "msg",
        "ok",
        "page",
        "result",
        "results",
        "row",
        "rows",
        "size",
        "status",
        "success",
        "total",
        "type",
        "value",
        "values",
    }
)
_DEFAULT_AUTH_FIELDS = frozenset(
    {
        "authorization",
        "accessToken",
        "access_token",
        "apiKey",
        "api_key",
        "token",
        "cookie",
        "jwt",
    }
)
_DEFAULT_PAGING_FIELDS = frozenset(
    {
        "page",
        "pageNo",
        "page_no",
        "pageNumber",
        "page_number",
        "pageSize",
        "page_size",
        "size",
        "limit",
        "offset",
        "sort",
        "orderBy",
        "order_by",
    }
)
_DEFAULT_SEARCH_FILTER_FIELDS = frozenset(
    {
        "q",
        "query",
        "keyword",
        "keywords",
        "search",
        "searchText",
        "search_text",
        "filter",
        "filters",
    }
)
_IDENTIFIER_SUFFIXES = ("id", "ids", "no", "nos", "num", "number", "code", "key", "seq", "uuid")
_CONTRACT_HINT_KEYS = (
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
    "const",
    "read_only",
    "write_only",
    "deprecated",
    "schema_ref",
    "schema_combinator",
    "schema_branch",
    "schema_branch_count",
    "schema_branches",
    "required_in_branch",
    "content_type",
    "content_types",
    "content_schema_type",
    "content_fields",
    "content_top_level_fields",
    "discriminator_property",
    "discriminator_value",
    "discriminator_values",
    "additional_properties",
    "map_value",
    "map_key_placeholder",
    *RESPONSE_ENVELOPE_HINT_KEYS,
    *EXAMPLE_FIELD_HINT_KEYS,
)


def build_io_contract(
    *,
    response_schema: dict[str, Any] | None = None,
    request_body_schema: dict[str, Any] | None = None,
    parameters: list[dict[str, Any]] | None = None,
    api_body_params: list[dict[str, Any]] | None = None,
    path_params: list[str] | None = None,
    user_input_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    context_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    auth_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    paging_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    search_filter_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    context_detector: FieldPredicate | None = None,
    auth_detector: FieldPredicate | None = None,
    paging_detector: FieldPredicate | None = None,
    search_filter_detector: FieldPredicate | None = None,
    tool_metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build ``(produces, consumes)`` dict lists from schema fragments.

    The function intentionally accepts generic hints instead of hard-coded
    product names. XGEN can pass its own context/auth/paging/search-filter
    classifiers while other users can rely on OpenAPI ``required`` flags and
    Pass-2 ``ai_metadata`` enrichment.
    """

    produces = _build_produces(response_schema)
    annotate_response_path_aliases(response_schema, produces)

    body_required, body_types, body_enums = _request_body_maps(request_body_schema)
    consumes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add_consume(
        name: str,
        *,
        field_type: str = "string",
        required: bool = False,
        enum: list[Any] | None = None,
        location: str = "",
        hints: dict[str, Any] | None = None,
    ) -> None:
        if not name:
            return
        if name in seen:
            for existing in consumes:
                if existing.get("field_name") == name:
                    existing["required"] = bool(existing.get("required")) or bool(required)
                    if field_type and existing.get("field_type") in ("", "string"):
                        existing["field_type"] = field_type
                    if enum and not existing.get("enum"):
                        existing["enum"] = list(enum)
                    if location and not existing.get("location"):
                        existing["location"] = location
                    _copy_contract_hints(hints or {}, existing)
                    break
            return
        seen.add(name)
        row: dict[str, Any] = {
            "field_name": name,
            "field_type": field_type or "string",
            "required": bool(required),
        }
        if enum is not None:
            row["enum"] = list(enum)
        if location:
            row["location"] = location
        _copy_contract_hints(hints or {}, row)
        consumes.append(row)

    for p in api_body_params or []:
        if not isinstance(p, dict):
            continue
        if p.get("read_only"):
            continue
        name = str(p.get("name") or "").strip()
        _add_consume(
            name,
            field_type=str(body_types.get(name) or p.get("type") or "string"),
            required=bool(body_required.get(name, p.get("required", False))),
            enum=body_enums.get(name) or p.get("enum"),
            location=str(p.get("in") or p.get("location") or "body"),
        )

    if isinstance(request_body_schema, dict) and request_body_schema:
        for leaf in extract_leaves(request_body_schema, base_path="$"):
            if leaf.read_only:
                continue
            if leaf.field_type in ("object", "array"):
                continue
            _add_consume(
                leaf.field_name,
                field_type=leaf.field_type,
                required=leaf.required,
                enum=leaf.enum,
                location="body",
                hints=_leaf_hints(leaf),
            )

    for p in parameters or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        schema = p.get("schema") if isinstance(p.get("schema"), dict) else {}
        field_type = str(schema.get("type") or p.get("type") or "string")
        enum = _schema_enum(schema) if isinstance(schema, dict) else p.get("enum")
        if not enum:
            enum = p.get("enum")
        loc = str(p.get("in") or p.get("location") or "")
        _add_consume(
            name,
            field_type=field_type,
            required=bool(p.get("required", loc == "path")),
            enum=list(enum) if isinstance(enum, list) else None,
            location=loc,
        )

    for pname in path_params or []:
        _add_consume(str(pname), required=True, location="path")

    policies = _Policy(
        user_input=_as_set(user_input_field_names),
        context=_as_set(context_field_names),
        auth=_as_set(auth_field_names),
        paging=_as_set(paging_field_names),
        search_filter=_as_set(search_filter_field_names),
        context_detector=context_detector,
        auth_detector=auth_detector,
        paging_detector=paging_detector,
        search_filter_detector=search_filter_detector,
    )
    _apply_semantics(produces, consumes, tool_metadata or {})
    _apply_field_policies(consumes, policies)

    return produces, consumes


def promote_api_contract_signals(
    schemas: list[Any],
    *,
    max_produces_per_tool: int = 32,
    max_consumes_per_tool: int = 32,
    max_field_frequency_ratio: float = 0.12,
    user_input_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    context_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    auth_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    paging_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    search_filter_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    context_detector: FieldPredicate | None = None,
    auth_detector: FieldPredicate | None = None,
    paging_detector: FieldPredicate | None = None,
    search_filter_detector: FieldPredicate | None = None,
    infer_semantic_tags: bool = True,
    promote_rare_produces: bool = False,
    index_promoted_contract_fields: bool = False,
) -> dict[str, int]:
    """Promote selected raw OpenAPI contract rows into graph/search IO signals.

    Plain OpenAPI ingest stores exhaustive request/response leaves in
    ``metadata.api_contract``. Exhaustive leaves are excellent for execution,
    but indexing every field from a large Swagger spec makes search noisy.
    This helper applies deterministic, product-neutral filters and merges only
    useful rows into top-level ``metadata.produces`` / ``metadata.consumes``.

    The function mutates the supplied schemas in place and returns counters so
    callers can report exactly how much contract signal entered the graph.
    """

    policy = _Policy(
        user_input=_as_set(user_input_field_names),
        context=_as_set(context_field_names),
        auth=_as_set(auth_field_names) | set(_DEFAULT_AUTH_FIELDS),
        paging=_as_set(paging_field_names) | set(_DEFAULT_PAGING_FIELDS),
        search_filter=_as_set(search_filter_field_names) | set(_DEFAULT_SEARCH_FILTER_FIELDS),
        context_detector=context_detector,
        auth_detector=auth_detector,
        paging_detector=paging_detector,
        search_filter_detector=search_filter_detector,
    )
    produce_freq = _contract_field_frequency(schemas, direction="produces")
    tool_count = max(1, len(schemas))
    max_field_frequency = max(2, int(tool_count * max_field_frequency_ratio))

    stats = {
        "tools_promoted": 0,
        "produces_added": 0,
        "consumes_added": 0,
        "produces_skipped": 0,
        "consumes_skipped": 0,
    }

    for schema in schemas:
        metadata = dict(getattr(schema, "metadata", None) or {})
        contract = (
            metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
        )
        promoted_produces: list[dict[str, Any]] = []
        promoted_consumes: list[dict[str, Any]] = []

        for row in contract.get("produces") or []:
            promoted = _promote_produce_row(
                row,
                produce_freq=produce_freq,
                max_field_frequency=max_field_frequency,
                infer_semantic_tags=infer_semantic_tags,
                promote_rare_produces=promote_rare_produces,
                search_signal=index_promoted_contract_fields,
            )
            if promoted is None:
                stats["produces_skipped"] += 1
                continue
            promoted_produces.append(promoted)
        promoted_produces.sort(key=_promoted_produce_sort_key)
        if max_produces_per_tool >= 0:
            promoted_produces = promoted_produces[:max_produces_per_tool]

        for row in contract.get("consumes") or []:
            promoted = _promote_consume_row(
                row,
                policy=policy,
                infer_semantic_tags=infer_semantic_tags,
                search_signal=index_promoted_contract_fields,
            )
            if promoted is None:
                stats["consumes_skipped"] += 1
                continue
            promoted_consumes.append(promoted)
        promoted_consumes.sort(key=_promoted_consume_sort_key)
        if max_consumes_per_tool >= 0:
            promoted_consumes = promoted_consumes[:max_consumes_per_tool]

        produces_added = _merge_rows(metadata, "produces", promoted_produces)
        consumes_added = _merge_rows(metadata, "consumes", promoted_consumes)
        if produces_added or consumes_added:
            metadata.setdefault("contract_signal_policy", {})
            metadata["contract_signal_policy"].update(
                {
                    "source": "api_contract",
                    "max_produces_per_tool": max_produces_per_tool,
                    "max_consumes_per_tool": max_consumes_per_tool,
                    "max_field_frequency_ratio": max_field_frequency_ratio,
                    "max_field_frequency": max_field_frequency,
                    "infer_semantic_tags": infer_semantic_tags,
                    "promote_rare_produces": promote_rare_produces,
                    "index_promoted_contract_fields": index_promoted_contract_fields,
                }
            )
            schema.metadata = metadata
            stats["tools_promoted"] += 1
            stats["produces_added"] += produces_added
            stats["consumes_added"] += consumes_added

    return stats


class _Policy:
    def __init__(
        self,
        *,
        user_input: set[str],
        context: set[str],
        auth: set[str],
        paging: set[str],
        search_filter: set[str],
        context_detector: FieldPredicate | None,
        auth_detector: FieldPredicate | None,
        paging_detector: FieldPredicate | None,
        search_filter_detector: FieldPredicate | None,
    ) -> None:
        self.user_input = user_input
        self.context = context
        self.auth = auth
        self.paging = paging
        self.search_filter = search_filter
        self.context_detector = context_detector
        self.auth_detector = auth_detector
        self.paging_detector = paging_detector
        self.search_filter_detector = search_filter_detector


def _as_set(values: set[str] | list[str] | tuple[str, ...] | None) -> set[str]:
    return {str(v) for v in values or [] if str(v)}


def _matches(field_name: str, names: set[str], detector: FieldPredicate | None) -> bool:
    if _name_matches(field_name, names):
        return True
    if detector is None:
        return False
    try:
        return bool(detector(field_name))
    except Exception:
        return False


def _name_matches(field_name: str, names: set[str]) -> bool:
    if field_name in names:
        return True
    field_key = _canonical_field_key(field_name)
    return bool(field_key and field_key in {_canonical_field_key(name) for name in names})


def _build_produces(response_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    produces: list[dict[str, Any]] = []
    if not isinstance(response_schema, dict) or not response_schema:
        return produces
    for leaf in extract_leaves(response_schema, base_path="$"):
        if leaf.write_only:
            continue
        row: dict[str, Any] = {
            "json_path": leaf.json_path,
            "field_name": leaf.field_name,
            "field_type": leaf.field_type,
        }
        if leaf.enum:
            row["enum"] = list(leaf.enum)
        _copy_leaf_hints(leaf, row)
        produces.append(row)
    return produces


def _request_body_maps(
    request_body_schema: dict[str, Any] | None,
) -> tuple[dict[str, bool], dict[str, str], dict[str, list[Any]]]:
    required: dict[str, bool] = {}
    types: dict[str, str] = {}
    enums: dict[str, list[Any]] = {}
    if not isinstance(request_body_schema, dict) or not request_body_schema:
        return required, types, enums
    for leaf in extract_leaves(request_body_schema, base_path="$"):
        if leaf.read_only:
            continue
        if leaf.field_type in ("object", "array"):
            continue
        required[leaf.field_name] = bool(leaf.required)
        types[leaf.field_name] = leaf.field_type
        if leaf.enum:
            enums[leaf.field_name] = list(leaf.enum)
    return required, types, enums


def _ai_metadata(tool_metadata: dict[str, Any]) -> dict[str, Any]:
    ai = tool_metadata.get("ai_metadata") if isinstance(tool_metadata, dict) else {}
    if isinstance(ai, dict):
        return ai
    return tool_metadata if isinstance(tool_metadata, dict) else {}


def _apply_semantics(
    produces: list[dict[str, Any]],
    consumes: list[dict[str, Any]],
    tool_metadata: dict[str, Any],
) -> None:
    ai = _ai_metadata(tool_metadata)
    prod_sem = {
        str(p.get("json_path") or ""): str(p.get("semantic") or "")
        for p in (ai.get("produces_semantics") or [])
        if isinstance(p, dict)
    }
    for p in produces:
        tag = prod_sem.get(str(p.get("json_path") or ""))
        if tag:
            p["semantic_tag"] = tag

    cons_info = {}
    for c in ai.get("consumes_semantics") or []:
        if not isinstance(c, dict) or not c.get("field"):
            continue
        raw_kind = str(c.get("kind") or "data").strip().lower()
        kind = raw_kind if raw_kind in ("data", "context", "auth") else "data"
        cons_info[str(c.get("field"))] = {
            "semantic_tag": str(c.get("semantic") or ""),
            "kind": kind,
        }

    for c in consumes:
        info = cons_info.get(str(c.get("field_name") or ""))
        if not info:
            continue
        if info["semantic_tag"]:
            c["semantic_tag"] = info["semantic_tag"]
        c["kind"] = info["kind"]
        if info["kind"] == "data":
            c["required"] = True
        elif info["kind"] in ("context", "auth"):
            c["required"] = False


def _apply_field_policies(consumes: list[dict[str, Any]], policies: _Policy) -> None:
    for c in consumes:
        field = str(c.get("field_name") or "")
        is_user_input = _name_matches(field, policies.user_input)

        if _matches(field, policies.auth, policies.auth_detector):
            c["kind"] = "auth"
            c["required"] = False
            continue
        if _matches(field, policies.context, policies.context_detector):
            c["kind"] = "context"
            c["required"] = False
            continue
        if _matches(field, policies.paging, policies.paging_detector) and not is_user_input:
            c["kind"] = "context"
            c["required"] = False
            continue
        if (
            _matches(field, policies.search_filter, policies.search_filter_detector)
            and not is_user_input
        ):
            c.setdefault("kind", "data")
            c["required"] = False
            continue
        c.setdefault("kind", "data")
        if is_user_input:
            c["required"] = True


def _contract_field_frequency(schemas: list[Any], *, direction: str) -> Counter[str]:
    freq: Counter[str] = Counter()
    for schema in schemas:
        metadata = getattr(schema, "metadata", None) or {}
        contract = (
            metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
        )
        seen_in_tool: set[str] = set()
        for row in contract.get(direction) or []:
            if not isinstance(row, dict):
                continue
            key = _canonical_field_key(row.get("field_name"))
            if key:
                seen_in_tool.add(key)
        freq.update(seen_in_tool)
    return freq


def _promote_produce_row(
    row: Any,
    *,
    produce_freq: Counter[str],
    max_field_frequency: int,
    infer_semantic_tags: bool,
    promote_rare_produces: bool,
    search_signal: bool,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    field_name = str(row.get("field_name") or "").strip()
    if not field_name:
        return None
    if row.get("write_only"):
        return None
    field_key = _canonical_field_key(field_name)
    if field_key in _GENERIC_PRODUCE_FIELDS:
        return None
    identifier = _is_identifier_like(field_name)
    rare = produce_freq.get(field_key, 0) <= max_field_frequency
    semantic = str(row.get("semantic_tag") or "").strip()
    if not (semantic or identifier or (promote_rare_produces and rare)):
        return None

    promoted = _copy_contract_field(row)
    promoted["contract_source"] = "api_contract"
    promoted["search_signal"] = bool(search_signal)
    promoted["signal_score"] = _produce_signal_score(
        promoted,
        identifier=identifier,
        rare=rare,
    )
    if infer_semantic_tags and not promoted.get("semantic_tag"):
        promoted["semantic_tag"] = _semantic_tag(field_name)
        promoted["semantic_inferred_from"] = "field_name"
    return promoted


def _promote_consume_row(
    row: Any,
    *,
    policy: _Policy,
    infer_semantic_tags: bool,
    search_signal: bool,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    field_name = str(row.get("field_name") or "").strip()
    if not field_name:
        return None
    if row.get("read_only"):
        return None

    location = str(row.get("location") or row.get("in") or "").strip().lower()
    required = bool(row.get("required") or location == "path")
    is_user_input = _name_matches(field_name, policy.user_input)
    kind = _consume_kind(field_name, location=location, policy=policy)
    if kind in ("auth", "context"):
        required = False
    elif is_user_input:
        required = True

    should_promote = (
        required
        or is_user_input
        or bool(row.get("enum"))
        or _is_identifier_like(field_name)
        or _matches(field_name, policy.search_filter, policy.search_filter_detector)
        or kind in ("context", "auth")
    )
    if not should_promote:
        return None

    promoted = _copy_contract_field(row)
    promoted["location"] = location
    promoted["required"] = required
    promoted["kind"] = kind
    promoted["contract_source"] = "api_contract"
    promoted["search_signal"] = bool(search_signal)
    promoted["signal_score"] = _consume_signal_score(promoted)
    if infer_semantic_tags and not promoted.get("semantic_tag") and kind == "data":
        promoted["semantic_tag"] = _semantic_tag(field_name)
        promoted["semantic_inferred_from"] = "field_name"
    return promoted


def _copy_contract_field(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "field_name": str(row.get("field_name") or "").strip(),
        "field_type": str(row.get("field_type") or "string"),
    }
    for key in ("json_path", "required", "location", "kind", "semantic_tag", "description"):
        value = row.get(key)
        if value not in (None, ""):
            out[key] = value
    for key in _CONTRACT_HINT_KEYS:
        value = row.get(key)
        if value not in (None, "", []):
            out[key] = value
    enum = row.get("enum")
    if isinstance(enum, list):
        out["enum"] = list(enum)
    return out


def _copy_leaf_hints(leaf: Any, row: dict[str, Any]) -> None:
    for key in _CONTRACT_HINT_KEYS:
        value = getattr(leaf, key, None)
        if value not in (None, "", []):
            row[key] = value


def _leaf_hints(leaf: Any) -> dict[str, Any]:
    row: dict[str, Any] = {}
    _copy_leaf_hints(leaf, row)
    return row


def _copy_contract_hints(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in _CONTRACT_HINT_KEYS:
        value = source.get(key)
        if value not in (None, "", []):
            target[key] = value


def _schema_enum(schema: dict[str, Any]) -> list[Any]:
    values = list(schema.get("enum") or [])
    if "const" in schema and schema.get("const") not in values:
        values.append(schema.get("const"))
    return values


def _consume_kind(field_name: str, *, location: str, policy: _Policy) -> str:
    if location in ("header", "cookie") or _matches(field_name, policy.auth, policy.auth_detector):
        return "auth"
    if _matches(field_name, policy.context, policy.context_detector):
        return "context"
    if _matches(field_name, policy.paging, policy.paging_detector):
        return "context"
    return "data"


def _merge_rows(metadata: dict[str, Any], key: str, incoming: list[dict[str, Any]]) -> int:
    rows = [dict(r) for r in metadata.get(key) or [] if isinstance(r, dict)]
    by_identity = {_row_identity(r, direction=key): r for r in rows}
    added = 0
    for row in incoming:
        identity = _row_identity(row, direction=key)
        existing = by_identity.get(identity)
        if existing is None:
            rows.append(row)
            by_identity[identity] = row
            added += 1
            continue
        for merge_key in (
            "semantic_tag",
            "semantic_inferred_from",
            "kind",
            "location",
            "json_path",
            "enum",
            "contract_source",
            "search_signal",
            "signal_score",
            *_CONTRACT_HINT_KEYS,
        ):
            if merge_key in row and not existing.get(merge_key):
                existing[merge_key] = row[merge_key]
        if bool(row.get("required")):
            existing["required"] = True
    if rows:
        metadata[key] = rows
    return added


def _row_identity(row: dict[str, Any], *, direction: str) -> tuple[str, str, str]:
    field = _canonical_field_key(row.get("field_name"))
    semantic = str(row.get("semantic_tag") or "")
    if direction == "produces":
        return field, semantic, str(row.get("json_path") or "")
    return field, semantic, str(row.get("location") or row.get("kind") or "")


def _promoted_produce_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    return (-int(row.get("signal_score") or 0), str(row.get("field_name") or ""))


def _promoted_consume_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    return (-int(row.get("signal_score") or 0), str(row.get("field_name") or ""))


def _produce_signal_score(row: dict[str, Any], *, identifier: bool, rare: bool) -> int:
    score = 0
    if row.get("semantic_tag"):
        score += 5
    if identifier:
        score += 4
    if rare:
        score += 2
    if row.get("enum"):
        score += 1
    return score


def _consume_signal_score(row: dict[str, Any]) -> int:
    score = 0
    if row.get("semantic_tag"):
        score += 5
    if row.get("required"):
        score += 4
    if row.get("location") == "path":
        score += 3
    if row.get("enum"):
        score += 2
    if _is_identifier_like(str(row.get("field_name") or "")):
        score += 2
    if row.get("kind") in ("context", "auth"):
        score += 1
    return score


def _canonical_field_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _semantic_tag(field_name: str) -> str:
    words = _split_field_words(field_name)
    return "_".join(words) if words else _canonical_field_key(field_name)


def _is_identifier_like(field_name: str) -> bool:
    words = _split_field_words(field_name)
    if not words:
        return False
    if len(words) == 1 and words[0] in {"id", "no", "key", "code", "seq"}:
        return False
    last = words[-1]
    return last in _IDENTIFIER_SUFFIXES


def _split_field_words(field_name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(field_name or ""))
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return [token.lower() for token in re.split(r"[^A-Za-z0-9]+", spaced) if token]


__all__ = ["build_io_contract", "promote_api_contract_signals"]
