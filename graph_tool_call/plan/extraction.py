"""Value extraction from tool responses.

Two jobs, one shared BFS core:

  * :func:`find_value_paths` — locate a field anywhere in a response tree,
    returning ranked ``PathCandidate`` entries (value + where it was found +
    how confident). Used by the runner's opt-in binding recovery to repair a
    stale ``${sN.path}`` when the declared path no longer matches the live
    shape, and by higher layers that need to reflect over responses.
  * :func:`extract_produced_entities` — given a tool's ``produces`` schema and
    its actual output, pull out ``{semantic_tag: value, field_name: value}``
    so the plan repairer can feed completed step results back into a fresh
    synthesis as entities.

Both are deterministic and stdlib-only. Matching prefers the declared
``json_path`` (precise), then falls back to a breadth-first search keyed on
``field_name`` — exact key first, then the loose separator/case-folded form
shared with the synthesizer (:func:`_normalize_field_name`).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from graph_tool_call.plan.binding import _tokenize
from graph_tool_call.plan.synthesizer import _normalize_field_name

__all__ = [
    "PathCandidate",
    "find_value_paths",
    "extract_produced_entities",
    "ValueExtractorLLM",
]

# Traversal guard — cap nodes visited so a pathological (deeply nested / huge)
# response can't turn a best-effort recovery into an expensive walk.
_MAX_NODES = 5000


@dataclass
class PathCandidate:
    """A located value and where/how it was found in a response tree.

    ``path`` is a binding-compatible dotted path *relative to the response
    root* (``body.items[0].goodsNo``) — the runner can splice it into
    ``${sN.<path>}`` to repair a binding. ``confidence`` is a 0..1 heuristic
    (exact key + shallow depth ⇒ higher); ``method`` is ``"exact"`` or
    ``"loose"``.
    """

    value: Any
    path: str
    method: str
    confidence: float


@runtime_checkable
class ValueExtractorLLM(Protocol):
    """Optional LLM hook for value extraction (P1-3 seam, unused in v0.22).

    An implementation receives the response and the field being sought and
    returns a best-effort value (or ``None``). Defined now so the runner /
    repairer signatures can accept it without a later breaking change; the
    deterministic BFS remains the default path.
    """

    def extract(self, output: Any, *, field_name: str, semantic_tag: str = "") -> Any: ...


def find_value_paths(
    output: Any,
    *,
    field_name: str,
    semantic_tag: str = "",
    max_depth: int = 8,
    max_candidates: int = 5,
) -> list[PathCandidate]:
    """Breadth-first search *output* for values under key ``field_name``.

    Returns up to ``max_candidates`` ranked candidates. An exact key match
    outranks a loose (separator/case-folded) one; among equal methods a
    shallower location wins. ``semantic_tag`` is accepted for API symmetry
    with the synthesizer and to disambiguate future scoring — the current
    ranking is driven by key match + depth.

    Empty ``field_name`` (or non-container ``output``) yields ``[]``.
    """
    if not field_name or not isinstance(output, (dict, list)):
        return []

    loose_target = _normalize_field_name(field_name)
    candidates: list[PathCandidate] = []
    # Queue of (node, path, depth). Root path is "" (relative to response).
    queue: deque[tuple[Any, str, int]] = deque([(output, "", 0)])
    visited = 0

    while queue and visited < _MAX_NODES:
        node, path, depth = queue.popleft()
        visited += 1
        if depth > max_depth:
            continue

        if isinstance(node, dict):
            for key, val in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                method = ""
                if key == field_name:
                    method = "exact"
                elif loose_target and _normalize_field_name(str(key)) == loose_target:
                    method = "loose"
                if method:
                    base = 1.0 if method == "exact" else 0.6
                    confidence = max(base - depth * 0.1, 0.2)
                    candidates.append(
                        PathCandidate(
                            value=val,
                            path=child_path,
                            method=method,
                            confidence=round(confidence, 3),
                        )
                    )
                if isinstance(val, (dict, list)):
                    queue.append((val, child_path, depth + 1))
        elif isinstance(node, list):
            for i, val in enumerate(node):
                child_path = f"{path}[{i}]"
                if isinstance(val, (dict, list)):
                    queue.append((val, child_path, depth + 1))

    # Rank: higher confidence first, then exact before loose, then shallower
    # path (fewer separators), then lexical for stability.
    candidates.sort(
        key=lambda c: (
            -c.confidence,
            0 if c.method == "exact" else 1,
            c.path.count(".") + c.path.count("["),
            c.path,
        )
    )
    return candidates[:max_candidates]


def extract_produced_entities(tool_meta: dict[str, Any], output: Any) -> dict[str, Any]:
    """Pull ``{semantic_tag: value, field_name: value}`` from *output*.

    Iterates the tool's ``produces`` schema. For each entry it first tries the
    declared ``json_path`` (precise), then falls back to a field-name BFS.
    Every located value is registered under **both** its ``semantic_tag`` and
    ``field_name`` so the repairer's re-synthesis — which matches entities by
    semantic first, field second — resolves either way. First value wins per
    key (no clobber).
    """
    produces = (tool_meta or {}).get("produces") or []
    entities: dict[str, Any] = {}
    for p in produces:
        if not isinstance(p, dict):
            continue
        field_name = p.get("field_name") or ""
        semantic = p.get("semantic_tag") or ""
        json_path = p.get("json_path") or ""

        value = _resolve_json_path(output, json_path)
        if value is None and field_name:
            cands = find_value_paths(
                output,
                field_name=field_name,
                semantic_tag=semantic,
                max_candidates=1,
            )
            if cands:
                value = cands[0].value
        if value is None:
            continue

        if semantic and semantic not in entities:
            entities[semantic] = value
        if field_name and field_name not in entities:
            entities[field_name] = value
    return entities


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resolve_json_path(output: Any, raw: str) -> Any:
    """Tolerant walk of a ``$.a.b[*].c`` json_path against *output*.

    Mirrors the binding resolver's tokenizer but never raises — returns
    ``None`` on any miss so callers can fall back to a BFS. ``[*]`` collapses
    to index 0 (v1 first-element semantics, consistent with binding paths).
    """
    if not raw:
        return None
    path = raw
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    path = path.replace("[*]", "[0]")
    if not path:
        return None

    node = output
    for tok in _tokenize(path):
        if tok.startswith("[") and tok.endswith("]"):
            try:
                idx = int(tok[1:-1])
            except ValueError:
                return None
            if not isinstance(node, (list, tuple)):
                return None
            try:
                node = node[idx]
            except IndexError:
                return None
        else:
            if not isinstance(node, dict) or tok not in node:
                return None
            node = node[tok]
    return node
