"""Convert standard GraphQL introspection results into executable ToolSchema objects."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from graph_tool_call.core.tool import MCPAnnotations, ToolParameter, ToolSchema
from graph_tool_call.ingest.adapters import (
    GraphQLIntrospectionIngestAdapter,
    IngestIssue,
    IngestResult,
)

_GRAPHQL_CAPABILITIES = GraphQLIntrospectionIngestAdapter.capabilities

_SCALAR_JSON_TYPES = {
    "Boolean": "boolean",
    "Float": "number",
    "ID": "string",
    "Int": "integer",
    "String": "string",
}

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "client_secret",
        "credential",
        "id_token",
        "jwt",
        "key",
        "password",
        "refresh_token",
        "secret",
        "session",
        "signature",
        "sig",
        "token",
    }
)
_SENSITIVE_QUERY_SUFFIXES = (
    "_api_key",
    "_credential",
    "_password",
    "_secret",
    "_signature",
    "_token",
)
_GRAPHQL_NAME_RE = re.compile(r"^[_A-Za-z][_0-9A-Za-z]*$")


def is_graphql_introspection(source: Any) -> bool:
    """Return whether *source* has the standard GraphQL introspection envelope."""

    document = _coerce_document(source, raise_errors=False)
    return _schema_payload(document) is not None


def ingest_graphql_introspection(
    source: Any,
    *,
    endpoint_url: str | None = None,
    include_deprecated: bool = False,
    max_selection_depth: int = 2,
    max_selection_fields: int = 24,
) -> IngestResult:
    """Build one canonical tool per GraphQL root field.

    Introspection describes a schema but does not contain the service endpoint.
    ``endpoint_url`` is therefore explicit. Without it, tools remain inspectable
    but the result carries a stable blocker and is not execution-ready.
    """

    if max_selection_depth < 0:
        raise ValueError("max_selection_depth must be >= 0")
    if max_selection_fields < 1:
        raise ValueError("max_selection_fields must be >= 1")

    document = _coerce_document(source, raise_errors=True)
    schema = _schema_payload(document)
    if schema is None:
        return IngestResult(
            tools=[],
            adapter="graphql-introspection",
            capabilities=_GRAPHQL_CAPABILITIES,
            issues=[
                IngestIssue(
                    severity="blocker",
                    code="invalid_graphql_introspection",
                    message="Source does not contain a standard GraphQL __schema payload.",
                )
            ],
        )

    issues: list[IngestIssue] = []
    endpoint = _normalize_endpoint(endpoint_url, issues)
    if endpoint is None and not any(issue.code == "graphql_endpoint_invalid" for issue in issues):
        issues.append(
            IngestIssue(
                severity="blocker",
                code="graphql_endpoint_required",
                message=(
                    "GraphQL introspection does not include an endpoint URL. "
                    "Pass endpoint_url to make generated tools executable."
                ),
            )
        )

    errors = document.get("errors")
    if isinstance(errors, list) and errors:
        issues.append(
            IngestIssue(
                severity="warning",
                code="graphql_introspection_partial_errors",
                message="The introspection response contained errors alongside schema data.",
                evidence={"count": len(errors)},
            )
        )

    type_index = {
        row["name"]: row
        for row in schema.get("types") or []
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    builder = _GraphQLSchemaBuilder(
        type_index,
        include_deprecated=include_deprecated,
        max_selection_depth=max_selection_depth,
        max_selection_fields=max_selection_fields,
    )

    tools: list[ToolSchema] = []
    operation_counts: Counter[str] = Counter()
    skipped_deprecated = 0
    root_specs = (
        ("query", schema.get("queryType")),
        ("mutation", schema.get("mutationType")),
        ("subscription", schema.get("subscriptionType")),
    )
    for operation_type, root_ref in root_specs:
        root_name = root_ref.get("name") if isinstance(root_ref, dict) else None
        root = type_index.get(root_name) if isinstance(root_name, str) else None
        if not isinstance(root, dict):
            continue
        for field in root.get("fields") or []:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            if bool(field.get("isDeprecated")) and not include_deprecated:
                skipped_deprecated += 1
                continue
            if not _valid_operation_field(field):
                issues.append(
                    IngestIssue(
                        severity="blocker",
                        code="invalid_graphql_operation",
                        message=(
                            "A GraphQL root field contains an invalid name or "
                            "incomplete argument type reference."
                        ),
                        evidence={"operation_type": operation_type},
                    )
                )
                continue
            tool = builder.build_tool(
                operation_type=operation_type,
                root_type=root_name,
                field=field,
                endpoint=endpoint,
            )
            tools.append(tool)
            operation_counts[operation_type] += 1
            if operation_type == "subscription":
                issues.append(
                    IngestIssue(
                        severity="warning",
                        code="graphql_subscription_transport_required",
                        message=(
                            "Subscription fields require an application-provided "
                            "GraphQL subscription transport."
                        ),
                        tool=tool.name,
                        evidence={"transport": "graphql-subscription"},
                    )
                )

    if skipped_deprecated:
        issues.append(
            IngestIssue(
                severity="warning",
                code="graphql_deprecated_fields_skipped",
                message="Deprecated GraphQL root fields were excluded from the tool catalog.",
                evidence={"count": skipped_deprecated},
            )
        )

    metadata = {
        "schema_description": str(schema.get("description") or ""),
        "schema_fingerprint": _schema_fingerprint(schema),
        "operation_counts": dict(sorted(operation_counts.items())),
        "type_count": len(type_index),
        "endpoint_configured": endpoint is not None,
        "introspection_errors": len(errors) if isinstance(errors, list) else 0,
    }
    return IngestResult(
        tools=tools,
        adapter="graphql-introspection",
        capabilities=_GRAPHQL_CAPABILITIES,
        issues=issues,
        metadata=metadata,
    )


class _GraphQLSchemaBuilder:
    def __init__(
        self,
        type_index: dict[str, dict[str, Any]],
        *,
        include_deprecated: bool,
        max_selection_depth: int,
        max_selection_fields: int,
    ) -> None:
        self.type_index = type_index
        self.include_deprecated = include_deprecated
        self.max_selection_depth = max_selection_depth
        self.max_selection_fields = max_selection_fields

    def build_tool(
        self,
        *,
        operation_type: str,
        root_type: str,
        field: dict[str, Any],
        endpoint: str | None,
    ) -> ToolSchema:
        field_name = str(field["name"])
        operation_name = f"Gtc{_pascal_case(operation_type)}{_pascal_case(field_name)}"
        arguments = [
            argument
            for argument in field.get("args") or []
            if isinstance(argument, dict) and isinstance(argument.get("name"), str)
        ]
        variable_schema = self._arguments_schema(arguments)
        parameters = [
            ToolParameter(
                name=str(argument["name"]),
                type=str(
                    variable_schema["properties"]
                    .get(str(argument["name"]), {})
                    .get("type", "string")
                ),
                description=str(argument.get("description") or ""),
                required=str(argument["name"]) in set(variable_schema.get("required") or []),
                enum=_enum_values(variable_schema["properties"].get(str(argument["name"]), {})),
            )
            for argument in arguments
        ]
        response_value_schema = self.output_schema(field.get("type"), depth=0, seen=set())
        response_schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {field_name: response_value_schema},
                    "required": [field_name],
                    "additionalProperties": False,
                }
            },
            "required": ["data"],
            "additionalProperties": False,
        }
        document = self.operation_document(
            operation_type=operation_type,
            operation_name=operation_name,
            field=field,
        )
        read_only = operation_type == "query"
        transport = "graphql-subscription" if operation_type == "subscription" else "graphql-http"
        execution: dict[str, Any] = {
            "transport": transport,
            "method": "POST",
            "endpoint": endpoint,
            "content_type": "application/json",
            "body_template": {
                "query": document,
                "operationName": operation_name,
            },
            "variable_binding": "arguments_to_variables",
            "result_path": ["data", field_name],
            "read_only": read_only,
        }
        if operation_type == "subscription":
            execution["executable"] = False

        base_url, path = _endpoint_parts(endpoint)
        from graph_tool_call.graphify.io_contract import build_io_contract

        produces, consumes = build_io_contract(
            request_body_schema=variable_schema,
            response_schema=response_schema,
        )
        graphql_metadata = {
            "operation_type": operation_type,
            "root_type": root_type,
            "root_field": field_name,
            "operation_name": operation_name,
            "document": document,
            "variables_schema": variable_schema,
            "return_type": _type_signature(field.get("type")),
            "deprecated": bool(field.get("isDeprecated")),
            "deprecation_reason": field.get("deprecationReason"),
        }
        metadata: dict[str, Any] = {
            "source": "graphql-introspection",
            "method": "POST",
            "path": path,
            "base_url": base_url,
            "request_body_schema": variable_schema,
            "request_content_type": "application/json",
            "response_schema": response_schema,
            "response_content_type": "application/json",
            "input_locations": ["graphql_variable"] if arguments else [],
            "api_contract": {
                "produces": produces,
                "consumes": consumes,
                "links": [],
            },
            "graphql": graphql_metadata,
            "execution": execution,
        }
        return ToolSchema(
            name=f"{operation_type}_{field_name}",
            description=(
                str(field.get("description") or "").strip()
                or f"GraphQL {operation_type} field {field_name}."
            ),
            parameters=parameters,
            tags=[operation_type, root_type],
            domain=root_type,
            metadata=metadata,
            annotations=_operation_annotations(operation_type),
        )

    def _arguments_schema(self, arguments: list[dict[str, Any]]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for argument in arguments:
            name = str(argument["name"])
            properties[name] = self.input_schema(argument.get("type"), seen=set())
            description = str(argument.get("description") or "").strip()
            if description:
                properties[name]["description"] = description
            default_literal = argument.get("defaultValue")
            if default_literal is not None:
                properties[name]["x-graphql-default-literal"] = str(default_literal)
            if _is_non_null(argument.get("type")) and default_literal is None:
                required.append(name)
        result: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            result["required"] = required
        return result

    def input_schema(
        self,
        type_ref: Any,
        *,
        seen: set[str],
        nullable: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(type_ref, dict):
            return {"type": "string", "x-graphql-type": "Unknown"}
        kind = type_ref.get("kind")
        if kind == "NON_NULL":
            return self.input_schema(type_ref.get("ofType"), seen=seen, nullable=False)
        if kind == "LIST":
            result = {
                "type": "array",
                "items": self.input_schema(type_ref.get("ofType"), seen=seen),
            }
            return _with_nullable(result, nullable)
        name = str(type_ref.get("name") or "Unknown")
        if kind == "SCALAR":
            return _with_nullable(
                {
                    "type": _SCALAR_JSON_TYPES.get(name, "string"),
                    "x-graphql-scalar": name,
                },
                nullable,
            )
        if kind == "ENUM":
            return _with_nullable(
                {
                    "type": "string",
                    "enum": self._enum_values(name),
                    "x-graphql-type": name,
                },
                nullable,
            )
        if kind == "INPUT_OBJECT":
            if name in seen:
                return _with_nullable(
                    {
                        "type": "object",
                        "x-graphql-type": name,
                        "x-graphql-recursive": True,
                    },
                    nullable,
                )
            row = self.type_index.get(name) or {}
            properties: dict[str, Any] = {}
            required: list[str] = []
            next_seen = {*seen, name}
            for input_field in row.get("inputFields") or []:
                if not isinstance(input_field, dict) or not input_field.get("name"):
                    continue
                if bool(input_field.get("isDeprecated")) and not self.include_deprecated:
                    continue
                field_name = str(input_field["name"])
                child = self.input_schema(input_field.get("type"), seen=next_seen)
                description = str(input_field.get("description") or "").strip()
                if description:
                    child["description"] = description
                default_literal = input_field.get("defaultValue")
                if default_literal is not None:
                    child["x-graphql-default-literal"] = str(default_literal)
                if _is_non_null(input_field.get("type")) and default_literal is None:
                    required.append(field_name)
                properties[field_name] = child
            result: dict[str, Any] = {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
                "x-graphql-type": name,
            }
            if required:
                result["required"] = required
            return _with_nullable(result, nullable)
        return _with_nullable(
            {"type": "string", "x-graphql-type": name},
            nullable,
        )

    def output_schema(
        self,
        type_ref: Any,
        *,
        depth: int,
        seen: set[str],
        nullable: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(type_ref, dict):
            return {"type": "string", "x-graphql-type": "Unknown"}
        kind = type_ref.get("kind")
        if kind == "NON_NULL":
            return self.output_schema(
                type_ref.get("ofType"),
                depth=depth,
                seen=seen,
                nullable=False,
            )
        if kind == "LIST":
            result = {
                "type": "array",
                "items": self.output_schema(
                    type_ref.get("ofType"),
                    depth=depth,
                    seen=seen,
                ),
            }
            return _with_nullable(result, nullable)
        name = str(type_ref.get("name") or "Unknown")
        if kind == "SCALAR":
            return _with_nullable(
                {
                    "type": _SCALAR_JSON_TYPES.get(name, "string"),
                    "x-graphql-scalar": name,
                },
                nullable,
            )
        if kind == "ENUM":
            return _with_nullable(
                {
                    "type": "string",
                    "enum": self._enum_values(name),
                    "x-graphql-type": name,
                },
                nullable,
            )
        if kind == "UNION":
            union_row = self.type_index.get(name) or {}
            possible_schemas = [
                self.output_schema(
                    possible_type,
                    depth=depth,
                    seen=seen,
                    nullable=False,
                )
                for possible_type in union_row.get("possibleTypes") or []
                if isinstance(possible_type, dict)
            ]
            result: dict[str, Any] = {
                "oneOf": possible_schemas
                or [
                    {
                        "type": "object",
                        "properties": {"__typename": {"type": "string"}},
                    }
                ],
                "x-graphql-type": name,
            }
            return _with_nullable(result, nullable)
        if kind in {"OBJECT", "INTERFACE"}:
            if name in seen or depth > self.max_selection_depth:
                return _with_nullable(
                    {
                        "type": "object",
                        "properties": {"__typename": {"type": "string"}},
                        "x-graphql-type": name,
                    },
                    nullable,
                )
            fields = self._selectable_fields(name)
            properties: dict[str, Any] = {"__typename": {"type": "string"}}
            next_seen = {*seen, name}
            for child in fields[: self.max_selection_fields]:
                properties[str(child["name"])] = self.output_schema(
                    child.get("type"),
                    depth=depth + 1,
                    seen=next_seen,
                )
            return _with_nullable(
                {
                    "type": "object",
                    "properties": properties,
                    "additionalProperties": False,
                    "x-graphql-type": name,
                },
                nullable,
            )
        return _with_nullable(
            {"type": "string", "x-graphql-type": name},
            nullable,
        )

    def operation_document(
        self,
        *,
        operation_type: str,
        operation_name: str,
        field: dict[str, Any],
    ) -> str:
        arguments = [
            argument
            for argument in field.get("args") or []
            if isinstance(argument, dict) and isinstance(argument.get("name"), str)
        ]
        variable_definitions = ", ".join(
            f"${argument['name']}: {_type_signature(argument.get('type'))}"
            for argument in arguments
        )
        operation_header = f"{operation_type} {operation_name}"
        if variable_definitions:
            operation_header += f"({variable_definitions})"
        invocation = str(field["name"])
        if arguments:
            assignments = ", ".join(
                f"{argument['name']}: ${argument['name']}" for argument in arguments
            )
            invocation += f"({assignments})"
        selection = self.selection_set(field.get("type"), depth=0, seen=set())
        lines = [f"{operation_header} {{", f"  {invocation}"]
        if selection:
            lines[-1] += " {"
            lines.extend(f"    {line}" for line in selection)
            lines.append("  }")
        lines.append("}")
        return "\n".join(lines)

    def selection_set(
        self,
        type_ref: Any,
        *,
        depth: int,
        seen: set[str],
    ) -> list[str]:
        named_kind, name = _named_type(type_ref)
        if named_kind in {"SCALAR", "ENUM"} or not name:
            return []
        if depth > self.max_selection_depth or name in seen:
            return ["__typename"]

        lines = ["__typename"]
        next_seen = {*seen, name}
        if named_kind == "UNION":
            row = self.type_index.get(name) or {}
            for possible_type in (row.get("possibleTypes") or [])[: self.max_selection_fields]:
                if not isinstance(possible_type, dict):
                    continue
                possible_name = possible_type.get("name")
                if not isinstance(possible_name, str) or not _is_graphql_name(possible_name):
                    continue
                nested = self._concrete_selection(
                    possible_name,
                    depth=depth + 1,
                    seen=next_seen,
                )
                lines.append(f"... on {possible_name} {{")
                lines.extend(f"  {line}" for line in nested)
                lines.append("}")
            return lines
        fields = self._selectable_fields(name)[: self.max_selection_fields]
        for field in fields:
            field_name = str(field["name"])
            child_kind, _child_name = _named_type(field.get("type"))
            if child_kind in {"SCALAR", "ENUM"}:
                lines.append(field_name)
                continue
            if depth >= self.max_selection_depth:
                continue
            nested = self.selection_set(
                field.get("type"),
                depth=depth + 1,
                seen=next_seen,
            )
            if nested:
                lines.append(f"{field_name} {{")
                lines.extend(f"  {line}" for line in nested)
                lines.append("}")
        return lines

    def _concrete_selection(
        self,
        type_name: str,
        *,
        depth: int,
        seen: set[str],
    ) -> list[str]:
        lines = ["__typename"]
        for field in self._selectable_fields(type_name)[: self.max_selection_fields]:
            field_name = str(field["name"])
            child_kind, _child_name = _named_type(field.get("type"))
            if child_kind in {"SCALAR", "ENUM"}:
                lines.append(field_name)
            elif depth <= self.max_selection_depth:
                nested = self.selection_set(
                    field.get("type"),
                    depth=depth,
                    seen=seen,
                )
                if nested:
                    lines.append(f"{field_name} {{")
                    lines.extend(f"  {line}" for line in nested)
                    lines.append("}")
        return lines

    def _selectable_fields(self, type_name: str) -> list[dict[str, Any]]:
        row = self.type_index.get(type_name) or {}
        result: list[dict[str, Any]] = []
        for field in row.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            if not _is_graphql_name(str(field["name"])):
                continue
            if bool(field.get("isDeprecated")) and not self.include_deprecated:
                continue
            required_arguments = [
                argument
                for argument in field.get("args") or []
                if isinstance(argument, dict)
                and _is_non_null(argument.get("type"))
                and argument.get("defaultValue") is None
            ]
            if required_arguments:
                continue
            result.append(field)
        return result

    def _enum_values(self, type_name: str) -> list[str]:
        row = self.type_index.get(type_name) or {}
        return [
            str(value["name"])
            for value in row.get("enumValues") or []
            if isinstance(value, dict)
            and value.get("name")
            and (self.include_deprecated or not value.get("isDeprecated"))
        ]


def _coerce_document(source: Any, *, raise_errors: bool) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    if isinstance(source, bytes):
        try:
            value = json.loads(source.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if raise_errors:
                raise ValueError("GraphQL introspection bytes must contain UTF-8 JSON") from None
            return {}
        return value if isinstance(value, dict) else {}
    if isinstance(source, str):
        text = source.strip()
        if text.startswith("{"):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                if raise_errors:
                    raise ValueError("GraphQL introspection text must contain valid JSON") from None
                return {}
            return value if isinstance(value, dict) else {}
        path = Path(source)
        try:
            is_file = len(source) <= 4096 and path.is_file()
        except OSError:
            is_file = False
        if is_file:
            if path.stat().st_size > 20 * 1024 * 1024:
                if raise_errors:
                    raise ValueError("GraphQL introspection file exceeds the 20 MB limit")
                return {}
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                if raise_errors:
                    raise ValueError(
                        "GraphQL introspection file must contain valid UTF-8 JSON"
                    ) from None
                return {}
            return value if isinstance(value, dict) else {}
    return {}


def _schema_payload(document: dict[str, Any]) -> dict[str, Any] | None:
    direct = document.get("__schema")
    if isinstance(direct, dict):
        return direct
    data = document.get("data")
    if isinstance(data, dict) and isinstance(data.get("__schema"), dict):
        return data["__schema"]
    return None


def _normalize_endpoint(
    endpoint_url: str | None,
    issues: list[IngestIssue],
) -> str | None:
    if endpoint_url is None or not endpoint_url.strip():
        return None
    value = endpoint_url.strip()
    parsed = urlsplit(value)
    sensitive_query_keys = sorted(
        {
            key
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
            if _is_sensitive_query_key(key)
        }
    )
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or sensitive_query_keys
    ):
        issues.append(
            IngestIssue(
                severity="blocker",
                code="graphql_endpoint_invalid",
                message=(
                    "GraphQL endpoint must be an absolute HTTP(S) URL without "
                    "userinfo credentials, sensitive query parameters, or a fragment."
                ),
                evidence={"sensitive_query_keys": sensitive_query_keys},
            )
        )
        return None
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/graphql",
            parsed.query,
            "",
        )
    )


def _endpoint_parts(endpoint: str | None) -> tuple[str | None, str]:
    if endpoint is None:
        return None, "/graphql"
    parsed = urlsplit(endpoint)
    base_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    path = parsed.path or "/graphql"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return base_url, path


def _named_type(type_ref: Any) -> tuple[str, str | None]:
    current = type_ref
    while isinstance(current, dict) and current.get("kind") in {"NON_NULL", "LIST"}:
        current = current.get("ofType")
    if not isinstance(current, dict):
        return "UNKNOWN", None
    return str(current.get("kind") or "UNKNOWN"), (
        str(current["name"]) if current.get("name") else None
    )


def _type_signature(type_ref: Any) -> str:
    if not isinstance(type_ref, dict):
        return "String"
    kind = type_ref.get("kind")
    if kind == "NON_NULL":
        return f"{_type_signature(type_ref.get('ofType'))}!"
    if kind == "LIST":
        return f"[{_type_signature(type_ref.get('ofType'))}]"
    return str(type_ref.get("name") or "String")


def _is_non_null(type_ref: Any) -> bool:
    return isinstance(type_ref, dict) and type_ref.get("kind") == "NON_NULL"


def _pascal_case(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    if not parts:
        return "Operation"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _enum_values(schema: Any) -> list[str] | None:
    if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
        return [str(value) for value in schema["enum"]]
    return None


def _normalized_query_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _is_sensitive_query_key(value: str) -> bool:
    normalized = _normalized_query_key(value)
    return normalized in _SENSITIVE_QUERY_KEYS or normalized.endswith(_SENSITIVE_QUERY_SUFFIXES)


def _with_nullable(schema: dict[str, Any], nullable: bool) -> dict[str, Any]:
    if nullable:
        schema["nullable"] = True
    return schema


def _is_graphql_name(value: str) -> bool:
    return bool(_GRAPHQL_NAME_RE.fullmatch(value))


def _valid_type_ref(type_ref: Any) -> bool:
    if not isinstance(type_ref, dict):
        return False
    kind = type_ref.get("kind")
    if kind in {"NON_NULL", "LIST"}:
        return _valid_type_ref(type_ref.get("ofType"))
    return kind in {
        "SCALAR",
        "OBJECT",
        "INTERFACE",
        "UNION",
        "ENUM",
        "INPUT_OBJECT",
    } and _is_graphql_name(str(type_ref.get("name") or ""))


def _valid_operation_field(field: dict[str, Any]) -> bool:
    if not _is_graphql_name(str(field.get("name") or "")):
        return False
    if not _valid_type_ref(field.get("type")):
        return False
    for argument in field.get("args") or []:
        if (
            not isinstance(argument, dict)
            or not _is_graphql_name(str(argument.get("name") or ""))
            or not _valid_type_ref(argument.get("type"))
        ):
            return False
    return True


def _schema_fingerprint(schema: dict[str, Any]) -> str:
    canonical = json.dumps(
        schema,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _operation_annotations(operation_type: str) -> MCPAnnotations:
    if operation_type == "query":
        return MCPAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    if operation_type == "mutation":
        return MCPAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=None,
            open_world_hint=True,
        )
    return MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=None,
        open_world_hint=True,
    )


__all__ = [
    "ingest_graphql_introspection",
    "is_graphql_introspection",
]
