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
from graph_tool_call.core.contract_matching import description_alias_key
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify.edges import (
    EVIDENCE_API_CONTRACT,
    EVIDENCE_OPENAPI_LINK,
    merge_graph_edges,
    normalize_graph_edge,
)
from graph_tool_call.graphify.io_contract import FieldPredicate, promote_api_contract_signals
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


def _apply_contract_data_flow_edges(
    tg: ToolGraph,
    schemas: list[ToolSchema],
    *,
    max_producers_per_field: int = 3,
) -> dict[str, int]:
    """Derive deterministic producer edges from promoted IO contracts.

    Direction follows the rest of Planflow: ``consumer --requires--> producer``.
    The edge is a graph hint, not an execution binding. ``PathSynthesizer`` still
    verifies that the producer actually exposes the field before using it.
    """

    stats = {
        "added": 0,
        "merged": 0,
        "skipped_self": 0,
        "skipped_no_producer": 0,
        "skipped_echo": 0,
    }
    tools_by_name = {schema.name: schema for schema in schemas}
    producer_index = _contract_producer_index(schemas)

    for consumer in schemas:
        metadata = consumer.metadata or {}
        for consume in metadata.get("consumes") or []:
            if not isinstance(consume, dict):
                continue
            if not consume.get("required"):
                continue
            if str(consume.get("kind") or "data").strip().lower() != "data":
                continue

            semantic = str(consume.get("semantic_tag") or "").strip()
            field_name = str(consume.get("field_name") or "").strip()
            field_key = _contract_field_key(field_name)
            description_key = description_alias_key(consume)
            candidate_names = list(
                dict.fromkeys(
                    producer_index.get(("semantic", semantic), [])
                    + producer_index.get(("field", field_name), [])
                    + producer_index.get(("loose", field_key), [])
                    + producer_index.get(("description", description_key), [])
                )
            )
            if not candidate_names:
                stats["skipped_no_producer"] += 1
                continue

            scored: list[tuple[int, str, dict[str, Any]]] = []
            for producer_name in candidate_names:
                if producer_name == consumer.name:
                    stats["skipped_self"] += 1
                    continue
                producer = tools_by_name.get(producer_name)
                if producer is None:
                    continue
                produce = _matching_produce(
                    producer.metadata or {},
                    semantic=semantic,
                    field_name=field_name,
                    field_key=field_key,
                    description_key=description_key,
                )
                if produce is None:
                    continue
                if _is_echo_producer(producer.metadata or {}, produce):
                    stats["skipped_echo"] += 1
                    continue
                scored.append(
                    (
                        _contract_edge_score(producer.metadata or {}, produce),
                        producer_name,
                        produce,
                    )
                )

            if not scored:
                stats["skipped_no_producer"] += 1
                continue

            scored.sort(key=lambda item: (-item[0], item[1]))
            for _score, producer_name, produce in scored[: max(0, max_producers_per_field)]:
                result = _add_or_merge_contract_edge(
                    tg,
                    consumer=consumer.name,
                    producer=producer_name,
                    consume=consume,
                    produce=produce,
                )
                stats[result] += 1

    return stats


def _promote_openapi_link_signals(schemas: list[ToolSchema]) -> dict[str, int]:
    """Expose response-link parameter mappings as producer aliases.

    OpenAPI Link Objects can say ``getUser.userId = $response.body#/id``.
    The producer's raw response field is ``id``, but the consumer field is
    ``userId``. Adding a non-search producer alias lets Planflow bind the
    documented mapping without guessing that ``id`` and ``userId`` are related.
    """

    stats = {
        "links_seen": 0,
        "produces_added": 0,
        "skipped_no_response_source": 0,
    }
    for producer in schemas:
        metadata = producer.metadata if isinstance(producer.metadata, dict) else {}
        if producer.metadata is not metadata:
            producer.metadata = metadata
        produces = metadata.setdefault("produces", [])
        if not isinstance(produces, list):
            produces = []
            metadata["produces"] = produces

        seen = {
            (str(row.get("field_name") or ""), str(row.get("json_path") or ""))
            for row in produces
            if isinstance(row, dict)
        }
        for link in _openapi_contract_links(producer):
            stats["links_seen"] += 1
            response_params = _response_link_parameters(link)
            if not response_params:
                stats["skipped_no_response_source"] += 1
                continue
            for parameter in response_params:
                field_name = str(parameter.get("field_name") or "").strip()
                json_path = _response_link_parameter_json_path(parameter)
                if not field_name or not json_path:
                    continue
                key = (field_name, json_path)
                if key in seen:
                    continue
                produce = {
                    "field_name": field_name,
                    "json_path": json_path,
                    "field_type": "string",
                    "required": False,
                    "kind": "data",
                    "search_signal": False,
                    "contract_source": EVIDENCE_OPENAPI_LINK,
                    "openapi_link_name": link.get("name"),
                    "openapi_link_target_operation_id": link.get("operation_id"),
                    "openapi_link_target_operation_ref": link.get("operation_ref"),
                    "openapi_link_source": parameter.get("source"),
                    "source_field_name": _response_link_source_field_name(parameter, json_path),
                }
                aliases = _response_body_value_aliases(
                    json_path, str(parameter.get("source") or "")
                )
                if aliases:
                    produce["value_path_aliases"] = aliases
                produces.append(produce)
                seen.add(key)
                stats["produces_added"] += 1
    return stats


def _apply_openapi_link_edges(tg: ToolGraph, schemas: list[ToolSchema]) -> dict[str, Any]:
    """Add graph edges from OpenAPI response links.

    Direction follows Planflow's convention:
    ``linked operation consumer --requires--> source response producer``.
    """

    stats: dict[str, Any] = {
        "added": 0,
        "merged": 0,
        "skipped_unresolved": 0,
        "skipped_self": 0,
        "by_relation": {},
    }
    index = _operation_target_index(schemas)
    for producer in schemas:
        for link in _openapi_contract_links(producer):
            consumer = _resolve_openapi_link_target(link, index)
            if not consumer:
                stats["skipped_unresolved"] += 1
                continue
            if consumer == producer.name:
                stats["skipped_self"] += 1
                continue
            relation = (
                RelationType.REQUIRES if _response_link_parameters(link) else RelationType.PRECEDES
            )
            result = _add_or_merge_openapi_link_edge(
                tg,
                consumer=consumer,
                producer=producer.name,
                link=link,
                relation=relation,
            )
            stats[result] += 1
            relation_value = relation.value
            stats["by_relation"][relation_value] = stats["by_relation"].get(relation_value, 0) + (
                1 if result == "added" else 0
            )
    return stats


def _openapi_contract_links(schema: ToolSchema) -> list[dict[str, Any]]:
    metadata = schema.metadata if isinstance(schema.metadata, dict) else {}
    contract = (
        metadata.get("api_contract") if isinstance(metadata.get("api_contract"), dict) else {}
    )
    links = contract.get("links") if isinstance(contract.get("links"), list) else []
    return [
        link for link in links if isinstance(link, dict) and link.get("success", True) is not False
    ]


def _response_link_parameters(link: dict[str, Any]) -> list[dict[str, Any]]:
    params = link.get("parameters") if isinstance(link.get("parameters"), list) else []
    return [
        param
        for param in params
        if isinstance(param, dict)
        and str(param.get("source") or "") in {"response_body", "response_header"}
    ]


def _response_link_parameter_json_path(parameter: dict[str, Any]) -> str:
    json_path = str(parameter.get("json_path") or "").strip()
    if json_path:
        return json_path
    if str(parameter.get("source") or "") == "response_header":
        header = str(parameter.get("header") or "").strip()
        if header:
            return f"$.headers.{header}"
    return ""


def _response_link_source_field_name(parameter: dict[str, Any], json_path: str) -> str:
    if str(parameter.get("source") or "") == "response_header":
        return str(parameter.get("header") or "").strip()
    return _json_path_tail(json_path)


def _operation_target_index(schemas: list[ToolSchema]) -> dict[tuple[str, str], str]:
    index: dict[tuple[str, str], str] = {}
    operation_names: dict[str, list[str]] = {}
    for schema in schemas:
        metadata = schema.metadata or {}
        openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        operation_id = str(openapi.get("operation_id") or schema.name).strip()
        if operation_id:
            operation_names.setdefault(operation_id, []).append(schema.name)
    ambiguous_operation_ids = {
        operation_id for operation_id, names in operation_names.items() if len(set(names)) > 1
    }

    for schema in schemas:
        metadata = schema.metadata or {}
        openapi = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        operation_id = str(openapi.get("operation_id") or schema.name).strip()
        if operation_id and operation_id not in ambiguous_operation_ids:
            index[("operation_id", operation_id)] = schema.name
        if schema.name != operation_id or operation_id not in ambiguous_operation_ids:
            index[("operation_id", schema.name)] = schema.name
        path = str(metadata.get("path") or "").strip()
        method = str(metadata.get("method") or "").strip().lower()
        if path and method:
            index[("operation_ref", _local_operation_ref(path, method))] = schema.name
    return index


def _resolve_openapi_link_target(
    link: dict[str, Any],
    index: dict[tuple[str, str], str],
) -> str:
    operation_id = str(link.get("operation_id") or link.get("operationId") or "").strip()
    if operation_id and (target := index.get(("operation_id", operation_id))):
        return target
    operation_ref = str(link.get("operation_ref") or link.get("operationRef") or "").strip()
    normalized_ref = _normalize_operation_ref(operation_ref)
    if normalized_ref and (target := index.get(("operation_ref", normalized_ref))):
        return target
    return ""


def _local_operation_ref(path: str, method: str) -> str:
    escaped_path = path.replace("~", "~0").replace("/", "~1")
    return f"#/paths/{escaped_path}/{method.lower()}"


def _normalize_operation_ref(operation_ref: str) -> str:
    if not operation_ref:
        return ""
    if "#" in operation_ref:
        operation_ref = "#" + operation_ref.split("#", 1)[1]
    return operation_ref


def _add_or_merge_openapi_link_edge(
    tg: ToolGraph,
    *,
    consumer: str,
    producer: str,
    link: dict[str, Any],
    relation: RelationType,
) -> str:
    parameters = [dict(param) for param in link.get("parameters") or [] if isinstance(param, dict)]
    response_params = _response_link_parameters(link)
    primary = response_params[0] if response_params else (parameters[0] if parameters else {})
    primary_path = _response_link_parameter_json_path(primary) if primary else ""
    relation_value = relation.value
    incoming = normalize_graph_edge(
        {
            "source": consumer,
            "target": producer,
            "relation": relation,
            "confidence": Confidence.EXTRACTED,
            "conf_score": 0.95 if relation == RelationType.REQUIRES else 0.9,
            "layer": 1,
            "evidence": _openapi_link_evidence(consumer, producer, link),
            "kind": "data" if relation == RelationType.REQUIRES else "semantic",
            "evidence_sources": [EVIDENCE_OPENAPI_LINK],
            "data_flow": {
                "from_operation": producer,
                "to_operation": consumer,
                "link_name": link.get("name"),
                "source_status": link.get("source_status"),
                "from_path": primary_path,
                "from_field": primary.get("source_field_name")
                or _response_link_source_field_name(primary, primary_path),
                "to_field": primary.get("field_name") or "",
                "parameters": parameters,
            },
        },
        default_source=EVIDENCE_OPENAPI_LINK,
    )
    if tg.graph.has_edge(consumer, producer):
        existing = tg.graph.get_edge_attrs(consumer, producer)
        merged = merge_graph_edges(
            {"source": consumer, "target": producer, **existing},
            incoming,
        )
        if relation == RelationType.REQUIRES:
            merged["relation"] = relation_value
        _put_edge(tg, consumer, producer, merged)
        return "merged"

    _put_edge(tg, consumer, producer, incoming)
    return "added"


def _openapi_link_evidence(consumer: str, producer: str, link: dict[str, Any]) -> str:
    link_name = str(link.get("name") or "link")
    parameters = link.get("parameters") if isinstance(link.get("parameters"), list) else []
    mapping = ", ".join(
        f"{param.get('field_name')}={param.get('expression') or param.get('value')}"
        for param in parameters
        if isinstance(param, dict) and param.get("field_name")
    )
    suffix = f": {mapping}" if mapping else ""
    return f"openapi link {link_name}: {producer} -> {consumer}{suffix}"


def _response_body_value_aliases(json_path: str, source: str) -> list[str]:
    if source != "response_body" or not json_path.startswith("$."):
        return []
    return [f"$.body{json_path[1:]}"]


def _json_path_tail(value: Any) -> str:
    path = str(value or "")
    if not path or path == "$":
        return ""
    tail = path.rsplit(".", 1)[-1]
    if tail.endswith("]") and "[" in tail:
        tail = tail.split("[", 1)[0]
    return tail


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


def _contract_producer_index(
    schemas: list[ToolSchema],
) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    for schema in schemas:
        metadata = schema.metadata or {}
        for produce in metadata.get("produces") or []:
            if not isinstance(produce, dict):
                continue
            semantic = str(produce.get("semantic_tag") or "").strip()
            field_name = str(produce.get("field_name") or "").strip()
            field_key = _contract_field_key(field_name)
            description_key = description_alias_key(produce)
            if semantic:
                index.setdefault(("semantic", semantic), []).append(schema.name)
            if field_name:
                index.setdefault(("field", field_name), []).append(schema.name)
            if field_key:
                index.setdefault(("loose", field_key), []).append(schema.name)
            if description_key:
                index.setdefault(("description", description_key), []).append(schema.name)
    return index


def _matching_produce(
    metadata: dict[str, Any],
    *,
    semantic: str,
    field_name: str,
    field_key: str,
    description_key: str,
) -> dict[str, Any] | None:
    for produce in metadata.get("produces") or []:
        if not isinstance(produce, dict):
            continue
        p_semantic = str(produce.get("semantic_tag") or "").strip()
        p_field_name = str(produce.get("field_name") or "").strip()
        if semantic and p_semantic == semantic:
            return produce
        if field_name and p_field_name == field_name:
            return produce
        if field_key and _contract_field_key(p_field_name) == field_key:
            return produce
        if description_key and description_alias_key(produce) == description_key:
            return produce
    return None


def _is_echo_producer(metadata: dict[str, Any], produce: dict[str, Any]) -> bool:
    p_semantic = str(produce.get("semantic_tag") or "").strip()
    p_field_name = str(produce.get("field_name") or "").strip()
    p_field_key = _contract_field_key(p_field_name)
    p_description_key = description_alias_key(produce)
    for consume in metadata.get("consumes") or []:
        if not isinstance(consume, dict):
            continue
        c_semantic = str(consume.get("semantic_tag") or "").strip()
        c_field_name = str(consume.get("field_name") or "").strip()
        if p_semantic and c_semantic == p_semantic:
            return True
        if p_field_name and c_field_name == p_field_name:
            return True
        if p_field_key and _contract_field_key(c_field_name) == p_field_key:
            return True
        if p_description_key and description_alias_key(consume) == p_description_key:
            return True
    return False


def _contract_edge_score(metadata: dict[str, Any], produce: dict[str, Any]) -> int:
    score = int(produce.get("signal_score") or 0)
    ai = metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else {}
    action = str(ai.get("canonical_action") or "").strip().lower()
    if action == "search":
        score += 4
    elif action == "read":
        score += 3
    elif action in ("list", "lookup"):
        score += 2
    if produce.get("semantic_inferred_from") != "field_name":
        score += 2
    return score


def _add_or_merge_contract_edge(
    tg: ToolGraph,
    *,
    consumer: str,
    producer: str,
    consume: dict[str, Any],
    produce: dict[str, Any],
) -> str:
    to_field = str(consume.get("field_name") or "")
    from_path = str(produce.get("json_path") or produce.get("field_name") or "")
    incoming = normalize_graph_edge(
        {
            "source": consumer,
            "target": producer,
            "relation": RelationType.REQUIRES,
            "confidence": Confidence.INFERRED,
            "conf_score": 0.82,
            "layer": 2,
            "evidence": f"api contract data flow: {producer}.{from_path} -> {consumer}.{to_field}",
            "kind": "data",
            "evidence_sources": [EVIDENCE_API_CONTRACT],
            "data_flow": {
                "from_path": from_path,
                "from_field": produce.get("field_name"),
                "to_field": to_field,
                "semantic_tag": consume.get("semantic_tag") or produce.get("semantic_tag") or "",
            },
        },
        default_source=EVIDENCE_API_CONTRACT,
    )
    if tg.graph.has_edge(consumer, producer):
        existing = tg.graph.get_edge_attrs(consumer, producer)
        merged = merge_graph_edges(
            {"source": consumer, "target": producer, **existing},
            incoming,
        )
        # A schema data-flow signal should remain traversable by Planflow even
        # when an older semantic edge already connected the same pair.
        merged["relation"] = RelationType.REQUIRES.value
        _put_edge(tg, consumer, producer, merged)
        return "merged"

    _put_edge(tg, consumer, producer, incoming)
    return "added"


def _put_edge(tg: ToolGraph, source: str, target: str, edge: dict[str, Any]) -> None:
    attrs = {k: v for k, v in edge.items() if k not in {"source", "target"}}
    tg.graph.add_edge(source, target, **attrs)


def _contract_field_key(value: Any) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def ingest_openapi_graphify(
    schemas: list[ToolSchema],
    *,
    extracted_min: float = DEFAULT_CONF_EXTRACTED,
    inferred_min: float = DEFAULT_CONF_INFERRED,
    ambiguous_min: float = DEFAULT_CONF_AMBIGUOUS,
    spec: dict[str, Any] | None = None,
    raw_spec: dict[str, Any] | None = None,
    promote_contract_signals: bool = False,
    contract_signal_options: dict[str, Any] | None = None,
    max_contract_producers_per_field: int = 3,
    user_input_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    context_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    auth_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    paging_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    search_filter_field_names: set[str] | list[str] | tuple[str, ...] | None = None,
    context_detector: FieldPredicate | None = None,
    auth_detector: FieldPredicate | None = None,
    paging_detector: FieldPredicate | None = None,
    search_filter_detector: FieldPredicate | None = None,
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
    promote_contract_signals:
        When True, selected rows from ``metadata.api_contract`` are promoted
        into top-level ``metadata.produces`` / ``metadata.consumes`` and used
        to derive ``REQUIRES`` data-flow edges. Defaults False to keep plain
        ingest conservative on very large, noisy Swagger specs.
    contract_signal_options:
        Optional keyword overrides forwarded to ``promote_api_contract_signals``.

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
    if promote_contract_signals:
        options = dict(contract_signal_options or {})
        defaults = {
            "user_input_field_names": user_input_field_names,
            "context_field_names": context_field_names,
            "auth_field_names": auth_field_names,
            "paging_field_names": paging_field_names,
            "search_filter_field_names": search_filter_field_names,
            "context_detector": context_detector,
            "auth_detector": auth_detector,
            "paging_detector": paging_detector,
            "search_filter_detector": search_filter_detector,
        }
        for key, value in defaults.items():
            if value is not None and key not in options:
                options[key] = value
        contract_signal_stats = promote_api_contract_signals(schemas, **options)
    else:
        contract_signal_stats = {}

    openapi_link_signal_stats = _promote_openapi_link_signals(schemas)

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
        "contract_signals": contract_signal_stats,
        "contract_edges": {},
        "openapi_link_signals": openapi_link_signal_stats,
        "openapi_link_edges": {},
    }

    if len(schemas) < 2:
        openapi_link_edge_stats = _apply_openapi_link_edges(tg, schemas)
        stats["openapi_link_edges"] = openapi_link_edge_stats
        stats["EXTRACTED"] += openapi_link_edge_stats.get("added", 0)
        for relation, count in openapi_link_edge_stats.get("by_relation", {}).items():
            stats["by_relation"][relation] = stats["by_relation"].get(relation, 0) + count
        if promote_contract_signals:
            stats["contract_edges"] = _apply_contract_data_flow_edges(
                tg,
                schemas,
                max_producers_per_field=max_contract_producers_per_field,
            )
        stats["edge_count"] = tg.graph.edge_count()
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

    openapi_link_edge_stats = _apply_openapi_link_edges(tg, schemas)
    stats["openapi_link_edges"] = openapi_link_edge_stats
    stats["EXTRACTED"] += openapi_link_edge_stats.get("added", 0)
    for relation, count in openapi_link_edge_stats.get("by_relation", {}).items():
        stats["by_relation"][relation] = stats["by_relation"].get(relation, 0) + count

    if promote_contract_signals:
        contract_edge_stats = _apply_contract_data_flow_edges(
            tg,
            schemas,
            max_producers_per_field=max_contract_producers_per_field,
        )
        stats["contract_edges"] = contract_edge_stats
        stats["INFERRED"] += contract_edge_stats.get("added", 0)
        stats["by_relation"]["requires"] = stats["by_relation"].get(
            "requires", 0
        ) + contract_edge_stats.get("added", 0)

    stats["edge_count"] = tg.graph.edge_count()
    return tg, stats
