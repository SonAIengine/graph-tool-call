"""JSON compressor: intelligent compression for dicts and lists."""

from __future__ import annotations

import json
from typing import Any

from graph_tool_call.compressor.base import CompressConfig
from graph_tool_call.compressor.error_comp import compress_error_dict, is_error_dict

# Keys considered "identity" — kept preferentially in samples.
_IDENTITY_KEYS = {"id", "name", "title", "type", "status", "key", "slug", "code"}


def _extract_schema(items: list[dict[str, Any]]) -> dict[str, str]:
    """Infer a flat {key: type_name} schema from a list of dicts."""
    schema: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if k not in schema:
                schema[k] = type(v).__name__
    return schema


def _slim_value(value: Any, *, max_len: int, depth: int, max_depth: int) -> Any:
    """Recursively slim down a single value."""
    if isinstance(value, str):
        if len(value) <= max_len:
            return value
        return value[:max_len] + f"... [{len(value) - max_len} chars]"

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    if depth >= max_depth:
        if isinstance(value, list):
            return f"[{len(value)} items]"
        if isinstance(value, dict):
            return f"{{{len(value)} keys}}"
        return str(value)[:max_len]

    if isinstance(value, list):
        if not value:
            return []
        preview = [
            _slim_value(v, max_len=max_len, depth=depth + 1, max_depth=max_depth) for v in value[:3]
        ]
        if len(value) > 3:
            preview.append(f"... +{len(value) - 3} more")
        return preview

    if isinstance(value, dict):
        return _slim_dict(value, max_len=max_len, depth=depth + 1, max_depth=max_depth)

    return str(value)[:max_len]


def _slim_dict(
    data: dict[str, Any],
    *,
    max_len: int,
    depth: int = 0,
    max_depth: int = 2,
    preserve_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Reduce a dict by trimming long values and deep nesting."""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if preserve_keys and k in preserve_keys:
            result[k] = v
            continue
        result[k] = _slim_value(v, max_len=max_len, depth=depth, max_depth=max_depth)
    return result


def _slim_item(item: Any, config: CompressConfig) -> Any:
    """Slim a single list element."""
    if isinstance(item, dict):
        return _slim_dict(
            item,
            max_len=config.max_value_len,
            max_depth=config.max_depth,
            preserve_keys=(
                set(config.preserve_keys) | _IDENTITY_KEYS
                if config.preserve_keys
                else _IDENTITY_KEYS
            ),
        )
    return _slim_value(item, max_len=config.max_value_len, depth=0, max_depth=config.max_depth)


def _brief_item(item: Any) -> Any:
    """Extract only identity keys from a dict for brief samples."""
    if not isinstance(item, dict):
        return item
    brief: dict[str, Any] = {}
    for k in _IDENTITY_KEYS:
        if k in item:
            v = item[k]
            if isinstance(v, str) and len(v) > 80:
                v = v[:77] + "..."
            brief[k] = v
    # If no identity keys found, take first 3 scalar keys.
    if not brief:
        for k, v in list(item.items())[:3]:
            if isinstance(v, (str, int, float, bool)) or v is None:
                brief[k] = v
    return brief


def compress_json_list(data: list[Any], config: CompressConfig) -> str:
    """Compress a JSON array to count + samples + schema.

    The first sample keeps full structure (slimmed).
    Subsequent samples keep only identity keys for brevity.
    """
    total = len(data)

    samples: list[Any] = []
    for i, item in enumerate(data[: config.max_list_items]):
        if i == 0:
            samples.append(_slim_item(item, config))
        else:
            samples.append(_brief_item(item))

    result: dict[str, Any] = {
        "_compressed": True,
        "total": total,
        "samples": samples,
    }

    # Extract schema from dict items.
    dict_items = [item for item in data if isinstance(item, dict)]
    if dict_items:
        result["schema"] = _extract_schema(dict_items[:10])

    if total > config.max_list_items:
        result["omitted"] = total - config.max_list_items

    return json.dumps(result, ensure_ascii=False, default=str)


def _is_http_response(data: dict[str, Any]) -> bool:
    """Heuristic: does *data* look like an HTTP response with status+headers+body?"""
    if "headers" not in data or "body" not in data:
        return False
    status = data.get("status")
    return isinstance(status, int)


def _compress_http_response(data: dict[str, Any], config: CompressConfig) -> str:
    """Compress an HTTP response: drop headers, keep status + compressed body."""
    status = data["status"]
    body = data["body"]

    # Error status → delegate to error compressor.
    if isinstance(status, int) and 400 <= status < 600:
        error_reason = data.get("error", "")
        from graph_tool_call.compressor.error_comp import _extract_message

        msg = None
        if isinstance(body, dict):
            msg = _extract_message(body)
        if not msg and error_reason:
            msg = error_reason
        if not msg:
            msg = "HTTP error"
        return f"HTTP {status}: {msg}"

    # Success: compress body with full budget.
    body_str: str
    if isinstance(body, list):
        body_str = compress_json_list(body, config)
    elif isinstance(body, dict):
        body_str = compress_json_dict(body, config)
    else:
        body_str = str(body)[: config.max_chars]

    return f"[HTTP {status}] {body_str}"


def compress_json_dict(data: dict[str, Any], config: CompressConfig) -> str:
    """Compress a JSON dict by slimming values."""
    # HTTP response: drop headers, focus on body.
    if _is_http_response(data):
        return _compress_http_response(data, config)

    # Delegate error dicts.
    if is_error_dict(data):
        return compress_error_dict(data, config)

    preserve = set(config.preserve_keys) if config.preserve_keys else set()
    slimmed = _slim_dict(
        data,
        max_len=config.max_value_len,
        max_depth=config.max_depth,
        preserve_keys=preserve | _IDENTITY_KEYS,
    )

    out = json.dumps(slimmed, ensure_ascii=False, default=str)

    # If still too long, do a hard truncate with marker.
    if len(out) > config.max_chars:
        return out[: config.max_chars - 30] + " ... [truncated]}"

    return out
