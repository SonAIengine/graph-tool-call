"""Frozen tokenizer accounting and whole-schema candidate truncation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from graph_tool_call.core.tool import ToolSchema

DEFAULT_CONTEXT_TOKENIZER = "Qwen/Qwen3-4B"
DEFAULT_CONTEXT_TOKENIZER_REVISION = "1cfa9a7208912126459214e8b04321603b3df60c"
DEFAULT_TOKEN_BUDGET = 2048
TOKEN_BUDGET_POLICY_REVISION = "ranked-greedy-whole-schema-v1"
TOOL_SCHEMA_SERIALIZATION_REVISION = "paper-tool-schema-json-v1"
CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION = "paper-contract-projected-admission-v1"
CONTRACT_PROJECTED_DESCRIPTION_LIMIT = 240
CONTRACT_PROJECTED_PARAMETER_DESCRIPTION_LIMIT = 160
CONTRACT_PROJECTED_ENUM_LIMIT = 16


class TokenCounter(Protocol):
    """Minimal tokenizer interface used by the deterministic paper harness."""

    def count(self, text: str) -> int:
        """Return the number of model-facing tokens in text."""


class HuggingFaceTokenCounter:
    """Count tokens with one immutable Hugging Face tokenizer revision."""

    def __init__(self, *, name: str, revision: str) -> None:
        if not name.strip() or not revision.strip():
            raise ValueError("Tokenizer name and revision must be non-empty.")
        self.name = name
        self.revision = revision
        self._tokenizer: Any | None = None

    def warmup(self) -> None:
        """Load the frozen tokenizer without executing repository code."""
        if self._tokenizer is not None:
            return
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "Token-budget accounting requires transformers. "
                "Run `poetry install --with dev -E embedding-local`."
            ) from exc
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.name,
            revision=self.revision,
            trust_remote_code=False,
        )

    def count(self, text: str) -> int:
        """Count tokens without model-added special tokens."""
        self.warmup()
        return len(self._tokenizer.encode(text, add_special_tokens=False))


@dataclass(frozen=True)
class TokenBudgetSelection:
    """One deterministic prefix selected under a model-facing token budget."""

    retrieved: list[str]
    schema_tokens: int
    token_budget_limit: int
    token_budget_used: int
    token_budget_utilization: float
    truncated: bool
    truncated_at: str
    considered_candidate_count: int
    policy_revision: str = TOKEN_BUDGET_POLICY_REVISION
    schema_modes: dict[str, str] = field(default_factory=dict)
    projected_schema_count: int = 0
    projection_saved_tokens: int = 0
    schema_chars: int = 0
    schema_utf8_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieved": list(self.retrieved),
            "schema_tokens": self.schema_tokens,
            "token_budget_limit": self.token_budget_limit,
            "token_budget_used": self.token_budget_used,
            "token_budget_utilization": self.token_budget_utilization,
            "truncated": self.truncated,
            "truncated_at": self.truncated_at,
            "considered_candidate_count": self.considered_candidate_count,
            "policy_revision": self.policy_revision,
            "schema_modes": dict(self.schema_modes),
            "projected_schema_count": self.projected_schema_count,
            "projection_saved_tokens": self.projection_saved_tokens,
            "schema_chars": self.schema_chars,
            "schema_utf8_bytes": self.schema_utf8_bytes,
        }


def model_facing_schema(tool: ToolSchema) -> dict[str, Any]:
    """Return the frozen schema payload visible to a catalog-selecting model."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": [parameter.to_dict() for parameter in tool.parameters],
    }


def contract_projected_model_facing_schema(tool: ToolSchema) -> dict[str, Any]:
    """Return a bounded selection-time view that preserves required inputs.

    The full schema remains the execution source of truth. This projection is
    only for admitting a graph-evidenced candidate to the catalog-selection
    context before the selected tool is hydrated.
    """
    ai_metadata = tool.metadata.get("ai_metadata") or {}
    openapi = tool.metadata.get("openapi") or {}
    description = (
        ai_metadata.get("one_line_summary") or openapi.get("summary") or tool.description or ""
    )
    parameters = []
    for parameter in tool.parameters:
        if not parameter.required:
            continue
        enum = list(parameter.enum or [])[:CONTRACT_PROJECTED_ENUM_LIMIT] or None
        parameters.append(
            {
                "name": parameter.name,
                "type": parameter.type,
                "description": _bounded_text(
                    parameter.description,
                    CONTRACT_PROJECTED_PARAMETER_DESCRIPTION_LIMIT,
                ),
                "required": True,
                "enum": enum,
            }
        )
    return {
        "name": tool.name,
        "description": _bounded_text(description, CONTRACT_PROJECTED_DESCRIPTION_LIMIT),
        "parameters": parameters,
    }


def serialize_model_facing_payloads(payloads: list[dict[str, Any]]) -> str:
    """Serialize model-facing payloads with deterministic JSON ordering."""
    return json.dumps(
        payloads,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def serialize_model_facing_schemas(
    names: list[str],
    tools_by_name: dict[str, ToolSchema],
) -> str:
    """Serialize complete tool schemas with deterministic JSON ordering."""
    payload = [model_facing_schema(tools_by_name[name]) for name in names if name in tools_by_name]
    return serialize_model_facing_payloads(payload)


def apply_ranked_token_budget(
    ranked_names: list[str],
    tools_by_name: dict[str, ToolSchema],
    *,
    token_counter: TokenCounter,
    token_budget: int,
) -> TokenBudgetSelection:
    """Keep the longest ranked prefix whose complete schemas fit the budget."""
    return _apply_token_budget(
        ranked_names,
        tools_by_name,
        projection_names=set(),
        token_counter=token_counter,
        token_budget=token_budget,
        policy_revision=TOKEN_BUDGET_POLICY_REVISION,
    )


def apply_contract_projected_token_budget(
    ranked_names: list[str],
    tools_by_name: dict[str, ToolSchema],
    *,
    projection_names: set[str],
    token_counter: TokenCounter,
    token_budget: int,
) -> TokenBudgetSelection:
    """Project only evidence-admitted schemas while preserving ranked order."""
    return _apply_token_budget(
        ranked_names,
        tools_by_name,
        projection_names=set(projection_names),
        token_counter=token_counter,
        token_budget=token_budget,
        policy_revision=CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION,
    )


def _apply_token_budget(
    ranked_names: list[str],
    tools_by_name: dict[str, ToolSchema],
    *,
    projection_names: set[str],
    token_counter: TokenCounter,
    token_budget: int,
    policy_revision: str,
) -> TokenBudgetSelection:
    if token_budget <= 0:
        raise ValueError("token_budget must be greater than zero.")

    selected: list[str] = []
    selected_payloads: list[dict[str, Any]] = []
    serialized = serialize_model_facing_payloads(selected_payloads)
    used = token_counter.count(serialized)
    if used > token_budget:
        raise ValueError("token_budget is too small for the empty catalog payload.")

    considered = 0
    truncated_at = ""
    schema_modes: dict[str, str] = {}
    projection_saved_tokens = 0
    for name in ranked_names:
        if name not in tools_by_name:
            continue
        considered += 1
        tool = tools_by_name[name]
        projected = name in projection_names
        payload = (
            contract_projected_model_facing_schema(tool) if projected else model_facing_schema(tool)
        )
        candidate_payloads = [*selected_payloads, payload]
        candidate_serialized = serialize_model_facing_payloads(candidate_payloads)
        candidate_tokens = token_counter.count(candidate_serialized)
        if candidate_tokens > token_budget:
            truncated_at = name
            break
        if projected:
            full_serialized = serialize_model_facing_payloads(
                [*selected_payloads, model_facing_schema(tool)]
            )
            projection_saved_tokens += max(
                0,
                token_counter.count(full_serialized) - candidate_tokens,
            )
        selected.append(name)
        selected_payloads = candidate_payloads
        schema_modes[name] = "contract_projected" if projected else "full"
        serialized = candidate_serialized
        used = candidate_tokens

    return TokenBudgetSelection(
        retrieved=selected,
        schema_tokens=used,
        token_budget_limit=token_budget,
        token_budget_used=used,
        token_budget_utilization=used / token_budget,
        truncated=bool(truncated_at),
        truncated_at=truncated_at,
        considered_candidate_count=considered,
        policy_revision=policy_revision,
        schema_modes=schema_modes,
        projected_schema_count=sum(mode == "contract_projected" for mode in schema_modes.values()),
        projection_saved_tokens=projection_saved_tokens,
        schema_chars=len(serialized),
        schema_utf8_bytes=len(serialized.encode("utf-8")),
    )


def _bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."
