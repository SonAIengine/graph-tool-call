"""Frozen deterministic baselines for the public paper corpus."""

from .retrievers import (
    DEFAULT_DENSE_MODEL,
    DEFAULT_DENSE_MODEL_REVISION,
    FIXED_BM25_TOKENIZER_REVISION,
    FIXED_RRF_K,
    DenseEncoder,
    FixedBM25Retriever,
    FixedDenseRetriever,
    RankedCandidate,
    SentenceTransformerDenseEncoder,
    fixed_lexical_tokens,
    flat_semantic_coverage,
    flat_semantic_document,
    flat_semantic_metadata,
    oracle_rank,
    reciprocal_rank_fusion,
    seeded_random_rank,
)

__all__ = [
    "DEFAULT_DENSE_MODEL",
    "DEFAULT_DENSE_MODEL_REVISION",
    "FIXED_RRF_K",
    "FIXED_BM25_TOKENIZER_REVISION",
    "DenseEncoder",
    "FixedBM25Retriever",
    "FixedDenseRetriever",
    "RankedCandidate",
    "SentenceTransformerDenseEncoder",
    "flat_semantic_coverage",
    "flat_semantic_document",
    "flat_semantic_metadata",
    "fixed_lexical_tokens",
    "oracle_rank",
    "reciprocal_rank_fusion",
    "run_paper_baselines",
    "seeded_random_rank",
]


def __getattr__(name: str):
    if name == "run_paper_baselines":
        from .run import run_paper_baselines

        return run_paper_baselines
    raise AttributeError(name)
