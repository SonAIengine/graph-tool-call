"""Ground-truth-only diagnostics for required producer graph coverage."""

from __future__ import annotations

import re
from collections import Counter, deque
from collections.abc import Iterable
from typing import Any

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.tool_graph import ToolGraph

PRODUCER_COVERAGE_POLICY_REVISION = "paper-producer-coverage-v1"

PRODUCER_COVERAGE_REASON_CODES = frozenset(
    {
        "target_tool_missing",
        "producer_tool_missing",
        "consumer_input_contract_missing",
        "producer_output_contract_missing",
        "contract_field_mismatch",
        "consumer_match_optional_only",
        "consumer_input_contract_not_promoted",
        "producer_output_contract_not_promoted",
        "matching_contract_fields_not_promoted",
        "promoted_contract_edge_not_selected",
        "contract_edge_missing",
        "edge_direction_mismatch",
        "path_direction_mismatch",
        "graph_path_beyond_budget",
        "graph_path_missing",
        "target_not_seeded",
        "producer_not_seeded",
        "producer_unreachable_from_seeds",
    }
)

_STATUS_PRIORITY = {
    "missing_tool": 0,
    "uncovered": 1,
    "path_outside_budget": 2,
    "bounded_graph_path": 3,
    "direct_graph_edge": 4,
    "direct_contract_edge": 5,
}


def diagnose_required_producer_coverage(
    graph: ToolGraph,
    *,
    expected_targets: Iterable[str],
    required_producers: Iterable[str],
    seed_names: Iterable[str] = (),
    max_depth: int = 2,
) -> dict[str, Any]:
    """Explain whether annotated producer-target pairs are usable by the graph.

    This is an offline evaluation helper. Expected targets and producers are
    ground truth and must never be supplied to the production retriever.
    """
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative.")

    targets = _unique_names(expected_targets)
    producers = _unique_names(required_producers)
    seeds = [name for name in _unique_names(seed_names) if name in graph.tools]
    pairs = [
        _diagnose_pair(
            graph,
            target=target,
            producer=producer,
            seeds=seeds,
            max_depth=max_depth,
        )
        for target in targets
        for producer in producers
    ]
    return {
        "policy_revision": PRODUCER_COVERAGE_POLICY_REVISION,
        "evaluation_scope": "ground_truth_only",
        "max_depth": max_depth,
        "expected_target_count": len(targets),
        "required_producer_count": len(producers),
        "seed_names": seeds,
        "summary": summarize_producer_edge_coverage([{"pairs": pairs}]),
        "pairs": pairs,
    }


def summarize_producer_edge_coverage(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate pair-level coverage without treating empty cases as successes."""
    reports_list = list(reports)
    pairs = [
        pair
        for report in reports_list
        for pair in report.get("pairs", [])
        if isinstance(pair, dict)
    ]
    status_counts = Counter(str(pair.get("status") or "uncovered") for pair in pairs)
    reason_counts = Counter(
        str(reason)
        for pair in pairs
        for reason in pair.get("reason_codes", [])
        if str(reason) in PRODUCER_COVERAGE_REASON_CODES
    )
    pair_count = len(pairs)
    return {
        "policy_revision": PRODUCER_COVERAGE_POLICY_REVISION,
        "case_count": sum(bool(report.get("pairs")) for report in reports_list),
        "pair_count": pair_count,
        "status_counts": dict(sorted(status_counts.items())),
        "reason_code_counts": dict(sorted(reason_counts.items())),
        "coverage": {
            key: _boolean_coverage(pairs, key)
            for key in (
                "target_present",
                "producer_present",
                "consumer_input_contract_present",
                "producer_output_contract_present",
                "consumer_promoted_input_present",
                "producer_promoted_output_present",
                "contract_field_match",
                "required_contract_field_match",
                "promoted_contract_field_match",
                "promoted_required_contract_field_match",
                "direct_graph_edge",
                "direct_contract_edge",
                "bounded_graph_path",
                "bounded_contract_path",
                "bounded_forward_graph_path",
                "bounded_forward_contract_path",
                "target_seeded",
                "producer_seeded",
                "producer_reachable_from_seeds",
            )
        },
    }


def _diagnose_pair(
    graph: ToolGraph,
    *,
    target: str,
    producer: str,
    seeds: list[str],
    max_depth: int,
) -> dict[str, Any]:
    target_tool = graph.tools.get(target)
    producer_tool = graph.tools.get(producer)
    target_present = target_tool is not None
    producer_present = producer_tool is not None
    reason_codes: set[str] = set()
    if not target_present:
        reason_codes.add("target_tool_missing")
    if not producer_present:
        reason_codes.add("producer_tool_missing")

    consumes = _contract_rows(target_tool, "consumes", include_raw=True)
    produces = _contract_rows(producer_tool, "produces", include_raw=True)
    promoted_consumes = _contract_rows(target_tool, "consumes", include_raw=False)
    promoted_produces = _contract_rows(producer_tool, "produces", include_raw=False)
    if target_present and not consumes:
        reason_codes.add("consumer_input_contract_missing")
    if producer_present and not produces:
        reason_codes.add("producer_output_contract_missing")
    if consumes and not promoted_consumes:
        reason_codes.add("consumer_input_contract_not_promoted")
    if produces and not promoted_produces:
        reason_codes.add("producer_output_contract_not_promoted")

    matches = _contract_matches(consumes, produces)
    required_matches = [match for match in matches if match["consumer_required"]]
    promoted_matches = _contract_matches(promoted_consumes, promoted_produces)
    promoted_required_matches = [match for match in promoted_matches if match["consumer_required"]]
    if target_present and producer_present and consumes and produces and not matches:
        reason_codes.add("contract_field_mismatch")
    if matches and not required_matches:
        reason_codes.add("consumer_match_optional_only")
    if matches and not promoted_matches:
        reason_codes.add("matching_contract_fields_not_promoted")

    direct_attrs = _edge_attrs(graph, target, producer)
    reverse_attrs = _edge_attrs(graph, producer, target)
    direct_graph_edge = direct_attrs is not None
    direct_contract_edge = bool(direct_attrs and _is_contract_edge(direct_attrs))
    reverse_graph_edge = reverse_attrs is not None
    if target_present and producer_present and not direct_contract_edge:
        reason_codes.add("contract_edge_missing")
    if promoted_required_matches and not direct_contract_edge:
        reason_codes.add("promoted_contract_edge_not_selected")
    if reverse_graph_edge and not direct_graph_edge:
        reason_codes.add("edge_direction_mismatch")

    bounded_path = _shortest_path(
        graph,
        target,
        producer,
        max_depth=max_depth,
    )
    bounded_contract_path = _shortest_path(
        graph,
        target,
        producer,
        max_depth=max_depth,
        contract_only=True,
    )
    bounded_forward_path = _shortest_path(
        graph,
        target,
        producer,
        max_depth=max_depth,
        direction="out",
    )
    bounded_forward_contract_path = _shortest_path(
        graph,
        target,
        producer,
        max_depth=max_depth,
        contract_only=True,
        direction="out",
    )
    any_path = bounded_path or _shortest_path(
        graph,
        target,
        producer,
        max_depth=max(0, len(graph.tools) - 1),
    )
    if target_present and producer_present and not bounded_path:
        reason_codes.add("graph_path_beyond_budget" if any_path else "graph_path_missing")
    if bounded_path and not bounded_forward_path:
        reason_codes.add("path_direction_mismatch")

    target_seeded = target in seeds
    producer_seeded = producer in seeds
    if target_present and not target_seeded:
        reason_codes.add("target_not_seeded")
    if producer_present and not producer_seeded:
        reason_codes.add("producer_not_seeded")
    seed_path = _best_seed_path(graph, seeds, producer, max_depth=max_depth)
    producer_reachable_from_seeds = bool(seed_path)
    if producer_present and seeds and not producer_reachable_from_seeds:
        reason_codes.add("producer_unreachable_from_seeds")

    status = _pair_status(
        tools_present=target_present and producer_present,
        direct_graph_edge=direct_graph_edge,
        direct_contract_edge=direct_contract_edge,
        bounded_path=bounded_path,
        any_path=any_path,
    )
    return {
        "target": target,
        "producer": producer,
        "status": status,
        "reason_codes": sorted(reason_codes),
        "target_present": target_present,
        "producer_present": producer_present,
        "consumer_input_contract_present": bool(consumes),
        "producer_output_contract_present": bool(produces),
        "consumer_promoted_input_present": bool(promoted_consumes),
        "producer_promoted_output_present": bool(promoted_produces),
        "consumer_field_count": len(consumes),
        "producer_field_count": len(produces),
        "consumer_promoted_field_count": len(promoted_consumes),
        "producer_promoted_field_count": len(promoted_produces),
        "contract_field_match": bool(matches),
        "required_contract_field_match": bool(required_matches),
        "promoted_contract_field_match": bool(promoted_matches),
        "promoted_required_contract_field_match": bool(promoted_required_matches),
        "contract_matches": matches,
        "promoted_contract_matches": promoted_matches,
        "direct_graph_edge": direct_graph_edge,
        "direct_contract_edge": direct_contract_edge,
        "direct_edge_evidence": _compact_edge_evidence(direct_attrs),
        "reverse_graph_edge": reverse_graph_edge,
        "bounded_graph_path": bool(bounded_path),
        "bounded_contract_path": bool(bounded_contract_path),
        "bounded_forward_graph_path": bool(bounded_forward_path),
        "bounded_forward_contract_path": bool(bounded_forward_contract_path),
        "shortest_path": bounded_path or any_path,
        "shortest_path_depth": max(0, len(bounded_path or any_path) - 1),
        "target_seeded": target_seeded,
        "producer_seeded": producer_seeded,
        "producer_reachable_from_seeds": producer_reachable_from_seeds,
        "best_seed_path": seed_path,
    }


def _contract_rows(
    tool: ToolSchema | None,
    key: str,
    *,
    include_raw: bool,
) -> list[dict[str, Any]]:
    if tool is None:
        return []
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    contract = (
        metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
    )
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, bool]] = set()
    sources = [metadata.get(key)]
    if include_raw:
        sources.append(contract.get(key))
    for source in sources:
        if not isinstance(source, list):
            continue
        for row in source:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("kind") or "data").strip().lower()
            if kind != "data":
                continue
            normalized = {
                "field_name": str(row.get("field_name") or "").strip(),
                "semantic_tag": str(row.get("semantic_tag") or "").strip(),
                "json_path": str(row.get("json_path") or "").strip(),
                "field_type": str(row.get("field_type") or "").strip(),
                "required": bool(row.get("required")),
            }
            identity = (
                normalized["field_name"].casefold(),
                normalized["semantic_tag"].casefold(),
                normalized["json_path"],
                normalized["field_type"].casefold(),
                normalized["required"],
            )
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(normalized)
    return rows


def _contract_matches(
    consumes: list[dict[str, Any]],
    produces: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, bool, str]] = set()
    for consume in consumes:
        for produce in produces:
            rule = _field_match_rule(consume, produce)
            if not rule:
                continue
            identity = (
                consume["field_name"],
                produce["field_name"],
                consume["required"],
                rule,
            )
            if identity in seen:
                continue
            seen.add(identity)
            matches.append(
                {
                    "consumer_field": consume["field_name"],
                    "producer_field": produce["field_name"],
                    "consumer_required": consume["required"],
                    "rule": rule,
                }
            )
    matches.sort(
        key=lambda row: (
            row["consumer_field"].casefold(),
            row["producer_field"].casefold(),
            row["rule"],
        )
    )
    return matches


def _field_match_rule(consume: dict[str, Any], produce: dict[str, Any]) -> str:
    consume_semantic = str(consume.get("semantic_tag") or "").casefold()
    produce_semantic = str(produce.get("semantic_tag") or "").casefold()
    if consume_semantic and consume_semantic == produce_semantic:
        return "semantic_tag"
    consume_field = str(consume.get("field_name") or "")
    produce_field = str(produce.get("field_name") or "")
    if consume_field and consume_field.casefold() == produce_field.casefold():
        return "field_name"
    consume_key = _field_key(consume_field)
    produce_key = _field_key(produce_field)
    if consume_key and consume_key == produce_key:
        return "normalized_field_name"
    return ""


def _field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _edge_attrs(graph: ToolGraph, source: str, target: str) -> dict[str, Any] | None:
    if source not in graph.tools or target not in graph.tools:
        return None
    if not graph.graph.has_edge(source, target):
        return None
    return graph.graph.get_edge_attrs(source, target)


def _is_contract_edge(attrs: dict[str, Any]) -> bool:
    sources = attrs.get("evidence_sources") or []
    if isinstance(sources, str):
        sources = [sources]
    return "api_contract" in {str(source).strip().lower() for source in sources}


def _compact_edge_evidence(attrs: dict[str, Any] | None) -> dict[str, Any]:
    if not attrs:
        return {}
    sources = attrs.get("evidence_sources") or []
    if isinstance(sources, str):
        sources = [sources]
    data_flow = attrs.get("data_flow") if isinstance(attrs.get("data_flow"), dict) else {}
    return {
        "relation": _enum_value(attrs.get("relation")),
        "confidence": _enum_value(attrs.get("confidence")),
        "conf_score": float(attrs.get("conf_score") or 0.0),
        "evidence_sources": sorted({str(source) for source in sources if str(source)}),
        "consumer_field": str(data_flow.get("consumer_field") or data_flow.get("to_field") or ""),
        "producer_field": str(data_flow.get("producer_field") or data_flow.get("from_field") or ""),
    }


def _shortest_path(
    graph: ToolGraph,
    start: str,
    goal: str,
    *,
    max_depth: int,
    contract_only: bool = False,
    direction: str = "both",
) -> list[str]:
    if start not in graph.tools or goal not in graph.tools:
        return []
    if start == goal:
        return [start]
    queue: deque[list[str]] = deque([[start]])
    visited = {start}
    while queue:
        path = queue.popleft()
        if len(path) - 1 >= max_depth:
            continue
        node = path[-1]
        for source, target, attrs in _sorted_edges(graph, node, direction=direction):
            if contract_only and not _is_contract_edge(attrs):
                continue
            neighbor = target if source == node else source
            if neighbor in visited:
                continue
            next_path = [*path, neighbor]
            if neighbor == goal:
                return next_path
            visited.add(neighbor)
            queue.append(next_path)
    return []


def _best_seed_path(
    graph: ToolGraph,
    seeds: list[str],
    producer: str,
    *,
    max_depth: int,
) -> list[str]:
    paths = [
        path
        for seed in seeds
        if (path := _shortest_path(graph, seed, producer, max_depth=max_depth))
    ]
    if not paths:
        return []
    return min(paths, key=lambda path: (len(path), [node.casefold() for node in path], path))


def _sorted_edges(
    graph: ToolGraph,
    node: str,
    *,
    direction: str = "both",
) -> list[tuple[str, str, dict[str, Any]]]:
    return sorted(
        graph.graph.get_edges_from(node, direction=direction),
        key=lambda row: (
            row[0].casefold(),
            row[0],
            row[1].casefold(),
            row[1],
            _enum_value(row[2].get("relation")),
        ),
    )


def _pair_status(
    *,
    tools_present: bool,
    direct_graph_edge: bool,
    direct_contract_edge: bool,
    bounded_path: list[str],
    any_path: list[str],
) -> str:
    if not tools_present:
        return "missing_tool"
    candidates = ["uncovered"]
    if any_path and not bounded_path:
        candidates.append("path_outside_budget")
    if bounded_path:
        candidates.append("bounded_graph_path")
    if direct_graph_edge:
        candidates.append("direct_graph_edge")
    if direct_contract_edge:
        candidates.append("direct_contract_edge")
    return max(candidates, key=_STATUS_PRIORITY.__getitem__)


def _boolean_coverage(pairs: list[dict[str, Any]], key: str) -> dict[str, Any]:
    count = sum(bool(pair.get(key)) for pair in pairs)
    return {
        "count": count,
        "rate": count / len(pairs) if pairs else 0.0,
    }


def _unique_names(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _enum_value(value: Any) -> str:
    raw = value.value if hasattr(value, "value") else value
    return str(raw or "").strip().lower()


__all__ = [
    "PRODUCER_COVERAGE_POLICY_REVISION",
    "PRODUCER_COVERAGE_REASON_CODES",
    "diagnose_required_producer_coverage",
    "summarize_producer_edge_coverage",
]
