"""Frozen graph ablations layered on the B4 flat-semantic ranking."""

from __future__ import annotations

import re
from typing import Any

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import (
    CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION,
    expand_candidates_with_producers,
    select_target_candidate,
    target_action_priority_for_query,
)
from graph_tool_call.retrieval.intent import classify_intent
from graph_tool_call.tool_graph import ToolGraph

from .retrievers import RankedCandidate, fixed_lexical_tokens

FIXED_GRAPH_POLICY_REVISION = "paper-graph-rerank-v1"
FIXED_GRAPH_SEED_COUNT = 5
FIXED_GRAPH_DEPTH = 2
FIXED_GRAPH_ADMISSION_POLICY_REVISION = "paper-consumer-aligned-contract-slot-v1"
FIXED_GRAPH_ADMISSION_RESERVED_SLOTS = 1
FIXED_PRODUCER_MAX_HOPS = 1
FIXED_PRODUCERS_PER_FIELD = 3

_PROFILES = frozenset({"untyped_topology", "typed_contract"})
_ADMISSION_POLICIES = frozenset({"protected_seeds", "consumer_aligned_contract_slot"})
_ADMISSION_ACTION_ALIASES = {
    "search": ("list", "find", "search", "query", "목록", "검색", "찾"),
    "read": (
        "read",
        "get",
        "show",
        "inspect",
        "check",
        "detail",
        "status",
        "log",
        "확인",
        "조회",
        "상태",
        "상세",
        "로그",
    ),
    "create": ("create", "add", "register", "생성", "추가", "등록"),
    "update": ("update", "modify", "edit", "change", "수정", "변경", "편집"),
    "delete": ("delete", "remove", "withdraw", "삭제", "제거", "탈퇴"),
    "action": ("send", "execute", "run", "approve", "reject", "실행", "승인", "거절"),
}
_ADMISSION_RESOURCE_STOPWORDS = frozenset(
    {
        "api",
        "all",
        "and",
        "core",
        "every",
        "for",
        "from",
        "in",
        "into",
        "namespaced",
        "namespace",
        "namespaces",
        "of",
        "one",
        "on",
        "or",
        "specified",
        "the",
        "to",
        "v1",
        "v2",
        "with",
        *(alias for aliases in _ADMISSION_ACTION_ALIASES.values() for alias in aliases),
    }
)
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

    def __init__(
        self,
        graph: ToolGraph,
        *,
        profile: str,
        admission_policy: str = "protected_seeds",
    ) -> None:
        if profile not in _PROFILES:
            raise ValueError(f"Unknown fixed graph profile: {profile}")
        if admission_policy not in _ADMISSION_POLICIES:
            raise ValueError(f"Unknown fixed graph admission policy: {admission_policy}")
        self.graph = graph
        self.profile = profile
        self.admission_policy = admission_policy

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
        best_path_nodes = {name: [name] for name in seed_names}
        consumer_aligned_scores: dict[str, float] = {}
        consumer_aligned_paths: dict[str, list[str]] = {}
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
                    if (
                        source == node
                        and _is_consumer_aligned_contract_edge(
                            self.graph,
                            source,
                            target,
                            attrs,
                        )
                        and propagated > consumer_aligned_scores.get(neighbour, 0.0)
                    ):
                        consumer_aligned_scores[neighbour] = propagated
                        consumer_aligned_paths[neighbour] = [
                            *best_path_nodes[node],
                            neighbour,
                        ]
                    if propagated <= best_path.get(neighbour, 0.0):
                        continue
                    best_path[neighbour] = propagated
                    best_path_nodes[neighbour] = [*best_path_nodes[node], neighbour]
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
        selected, admission = _apply_candidate_admission(
            rescored,
            query=query,
            graph=self.graph,
            top_k=top_k,
            seed_names=seed_names,
            consumer_aligned_scores=consumer_aligned_scores,
            consumer_aligned_paths=consumer_aligned_paths,
            policy=self.admission_policy,
        )
        diagnostics = self._diagnostics(seed_names, used_edges, contract_edges)
        diagnostics["expanded_tool_count"] = len(set(graph_scores) - set(seed_names))
        diagnostics["graph_reached_tool_count"] = len(graph_scores)
        diagnostics["candidate_admission"] = admission
        return selected, diagnostics

    def _diagnostics(
        self,
        seeds: list[str],
        used_edges: set[tuple[str, str]],
        contract_edges: set[tuple[str, str]],
    ) -> dict[str, Any]:
        return {
            "policy_revision": FIXED_GRAPH_POLICY_REVISION,
            "profile": self.profile,
            "admission_policy": self.admission_policy,
            "seed_count": len(seeds),
            "seeds": list(seeds),
            "depth": FIXED_GRAPH_DEPTH,
            "score_combination": "seed_score_or_max_graph_path",
            "edge_count_used": len(used_edges),
            "contract_edges_used": len(contract_edges),
            "expanded_tool_count": 0,
            "graph_reached_tool_count": 0,
        }


def _apply_candidate_admission(
    ranking: list[RankedCandidate],
    *,
    query: str,
    graph: ToolGraph,
    top_k: int,
    seed_names: list[str],
    consumer_aligned_scores: dict[str, float],
    consumer_aligned_paths: dict[str, list[str]],
    policy: str,
) -> tuple[list[RankedCandidate], dict[str, Any]]:
    selected = list(ranking[:top_k])
    diagnostics: dict[str, Any] = {
        "policy_revision": FIXED_GRAPH_ADMISSION_POLICY_REVISION,
        "policy": policy,
        "surface_top_k": top_k,
        "reserved_slots": (
            FIXED_GRAPH_ADMISSION_RESERVED_SLOTS
            if policy == "consumer_aligned_contract_slot" and top_k > 1
            else 0
        ),
        "qualification": (
            "non_seed_forward_consumer_aligned_api_contract_path"
            "_and_first_query_action_resource_match"
        ),
        "contract_qualified_candidate_count": 0,
        "qualified_candidate_count": 0,
        "satisfied_by_ranking": False,
        "triggered": False,
        "admitted": [],
        "evicted": [],
    }
    if policy != "consumer_aligned_contract_slot" or top_k <= 1 or len(selected) < top_k:
        return selected, diagnostics

    seed_set = set(seed_names)
    ranking_index = {candidate.name: index for index, candidate in enumerate(ranking)}
    contract_qualified = sorted(
        (
            candidate
            for candidate in ranking
            if candidate.name not in seed_set and candidate.name in consumer_aligned_scores
        ),
        key=lambda candidate: (
            -consumer_aligned_scores[candidate.name],
            ranking_index[candidate.name],
            candidate.name.casefold(),
            candidate.name,
        ),
    )
    semantic_evidence = {
        candidate.name: _candidate_admission_semantic_evidence(
            query,
            graph.tools[candidate.name],
        )
        for candidate in contract_qualified
    }
    qualified = [candidate for candidate in contract_qualified if semantic_evidence[candidate.name]]
    diagnostics["contract_qualified_candidate_count"] = len(contract_qualified)
    diagnostics["qualified_candidate_count"] = len(qualified)
    selected_names = {candidate.name for candidate in selected}
    if any(candidate.name in selected_names for candidate in qualified):
        diagnostics["satisfied_by_ranking"] = True
        return selected, diagnostics
    if not qualified:
        return selected, diagnostics

    admitted = qualified[0]
    evicted = selected[-1]
    selected[-1] = admitted
    diagnostics["triggered"] = True
    diagnostics["admitted"] = [
        {
            "name": admitted.name,
            "score": admitted.score,
            "admission_score": consumer_aligned_scores[admitted.name],
            "path": consumer_aligned_paths.get(admitted.name, []),
            "semantic_evidence": semantic_evidence[admitted.name],
        }
    ]
    diagnostics["evicted"] = [{"name": evicted.name, "score": evicted.score}]
    return selected, diagnostics


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


def _is_consumer_aligned_contract_edge(
    graph: ToolGraph,
    source: str,
    target: str,
    attrs: dict[str, Any],
) -> bool:
    if not _is_contract_edge(attrs):
        return False
    producer = graph.tools.get(target)
    if producer is None:
        return False
    data_flow = attrs.get("data_flow") or {}
    from_field = str(data_flow.get("from_field") or "")
    from_path = str(data_flow.get("from_path") or "")
    for row in producer.metadata.get("produces") or []:
        if not row.get("consumer_alignment_only"):
            continue
        alignment = row.get("consumer_alignment") or {}
        if alignment.get("policy_revision") != CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION:
            continue
        if source not in set(alignment.get("consumer_tools") or []):
            continue
        if from_field and row.get("field_name") != from_field:
            continue
        if from_path and row.get("json_path") != from_path:
            continue
        return True
    return False


def _candidate_admission_semantic_evidence(
    query: str,
    tool: ToolSchema,
) -> list[dict[str, Any]]:
    first_action = _first_query_action(query)
    ai = tool.metadata.get("ai_metadata") or {}
    canonical_action = str(ai.get("canonical_action") or "").strip().lower()
    if not first_action or canonical_action != first_action:
        return []

    openapi = tool.metadata.get("openapi") or {}
    surface = " ".join(
        [
            str(ai.get("primary_resource") or ""),
            str(openapi.get("path_module") or ""),
        ]
    )
    if not _resource_terms(surface):
        surface = " ".join(
            [
                tool.name,
                str(ai.get("one_line_summary") or ""),
                str(openapi.get("summary") or ""),
            ]
        )
    query_terms = _resource_terms(query)
    candidate_terms = _resource_terms(surface)
    matched_terms = sorted(query_terms & candidate_terms)
    if not matched_terms:
        return []
    return [
        {
            "source": "first_query_action",
            "value": canonical_action,
        },
        {
            "source": "resource_terms",
            "matched_terms": matched_terms[:12],
        },
    ]


def _first_query_action(query: str) -> str:
    normalized = str(query or "").casefold()
    matches: list[tuple[int, str]] = []
    for action, aliases in _ADMISSION_ACTION_ALIASES.items():
        for alias in aliases:
            if alias.isascii():
                match = re.search(rf"\b{re.escape(alias)}\b", normalized)
                position = match.start() if match else -1
            else:
                position = normalized.find(alias)
            if position >= 0:
                matches.append((position, action))
    return min(matches)[1] if matches else ""


def _resource_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in fixed_lexical_tokens(text):
        if token in _ADMISSION_RESOURCE_STOPWORDS or len(token) <= 1:
            continue
        terms.add(token)
        if token.isascii() and token.endswith("s") and len(token) > 3:
            terms.add(token[:-1])
    return terms


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
