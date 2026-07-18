"""Response shape hints for OpenAPI-derived IO contracts."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

RESPONSE_ENVELOPE_HINT_KEYS = (
    "response_envelope_path",
    "response_collection_path",
    "response_item_path",
    "value_path_aliases",
)

_RESPONSE_ENVELOPE_META_FIELDS = frozenset(
    {
        "code",
        "error",
        "errorcode",
        "errors",
        "message",
        "msg",
        "ok",
        "reason",
        "status",
        "success",
        "timestamp",
        "traceid",
    }
)
_RESPONSE_ENVELOPE_WRAPPER_FIELDS = frozenset(
    {
        "body",
        "content",
        "data",
        "payload",
        "result",
        "resultdata",
        "response",
    }
)


def annotate_response_path_aliases(
    schema: dict[str, Any] | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Annotate response rows with envelope and value-path alias hints.

    Many business APIs wrap useful payloads as ``{code, message, data: ...}``,
    while execution adapters may return either the raw body or a normalized
    ``{"body": ...}`` object. The canonical OpenAPI ``json_path`` remains
    authoritative; aliases are additive fallback paths used by planners and
    value extractors when the runtime shape differs from the spec wrapper.
    """

    if not rows:
        return {}

    envelope = response_envelope_metadata(schema, rows)
    wrapper_path = str(envelope.get("wrapper_path") or "")
    collection_path = str(envelope.get("collection_path") or "")
    item_path = str(envelope.get("item_path") or collection_path)

    for row in rows:
        raw_path = str(row.get("json_path") or "")
        aliases = _response_value_path_aliases(raw_path, envelope)
        if aliases:
            row["value_path_aliases"] = aliases
        if wrapper_path and _json_path_startswith(raw_path, wrapper_path):
            row["response_envelope_path"] = wrapper_path
        if collection_path and _json_path_startswith(raw_path, collection_path):
            row["response_collection_path"] = collection_path
            row["response_item_path"] = item_path

    return envelope


def response_envelope_metadata(
    schema: dict[str, Any] | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return deterministic response wrapper/collection metadata."""

    root_fields = _response_root_fields(rows)
    if not root_fields:
        collection_path = _response_collection_path(rows, wrapper_path="")
        return _compact_envelope(collection_path=collection_path)

    metadata_fields = [
        name
        for name in root_fields
        if _canonical_response_key(name) in _RESPONSE_ENVELOPE_META_FIELDS
    ]
    business_fields = [name for name in root_fields if name not in metadata_fields]
    wrapper_field = _select_wrapper_field(schema, rows, business_fields, metadata_fields)
    wrapper_path = f"$.{wrapper_field}" if wrapper_field else ""
    collection_path = _response_collection_path(rows, wrapper_path=wrapper_path)
    envelope = _compact_envelope(
        wrapper_field=wrapper_field,
        wrapper_path=wrapper_path,
        collection_path=collection_path,
        metadata_fields=metadata_fields,
    )
    if envelope:
        envelope["alias_strategy"] = "openapi_response_envelope_v1"
    return envelope


def _select_wrapper_field(
    schema: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    business_fields: list[str],
    metadata_fields: list[str],
) -> str:
    if not business_fields:
        return ""

    wrapper_candidates = [
        field
        for field in business_fields
        if _canonical_response_key(field) in _RESPONSE_ENVELOPE_WRAPPER_FIELDS
        and _has_nested_response_path(rows, field)
    ]
    if len(wrapper_candidates) == 1:
        return wrapper_candidates[0]

    if (
        len(business_fields) == 1
        and metadata_fields
        and _has_nested_response_path(rows, business_fields[0])
    ):
        return business_fields[0]

    properties = (schema or {}).get("properties") if isinstance(schema, dict) else {}
    if not isinstance(properties, dict):
        return ""
    typed_candidates: list[str] = []
    for field in business_fields:
        prop = properties.get(field)
        if not isinstance(prop, dict):
            continue
        prop_type = prop.get("type")
        if _canonical_response_key(field) in _RESPONSE_ENVELOPE_WRAPPER_FIELDS and prop_type in (
            "object",
            "array",
        ):
            typed_candidates.append(field)
    return typed_candidates[0] if len(typed_candidates) == 1 else ""


def _response_root_fields(rows: list[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    for row in rows:
        field = _json_path_first_field(str(row.get("json_path") or ""))
        if field and field not in fields:
            fields.append(field)
    return fields


def _json_path_first_field(path: str) -> str:
    match = re.match(r"^\$\.([^\.\[]+)", path)
    return match.group(1) if match else ""


def _canonical_response_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _has_nested_response_path(rows: list[dict[str, Any]], root_field: str) -> bool:
    prefix = f"$.{root_field}"
    return any(
        _json_path_startswith(str(row.get("json_path") or ""), prefix)
        and str(row.get("json_path") or "") != prefix
        for row in rows
    )


def _response_collection_path(rows: list[dict[str, Any]], *, wrapper_path: str) -> str:
    counts: Counter[str] = Counter()
    order: list[str] = []
    for row in rows:
        prefix = _json_path_first_array_prefix(str(row.get("json_path") or ""))
        if not prefix:
            continue
        counts[prefix] += 1
        if prefix not in order:
            order.append(prefix)
    if not order:
        return ""
    preferred = [
        path for path in order if wrapper_path and _json_path_startswith(path, wrapper_path)
    ]
    candidates = preferred or order
    return max(candidates, key=lambda path: (counts[path], -len(path)))


def _json_path_first_array_prefix(path: str) -> str:
    marker = "[*]"
    idx = path.find(marker)
    if idx < 0:
        return ""
    return path[: idx + len(marker)]


def _response_value_path_aliases(path: str, envelope: dict[str, Any]) -> list[str]:
    aliases: list[str] = []

    def add(candidate: str) -> None:
        if candidate and candidate != path and candidate not in aliases:
            aliases.append(candidate)

    add(_body_prefixed_json_path(path))

    wrapper_path = str(envelope.get("wrapper_path") or "")
    if wrapper_path and _json_path_startswith(path, wrapper_path):
        unwrapped = _strip_json_path_prefix(path, wrapper_path)
        add(unwrapped)
        add(_body_prefixed_json_path(unwrapped))

    collection_path = str(envelope.get("collection_path") or "")
    if collection_path and _json_path_startswith(path, collection_path):
        item_relative = _strip_json_path_prefix(path, collection_path)
        add(item_relative)
        add(_body_prefixed_json_path(item_relative))

    return aliases


def _body_prefixed_json_path(path: str) -> str:
    if not path or path == "$.body" or path.startswith("$.body.") or path.startswith("$.body["):
        return ""
    if path == "$":
        return "$.body"
    if path.startswith("$"):
        return "$.body" + path[1:]
    return ""


def _strip_json_path_prefix(path: str, prefix: str) -> str:
    if not path or not prefix or not _json_path_startswith(path, prefix):
        return ""
    if path == prefix:
        return "$"
    tail = path[len(prefix) :]
    if tail.startswith((".", "[")):
        return "$" + tail
    return ""


def _json_path_startswith(path: str, prefix: str) -> bool:
    if not path or not prefix:
        return False
    if prefix == "$":
        return path == "$" or path.startswith("$.") or path.startswith("$[")
    return path == prefix or path.startswith(f"{prefix}.") or path.startswith(f"{prefix}[")


def _compact_envelope(
    *,
    wrapper_field: str = "",
    wrapper_path: str = "",
    collection_path: str = "",
    metadata_fields: list[str] | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {}
    if wrapper_field:
        envelope["wrapper_field"] = wrapper_field
    if wrapper_path:
        envelope["wrapper_path"] = wrapper_path
    if collection_path:
        envelope["collection_path"] = collection_path
        envelope["item_path"] = collection_path
    if metadata_fields:
        envelope["metadata_fields"] = list(metadata_fields)
    return envelope
