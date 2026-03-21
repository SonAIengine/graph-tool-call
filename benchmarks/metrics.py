"""Retrieval evaluation metrics."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence


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


def ndcg_at_k(
    retrieved: list[str],
    relevant: set[str] | dict[str, int],
    k: int,
) -> float:
    """Normalized Discounted Cumulative Gain@K.

    Supports both binary relevance (set) and graded relevance (dict).

    Parameters
    ----------
    retrieved:
        Ordered list of retrieved tool names.
    relevant:
        Set of relevant tool names (binary: 1 if present), or
        dict mapping tool name → relevance grade (e.g. 3=required, 2=optional, 1=contextual).
    k:
        Number of top results to consider.

    Returns
    -------
    float
        NDCG value between 0.0 and 1.0.
    """
    if not relevant or k <= 0:
        return 0.0

    # Normalize to graded relevance dict
    if isinstance(relevant, set):
        grades: dict[str, int] = {name: 1 for name in relevant}
    else:
        grades = relevant

    top_k = retrieved[:k]

    # DCG: sum(rel_i / log2(i + 2)) for i in 0..k-1
    dcg = 0.0
    for i, name in enumerate(top_k):
        rel = float(grades.get(name, 0))
        dcg += rel / math.log2(i + 2)

    # Ideal DCG: sort grades descending, take top-k
    sorted_grades = sorted(grades.values(), reverse=True)[:k]
    idcg = sum(float(g) / math.log2(i + 2) for i, g in enumerate(sorted_grades))

    if idcg == 0:
        return 0.0
    return dcg / idcg


def mrr(retrieved: list[str], relevant: set[str]) -> float:
    """Mean Reciprocal Rank: 1/rank of the first relevant result.

    Parameters
    ----------
    retrieved:
        Ordered list of retrieved tool names.
    relevant:
        Set of relevant (ground-truth) tool names.

    Returns
    -------
    float
        1/rank of first relevant item, or 0.0 if none found.
    """
    for i, name in enumerate(retrieved):
        if name in relevant:
            return 1.0 / (i + 1)
    return 0.0


def average_precision(retrieved: list[str], relevant: set[str]) -> float:
    """Average Precision: average of precision@k at each relevant hit.

    Parameters
    ----------
    retrieved:
        Ordered list of retrieved tool names.
    relevant:
        Set of relevant (ground-truth) tool names.

    Returns
    -------
    float
        AP value between 0.0 and 1.0.
    """
    if not relevant:
        return 1.0
    hits = 0
    sum_precision = 0.0
    for i, name in enumerate(retrieved):
        if name in relevant:
            hits += 1
            sum_precision += hits / (i + 1)
    if hits == 0:
        return 0.0
    return sum_precision / len(relevant)


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


# --- Statistical metrics ---


def hit_rate(retrieved: list[str], relevant: set[str], k: int) -> float:
    """HitRate@K: 1.0 if at least one relevant item in top-K, else 0.0."""
    if not relevant or k <= 0:
        return 0.0
    return 1.0 if any(name in relevant for name in retrieved[:k]) else 0.0


def miss_rate(recall_values: Sequence[float]) -> float:
    """Fraction of queries with recall=0 (complete miss).

    Parameters
    ----------
    recall_values:
        Per-query recall values.

    Returns
    -------
    float
        Fraction of queries where recall is exactly 0.0.
    """
    if not recall_values:
        return 0.0
    return sum(1 for r in recall_values if r == 0.0) / len(recall_values)


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))


def confidence_interval(
    values: Sequence[float],
    confidence: float = 0.95,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> tuple[float, float]:
    """Bootstrap confidence interval for the mean.

    Parameters
    ----------
    values:
        Sample values.
    confidence:
        Confidence level (default: 0.95).
    n_bootstrap:
        Number of bootstrap resamples.
    seed:
        Random seed for reproducibility.

    Returns
    -------
    tuple[float, float]
        (lower, upper) bounds of the confidence interval.
    """
    if len(values) < 2:
        mean = values[0] if values else 0.0
        return (mean, mean)

    rng = random.Random(seed)
    n = len(values)
    values_list = list(values)
    means = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(values_list) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    alpha = 1 - confidence
    lo_idx = int(alpha / 2 * n_bootstrap)
    hi_idx = int((1 - alpha / 2) * n_bootstrap) - 1
    return (means[lo_idx], means[hi_idx])


def paired_t_test(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Paired two-sided t-test.

    Parameters
    ----------
    a, b:
        Paired samples (same length).

    Returns
    -------
    tuple[float, float]
        (t_statistic, p_value). p_value uses approximation for df > 1.
    """
    n = len(a)
    if n != len(b) or n < 2:
        return (0.0, 1.0)

    diffs = [ai - bi for ai, bi in zip(a, b)]
    mean_d = sum(diffs) / n
    var_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)
    if var_d == 0:
        # Zero variance: if mean_d != 0, difference is perfectly consistent → p=0
        return (
            float("inf") if mean_d > 0 else float("-inf") if mean_d < 0 else 0.0,
            0.0 if mean_d != 0 else 1.0,
        )

    se = math.sqrt(var_d / n)
    t_stat = mean_d / se
    # Approximate two-sided p-value using t-distribution (large sample approx)
    df = n - 1
    # Simple approximation: for df >= 30, use normal; else use crude t approx
    if df >= 30:
        # Normal approximation
        p = 2 * (1 - _normal_cdf(abs(t_stat)))
    else:
        # Approximation: p ≈ 2 * (1 - t_cdf(|t|, df))
        p = 2 * _t_survival(abs(t_stat), df)

    return (t_stat, min(p, 1.0))


def _normal_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _t_survival(t: float, df: int) -> float:
    """Approximate P(T > t) for t-distribution with df degrees of freedom."""
    # Use the approximation: t_df ≈ normal for large df
    # For smaller df, use a correction factor
    if df >= 100:
        return 1 - _normal_cdf(t)
    # Hill's approximation for moderate df
    a = df - 0.5
    z = a * math.log(1 + t * t / df) if t * t / df < 700 else 700 * a
    z = math.sqrt(z)
    return 1 - _normal_cdf(z)


def token_efficiency(accuracy: float, avg_tokens: float) -> float:
    """Token efficiency: accuracy per 1K tokens.

    Higher is better — achieving same accuracy with fewer tokens is more efficient.
    """
    if avg_tokens <= 0:
        return 0.0
    return accuracy / (avg_tokens / 1000)
