"""Auto-detect content type and route to the appropriate compressor."""

from __future__ import annotations

import json
from typing import Any

from graph_tool_call.compressor.base import CompressConfig
from graph_tool_call.compressor.error_comp import (
    compress_error_dict,
    compress_error_text,
    is_error_dict,
    is_error_text,
)
from graph_tool_call.compressor.html_comp import compress_html, is_html
from graph_tool_call.compressor.json_comp import compress_json_dict, compress_json_list
from graph_tool_call.compressor.text_comp import compress_text


def _detect_and_compress(content: Any, config: CompressConfig) -> str:
    """Detect content type and compress accordingly."""
    # -- Already structured data --
    if isinstance(content, list):
        return compress_json_list(content, config)

    if isinstance(content, dict):
        if is_error_dict(content):
            return compress_error_dict(content, config)
        return compress_json_dict(content, config)

    # -- String content: try to parse / classify --
    if not isinstance(content, str):
        content = str(content)

    # Short enough — no compression needed.
    if len(content) <= config.max_chars:
        return content

    # Try JSON parse.
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        parsed = None

    if parsed is not None:
        if isinstance(parsed, list):
            return compress_json_list(parsed, config)
        if isinstance(parsed, dict):
            if is_error_dict(parsed):
                return compress_error_dict(parsed, config)
            return compress_json_dict(parsed, config)

    # HTML detection.
    if is_html(content):
        return compress_html(content, config)

    # Error text detection.
    if is_error_text(content):
        return compress_error_text(content, config)

    # Fallback: plain text.
    return compress_text(content, config)


def compress_tool_result(
    content: str | dict | list | Any,
    *,
    config: CompressConfig | None = None,
    max_chars: int = 4000,
    content_type: str | None = None,
) -> str:
    """Intelligently compress a tool result for LLM context.

    Parameters:
        content: The tool result — str, dict, list, or anything with ``__str__``.
        config: Compression configuration.  When *None*, a default
            ``CompressConfig(max_chars=max_chars)`` is created.
        max_chars: Shorthand for ``CompressConfig(max_chars=...)``.
            Ignored when *config* is provided.
        content_type: Force a specific compressor instead of auto-detecting.
            One of ``"json"``, ``"html"``, ``"error"``, ``"text"``.

    Returns:
        The compressed string.  If *content* is already short enough it is
        returned as-is (for strings) or serialised (for dicts/lists).
    """
    if config is None:
        config = CompressConfig(max_chars=max_chars)

    # Forced content type — skip auto-detection.
    if content_type is not None:
        return _compress_by_type(content, content_type, config)

    return _detect_and_compress(content, config)


def _compress_by_type(content: Any, content_type: str, config: CompressConfig) -> str:
    """Route to a specific compressor by name."""
    if isinstance(content, str):
        text = content
    else:
        text = json.dumps(content, ensure_ascii=False, default=str)

    if content_type == "json":
        try:
            parsed = json.loads(text) if isinstance(content, str) else content
        except (json.JSONDecodeError, ValueError):
            return compress_text(text, config)
        if isinstance(parsed, list):
            return compress_json_list(parsed, config)
        if isinstance(parsed, dict):
            return compress_json_dict(parsed, config)
        return compress_text(text, config)

    if content_type == "html":
        return compress_html(text, config)

    if content_type == "error":
        if isinstance(content, dict):
            return compress_error_dict(content, config)
        return compress_error_text(text, config)

    # "text" or unknown
    return compress_text(text, config)
