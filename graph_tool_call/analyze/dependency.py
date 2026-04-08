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
    relations.extend(_detect_cross_resource(tools))
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
    """Nested paths imply REQUIRES — but only direct parent-child, not grandparent.

    /orders/{id}/refund REQUIRES /orders/{id} (direct parent)
    /orders/{id}/refund does NOT require /orders (grandparent — too loose)

    Additionally, the parent must be a data-providing operation (GET/POST)
    to avoid false positives like refund REQUIRES listOrders.
    """
    relations: list[DetectedRelation] = []

    # Build (stripped_path, original_path) → tool index
    path_tools: dict[str, list[ToolSchema]] = {}
    for tool in tools:
        stripped = _strip_path_params(tool.metadata["path"])
        path_tools.setdefault(stripped, []).append(tool)

    for tool in tools:
        path = tool.metadata["path"]
        # Find the closest parent by walking up the original path segments
        # /orders/{orderId}/refund → try /orders/{orderId} first, then /orders
        segments = [s for s in path.split("/") if s]
        if len(segments) < 2:
            continue

        # Try progressively shorter paths, stop at first match
        found_parent = False
        for depth in range(len(segments) - 1, 0, -1):
            parent_path_raw = "/" + "/".join(segments[:depth])
            parent_stripped = _strip_path_params(parent_path_raw)
            parent_tools_list = path_tools.get(parent_stripped, [])
            for parent in parent_tools_list:
                if parent.name == tool.name:
                    continue
                # Only GET as data provider (not POST/list — too loose)
                parent_method = parent.metadata.get("method", "").upper()
                if parent_method != "GET":
                    continue
                # Must be a single-resource GET (with {id} param)
                if not _is_single_resource_path(parent.metadata["path"]):
                    continue
                relations.append(
                    DetectedRelation(
                        source=tool.name,
                        target=parent.name,
                        relation_type=RelationType.REQUIRES,
                        confidence=0.9,
                        evidence=(
                            f"{tool.name} ({path}) requires data from "
                            f"{parent.name} ({parent.metadata['path']})"
                        ),
                        layer=1,
                    )
                )
                found_parent = True
            if found_parent:
                break  # stop at closest parent
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
    deletes = by_role.get("delete_single", [])

    # --- Focused CRUD relations ---
    # Only create relations that represent real data dependencies,
    # not every possible CRUD combination.

    # POST → GET/{id}: the resource must be created before it can be read
    # This is the strongest CRUD dependency.
    for post in posts:
        for get_s in gets_single:
            if post.name == get_s.name:
                continue
            # Only if they share the same resource path
            post_resource = _extract_resource(post.metadata["path"])
            get_resource = _extract_resource(get_s.metadata["path"])
            if post_resource != get_resource:
                continue
            relations.append(
                DetectedRelation(
                    source=get_s.name,
                    target=post.name,
                    relation_type=RelationType.REQUIRES,
                    confidence=0.9,
                    evidence=(
                        f"{get_s.name} (GET single) requires {post.name} (POST) "
                        f"— same resource '{post_resource}'"
                    ),
                    layer=1,
                )
            )

    # GET (single) ↔ GET (list): SIMILAR_TO (these are alternative views)
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

    # POST → DELETE: create before delete (lifecycle endpoints only)
    for post in posts:
        for dele in deletes:
            if post.name == dele.name:
                continue
            post_resource = _extract_resource(post.metadata["path"])
            del_resource = _extract_resource(dele.metadata["path"])
            if post_resource != del_resource:
                continue
            relations.append(
                DetectedRelation(
                    source=post.name,
                    target=dele.name,
                    relation_type=RelationType.PRECEDES,
                    confidence=0.85,
                    evidence=(
                        f"{post.name} (create) precedes {dele.name} (delete) "
                        f"— same resource '{post_resource}'"
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

    # Match: tool B has a parameter like "{resource}_id" and tool A is
    # a creator (POST) for that resource → tool B REQUIRES tool A.
    # Filter: require at least 2 shared tokens OR the shared token must
    # be a specific resource name (not a generic verb).
    creators = {
        t.name: tool_tokens[t.name] for t in tools if t.metadata.get("method", "").lower() == "post"
    }
    for creator_name, resource_tokens in creators.items():
        if not resource_tokens:
            continue
        for tool_b in tools:
            if tool_b.name == creator_name:
                continue
            params_b = tool_param_tokens[tool_b.name]
            shared = resource_tokens & params_b
            if not shared:
                continue
            # Require strong evidence: 2+ shared tokens, or the token
            # appears in a parameter ending with "id" (e.g., "orderId")
            has_id_param = any(
                tok in p.name.lower()
                for p in tool_b.parameters
                for tok in shared
                if "id" in p.name.lower()
            )
            if len(shared) >= 2 or has_id_param:
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
# Layer 3: Cross-resource parameter dependency
# ---------------------------------------------------------------------------


def _detect_cross_resource(tools: list[ToolSchema]) -> list[DetectedRelation]:
    """Detect cross-resource dependencies from parameter names.

    When tool B has a parameter like ``orderId``, it needs data from the
    ``orders`` resource. This creates a REQUIRES relation to a GET tool
    that can provide that ID.

    Example: ``checkout(shippingAddressId)`` → REQUIRES ``addUserAddress``
             ``addToCart(productId)`` → REQUIRES ``getProduct``
    """
    relations: list[DetectedRelation] = []

    # Build resource → GET/POST provider index
    # e.g., "order" → getOrder, "product" → getProduct, "user" → getUser
    resource_providers: dict[str, list[ToolSchema]] = {}
    for tool in tools:
        method = (tool.metadata.get("method") or "").upper()
        if method not in ("GET", "POST"):
            continue
        # Extract resource name from tool name
        name_tokens = _normalize_name(tool.name)
        # Remove verb prefix
        resource_tokens = [
            t
            for t in name_tokens
            if t not in ("get", "list", "create", "add", "post", "read", "find")
        ]
        for tok in resource_tokens:
            resource_providers.setdefault(tok, []).append(tool)

    # For each tool, check if its parameters reference other resources
    for tool in tools:
        if not tool.parameters:
            continue
        for param in tool.parameters:
            p_name = param.name if hasattr(param, "name") else str(param)
            p_lower = p_name.lower()

            # Match patterns like "orderId", "product_id", "userId"
            # Extract the resource name from the parameter
            resource_name = None
            if p_lower.endswith("id") and len(p_lower) > 2:
                # "orderId" → "order", "productId" → "product"
                raw = p_lower[:-2]  # strip "id"
                if raw.endswith("_"):
                    raw = raw[:-1]  # strip trailing underscore
                if len(raw) >= 3:
                    resource_name = raw
            elif "_id" in p_lower:
                # "user_id" → "user"
                parts = p_lower.split("_id")
                if parts[0] and len(parts[0]) >= 3:
                    resource_name = parts[0]

            if not resource_name:
                continue

            # Find providers for this resource
            providers = resource_providers.get(resource_name, [])
            for provider in providers:
                if provider.name == tool.name:
                    continue

                # Prefer GET single over GET list/POST
                provider_method = (provider.metadata.get("method") or "").upper()
                provider_path = provider.metadata.get("path", "")
                is_get_single = provider_method == "GET" and _is_single_resource_path(provider_path)

                # Only create cross-resource link if provider is from
                # a DIFFERENT resource category than the consumer
                consumer_resource = _extract_resource(tool.metadata.get("path", ""))
                provider_resource = _extract_resource(provider_path)
                if consumer_resource == provider_resource:
                    continue  # same resource — handled by structural detection

                # Only accept GET single as cross-resource provider
                # GET list and POST are too noisy as providers
                if not is_get_single:
                    continue

                conf = 0.85
                relations.append(
                    DetectedRelation(
                        source=tool.name,
                        target=provider.name,
                        relation_type=RelationType.REQUIRES,
                        confidence=conf,
                        evidence=(
                            f"{tool.name} has param '{p_name}' referencing "
                            f"{provider.name}'s resource '{resource_name}'"
                        ),
                        layer=3,
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
