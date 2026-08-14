"""Deterministic ranking helpers shared by retrieval channels."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def stable_score_items(
    scores: Mapping[str, float] | Iterable[tuple[str, float]],
) -> list[tuple[str, float]]:
    """Sort scores descending with a stable, content-derived tie breaker.

    Retrieval inputs often originate from graph neighbor sets. Relying on dict
    insertion order for equal scores makes top-k results vary with Python's
    hash seed, so tool name is the final deterministic ordering key.
    """
    items = scores.items() if isinstance(scores, Mapping) else scores
    return sorted(items, key=lambda item: (-item[1], item[0].casefold(), item[0]))
