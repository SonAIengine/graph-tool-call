"""Zero-vector retrieval over a graphify-style ToolGraph.

Algorithm (mirrors graphify/serve.py):
  1. seed = top-5 of BM25(query)  (substring fallback if BM25 returns empty)
  2. weights = INTENT_RELATION_WEIGHTS[dominant_intent] or DEFAULT
  3. score = rel_weight[rel] * CONF_FACTOR[confidence] * decay(depth)
     CONF_FACTOR = {EXTRACTED: 1.0, INFERRED: 0.7, AMBIGUOUS: 0.4, None: 0.5}
     decay(d)   = 1 / (0.5*d + 1)
  4. BFS from seeds, depth=2, accumulate max score per neighbour
  5. history-aware demote (used tools * 0.6)
  6. render_subgraph_text(top_k nodes + edges, token_budget)

Why this works without embeddings:
  - The graph carries the semantic signal (CRUD chains, $ref data flow,
    cross-resource matches) — once a relationship is in the graph, traversal
    finds it.
  - Confidence labels let the score down-weight guesses without dropping them;
    AMBIGUOUS edges still appear, just behind EXTRACTED ones.
  - Token-budgeted rendering means an LLM gets a compact, structured context
    (not a list of tool JSON blobs) and can decide chains via the EDGE lines.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import (
    DEFAULT_RELATION_WEIGHTS,
    INTENT_RELATION_WEIGHTS,
    NodeType,
    RelationType,
)
from graph_tool_call.retrieval.intent import classify_intent
from graph_tool_call.tool_graph import ToolGraph

# Score multiplier per confidence bucket. EXTRACTED edges are deterministic
# (path/CRUD/$ref) and trusted at 1.0; INFERRED is heuristic but still
# high-confidence; AMBIGUOUS gets a strong penalty so it's surfaced for
# review without dominating EXTRACTED chains.
#
# Edges added by callers without a confidence attr (e.g. legacy code paths)
# get the same weight as the no-bucket fallback (0.5) — neither rewarded
# nor heavily penalised.
CONF_FACTOR: dict[str | None, float] = {
    "EXTRACTED": 1.0,
    "INFERRED": 0.7,
    "AMBIGUOUS": 0.4,
    None: 0.5,
}

_DEFAULT_DEPTH = 2
_DEFAULT_TOP_K = 10
_DEFAULT_BUDGET = 2000
_HISTORY_DEMOTE = 0.6


# ---------------------------------------------------------------------------
# Seed selection
# ---------------------------------------------------------------------------


def _strip_diacritics(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _substring_seeds(
    tools: dict[str, ToolSchema],
    query: str,
    *,
    limit: int = 5,
) -> list[tuple[str, float]]:
    """Substring fallback when BM25 returns no hits (very short or non-Latin queries)."""
    q = _strip_diacritics(query).lower()
    terms = [t for t in re.split(r"[\s_\-/.,;:!?()]+", q) if t and len(t) > 1]
    scored: list[tuple[str, float]] = []
    for name, tool in tools.items():
        nname = _strip_diacritics(name).lower()
        ndesc = _strip_diacritics(tool.description or "").lower()
        score = sum(1.0 for t in terms if t in nname) + 0.5 * sum(1.0 for t in terms if t in ndesc)
        if score > 0:
            scored.append((name, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def _bm25_seeds(tg: ToolGraph, query: str, *, limit: int = 5) -> list[tuple[str, float]]:
    """Top-N BM25 hits as seeds. Uses the engine's BM25 index, lazy-built once."""
    try:
        engine = tg._get_retrieval_engine()  # noqa: SLF001
        bm25 = engine._get_bm25()  # noqa: SLF001
    except Exception:
        return []
    scores = bm25.score(query) or {}
    if not scores:
        return []
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(name, score) for name, score in ranked[:limit]]


def _select_seeds(
    tg: ToolGraph,
    query: str,
    *,
    limit: int = 5,
) -> list[tuple[str, float]]:
    seeds = _bm25_seeds(tg, query, limit=limit)
    if seeds:
        return seeds
    return _substring_seeds(tg.tools, query, limit=limit)


# ---------------------------------------------------------------------------
# BFS traversal
# ---------------------------------------------------------------------------


def _intent_weights(query: str) -> tuple[dict[str, float], str]:
    """Pick relation weights based on dominant query intent.

    Returns (weights_map, dominant_label) where label is one of
    'read'/'write'/'delete'/'neutral'.
    """
    intent = classify_intent(query)
    if intent.is_neutral:
        return DEFAULT_RELATION_WEIGHTS, "neutral"
    by_dim = {
        "read": intent.read_intent,
        "write": intent.write_intent,
        "delete": intent.delete_intent,
    }
    dominant = max(by_dim, key=lambda k: by_dim[k])
    if by_dim[dominant] < 0.5:
        return DEFAULT_RELATION_WEIGHTS, "neutral"
    weights = INTENT_RELATION_WEIGHTS.get(dominant, DEFAULT_RELATION_WEIGHTS)
    return weights, dominant


def _normalize_relation_key(rel: Any) -> Any:
    """Relation weights are keyed by RelationType. Normalize string attrs to enum."""
    if isinstance(rel, RelationType):
        return rel
    if isinstance(rel, str):
        try:
            return RelationType(rel)
        except ValueError:
            return rel
    return rel


def _bfs_from_seeds(
    graph: GraphEngine,
    seed_scores: list[tuple[str, float]],
    *,
    depth: int,
    rel_weights: dict[str, float],
) -> tuple[dict[str, float], list[tuple[str, str]]]:
    """Confidence-weighted BFS. Returns (scores, edges_visited).

    Score policy:
      seeds:        normalized BM25 score (top seed = 1.0, others scaled)
      neighbour at depth d via edge of weight w and confidence c:
        score(neighbour) = max(prev,  parent_score * w * CONF_FACTOR[c] * 1/(0.5*d + 1))

    Why normalize seeds: if all 5 BM25 hits got flat 1.0, top-K shows them in
    arbitrary order with identical scores and BFS-found neighbours never compete.
    Scaling by ``score / max_seed_score`` preserves BM25's relative ranking and
    lets a strongly-matching seed lift its 1-hop neighbours above weakly-matching
    sibling seeds.

    Tools nodes are scored; CATEGORY/DOMAIN nodes are passthrough so we can
    reach sibling tools on the next hop.
    """
    if not seed_scores:
        return {}, []

    max_seed = max((s for _, s in seed_scores), default=1.0) or 1.0
    scores: dict[str, float] = {n: s / max_seed for n, s in seed_scores if graph.has_node(n)}
    visited: set[str] = set(scores)
    frontier: list[str] = list(scores)
    edges_visited: list[tuple[str, str]] = []

    for d in range(1, depth + 1):
        decay = 1.0 / (0.5 * d + 1)
        next_frontier: list[str] = []
        for node in frontier:
            parent_score = scores.get(node, 0.0)
            try:
                edges = graph.get_edges_from(node, direction="both")
            except (KeyError, ValueError):
                continue
            for src, tgt, attrs in edges:
                neighbour = tgt if src == node else src
                if neighbour in visited:
                    continue
                neighbour_attrs = graph.get_node_attrs(neighbour)
                neighbour_type = neighbour_attrs.get("node_type")

                rel_key = _normalize_relation_key(attrs.get("relation"))
                rel_w = rel_weights.get(rel_key, 0.3)
                conf = attrs.get("confidence")
                conf_factor = CONF_FACTOR.get(conf, CONF_FACTOR[None])

                if neighbour_type == NodeType.TOOL:
                    # Propagate parent's score so a high-BM25 seed lifts its
                    # neighbours more than a low-BM25 seed does. This is what
                    # makes the ranking actually informative — without
                    # parent_score multiplication every BFS-discovered tool
                    # would inherit the same fixed weight.
                    score = parent_score * rel_w * conf_factor * decay
                    scores[neighbour] = max(scores.get(neighbour, 0.0), score)
                    edges_visited.append((src, tgt))
                    next_frontier.append(neighbour)
                    visited.add(neighbour)
                elif neighbour_type in (NodeType.CATEGORY, NodeType.DOMAIN):
                    # Passthrough — visit but don't score; lets BFS reach
                    # sibling tools via CATEGORY hubs without inflating scores.
                    next_frontier.append(neighbour)
                    visited.add(neighbour)
        frontier = next_frontier
        if not frontier:
            break

    return scores, edges_visited


# ---------------------------------------------------------------------------
# Subgraph rendering
# ---------------------------------------------------------------------------


def _node_line(name: str, tool: ToolSchema | None, attrs: dict) -> str:
    """One NODE line for the subgraph text rendering."""
    md = (tool.metadata if tool else {}) or {}
    method = str(md.get("method") or "").upper()
    path = str(md.get("path") or "")
    src_label = str(md.get("source_label") or "")
    community = attrs.get("community")
    parts = [name]
    if method or path:
        parts.append(f"[{method} {path}]".strip())
    if src_label:
        parts.append(f"[source={src_label}]")
    if community is not None:
        parts.append(f"[community={community}]")
    return "NODE " + " ".join(p for p in parts if p)


def _edge_line(
    u: str,
    v: str,
    attrs: dict,
) -> str:
    """One EDGE line. confidence in [], evidence in (...)."""
    rel = attrs.get("relation")
    rel_str = rel.value if hasattr(rel, "value") else str(rel)
    conf = attrs.get("confidence", "")
    conf_str = f" [{conf}]" if conf else ""
    line = f"EDGE {u} --{rel_str}{conf_str}--> {v}"
    evidence = attrs.get("evidence")
    if evidence:
        line += f"   ({evidence})"
    return line


def render_subgraph_text(
    tg: ToolGraph,
    nodes: set[str] | list[str],
    edges: list[tuple[str, str]] | None = None,
    *,
    token_budget: int = _DEFAULT_BUDGET,
    sort_by_score: dict[str, float] | None = None,
) -> str:
    """Render the matched subgraph as ``NODE ...`` / ``EDGE ...`` lines.

    Approx 3 chars per token is the budget conversion. When the rendering
    overflows the budget, the tail is cut and a ``... (truncated)`` line
    is appended.

    sort_by_score: if provided, NODE lines are emitted in descending score
    order so the LLM sees the most relevant tools first.

    edges: optional hint listing edges visited during BFS — purely for
    ordering. Whether or not this is supplied, ALL graph edges between any
    pair of chosen nodes are emitted so the LLM sees the full local
    structure (matching graphify's behaviour).
    """
    char_budget = token_budget * 3
    node_set: set[str] = set(nodes)

    # Order nodes: by retrieval score (desc) if known, else by name.
    if sort_by_score:
        node_order = sorted(node_set, key=lambda n: (-sort_by_score.get(n, 0.0), n))
    else:
        node_order = sorted(node_set)

    lines: list[str] = []
    for n in node_order:
        if not tg.graph.has_node(n):
            continue
        attrs = tg.graph.get_node_attrs(n)
        tool = tg.tools.get(n)
        lines.append(_node_line(n, tool, attrs))

    # Walk all graph edges between chosen nodes (not just BFS visited ones)
    # so the LLM gets the complete local structure. BFS-visited edges naturally
    # come first when we sort, ensuring no surprise gaps.
    seen_edges: set[tuple[str, str]] = set()
    edge_lines: list[str] = []
    for u in node_order:
        if not tg.graph.has_node(u):
            continue
        try:
            outgoing = tg.graph.get_edges_from(u, direction="out")
        except (KeyError, ValueError):
            continue
        for src, tgt, attrs in outgoing:
            if tgt not in node_set:
                continue
            key = (src, tgt)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edge_lines.append(_edge_line(src, tgt, attrs))

    lines.extend(edge_lines)

    output = "\n".join(lines)
    if len(output) > char_budget:
        # Cut at the last newline that fits, then append a marker. Keep the
        # marker even if it pushes us slightly over the char budget — the
        # token budget is a soft cap.
        cut = output[:char_budget].rsplit("\n", 1)[0]
        output = cut + f"\n... (truncated to ~{token_budget} token budget)"
    return output


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def retrieve_graphify(
    tg: ToolGraph,
    query: str,
    *,
    top_k: int = _DEFAULT_TOP_K,
    depth: int = _DEFAULT_DEPTH,
    token_budget: int = _DEFAULT_BUDGET,
    history: list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve tools for a natural-language query using graph traversal only.

    Parameters
    ----------
    tg:
        A graphify-style ``ToolGraph``. Edges should carry ``confidence``
        attrs (EXTRACTED/INFERRED/AMBIGUOUS); edges without one get the
        neutral 0.5 multiplier.
    query:
        Natural-language search.
    top_k:
        Maximum tools in the result set (and the rendered subgraph).
    depth:
        BFS depth from seeds. 2 is graphify's default and works for most
        workflow chains (createX -> getX -> doSomethingWithX).
    token_budget:
        Char-budget for the rendered text (~3 chars/token).
    history:
        Tool names already called in this session — they are demoted (×0.6)
        to encourage progress through a workflow rather than re-suggesting.

    Returns
    -------
    dict with keys:
      - results:        list of {name, score, tool: {...}} sorted desc.
      - subgraph_text:  the LLM-ready NODE/EDGE rendering.
      - intent:         {dominant: 'read'|'write'|'delete'|'neutral', read, write, delete}
      - stats:          {seeds: [...], visited_nodes: int, visited_edges: int}

    Note: prerequisite chain construction (e.g. listOrders → getOrder → cancelOrder)
    is NOT this function's job — it lives in Stage 2 ``synthesize_plan`` which
    consumes the graph this module produces. retrieve_graphify only finds the
    primary candidates; chain assembly is downstream.
    """
    if not query or not tg.tools:
        return {
            "results": [],
            "subgraph_text": "",
            "intent": {"dominant": "neutral", "read": 0.0, "write": 0.0, "delete": 0.0},
            "stats": {"seeds": [], "visited_nodes": 0, "visited_edges": 0},
        }

    # 1) Seeds
    seeds_with_scores = _select_seeds(tg, query, limit=5)
    seed_names = [s for s, _ in seeds_with_scores]

    if not seed_names:
        return {
            "results": [],
            "subgraph_text": "",
            "intent": {"dominant": "neutral", "read": 0.0, "write": 0.0, "delete": 0.0},
            "stats": {"seeds": [], "visited_nodes": 0, "visited_edges": 0},
        }

    # 2) Intent → relation weight map
    rel_weights, dominant = _intent_weights(query)
    from graph_tool_call.retrieval.intent import classify_intent  # noqa: I001 (re-import OK)

    intent_obj = classify_intent(query)

    # 3) BFS — pass full (name, score) pairs so seed scores reflect BM25 ranking
    scores, edges_visited = _bfs_from_seeds(
        tg.graph,
        seeds_with_scores,
        depth=depth,
        rel_weights=rel_weights,
    )

    # 4) History demote
    if history:
        for h in history:
            if h in scores:
                scores[h] *= _HISTORY_DEMOTE

    # 5) Filter to TOOL nodes only and rank
    tool_scores: dict[str, float] = {n: s for n, s in scores.items() if n in tg.tools}
    ranked = sorted(tool_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    chosen_names: set[str] = {n for n, _ in ranked}

    # 6) Render
    subgraph_text = render_subgraph_text(
        tg,
        chosen_names,
        edges_visited,
        token_budget=token_budget,
        sort_by_score=tool_scores,
    )

    results = [
        {
            "name": name,
            "score": round(score, 4),
            "tool": tg.tools[name].to_dict() if name in tg.tools else None,
        }
        for name, score in ranked
    ]

    return {
        "results": results,
        "subgraph_text": subgraph_text,
        "intent": {
            "dominant": dominant,
            "read": round(intent_obj.read_intent, 3),
            "write": round(intent_obj.write_intent, 3),
            "delete": round(intent_obj.delete_intent, 3),
        },
        "stats": {
            "seeds": seed_names,
            "visited_nodes": len(scores),
            "visited_edges": len(edges_visited),
        },
    }
