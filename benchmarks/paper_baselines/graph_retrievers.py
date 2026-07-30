"""Frozen graph ablations layered on the B4 flat-semantic ranking."""

from __future__ import annotations

from typing import Any

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import (
    expand_candidates_with_producers,
    select_target_candidate,
    target_action_priority_for_query,
)
from graph_tool_call.retrieval.intent import classify_intent
from graph_tool_call.tool_graph import ToolGraph

from .retrievers import RankedCandidate

FIXED_GRAPH_POLICY_REVISION = "paper-graph-rerank-v1"
FIXED_GRAPH_SEED_COUNT = 5
FIXED_GRAPH_DEPTH = 2
FIXED_PRODUCER_MAX_HOPS = 1
FIXED_PRODUCERS_PER_FIELD = 3

_PROFILES = frozenset({"untyped_topology", "typed_contract"})
_CONFIDENCE_FACTORS = {
    "EXTRACTED": 1.0,
    "INFERRED": 0.7,
    "AMBIGUOUS": 0.4,
    "": 0.5,
}
_DEFAULT_RELATION_WEIGHTS = {
    "similar_to": 0.8,
    "requires": 1.0,
    "complementary": 0.7,
    "conflicts_with": 0.2,
    "belongs_to": 0.5,
    "precedes": 0.9,
}
_INTENT_RELATION_WEIGHTS = {
    "read": {
        "similar_to": 1.0,
        "requires": 0.8,
        "complementary": 0.4,
        "conflicts_with": 0.2,
        "belongs_to": 0.6,
        "precedes": 0.5,
    },
    "write": {
        "similar_to": 0.5,
        "requires": 1.0,
        "complementary": 0.95,
        "conflicts_with": 0.3,
        "belongs_to": 0.5,
        "precedes": 0.7,
    },
    "delete": {
        "similar_to": 0.4,
        "requires": 0.9,
        "complementary": 0.3,
        "conflicts_with": 0.5,
        "belongs_to": 0.5,
        "precedes": 0.8,
    },
}


class FixedGraphRetriever:
    """Apply one frozen graph profile without changing B4's seed ranking.

    ``untyped_topology`` observes only non-contract adjacency and assigns every
    traversed edge the same weight. ``typed_contract`` additionally observes
    API-contract edges and uses frozen relation/confidence weights.
    """

    def __init__(self, graph: ToolGraph, *, profile: str) -> None:
        if profile not in _PROFILES:
            raise ValueError(f"Unknown fixed graph profile: {profile}")
        self.graph = graph
        self.profile = profile

    def rank(
        self,
        query: str,
        base_ranking: list[RankedCandidate],
        *,
        top_k: int,
    ) -> tuple[list[RankedCandidate], dict[str, Any]]:
        if top_k <= 0 or not base_ranking:
            return [], self._diagnostics([], set(), set())

        unique_base: list[RankedCandidate] = []
        seen: set[str] = set()
        for candidate in base_ranking:
            if candidate.name in seen or candidate.name not in self.graph.tools:
                continue
            unique_base.append(candidate)
            seen.add(candidate.name)
        if not unique_base:
            return [], self._diagnostics([], set(), set())

        base_scores = _normalized_base_scores(unique_base)
        seed_names = [candidate.name for candidate in unique_base[:FIXED_GRAPH_SEED_COUNT]]
        frontier = {name: base_scores[name] for name in seed_names}
        best_path = dict(frontier)
        graph_scores: dict[str, float] = {}
        used_edges: set[tuple[str, str]] = set()
        contract_edges: set[tuple[str, str]] = set()
        relation_weights = _relation_weights(query)

        for depth in range(1, FIXED_GRAPH_DEPTH + 1):
            decay = 1.0 / (0.5 * depth + 1.0)
            next_frontier: dict[str, float] = {}
            for node, parent_score in sorted(frontier.items()):
                for source, target, attrs in _sorted_edges(self.graph, node):
                    is_contract = _is_contract_edge(attrs)
                    if self.profile == "untyped_topology" and is_contract:
                        continue
                    neighbour = target if source == node else source
                    if neighbour not in self.graph.tools:
                        continue
                    edge_score = _edge_score(
                        attrs,
                        profile=self.profile,
                        relation_weights=relation_weights,
                    )
                    propagated = parent_score * edge_score * decay
                    if propagated <= best_path.get(neighbour, 0.0):
                        continue
                    best_path[neighbour] = propagated
                    graph_scores[neighbour] = max(graph_scores.get(neighbour, 0.0), propagated)
                    next_frontier[neighbour] = max(
                        next_frontier.get(neighbour, 0.0),
                        propagated,
                    )
                    edge_key = (source, target)
                    used_edges.add(edge_key)
                    if is_contract:
                        contract_edges.add(edge_key)
            frontier = next_frontier
            if not frontier:
                break

        base_rank = {candidate.name: index for index, candidate in enumerate(unique_base)}
        seed_set = set(seed_names)
        rescored = []
        for candidate in unique_base:
            if candidate.name in seed_set:
                score = base_scores[candidate.name]
            elif candidate.name in graph_scores:
                score = graph_scores[candidate.name]
            else:
                score = -(base_rank[candidate.name] + 1) * 1e-6
            rescored.append(RankedCandidate(name=candidate.name, score=score))
        rescored.sort(
            key=lambda candidate: (
                -candidate.score,
                base_rank[candidate.name],
                candidate.name.casefold(),
                candidate.name,
            )
        )
        diagnostics = self._diagnostics(seed_names, used_edges, contract_edges)
        diagnostics["expanded_tool_count"] = len(set(graph_scores) - set(seed_names))
        diagnostics["graph_reached_tool_count"] = len(graph_scores)
        return rescored[:top_k], diagnostics

    def _diagnostics(
        self,
        seeds: list[str],
        used_edges: set[tuple[str, str]],
        contract_edges: set[tuple[str, str]],
    ) -> dict[str, Any]:
        return {
            "policy_revision": FIXED_GRAPH_POLICY_REVISION,
            "profile": self.profile,
            "seed_count": len(seeds),
            "seeds": list(seeds),
            "depth": FIXED_GRAPH_DEPTH,
            "score_combination": "seed_score_or_max_graph_path",
            "edge_count_used": len(used_edges),
            "contract_edges_used": len(contract_edges),
            "expanded_tool_count": 0,
            "graph_reached_tool_count": 0,
        }


def full_graph_pipeline_rank(
    query: str,
    typed_ranking: list[RankedCandidate],
    tools_by_name: dict[str, ToolSchema | dict[str, Any]],
    *,
    top_k: int,
) -> tuple[list[RankedCandidate], dict[str, Any]]:
    """Apply B7 target selection and bounded producer expansion to B6."""
    if top_k <= 0 or not typed_ranking:
        return [], {
            "selected_target": "",
            "producer_candidates": [],
            "candidate_count": 0,
            "target_selector": {},
        }

    pool = typed_ranking[:top_k]
    pool_names = [candidate.name for candidate in pool]
    tool_dicts = {
        name: tool.to_dict() if isinstance(tool, ToolSchema) else dict(tool)
        for name, tool in tools_by_name.items()
    }
    retrieval_results = [{"name": candidate.name, "score": candidate.score} for candidate in pool]
    selector = select_target_candidate(
        query,
        pool_names,
        tool_dicts,
        retrieval_results=retrieval_results,
    )
    selected_target = str(selector.get("selected_target") or "")
    ordered: list[str] = []
    if selected_target:
        ordered.append(selected_target)
    expanded = expand_candidates_with_producers(
        [selected_target] if selected_target else [],
        tool_dicts,
        max_producers_per_field=FIXED_PRODUCERS_PER_FIELD,
        max_hops=FIXED_PRODUCER_MAX_HOPS,
        action_priority=target_action_priority_for_query(query),
    )
    producer_candidates = [name for name in expanded if name != selected_target]
    ordered.extend(producer_candidates)
    ordered.extend(pool_names)
    selected_names = list(dict.fromkeys(name for name in ordered if name in tool_dicts))[:top_k]
    ranking = [
        RankedCandidate(name=name, score=1.0 / rank)
        for rank, name in enumerate(selected_names, start=1)
    ]
    return ranking, {
        "selected_target": selected_target,
        "producer_candidates": [name for name in producer_candidates if name in selected_names],
        "candidate_count": len(ranking),
        "target_selector": selector,
        "producer_expansion": {
            "max_hops": FIXED_PRODUCER_MAX_HOPS,
            "max_producers_per_field": FIXED_PRODUCERS_PER_FIELD,
        },
    }


def _normalized_base_scores(ranking: list[RankedCandidate]) -> dict[str, float]:
    maximum = max((max(0.0, float(candidate.score)) for candidate in ranking), default=0.0)
    if maximum > 0.0:
        return {candidate.name: max(0.0, float(candidate.score)) / maximum for candidate in ranking}
    return {candidate.name: 1.0 / rank for rank, candidate in enumerate(ranking, start=1)}


def _sorted_edges(
    graph: ToolGraph,
    node: str,
) -> list[tuple[str, str, dict[str, Any]]]:
    try:
        rows = graph.graph.get_edges_from(node, direction="both")
    except (KeyError, ValueError):
        return []
    return sorted(
        rows,
        key=lambda row: (
            row[0].casefold(),
            row[0],
            row[1].casefold(),
            row[1],
            _enum_value(row[2].get("relation")),
        ),
    )


def _is_contract_edge(attrs: dict[str, Any]) -> bool:
    sources = attrs.get("evidence_sources") or []
    if isinstance(sources, str):
        sources = [sources]
    return "api_contract" in {str(source).strip().lower() for source in sources}


def _edge_score(
    attrs: dict[str, Any],
    *,
    profile: str,
    relation_weights: dict[str, float],
) -> float:
    if profile == "untyped_topology":
        return 1.0
    relation = _enum_value(attrs.get("relation"))
    confidence = _enum_value(attrs.get("confidence")).upper()
    return relation_weights.get(relation, 0.3) * _CONFIDENCE_FACTORS.get(
        confidence,
        _CONFIDENCE_FACTORS[""],
    )


def _relation_weights(query: str) -> dict[str, float]:
    intent = classify_intent(query)
    if intent.is_neutral:
        return _DEFAULT_RELATION_WEIGHTS
    dimensions = {
        "read": intent.read_intent,
        "write": intent.write_intent,
        "delete": intent.delete_intent,
    }
    dominant = max(dimensions, key=dimensions.get)
    if dimensions[dominant] < 0.5:
        return _DEFAULT_RELATION_WEIGHTS
    return _INTENT_RELATION_WEIGHTS[dominant]


def _enum_value(value: Any) -> str:
    raw = value.value if hasattr(value, "value") else value
    return str(raw or "").strip().lower()
