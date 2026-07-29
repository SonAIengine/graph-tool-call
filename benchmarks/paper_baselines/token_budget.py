"""Frozen tokenizer accounting and whole-schema candidate truncation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from graph_tool_call.core.tool import ToolSchema

DEFAULT_CONTEXT_TOKENIZER = "Qwen/Qwen3-4B"
DEFAULT_CONTEXT_TOKENIZER_REVISION = "1cfa9a7208912126459214e8b04321603b3df60c"
DEFAULT_TOKEN_BUDGET = 2048
TOKEN_BUDGET_POLICY_REVISION = "ranked-greedy-whole-schema-v1"
TOOL_SCHEMA_SERIALIZATION_REVISION = "paper-tool-schema-json-v1"


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
        }


def model_facing_schema(tool: ToolSchema) -> dict[str, Any]:
    """Return the frozen schema payload visible to a catalog-selecting model."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": [parameter.to_dict() for parameter in tool.parameters],
    }


def serialize_model_facing_schemas(
    names: list[str],
    tools_by_name: dict[str, ToolSchema],
) -> str:
    """Serialize complete tool schemas with deterministic JSON ordering."""
    payload = [model_facing_schema(tools_by_name[name]) for name in names if name in tools_by_name]
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def apply_ranked_token_budget(
    ranked_names: list[str],
    tools_by_name: dict[str, ToolSchema],
    *,
    token_counter: TokenCounter,
    token_budget: int,
) -> TokenBudgetSelection:
    """Keep the longest ranked prefix whose complete schemas fit the budget."""
    if token_budget <= 0:
        raise ValueError("token_budget must be greater than zero.")

    selected: list[str] = []
    used = token_counter.count(serialize_model_facing_schemas(selected, tools_by_name))
    if used > token_budget:
        raise ValueError("token_budget is too small for the empty catalog payload.")

    considered = 0
    truncated_at = ""
    for name in ranked_names:
        if name not in tools_by_name:
            continue
        considered += 1
        candidate_names = [*selected, name]
        candidate_tokens = token_counter.count(
            serialize_model_facing_schemas(candidate_names, tools_by_name)
        )
        if candidate_tokens > token_budget:
            truncated_at = name
            break
        selected = candidate_names
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
    )
