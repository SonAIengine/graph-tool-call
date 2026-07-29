"""Benchmark-only retrieval baselines with frozen behavior."""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter
from dataclasses import dataclass

from graph_tool_call.core.tool import ToolSchema

FIXED_BM25_TOKENIZER_REVISION = "paper-bm25-lexical-v1"
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class RankedCandidate:
    """One deterministic baseline ranking result."""

    name: str
    score: float


def fixed_lexical_tokens(text: str) -> list[str]:
    """Tokenize identifiers and natural language with a frozen stdlib policy."""
    expanded = _CAMEL_BOUNDARY.sub(" ", str(text or ""))
    raw_tokens = [match.group(0).casefold() for match in _WORD.finditer(expanded)]
    tokens: list[str] = []
    for token in raw_tokens:
        tokens.append(token)
        if _contains_hangul(token) and len(token) > 2:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


class FixedBM25Retriever:
    """Clean BM25 baseline over name, one-line summary, and description only."""

    def __init__(
        self,
        tools: list[ToolSchema],
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        self.k1 = float(k1)
        self.b = float(b)
        unique_tools: dict[str, ToolSchema] = {}
        for tool in sorted(tools, key=_tool_sort_key):
            unique_tools.setdefault(tool.name, tool)
        self._tools = list(unique_tools.values())
        self._documents = [
            Counter(fixed_lexical_tokens(_baseline_document(tool))) for tool in self._tools
        ]
        self._document_lengths = [sum(document.values()) for document in self._documents]
        self._average_document_length = (
            sum(self._document_lengths) / len(self._document_lengths)
            if self._document_lengths
            else 0.0
        )
        self._document_frequency: Counter[str] = Counter()
        for document in self._documents:
            self._document_frequency.update(document)

    def rank(self, query: str, *, top_k: int) -> list[RankedCandidate]:
        if top_k <= 0 or not self._tools:
            return []
        query_terms = Counter(fixed_lexical_tokens(query))
        ranked = [
            RankedCandidate(
                name=tool.name,
                score=self._score(document, length, query_terms),
            )
            for tool, document, length in zip(
                self._tools,
                self._documents,
                self._document_lengths,
                strict=True,
            )
        ]
        ranked.sort(key=lambda item: (-item.score, item.name.casefold(), item.name))
        return ranked[:top_k]

    def _score(
        self,
        document: Counter[str],
        document_length: int,
        query_terms: Counter[str],
    ) -> float:
        if not query_terms:
            return 0.0
        score = 0.0
        document_count = len(self._documents)
        average_length = self._average_document_length or 1.0
        for term, query_frequency in query_terms.items():
            term_frequency = document.get(term, 0)
            if not term_frequency:
                continue
            document_frequency = self._document_frequency[term]
            inverse_document_frequency = math.log(
                1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = term_frequency + self.k1 * (
                1.0 - self.b + self.b * document_length / average_length
            )
            score += (
                inverse_document_frequency
                * (term_frequency * (self.k1 + 1.0) / denominator)
                * query_frequency
            )
        return score


def seeded_random_rank(
    tools: list[ToolSchema],
    *,
    top_k: int,
    seed: int,
    source_id: str,
    case_id: str,
) -> list[RankedCandidate]:
    """Sample a reproducible random ranking without depending on case order."""
    names = sorted({tool.name for tool in tools}, key=lambda name: (name.casefold(), name))
    if top_k <= 0 or not names:
        return []
    derived_seed = hashlib.sha256(f"{seed}:{source_id}:{case_id}".encode()).digest()
    rng = random.Random(int.from_bytes(derived_seed[:8], "big"))
    selected = rng.sample(names, k=min(top_k, len(names)))
    return [RankedCandidate(name=name, score=0.0) for name in selected]


def oracle_rank(
    *,
    expected_targets: list[str],
    required_producers: list[str],
    acceptable_alternatives: list[str],
    available_names: set[str],
    top_k: int,
) -> list[RankedCandidate]:
    """Return the annotated ceiling in target, producer, alternative order."""
    ranked: list[RankedCandidate] = []
    seen: set[str] = set()
    for grade, names in (
        (3.0, expected_targets),
        (2.0, required_producers),
        (1.0, acceptable_alternatives),
    ):
        for name in names:
            if name in available_names and name not in seen:
                ranked.append(RankedCandidate(name=name, score=grade))
                seen.add(name)
                if len(ranked) >= top_k:
                    return ranked
    return ranked


def _baseline_document(tool: ToolSchema) -> str:
    ai_metadata = tool.metadata.get("ai_metadata")
    summary = ai_metadata.get("one_line_summary", "") if isinstance(ai_metadata, dict) else ""
    return " ".join((tool.name, str(summary or ""), tool.description or ""))


def _contains_hangul(token: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in token)


def _tool_sort_key(tool: ToolSchema) -> tuple[str, str]:
    return tool.name.casefold(), tool.name
