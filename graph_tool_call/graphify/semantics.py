"""Deterministic OpenAPI semantic metadata helpers.

These helpers turn the stable facts already extracted from OpenAPI into
product-neutral semantic labels. They do not call an LLM and they do not know
about XGEN-specific tables, users, cookies, or execution state.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify.edges import (
    EVIDENCE_API_CONTRACT,
    EVIDENCE_MANUAL,
    EVIDENCE_OPENAPI_LINK,
    EVIDENCE_PROVEN,
    EVIDENCE_RUN,
    EVIDENCE_STRUCTURAL,
)

ACTION_TAXONOMY = ("search", "read", "create", "update", "delete", "action", "unknown")

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")
_VERSION_RE = re.compile(r"^v\d+(?:[._-]?\d+)?$", re.IGNORECASE)

_GENERIC_PATH_SEGMENTS = {
    "api",
    "apis",
    "bo",
    "fo",
    "admin",
    "internal",
    "external",
    "public",
    "private",
    "service",
    "services",
    "controller",
    "controllers",
    "endpoint",
    "operation",
    "tool",
}
_OPERATION_SUFFIX_SEGMENTS = {
    "api",
    "apis",
    "proc",
    "process",
    "mgmt",
    "management",
    "common",
    "commonapi",
    "controller",
    "service",
}
_OPERATION_JOINERS = {"by", "with", "for", "from", "to", "and", "or", "of"}

_ACTION_KEYWORDS: dict[str, set[str]] = {
    "search": {
        "list",
        "lists",
        "search",
        "find",
        "query",
        "queries",
        "lookup",
        "filter",
        "browse",
        "count",
        "목록",
        "리스트",
        "검색",
        "조회목록",
        "조건조회",
    },
    "read": {
        "get",
        "read",
        "fetch",
        "detail",
        "details",
        "info",
        "view",
        "show",
        "조회",
        "상세",
        "정보",
        "확인",
        "보기",
    },
    "create": {
        "create",
        "add",
        "insert",
        "register",
        "new",
        "upload",
        "import",
        "등록",
        "생성",
        "추가",
        "업로드",
        "신규",
    },
    "update": {
        "update",
        "modify",
        "edit",
        "save",
        "patch",
        "set",
        "change",
        "merge",
        "수정",
        "변경",
        "저장",
        "갱신",
        "설정",
        "반영",
    },
    "delete": {
        "delete",
        "remove",
        "drop",
        "erase",
        "삭제",
        "제거",
    },
    "action": {
        "cancel",
        "approve",
        "reject",
        "accept",
        "withdraw",
        "withdrawal",
        "refund",
        "return",
        "exchange",
        "issue",
        "process",
        "execute",
        "run",
        "apply",
        "confirm",
        "complete",
        "send",
        "취소",
        "승인",
        "반려",
        "거절",
        "철회",
        "환불",
        "교환",
        "반품",
        "처리",
        "발행",
        "확정",
        "완료",
        "전송",
        "적용",
    },
}

_METHOD_ACTION = {
    "get": "read",
    "post": "action",
    "put": "update",
    "patch": "update",
    "delete": "delete",
}


def derive_openapi_tool_semantics(
    tool: ToolSchema,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive deterministic semantic metadata for one OpenAPI tool."""

    opts = dict(options or {})
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
    ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
    contract = (
        metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
    )

    method = str(metadata.get("method") or openapi.get("method") or "").strip().lower()
    path = str(metadata.get("path") or openapi.get("path") or "").strip()
    operation_id = str(openapi.get("operation_id") or tool.name or "").strip()
    summary = str(openapi.get("summary") or tool.description or "").strip()
    description = str(openapi.get("description") or "").strip()

    action_aliases = _normalized_alias_map(opts.get("action_aliases"))
    resource_aliases = _normalized_alias_map(opts.get("resource_aliases"))
    module_aliases = _normalized_alias_map(opts.get("module_aliases"))

    path_segments = _semantic_path_segments(path)
    operation_words = _split_words(operation_id)
    text_blob = " ".join([operation_id, summary, description, path]).strip()

    canonical_action, action_evidence = _derive_action(
        existing=ai.get("canonical_action"),
        method=method,
        operation_words=operation_words,
        text_blob=text_blob,
        aliases=action_aliases,
    )
    primary_resource, resource_evidence = _derive_resource(
        existing=ai.get("primary_resource"),
        tags=tool.tags,
        path_segments=path_segments,
        operation_words=operation_words,
        contract=contract,
        aliases=resource_aliases,
    )
    path_module, module_evidence = _derive_path_module(path_segments, module_aliases)
    operation_group = _derive_operation_group(tool.tags, path_module, primary_resource)

    confidence, confidence_score = _semantic_confidence(
        action=canonical_action,
        resource=primary_resource,
        module=path_module,
        evidence=[action_evidence, resource_evidence, module_evidence],
    )
    one_line_summary = _one_line_summary(
        existing=ai.get("one_line_summary"),
        action=canonical_action,
        resource=primary_resource,
        summary=summary,
        operation_id=operation_id,
        method=method,
        path=path,
    )
    when_to_use = _when_to_use(
        existing=ai.get("when_to_use"),
        action=canonical_action,
        resource=primary_resource,
        summary=summary,
        method=method,
        path=path,
    )
    evidence = [action_evidence, resource_evidence, module_evidence]
    semantic_sources = sorted(
        {
            str(row.get("source"))
            for row in evidence
            if isinstance(row, dict) and row.get("source") and row.get("source") != "unknown"
        }
    )

    return {
        "ai_metadata": {
            "canonical_action": canonical_action,
            "primary_resource": primary_resource,
            "one_line_summary": one_line_summary,
            "when_to_use": when_to_use,
            "semantic_confidence": confidence,
            "semantic_confidence_score": confidence_score,
            "semantic_evidence": evidence,
        },
        "openapi": {
            "path_module": path_module,
            "operation_group": operation_group,
            "semantic_sources": semantic_sources,
        },
    }


def annotate_openapi_tool_semantics(
    tools: Mapping[str, ToolSchema] | Sequence[ToolSchema],
    *,
    options: Mapping[str, Any] | None = None,
    overwrite: bool = False,
) -> list[ToolSchema]:
    """Annotate OpenAPI tools with deterministic semantic metadata.

    Existing human/LLM ``ai_metadata`` is preserved by default. Pass
    ``overwrite=True`` only for explicit rebuilds where deterministic metadata
    should replace prior values.
    """

    tool_list = list(tools.values()) if isinstance(tools, Mapping) else list(tools)
    for tool in tool_list:
        derived = derive_openapi_tool_semantics(tool, options=options)
        metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
        if tool.metadata is not metadata:
            tool.metadata = metadata

        ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
        ai = dict(ai)
        for key, value in derived["ai_metadata"].items():
            if overwrite or _missing_semantic_value(ai.get(key)):
                ai[key] = value
        metadata["ai_metadata"] = ai

        openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        openapi = dict(openapi)
        for key, value in derived["openapi"].items():
            if overwrite or _missing_semantic_value(openapi.get(key)):
                openapi[key] = value
        metadata["openapi"] = openapi
        tool.metadata = metadata
    return tool_list


def summarize_openapi_semantics(
    tools: Mapping[str, ToolSchema] | Sequence[ToolSchema],
    *,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize semantic coverage without mutating the tools."""

    tool_list = list(tools.values()) if isinstance(tools, Mapping) else list(tools)
    action_counts: Counter[str] = Counter()
    resource_counts: Counter[str] = Counter()
    module_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    unknown_samples: list[dict[str, Any]] = []

    for tool in tool_list:
        metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
        openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
        derived = derive_openapi_tool_semantics(tool, options=options)
        derived_ai = derived["ai_metadata"]
        derived_openapi = derived["openapi"]

        action = _normalize_action(ai.get("canonical_action")) or str(
            derived_ai.get("canonical_action") or "unknown"
        )
        resource = _canonical_label(
            ai.get("primary_resource") or derived_ai.get("primary_resource")
        )
        path_module = _canonical_label(
            openapi.get("path_module") or derived_openapi.get("path_module")
        )
        confidence = str(
            ai.get("semantic_confidence") or derived_ai.get("semantic_confidence") or "low"
        )

        if action not in ACTION_TAXONOMY:
            action = "unknown"
        action_counts[action] += 1
        resource_counts[resource or "unassigned"] += 1
        module_counts[path_module or "unassigned"] += 1
        confidence_counts[confidence] += 1

        missing = []
        if action == "unknown":
            missing.append("canonical_action")
        if not resource:
            missing.append("primary_resource")
        if not path_module:
            missing.append("path_module")
        if missing and len(unknown_samples) < 20:
            unknown_samples.append(
                {
                    "name": tool.name,
                    "missing": missing,
                    "method": str(metadata.get("method") or "").upper(),
                    "path": str(metadata.get("path") or ""),
                    "operation_id": str(openapi.get("operation_id") or tool.name),
                }
            )

    total = len(tool_list)
    action_known = total - action_counts.get("unknown", 0)
    resource_assigned = total - resource_counts.get("unassigned", 0)
    module_assigned = total - module_counts.get("unassigned", 0)
    top_modules = [
        {"module": name, "count": count, "rate": _rate(count, total)}
        for name, count in module_counts.most_common(20)
    ]
    return {
        "tool_count": total,
        "canonical_action_known_count": action_known,
        "canonical_action_known_rate": _rate(action_known, total),
        "primary_resource_assigned_count": resource_assigned,
        "primary_resource_assigned_rate": _rate(resource_assigned, total),
        "path_module_assigned_count": module_assigned,
        "path_module_assigned_rate": _rate(module_assigned, total),
        "action_counts": dict(sorted(action_counts.items())),
        "resource_counts": dict(resource_counts.most_common(50)),
        "module_counts": dict(module_counts.most_common(50)),
        "top_modules": top_modules,
        "semantic_confidence_counts": dict(sorted(confidence_counts.items())),
        "unknown_samples": unknown_samples,
    }


def summarize_edge_quality(graph: GraphEngine | None) -> dict[str, Any]:
    """Summarize edge provenance quality for large OpenAPI collections."""

    counters: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    visual_candidate_count = 0
    if graph is None:
        return _edge_quality_payload(counters, relation_counts, visual_candidate_count)

    for _source, _target, attrs in graph.edges():
        counters["total"] += 1
        relation = _label(attrs.get("relation")).lower()
        relation_counts[relation or "unknown"] += 1
        evidence_sources = {
            str(source) for source in (attrs.get("evidence_sources") or []) if str(source).strip()
        }
        evidence_text = str(attrs.get("evidence") or "").lower()
        kind = str(attrs.get("kind") or "").strip().lower()
        confidence = str(attrs.get("confidence") or "").strip().upper()
        conf_score = _float(attrs.get("conf_score"))

        if kind == "data" or attrs.get("data_flow") or relation in {"requires", "produces_for"}:
            counters["data_flow"] += 1
        if EVIDENCE_STRUCTURAL in evidence_sources or _looks_structural_edge(evidence_text):
            counters["structural"] += 1
        if "name_based" in evidence_sources or "name/rpc" in evidence_text:
            counters["name_based"] += 1
        if EVIDENCE_MANUAL in evidence_sources or attrs.get("is_manual"):
            counters["manual"] += 1
        if EVIDENCE_RUN in evidence_sources or EVIDENCE_PROVEN in evidence_sources:
            counters["trace"] += 1
        if _has_strong_deterministic_evidence(evidence_sources, confidence, conf_score):
            counters["strong_deterministic_evidence"] += 1
        if _is_visual_edge_candidate(evidence_sources, relation, confidence, conf_score, attrs):
            visual_candidate_count += 1

    return _edge_quality_payload(counters, relation_counts, visual_candidate_count)


def _derive_action(
    *,
    existing: Any,
    method: str,
    operation_words: list[str],
    text_blob: str,
    aliases: Mapping[str, str],
) -> tuple[str, dict[str, Any]]:
    action = _normalize_action(existing, aliases=aliases)
    if action and action != "unknown":
        return action, _evidence("ai_metadata.canonical_action", action, "existing", 1.0)

    for word in operation_words:
        action = _action_from_word(word, aliases=aliases)
        if action:
            if action == "read" and _has_search_signal(operation_words, text_blob):
                action = "search"
            return action, _evidence("operation_id", word, "operation_id_verb", 0.9)

    action = _action_from_text(text_blob, aliases=aliases)
    if action:
        return action, _evidence("summary_description", text_blob[:160], "summary_verb", 0.78)

    fallback = _METHOD_ACTION.get(method, "unknown")
    confidence = 0.55 if fallback != "unknown" else 0.0
    return fallback, _evidence("method", method, "http_method_fallback", confidence)


def _derive_resource(
    *,
    existing: Any,
    tags: Sequence[str],
    path_segments: list[str],
    operation_words: list[str],
    contract: Mapping[str, Any],
    aliases: Mapping[str, str],
) -> tuple[str, dict[str, Any]]:
    current = _canonical_label(existing)
    if current and current != "unassigned":
        current = _apply_alias(current, aliases)
        return current, _evidence("ai_metadata.primary_resource", current, "existing", 1.0)

    for tag in tags:
        candidate = _resource_candidate(tag)
        if candidate:
            candidate = _apply_alias(candidate, aliases)
            return candidate, _evidence("tag", tag, "tag", 0.9)

    for segment in path_segments:
        candidate = _resource_candidate(segment)
        if candidate and not _looks_like_operation_segment(candidate):
            candidate = _apply_alias(candidate, aliases)
            return candidate, _evidence("path", segment, "stable_path_segment", 0.84)

    noun = _operation_resource_noun(operation_words)
    if noun:
        noun = _apply_alias(noun, aliases)
        return noun, _evidence("operation_id", noun, "operation_id_noun", 0.72)

    contract_resource = _resource_from_contract(contract)
    if contract_resource:
        contract_resource = _apply_alias(contract_resource, aliases)
        return contract_resource, _evidence("api_contract", contract_resource, "schema_field", 0.62)

    return "", _evidence("resource", "", "unknown", 0.0)


def _derive_path_module(
    path_segments: list[str],
    aliases: Mapping[str, str],
) -> tuple[str, dict[str, Any]]:
    if not path_segments:
        return "", _evidence("path_module", "", "unknown", 0.0)
    module_segments = [
        _module_candidate(segment)
        for segment in path_segments[:2]
        if _module_candidate(segment) and not _looks_like_operation_segment(segment)
    ]
    if not module_segments:
        module_segments = [_resource_candidate(path_segments[0])]
    deduped: list[str] = []
    for segment in module_segments:
        if segment and segment not in deduped:
            deduped.append(segment)
    module = "/".join(deduped)
    module = _apply_alias(module, aliases)
    return module, _evidence("path", "/".join(path_segments[:2]), "path_module", 0.9)


def _derive_operation_group(
    tags: Sequence[str],
    path_module: str,
    primary_resource: str,
) -> str:
    for tag in tags:
        candidate = _resource_candidate(tag)
        if candidate:
            return candidate
    return path_module or primary_resource or ""


def _semantic_confidence(
    *,
    action: str,
    resource: str,
    module: str,
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[str, float]:
    scores = [_float(row.get("confidence")) for row in evidence]
    known = int(action != "unknown") + int(bool(resource)) + int(bool(module))
    score = round((sum(scores) / max(len(scores), 1)) * (known / 3), 4)
    if known == 3 and score >= 0.75:
        return "high", score
    if known >= 2 and score >= 0.45:
        return "medium", score
    return "low", score


def _one_line_summary(
    *,
    existing: Any,
    action: str,
    resource: str,
    summary: str,
    operation_id: str,
    method: str,
    path: str,
) -> str:
    current = str(existing or "").strip()
    if current:
        return current
    if summary:
        return summary[:240]
    parts = []
    if action and action != "unknown":
        parts.append(action)
    if resource:
        parts.append(resource)
    if parts:
        return " ".join(parts)
    return " ".join(part for part in [method.upper(), path or operation_id] if part).strip()


def _when_to_use(
    *,
    existing: Any,
    action: str,
    resource: str,
    summary: str,
    method: str,
    path: str,
) -> str:
    current = str(existing or "").strip()
    if current:
        return current
    target = resource or "the API resource"
    if action == "search":
        return f"Use when finding or listing {target} records."
    if action == "read":
        return f"Use when reading one {target} record or detail view."
    if action == "create":
        return f"Use when creating {target} records."
    if action == "update":
        return f"Use when updating {target} records."
    if action == "delete":
        return f"Use when deleting {target} records."
    if summary:
        return f"Use for: {summary[:180]}"
    return " ".join(part for part in [method.upper(), path] if part).strip()


def _semantic_path_segments(path: str) -> list[str]:
    segments: list[str] = []
    for raw in path.split("/"):
        segment = raw.strip()
        if not segment or segment.startswith("{") or segment.endswith("}"):
            continue
        canonical = _canonical_label(segment)
        if (
            not canonical
            or canonical in _GENERIC_PATH_SEGMENTS
            or _VERSION_RE.match(canonical)
            or _looks_like_operation_segment(canonical)
        ):
            continue
        segments.append(segment)
    return segments


def _looks_like_operation_segment(value: str) -> bool:
    words = _split_words(value)
    if not words:
        return False
    first = words[0]
    if _action_from_word(first, aliases={}):
        return True
    return _canonical_label(value) in _OPERATION_SUFFIX_SEGMENTS


def _resource_candidate(value: Any) -> str:
    words = _split_words(str(value or ""))
    selected = [
        word
        for word in words
        if word
        and word not in _GENERIC_PATH_SEGMENTS
        and word not in _OPERATION_SUFFIX_SEGMENTS
        and word not in _OPERATION_JOINERS
        and not _VERSION_RE.match(word)
        and not _action_from_word(word, aliases={})
    ]
    if not selected:
        return ""
    return "_".join(selected[:3])


def _module_candidate(value: Any) -> str:
    words = _split_words(str(value or ""))
    selected = [
        word
        for word in words
        if word
        and word not in _GENERIC_PATH_SEGMENTS
        and word not in {"api", "apis", "proc", "process", "controller", "service"}
        and not _VERSION_RE.match(word)
    ]
    if not selected:
        return ""
    return "_".join(selected[:4])


def _operation_resource_noun(words: list[str]) -> str:
    selected: list[str] = []
    for word in words:
        if (
            not word
            or _action_from_word(word, aliases={})
            or word in _OPERATION_JOINERS
            or _looks_generic_resource_word(word)
        ):
            continue
        if word in {"list", "info", "detail", "details", "query", "search"}:
            continue
        selected.append(word)
        if len(selected) >= 3:
            break
    return "_".join(selected)


def _looks_generic_resource_word(word: str) -> bool:
    return word in _GENERIC_PATH_SEGMENTS or bool(re.match(r"^(tool|operation|endpoint)\d*$", word))


def _resource_from_contract(contract: Mapping[str, Any]) -> str:
    rows = []
    for key in ("produces", "consumes"):
        values = contract.get(key) if isinstance(contract, Mapping) else []
        if isinstance(values, list):
            rows.extend(row for row in values if isinstance(row, dict))
    for row in rows:
        semantic = _canonical_label(row.get("semantic_tag"))
        if semantic and semantic.endswith("_id"):
            return semantic[: -len("_id")]
        field = _canonical_label(row.get("field_name"))
        if field.endswith("_no") or field.endswith("_id"):
            return field.rsplit("_", 1)[0]
    return ""


def _action_from_text(text: str, *, aliases: Mapping[str, str]) -> str:
    words = _split_words(text)
    for preferred in ("create", "update", "delete", "action"):
        for word in words:
            action = _action_from_word(word, aliases=aliases)
            if action == preferred:
                return action
    if _has_search_signal(words, text):
        return "search"
    for word in words:
        action = _action_from_word(word, aliases=aliases)
        if action:
            return action
    lowered = text.lower()
    for action, keywords in _ACTION_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords if len(keyword) > 1):
            return action
    return ""


def _action_from_word(word: str, *, aliases: Mapping[str, str]) -> str:
    canonical = _canonical_label(word)
    if not canonical:
        return ""
    if canonical in aliases:
        return _normalize_action(aliases[canonical]) or ""
    for action, keywords in _ACTION_KEYWORDS.items():
        if canonical in keywords:
            return action
    return ""


def _has_search_signal(words: Sequence[str], text: str) -> bool:
    word_set = set(words)
    if word_set & _ACTION_KEYWORDS["search"]:
        return True
    lowered = text.lower()
    return any(keyword in lowered for keyword in ("목록", "리스트", "검색", "list", "query"))


def _normalize_action(value: Any, *, aliases: Mapping[str, str] | None = None) -> str:
    key = _canonical_label(value)
    if not key:
        return ""
    alias_value = (aliases or {}).get(key, key)
    if alias_value in {"lookup", "list", "find", "query"}:
        return "search"
    if alias_value in {"get", "fetch", "detail"}:
        return "read"
    if alias_value in ACTION_TAXONOMY:
        return alias_value
    for action, keywords in _ACTION_KEYWORDS.items():
        if alias_value in keywords:
            return action
    return "unknown" if key == "unknown" else ""


def _split_words(value: str) -> list[str]:
    expanded = _CAMEL_RE.sub(" ", str(value or ""))
    words: list[str] = []
    for token in _TOKEN_RE.findall(expanded.replace("_", " ").replace("-", " ")):
        canonical = _canonical_label(token)
        if canonical:
            words.append(canonical)
    return words


def _canonical_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _CAMEL_RE.sub("_", text)
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_").lower()
    return text


def _normalized_alias_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    aliases: dict[str, str] = {}
    for key, raw in value.items():
        canonical_key = _canonical_label(key)
        if isinstance(raw, (list, tuple, set)):
            if canonical_key:
                aliases[canonical_key] = canonical_key
            for item in raw:
                item_key = _canonical_label(item)
                if item_key:
                    aliases[item_key] = canonical_key
        else:
            raw_key = _canonical_label(raw)
            if canonical_key and raw_key:
                aliases[canonical_key] = raw_key
    return aliases


def _apply_alias(value: str, aliases: Mapping[str, str]) -> str:
    return aliases.get(_canonical_label(value), value)


def _missing_semantic_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in {"unknown", "unassigned"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _evidence(field: str, value: Any, source: str, confidence: float) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "source": source,
        "confidence": round(float(confidence), 4),
    }


def _edge_quality_payload(
    counters: Counter[str],
    relation_counts: Counter[str],
    visual_candidate_count: int,
) -> dict[str, Any]:
    total = counters.get("total", 0)
    return {
        "total": total,
        "data_flow": counters.get("data_flow", 0),
        "structural": counters.get("structural", 0),
        "name_based": counters.get("name_based", 0),
        "manual": counters.get("manual", 0),
        "trace": counters.get("trace", 0),
        "strong_deterministic_evidence": counters.get("strong_deterministic_evidence", 0),
        "visual_edge_candidate_count": visual_candidate_count,
        "strong_deterministic_evidence_rate": _rate(
            counters.get("strong_deterministic_evidence", 0), total
        ),
        "visual_edge_candidate_rate": _rate(visual_candidate_count, total),
        "relation_counts": dict(sorted(relation_counts.items())),
    }


def _looks_structural_edge(evidence_text: str) -> bool:
    return any(
        marker in evidence_text
        for marker in ("path hierarchy", "crud", "shared schema", "$ref", "structural")
    )


def _has_strong_deterministic_evidence(
    evidence_sources: set[str],
    confidence: str,
    conf_score: float,
) -> bool:
    if evidence_sources & {EVIDENCE_API_CONTRACT, EVIDENCE_OPENAPI_LINK, EVIDENCE_STRUCTURAL}:
        return True
    return confidence == "EXTRACTED" and conf_score >= 0.85


def _is_visual_edge_candidate(
    evidence_sources: set[str],
    relation: str,
    confidence: str,
    conf_score: float,
    attrs: Mapping[str, Any],
) -> bool:
    if evidence_sources & {EVIDENCE_API_CONTRACT, EVIDENCE_OPENAPI_LINK, EVIDENCE_MANUAL}:
        return True
    if evidence_sources & {EVIDENCE_RUN, EVIDENCE_PROVEN}:
        return True
    if attrs.get("data_flow") and confidence in {"EXTRACTED", "INFERRED"}:
        return True
    return relation in {"requires", "precedes"} and confidence == "EXTRACTED" and conf_score >= 0.9


def _label(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "")


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _rate(numerator: int, denominator: int) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


__all__ = [
    "ACTION_TAXONOMY",
    "annotate_openapi_tool_semantics",
    "derive_openapi_tool_semantics",
    "summarize_edge_quality",
    "summarize_openapi_semantics",
]
