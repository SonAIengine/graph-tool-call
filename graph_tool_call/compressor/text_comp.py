"""Plain-text compressor: head + tail with omission marker."""

from __future__ import annotations

from graph_tool_call.compressor.base import CompressConfig


def compress_text(text: str, config: CompressConfig) -> str:
    """Compress plain text by keeping head and tail portions.

    Returns *text* unchanged when it fits within *config.max_chars*.
    """
    if len(text) <= config.max_chars:
        return text

    head_len = int(config.max_chars * 0.7)
    tail_len = int(config.max_chars * 0.2)

    head = text[:head_len]
    tail = text[-tail_len:] if tail_len > 0 else ""
    omitted = len(text) - head_len - tail_len

    parts = [head, f"\n\n... [{omitted} chars omitted] ...\n\n"]
    if tail:
        parts.append(tail)
    return "".join(parts)
