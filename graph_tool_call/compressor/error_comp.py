"""Error response compressor: extract status + message only."""

from __future__ import annotations

import re
from typing import Any

from graph_tool_call.compressor.base import CompressConfig

# Keys that typically carry the error message, checked in priority order.
_MESSAGE_KEYS = ("message", "detail", "error", "reason", "error_description", "msg")

# Keys that carry nested error detail dicts.
_DETAIL_CONTAINER_KEYS = ("body", "response", "data", "error")


def _extract_message(data: dict[str, Any]) -> str | None:
    """Recursively look for an error message string."""
    for key in _MESSAGE_KEYS:
        val = data.get(key)
        if isinstance(val, str) and val:
            return val

    # Check one level deeper in container keys.
    for key in _DETAIL_CONTAINER_KEYS:
        nested = data.get(key)
        if isinstance(nested, dict):
            msg = _extract_message(nested)
            if msg:
                return msg
    return None


def is_error_dict(data: dict[str, Any]) -> bool:
    """Heuristic: does *data* look like an error response?"""
    status = data.get("status") or data.get("status_code") or data.get("statusCode")
    if isinstance(status, int) and 400 <= status < 600:
        return True
    if "error" in data or "traceback" in data or "stack_trace" in data or "exception" in data:
        return True
    return False


def compress_error_dict(data: dict[str, Any], config: CompressConfig) -> str:
    """Compress an error-shaped dict to ``HTTP {status}: {message}``."""
    status = data.get("status") or data.get("status_code") or data.get("statusCode") or "?"

    # Prefer the most specific nested message over generic top-level "error".
    message = None
    for key in _DETAIL_CONTAINER_KEYS:
        nested = data.get(key)
        if isinstance(nested, dict):
            message = _extract_message(nested)
            if message:
                break
    if not message:
        message = _extract_message(data) or "Unknown error"
    if isinstance(message, dict):
        message = str(message)

    result = f"HTTP {status}: {message}"
    return result[: config.max_chars]


def compress_error_text(text: str, config: CompressConfig) -> str:
    """Compress an error-like text string (e.g. tracebacks)."""
    lines = text.strip().splitlines()
    if not lines:
        return text

    # For Python tracebacks keep the last exception line.
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("File ") and not stripped.startswith("at "):
            return stripped[: config.max_chars]

    return lines[-1][: config.max_chars]


def is_error_text(text: str) -> bool:
    """Heuristic: does *text* look like an error/traceback?"""
    if re.search(r"Traceback \(most recent call", text):
        return True
    if re.search(r"^[A-Z]\w*(Error|Exception):", text, re.MULTILINE):
        return True
    return False
