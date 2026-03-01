"""5-Stage deduplication pipeline for tool schemas."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from graph_tool_call.core.tool import ToolSchema


class MergeStrategy(str, Enum):
    """Strategy for merging duplicate tools."""

    KEEP_FIRST = "keep_first"
    KEEP_BEST = "keep_best"
    CREATE_ALIAS = "create_alias"


@dataclass
class DuplicatePair:
    """A detected duplicate pair with similarity info."""

    tool_a: str
    tool_b: str
    score: float
    stage: int  # which stage detected this pair (1-5)


# ---------------------------------------------------------------------------
# Stage 1: Exact SHA256 hash
# ---------------------------------------------------------------------------


def _canonical_repr(tool: ToolSchema) -> str:
    """Create a canonical string representation for hashing."""
    params = sorted(
        [{"name": p.name, "type": p.type, "required": p.required} for p in tool.parameters],
        key=lambda x: x["name"],
    )
    canonical = {"name": tool.name.lower(), "parameters": params}
    return json.dumps(canonical, sort_keys=True, ensure_ascii=True)


def _stage1_exact_hash(tools: dict[str, ToolSchema]) -> list[DuplicatePair]:
    """Stage 1: SHA256 exact hash on canonical(name + params). O(n)."""
    hashes: dict[str, list[str]] = {}
    for name, tool in tools.items():
        h = hashlib.sha256(_canonical_repr(tool).encode()).hexdigest()
        hashes.setdefault(h, []).append(name)

    pairs: list[DuplicatePair] = []
    for names in hashes.values():
        if len(names) < 2:
            continue
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                pairs.append(DuplicatePair(tool_a=a, tool_b=b, score=1.0, stage=1))
    return pairs


# ---------------------------------------------------------------------------
# Stage 2: RapidFuzz name similarity (optional)
# ---------------------------------------------------------------------------


def _stage2_name_fuzzy(tools: dict[str, ToolSchema], threshold: float) -> list[DuplicatePair]:
    """Stage 2: Name fuzzy matching with RapidFuzz. O(n^2) but fast (C++)."""
    try:
        from rapidfuzz.distance import JaroWinkler
        from rapidfuzz.fuzz import token_sort_ratio
    except ImportError:
        return []  # skip if rapidfuzz not installed

    names = list(tools.keys())
    pairs: list[DuplicatePair] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            jw = JaroWinkler.similarity(a.lower(), b.lower())
            tsr = token_sort_ratio(a.lower(), b.lower()) / 100.0
            score = max(jw, tsr)
            if score >= threshold:
                pairs.append(DuplicatePair(tool_a=a, tool_b=b, score=score, stage=2))
    return pairs


# ---------------------------------------------------------------------------
# Stage 3: Parameter key Jaccard + type compatibility
# ---------------------------------------------------------------------------


def _param_jaccard(tool_a: ToolSchema, tool_b: ToolSchema) -> float:
    """Compute Jaccard similarity of parameter names with type compatibility bonus."""
    keys_a = {p.name for p in tool_a.parameters}
    keys_b = {p.name for p in tool_b.parameters}

    if not keys_a and not keys_b:
        return 1.0  # both have no params
    if not keys_a or not keys_b:
        return 0.0

    intersection = keys_a & keys_b
    union = keys_a | keys_b
    jaccard = len(intersection) / len(union)

    # Type compatibility bonus: for shared params, check type match
    if intersection:
        types_a = {p.name: p.type for p in tool_a.parameters}
        types_b = {p.name: p.type for p in tool_b.parameters}
        type_matches = sum(1 for k in intersection if types_a.get(k) == types_b.get(k))
        type_ratio = type_matches / len(intersection)
        # Blend: 70% jaccard + 30% type compatibility
        return 0.7 * jaccard + 0.3 * type_ratio

    return jaccard


def _stage3_schema_structural(
    tools: dict[str, ToolSchema], threshold: float
) -> list[DuplicatePair]:
    """Stage 3: Parameter key Jaccard + type compatibility. O(n^2 * params)."""
    names = list(tools.keys())
    pairs: list[DuplicatePair] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            score = _param_jaccard(tools[a], tools[b])
            if score >= threshold:
                pairs.append(DuplicatePair(tool_a=a, tool_b=b, score=score, stage=3))
    return pairs


# ---------------------------------------------------------------------------
# Stage 4: Embedding cosine similarity (optional)
# ---------------------------------------------------------------------------


def _stage4_embedding(
    tools: dict[str, ToolSchema],
    threshold: float,
    embedding_index: Any = None,
) -> list[DuplicatePair]:
    """Stage 4: Embedding cosine similarity. Optional sentence-transformers."""
    if embedding_index is None or embedding_index.size == 0:
        return []

    try:
        import numpy as np
    except ImportError:
        return []

    names = list(tools.keys())
    pairs: list[DuplicatePair] = []

    # Collect embeddings for tools that have them
    embeddings: dict[str, Any] = {}
    for name in names:
        if name in embedding_index._embeddings:
            embeddings[name] = np.array(embedding_index._embeddings[name], dtype=np.float32)

    emb_names = list(embeddings.keys())
    for i, a in enumerate(emb_names):
        va = embeddings[a]
        na = np.linalg.norm(va)
        if na == 0:
            continue
        va_n = va / na
        for b in emb_names[i + 1 :]:
            vb = embeddings[b]
            nb = np.linalg.norm(vb)
            if nb == 0:
                continue
            vb_n = vb / nb
            sim = float(np.dot(va_n, vb_n))
            if sim >= threshold:
                pairs.append(DuplicatePair(tool_a=a, tool_b=b, score=sim, stage=4))
    return pairs


# ---------------------------------------------------------------------------
# Stage 5: Composite score
# ---------------------------------------------------------------------------


def _stage5_composite(
    tools: dict[str, ToolSchema],
    threshold: float,
    stage2_scores: dict[tuple[str, str], float],
    stage3_scores: dict[tuple[str, str], float],
    stage4_scores: dict[tuple[str, str], float],
) -> list[DuplicatePair]:
    """Stage 5: Composite (0.2*name + 0.3*schema + 0.5*semantic)."""
    all_pair_keys: set[tuple[str, str]] = set()
    all_pair_keys.update(stage2_scores.keys())
    all_pair_keys.update(stage3_scores.keys())
    all_pair_keys.update(stage4_scores.keys())

    has_stage2 = bool(stage2_scores)
    has_stage4 = bool(stage4_scores)

    pairs: list[DuplicatePair] = []
    for key in all_pair_keys:
        name_score = stage2_scores.get(key, 0.0)
        schema_score = stage3_scores.get(key, 0.0)
        semantic_score = stage4_scores.get(key, 0.0)

        # Weight assignment depends on available stages
        if has_stage2 and has_stage4:
            # All stages available: 0.2*name + 0.3*schema + 0.5*semantic
            composite = 0.2 * name_score + 0.3 * schema_score + 0.5 * semantic_score
        elif has_stage2 and not has_stage4:
            # No embedding: redistribute semantic weight to schema
            # 0.3*name + 0.7*schema
            composite = 0.3 * name_score + 0.7 * schema_score
        elif has_stage4 and not has_stage2:
            # No rapidfuzz: redistribute name weight to schema
            # 0.4*schema + 0.6*semantic
            composite = 0.4 * schema_score + 0.6 * semantic_score
        else:
            # Only schema available
            composite = schema_score

        if composite >= threshold:
            pairs.append(DuplicatePair(tool_a=key[0], tool_b=key[1], score=composite, stage=5))
    return pairs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_duplicates(
    tools: dict[str, ToolSchema],
    *,
    threshold: float = 0.85,
    embedding_index: Any = None,
) -> list[DuplicatePair]:
    """Find duplicate tool pairs using a 5-stage pipeline.

    Parameters
    ----------
    tools:
        Dict of tool_name → ToolSchema.
    threshold:
        Minimum similarity score (0.0-1.0) for duplicate detection.
    embedding_index:
        Optional EmbeddingIndex for Stage 4 semantic similarity.

    Returns
    -------
    list[DuplicatePair]
        Detected duplicate pairs, sorted by score descending.
        De-duplicated: each tool pair appears at most once (highest stage wins).
    """
    if len(tools) < 2:
        return []

    # Stage 1: exact hash (always run, threshold=1.0)
    stage1 = _stage1_exact_hash(tools)

    # Stage 2: name fuzzy (optional rapidfuzz)
    stage2 = _stage2_name_fuzzy(tools, threshold)
    stage2_scores = {(_normalize_key(p.tool_a, p.tool_b)): p.score for p in stage2}

    # Stage 3: schema structural
    stage3 = _stage3_schema_structural(tools, threshold)
    stage3_scores = {(_normalize_key(p.tool_a, p.tool_b)): p.score for p in stage3}

    # Stage 4: embedding cosine (optional)
    stage4 = _stage4_embedding(tools, threshold, embedding_index)
    stage4_scores = {(_normalize_key(p.tool_a, p.tool_b)): p.score for p in stage4}

    # Stage 5: composite
    stage5 = _stage5_composite(tools, threshold, stage2_scores, stage3_scores, stage4_scores)

    # Merge all stages: for each pair, keep the highest-stage result
    best: dict[tuple[str, str], DuplicatePair] = {}
    for pair in stage1 + stage2 + stage3 + stage4 + stage5:
        key = _normalize_key(pair.tool_a, pair.tool_b)
        existing = best.get(key)
        if existing is None or pair.stage > existing.stage:
            best[key] = DuplicatePair(
                tool_a=key[0],
                tool_b=key[1],
                score=pair.score,
                stage=pair.stage,
            )

    result = list(best.values())
    result.sort(key=lambda p: p.score, reverse=True)
    return result


def _normalize_key(a: str, b: str) -> tuple[str, str]:
    """Normalize pair key so (a, b) == (b, a)."""
    return (min(a, b), max(a, b))


def merge_duplicates(
    tools: dict[str, ToolSchema],
    pairs: list[DuplicatePair],
    strategy: str | MergeStrategy = MergeStrategy.KEEP_BEST,
) -> dict[str, str]:
    """Merge duplicate tools according to the given strategy.

    Parameters
    ----------
    tools:
        Dict of tool_name → ToolSchema (will NOT be mutated).
    pairs:
        Duplicate pairs from ``find_duplicates()``.
    strategy:
        Merge strategy: "keep_first", "keep_best", or "create_alias".

    Returns
    -------
    dict[str, str]
        Mapping of removed_name → kept_name (canonical).
    """
    if isinstance(strategy, str):
        strategy = MergeStrategy(strategy)

    merged: dict[str, str] = {}
    for pair in pairs:
        if pair.tool_a in merged or pair.tool_b in merged:
            continue  # already merged one of them

        a, b = pair.tool_a, pair.tool_b
        tool_a = tools.get(a)
        tool_b = tools.get(b)
        if tool_a is None or tool_b is None:
            continue

        if strategy == MergeStrategy.KEEP_FIRST:
            # Keep the one that sorts first (deterministic)
            keep, remove = (a, b) if a <= b else (b, a)

        elif strategy == MergeStrategy.KEEP_BEST:
            score_a = _quality_score(tool_a)
            score_b = _quality_score(tool_b)
            if score_a >= score_b:
                keep, remove = a, b
            else:
                keep, remove = b, a

        elif strategy == MergeStrategy.CREATE_ALIAS:
            # Keep both but mark the second as alias
            keep, remove = (a, b) if a <= b else (b, a)

        else:
            keep, remove = a, b

        merged[remove] = keep

    return merged


def _quality_score(tool: ToolSchema) -> float:
    """Score tool quality based on description length and parameter documentation."""
    score = 0.0
    # Description length (normalized)
    score += min(len(tool.description) / 200.0, 1.0) * 0.5

    # Parameter documentation completeness
    if tool.parameters:
        documented = sum(1 for p in tool.parameters if p.description)
        score += (documented / len(tool.parameters)) * 0.5
    else:
        score += 0.25  # neutral for no params

    return score
