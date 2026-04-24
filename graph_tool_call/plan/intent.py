"""Stage 1 — Intent Parser.

자연어 요구사항을 Stage 2 (PathSynthesizer) 가 소비할 수 있는 구조화
``{target, entities}`` 로 변환한다. LLM 1회 호출, 작은 context.

Catalog 구성 원칙 (설계 §4):
  - 사전에 retrieval 로 상위 K개 도구만 넘김 (전체 카탈로그 X)
  - 각 도구는 name + one_line_summary + when_to_use + 핵심 semantic tags
  - Pass 2 enrichment 가 채운 ai_metadata 가 있으면 그 정보를 우선 사용;
    없으면 description 축약본으로 fallback

LLM 은 structured JSON 만 반환 — 파싱 실패 시 BindingError 같은 방식으로
호출자에게 명확히 전달.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from graph_tool_call.ontology.llm_provider import OntologyLLM, _extract_json


# ---------------------------------------------------------------------------
# data shape
# ---------------------------------------------------------------------------


@dataclass
class ToolCatalogEntry:
    """Condensed tool view for intent-parsing prompt — under ~150 chars each."""

    name: str
    summary: str = ""                          # one_line_summary from ai_metadata
    when_to_use: str = ""                      # ai_metadata.when_to_use
    consumes_tags: list[str] = field(default_factory=list)   # required semantic ids
    canonical_action: str = ""                 # "read" | "search" | "create" | ...
    primary_resource: str = ""                 # "product" | ...


@dataclass
class ParsedIntent:
    """Stage 1 output — consumed by Stage 2 PathSynthesizer."""

    target: str                                # tool name picked by LLM
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0                    # 0.0 ~ 1.0
    output_shape: str = "single"               # "single" | "list" | "count"
    reasoning: str = ""


class IntentParseError(Exception):
    """Raised when the LLM output can't be mapped to a valid ParsedIntent."""


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------


_INTENT_PROMPT = """\
You pick the right API tool and extract entity values for a planning system.

User requirement:
{requirement}

Candidate tools (shortlisted by retrieval):
{catalog}

Rules:
  - Pick exactly ONE tool (the final-goal tool). Do not plan the chain —
    the downstream system will build prerequisite steps automatically.
  - entities: extract values from the requirement and key them by semantic
    id when known (e.g. "search_keyword", "product_id", "site_id").
    For free-text user inputs, prefer "search_keyword".
  - output_shape: "single" for one-item answers, "list" for multiple,
    "count" for aggregates.
  - confidence: your certainty in the tool pick, 0.0~1.0.
  - reasoning: one short sentence, for audit logs.

Output JSON only — no markdown, no prose. Schema:
{{
  "target": "<tool_name>",
  "entities": {{...}},
  "confidence": 0.0,
  "output_shape": "single" | "list" | "count",
  "reasoning": "..."
}}
"""


def _format_catalog(entries: list[ToolCatalogEntry]) -> str:
    lines: list[str] = []
    for i, e in enumerate(entries, start=1):
        parts = [f"{i}. {e.name}"]
        if e.canonical_action or e.primary_resource:
            parts.append(f"[{e.canonical_action}/{e.primary_resource}]".strip("[/]"))
        if e.summary:
            parts.append(f"— {e.summary}")
        lines.append(" ".join(p for p in parts if p))
        if e.when_to_use:
            lines.append(f"   when: {e.when_to_use[:140]}")
        if e.consumes_tags:
            lines.append(f"   needs: {', '.join(e.consumes_tags[:6])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def parse_intent(
    requirement: str,
    catalog: list[ToolCatalogEntry],
    llm: OntologyLLM,
) -> ParsedIntent:
    """Call the LLM once to produce a ParsedIntent.

    ``catalog`` should be the retrieval-shortlisted candidate tools (keep
    small — ~10 entries — to control prompt size). ``llm`` is any
    OntologyLLM-compatible provider.
    """
    if not catalog:
        raise IntentParseError("empty catalog — cannot pick a target")

    prompt = _INTENT_PROMPT.format(
        requirement=requirement.strip(),
        catalog=_format_catalog(catalog),
    )
    raw = llm.generate(prompt)

    try:
        parsed = _extract_json(raw)
    except json.JSONDecodeError as exc:
        raise IntentParseError(f"LLM output not parseable JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise IntentParseError(f"expected JSON object, got {type(parsed).__name__}")

    target = str(parsed.get("target") or "").strip()
    if not target:
        raise IntentParseError("target missing from LLM output")

    # Validate target is in the catalog — guard against hallucinated names
    allowed = {e.name for e in catalog}
    if target not in allowed:
        raise IntentParseError(
            f"target {target!r} not in catalog (candidates: {sorted(allowed)[:5]!r}...)"
        )

    entities_raw = parsed.get("entities")
    entities = entities_raw if isinstance(entities_raw, dict) else {}

    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    shape = str(parsed.get("output_shape") or "single").strip().lower()
    if shape not in ("single", "list", "count"):
        shape = "single"

    return ParsedIntent(
        target=target,
        entities=entities,
        confidence=confidence,
        output_shape=shape,
        reasoning=str(parsed.get("reasoning") or "").strip(),
    )


__all__ = [
    "ToolCatalogEntry",
    "ParsedIntent",
    "IntentParseError",
    "parse_intent",
]
