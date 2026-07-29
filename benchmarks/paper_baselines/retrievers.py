"""Benchmark-only retrieval baselines with frozen behavior."""

from __future__ import annotations

import hashlib
import math
import random
import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from graph_tool_call.core.tool import ToolSchema

FIXED_BM25_TOKENIZER_REVISION = "paper-bm25-lexical-v1"
DEFAULT_DENSE_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_DENSE_MODEL_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
FIXED_RRF_K = 60
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class RankedCandidate:
    """One deterministic baseline ranking result."""

    name: str
    score: float


class DenseEncoder(Protocol):
    """Minimal encoder contract used by the benchmark-only dense retriever."""

    def encode_documents(self, texts: list[str]) -> list[list[float]]: ...

    def encode_queries(self, texts: list[str]) -> list[list[float]]: ...


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
            Counter(fixed_lexical_tokens(baseline_document(tool))) for tool in self._tools
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


class SentenceTransformerDenseEncoder:
    """Revision-pinned multilingual E5 encoder for the B2 paper baseline."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_DENSE_MODEL,
        revision: str = DEFAULT_DENSE_MODEL_REVISION,
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.device = device
        self.batch_size = batch_size
        self._model: Any = None

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {text}" for text in texts])

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"query: {text}" for text in texts])

    def warmup(self) -> None:
        """Load the pinned model without attributing load time to one source."""
        self._get_model()

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        embeddings = model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [embedding.tolist() for embedding in embeddings]

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "B2/B3 require sentence-transformers. "
                    "Install with: poetry install --with dev -E embedding-local"
                )
            self._model = SentenceTransformer(
                self.model_name,
                revision=self.revision,
                device=self.device,
                trust_remote_code=False,
            )
        return self._model


class FixedDenseRetriever:
    """Cosine dense retrieval over the same frozen text as B1."""

    def __init__(self, tools: list[ToolSchema], encoder: DenseEncoder) -> None:
        unique_tools: dict[str, ToolSchema] = {}
        for tool in sorted(tools, key=_tool_sort_key):
            unique_tools.setdefault(tool.name, tool)
        self._tools = list(unique_tools.values())
        self._encoder = encoder
        started = time.perf_counter()
        self._embeddings = encoder.encode_documents(
            [baseline_document(tool) for tool in self._tools]
        )
        self.build_latency_ms = (time.perf_counter() - started) * 1000
        if len(self._embeddings) != len(self._tools):
            raise ValueError("Dense encoder returned a different number of document embeddings.")
        dimensions = {len(embedding) for embedding in self._embeddings}
        if len(dimensions) > 1:
            raise ValueError("Dense document embeddings must share one dimension.")

    def rank(self, query: str, *, top_k: int) -> list[RankedCandidate]:
        if top_k <= 0 or not self._tools:
            return []
        query_embeddings = self._encoder.encode_queries([query])
        if len(query_embeddings) != 1:
            raise ValueError("Dense encoder must return exactly one query embedding.")
        query_embedding = query_embeddings[0]
        ranked = [
            RankedCandidate(
                name=tool.name,
                score=_cosine_similarity(query_embedding, embedding),
            )
            for tool, embedding in zip(self._tools, self._embeddings, strict=True)
        ]
        ranked.sort(key=lambda item: (-item.score, item.name.casefold(), item.name))
        return ranked[:top_k]


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


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[RankedCandidate]],
    *,
    top_k: int,
    rrf_k: int = FIXED_RRF_K,
) -> list[RankedCandidate]:
    """Fuse complete rankings with unweighted reciprocal rank fusion."""
    if top_k <= 0:
        return []
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative.")
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, candidate in enumerate(ranking, start=1):
            if candidate.name in seen:
                continue
            seen.add(candidate.name)
            scores[candidate.name] = scores.get(candidate.name, 0.0) + 1.0 / (rrf_k + rank)
    fused = [RankedCandidate(name=name, score=score) for name, score in scores.items()]
    fused.sort(key=lambda item: (-item.score, item.name.casefold(), item.name))
    return fused[:top_k]


def baseline_document(tool: ToolSchema) -> str:
    ai_metadata = tool.metadata.get("ai_metadata")
    summary = ai_metadata.get("one_line_summary", "") if isinstance(ai_metadata, dict) else ""
    return " ".join((tool.name, str(summary or ""), tool.description or ""))


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Dense query and document embeddings must share one dimension.")
    if not left:
        return 0.0
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (left_norm * right_norm)


def _contains_hangul(token: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in token)


def _tool_sort_key(tool: ToolSchema) -> tuple[str, str]:
    return tool.name.casefold(), tool.name
