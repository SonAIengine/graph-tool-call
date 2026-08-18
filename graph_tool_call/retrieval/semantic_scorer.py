"""Low-weight structured semantic scoring for retrieval candidates."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from graph_tool_call.core.tool import ToolSchema

_SHAPE_TERMS = {
    "single": {
        "single",
        "detail",
        "details",
        "info",
        "information",
        "상세",
        "정보",
        "단건",
    },
    "list": {
        "list",
        "lists",
        "search",
        "find",
        "query",
        "browse",
        "filter",
        "filtered",
        "matching",
        "condition",
        "conditions",
        "목록",
        "리스트",
        "검색",
        "조건",
    },
    "count": {"count", "total", "cnt", "건수", "개수", "카운트"},
    "mutation": {
        "create",
        "update",
        "delete",
        "action",
        "등록",
        "수정",
        "삭제",
        "처리",
    },
}
_STRONG_SINGLE_SHAPE_TERMS = {"single", "detail", "details", "상세", "단건"}
_WEAK_SINGLE_SHAPE_TERMS = _SHAPE_TERMS["single"] - _STRONG_SINGLE_SHAPE_TERMS
_ACTION_TERMS = {
    "search": {"search", "find", "query", "list", "검색", "목록"},
    "read": {"read", "get", "detail", "view", "show", "조회", "상세", "확인"},
    "create": {"create", "add", "register", "등록", "생성", "추가"},
    "update": {"update", "edit", "change", "save", "수정", "저장", "변경"},
    "delete": {"delete", "remove", "cancel", "삭제", "제거", "취소"},
    "action": {"action", "process", "run", "approve", "처리", "실행", "승인"},
}
_SEMANTIC_GENERIC_TERMS = {
    "api",
    "data",
    "info",
    "information",
    "manage",
    "management",
    "record",
    "records",
    "tool",
    "use",
    "관리",
    "도구",
    "정보",
}


def semantic_match_evidence(tool: ToolSchema, query: str) -> dict[str, Any]:
    """Return stable action/resource/shape/contract match evidence."""
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
    ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
    query_terms = semantic_terms(query)

    action = str(ai.get("canonical_action") or "").strip().lower()
    resource = str(ai.get("primary_resource") or "").strip().lower()
    result_shape = str(ai.get("result_shape") or "").strip().lower()
    module = str(openapi.get("path_module") or "").strip().lower()
    contract_rows = _contract_rows(metadata)
    primary_summary = str(
        ai.get("one_line_summary")
        or openapi.get("summary")
        or (tool.description.splitlines()[0] if tool.description else "")
    )
    summary_values = [
        ai.get("one_line_summary"),
        openapi.get("summary"),
        ai.get("when_to_use"),
        tool.description.splitlines()[0] if tool.description else "",
    ]

    action_terms = semantic_terms(action) | action_alias_terms(action)
    resource_terms = semantic_terms(resource.replace("/", " "))
    module_terms = semantic_terms(module.replace("/", " "))
    shape_terms = result_shape_terms(result_shape)
    contract_terms = {
        term
        for row in contract_rows
        for value in (
            row.get("field_name"),
            row.get("semantic_tag"),
            row.get("description"),
            row.get("json_path"),
        )
        for term in semantic_terms(str(value or ""))
    }
    summary_terms = {term for value in summary_values for term in semantic_terms(str(value or ""))}
    summary_matches = _matching_terms(query_terms, summary_terms)
    generic_terms = _SEMANTIC_GENERIC_TERMS | {
        term for values in (*_ACTION_TERMS.values(), *_SHAPE_TERMS.values()) for term in values
    }
    query_content_terms = query_terms - generic_terms
    primary_summary_terms = semantic_terms(primary_summary) - generic_terms
    primary_summary_matches = _matching_terms(query_content_terms, primary_summary_terms)
    summary_specificity = len(primary_summary_matches) / max(len(primary_summary_terms), 1)

    return {
        "canonical_action": action,
        "primary_resource": resource,
        "result_shape": result_shape,
        "path_module": module,
        "query_action": infer_query_action(query),
        "query_result_shape": infer_query_result_shape(query),
        "action_match": _terms_overlap(query_terms, action_terms),
        "resource_match": _terms_overlap(query_terms, resource_terms),
        "module_match": _terms_overlap(query_terms, module_terms),
        "shape_match": _terms_overlap(query_terms, shape_terms),
        "contract_match": _terms_overlap(query_terms, contract_terms),
        "summary_match": bool(summary_matches),
        "summary_match_count": len(summary_matches),
        "summary_matched_terms": sorted(summary_matches),
        "summary_specificity": round(summary_specificity, 6),
        "matched_terms": sorted(
            query_terms
            & (action_terms | resource_terms | module_terms | shape_terms | contract_terms)
        ),
    }


def semantic_rank_multiplier(tool: ToolSchema, query: str) -> tuple[float, dict[str, Any]]:
    """Return a conservative multiplier derived from generic metadata.

    Shape and action signals affect ranking only when the query expresses an
    unambiguous intent. Resource, module, and contract overlap are small tie
    breakers; lexical and embedding channels remain the primary rankers.
    """
    evidence = semantic_match_evidence(tool, query)
    if not _has_structured_semantics(evidence):
        evidence["rank_multiplier"] = 1.0
        return 1.0, evidence

    query_shape = str(evidence["query_result_shape"] or "")
    query_action = str(evidence["query_action"] or "")
    tool_shape = str(evidence["result_shape"] or "")
    tool_action = str(evidence["canonical_action"] or "")
    multiplier = 1.0

    if query_shape and tool_shape:
        multiplier += 0.18 if query_shape == tool_shape else -0.04
    if query_action and tool_action:
        if query_action == tool_action:
            multiplier += 0.08
        elif {query_action, tool_action} <= {"read", "search"}:
            multiplier += 0.03
    if evidence["resource_match"]:
        multiplier += 0.05
    if evidence["module_match"]:
        multiplier += 0.03
    if evidence["contract_match"]:
        multiplier += 0.04
    multiplier += 0.30 * float(evidence["summary_specificity"])

    multiplier = round(min(1.60, max(0.90, multiplier)), 6)
    evidence["rank_multiplier"] = multiplier
    return multiplier, evidence


def semantic_channel_score(tool: ToolSchema, query: str) -> float:
    """Return a normalized structured-semantic retrieval score.

    This is an independent, low-weight channel for metadata-rich catalogs. It
    complements BM25 when long descriptions swamp concise action/resource/shape
    evidence, while returning zero for tools without structured semantics.
    """
    evidence = semantic_match_evidence(tool, query)
    if not _has_structured_semantics(evidence):
        return 0.0

    query_shape = str(evidence["query_result_shape"] or "")
    query_action = str(evidence["query_action"] or "")
    tool_shape = str(evidence["result_shape"] or "")
    tool_action = str(evidence["canonical_action"] or "")
    score = 0.0
    if query_shape and tool_shape:
        score += 0.35 if query_shape == tool_shape else 0.0
    if query_action and tool_action:
        if query_action == tool_action:
            score += 0.20
        elif {query_action, tool_action} <= {"read", "search"}:
            score += 0.10
    score += 0.25 * float(evidence["summary_specificity"])
    if evidence["resource_match"]:
        score += 0.10
    if evidence["module_match"]:
        score += 0.05
    if evidence["contract_match"]:
        score += 0.05
    return round(min(1.0, score), 6)


def compute_semantic_scores(query: str, tools: dict[str, ToolSchema]) -> dict[str, float]:
    """Score a catalog with deterministic structured semantic evidence."""
    scores: dict[str, float] = {}
    for name, tool in tools.items():
        score = semantic_channel_score(tool, query)
        if score > 0:
            scores[name] = score
    return scores


def infer_query_result_shape(query: str) -> str:
    normalized = _normalized_text(query)
    if _contains_any(normalized, _SHAPE_TERMS["count"]):
        return "count"
    # Generic nouns such as "information" describe the resource, not the
    # cardinality. Explicit list/search language must win when both appear.
    if _contains_any(normalized, _SHAPE_TERMS["list"]):
        return "list"
    if _contains_any(normalized, _STRONG_SINGLE_SHAPE_TERMS):
        return "single"
    if _contains_any(normalized, _SHAPE_TERMS["mutation"]):
        return "mutation"
    if _contains_any(normalized, _WEAK_SINGLE_SHAPE_TERMS):
        return "single"
    return ""


def infer_query_action(query: str) -> str:
    normalized = _normalized_text(query)
    shape = infer_query_result_shape(query)
    if shape == "list":
        return "search"
    if shape == "single":
        return "read"
    for action in ("delete", "create", "update", "action", "search", "read"):
        if _contains_any(normalized, _ACTION_TERMS[action]):
            return action
    return ""


def semantic_terms(value: str) -> set[str]:
    normalized = _normalized_text(value)
    terms: set[str] = set()
    for term in re.split(r"[\s_\-/.,;:!?()[\]{}$#]+", normalized):
        if len(term) <= 1:
            continue
        terms.add(term)
        stripped = _strip_korean_suffix(term)
        if stripped != term:
            terms.add(stripped)
    return terms


def action_alias_terms(action: str) -> set[str]:
    return set(_ACTION_TERMS.get(str(action or "").lower(), set()))


def result_shape_terms(shape: str) -> set[str]:
    return set(_SHAPE_TERMS.get(str(shape or "").lower(), set()))


def _contract_rows(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        row
        for key in ("produces", "consumes")
        for row in (metadata.get(key) or [])
        if isinstance(row, dict)
    ]
    if rows:
        return rows
    contract = (
        metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
    )
    return [
        row
        for key in ("produces", "consumes")
        for row in (contract.get(key) or [])
        if isinstance(row, dict)
    ]


def _has_structured_semantics(evidence: dict[str, Any]) -> bool:
    return any(
        evidence.get(key)
        for key in ("canonical_action", "primary_resource", "result_shape", "path_module")
    )


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    return normalized.lower()


def _contains_any(normalized: str, terms: set[str]) -> bool:
    for term in terms:
        if re.search(r"[a-z]", term):
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized):
                return True
        elif term in normalized:
            return True
    return False


def _strip_korean_suffix(term: str) -> str:
    if not re.fullmatch(r"[가-힣0-9]+", term) or len(term) < 3:
        return term
    for suffix in (
        "해주세요",
        "해줘",
        "합니다",
        "하세요",
        "에서",
        "으로",
        "에게",
        "부터",
        "까지",
        "하고",
        "하며",
        "이라",
        "라고",
        "인",
        "의",
        "을",
        "를",
        "은",
        "는",
        "이",
        "가",
        "와",
        "과",
        "로",
    ):
        if term.endswith(suffix) and len(term) - len(suffix) >= 2:
            return term[: -len(suffix)]
    return term


def _terms_overlap(left: set[str], right: set[str]) -> bool:
    return bool(_matching_terms(left, right))


def _matching_terms(left: set[str], right: set[str]) -> set[str]:
    matches = left & right
    for left_term in left - matches:
        if not re.fullmatch(r"[가-힣]+", left_term) or len(left_term) < 2:
            continue
        if any(
            re.fullmatch(r"[가-힣]+", right_term)
            and len(right_term) >= 2
            and (left_term in right_term or right_term in left_term)
            for right_term in right
        ):
            matches.add(left_term)
    return matches
