"""Contract tests for GraphQL introspection ingestion."""

from __future__ import annotations

from typing import Any

from graph_tool_call import ingest_graphql_introspection, ingest_source


def _named(kind: str, name: str) -> dict[str, Any]:
    return {"kind": kind, "name": name, "ofType": None}


def _non_null(inner: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "NON_NULL", "name": None, "ofType": inner}


def _list(inner: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "LIST", "name": None, "ofType": inner}


def _input_value(
    name: str,
    type_ref: dict[str, Any],
    *,
    description: str = "",
    default_value: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "type": type_ref,
        "defaultValue": default_value,
        "isDeprecated": False,
        "deprecationReason": None,
    }


def _field(
    name: str,
    type_ref: dict[str, Any],
    *,
    description: str = "",
    args: list[dict[str, Any]] | None = None,
    deprecated: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "args": args or [],
        "type": type_ref,
        "isDeprecated": deprecated,
        "deprecationReason": "Use the replacement field" if deprecated else None,
    }


def _introspection() -> dict[str, Any]:
    return {
        "data": {
            "__schema": {
                "description": "Commerce graph",
                "queryType": {"name": "Query"},
                "mutationType": {"name": "Mutation"},
                "subscriptionType": {"name": "Subscription"},
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "description": "",
                        "fields": [
                            _field(
                                "customer",
                                _named("OBJECT", "Customer"),
                                description="Read one customer",
                                args=[
                                    _input_value(
                                        "id",
                                        _non_null(_named("SCALAR", "ID")),
                                        description="Customer identifier",
                                    )
                                ],
                            ),
                            _field(
                                "customers",
                                _non_null(_list(_non_null(_named("OBJECT", "Customer")))),
                                description="Search customers",
                                args=[
                                    _input_value(
                                        "filter",
                                        _named("INPUT_OBJECT", "CustomerFilter"),
                                    )
                                ],
                            ),
                            _field(
                                "legacyCustomer",
                                _named("OBJECT", "Customer"),
                                deprecated=True,
                            ),
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Mutation",
                        "description": "",
                        "fields": [
                            _field(
                                "updateCustomer",
                                _non_null(_named("OBJECT", "Customer")),
                                description="Update a customer",
                                args=[
                                    _input_value(
                                        "input",
                                        _non_null(_named("INPUT_OBJECT", "UpdateCustomerInput")),
                                    )
                                ],
                            )
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Subscription",
                        "description": "",
                        "fields": [
                            _field(
                                "customerChanged",
                                _named("OBJECT", "Customer"),
                            )
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Customer",
                        "description": "A customer",
                        "fields": [
                            _field("id", _non_null(_named("SCALAR", "ID"))),
                            _field("name", _named("SCALAR", "String")),
                            _field("status", _named("ENUM", "CustomerStatus")),
                            _field(
                                "orders",
                                _list(_named("OBJECT", "Order")),
                                args=[
                                    _input_value(
                                        "first",
                                        _non_null(_named("SCALAR", "Int")),
                                    )
                                ],
                            ),
                        ],
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Order",
                        "description": "",
                        "fields": [
                            _field("id", _non_null(_named("SCALAR", "ID"))),
                            _field("total", _named("SCALAR", "Float")),
                        ],
                    },
                    {
                        "kind": "INPUT_OBJECT",
                        "name": "CustomerFilter",
                        "description": "",
                        "inputFields": [
                            _input_value("status", _named("ENUM", "CustomerStatus")),
                            _input_value(
                                "tags",
                                _list(_non_null(_named("SCALAR", "String"))),
                            ),
                        ],
                    },
                    {
                        "kind": "INPUT_OBJECT",
                        "name": "UpdateCustomerInput",
                        "description": "",
                        "inputFields": [
                            _input_value(
                                "id",
                                _non_null(_named("SCALAR", "ID")),
                            ),
                            _input_value("name", _named("SCALAR", "String")),
                        ],
                    },
                    {
                        "kind": "ENUM",
                        "name": "CustomerStatus",
                        "description": "",
                        "enumValues": [
                            {
                                "name": "ACTIVE",
                                "description": "",
                                "isDeprecated": False,
                                "deprecationReason": None,
                            },
                            {
                                "name": "DISABLED",
                                "description": "",
                                "isDeprecated": False,
                                "deprecationReason": None,
                            },
                        ],
                    },
                    _named("SCALAR", "ID"),
                    _named("SCALAR", "String"),
                    _named("SCALAR", "Int"),
                    _named("SCALAR", "Float"),
                ],
                "directives": [],
            }
        }
    }


def test_graphql_introspection_is_detected_before_generic_catalog() -> None:
    result = ingest_source(
        _introspection(),
        endpoint_url="https://api.example.com/graphql",
    )

    assert result.adapter == "graphql-introspection"
    assert result.ready is True
    assert [tool.name for tool in result.tools] == [
        "query_customer",
        "query_customers",
        "mutation_updateCustomer",
        "subscription_customerChanged",
    ]
    assert result.capabilities.transports == frozenset({"graphql-http", "graphql-subscription"})
    assert result.metadata["operation_counts"] == {
        "mutation": 1,
        "query": 2,
        "subscription": 1,
    }
    assert result.metadata["schema_fingerprint"].startswith("sha256:")
    assert len(result.metadata["schema_fingerprint"]) == 71


def test_graphql_introspection_does_not_claim_auth_schema_capability() -> None:
    result = ingest_source(
        _introspection(),
        endpoint_url="https://api.example.com/graphql",
        required_capabilities={"authentication"},
    )

    assert result.ready is False
    issue = next(issue for issue in result.issues if issue.code == "unsupported_capability")
    assert issue.evidence["capability"] == "authentication"
    assert "authentication" not in result.capabilities.features


def test_graphql_query_preserves_variables_document_and_contract() -> None:
    result = ingest_graphql_introspection(
        _introspection(),
        endpoint_url="https://api.example.com/graphql",
    )
    tool = next(tool for tool in result.tools if tool.name == "query_customer")

    assert [
        (parameter.name, parameter.type, parameter.required) for parameter in tool.parameters
    ] == [("id", "string", True)]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.metadata["base_url"] == "https://api.example.com"
    assert tool.metadata["path"] == "/graphql"
    assert tool.metadata["method"] == "POST"
    assert tool.metadata["graphql"]["operation_type"] == "query"
    assert tool.metadata["graphql"]["root_field"] == "customer"
    assert tool.metadata["graphql"]["operation_name"] == "GtcQueryCustomer"
    assert tool.metadata["execution"] == {
        "transport": "graphql-http",
        "method": "POST",
        "endpoint": "https://api.example.com/graphql",
        "content_type": "application/json",
        "body_template": {
            "query": (
                "query GtcQueryCustomer($id: ID!) {\n"
                "  customer(id: $id) {\n"
                "    __typename\n"
                "    id\n"
                "    name\n"
                "    status\n"
                "  }\n"
                "}"
            ),
            "operationName": "GtcQueryCustomer",
        },
        "variable_binding": "arguments_to_variables",
        "result_path": ["data", "customer"],
        "read_only": True,
    }
    assert tool.metadata["request_body_schema"] == {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "x-graphql-scalar": "ID",
                "description": "Customer identifier",
            }
        },
        "required": ["id"],
        "additionalProperties": False,
    }
    assert tool.metadata["response_schema"]["properties"]["data"]["properties"]["customer"][
        "properties"
    ]["status"] == {
        "type": "string",
        "enum": ["ACTIVE", "DISABLED"],
        "x-graphql-type": "CustomerStatus",
        "nullable": True,
    }
    assert (
        tool.metadata["response_schema"]["properties"]["data"]["properties"]["customer"][
            "properties"
        ]["name"]["nullable"]
        is True
    )
    consumes = tool.metadata["api_contract"]["consumes"]
    produces = tool.metadata["api_contract"]["produces"]
    assert any(row["field_name"] == "id" and row["required"] for row in consumes)
    assert any(
        row["field_name"] == "status" and row["json_path"] == "$.data.customer.status"
        for row in produces
    )


def test_graphql_input_objects_and_mutations_keep_nested_schema() -> None:
    result = ingest_graphql_introspection(
        _introspection(),
        endpoint_url="https://api.example.com/graphql",
    )
    query_tool = next(tool for tool in result.tools if tool.name == "query_customers")
    mutation_tool = next(tool for tool in result.tools if tool.name == "mutation_updateCustomer")

    filter_schema = query_tool.metadata["request_body_schema"]["properties"]["filter"]
    assert filter_schema["properties"]["status"]["enum"] == ["ACTIVE", "DISABLED"]
    assert filter_schema["nullable"] is True
    assert filter_schema["properties"]["tags"] == {
        "type": "array",
        "items": {
            "type": "string",
            "x-graphql-scalar": "String",
        },
        "nullable": True,
    }
    mutation_input = mutation_tool.metadata["request_body_schema"]["properties"]["input"]
    assert mutation_input["required"] == ["id"]
    assert mutation_tool.annotations is not None
    assert mutation_tool.annotations.read_only_hint is False
    assert mutation_tool.annotations.destructive_hint is True
    assert mutation_tool.metadata["execution"]["read_only"] is False
    assert (
        "mutation GtcMutationUpdateCustomer($input: UpdateCustomerInput!)"
        in (mutation_tool.metadata["execution"]["body_template"]["query"])
    )


def test_missing_endpoint_is_a_stable_blocker_but_schema_remains_inspectable() -> None:
    result = ingest_source(_introspection(), format_hint="graphql-introspection")

    assert result.ready is False
    assert len(result.tools) == 4
    issue = next(issue for issue in result.issues if issue.code == "graphql_endpoint_required")
    assert issue.severity == "blocker"
    assert all(tool.metadata["execution"]["endpoint"] is None for tool in result.tools)


def test_endpoint_credentials_and_sensitive_query_values_are_never_persisted() -> None:
    for endpoint in (
        "https://user:password@api.example.com/graphql",
        "https://api.example.com/graphql?access-token=secret-value",
        "https://api.example.com/graphql?x-amz-signature=secret-value",
    ):
        result = ingest_graphql_introspection(_introspection(), endpoint_url=endpoint)

        assert result.ready is False
        issue = next(issue for issue in result.issues if issue.code == "graphql_endpoint_invalid")
        assert issue.severity == "blocker"
        serialized = str(result.to_dict(include_tools=True))
        assert "secret-value" not in serialized
        assert "user:password" not in serialized
        assert all(tool.metadata["execution"]["endpoint"] is None for tool in result.tools)


def test_deprecated_fields_are_hidden_by_default_and_reported() -> None:
    default_result = ingest_graphql_introspection(
        _introspection(),
        endpoint_url="https://api.example.com/graphql",
    )
    inclusive_result = ingest_graphql_introspection(
        _introspection(),
        endpoint_url="https://api.example.com/graphql",
        include_deprecated=True,
    )

    assert "query_legacyCustomer" not in [tool.name for tool in default_result.tools]
    assert "query_legacyCustomer" in [tool.name for tool in inclusive_result.tools]
    issue = next(
        issue
        for issue in default_result.issues
        if issue.code == "graphql_deprecated_fields_skipped"
    )
    assert issue.evidence == {"count": 1}


def test_subscription_tools_are_preserved_with_non_http_execution_diagnostic() -> None:
    result = ingest_graphql_introspection(
        _introspection(),
        endpoint_url="https://api.example.com/graphql",
    )
    subscription = next(
        tool for tool in result.tools if tool.name == "subscription_customerChanged"
    )

    assert subscription.metadata["execution"]["transport"] == "graphql-subscription"
    assert subscription.metadata["execution"]["executable"] is False
    issue = next(
        issue for issue in result.issues if issue.code == "graphql_subscription_transport_required"
    )
    assert issue.severity == "warning"
    assert issue.tool == subscription.name


def test_union_results_use_inline_fragments_and_one_of_schema() -> None:
    source = _introspection()
    schema = source["data"]["__schema"]
    query_type = next(row for row in schema["types"] if row.get("name") == "Query")
    query_type["fields"].append(
        _field(
            "search",
            _list(_named("UNION", "SearchResult")),
        )
    )
    schema["types"].append(
        {
            "kind": "UNION",
            "name": "SearchResult",
            "description": "",
            "possibleTypes": [
                _named("OBJECT", "Customer"),
                _named("OBJECT", "Order"),
            ],
        }
    )

    result = ingest_graphql_introspection(
        source,
        endpoint_url="https://api.example.com/graphql",
    )
    tool = next(tool for tool in result.tools if tool.name == "query_search")
    document = tool.metadata["execution"]["body_template"]["query"]
    result_schema = tool.metadata["response_schema"]["properties"]["data"]["properties"]["search"]

    assert "... on Customer {" in document
    assert "... on Order {" in document
    assert "name" in document
    assert "total" in document
    assert result_schema["type"] == "array"
    assert result_schema["nullable"] is True
    assert len(result_schema["items"]["oneOf"]) == 2


def test_invalid_graphql_names_cannot_inject_generated_documents() -> None:
    source = _introspection()
    query_type = next(
        row for row in source["data"]["__schema"]["types"] if row.get("name") == "Query"
    )
    query_type["fields"].append(
        _field(
            "customer) { secretField } #",
            _named("SCALAR", "String"),
        )
    )

    result = ingest_graphql_introspection(
        source,
        endpoint_url="https://api.example.com/graphql",
    )

    assert result.ready is False
    assert all("secretField" not in tool.name for tool in result.tools)
    assert any(issue.code == "invalid_graphql_operation" for issue in result.issues)
    assert "secretField" not in str(result.to_dict(include_tools=True))


def test_introspection_errors_are_counted_without_persisting_server_messages() -> None:
    source = _introspection()
    source["errors"] = [
        {
            "message": "Authorization bearer secret-value was rejected",
            "extensions": {"token": "secret-value"},
        }
    ]

    result = ingest_graphql_introspection(
        source,
        endpoint_url="https://api.example.com/graphql",
    )

    issue = next(
        issue for issue in result.issues if issue.code == "graphql_introspection_partial_errors"
    )
    assert issue.evidence == {"count": 1}
    serialized = str(result.to_dict(include_tools=True))
    assert "secret-value" not in serialized
