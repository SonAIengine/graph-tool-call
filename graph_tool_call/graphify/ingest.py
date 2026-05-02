"""Deterministic ingest: ToolSchema list -> ToolGraph with confidence labels.

Pipeline (no LLM, no embeddings):
  1. ``detect_dependencies`` runs all four layers (path-hierarchy, CRUD,
     shared $ref, name/RPC/cross-resource) at threshold 0.0.
  2. Each ``DetectedRelation`` is bucketed by (layer, conf_score) into one of
     EXTRACTED / INFERRED / AMBIGUOUS / dropped.
  3. Edges are added to a fresh ``ToolGraph`` with the bucket as ``confidence``
     attr, plus ``conf_score`` / ``layer`` / ``evidence`` for transparency.
  4. ``edge_stats`` summarises bucket counts, per-relation counts, and the
     count of cross-source edges (different ``source_label`` on each end —
     the key signal that adding a new source linked into the existing graph).

For specs that use a lot of $ref pointers (typical of Swagger/OpenAPI 3.x
generators like SpringDoc), pass the raw spec dict to
``preserve_refs_for_detection`` BEFORE calling ``ingest_openapi_graphify`` so
``detect_dependencies._detect_shared_schemas`` can fire — without this step
the library's ``ingest_openapi`` resolves refs inline and the shared-schema
signal is lost. ``ingest_openapi_graphify`` accepts the raw spec directly via
``raw_spec=`` and runs preservation automatically.

This is the ONLY ingest path used by xgen-workflow. The legacy 14-stage
``RetrievalEngine`` plumbing in graph_tool_call.retrieval is left intact
for benchmark/example users but is not invoked from this module.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from graph_tool_call.analyze.dependency import (
    DetectedRelation,
    detect_dependencies,
)
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import Confidence, RelationType
from graph_tool_call.tool_graph import ToolGraph

# Thresholds — same numbers graphify uses for INFERRED vs AMBIGUOUS.
# EXTRACTED additionally requires layer == 1 (deterministic structural).
DEFAULT_CONF_EXTRACTED = 0.85
DEFAULT_CONF_INFERRED = 0.85
DEFAULT_CONF_AMBIGUOUS = 0.70


def bucket_confidence(
    layer: int,
    conf_score: float,
    *,
    extracted_min: float = DEFAULT_CONF_EXTRACTED,
    inferred_min: float = DEFAULT_CONF_INFERRED,
    ambiguous_min: float = DEFAULT_CONF_AMBIGUOUS,
) -> Confidence | None:
    """Bucket a (layer, conf_score) pair into a Confidence label.

    layer == 1 (path/CRUD/$ref) AND conf >= extracted_min  -> EXTRACTED
    conf >= inferred_min                                   -> INFERRED
    ambiguous_min <= conf < inferred_min                   -> AMBIGUOUS
    else                                                   -> None  (dropped)
    """
    if conf_score >= extracted_min and layer == 1:
        return Confidence.EXTRACTED
    if conf_score >= inferred_min:
        return Confidence.INFERRED
    if conf_score >= ambiguous_min:
        return Confidence.AMBIGUOUS
    return None


# ---------------------------------------------------------------------------
# $ref preservation
#
# Library ``ingest_openapi`` calls ``_resolve_refs`` which inlines every
# ``$ref`` pointer into its target schema. That makes life easier for runtime
# users (they get full schemas, no traversal needed) but it ERASES the signal
# ``_detect_shared_schemas`` relies on — that detector walks metadata looking
# for literal ``$ref`` strings to spot tools sharing a DTO.
#
# This helper rescans the raw spec, captures refs per operation BEFORE they're
# resolved, applies a frequency filter (drop common wrappers + singletons),
# and re-injects them as ``__refs__`` markers into each tool's metadata so
# ``_collect_refs`` finds them. Identical algorithm to xgen-workflow's
# ``swagger_tool_generator._collect_operation_refs``.
# ---------------------------------------------------------------------------

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _scan_refs(obj: Any) -> set[str]:
    """Recursively collect ``$ref`` pointer strings from a schema fragment."""
    refs: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "$ref" and isinstance(v, str):
                refs.add(v)
            else:
                refs.update(_scan_refs(v))
    elif isinstance(obj, list):
        for item in obj:
            refs.update(_scan_refs(item))
    return refs


def preserve_refs_for_detection(
    tools: list[ToolSchema],
    raw_spec: dict[str, Any],
    *,
    min_freq: int = 2,
    max_freq_ratio: float = 0.3,
) -> int:
    """Inject ``__refs__`` markers into tool metadata so shared-schema detection fires.

    Walk ``raw_spec`` BEFORE resolve, find $refs per operation, filter to the
    "domain DTO" sweet spot (>=min_freq references, <=max_freq_ratio of all ops),
    and re-inject them into each tool's ``metadata.response_schema.__refs__`` and
    ``metadata.request_body_refs``.

    Why filter:
      - Common wrappers like ``ApiResponse`` show up in nearly every operation;
        leaving them in produces a fully-connected COMPLEMENTARY graph (noise).
      - Singletons show up once and can't form edges anyway.

    Returns the number of tools whose metadata was updated. Mutates ``tools``
    in place.
    """
    paths = raw_spec.get("paths") or {}
    if not isinstance(paths, dict):
        return 0

    raw_per_op: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    freq: Counter[str] = Counter()

    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            req = _scan_refs(op.get("requestBody")) | _scan_refs(op.get("parameters"))
            resp = _scan_refs(op.get("responses"))
            if not (req or resp):
                continue
            raw_per_op[(method, path)] = (req, resp)
            for r in req | resp:
                freq[r] += 1

    if not raw_per_op:
        return 0

    total_ops = len(raw_per_op)
    ceiling = max(min_freq, int(total_ops * max_freq_ratio))

    def _useful(r: str) -> bool:
        return min_freq <= freq[r] <= ceiling

    op_refs: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for k, (req, resp) in raw_per_op.items():
        rq = sorted(r for r in req if _useful(r))
        rp = sorted(r for r in resp if _useful(r))
        if rq or rp:
            op_refs[k] = (rq, rp)

    updated = 0
    for tool in tools:
        md = tool.metadata or {}
        method = str(md.get("method") or "").lower()
        path = str(md.get("path") or "")
        refs = op_refs.get((method, path))
        if not refs:
            continue
        rq, rp = refs
        if rp:
            rs = md.get("response_schema") or {}
            if isinstance(rs, dict):
                rs = dict(rs)
                rs["__refs__"] = [{"$ref": r} for r in rp]
                md["response_schema"] = rs
        if rq:
            md["request_body_refs"] = [{"$ref": r} for r in rq]
        tool.metadata = md
        updated += 1

    return updated


# ---------------------------------------------------------------------------
# ai_metadata.pairs_well_with → graphify edge derivation
#
# ``ai_metadata`` is the source-of-truth (LLM Pass 2 fills it; the operator
# can hand-edit it via ToolGraphView). On every rebuild we derive the
# corresponding workflow edges into the graphify graph so ``_find_producer``
# can score them as a first-class signal — no separate lookup, no two-system
# sync drift. The frontend keeps reading ``ai_metadata.pairs_well_with``
# directly (single read path, no UI churn).
#
# Confidence mapping reflects the trust we place in each source:
#   PairHint.source == "manual" → EXTRACTED  (operator deliberately curated)
#   PairHint.source == "auto"   → INFERRED   (LLM Pass 2 high-confidence)
#   anything else / missing     → INFERRED   (legacy entries default safe)
#
# Layer is set to 2 because pair hints are not structural (path/$ref/CRUD)
# even when curated — they encode workflow semantics, which sits one level
# above structural inference in the graphify confidence model.
# ---------------------------------------------------------------------------


def _apply_pair_hints(
    tg: ToolGraph,
    schemas: list[ToolSchema],
) -> dict[str, int]:
    """Convert ``metadata.ai_metadata.pairs_well_with`` into graphify edges.

    Skips pairs whose target tool isn't in the current graph (cross-source
    enrichment can list pairs that haven't been ingested yet) and self-pairs.
    Skips when the same (src, tgt) pair already carries a structural relation
    from ``detect_dependencies`` UNLESS the new pair is operator-curated
    (``source="manual"``) — operator intent overrides automatic detection.
    """
    stats = {
        "manual": 0,
        "auto": 0,
        "skipped_target_missing": 0,
        "skipped_self": 0,
        "skipped_existing_structural": 0,
    }
    tool_names = set(tg.tools.keys())

    for s in schemas:
        ai = (s.metadata or {}).get("ai_metadata") or {}
        pairs = ai.get("pairs_well_with") or []
        if not isinstance(pairs, list):
            continue
        for p in pairs:
            if not isinstance(p, dict):
                continue
            target = str(p.get("tool") or "").strip()
            if not target:
                continue
            if target == s.name:
                stats["skipped_self"] += 1
                continue
            if target not in tool_names:
                stats["skipped_target_missing"] += 1
                continue

            source = str(p.get("source") or "auto").strip().lower()
            is_manual = source == "manual"
            confidence = Confidence.EXTRACTED if is_manual else Confidence.INFERRED
            reason = str(p.get("reason") or "")[:200]

            # Existing-edge policy: if detect_dependencies already produced
            # an edge here we keep it unless the operator is overriding.
            if tg.graph.has_edge(s.name, target):
                if not is_manual:
                    stats["skipped_existing_structural"] += 1
                    continue

            try:
                tg.add_relation(
                    s.name,
                    target,
                    RelationType.COMPLEMENTARY,
                    confidence=confidence,
                    layer=2,
                    evidence=f"pair[{source}]: {reason}" if reason else f"pair[{source}]",
                )
                stats["manual" if is_manual else "auto"] += 1
            except (KeyError, ValueError):
                stats["skipped_target_missing"] += 1

    return stats


def _source_label(schema: ToolSchema) -> str:
    """Return the source label that distinguishes which OpenAPI spec a tool came from.

    xgen-workflow tags each tool with ``metadata.source_label`` (e.g. "order",
    "claim"). When that's absent, fall back to the first path segment so
    cross-source detection still works for libraries used outside xgen.
    """
    md = schema.metadata or {}
    label = md.get("source_label")
    if label:
        return str(label)
    path = str(md.get("path") or "")
    segs = [s for s in path.split("/") if s and not s.startswith("{")]
    return segs[0] if segs else ""


def ingest_openapi_graphify(
    schemas: list[ToolSchema],
    *,
    extracted_min: float = DEFAULT_CONF_EXTRACTED,
    inferred_min: float = DEFAULT_CONF_INFERRED,
    ambiguous_min: float = DEFAULT_CONF_AMBIGUOUS,
    spec: dict[str, Any] | None = None,
    raw_spec: dict[str, Any] | None = None,
) -> tuple[ToolGraph, dict[str, Any]]:
    """Build a graphify-style ToolGraph from a list of ToolSchemas.

    Parameters
    ----------
    schemas:
        Tools to ingest. Pre-existing ``metadata.source_label`` enables
        cross-source edge tracking.
    extracted_min / inferred_min / ambiguous_min:
        Confidence bucket thresholds (see ``bucket_confidence``).
    spec:
        Optional normalized spec dict, forwarded to ``detect_dependencies``.
        Currently unused by the detector but kept for forward compat.
    raw_spec:
        Optional ORIGINAL OpenAPI/Swagger spec dict (BEFORE $ref resolution).
        When supplied, runs ``preserve_refs_for_detection`` so the layer-1
        shared-schema detector can fire on heavily $ref-using specs (typical
        of SpringDoc-generated OpenAPI). xgen-workflow callers who already
        bake refs into tool metadata via swagger_tool_generator can leave
        this None.

    Returns
    -------
    (ToolGraph, edge_stats):
        ``edge_stats`` keys:
          EXTRACTED, INFERRED, AMBIGUOUS, dropped:  int counts
          by_relation:                              {relation_value: int}
          cross_source:                             int  (edges across labels)
          tool_count, edge_count:                   int
          refs_preserved:                           int  (tools touched by
                                                          preserve_refs_for_detection)
    """
    tg = ToolGraph()
    for s in schemas:
        tg.add_tool(s)

    label_by_name = {s.name: _source_label(s) for s in schemas}

    stats: dict[str, Any] = {
        "EXTRACTED": 0,
        "INFERRED": 0,
        "AMBIGUOUS": 0,
        "dropped": 0,
        "by_relation": {},
        "cross_source": 0,
        "tool_count": len(schemas),
        "edge_count": 0,
        "refs_preserved": 0,
    }

    if len(schemas) < 2:
        return tg, stats

    # Optional: rescue layer-1 shared-schema signal that ingest_openapi inlined.
    if raw_spec is not None:
        stats["refs_preserved"] = preserve_refs_for_detection(schemas, raw_spec)

    # min_confidence=0.0 so we see every candidate; we re-bucket here.
    relations: list[DetectedRelation] = detect_dependencies(schemas, spec, min_confidence=0.0)

    seen: set[tuple[str, str, str]] = set()  # (src, tgt, relation_value)
    for rel in relations:
        bucket = bucket_confidence(
            rel.layer,
            rel.confidence,
            extracted_min=extracted_min,
            inferred_min=inferred_min,
            ambiguous_min=ambiguous_min,
        )
        if bucket is None:
            stats["dropped"] += 1
            continue

        rel_value = (
            rel.relation_type.value
            if hasattr(rel.relation_type, "value")
            else str(rel.relation_type)
        )
        key = (rel.source, rel.target, rel_value)
        if key in seen:
            # detect_dependencies already de-duplicates, but be defensive.
            continue
        seen.add(key)

        try:
            tg.add_relation(
                rel.source,
                rel.target,
                rel.relation_type,
                confidence=bucket,
                conf_score=rel.confidence,
                layer=rel.layer,
                evidence=rel.evidence,
            )
        except (KeyError, ValueError):
            # Endpoint not in graph (shouldn't happen — tools were just added) — skip.
            stats["dropped"] += 1
            continue

        stats[bucket.value] += 1
        stats["by_relation"][rel_value] = stats["by_relation"].get(rel_value, 0) + 1

        src_label = label_by_name.get(rel.source, "")
        tgt_label = label_by_name.get(rel.target, "")
        if src_label and tgt_label and src_label != tgt_label:
            stats["cross_source"] += 1

    # Derive workflow edges from ai_metadata.pairs_well_with — single
    # source-of-truth lives on each tool's metadata, edges are regenerated
    # on every rebuild so operator/LLM curation flows in automatically.
    pair_stats = _apply_pair_hints(tg, schemas)
    stats["pair_edges"] = pair_stats
    # Roll the pair edges into the global confidence/by_relation counters
    # so ``edge_stats`` accurately reflects the final graph contents.
    stats["EXTRACTED"] += pair_stats.get("manual", 0)
    stats["INFERRED"] += pair_stats.get("auto", 0)
    if pair_stats.get("manual") or pair_stats.get("auto"):
        stats["by_relation"]["complementary"] = (
            stats["by_relation"].get("complementary", 0)
            + pair_stats.get("manual", 0)
            + pair_stats.get("auto", 0)
        )
        # cross_source also re-counted on these new edges for completeness.
        for s in schemas:
            ai = (s.metadata or {}).get("ai_metadata") or {}
            for p in ai.get("pairs_well_with") or []:
                if not isinstance(p, dict):
                    continue
                tgt = str(p.get("tool") or "").strip()
                if not tgt or tgt == s.name or tgt not in tg.tools:
                    continue
                src_lab = label_by_name.get(s.name, "")
                tgt_lab = label_by_name.get(tgt, "")
                if src_lab and tgt_lab and src_lab != tgt_lab:
                    stats["cross_source"] += 1

    stats["edge_count"] = tg.graph.edge_count()
    return tg, stats
