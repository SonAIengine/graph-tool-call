"""Evidence-gated dependency completion for planner-facing tool bundles."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify.edges import (
    EVIDENCE_API_CONTRACT,
    EVIDENCE_MANUAL,
    EVIDENCE_NAME_BASED,
    EVIDENCE_OPENAPI_LINK,
    EVIDENCE_PROVEN,
    EVIDENCE_RUN,
)

DEPENDENCY_CLOSURE_POLICY_REVISION = "evidence-gated-dependency-closure-v1"
TOOL_BUNDLE_POLICY_REVISION = "role-budgeted-contract-bundle-v1"
_AUTO_EVIDENCE = frozenset(
    {
        EVIDENCE_API_CONTRACT,
        EVIDENCE_MANUAL,
        EVIDENCE_OPENAPI_LINK,
        EVIDENCE_PROVEN,
        EVIDENCE_RUN,
    }
)
_MUTATING_ACTIONS = frozenset({"create", "update", "delete", "action", "mutation"})
_DATA_KINDS = frozenset({"", "data"})


class TokenCounter(Protocol):
    """Minimal tokenizer contract accepted by :func:`assemble_tool_bundle`."""

    def count(self, text: str) -> int:
        """Return the model-facing token count for *text*."""


@dataclass(frozen=True)
class DependencyClosureResult:
    """A target-preserving, evidence-auditable dependency closure."""

    target: str
    required_dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    alternatives_by_field: dict[str, list[str]] = field(default_factory=dict)
    resolved_fields: list[dict[str, Any]] = field(default_factory=list)
    unresolved_fields: list[dict[str, Any]] = field(default_factory=list)
    dependency_paths: list[dict[str, Any]] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    policy_revision: str = DEPENDENCY_CLOSURE_POLICY_REVISION

    @property
    def complete(self) -> bool:
        return not self.unresolved_fields and not self.cycles

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["complete"] = self.complete
        return result


@dataclass(frozen=True)
class ToolBundle:
    """Role-separated, token-accounted catalog for target selection and planning."""

    target: str
    target_alternatives: list[str]
    required_tools: list[str]
    optional_tools: list[str]
    user_input_slots: list[dict[str, Any]]
    projected_schemas: dict[str, dict[str, Any]]
    admitted_tools: list[str]
    omitted_tools: list[str]
    token_budget: dict[str, Any]
    closure_status: str
    closure: dict[str, Any]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    policy_revision: str = TOOL_BUNDLE_POLICY_REVISION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _ProducerCandidate:
    name: str
    tier: int
    auto_selectable: bool
    matched_fields: tuple[str, ...]
    evidence_sources: tuple[str, ...]
    evidence: str
    type_compatible: bool
    mutating: bool
    graph_only: bool = False


def complete_target_dependencies(
    target: str,
    tools: dict[str, Any] | list[Any],
    *,
    graph: Any | None = None,
    available_fields: set[str] | list[str] | tuple[str, ...] | None = None,
    max_hops: int = 3,
    max_alternatives_per_field: int = 2,
    policy: str = "evidence_gated",
    learning_suggestions: list[dict[str, Any]] | None = None,
) -> DependencyClosureResult:
    """Complete required producer paths after a target has been selected.

    The target never competes with its dependencies. Strong graph/contract
    evidence may select a producer automatically; name-only evidence is kept as
    an explainable alternative and never silently changes the plan surface.
    """

    if policy != "evidence_gated":
        raise ValueError("policy must be 'evidence_gated'.")
    if max_hops < 0:
        raise ValueError("max_hops must be non-negative.")
    if max_alternatives_per_field < 0:
        raise ValueError("max_alternatives_per_field must be non-negative.")

    tools_by_name = _normalize_tools(tools)
    if target not in tools_by_name:
        return DependencyClosureResult(
            target=target,
            unresolved_fields=[{"tool": target, "reason": "unknown_target"}],
            diagnostics=[{"reason": "unknown_target", "tool": target}],
        )

    available = {_field_key(value) for value in (available_fields or []) if _field_key(value)}
    required: list[str] = []
    optional: list[str] = []
    alternatives: dict[str, list[str]] = {}
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    paths: list[dict[str, Any]] = []
    cycles: list[list[str]] = []
    evidence: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    selected = {target}
    learning = _promoted_learning_preferences(learning_suggestions or [])

    def visit(tool_name: str, depth: int, ancestry: list[str]) -> None:
        if depth > max_hops:
            unresolved.append({"tool": tool_name, "reason": "max_depth", "depth": depth})
            return

        graph_candidates = _graph_dependency_candidates(tool_name, graph, tools_by_name)
        for candidate in graph_candidates:
            if not candidate.auto_selectable:
                if candidate.name not in optional and candidate.name not in selected:
                    optional.append(candidate.name)
                continue
            _admit_candidate(
                candidate,
                consumer=tool_name,
                field_key="__graph__",
                depth=depth,
                ancestry=ancestry,
            )

        consumes = _required_data_consumes(tools_by_name[tool_name])
        for consume in consumes:
            key = _contract_key(consume)
            label = str(consume.get("field_name") or consume.get("semantic_tag") or key)
            if key in available:
                resolved.append(
                    {
                        "tool": tool_name,
                        "field": label,
                        "field_key": key,
                        "source": "available_field",
                    }
                )
                continue
            candidates = _contract_producer_candidates(
                tool_name,
                consume,
                tools_by_name,
                graph=graph,
                learning=learning,
            )
            auto = [candidate for candidate in candidates if candidate.auto_selectable]
            weak = [candidate for candidate in candidates if not candidate.auto_selectable]
            alternative_names = [candidate.name for candidate in [*auto[1:], *weak]][
                :max_alternatives_per_field
            ]
            if alternative_names:
                alternatives[f"{tool_name}.{label}"] = alternative_names
            if not auto:
                reason = "ambiguous_producer" if candidates else "no_producer"
                unresolved.append(
                    {
                        "tool": tool_name,
                        "field": label,
                        "field_key": key,
                        "reason": reason,
                        "alternatives": alternative_names,
                    }
                )
                continue
            chosen = auto[0]
            resolved.append(
                {
                    "tool": tool_name,
                    "field": label,
                    "field_key": key,
                    "source": "producer",
                    "producer": chosen.name,
                    "evidence_tier": chosen.tier,
                }
            )
            _admit_candidate(
                chosen,
                consumer=tool_name,
                field_key=key,
                depth=depth,
                ancestry=ancestry,
            )

    def _admit_candidate(
        candidate: _ProducerCandidate,
        *,
        consumer: str,
        field_key: str,
        depth: int,
        ancestry: list[str],
    ) -> None:
        path = [*ancestry, consumer, candidate.name]
        if candidate.name in [*ancestry, consumer]:
            cycle_start = path.index(candidate.name)
            cycle = path[cycle_start:]
            if cycle not in cycles:
                cycles.append(cycle)
            diagnostics.append(
                {"reason": "cycle", "consumer": consumer, "producer": candidate.name}
            )
            return
        if depth >= max_hops:
            unresolved.append(
                {
                    "tool": consumer,
                    "field_key": field_key,
                    "reason": "max_depth",
                    "depth": depth,
                    "producer_candidate": candidate.name,
                }
            )
            return
        evidence_row = {
            "consumer": consumer,
            "producer": candidate.name,
            "field_key": field_key,
            "tier": candidate.tier,
            "sources": list(candidate.evidence_sources),
            "evidence": candidate.evidence,
            "type_compatible": candidate.type_compatible,
            "mutating": candidate.mutating,
        }
        if evidence_row not in evidence:
            evidence.append(evidence_row)
        path_row = {
            "consumer": consumer,
            "producer": candidate.name,
            "field_key": field_key,
            "depth": depth + 1,
            "path": path,
            "evidence_tier": candidate.tier,
        }
        if path_row not in paths:
            paths.append(path_row)
        if candidate.name in selected:
            return
        selected.add(candidate.name)
        required.append(candidate.name)
        visit(candidate.name, depth + 1, [*ancestry, consumer])

    visit(target, 0, [])
    for row in unresolved:
        diagnostics.append(dict(row))
    return DependencyClosureResult(
        target=target,
        required_dependencies=required,
        optional_dependencies=optional,
        alternatives_by_field=alternatives,
        resolved_fields=resolved,
        unresolved_fields=_dedupe_dicts(unresolved),
        dependency_paths=paths,
        cycles=cycles,
        evidence=evidence,
        diagnostics=_dedupe_dicts(diagnostics),
    )


def assemble_tool_bundle(
    query: str,
    target: str,
    tools: dict[str, Any] | list[Any],
    *,
    graph: Any | None = None,
    target_alternatives: list[str] | None = None,
    available_fields: set[str] | list[str] | tuple[str, ...] | None = None,
    max_hops: int = 3,
    max_alternatives_per_field: int = 2,
    token_budget: int | None = None,
    token_counter: TokenCounter | Any | None = None,
    learning_suggestions: list[dict[str, Any]] | None = None,
) -> ToolBundle:
    """Build a target-first, dependency-closed model-facing tool bundle."""

    del query  # Reserved for future query-conditioned admission without changing the contract.
    tools_by_name = _normalize_tools(tools)
    closure = complete_target_dependencies(
        target,
        tools_by_name,
        graph=graph,
        available_fields=available_fields,
        max_hops=max_hops,
        max_alternatives_per_field=max_alternatives_per_field,
        learning_suggestions=learning_suggestions,
    )
    alternatives = [
        name
        for name in _dedupe_names(target_alternatives or [])
        if name in tools_by_name and name != target
    ]
    required_order = [target, *closure.required_dependencies]
    optional_order = [
        name
        for name in [*alternatives, *closure.optional_dependencies]
        if name not in required_order
    ]
    candidate_order = _dedupe_names([*required_order, *optional_order])
    projected = {
        name: contract_projected_tool_schema(tools_by_name[name])
        for name in candidate_order
        if name in tools_by_name
    }
    admitted, omitted, budget_info = _admit_projected_schemas(
        candidate_order,
        projected,
        required_names=set(required_order),
        token_budget=token_budget,
        token_counter=token_counter,
    )
    missing_required = [name for name in required_order if name not in admitted]
    diagnostics = list(closure.diagnostics)
    if missing_required:
        diagnostics.append(
            {
                "reason": "budget_insufficient",
                "missing_required_tools": missing_required,
            }
        )
    status = "ready"
    if missing_required:
        status = "budget_insufficient"
    elif closure.cycles:
        status = "cycle"
    elif closure.unresolved_fields:
        status = "incomplete"
    user_slots = [
        row
        for row in closure.unresolved_fields
        if row.get("reason") in {"no_producer", "ambiguous_producer"}
    ]
    return ToolBundle(
        target=target,
        target_alternatives=alternatives,
        required_tools=list(closure.required_dependencies),
        optional_tools=list(closure.optional_dependencies),
        user_input_slots=user_slots,
        projected_schemas={name: projected[name] for name in admitted},
        admitted_tools=admitted,
        omitted_tools=omitted,
        token_budget=budget_info,
        closure_status=status,
        closure=closure.to_dict(),
        diagnostics=_dedupe_dicts(diagnostics),
    )


def contract_projected_tool_schema(tool: Any) -> dict[str, Any]:
    """Return a compact required-input view; the full tool remains authoritative."""

    row = _tool_dict(tool)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
    openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
    description = ai.get("one_line_summary") or openapi.get("summary") or row.get("description")
    parameters = []
    for parameter in row.get("parameters") or []:
        if not isinstance(parameter, dict) or not parameter.get("required"):
            continue
        parameters.append(
            {
                "name": str(parameter.get("name") or ""),
                "type": str(parameter.get("type") or "string"),
                "description": _bounded_text(parameter.get("description"), 160),
                "required": True,
                "enum": list(parameter.get("enum") or [])[:16] or None,
            }
        )
    return {
        "name": str(row.get("name") or ""),
        "description": _bounded_text(description, 240),
        "parameters": parameters,
    }


def _admit_projected_schemas(
    ordered_names: list[str],
    projected: dict[str, dict[str, Any]],
    *,
    required_names: set[str],
    token_budget: int | None,
    token_counter: Any | None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    if token_budget is not None and token_budget <= 0:
        raise ValueError("token_budget must be greater than zero.")
    admitted: list[str] = []
    omitted: list[str] = []
    payloads: list[dict[str, Any]] = []
    used = _count_payloads(payloads, token_counter)
    for name in ordered_names:
        candidate_payloads = [*payloads, projected[name]]
        candidate_tokens = _count_payloads(candidate_payloads, token_counter)
        if token_budget is not None and candidate_tokens > token_budget:
            omitted.append(name)
            if name in required_names:
                # Required closure is an ordered chain. Later tools cannot make it complete.
                omitted.extend(item for item in ordered_names if item not in admitted + omitted)
                break
            continue
        admitted.append(name)
        payloads = candidate_payloads
        used = candidate_tokens
    omitted.extend(name for name in ordered_names if name not in admitted + omitted)
    return (
        admitted,
        omitted,
        {
            "limit": token_budget,
            "used": used,
            "utilization": (used / token_budget) if token_budget else None,
            "accounting": "provided_token_counter"
            if token_counter is not None
            else "utf8_chars_div_3",
            "policy_revision": TOOL_BUNDLE_POLICY_REVISION,
            "required_tool_count": len(required_names),
            "admitted_required_tool_count": len(required_names.intersection(admitted)),
        },
    )


def _count_payloads(payloads: list[dict[str, Any]], token_counter: Any | None) -> int:
    serialized = json.dumps(payloads, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if token_counter is None:
        return math.ceil(len(serialized.encode("utf-8")) / 3)
    count = getattr(token_counter, "count", token_counter)
    if not callable(count):
        raise TypeError("token_counter must be callable or expose count(text).")
    return int(count(serialized))


def _contract_producer_candidates(
    consumer_name: str,
    consume: dict[str, Any],
    tools_by_name: dict[str, dict[str, Any]],
    *,
    graph: Any | None,
    learning: set[tuple[str, str]],
) -> list[_ProducerCandidate]:
    candidates: list[_ProducerCandidate] = []
    consume_semantic = _field_key(consume.get("semantic_tag"))
    consume_field = _field_key(consume.get("field_name"))
    consume_type = _field_type(consume)
    graph_by_name = {
        candidate.name: candidate
        for candidate in _graph_dependency_candidates(consumer_name, graph, tools_by_name)
    }
    for name, tool in tools_by_name.items():
        if name == consumer_name:
            continue
        best: _ProducerCandidate | None = None
        for produce in _produces(tool):
            semantic_match = (
                bool(consume_semantic)
                and _field_key(produce.get("semantic_tag")) == consume_semantic
            )
            field_match = (
                bool(consume_field) and _field_key(produce.get("field_name")) == consume_field
            )
            if not semantic_match and not field_match:
                continue
            compatible = _types_compatible(consume_type, _field_type(produce))
            if not compatible:
                continue
            graph_candidate = graph_by_name.get(name)
            sources = set(_contract_sources(consume, produce))
            if graph_candidate:
                sources.update(graph_candidate.evidence_sources)
            if semantic_match:
                tier = 1 if sources.intersection(_AUTO_EVIDENCE) else 2
            else:
                tier = 2 if sources.intersection(_AUTO_EVIDENCE) else 3
            auto = tier <= 3 and sources != {EVIDENCE_NAME_BASED}
            evidence_text = (
                f"contract:{'semantic_tag' if semantic_match else 'field_name'}:"
                f"{consume.get('field_name') or consume.get('semantic_tag')}"
            )
            best = _ProducerCandidate(
                name=name,
                tier=tier,
                auto_selectable=auto,
                matched_fields=(consume_field or consume_semantic,),
                evidence_sources=tuple(sorted(sources or {EVIDENCE_API_CONTRACT})),
                evidence=evidence_text,
                type_compatible=True,
                mutating=_is_mutating(tool),
            )
            break
        if best:
            candidates.append(best)
    candidates.sort(
        key=lambda item: (
            item.tier,
            item.mutating,
            (consumer_name, item.name) not in learning,
            item.name,
        )
    )
    return candidates


def _graph_dependency_candidates(
    consumer: str,
    graph: Any | None,
    tools_by_name: dict[str, dict[str, Any]],
) -> list[_ProducerCandidate]:
    rows = _graph_edges_for_consumer(consumer, graph)
    candidates: list[_ProducerCandidate] = []
    for producer, attrs in rows:
        if producer == consumer or producer not in tools_by_name:
            continue
        relation = _relation_value(attrs.get("relation"))
        sources = tuple(sorted(str(value) for value in attrs.get("evidence_sources") or []))
        confidence = str(_enum_value(attrs.get("confidence")) or "").upper()
        score = float(attrs.get("conf_score") or 0.0)
        manual_like = bool(attrs.get("is_manual")) or bool(
            set(sources).intersection(_AUTO_EVIDENCE)
        )
        direct_required = relation in {"requires", "produces_for"}
        extracted = confidence == "EXTRACTED" or score >= 0.8
        auto = direct_required and (manual_like or extracted)
        optional = relation in {"complementary", "pairs_well_with", "precedes"}
        if not auto and not optional:
            continue
        tier = 1 if auto and manual_like else 2 if auto else 4
        candidates.append(
            _ProducerCandidate(
                name=producer,
                tier=tier,
                auto_selectable=auto,
                matched_fields=tuple(),
                evidence_sources=sources or ((EVIDENCE_MANUAL,) if attrs.get("is_manual") else ()),
                evidence=str(attrs.get("evidence") or f"graph:{relation}"),
                type_compatible=True,
                mutating=_is_mutating(tools_by_name[producer]),
                graph_only=True,
            )
        )
    candidates.sort(key=lambda item: (item.tier, item.mutating, item.name))
    return candidates


def _graph_edges_for_consumer(consumer: str, graph: Any | None) -> list[tuple[str, dict[str, Any]]]:
    if graph is None:
        return []
    if isinstance(graph, dict):
        if consumer in graph and isinstance(graph[consumer], list):
            return [
                (
                    str(name),
                    {
                        "relation": "requires",
                        "confidence": "EXTRACTED",
                        "is_manual": True,
                    },
                )
                for name in graph[consumer]
            ]
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        return _plain_edge_dependencies(consumer, edges)
    backend = getattr(graph, "graph", graph)
    get_edges = getattr(backend, "get_edges_from", None)
    if not callable(get_edges):
        return []
    rows: list[tuple[str, dict[str, Any]]] = []
    for source, target, attrs in get_edges(consumer, direction="both"):
        relation = _relation_value(attrs.get("relation"))
        sources = set(str(value) for value in attrs.get("evidence_sources") or [])
        if source == consumer and relation != "produces_for":
            rows.append((str(target), dict(attrs)))
        elif target == consumer and sources.intersection({EVIDENCE_RUN, EVIDENCE_PROVEN}):
            rows.append((str(source), dict(attrs)))
        elif target == consumer and relation == "produces_for":
            rows.append((str(source), dict(attrs)))
    return rows


def _plain_edge_dependencies(
    consumer: str, edges: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        attrs = {key: value for key, value in edge.items() if key not in {"source", "target"}}
        sources = set(str(value) for value in attrs.get("evidence_sources") or [])
        relation = _relation_value(attrs.get("relation"))
        if source == consumer and relation != "produces_for":
            rows.append((target, attrs))
        elif target == consumer and sources.intersection({EVIDENCE_RUN, EVIDENCE_PROVEN}):
            rows.append((source, attrs))
        elif target == consumer and relation == "produces_for":
            rows.append((source, attrs))
    return rows


def _normalize_tools(tools: dict[str, Any] | list[Any]) -> dict[str, dict[str, Any]]:
    values = tools.values() if isinstance(tools, dict) else tools
    result: dict[str, dict[str, Any]] = {}
    for tool in values:
        row = _tool_dict(tool)
        name = str(row.get("name") or "")
        if name:
            result[name] = row
    return result


def _tool_dict(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        return dict(tool)
    if isinstance(tool, ToolSchema):
        return tool.to_dict()
    dump = getattr(tool, "to_dict", None)
    if callable(dump):
        return dict(dump())
    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", ""),
        "parameters": [
            parameter.to_dict() if hasattr(parameter, "to_dict") else dict(parameter)
            for parameter in getattr(tool, "parameters", [])
        ],
        "metadata": getattr(tool, "metadata", {}) or {},
    }


def _required_data_consumes(tool: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in _consumes(tool)
        if row.get("required") and str(row.get("kind") or "data").strip().lower() in _DATA_KINDS
    ]


def _consumes(tool: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    rows = metadata.get("consumes")
    if not isinstance(rows, list):
        api = metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
        rows = api.get("consumes")
    return [dict(row) for row in rows or [] if isinstance(row, dict)]


def _produces(tool: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    rows = metadata.get("produces")
    if not isinstance(rows, list):
        api = metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
        rows = api.get("produces")
    return [dict(row) for row in rows or [] if isinstance(row, dict)]


def _contract_sources(consume: dict[str, Any], produce: dict[str, Any]) -> set[str]:
    sources = {
        str(value)
        for value in (consume.get("evidence_sources") or [])
        + (produce.get("evidence_sources") or [])
    }
    for row in (consume, produce):
        source = str(row.get("contract_source") or "")
        if source:
            sources.add(source)
        if row.get("openapi_link_name"):
            sources.add(EVIDENCE_OPENAPI_LINK)
    return sources


def _types_compatible(left: str, right: str) -> bool:
    if not left or not right or left == "any" or right == "any":
        return True
    aliases = {"integer": "number", "float": "number", "double": "number"}
    return aliases.get(left, left) == aliases.get(right, right)


def _field_type(row: dict[str, Any]) -> str:
    value = row.get("field_type") or row.get("type") or ""
    if isinstance(value, dict):
        value = value.get("type")
    return str(value or "").strip().lower()


def _contract_key(row: dict[str, Any]) -> str:
    return _field_key(row.get("semantic_tag")) or _field_key(row.get("field_name"))


def _field_key(value: Any) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")


def _is_mutating(tool: dict[str, Any]) -> bool:
    metadata = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
    action = str(ai.get("canonical_action") or "").lower()
    method = str(metadata.get("method") or "").lower()
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    return (
        action in _MUTATING_ACTIONS
        or method in {"post", "put", "patch", "delete"}
        or bool(annotations.get("destructive_hint"))
    )


def _promoted_learning_preferences(suggestions: list[dict[str, Any]]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for row in suggestions:
        if str(row.get("status") or "") != "promoted":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        consumer = str(payload.get("consumer") or payload.get("target") or "")
        producer = str(payload.get("producer") or payload.get("source") or "")
        if consumer and producer:
            result.add((consumer, producer))
    return result


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _relation_value(value: Any) -> str:
    return str(_enum_value(value) or "").lower()


def _bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _dedupe_names(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        marker = json.dumps(value, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


__all__ = [
    "DEPENDENCY_CLOSURE_POLICY_REVISION",
    "TOOL_BUNDLE_POLICY_REVISION",
    "DependencyClosureResult",
    "TokenCounter",
    "ToolBundle",
    "assemble_tool_bundle",
    "complete_target_dependencies",
    "contract_projected_tool_schema",
]
