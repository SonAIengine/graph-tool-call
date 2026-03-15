"""Automatic ontology construction: Auto mode and LLM-Auto mode (Phase 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graph_tool_call.ontology.builder import OntologyBuilder


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def auto_organize(
    builder: OntologyBuilder,
    tools: list[Any],
    llm: Any = None,
) -> None:
    """Automatically organize tools into categories and infer relations.

    Mode 1 (Auto): Always runs. Uses tags, domain, and embedding clustering.
    Mode 2 (LLM-Auto): If ``llm`` is provided, runs Auto first then enhances
    with LLM-inferred relations and category suggestions.

    Parameters
    ----------
    builder:
        The OntologyBuilder to populate.
    tools:
        List of ToolSchema instances.
    llm:
        Optional OntologyLLM instance for LLM-Auto mode.
    """
    # --- Auto mode (always) ---
    _auto_categorize_by_tags(builder, tools)
    _auto_categorize_by_domain(builder, tools)
    _auto_cluster_by_embedding(builder, tools)

    # --- LLM-Auto mode (if LLM provided) ---
    if llm is not None:
        _llm_auto_organize(builder, tools, llm)


# ---------------------------------------------------------------------------
# Auto mode: Tag-based categorization
# ---------------------------------------------------------------------------


def _auto_categorize_by_tags(builder: OntologyBuilder, tools: list[Any]) -> None:
    """Create categories from tool tags and assign tools to them."""
    for tool in tools:
        if not tool.tags:
            continue
        for tag in tool.tags:
            tag_lower = tag.lower().strip()
            if not tag_lower:
                continue
            if not builder._graph.has_node(tag_lower):
                builder.add_category(tag_lower)
            try:
                builder.assign_category(tool.name, tag_lower)
            except (KeyError, ValueError):
                pass


# ---------------------------------------------------------------------------
# Auto mode: Domain-based categorization
# ---------------------------------------------------------------------------


def _auto_categorize_by_domain(builder: OntologyBuilder, tools: list[Any]) -> None:
    """Create categories from tool domains."""
    for tool in tools:
        if not tool.domain:
            continue
        domain = tool.domain.lower().strip()
        if not domain:
            continue
        if not builder._graph.has_node(domain):
            builder.add_category(domain)
        try:
            builder.assign_category(tool.name, domain)
        except (KeyError, ValueError):
            pass


# ---------------------------------------------------------------------------
# Auto mode: Embedding-based clustering (optional)
# ---------------------------------------------------------------------------


def _auto_cluster_by_embedding(builder: OntologyBuilder, tools: list[Any]) -> None:
    """Cluster tools by embedding similarity and create categories.

    Uses numpy-only agglomerative clustering (no scikit-learn dependency).
    Skips silently if numpy or embeddings are not available.
    """
    if len(tools) < 3:
        return

    try:
        import numpy as np
    except ImportError:
        return

    # Try to build embeddings
    try:
        from graph_tool_call.retrieval.embedding import EmbeddingIndex

        idx = EmbeddingIndex(model_name="all-MiniLM-L6-v2")
        tool_dict = {t.name: t for t in tools}
        idx.build_from_tools(tool_dict)
    except (ImportError, Exception):
        return

    if idx.size < 3:
        return

    # Build embedding matrix
    names = list(idx._embeddings.keys())
    matrix = np.array([idx._embeddings[n] for n in names], dtype=np.float32)

    # Normalize
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = matrix / norms

    # Simple agglomerative clustering via cosine similarity
    n = len(names)
    n_clusters = max(2, n // 5)  # auto-determine cluster count
    n_clusters = min(n_clusters, n)

    # Assign clusters by similarity to centroid seeds
    # Pick n_clusters seeds spread across the tool list (deterministic)
    # Sort names first to ensure consistent ordering regardless of dict iteration
    sorted_indices = np.argsort(names)
    step = max(1, n // n_clusters)
    seed_indices = sorted_indices[::step][:n_clusters].tolist()
    centroids = matrix[seed_indices].copy()

    # K-means-style assignment (5 iterations for better convergence)
    labels = np.zeros(n, dtype=int)
    for _ in range(5):
        # Assign
        sims = matrix @ centroids.T  # (n, k)
        labels = np.argmax(sims, axis=1)
        # Update centroids
        for k in range(n_clusters):
            mask = labels == k
            if mask.any():
                centroids[k] = matrix[mask].mean(axis=0)
                c_norm = np.linalg.norm(centroids[k])
                if c_norm > 0:
                    centroids[k] /= c_norm

    # Create cluster categories
    cluster_tools: dict[int, list[str]] = {}
    for i, label in enumerate(labels):
        cluster_tools.setdefault(int(label), []).append(names[i])

    for cluster_id, tool_names in cluster_tools.items():
        if len(tool_names) < 2:
            continue
        # Name the category from common tokens
        cat_name = _derive_cluster_name(tool_names, tools)
        if not cat_name:
            cat_name = f"cluster_{cluster_id}"

        if not builder._graph.has_node(cat_name):
            builder.add_category(cat_name)
        for tname in tool_names:
            try:
                builder.assign_category(tname, cat_name)
            except (KeyError, ValueError):
                pass


def _derive_cluster_name(tool_names: list[str], tools: list[Any]) -> str:
    """Derive a category name from common tokens in tool names."""
    import re

    all_tokens: list[list[str]] = []
    for name in tool_names:
        # camelCase/snake_case split
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
        spaced = re.sub(r"[_\-]+", " ", spaced)
        tokens = [t.lower() for t in spaced.split() if t]
        # Remove common verbs
        tokens = [
            t
            for t in tokens
            if t
            not in {
                "get",
                "set",
                "create",
                "update",
                "delete",
                "list",
                "find",
                "add",
                "remove",
            }
        ]
        all_tokens.append(tokens)

    if not all_tokens:
        return ""

    # Find most common token across all tools in cluster
    from collections import Counter

    counter: Counter[str] = Counter()
    for tokens in all_tokens:
        counter.update(set(tokens))

    if not counter:
        return ""

    # Pick the most common token that appears in at least half the tools
    threshold = max(2, len(tool_names) // 2)
    for token, count in counter.most_common():
        if count >= threshold and len(token) > 1:
            return token

    # Fallback: just use the most common token
    most_common = counter.most_common(1)
    if most_common and len(most_common[0][0]) > 1:
        return most_common[0][0]

    return ""


# ---------------------------------------------------------------------------
# LLM-Auto mode
# ---------------------------------------------------------------------------


def _llm_auto_organize(
    builder: OntologyBuilder,
    tools: list[Any],
    llm: Any,
) -> None:
    """Enhance ontology with LLM-inferred relations and categories."""
    from graph_tool_call.ontology.llm_provider import ToolSummary

    # Build tool summaries for LLM
    summaries = [
        ToolSummary(
            name=t.name,
            description=t.description,
            parameters=[p.name for p in t.parameters],
        )
        for t in tools
    ]

    tool_names = {t.name for t in tools}

    # Infer relations
    relations = llm.infer_relations(summaries, batch_size=50)
    for rel in relations:
        if rel.confidence < 0.85:
            continue
        if rel.source not in tool_names or rel.target not in tool_names:
            continue
        if rel.source == rel.target:
            continue
        builder.add_relation(rel.source, rel.target, rel.relation_type)

    # Suggest categories (pass existing to avoid duplicates)
    from graph_tool_call.ontology.schema import NodeType

    existing_cats = [
        n
        for n in builder._graph.nodes()
        if builder._graph.get_node_attrs(n).get("node_type") == NodeType.CATEGORY
    ]
    categories = llm.suggest_categories(summaries, existing_categories=existing_cats)
    for cat_name, cat_tools in categories.items():
        cat_name_clean = cat_name.lower().strip()
        if not cat_name_clean:
            continue
        if not builder._graph.has_node(cat_name_clean):
            builder.add_category(cat_name_clean)
        for tname in cat_tools:
            if tname in tool_names:
                try:
                    builder.assign_category(tname, cat_name_clean)
                except (KeyError, ValueError):
                    pass

    # NOTE: keyword enrichment and example_queries are intentionally omitted.
    # The calling LLM already handles query expansion at search time,
    # and adding keywords to tools pollutes BM25 IDF scores.
