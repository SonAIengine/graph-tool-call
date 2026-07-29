"""Frozen deterministic baselines for the public paper corpus."""

from .retrievers import (
    FIXED_BM25_TOKENIZER_REVISION,
    FixedBM25Retriever,
    fixed_lexical_tokens,
    oracle_rank,
    seeded_random_rank,
)

__all__ = [
    "FIXED_BM25_TOKENIZER_REVISION",
    "FixedBM25Retriever",
    "fixed_lexical_tokens",
    "oracle_rank",
    "run_paper_baselines",
    "seeded_random_rank",
]


def __getattr__(name: str):
    if name == "run_paper_baselines":
        from .run import run_paper_baselines

        return run_paper_baselines
    raise AttributeError(name)
