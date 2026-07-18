"""Product-neutral IO contract builder for graphify collections.

This module turns schema facts into the plain ``metadata.produces`` /
``metadata.consumes`` lists consumed by :class:`PathSynthesizer`. Callers can
pass product-specific field classifiers as sets or predicates; the library
keeps only the generic data shape and precedence rules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from graph_tool_call.ingest.io_contract import extract_leaves

FieldPredicate = Callable[[str], bool]


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
        consumes.append(row)

    for p in api_body_params or []:
        if not isinstance(p, dict):
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
            if leaf.field_type in ("object", "array"):
                continue
            _add_consume(
                leaf.field_name,
                field_type=leaf.field_type,
                required=leaf.required,
                enum=leaf.enum,
                location="body",
            )

    for p in parameters or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        schema = p.get("schema") if isinstance(p.get("schema"), dict) else {}
        field_type = str(schema.get("type") or p.get("type") or "string")
        enum = schema.get("enum") if "enum" in schema else p.get("enum")
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
    if field_name in names:
        return True
    if detector is None:
        return False
    try:
        return bool(detector(field_name))
    except Exception:
        return False


def _build_produces(response_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    produces: list[dict[str, Any]] = []
    if not isinstance(response_schema, dict) or not response_schema:
        return produces
    for leaf in extract_leaves(response_schema, base_path="$"):
        row: dict[str, Any] = {
            "json_path": leaf.json_path,
            "field_name": leaf.field_name,
            "field_type": leaf.field_type,
        }
        if leaf.enum:
            row["enum"] = list(leaf.enum)
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
        is_user_input = field in policies.user_input

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


__all__ = ["build_io_contract"]
