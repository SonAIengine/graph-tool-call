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

import difflib
import json
from dataclasses import dataclass, field
from typing import Any

from graph_tool_call.ontology.llm_provider import OntologyLLM, _extract_json


# Minimum SequenceMatcher ratio for treating an LLM-emitted entity key as
# a typo/expansion of a real vocab entry. 0.8 catches "search_keyword_name"
# vs "search_keyword" (~0.85) while rejecting unrelated pairs like
# "search_keyword" vs "search_query" (~0.54).
_VOCAB_FUZZY_CUTOFF = 0.8


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

Candidate tools (shortlisted by retrieval — includes the target's
prerequisite producers so every key you need should appear in some
tool's "needs:" line below):
{catalog}
{vocabulary_block}{enum_block}{seed_block}
HARD CONSTRAINTS — violating any of these is a planning error, not a
stylistic choice. Re-check the constraints before you emit JSON.

  HC1. DO NOT put a value into an identifier-style field (a field name
       ending in "No" / "Id" / "Idx" / "Code" / "id") if the value
       contains spaces, Korean/Chinese/Japanese letters, or category
       words ("티셔츠", "신발", "shoes", a brand or model name).
       Identifier fields accept short alphanumeric record locators
       only ("G12345", "10293"). A descriptive phrase placed in such
       a field is always wrong.
  HC2. DO NOT invent field names. Every entity key MUST appear in one
       of the candidate tools' "needs:" lines. If no listed field can
       carry the user's value without violating HC1, omit the entity —
       empty entities are fine; the downstream synthesizer chains
       through a producer.
  HC3. DO NOT put the same value into more than one field. Each value
       goes into zero or exactly one field.
  HC4. DO NOT translate, normalize, paraphrase, or expand the user's
       value. Copy it byte-for-byte as written in the requirement.
  HC5. For fields that have an enum mapping below, the entity value
       MUST be one of the listed CODES (left side), never the label
       (right side) and never the user's original phrase. Pick the
       code whose label best matches the user's intent. If nothing
       matches clearly, omit that entity.

Selection guidance (apply only after the constraints hold):
  - Pick exactly ONE tool — the final-goal tool. Do not plan the chain;
    the downstream system builds prerequisite steps automatically.
  - Free-text values (descriptive phrases like "quarzen 티셔츠",
    "black hoodie") match fields named "searchWord", "query",
    "keyword", or names ending in "Nm" / "Name".
  - When several fields could carry the value without violating HC1,
    prefer one a candidate's "needs:" line lists — that is a field a
    tool you already considered actually accepts.
  - output_shape: "single" / "list" / "count".
  - confidence: 0.0~1.0 — your certainty in the tool pick.
  - reasoning: one short sentence for audit logs.

Output JSON only — no markdown, no prose. Schema:
{{
  "target": "<tool_name>",
  "entities": {{...}},
  "confidence": 0.0,
  "output_shape": "single" | "list" | "count",
  "reasoning": "..."
}}
"""


def _coerce_entity_keys(
    entities: dict[str, Any],
    vocab: list[str],
) -> dict[str, Any]:
    """Map LLM-emitted entity keys onto the vocabulary.

    Exact match → kept. Close match above ``_VOCAB_FUZZY_CUTOFF`` → coerced
    to the canonical vocab entry. Otherwise the entry is dropped — silently
    passing an invented key downstream causes producer-chain failures or
    cycle detection (the vocab miss is the failure, not the symptom).
    """
    vocab_set = set(vocab)
    out: dict[str, Any] = {}
    for key, value in entities.items():
        key_str = str(key)
        if key_str in vocab_set:
            out[key_str] = value
            continue
        match = difflib.get_close_matches(
            key_str, vocab, n=1, cutoff=_VOCAB_FUZZY_CUTOFF,
        )
        if match:
            # If multiple LLM keys collapse onto the same vocab entry, the
            # later one wins. Acceptable: same canonical key with two
            # values is already a degenerate LLM output.
            out[match[0]] = value
    return out


def _format_seed_block(seed_entities: dict[str, Any] | None) -> str:
    """Render a 'carry forward' section for entities the caller already
    decided in a previous turn.

    Multi-turn flow: when a previous synthesize attempt asked the user to
    pick a value (e.g. via a popup of enum options), the chosen pairs are
    fed back as ``seed_entities``. The LLM should keep them as-is unless
    the new requirement explicitly contradicts a value, and only EXTRACT
    NEW entities to add. Empty / None ⇒ section omitted.
    """
    if not seed_entities:
        return ""
    lines = "\n".join(
        f'  - {k}: {json.dumps(v, ensure_ascii=False)}'
        for k, v in seed_entities.items()
    )
    return (
        "\n\nExisting entities (carried over from prior turns — keep these "
        "values exactly unless the user's new requirement explicitly "
        "overrides one. You only need to extract additional entities that "
        "the new requirement introduces):\n"
        f"{lines}"
    )


def _format_enum_block(enum_mappings: dict[str, dict[str, str]] | None) -> str:
    """Render the optional enum-mapping section of the prompt.

    ``enum_mappings`` shape: ``{field_name: {code: label}}`` — operator-
    registered code lookups for backend enum fields whose values aren't
    in the swagger schema (e.g. "10" -> "비회원" for a basket type code).
    The LLM picks the code whose label matches the user's natural-language
    intent. Empty / None ⇒ section omitted entirely.
    """
    if not enum_mappings:
        return ""
    lines: list[str] = []
    for field, codes in enum_mappings.items():
        if not isinstance(codes, dict) or not codes:
            continue
        lines.append(f"  - {field}:")
        for code, label in codes.items():
            lines.append(f'      "{code}" → {label}')
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "\n\nEnum code mappings (operator-registered — when one of these "
        "fields needs a value, pick the CODE whose label matches the "
        "user's intent):\n"
        f"{body}"
    )


def _format_vocabulary_block(tags: list[str]) -> str:
    """Render the optional vocabulary section of the prompt.

    Returns an empty string when no vocab is provided so the prompt
    stays focused on ``catalog``. Callers that want LLM access to
    field names beyond the catalog (e.g. when retrieval failed to pull
    in producers) can pass a non-empty list.
    """
    if not tags:
        return ""
    lines = "\n".join(f"  - {t}" for t in tags)
    return (
        "\n\nAvailable entity field names — backup vocabulary used only when "
        "no candidate tool's \"needs:\" line carries the user's value:\n"
        f"{lines}"
    )


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
    *,
    vocabulary: list[str] | None = None,
    enum_mappings: dict[str, dict[str, str]] | None = None,
    seed_entities: dict[str, Any] | None = None,
) -> ParsedIntent:
    """Call the LLM once to produce a ParsedIntent.

    ``catalog`` should be the retrieval-shortlisted candidate tools (keep
    small — ~10 entries — to control prompt size). ``vocabulary`` is the
    full set of ``kind=data`` semantic ids in the graph (so the LLM can
    map free-text inputs to a search-style key even when the matching
    producer wasn't retrieved). ``enum_mappings`` is operator-registered
    ``{field_name: {code: label}}`` lookups for backend enum fields whose
    values aren't in the swagger schema — exposed only when relevant
    (caller should pre-filter to the catalog's consumes fields).
    ``seed_entities`` carries entities decided in earlier turns of a
    multi-turn flow (e.g. user clicked an option in a popup); the LLM
    keeps them and only extracts additional ones from the new
    ``requirement``. ``llm`` is any OntologyLLM-compatible provider.
    """
    if not catalog:
        raise IntentParseError("empty catalog — cannot pick a target")

    vocab = vocabulary or []
    if not vocab:
        # Fallback: derive from catalog. Same-domain narrowing only —
        # callers that supply the full graph vocab get better accuracy.
        seen: set[str] = set()
        for e in catalog:
            for tag in e.consumes_tags:
                if tag and tag not in seen:
                    seen.add(tag)
                    vocab.append(tag)

    prompt = _INTENT_PROMPT.format(
        requirement=requirement.strip(),
        catalog=_format_catalog(catalog),
        vocabulary_block=_format_vocabulary_block(vocab),
        enum_block=_format_enum_block(enum_mappings),
        seed_block=_format_seed_block(seed_entities),
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

    # Validate entity keys against the vocabulary. The LLM regularly emits
    # a slightly-elaborated key ("search_keyword_name" instead of
    # "search_keyword") that nothing downstream can match — coerce the
    # close ones, drop the rest. A wrong key triggers worse downstream
    # behavior than no key.
    if vocab and entities:
        entities = _coerce_entity_keys(entities, vocab)

    # Multi-turn safety net: even if the LLM ignored the carry-forward
    # instructions, prior-turn entities must persist. New entities from
    # this turn override on conflict (later turn wins for explicit
    # contradictions in the requirement).
    if seed_entities:
        entities = {**seed_entities, **entities}

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
