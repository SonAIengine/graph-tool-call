"""Catalog helpers shared by retrieval and plan synthesis adapters."""

from __future__ import annotations

from typing import Any

_DEFAULT_ACTION_PRIORITY = {"search": 3, "read": 2, "action": 1}


def expand_candidates_with_producers(
    candidate_names: list[str],
    tools_by_name: dict[str, dict[str, Any]],
    *,
    max_producers_per_field: int = 3,
    max_hops: int = 1,
    action_priority: dict[str, int] | None = None,
) -> list[str]:
    """Return retrieval candidates plus producer tools for required inputs.

    Stage-1 intent parsing works better when the catalog contains both the
    likely final tools and the producer tools that can supply their required
    data fields. ``max_hops`` defaults to the historical 1-hop behavior; callers
    that are constructing a target-specific plan candidate set can opt into
    deeper producer chains without expanding every top-K retrieval hit.
    """

    priority = action_priority or _DEFAULT_ACTION_PRIORITY
    producer_index = _build_producer_index(tools_by_name)
    seen = {name for name in candidate_names}
    expanded = list(candidate_names)
    frontier = list(candidate_names)

    for _hop in range(max(0, max_hops)):
        next_frontier: list[str] = []
        for name in frontier:
            producers = _producers_for_required_inputs(
                name,
                tools_by_name=tools_by_name,
                producer_index=producer_index,
                priority=priority,
                seen=seen,
                max_producers_per_field=max_producers_per_field,
            )
            for producer in producers:
                expanded.append(producer)
                seen.add(producer)
                next_frontier.append(producer)
        if not next_frontier:
            break
        frontier = next_frontier

    return expanded


def _producers_for_required_inputs(
    name: str,
    *,
    tools_by_name: dict[str, dict[str, Any]],
    producer_index: dict[str, list[str]],
    priority: dict[str, int],
    seen: set[str],
    max_producers_per_field: int,
) -> list[str]:
    out: list[str] = []
    tool = tools_by_name.get(name) or {}
    metadata = tool.get("metadata") or {}
    local_seen = set(seen)
    for consume in metadata.get("consumes") or []:
        if not isinstance(consume, dict):
            continue
        if not consume.get("required"):
            continue
        if str(consume.get("kind") or "data").strip().lower() != "data":
            continue
        semantic = str(consume.get("semantic_tag") or "").strip()
        field_name = str(consume.get("field_name") or "").strip()
        pool = list(
            dict.fromkeys(producer_index.get(semantic, []) + producer_index.get(field_name, []))
        )
        pool = [p for p in pool if p != name and p not in local_seen]
        pool.sort(
            key=lambda p: _producer_score(tools_by_name.get(p) or {}, priority),
            reverse=True,
        )
        for producer in pool[: max(0, max_producers_per_field)]:
            out.append(producer)
            local_seen.add(producer)
    return out


def _build_producer_index(
    tools_by_name: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for name, tool in (tools_by_name or {}).items():
        if not isinstance(tool, dict):
            continue
        metadata = tool.get("metadata") or {}
        consumed_fields = {
            str(c.get("field_name") or "")
            for c in metadata.get("consumes") or []
            if isinstance(c, dict)
        }
        consumed_semantics = {
            str(c.get("semantic_tag") or "")
            for c in metadata.get("consumes") or []
            if isinstance(c, dict)
        }
        for produce in metadata.get("produces") or []:
            if not isinstance(produce, dict):
                continue
            semantic = str(produce.get("semantic_tag") or "").strip()
            field_name = str(produce.get("field_name") or "").strip()
            if semantic and semantic not in consumed_semantics:
                index.setdefault(semantic, []).append(name)
            if field_name and field_name != semantic and field_name not in consumed_fields:
                index.setdefault(field_name, []).append(name)
    return index


def _producer_score(tool: dict[str, Any], priority: dict[str, int]) -> int:
    ai = (tool.get("metadata") or {}).get("ai_metadata") or {}
    action = str(ai.get("canonical_action") or "").strip().lower()
    return priority.get(action, 0)


__all__ = ["expand_candidates_with_producers"]
