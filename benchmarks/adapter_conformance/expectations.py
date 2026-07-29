"""Independent source inspectors for adapter-conformance expectations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "trace"})


@dataclass(frozen=True)
class ToolExpectation:
    """Source-declared facts that one normalized tool should preserve."""

    key: str
    request_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    request_signatures: frozenset[tuple[str, str]] = frozenset()
    response_signatures: frozenset[tuple[str, str]] = frozenset()
    request_fields: frozenset[str] = frozenset()
    request_field_types: frozenset[tuple[str, str, bool]] = frozenset()
    consume_fields: frozenset[str] = frozenset()
    produce_fields: frozenset[str] = frozenset()
    auth_schemes: frozenset[str] = frozenset()
    required_auth_schemes: frozenset[str] = frozenset()
    auth_scheme_facts: frozenset[tuple[str, ...]] = frozenset()
    auth_requirements: tuple[tuple[tuple[str, tuple[str, ...]], ...], ...] = ()
    execution_transport: str = ""
    graphql_return_type: str = ""
    graphql_response_root_type: str = ""
    consumes_expected: bool = False
    produces_expected: bool = False

    @property
    def request_applicable(self) -> bool:
        return self.request_schema is not None or bool(self.request_fields)

    @property
    def response_applicable(self) -> bool:
        return self.response_schema is not None or self.produces_expected


@dataclass(frozen=True)
class SourceExpectations:
    """All independently inspected operations for one source document."""

    source_type: str
    tools: dict[str, ToolExpectation] = field(default_factory=dict)


def inspect_source_expectations(
    source: dict[str, Any] | list[dict[str, Any]],
    *,
    source_type: str,
    ingest_options: dict[str, Any] | None = None,
) -> SourceExpectations:
    """Inspect raw source facts without invoking a graph-tool-call adapter."""
    if source_type == "openapi":
        return _inspect_openapi(source)
    if source_type == "graphql-introspection":
        return _inspect_graphql(source, ingest_options=ingest_options or {})
    if source_type == "mcp":
        return _inspect_mcp(source)
    raise ValueError(f"Unsupported conformance source_type: {source_type}")


def normalized_tool_key(tool_metadata: dict[str, Any], *, source_type: str, name: str) -> str:
    """Return the source-stable key for one normalized tool."""
    if source_type == "openapi":
        method = str(tool_metadata.get("method") or "").upper()
        path = str(tool_metadata.get("path") or "")
        return f"{method} {path}"
    if source_type == "graphql-introspection":
        graphql = tool_metadata.get("graphql") or {}
        return f"{graphql.get('operation_type', '')}:{graphql.get('root_field', '')}"
    return name


def schema_signatures(
    schema: dict[str, Any] | None,
    *,
    document: dict[str, Any] | None = None,
) -> frozenset[tuple[str, str]]:
    """Return bounded leaf path/type signatures for structural fidelity checks."""
    signatures: set[tuple[str, str]] = set()
    _collect_schema_signatures(
        schema,
        document=document or {},
        path="$",
        signatures=signatures,
        ref_stack=(),
        depth=0,
    )
    return frozenset(signatures)


def normalized_auth_scheme_fact(name: str, scheme: Any) -> tuple[str, ...]:
    """Return a stable, credential-free security-scheme fact tuple."""
    row = scheme if isinstance(scheme, dict) else {}
    raw_flows = row.get("oauth_flows")
    if isinstance(raw_flows, list):
        oauth_flows = sorted(str(value) for value in raw_flows)
    elif isinstance(row.get("flows"), dict):
        oauth_flows = sorted(str(value) for value in row["flows"])
    elif row.get("flow"):
        oauth_flows = [str(row["flow"])]
    else:
        oauth_flows = []
    return (
        str(name),
        str(row.get("type") or ""),
        str(row.get("in") or ""),
        str(row.get("name") or ""),
        str(row.get("scheme") or ""),
        str(row.get("bearerFormat") or row.get("bearer_format") or ""),
        ",".join(oauth_flows),
        str(row.get("openIdConnectUrl") or row.get("open_id_connect_url") or ""),
    )


def normalized_auth_requirements(
    requirements: Any,
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], ...]:
    """Canonicalize OpenAPI OR-of-AND security requirements."""
    if not isinstance(requirements, list):
        return ()
    normalized = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        normalized.append(
            tuple(
                sorted(
                    (
                        str(name),
                        tuple(sorted(str(scope) for scope in (raw_scopes or []))),
                    )
                    for name, raw_scopes in requirement.items()
                )
            )
        )
    return tuple(sorted(normalized))


def _inspect_openapi(source: Any) -> SourceExpectations:
    if not isinstance(source, dict):
        raise TypeError("OpenAPI conformance source must be an object.")
    tools: dict[str, ToolExpectation] = {}
    paths = source.get("paths")
    if not isinstance(paths, dict):
        return SourceExpectations(source_type="openapi")
    for path, raw_path_item in paths.items():
        path_item = _resolve_mapping(raw_path_item, source)
        if not isinstance(path_item, dict):
            continue
        path_parameters = _parameter_rows(path_item.get("parameters"), source)
        for method, raw_operation in path_item.items():
            if str(method).lower() not in _HTTP_METHODS:
                continue
            operation = _resolve_mapping(raw_operation, source)
            if not isinstance(operation, dict):
                continue
            operation_parameters = _parameter_rows(operation.get("parameters"), source)
            parameter_rows = _merge_parameter_rows(path_parameters, operation_parameters)
            request_schema = _openapi_request_schema(operation, parameter_rows, source)
            request_fields = frozenset(
                str(row.get("name"))
                for row in parameter_rows
                if isinstance(row.get("name"), str) and row.get("in") != "body"
            )
            response_schema = _openapi_response_schema(operation, source)
            requirements = operation.get("security", source.get("security", []))
            auth_schemes = _security_scheme_names(requirements)
            declared_schemes = _declared_security_schemes(source)
            consume_fields = _contract_field_names(request_schema, document=source)
            consume_fields = frozenset({*consume_fields, *request_fields})
            produce_fields = _contract_field_names(response_schema, document=source)
            key = f"{str(method).upper()} {path}"
            tools[key] = ToolExpectation(
                key=key,
                request_schema=request_schema,
                response_schema=response_schema,
                request_signatures=schema_signatures(request_schema, document=source),
                response_signatures=schema_signatures(response_schema, document=source),
                request_fields=request_fields,
                consume_fields=consume_fields,
                produce_fields=produce_fields,
                auth_schemes=auth_schemes or frozenset(declared_schemes),
                required_auth_schemes=auth_schemes,
                auth_scheme_facts=frozenset(
                    normalized_auth_scheme_fact(name, scheme)
                    for name, scheme in declared_schemes.items()
                ),
                auth_requirements=normalized_auth_requirements(requirements),
                execution_transport="http",
                consumes_expected=bool(consume_fields or auth_schemes),
                produces_expected=bool(produce_fields),
            )
    return SourceExpectations(source_type="openapi", tools=tools)


def _inspect_graphql(
    source: Any,
    *,
    ingest_options: dict[str, Any],
) -> SourceExpectations:
    if not isinstance(source, dict):
        raise TypeError("GraphQL conformance source must be an object.")
    payload = source.get("data") if isinstance(source.get("data"), dict) else source
    schema = payload.get("__schema") if isinstance(payload, dict) else None
    if not isinstance(schema, dict):
        return SourceExpectations(source_type="graphql-introspection")
    type_index = {
        row["name"]: row
        for row in schema.get("types") or []
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    include_deprecated = bool(ingest_options.get("include_deprecated", False))
    max_selection_depth = int(ingest_options.get("max_selection_depth", 2))
    max_selection_fields = int(ingest_options.get("max_selection_fields", 24))
    tools: dict[str, ToolExpectation] = {}
    roots = (
        ("query", schema.get("queryType")),
        ("mutation", schema.get("mutationType")),
        ("subscription", schema.get("subscriptionType")),
    )
    for operation_type, root_ref in roots:
        root_name = root_ref.get("name") if isinstance(root_ref, dict) else None
        root = type_index.get(root_name) if isinstance(root_name, str) else None
        if not isinstance(root, dict):
            continue
        for field_row in root.get("fields") or []:
            if not isinstance(field_row, dict) or not isinstance(field_row.get("name"), str):
                continue
            if bool(field_row.get("isDeprecated")) and not include_deprecated:
                continue
            field_name = str(field_row["name"])
            request_fields = frozenset(
                str(argument["name"])
                for argument in field_row.get("args") or []
                if isinstance(argument, dict) and isinstance(argument.get("name"), str)
            )
            request_field_types = frozenset(
                (
                    str(argument["name"]),
                    _graphql_json_type(argument.get("type"), type_index),
                    _graphql_required(argument),
                )
                for argument in field_row.get("args") or []
                if isinstance(argument, dict) and isinstance(argument.get("name"), str)
            )
            consume_fields: set[str] = set()
            for argument in field_row.get("args") or []:
                if not isinstance(argument, dict) or not isinstance(argument.get("name"), str):
                    continue
                consume_fields.update(
                    _graphql_input_contract_fields(
                        str(argument["name"]),
                        argument.get("type"),
                        type_index,
                        include_deprecated=include_deprecated,
                        seen=frozenset(),
                    )
                )
            return_type = _graphql_type_signature(field_row.get("type"))
            produce_fields = _graphql_output_contract_fields(
                field_row.get("type"),
                type_index,
                include_deprecated=include_deprecated,
                max_selection_depth=max_selection_depth,
                max_selection_fields=max_selection_fields,
                depth=0,
                seen=frozenset(),
                fallback_name=field_name,
            )
            key = f"{operation_type}:{field_name}"
            tools[key] = ToolExpectation(
                key=key,
                request_schema={"type": "object"},
                response_schema={"type": "graphql-result"},
                request_fields=request_fields,
                request_field_types=request_field_types,
                consume_fields=frozenset(consume_fields),
                produce_fields=produce_fields,
                execution_transport=(
                    "graphql-subscription" if operation_type == "subscription" else "graphql-http"
                ),
                graphql_return_type=return_type,
                graphql_response_root_type=_graphql_json_type(
                    field_row.get("type"),
                    type_index,
                ),
                consumes_expected=bool(consume_fields),
                produces_expected=bool(produce_fields),
            )
    return SourceExpectations(source_type="graphql-introspection", tools=tools)


def _inspect_mcp(source: Any) -> SourceExpectations:
    rows = source.get("tools") if isinstance(source, dict) else source
    if not isinstance(rows, list):
        raise TypeError("MCP conformance source must contain a tools list.")
    tools: dict[str, ToolExpectation] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            continue
        input_schema = row.get("inputSchema")
        output_schema = row.get("outputSchema")
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        if not isinstance(output_schema, dict):
            output_schema = None
        request_fields = frozenset(
            str(name) for name in (input_schema.get("properties") or {}) if isinstance(name, str)
        )
        consume_fields = _contract_field_names(input_schema)
        produce_fields = _contract_field_names(output_schema)
        name = str(row["name"])
        tools[name] = ToolExpectation(
            key=name,
            request_schema=input_schema,
            response_schema=output_schema,
            request_signatures=schema_signatures(input_schema),
            response_signatures=schema_signatures(output_schema),
            request_fields=request_fields,
            consume_fields=consume_fields,
            produce_fields=produce_fields,
            execution_transport="mcp",
            consumes_expected=bool(consume_fields),
            produces_expected=bool(produce_fields),
        )
    return SourceExpectations(source_type="mcp", tools=tools)


def _openapi_request_schema(
    operation: dict[str, Any],
    parameters: list[dict[str, Any]],
    document: dict[str, Any],
) -> dict[str, Any] | None:
    request_body = _resolve_mapping(operation.get("requestBody"), document)
    if isinstance(request_body, dict):
        content = request_body.get("content")
        if isinstance(content, dict):
            for media_type in sorted(content, key=_content_type_priority):
                media = _resolve_mapping(content.get(media_type), document)
                schema = _resolve_mapping(
                    media.get("schema") if isinstance(media, dict) else None,
                    document,
                )
                if isinstance(schema, dict):
                    return schema
    for row in parameters:
        if row.get("in") == "body":
            schema = _resolve_mapping(row.get("schema"), document)
            if isinstance(schema, dict):
                return schema
    return None


def _openapi_response_schema(
    operation: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any] | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    statuses = sorted(
        responses,
        key=lambda value: (not str(value).startswith("2"), str(value) == "default", str(value)),
    )
    for status in statuses:
        if not (str(status).startswith("2") or str(status) == "default"):
            continue
        response = _resolve_mapping(responses.get(status), document)
        if not isinstance(response, dict):
            continue
        schema = _resolve_mapping(response.get("schema"), document)
        if isinstance(schema, dict):
            return schema
        content = response.get("content")
        if isinstance(content, dict):
            for media_type in sorted(content, key=_content_type_priority):
                media = _resolve_mapping(content.get(media_type), document)
                schema = _resolve_mapping(
                    media.get("schema") if isinstance(media, dict) else None,
                    document,
                )
                if isinstance(schema, dict):
                    return schema
    return None


def _parameter_rows(value: Any, document: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        resolved for row in value if isinstance((resolved := _resolve_mapping(row, document)), dict)
    ]


def _merge_parameter_rows(
    path_rows: list[dict[str, Any]],
    operation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*path_rows, *operation_rows]:
        key = (str(row.get("name") or ""), str(row.get("in") or ""))
        merged[key] = row
    return list(merged.values())


def _security_scheme_names(requirements: Any) -> frozenset[str]:
    if not isinstance(requirements, list):
        return frozenset()
    return frozenset(
        str(name)
        for requirement in requirements
        if isinstance(requirement, dict)
        for name in requirement
    )


def _declared_security_schemes(document: dict[str, Any]) -> dict[str, Any]:
    schemes = (
        (document.get("components") or {}).get("securitySchemes")
        if isinstance(document.get("components"), dict)
        else None
    )
    if not isinstance(schemes, dict):
        schemes = document.get("securityDefinitions")
    if not isinstance(schemes, dict):
        return {}
    return {str(name): row for name, row in schemes.items()}


def _contract_field_names(
    schema: dict[str, Any] | None,
    *,
    document: dict[str, Any] | None = None,
) -> frozenset[str]:
    fields = {
        field_name
        for path, field_type in schema_signatures(schema, document=document)
        if (path, field_type) not in {("$", "object"), ("$", "unknown")}
        if (field_name := _contract_field_name(path))
    }
    return frozenset(fields)


def _contract_field_name(path: str) -> str:
    if path in {"$", "$[]", "$.*"}:
        return "body"
    normalized = path
    while normalized.endswith("[]"):
        normalized = normalized[:-2]
    if normalized.endswith(".*"):
        normalized = normalized[:-2]
    name = normalized.rsplit(".", 1)[-1]
    return name if name and name != "$" else "body"


def _graphql_type_signature(type_ref: Any) -> str:
    if not isinstance(type_ref, dict):
        return ""
    kind = str(type_ref.get("kind") or "")
    if kind == "NON_NULL":
        return f"{_graphql_type_signature(type_ref.get('ofType'))}!"
    if kind == "LIST":
        return f"[{_graphql_type_signature(type_ref.get('ofType'))}]"
    return str(type_ref.get("name") or "")


def _graphql_json_type(
    type_ref: Any,
    type_index: dict[str, dict[str, Any]],
) -> str:
    current = type_ref
    while isinstance(current, dict) and current.get("kind") == "NON_NULL":
        current = current.get("ofType")
    if not isinstance(current, dict):
        return "string"
    if current.get("kind") == "LIST":
        return "array"
    name = str(current.get("name") or "")
    kind = str(current.get("kind") or (type_index.get(name) or {}).get("kind") or "")
    if kind == "ENUM":
        return "string"
    if kind in {"INPUT_OBJECT", "INTERFACE", "OBJECT", "UNION"}:
        return "object"
    return {
        "Boolean": "boolean",
        "Float": "number",
        "Int": "integer",
    }.get(name, "string")


def _graphql_required(argument: dict[str, Any]) -> bool:
    type_ref = argument.get("type")
    return (
        isinstance(type_ref, dict)
        and type_ref.get("kind") == "NON_NULL"
        and argument.get("defaultValue") is None
    )


def _graphql_input_contract_fields(
    fallback_name: str,
    type_ref: Any,
    type_index: dict[str, dict[str, Any]],
    *,
    include_deprecated: bool,
    seen: frozenset[str],
) -> frozenset[str]:
    kind, name = _graphql_named_type(type_ref)
    if kind != "INPUT_OBJECT" or not name or name in seen:
        return frozenset({fallback_name})
    row = type_index.get(name) or {}
    fields: set[str] = set()
    for child in row.get("inputFields") or []:
        if not isinstance(child, dict) or not isinstance(child.get("name"), str):
            continue
        if bool(child.get("isDeprecated")) and not include_deprecated:
            continue
        child_name = str(child["name"])
        fields.update(
            _graphql_input_contract_fields(
                child_name,
                child.get("type"),
                type_index,
                include_deprecated=include_deprecated,
                seen=seen | {name},
            )
        )
    return frozenset(fields or {fallback_name})


def _graphql_output_contract_fields(
    type_ref: Any,
    type_index: dict[str, dict[str, Any]],
    *,
    include_deprecated: bool,
    max_selection_depth: int,
    max_selection_fields: int,
    depth: int,
    seen: frozenset[str],
    fallback_name: str,
) -> frozenset[str]:
    kind, name = _graphql_named_type(type_ref)
    if kind in {"SCALAR", "ENUM"} or not name:
        return frozenset({fallback_name})
    if kind not in {"INTERFACE", "OBJECT", "UNION"}:
        return frozenset({fallback_name})
    if name in seen or depth > max_selection_depth:
        return frozenset()

    if kind == "UNION":
        possible_types = [
            type_index.get(str(row.get("name") or ""))
            for row in (type_index.get(name) or {}).get("possibleTypes") or []
            if isinstance(row, dict)
        ][:max_selection_fields]
        source_fields = [
            child_field
            for possible in possible_types
            if isinstance(possible, dict)
            for child_field in possible.get("fields") or []
        ]
    else:
        source_fields = list((type_index.get(name) or {}).get("fields") or [])

    selectable = []
    for source_field in source_fields:
        if not isinstance(source_field, dict) or not isinstance(source_field.get("name"), str):
            continue
        if bool(source_field.get("isDeprecated")) and not include_deprecated:
            continue
        if any(
            _graphql_required(argument)
            for argument in source_field.get("args") or []
            if isinstance(argument, dict)
        ):
            continue
        selectable.append(source_field)

    fields: set[str] = set()
    for child in selectable[:max_selection_fields]:
        child_name = str(child["name"])
        fields.update(
            _graphql_output_contract_fields(
                child.get("type"),
                type_index,
                include_deprecated=include_deprecated,
                max_selection_depth=max_selection_depth,
                max_selection_fields=max_selection_fields,
                depth=depth + 1,
                seen=seen | {name},
                fallback_name=child_name,
            )
        )
    return frozenset(fields)


def _graphql_named_type(type_ref: Any) -> tuple[str, str]:
    current = type_ref
    while isinstance(current, dict) and current.get("kind") in {"LIST", "NON_NULL"}:
        current = current.get("ofType")
    if not isinstance(current, dict):
        return "", ""
    return str(current.get("kind") or ""), str(current.get("name") or "")


def _resolve_mapping(value: Any, document: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    ref = value.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return value
    current: Any = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return value
        current = current[part]
    return current if isinstance(current, dict) else value


def _collect_schema_signatures(
    schema: Any,
    *,
    document: dict[str, Any],
    path: str,
    signatures: set[tuple[str, str]],
    ref_stack: tuple[str, ...],
    depth: int,
) -> None:
    if not isinstance(schema, dict) or depth > 12:
        return
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        if ref in ref_stack:
            return
        resolved = _resolve_mapping(schema, document)
        if resolved is not schema:
            _collect_schema_signatures(
                resolved,
                document=document,
                path=path,
                signatures=signatures,
                ref_stack=(*ref_stack, ref),
                depth=depth + 1,
            )
            return
        return

    has_structural_children = False
    properties = schema.get("properties")
    if isinstance(properties, dict):
        has_structural_children = bool(properties)
        for name, child in sorted(properties.items()):
            _collect_schema_signatures(
                child,
                document=document,
                path=f"{path}.{name}",
                signatures=signatures,
                ref_stack=ref_stack,
                depth=depth + 1,
            )
    items = schema.get("items")
    if isinstance(items, dict):
        has_structural_children = True
        _collect_schema_signatures(
            items,
            document=document,
            path=f"{path}[]",
            signatures=signatures,
            ref_stack=ref_stack,
            depth=depth + 1,
        )
    additional_properties = schema.get("additionalProperties")
    if isinstance(additional_properties, dict):
        has_structural_children = True
        _collect_schema_signatures(
            additional_properties,
            document=document,
            path=f"{path}.*",
            signatures=signatures,
            ref_stack=ref_stack,
            depth=depth + 1,
        )
    for keyword in ("allOf", "anyOf", "oneOf"):
        rows = schema.get(keyword)
        if isinstance(rows, list):
            has_structural_children = has_structural_children or any(
                isinstance(child, dict) for child in rows
            )
            for child in rows:
                _collect_schema_signatures(
                    child,
                    document=document,
                    path=path,
                    signatures=signatures,
                    ref_stack=ref_stack,
                    depth=depth + 1,
                )
    if not has_structural_children:
        schema_type = schema.get("type")
        if isinstance(schema_type, str):
            signatures.add((path, schema_type))
        elif isinstance(properties, dict):
            signatures.add((path, "object"))


def _content_type_priority(value: str) -> tuple[int, str]:
    lowered = str(value).lower()
    return (
        0 if lowered == "application/json" else 1 if lowered.endswith("+json") else 2,
        lowered,
    )
