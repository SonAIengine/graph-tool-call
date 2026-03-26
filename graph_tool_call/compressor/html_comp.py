"""HTML compressor: strip tags, extract text, detect error pages."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from graph_tool_call.compressor.base import CompressConfig

# Tags whose content should be removed entirely.
_STRIP_TAGS = {"script", "style", "head", "noscript", "svg", "iframe"}

# Common error patterns found in HTML pages.
_ERROR_PATTERNS = [
    re.compile(r"\b(404|403|500|502|503)\b"),
    re.compile(r"not\s+found", re.IGNORECASE),
    re.compile(r"internal\s+server\s+error", re.IGNORECASE),
    re.compile(r"access\s+denied", re.IGNORECASE),
    re.compile(r"forbidden", re.IGNORECASE),
]


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text converter using stdlib only."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str = ""
        self.text_parts: list[str] = []
        self._skip_depth: int = 0
        self._in_title: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in _STRIP_TAGS:
            self._skip_depth += 1
        if lower == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in _STRIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if lower == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        if self._skip_depth == 0:
            self.text_parts.append(data)


def _extract_text(html: str) -> tuple[str, str]:
    """Return (title, body_text) from HTML."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        # Fallback: regex strip if parser fails on malformed HTML.
        text = re.sub(r"<[^>]+>", " ", html)
        return "", text

    raw = " ".join(parser.text_parts)
    # Normalise whitespace.
    text = re.sub(r"\s+", " ", raw).strip()
    return parser.title, text


def compress_html(html: str, config: CompressConfig) -> str:
    """Compress an HTML string to plain text.

    Error pages are reduced to a single line like ``[HTML] 404: Not Found``.
    """
    title, text = _extract_text(html)

    # Detect error pages.
    snippet = (title + " " + text[:500]).strip()
    for pattern in _ERROR_PATTERNS:
        m = pattern.search(snippet)
        if m:
            code = m.group(0) if m.group(0).isdigit() else ""
            label = snippet[:200].strip()
            prefix = f"[HTML] {code}: " if code else "[HTML] "
            return (prefix + label)[: config.max_chars]

    # Deduplicate repeated lines/segments before truncating.
    text = _dedup_lines(text)

    # Build readable output.
    parts: list[str] = []
    if title:
        parts.append(f"[HTML] {title}")
    if text:
        parts.append(text)
    output = "\n".join(parts) if parts else "[HTML] (empty page)"

    if len(output) <= config.max_chars:
        return output
    return output[: config.max_chars - 20] + " ... [truncated]"


def _dedup_lines(text: str) -> str:
    """Collapse repeated segments in extracted text.

    When the same sentence/segment appears 3+ times in a row, keep the first
    occurrence and replace the rest with a count marker.
    """
    # Split on sentence-like boundaries (period/newline followed by uppercase or timestamp).
    segments = re.split(r"(?<=[.!?\n])\s+(?=[A-Z0-9])", text)
    if len(segments) < 4:
        return text

    result: list[str] = []
    prev = None
    repeat_count = 0

    for seg in segments:
        # Normalise for comparison: strip and collapse whitespace.
        norm = re.sub(r"\s+", " ", seg.strip())
        if norm == prev:
            repeat_count += 1
        else:
            if repeat_count > 1:
                result.append(f"[... repeated {repeat_count} more times]")
            elif repeat_count == 1:
                result.append(seg)  # Only 1 repeat — keep it.
            prev = norm
            repeat_count = 0
            result.append(seg)

    if repeat_count > 1:
        result.append(f"[... repeated {repeat_count} more times]")
    elif repeat_count == 1 and segments:
        result.append(segments[-1])

    return " ".join(result)


def is_html(text: str) -> bool:
    """Heuristic: does *text* look like HTML?"""
    # Check first 500 chars for common HTML indicators.
    head = text[:500].strip()
    if head.startswith("<!") or head.startswith("<html") or head.startswith("<HTML"):
        return True
    if re.search(r"<(div|span|body|head|p|table|form|a)\b", head, re.IGNORECASE):
        return True
    return False
