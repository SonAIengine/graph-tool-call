"""Automatic dependency detection between tools."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import RelationType

# Parameter names too generic to be meaningful for name-based matching
_GENERIC_PARAMS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "type",
        "status",
        "page",
        "limit",
        "offset",
        "sort",
        "order",
        "filter",
        "q",
        "query",
        "format",
        "fields",
        "include",
        "exclude",
    }
)

# Canonical CRUD method ordering for PRECEDES detection
_CRUD_ORDER: dict[str, int] = {"post": 0, "get": 1, "put": 2, "patch": 2, "delete": 3}


@dataclass
class DetectedRelation:
    """A detected dependency between two tools."""

    source: str
    target: str
    relation_type: RelationType
    confidence: float  # 0.0 ~ 1.0
    evidence: str  # human-readable explanation
    layer: int  # 1=structural, 2=name-based


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_dependencies(
    tools: list[ToolSchema],
    spec: dict[str, Any] | None = None,
    *,
    min_confidence: float = 0.7,
) -> list[DetectedRelation]:
    """Detect dependency relations between *tools*.

    Parameters
    ----------
    tools:
        List of tool schemas to analyze.
    spec:
        Optional OpenAPI spec dict (currently unused; metadata on each tool is
        preferred).
    min_confidence:
        Only return relations whose confidence >= this threshold.

    Returns
    -------
    list[DetectedRelation]
        De-duplicated list of detected relations sorted by confidence desc.
    """
    relations: list[DetectedRelation] = []
    relations.extend(_detect_structural(tools, spec))
    relations.extend(_detect_name_based(tools))
    relations = _deduplicate(relations)
    relations = [r for r in relations if r.confidence >= min_confidence]
    relations.sort(key=lambda r: r.confidence, reverse=True)
    return relations


# ---------------------------------------------------------------------------
# Name normalisation helpers
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> list[str]:
    """Split camelCase / snake_case / kebab-case *name* into lowercase tokens."""
    # Insert space before uppercase letters to split camelCase / PascalCase
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    # Replace separators with spaces
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return [tok.lower() for tok in spaced.split() if tok]


def _extract_resource(path: str) -> str:
    """Extract the primary resource name from *path*.

    ``/users/{id}`` → ``users``, ``/users/{id}/orders`` → ``orders``.
    """
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return segments[-1] if segments else ""


def _strip_path_params(path: str) -> str:
    """Remove path parameters, returning only static segments.

    ``/users/{id}/orders/{orderId}`` → ``/users/orders``
    """
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return "/" + "/".join(segments) if segments else "/"


def _is_single_resource_path(path: str) -> bool:
    """Return True if path targets a single resource (ends with ``{param}``)."""
    segments = [s for s in path.split("/") if s]
    return bool(segments) and segments[-1].startswith("{")


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def _group_by_resource(tools: list[ToolSchema]) -> dict[str, list[ToolSchema]]:
    """Group tools that have ``method`` and ``path`` metadata by their base resource.

    The base resource is the first non-param path segment (e.g. ``/pets``).
    """
    groups: dict[str, list[ToolSchema]] = {}
    for tool in tools:
        path = tool.metadata.get("path")
        method = tool.metadata.get("method")
        if not path or not method:
            continue
        # base resource = first static segment of the path
        segments = [s for s in path.split("/") if s and not s.startswith("{")]
        base = "/" + segments[0] if segments else "/"
        groups.setdefault(base, []).append(tool)
    return groups


# ---------------------------------------------------------------------------
# Layer 1: Structural detection
# ---------------------------------------------------------------------------


def _detect_structural(
    tools: list[ToolSchema],
    spec: dict[str, Any] | None,
) -> list[DetectedRelation]:
    """Detect relations based on HTTP method + path metadata (Layer 1)."""
    relations: list[DetectedRelation] = []

    # Only consider tools that carry method/path metadata
    api_tools = [t for t in tools if t.metadata.get("method") and t.metadata.get("path")]
    if not api_tools:
        return relations

    # --- Path hierarchy ---
    relations.extend(_detect_path_hierarchy(api_tools))

    # --- CRUD patterns per resource group ---
    groups = _group_by_resource(api_tools)
    for _resource, group in groups.items():
        relations.extend(_detect_crud_patterns(group))

    # --- Shared schema references ---
    relations.extend(_detect_shared_schemas(api_tools))

    return relations


def _detect_path_hierarchy(tools: list[ToolSchema]) -> list[DetectedRelation]:
    """Nested paths imply REQUIRES (child requires parent)."""
    relations: list[DetectedRelation] = []
    for i, a in enumerate(tools):
        for b in tools[i + 1 :]:
            if a.name == b.name:
                continue
            path_a = _strip_path_params(a.metadata["path"])
            path_b = _strip_path_params(b.metadata["path"])
            if path_a == path_b:
                continue
            if path_b.startswith(path_a + "/"):
                # b is nested under a → b REQUIRES a
                relations.append(
                    DetectedRelation(
                        source=b.name,
                        target=a.name,
                        relation_type=RelationType.REQUIRES,
                        confidence=0.95,
                        evidence=(
                            f"Path {b.metadata['path']} is nested under {a.metadata['path']}"
                        ),
                        layer=1,
                    )
                )
            elif path_a.startswith(path_b + "/"):
                # a is nested under b → a REQUIRES b
                relations.append(
                    DetectedRelation(
                        source=a.name,
                        target=b.name,
                        relation_type=RelationType.REQUIRES,
                        confidence=0.95,
                        evidence=(
                            f"Path {a.metadata['path']} is nested under {b.metadata['path']}"
                        ),
                        layer=1,
                    )
                )
    return relations


def _detect_crud_patterns(group: list[ToolSchema]) -> list[DetectedRelation]:
    """Detect CRUD-based relations within a resource group."""
    relations: list[DetectedRelation] = []

    # Classify tools by method + single-vs-collection
    by_role: dict[str, list[ToolSchema]] = {}
    for tool in group:
        method = tool.metadata["method"].lower()
        path = tool.metadata["path"]
        single = _is_single_resource_path(path)
        role = f"{method}_{'single' if single else 'collection'}"
        by_role.setdefault(role, []).append(tool)

    posts = by_role.get("post_collection", [])
    gets_single = by_role.get("get_single", [])
    gets_collection = by_role.get("get_collection", [])
    puts = by_role.get("put_single", [])
    patches = by_role.get("patch_single", [])
    deletes = by_role.get("delete_single", [])

    updates = puts + patches

    # POST → GET/{id}: REQUIRES (creating before retrieving specific)
    for post in posts:
        for get_s in gets_single:
            if post.name == get_s.name:
                continue
            relations.append(
                DetectedRelation(
                    source=get_s.name,
                    target=post.name,
                    relation_type=RelationType.REQUIRES,
                    confidence=0.95,
                    evidence=f"{get_s.name} (GET single) requires {post.name} (POST) to exist",
                    layer=1,
                )
            )

    # POST → PUT: COMPLEMENTARY
    for post in posts:
        for upd in updates:
            if post.name == upd.name:
                continue
            relations.append(
                DetectedRelation(
                    source=post.name,
                    target=upd.name,
                    relation_type=RelationType.COMPLEMENTARY,
                    confidence=0.9,
                    evidence=f"{post.name} (POST) and {upd.name} (PUT/PATCH) are complementary",
                    layer=1,
                )
            )

    # GET (single) ↔ GET (list): SIMILAR_TO
    for get_c in gets_collection:
        for get_s in gets_single:
            if get_c.name == get_s.name:
                continue
            relations.append(
                DetectedRelation(
                    source=get_c.name,
                    target=get_s.name,
                    relation_type=RelationType.SIMILAR_TO,
                    confidence=0.85,
                    evidence=(
                        f"{get_c.name} (GET list) and {get_s.name} (GET single) "
                        "are similar (same resource)"
                    ),
                    layer=1,
                )
            )

    # PUT ↔ DELETE: CONFLICTS_WITH
    for upd in updates:
        for dele in deletes:
            if upd.name == dele.name:
                continue
            relations.append(
                DetectedRelation(
                    source=upd.name,
                    target=dele.name,
                    relation_type=RelationType.CONFLICTS_WITH,
                    confidence=0.8,
                    evidence=(
                        f"{upd.name} (PUT/PATCH) and {dele.name} (DELETE) "
                        "are conflicting state changes"
                    ),
                    layer=1,
                )
            )

    # CRUD ordering: POST → GET/PUT/PATCH/DELETE = PRECEDES
    # Only create PRECEDES between different CRUD stages (not within same stage)
    # POST(create) → GET(read), PUT/PATCH(update), DELETE(delete)
    # GET(read) → PUT/PATCH(update) — need to read before updating
    # POST is prerequisite for single-resource operations
    for post in posts:
        for target in gets_single + updates + deletes:
            if post.name == target.name:
                continue
            relations.append(
                DetectedRelation(
                    source=post.name,
                    target=target.name,
                    relation_type=RelationType.PRECEDES,
                    confidence=0.9,
                    evidence=(
                        f"{post.name} (POST/create) precedes "
                        f"{target.name} ({target.metadata['method'].upper()}) — "
                        "resource must exist first"
                    ),
                    layer=1,
                )
            )

    # GET(single) → PUT/PATCH/DELETE: read before modify/delete
    for get_s in gets_single:
        for target in updates + deletes:
            if get_s.name == target.name:
                continue
            relations.append(
                DetectedRelation(
                    source=get_s.name,
                    target=target.name,
                    relation_type=RelationType.PRECEDES,
                    confidence=0.8,
                    evidence=(
                        f"{get_s.name} (GET) precedes {target.name} "
                        f"({target.metadata['method'].upper()}) — read before modify"
                    ),
                    layer=1,
                )
            )

    # PUT/PATCH → DELETE: update before delete (optional, lower confidence)
    for upd in updates:
        for dele in deletes:
            if upd.name == dele.name:
                continue
            relations.append(
                DetectedRelation(
                    source=upd.name,
                    target=dele.name,
                    relation_type=RelationType.PRECEDES,
                    confidence=0.7,
                    evidence=(
                        f"{upd.name} ({upd.metadata['method'].upper()}) precedes "
                        f"{dele.name} (DELETE) in CRUD lifecycle"
                    ),
                    layer=1,
                )
            )

    return relations


def _detect_shared_schemas(tools: list[ToolSchema]) -> list[DetectedRelation]:
    """Detect COMPLEMENTARY/PRECEDES relations from shared schema references.

    Checks both request body and response schemas:
    - Shared $ref in any metadata → COMPLEMENTARY
    - Tool A's response $ref matches Tool B's request $ref → PRECEDES (data flow)
    """
    relations: list[DetectedRelation] = []

    def _collect_refs(obj: Any) -> set[str]:
        refs: set[str] = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "$ref" and isinstance(v, str):
                    refs.add(v)
                else:
                    refs.update(_collect_refs(v))
        elif isinstance(obj, list):
            for item in obj:
                refs.update(_collect_refs(item))
        return refs

    # Collect all refs, plus separate response/request refs for data flow detection
    tool_refs: dict[str, set[str]] = {}
    tool_response_refs: dict[str, set[str]] = {}
    tool_request_refs: dict[str, set[str]] = {}

    for tool in tools:
        refs = _collect_refs(tool.metadata)
        if refs:
            tool_refs[tool.name] = refs
        # Response schema refs
        resp_schema = tool.metadata.get("response_schema")
        if resp_schema:
            resp_refs = _collect_refs(resp_schema)
            if resp_refs:
                tool_response_refs[tool.name] = resp_refs
        # Request body refs (from metadata excluding response_schema)
        req_meta = {k: v for k, v in tool.metadata.items() if k != "response_schema"}
        req_refs = _collect_refs(req_meta)
        if req_refs:
            tool_request_refs[tool.name] = req_refs

    # Shared schema refs → COMPLEMENTARY
    names = list(tool_refs.keys())
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            shared = tool_refs[name_a] & tool_refs[name_b]
            if shared:
                relations.append(
                    DetectedRelation(
                        source=name_a,
                        target=name_b,
                        relation_type=RelationType.COMPLEMENTARY,
                        confidence=0.85,
                        evidence=(
                            f"{name_a} and {name_b} share schema refs: {', '.join(sorted(shared))}"
                        ),
                        layer=1,
                    )
                )

    # Response→Request data flow → PRECEDES
    for producer, resp_refs in tool_response_refs.items():
        for consumer, req_refs in tool_request_refs.items():
            if producer == consumer:
                continue
            shared = resp_refs & req_refs
            if shared:
                relations.append(
                    DetectedRelation(
                        source=producer,
                        target=consumer,
                        relation_type=RelationType.PRECEDES,
                        confidence=0.9,
                        evidence=(
                            f"{producer}'s response feeds into {consumer}'s request "
                            f"via shared schema: {', '.join(sorted(shared))}"
                        ),
                        layer=1,
                    )
                )

    return relations


# ---------------------------------------------------------------------------
# Layer 2: Name-based detection
# ---------------------------------------------------------------------------


def _detect_name_based(tools: list[ToolSchema]) -> list[DetectedRelation]:
    """Detect relations from tool name / parameter name overlap (Layer 2)."""
    relations: list[DetectedRelation] = []

    # Build index: for each tool, extract resource tokens from its name
    tool_tokens: dict[str, set[str]] = {}
    for tool in tools:
        tokens = set(_normalize_name(tool.name))
        # Remove common verbs that don't indicate a resource
        tokens -= {
            "get",
            "set",
            "create",
            "update",
            "delete",
            "remove",
            "list",
            "fetch",
            "find",
            "search",
            "add",
            "put",
            "patch",
            "post",
            "read",
            "write",
        }
        tool_tokens[tool.name] = tokens

    # Build index: for each tool, gather non-generic parameter name tokens
    tool_param_tokens: dict[str, set[str]] = {}
    for tool in tools:
        param_tokens: set[str] = set()
        for param in tool.parameters:
            normalized = _normalize_name(param.name)
            for tok in normalized:
                if tok.lower() not in _GENERIC_PARAMS:
                    param_tokens.add(tok)
        tool_param_tokens[tool.name] = param_tokens

    # Match: tool A is a creator (POST) and tool B's params reference A's resource
    # → tool B depends on tool A (tool B REQUIRES tool A)
    # Only POST/creator tools can be dependency targets to avoid noisy relations.
    creators = {
        t.name: tool_tokens[t.name]
        for t in tools
        if t.metadata.get("method", "").lower() == "post"
    }
    for creator_name, resource_tokens in creators.items():
        if not resource_tokens:
            continue
        for tool_b in tools:
            if tool_b.name == creator_name:
                continue
            params_b = tool_param_tokens[tool_b.name]
            shared = resource_tokens & params_b
            if shared:
                conf = 0.85 if len(shared) >= 2 else 0.8
                relations.append(
                    DetectedRelation(
                        source=tool_b.name,
                        target=creator_name,
                        relation_type=RelationType.REQUIRES,
                        confidence=conf,
                        evidence=(
                            f"{tool_b.name} has params referencing {creator_name}'s "
                            f"resource: {', '.join(sorted(shared))}"
                        ),
                        layer=2,
                    )
                )

    return relations


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------


def _deduplicate(relations: list[DetectedRelation]) -> list[DetectedRelation]:
    """Keep only the highest-confidence relation for each (source, target, type) triple."""
    best: dict[tuple[str, str, RelationType], DetectedRelation] = {}
    for rel in relations:
        key = (rel.source, rel.target, rel.relation_type)
        existing = best.get(key)
        if existing is None or rel.confidence > existing.confidence:
            best[key] = rel
    return list(best.values())
