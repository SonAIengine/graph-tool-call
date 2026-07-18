"""Example-payload field extraction for weak OpenAPI schemas."""

from __future__ import annotations

import json
import re
from typing import Any

EXAMPLE_FIELD_HINT_KEYS = (
    "schema_inferred_from",
    "example_source",
    "example_name",
    "example_content_type",
    "example_status",
)

_MAX_EXAMPLE_ROWS = 128
_MAX_ARRAY_ITEMS = 3
_MAX_DEPTH = 8


def example_leaf_rows(
    examples: list[dict[str, Any]],
    *,
    location: str,
    source: str,
    max_rows: int = _MAX_EXAMPLE_ROWS,
) -> list[dict[str, Any]]:
    """Infer leaf field rows from OpenAPI example payloads."""

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for example in examples:
        value = _example_value(example)
        if value is None:
            continue
        for row in _walk_example_leaves(
            value,
            path="$",
            location=location,
            source=source,
            example=example,
        ):
            key = (str(row.get("field_name") or ""), str(row.get("json_path") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= max_rows:
                return rows
    return rows


def example_top_level_rows(
    examples: list[dict[str, Any]],
    *,
    location: str,
    source: str,
    max_rows: int = _MAX_EXAMPLE_ROWS,
) -> list[dict[str, Any]]:
    """Infer top-level object field rows from OpenAPI example payloads."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for example in examples:
        value = _example_value(example)
        if not isinstance(value, dict):
            continue
        for name, child in value.items():
            field_name = str(name)
            if not field_name or field_name in seen:
                continue
            seen.add(field_name)
            row: dict[str, Any] = {
                "field_name": field_name,
                "json_path": f"$.{field_name}",
                "field_type": _field_type(child),
                "required": False,
                "location": location,
                **_example_hints(example, source=source),
            }
            description = _nested_description(child, base_path=f"$.{field_name}")
            if description:
                row["description"] = description
            if child is None:
                row["nullable"] = True
            rows.append(row)
            if len(rows) >= max_rows:
                return rows
    return rows


def _walk_example_leaves(
    value: Any,
    *,
    path: str,
    location: str,
    source: str,
    example: dict[str, Any],
    depth: int = 0,
) -> list[dict[str, Any]]:
    if depth > _MAX_DEPTH:
        return []
    if isinstance(value, dict):
        rows: list[dict[str, Any]] = []
        for key, child in value.items():
            rows.extend(
                _walk_example_leaves(
                    child,
                    path=f"{path}.{key}",
                    location=location,
                    source=source,
                    example=example,
                    depth=depth + 1,
                )
            )
            if len(rows) >= _MAX_EXAMPLE_ROWS:
                break
        return rows[:_MAX_EXAMPLE_ROWS]
    if isinstance(value, list):
        rows = []
        for child in value[:_MAX_ARRAY_ITEMS]:
            rows.extend(
                _walk_example_leaves(
                    child,
                    path=f"{path}[*]",
                    location=location,
                    source=source,
                    example=example,
                    depth=depth + 1,
                )
            )
            if len(rows) >= _MAX_EXAMPLE_ROWS:
                break
        return rows[:_MAX_EXAMPLE_ROWS]

    field_name = _last_path_segment(path)
    if not field_name:
        return []
    row: dict[str, Any] = {
        "field_name": field_name,
        "json_path": path,
        "field_type": _field_type(value),
        "required": False,
        "location": location,
        **_example_hints(example, source=source),
    }
    if value is None:
        row["nullable"] = True
    return [row]


def _nested_description(value: Any, *, base_path: str) -> str:
    if not isinstance(value, (dict, list)):
        return ""
    rows = _walk_example_leaves(
        value,
        path=base_path,
        location="body",
        source="example",
        example={},
    )
    if not rows:
        return ""
    lines = ["Fields:"]
    for row in rows[:12]:
        path = str(row.get("json_path") or "")
        rel = _strip_path_prefix(path, base_path)
        name = rel or str(row.get("field_name") or "")
        lines.append(f"- {name} ({row.get('field_type', 'string')})")
    return "\n".join(lines)


def _strip_path_prefix(path: str, prefix: str) -> str:
    if path == prefix:
        return ""
    if path.startswith(f"{prefix}."):
        return path[len(prefix) + 1 :]
    if path.startswith(f"{prefix}["):
        return path[len(prefix) :]
    return path


def _example_value(example: dict[str, Any]) -> Any:
    if not isinstance(example, dict) or "value" not in example:
        return None
    value = example.get("value")
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _example_hints(example: dict[str, Any], *, source: str) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "schema_inferred_from": "example",
        "example_source": source,
    }
    name = str(example.get("name") or "")
    content_type = str(example.get("content_type") or "")
    status = str(example.get("status") or "")
    if name:
        hints["example_name"] = name
    if content_type:
        hints["example_content_type"] = content_type
    if status:
        hints["example_status"] = status
    return hints


def _field_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _last_path_segment(path: str) -> str:
    text = str(path or "")
    text = re.sub(r"\[\*\]$", "", text)
    text = re.sub(r"\[\*\]", "", text)
    if "." not in text:
        return ""
    return text.rsplit(".", 1)[-1]
