"""Retrieval evaluation metrics."""

from __future__ import annotations

import math


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Precision@K: fraction of top-K results that are relevant.

    Parameters
    ----------
    retrieved:
        Ordered list of retrieved tool names.
    relevant:
        Set of relevant (ground-truth) tool names.
    k:
        Number of top results to consider.

    Returns
    -------
    float
        Precision value between 0.0 and 1.0.
    """
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for name in top_k if name in relevant)
    return hits / len(top_k)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Recall@K: fraction of relevant items found in top-K results.

    Parameters
    ----------
    retrieved:
        Ordered list of retrieved tool names.
    relevant:
        Set of relevant (ground-truth) tool names.
    k:
        Number of top results to consider.

    Returns
    -------
    float
        Recall value between 0.0 and 1.0.
    """
    if not relevant:
        return 1.0  # no relevant items → perfect recall by convention
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for name in top_k if name in relevant)
    return hits / len(relevant)


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain@K.

    Uses binary relevance: 1 if in relevant set, 0 otherwise.

    Parameters
    ----------
    retrieved:
        Ordered list of retrieved tool names.
    relevant:
        Set of relevant (ground-truth) tool names.
    k:
        Number of top results to consider.

    Returns
    -------
    float
        NDCG value between 0.0 and 1.0.
    """
    if not relevant or k <= 0:
        return 0.0

    top_k = retrieved[:k]

    # DCG: sum(rel_i / log2(i + 2)) for i in 0..k-1
    dcg = 0.0
    for i, name in enumerate(top_k):
        rel = 1.0 if name in relevant else 0.0
        dcg += rel / math.log2(i + 2)

    # Ideal DCG: all relevant items ranked first
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))

    if idcg == 0:
        return 0.0
    return dcg / idcg


def workflow_coverage(
    retrieved: list[str],
    workflow_steps: list[str],
) -> float:
    """Fraction of workflow steps covered by retrieved tools.

    Parameters
    ----------
    retrieved:
        List of retrieved tool names.
    workflow_steps:
        Ordered list of tool names in a workflow.

    Returns
    -------
    float
        Coverage value between 0.0 and 1.0.
    """
    if not workflow_steps:
        return 1.0
    retrieved_set = set(retrieved)
    covered = sum(1 for step in workflow_steps if step in retrieved_set)
    return covered / len(workflow_steps)
