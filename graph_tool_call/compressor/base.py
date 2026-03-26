"""Base types for the compressor module."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompressConfig:
    """Compression configuration.

    Attributes:
        max_chars: Maximum output characters (~4 chars per token).
        max_list_items: Number of sample items to keep from JSON arrays.
        max_value_len: Maximum character length for individual JSON values.
        max_depth: Maximum nesting depth before summarising nested structures.
        preserve_keys: JSON keys whose values are always kept in full.
    """

    max_chars: int = 4000
    max_list_items: int = 3
    max_value_len: int = 80
    max_depth: int = 2
    preserve_keys: list[str] = field(default_factory=list)
