"""Deterministic catalog contracts for the budgeted LLM-only baseline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.paper_baselines.token_budget import (
    TokenCounter,
    serialize_model_facing_payloads,
)
from graph_tool_call.core.tool import ToolSchema

B0L_BASELINE = "llm_hierarchical_catalog_selector"
LLM_CATALOG_INDEX_REVISION = "paper-flat-contract-catalog-index-v1"
LLM_CATALOG_CHUNK_POLICY_REVISION = "paper-hierarchical-catalog-chunking-v1"
LLM_CATALOG_SHORTLIST_REVISION = "paper-local-shortlist-v1"
LLM_CATALOG_FINAL_SELECTION_REVISION = "paper-b0l-final-selection-v1"
LLM_CATALOG_REDUCTION_RATIO = 0.5
DEFAULT_SHORTLIST_SIZE = 5
DEFAULT_MAX_HIERARCHY_ROUNDS = 8
DESCRIPTION_LIMIT = 240
PATH_LIMIT = 200
MAX_INPUT_FIELDS = 24
MAX_OUTPUT_FIELDS = 24


@dataclass(frozen=True)
class CatalogChunk:
    """One complete, deterministic model-facing catalog chunk."""

    round_index: int
    chunk_index: int
    names: list[str]
    payloads: list[dict[str, Any]]
    serialized: str
    catalog_tokens: int
    token_budget_limit: int
    catalog_sha256: str

    def to_dict(self, *, include_payloads: bool = False) -> dict[str, Any]:
        value = asdict(self)
        if not include_payloads:
            value.pop("payloads", None)
            value.pop("serialized", None)
        return value


@dataclass(frozen=True)
class ShortlistDecision:
    """Normalized local reduction decision for one catalog chunk."""

    candidate_tools: list[str]
    raw: dict[str, Any]
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_llm_catalog_index(tools_by_name: dict[str, ToolSchema]) -> list[dict[str, Any]]:
    """Build a graph-free flat catalog index in stable operation-name order.

    The index exposes only per-tool source and contract facts. It never uses
    retrieval rank, graph edges, expected labels, traces, or held-out data.
    """
    return [
        _catalog_index_entry(tools_by_name[name])
        for name in sorted(tools_by_name, key=lambda value: (value.casefold(), value))
    ]


def build_llm_catalog_chunks(
    entries: list[dict[str, Any]],
    *,
    token_counter: TokenCounter,
    token_budget: int,
    round_index: int,
) -> list[CatalogChunk]:
    """Partition every supplied entry into stable greedy chunks under budget."""
    if token_budget <= 0:
        raise ValueError("token_budget must be greater than zero.")
    if round_index < 0:
        raise ValueError("round_index must be non-negative.")

    chunks: list[CatalogChunk] = []
    current: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            raise ValueError("Every catalog index entry requires a name.")
        candidate = [*current, entry]
        if token_counter.count(serialize_model_facing_payloads(candidate)) <= token_budget:
            current = candidate
            continue
        if not current:
            raise ValueError(f"Catalog entry exceeds token budget: {name}")
        chunks.append(
            _catalog_chunk(
                current,
                round_index=round_index,
                chunk_index=len(chunks),
                token_counter=token_counter,
                token_budget=token_budget,
            )
        )
        current = [entry]
        if token_counter.count(serialize_model_facing_payloads(current)) > token_budget:
            raise ValueError(f"Catalog entry exceeds token budget: {name}")

    if current:
        chunks.append(
            _catalog_chunk(
                current,
                round_index=round_index,
                chunk_index=len(chunks),
                token_counter=token_counter,
                token_budget=token_budget,
            )
        )
    return chunks


def parse_shortlist_decision(content: str, *, shortlist_size: int) -> ShortlistDecision:
    """Parse a local shortlist while preserving model order and a hard size cap."""
    if shortlist_size <= 0:
        raise ValueError("shortlist_size must be greater than zero.")
    payload = _extract_json_object(content)
    raw_names = payload.get("candidate_tools")
    if not isinstance(raw_names, list):
        raw_names = payload.get("selected_tools")
    if not isinstance(raw_names, list):
        target = str(payload.get("target_tool") or "").strip()
        supporting = payload.get("supporting_tools")
        raw_names = [*(supporting if isinstance(supporting, list) else []), target]
    names = _dedupe_names([str(name) for name in raw_names if str(name).strip()])
    reason_codes: list[str] = []
    if not names:
        reason_codes.append("shortlist_empty")
    if len(names) > shortlist_size:
        reason_codes.append("shortlist_limit_exceeded")
        names = names[:shortlist_size]
    return ShortlistDecision(
        candidate_tools=names,
        raw=payload,
        reason_codes=reason_codes,
    )


def shortlist_messages(
    query: str,
    serialized_chunk: str,
    *,
    shortlist_size: int,
) -> list[dict[str, str]]:
    """Return the frozen local-reduction prompt without evaluation labels."""
    return [
        {
            "role": "system",
            "content": (
                "Shortlist API tools only from the supplied catalog chunk. Return one JSON "
                f'object with schema {{"candidate_tools": [string]}} and at most '
                f"{shortlist_size} names. Preserve tools that may be the final operation or "
                "may produce data required by it. Use exact catalog names, do not invent "
                "tools, and return no prose."
            ),
        },
        {
            "role": "user",
            "content": f"Request:\n{query}\n\nCatalog chunk:\n{serialized_chunk}",
        },
    ]


def final_selection_messages(
    query: str,
    serialized_catalog: str,
    *,
    max_selected_tools: int,
) -> list[dict[str, str]]:
    """Return the frozen B0-L final selector prompt with an explicit cap."""
    if max_selected_tools <= 0:
        raise ValueError("max_selected_tools must be greater than zero.")
    max_supporting = max_selected_tools - 1
    return [
        {
            "role": "system",
            "content": (
                "Select API tools only from the supplied catalog. Return one JSON object "
                'with schema {"target_tool": string, "supporting_tools": [string]}. '
                "The target is the final operation satisfying the request. Supporting tools "
                "must run before the target and provide data needed by it. Select at most "
                f"{max_selected_tools} tools total, including no more than {max_supporting} "
                "supporting tools. Use exact catalog names, do not invent tools, and return "
                "no prose."
            ),
        },
        {
            "role": "user",
            "content": f"Request:\n{query}\n\nFrozen tool catalog:\n{serialized_catalog}",
        },
    ]


def local_shortlist_limit(chunk_size: int, *, shortlist_size: int) -> int:
    """Return a deterministic cap that guarantees reduction for non-singletons."""
    if chunk_size <= 0 or shortlist_size <= 0:
        raise ValueError("chunk_size and shortlist_size must be greater than zero.")
    return min(shortlist_size, max(1, int(chunk_size * LLM_CATALOG_REDUCTION_RATIO)))


def _catalog_index_entry(tool: ToolSchema) -> dict[str, Any]:
    metadata = tool.metadata or {}
    openapi = metadata.get("openapi") or {}
    ai_metadata = metadata.get("ai_metadata") or {}
    contract = metadata.get("api_contract") or {}
    description = (
        openapi.get("summary") or ai_metadata.get("one_line_summary") or tool.description or ""
    )
    all_required_inputs = [
        {"name": parameter.name, "type": parameter.type}
        for parameter in tool.parameters
        if parameter.required
    ]
    all_optional_inputs = [
        {"name": parameter.name, "type": parameter.type}
        for parameter in tool.parameters
        if not parameter.required
    ]
    required_inputs = all_required_inputs[:MAX_INPUT_FIELDS]
    optional_inputs = all_optional_inputs[:MAX_INPUT_FIELDS]
    output_fields = []
    seen_outputs: set[tuple[str, str]] = set()
    for row in contract.get("produces") or []:
        name = str(row.get("field_name") or "").strip()
        field_type = str(row.get("field_type") or "").strip()
        if not name or (name, field_type) in seen_outputs:
            continue
        seen_outputs.add((name, field_type))
        output_fields.append({"name": name, "type": field_type})
        if len(output_fields) >= MAX_OUTPUT_FIELDS:
            break

    entry: dict[str, Any] = {
        "name": tool.name,
        "description": _bounded_text(description, DESCRIPTION_LIMIT),
        "required_inputs": required_inputs,
        "optional_inputs": optional_inputs,
        "output_fields": output_fields,
        "field_counts": {
            "required_inputs": len(all_required_inputs),
            "optional_inputs": len(all_optional_inputs),
            "outputs": len(seen_outputs),
        },
        "field_truncation": {
            "required_inputs": len(all_required_inputs) > MAX_INPUT_FIELDS,
            "optional_inputs": len(all_optional_inputs) > MAX_INPUT_FIELDS,
            "outputs": len(seen_outputs) > MAX_OUTPUT_FIELDS,
        },
    }
    source_facts = {
        "method": metadata.get("method") or openapi.get("method"),
        "path": _bounded_text(metadata.get("path") or openapi.get("path"), PATH_LIMIT),
    }
    source_facts = {key: value for key, value in source_facts.items() if value}
    if source_facts:
        entry["source"] = source_facts
    semantics = {
        key: ai_metadata.get(key) or openapi.get(key)
        for key in (
            "canonical_action",
            "primary_resource",
            "path_module",
            "result_shape",
        )
        if ai_metadata.get(key)
    }
    if semantics:
        entry["semantics"] = semantics
    return entry


def _catalog_chunk(
    payloads: list[dict[str, Any]],
    *,
    round_index: int,
    chunk_index: int,
    token_counter: TokenCounter,
    token_budget: int,
) -> CatalogChunk:
    serialized = serialize_model_facing_payloads(payloads)
    tokens = token_counter.count(serialized)
    return CatalogChunk(
        round_index=round_index,
        chunk_index=chunk_index,
        names=[str(payload["name"]) for payload in payloads],
        payloads=list(payloads),
        serialized=serialized,
        catalog_tokens=tokens,
        token_budget_limit=token_budget,
        catalog_sha256=hashlib.sha256(serialized.encode()).hexdigest(),
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _dedupe_names(names: list[str]) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))
