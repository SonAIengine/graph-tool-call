"""Conflict detection — find tools that conflict with each other.

Detects conflicts based on:
1. Same-resource write operations (PUT/PATCH vs DELETE on same path)
2. MCP annotation conflicts (destructive vs read-only on same resource)
3. Idempotency conflicts (non-idempotent operations on same resource)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import RelationType


@dataclass
class ConflictResult:
    """A detected conflict between two tools."""

    source: str
    target: str
    confidence: float
    reason: str


def detect_conflicts(
    tools: list[ToolSchema],
    *,
    min_confidence: float = 0.6,
) -> list[ConflictResult]:
    """Detect conflicting tool pairs.

    Returns conflicts sorted by confidence descending.
    """
    conflicts: list[ConflictResult] = []
    conflicts.extend(_detect_write_conflicts(tools))
    conflicts.extend(_detect_annotation_conflicts(tools))

    # Deduplicate: keep highest confidence per pair
    best: dict[tuple[str, str], ConflictResult] = {}
    for c in conflicts:
        key = (min(c.source, c.target), max(c.source, c.target))
        if key not in best or c.confidence > best[key].confidence:
            best[key] = c

    result = [c for c in best.values() if c.confidence >= min_confidence]
    result.sort(key=lambda c: c.confidence, reverse=True)
    return result


def _detect_write_conflicts(tools: list[ToolSchema]) -> list[ConflictResult]:
    """Detect conflicts between write operations on the same resource."""
    conflicts: list[ConflictResult] = []

    # Group by base resource path
    resource_writes: dict[str, list[ToolSchema]] = {}
    for tool in tools:
        method = tool.metadata.get("method", "").lower()
        path = tool.metadata.get("path", "")
        if not method or not path:
            continue
        if method not in ("put", "patch", "delete", "post"):
            continue
        # Normalize path: strip trailing params for grouping
        base = _base_resource(path)
        resource_writes.setdefault(base, []).append(tool)

    for base, group in resource_writes.items():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            m_a = a.metadata.get("method", "").lower()
            for b in group[i + 1 :]:
                m_b = b.metadata.get("method", "").lower()
                # DELETE vs PUT/PATCH: strong conflict
                if (m_a == "delete" and m_b in ("put", "patch")) or (
                    m_b == "delete" and m_a in ("put", "patch")
                ):
                    conflicts.append(
                        ConflictResult(
                            source=a.name,
                            target=b.name,
                            confidence=0.85,
                            reason=f"Conflicting state changes on {base}: "
                            f"{a.name} ({m_a.upper()}) vs {b.name} ({m_b.upper()})",
                        )
                    )
                # Multiple non-idempotent writes (POST vs POST on same resource)
                elif m_a == "post" and m_b == "post":
                    conflicts.append(
                        ConflictResult(
                            source=a.name,
                            target=b.name,
                            confidence=0.6,
                            reason=f"Multiple POST operations on {base}: {a.name} vs {b.name}",
                        )
                    )

    return conflicts


def _detect_annotation_conflicts(tools: list[ToolSchema]) -> list[ConflictResult]:
    """Detect conflicts based on MCP annotations."""
    conflicts: list[ConflictResult] = []

    # Find destructive tools and read-only tools on similar resources
    destructive: list[ToolSchema] = []
    non_destructive_writers: list[ToolSchema] = []

    for tool in tools:
        ann = tool.annotations
        if ann is None:
            continue
        if ann.destructive_hint is True:
            destructive.append(tool)
        elif ann.read_only_hint is not True:
            # It's a writer but not destructive
            method = tool.metadata.get("method", "").lower()
            if method in ("put", "patch", "post"):
                non_destructive_writers.append(tool)

    # Destructive tool vs non-destructive writer on same resource
    for d_tool in destructive:
        d_base = _base_resource(d_tool.metadata.get("path", ""))
        if not d_base:
            continue
        for w_tool in non_destructive_writers:
            w_base = _base_resource(w_tool.metadata.get("path", ""))
            if d_base == w_base and d_tool.name != w_tool.name:
                conflicts.append(
                    ConflictResult(
                        source=d_tool.name,
                        target=w_tool.name,
                        confidence=0.8,
                        reason=f"Destructive ({d_tool.name}) vs non-destructive writer "
                        f"({w_tool.name}) on {d_base}",
                    )
                )

    return conflicts


def apply_conflicts(
    tg: Any,
    conflicts: list[ConflictResult],
) -> int:
    """Apply detected conflicts as CONFLICTS_WITH relations to a ToolGraph.

    Returns the number of new relations added.
    """
    added = 0
    for c in conflicts:
        if not tg.graph.has_edge(c.source, c.target) and not tg.graph.has_edge(c.target, c.source):
            tg.add_relation(c.source, c.target, RelationType.CONFLICTS_WITH)
            added += 1
    return added


def _base_resource(path: str) -> str:
    """Extract base resource from path, ignoring parameters."""
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return "/" + "/".join(segments) if segments else ""
