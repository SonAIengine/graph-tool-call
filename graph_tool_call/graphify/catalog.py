"""Catalog helpers shared by retrieval and plan synthesis adapters."""

from __future__ import annotations

import re
from typing import Any

from graph_tool_call.retrieval.intent import classify_intent

_DEFAULT_ACTION_PRIORITY = {"search": 3, "read": 2, "action": 1}
_ACTION_PRIORITY_SEARCH = {"search": 6, "read": 4, "action": 2}
_ACTION_PRIORITY_READ = {"read": 6, "search": 4, "action": 2}
_ACTION_PRIORITY_CREATE = {"create": 6, "action": 5, "update": 3, "read": 2, "search": 1}
_ACTION_PRIORITY_UPDATE = {"update": 6, "action": 5, "create": 3, "read": 2, "search": 1}
_ACTION_PRIORITY_ACTION = {"action": 6, "update": 4, "create": 3, "read": 2, "search": 1}
_ACTION_PRIORITY_DELETE = {"delete": 6, "action": 5, "update": 3, "read": 1, "search": 1}
_ACTION_PRIORITY_NOTIFICATION = {"create": 7, "action": 6, "update": 3, "read": 2, "search": 1}

_SEARCH_TERMS = frozenset(
    {"search", "find", "query", "lookup", "list", "browse", "검색", "찾", "목록", "리스트"}
)
_READ_TERMS = frozenset(
    {"get", "read", "detail", "view", "show", "check", "retrieve", "조회", "상세", "보기", "확인"}
)
_DETAIL_READ_TERMS = frozenset({"detail", "details", "view", "show", "상세", "보기", "보여"})
_AUDIT_READ_TERMS = frozenset(
    {"audit", "log", "logs", "history", "event", "events", "감사", "로그", "이력", "기록"}
)
_CREATE_TERMS = frozenset(
    {"create", "add", "register", "insert", "submit", "write", "생성", "추가", "등록", "작성"}
)
_UPDATE_TERMS = frozenset(
    {"update", "modify", "edit", "change", "set", "patch", "put", "수정", "변경", "편집", "설정"}
)
_ACTION_TERMS = frozenset(
    {
        "send",
        "approve",
        "process",
        "execute",
        "run",
        "apply",
        "assign",
        "checkout",
        "issue",
        "validate",
        "전송",
        "승인",
        "처리",
        "실행",
        "적용",
        "부여",
        "발급",
        "결제",
        "검증",
    }
)
_NOTIFICATION_TERMS = frozenset({"notification", "notify", "alert", "message", "알림", "메시지"})
_NOTIFICATION_SEND_TERMS = frozenset({"send", "notify", "전송", "보내", "발송"})
_DELETE_TERMS = frozenset(
    {
        "delete",
        "remove",
        "cancel",
        "revoke",
        "disable",
        "drop",
        "삭제",
        "제거",
        "취소",
        "철회",
        "해제",
    }
)
_SURFACE_STOPWORDS = frozenset(
    {
        "and",
        "are",
        "based",
        "can",
        "default",
        "for",
        "from",
        "function",
        "given",
        "into",
        "its",
        "one",
        "optional",
        "parameter",
        "parameters",
        "return",
        "returns",
        "specific",
        "the",
        "this",
        "two",
        "use",
        "used",
        "using",
        "value",
        "with",
    }
)


def target_action_priority_for_query(query: str) -> dict[str, int]:
    """Derive deterministic canonical-action priority from a user query.

    The result is intentionally generic: adapters can pass it directly to
    ``build_candidate_set(..., target_action_priority=...)`` to rerank target
    candidates by ``ai_metadata.canonical_action`` without an LLM. Empty or
    ambiguous queries return an empty dict, preserving retrieval order.
    """

    terms = _query_terms(query)
    has_delete = _has_action_term(terms, _DELETE_TERMS)
    has_action = _has_action_term(terms, _ACTION_TERMS)
    has_update = _has_action_term(terms, _UPDATE_TERMS)
    has_create = _has_action_term(terms, _CREATE_TERMS)
    has_search = _has_action_term(terms, _SEARCH_TERMS)
    has_read = _has_action_term(terms, _READ_TERMS)

    if has_read and _has_action_term(terms, _AUDIT_READ_TERMS):
        return dict(_ACTION_PRIORITY_READ)
    if _has_action_term(terms, _NOTIFICATION_TERMS) and _has_action_term(
        terms,
        _NOTIFICATION_SEND_TERMS,
    ):
        return dict(_ACTION_PRIORITY_NOTIFICATION)
    if has_delete:
        return dict(_ACTION_PRIORITY_DELETE)
    if has_action:
        return dict(_ACTION_PRIORITY_ACTION)
    if has_read and _has_action_term(terms, _DETAIL_READ_TERMS):
        return dict(_ACTION_PRIORITY_READ)
    if has_update:
        return dict(_ACTION_PRIORITY_UPDATE)
    if has_create:
        return dict(_ACTION_PRIORITY_CREATE)
    if has_search:
        return dict(_ACTION_PRIORITY_SEARCH)
    if has_read:
        return dict(_ACTION_PRIORITY_READ)

    intent = classify_intent(query)
    if intent.is_neutral:
        return {}
    if intent.delete_intent >= max(intent.read_intent, intent.write_intent):
        return dict(_ACTION_PRIORITY_DELETE)
    if intent.write_intent >= max(intent.read_intent, intent.delete_intent):
        return dict(_ACTION_PRIORITY_ACTION)
    return dict(_ACTION_PRIORITY_READ)


def build_candidate_set(
    target_candidates: list[str],
    tools_by_name: dict[str, dict[str, Any]],
    *,
    expansion_seed: list[str] | None = None,
    target_action_priority: dict[str, int] | None = None,
    max_target_candidates: int | None = None,
    max_targets_per_group: int | None = None,
    diversify_target_groups: bool = False,
    max_producers_per_field: int = 3,
    max_hops: int = 1,
    action_priority: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a structured target/producers candidate set.

    ``target_candidates`` is the retrieval/target-selection surface. Producers
    are expanded only from ``expansion_seed`` so XGEN-style adapters can keep
    top-K target search separate from the plan candidate set for the selected
    target. If no seed is provided, the function preserves the legacy behavior
    and expands from every target candidate. ``max_targets_per_group`` is an
    opt-in sibling cap for adapters that want to avoid near-duplicate targets
    crowding a small LLM-visible set. ``max_target_candidates`` and
    ``diversify_target_groups`` are opt-in controls for multi-intent target
    surfaces.
    """

    raw_targets = _dedupe_names(target_candidates)
    ranked_targets = _rank_target_candidates(
        raw_targets,
        tools_by_name=tools_by_name,
        target_action_priority=target_action_priority,
    )
    seed = _dedupe_names(target_candidates if expansion_seed is None else expansion_seed)
    explicit_seed = _dedupe_names(expansion_seed or [])
    targets, suppressed_targets, target_groups = _target_candidates_with_group_cap(
        ranked_targets,
        tools_by_name=tools_by_name,
        max_target_candidates=max_target_candidates,
        max_targets_per_group=max_targets_per_group,
        diversify_target_groups=diversify_target_groups,
        always_keep=set(explicit_seed),
    )
    selected_target_set = set(targets)
    target_equivalence_groups = _enrich_equivalence_groups(
        build_tool_equivalence_groups(raw_targets, tools_by_name),
        selected_targets=selected_target_set,
    )
    candidates = expand_candidates_with_producers(
        seed,
        tools_by_name,
        max_producers_per_field=max_producers_per_field,
        max_hops=max_hops,
        action_priority=action_priority,
    )
    seed_set = set(seed)
    producers = [name for name in candidates if name not in seed_set]
    target_rank_signals = _target_rank_signals(
        raw_targets,
        ranked_targets=ranked_targets,
        selected_targets=targets,
        suppressed_targets=suppressed_targets,
        tools_by_name=tools_by_name,
        target_action_priority=target_action_priority,
    )
    return {
        "raw_target_candidates": raw_targets,
        "ranked_target_candidates": ranked_targets,
        "target_candidates": targets,
        "expansion_seed": seed,
        "producer_candidates": producers,
        "candidates": candidates,
        "target_candidate_count": len(targets),
        "raw_target_candidate_count": len(raw_targets),
        "candidate_count": len(candidates),
        "producer_added_count": len(producers),
        "adaptive_expansion_applied": bool(producers),
        "target_rank_signals": target_rank_signals,
        "target_action_priority": target_action_priority or {},
        "target_rerank_applied": bool(target_action_priority),
        "suppressed_target_candidates": suppressed_targets,
        "suppressed_target_count": len(suppressed_targets),
        "sibling_control_applied": bool(suppressed_targets),
        "target_candidate_groups": target_groups,
        "target_equivalence_groups": target_equivalence_groups,
        "target_equivalence_group_count": len(target_equivalence_groups),
        "max_target_candidates": max_target_candidates,
        "max_targets_per_group": max_targets_per_group,
        "diversify_target_groups": diversify_target_groups,
        "target_diversity_applied": bool(diversify_target_groups and max_target_candidates),
        "max_hops": max(0, max_hops),
        "max_producers_per_field": max(0, max_producers_per_field),
    }


def build_tool_equivalence_groups(
    candidate_names: list[str],
    tools_by_name: dict[str, dict[str, Any]],
    *,
    threshold: float = 0.42,
) -> list[dict[str, Any]]:
    """Return high-confidence near-duplicate/equivalent tool surface groups.

    This helper is intentionally deterministic and evidence-only. It does not
    merge, suppress, or rerank candidates; adapters can use the returned groups
    to explain ambiguity, add selector evidence, or decide whether an
    equivalence-aware UI/model prompt is needed.
    """

    names = _dedupe_names(candidate_names)
    if len(names) < 2:
        return []

    pair_evidence: list[dict[str, Any]] = []
    adjacency: dict[str, set[str]] = {name: set() for name in names}
    for index, left_name in enumerate(names):
        left_tool = tools_by_name.get(left_name) or {}
        for right_name in names[index + 1 :]:
            right_tool = tools_by_name.get(right_name) or {}
            evidence = _surface_equivalence_evidence(
                left_name,
                left_tool,
                right_name,
                right_tool,
                threshold=threshold,
            )
            if not evidence:
                continue
            pair_evidence.append(evidence)
            adjacency[left_name].add(right_name)
            adjacency[right_name].add(left_name)

    seen: set[str] = set()
    groups: list[dict[str, Any]] = []
    order = {name: index for index, name in enumerate(names)}
    for name in names:
        if name in seen or not adjacency[name]:
            continue
        stack = [name]
        members: set[str] = set()
        while stack:
            current = stack.pop()
            if current in members:
                continue
            members.add(current)
            stack.extend(sorted(adjacency[current] - members, key=order.get, reverse=True))
        seen.update(members)
        ordered_members = sorted(members, key=order.get)
        group_pairs = [
            row for row in pair_evidence if row["tool_a"] in members and row["tool_b"] in members
        ]
        max_score = max((float(row["score"]) for row in group_pairs), default=0.0)
        groups.append(
            {
                "key": f"surface_equivalence:{_stable_group_key(ordered_members)}",
                "kind": "surface_equivalence",
                "members": ordered_members,
                "member_count": len(ordered_members),
                "score": round(max_score, 6),
                "confidence": "high" if max_score >= 0.5 else "medium",
                "evidence_sources": ["tool_surface"],
                "pair_evidence": group_pairs,
            }
        )
    return groups


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


def _dedupe_names(names: list[str]) -> list[str]:
    return list(dict.fromkeys(str(name) for name in names if str(name)))


def _query_terms(query: str) -> set[str]:
    text = str(query or "").strip().lower()
    if not text:
        return set()
    terms = {text}
    terms.update(t for t in re.split(r"[\s_\-/.,;:!?()]+", text) if t)
    return terms


def _has_action_term(query_terms: set[str], action_terms: frozenset[str]) -> bool:
    for term in query_terms:
        for action in action_terms:
            if action and action in term:
                return True
    return False


def _rank_target_candidates(
    names: list[str],
    *,
    tools_by_name: dict[str, dict[str, Any]],
    target_action_priority: dict[str, int] | None,
) -> list[str]:
    if not target_action_priority:
        return list(names)
    original_rank = {name: idx for idx, name in enumerate(names)}
    return sorted(
        names,
        key=lambda name: (
            -_target_action_score(
                tools_by_name.get(name) or {},
                target_action_priority=target_action_priority,
            ),
            original_rank[name],
        ),
    )


def _target_rank_signals(
    raw_targets: list[str],
    *,
    ranked_targets: list[str],
    selected_targets: list[str],
    suppressed_targets: list[str],
    tools_by_name: dict[str, dict[str, Any]],
    target_action_priority: dict[str, int] | None,
) -> list[dict[str, Any]]:
    raw_rank = {name: idx + 1 for idx, name in enumerate(raw_targets)}
    reranked_rank = {name: idx + 1 for idx, name in enumerate(ranked_targets)}
    selected = set(selected_targets)
    suppressed = set(suppressed_targets)
    signals: list[dict[str, Any]] = []
    for name in ranked_targets:
        tool = tools_by_name.get(name) or {}
        ai = (tool.get("metadata") or {}).get("ai_metadata") or {}
        action = str(ai.get("canonical_action") or "").strip().lower()
        resource = str(ai.get("primary_resource") or "").strip().lower()
        signals.append(
            {
                "name": name,
                "original_rank": raw_rank.get(name),
                "reranked_rank": reranked_rank.get(name),
                "canonical_action": action,
                "primary_resource": resource,
                "group_key": _target_group_key(name, tool),
                "action_priority": _target_action_score(
                    tool,
                    target_action_priority=target_action_priority,
                ),
                "selected": name in selected,
                "suppressed": name in suppressed,
            }
        )
    return signals


def _target_action_score(
    tool: dict[str, Any],
    *,
    target_action_priority: dict[str, int] | None,
) -> int:
    if not target_action_priority:
        return 0
    ai = (tool.get("metadata") or {}).get("ai_metadata") or {}
    action = str(ai.get("canonical_action") or "").strip().lower()
    return int(target_action_priority.get(action, 0))


def _target_candidates_with_group_cap(
    names: list[str],
    *,
    tools_by_name: dict[str, dict[str, Any]],
    max_target_candidates: int | None,
    max_targets_per_group: int | None,
    diversify_target_groups: bool,
    always_keep: set[str],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    groups = _target_candidate_groups(names, tools_by_name=tools_by_name)

    candidates = list(names)
    if max_targets_per_group is not None:
        cap = max(1, int(max_targets_per_group))
        candidates = _cap_targets_per_group(
            candidates,
            tools_by_name=tools_by_name,
            cap=cap,
            always_keep=always_keep,
        )

    if max_target_candidates is not None:
        limit = max(1, int(max_target_candidates))
        if diversify_target_groups:
            candidates = _diverse_target_candidates(
                candidates,
                tools_by_name=tools_by_name,
                limit=limit,
                always_keep=always_keep,
            )
        else:
            candidates = _limit_targets(candidates, limit=limit, always_keep=always_keep)

    selected_set = set(candidates)
    suppressed = [name for name in names if name not in selected_set]
    enriched_groups: list[dict[str, Any]] = []
    for group in groups:
        members = list(group["members"])
        suppressed_members = [name for name in members if name not in selected_set]
        enriched_groups.append(
            {
                **group,
                "selected": [name for name in members if name in selected_set],
                "suppressed": suppressed_members,
                "suppressed_count": len(suppressed_members),
            }
        )
    return candidates, suppressed, enriched_groups


def _cap_targets_per_group(
    names: list[str],
    *,
    tools_by_name: dict[str, dict[str, Any]],
    cap: int,
    always_keep: set[str],
) -> list[str]:
    selected: list[str] = []
    group_counts: dict[str, int] = {}
    for name in names:
        key = _target_group_key(name, tools_by_name.get(name) or {})
        count = group_counts.get(key, 0)
        if count < cap or name in always_keep:
            selected.append(name)
            group_counts[key] = count + 1
    return selected


def _limit_targets(names: list[str], *, limit: int, always_keep: set[str]) -> list[str]:
    selected = list(names[:limit])
    return _ensure_always_keep(selected, names=names, limit=limit, always_keep=always_keep)


def _diverse_target_candidates(
    names: list[str],
    *,
    tools_by_name: dict[str, dict[str, Any]],
    limit: int,
    always_keep: set[str],
) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for name in names:
        key = _target_group_key(name, tools_by_name.get(name) or {})
        grouped.setdefault(key, []).append(name)

    selected: list[str] = []
    offsets = {key: 0 for key in grouped}
    while len(selected) < limit:
        added = False
        for key, members in grouped.items():
            offset = offsets[key]
            if offset >= len(members):
                continue
            selected.append(members[offset])
            offsets[key] = offset + 1
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
    return _ensure_always_keep(selected, names=names, limit=limit, always_keep=always_keep)


def _ensure_always_keep(
    selected: list[str],
    *,
    names: list[str],
    limit: int,
    always_keep: set[str],
) -> list[str]:
    out = list(selected)
    selected_set = set(out)
    for keep in [name for name in names if name in always_keep and name not in selected_set]:
        if len(out) < limit:
            out.append(keep)
            selected_set.add(keep)
            continue
        replace_idx = next(
            (idx for idx in range(len(out) - 1, -1, -1) if out[idx] not in always_keep),
            None,
        )
        if replace_idx is None:
            out.append(keep)
        else:
            selected_set.discard(out[replace_idx])
            out[replace_idx] = keep
        selected_set.add(keep)
    return out


def _target_candidate_groups(
    names: list[str],
    *,
    tools_by_name: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for name in names:
        key = _target_group_key(name, tools_by_name.get(name) or {})
        grouped.setdefault(key, []).append(name)
    return [
        {
            "key": key,
            "members": members,
            "member_count": len(members),
        }
        for key, members in grouped.items()
    ]


def _target_group_key(name: str, tool: dict[str, Any]) -> str:
    metadata = tool.get("metadata") or {}
    ai = metadata.get("ai_metadata") or {}
    resource = str(ai.get("primary_resource") or "").strip().lower()
    action = str(ai.get("canonical_action") or "").strip().lower()
    if resource and action:
        return f"resource_action:{resource}:{action}"
    if resource:
        return f"resource:{resource}"
    tags = [str(tag).strip().lower() for tag in tool.get("tags") or [] if str(tag).strip()]
    if tags and action:
        return f"tag_action:{tags[0]}:{action}"
    if tags:
        return f"tag:{tags[0]}"
    return f"name:{name}"


def _enrich_equivalence_groups(
    groups: list[dict[str, Any]],
    *,
    selected_targets: set[str],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for group in groups:
        members = list(group.get("members") or [])
        selected = [name for name in members if name in selected_targets]
        suppressed = [name for name in members if name not in selected_targets]
        enriched.append(
            {
                **group,
                "selected": selected,
                "suppressed": suppressed,
                "suppressed_count": len(suppressed),
            }
        )
    return enriched


def _surface_equivalence_evidence(
    left_name: str,
    left_tool: dict[str, Any],
    right_name: str,
    right_tool: dict[str, Any],
    *,
    threshold: float,
) -> dict[str, Any] | None:
    left_terms = _tool_surface_terms(left_name, left_tool)
    right_terms = _tool_surface_terms(right_name, right_tool)
    if not left_terms or not right_terms:
        return None
    shared_terms = left_terms & right_terms
    surface_overlap = len(shared_terms) / len(left_terms | right_terms)
    name_overlap = bool(_identifier_terms(left_name) & _identifier_terms(right_name))
    required_field_gap = abs(len(_required_fields(left_tool)) - len(_required_fields(right_tool)))
    required_field_overlap = _required_field_overlap(left_tool, right_tool)
    score = min(1.0, surface_overlap + (0.1 if name_overlap else 0.0))
    equivalent = required_field_gap <= 2 and (
        surface_overlap >= threshold
        or (surface_overlap >= 0.32 and name_overlap)
        or _domain_surface_equivalent(
            left_terms,
            right_terms,
            shared_terms,
            name_overlap=name_overlap,
            required_field_overlap=required_field_overlap,
        )
    )
    if not equivalent:
        return None
    return {
        "tool_a": left_name,
        "tool_b": right_name,
        "score": round(score, 6),
        "surface_overlap": round(surface_overlap, 6),
        "name_overlap": name_overlap,
        "required_field_gap": required_field_gap,
        "required_field_overlap": round(required_field_overlap, 6),
        "shared_terms": sorted(shared_terms)[:12],
    }


def _tool_surface_terms(name: str, tool: dict[str, Any]) -> set[str]:
    params = tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {}
    properties = params.get("properties") if isinstance(params, dict) else {}
    parts = [name, str(tool.get("name") or ""), str(tool.get("description") or "")]
    if isinstance(properties, dict):
        for property_name, schema in properties.items():
            parts.append(str(property_name))
            if isinstance(schema, dict):
                parts.append(str(schema.get("description") or ""))
    metadata = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
    parts.extend(
        [
            str(ai.get("primary_resource") or ""),
            str(ai.get("canonical_action") or ""),
            str(ai.get("one_line_summary") or ""),
            str(ai.get("when_to_use") or ""),
        ]
    )
    return _surface_terms(" ".join(parts))


def _required_fields(tool: dict[str, Any]) -> list[str]:
    params = tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {}
    required = params.get("required") if isinstance(params, dict) else []
    if not isinstance(required, list):
        return []
    return [str(name) for name in required]


def _required_field_overlap(left_tool: dict[str, Any], right_tool: dict[str, Any]) -> float:
    left = set(_required_fields(left_tool))
    right = set(_required_fields(right_tool))
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _domain_surface_equivalent(
    left_terms: set[str],
    right_terms: set[str],
    shared_terms: set[str],
    *,
    name_overlap: bool,
    required_field_overlap: float,
) -> bool:
    union = left_terms | right_terms
    if {"currency", "convert"}.issubset(shared_terms) and required_field_overlap >= 0.67:
        return True
    if {"area", "curve", "under"}.issubset(shared_terms) and union & {
        "integral",
        "integrate",
        "integration",
    }:
        return True
    if (
        (left_terms & {"integral", "integrate", "integration"})
        and {"area", "curve", "under"} <= right_terms
        and shared_terms & {"calculate", "function", "interval"}
    ) or (
        (right_terms & {"integral", "integrate", "integration"})
        and {"area", "curve", "under"} <= left_terms
        and shared_terms & {"calculate", "function", "interval"}
    ):
        return True
    if (
        "fibonacci" in shared_terms
        and name_overlap
        and ({"sequence", "series", "serie"} & left_terms)
        and ({"sequence", "series", "serie"} & right_terms)
    ):
        return True
    if "common" in shared_terms and union & {"gcd", "divisor"} and union & {"hcf", "factor"}:
        return True
    return False


def _surface_terms(text: str) -> set[str]:
    return {
        term for term in _identifier_terms(text) if len(term) > 2 and term not in _SURFACE_STOPWORDS
    }


def _identifier_terms(text: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    terms = {term for term in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if term}
    singular_terms = {
        term[:-1]
        for term in terms
        if len(term) > 3 and term.endswith("s") and not term.endswith("ss")
    }
    return terms | singular_terms


def _stable_group_key(names: list[str]) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "_", "__".join(names))[:120]


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


__all__ = [
    "build_candidate_set",
    "build_tool_equivalence_groups",
    "expand_candidates_with_producers",
    "target_action_priority_for_query",
]
