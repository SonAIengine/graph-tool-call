"""Tests for OpenAPI collection readiness reporting."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from graph_tool_call import ToolGraph
from graph_tool_call.analyze import analyze_openapi_collection
from graph_tool_call.core.tool import ToolParameter, ToolSchema


def _ready_crud_spec() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Ready Users API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["email"],
                                    "properties": {
                                        "email": {"type": "string"},
                                        "displayName": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "userId": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/users/{userId}": {
                "get": {
                    "operationId": "getUser",
                    "parameters": [
                        {
                            "name": "userId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "userId": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }


def test_analyze_openapi_collection_reports_contract_coverage() -> None:
    report = analyze_openapi_collection(_ready_crud_spec())
    payload = report.to_dict()

    assert payload["summary"]["tool_count"] == 2
    assert payload["summary"]["operation_count"] == 2
    assert payload["summary"]["status"] in {"ready", "warning"}
    assert payload["coverage"]["request_schema_tool_count"] == 1
    assert payload["coverage"]["response_schema_tool_count"] == 2
    assert payload["coverage"]["consumes_field_count"] >= 3
    assert payload["coverage"]["produces_field_count"] >= 4
    assert not any(issue["severity"] == "blocker" for issue in payload["issues"])


def test_readiness_accepts_persisted_openapi_contract_without_openapi_block() -> None:
    tool = ToolSchema(
        name="getMemberList",
        description="회원 목록 조회",
        parameters=[
            ToolParameter(name="loginId", type="string", required=True),
            ToolParameter(name="siteNo", type="integer", required=False),
        ],
        metadata={
            "source": "openapi",
            "method": "get",
            "path": "/v1/member/memberMgmt/getMemberList",
            "api_contract": {
                "consumes": [
                    {
                        "field_name": "loginId",
                        "field_type": "string",
                        "required": True,
                        "location": "query",
                        "kind": "data",
                    },
                    {
                        "field_name": "siteNo",
                        "field_type": "integer",
                        "required": False,
                        "location": "query",
                        "kind": "context",
                    },
                ],
                "produces": [
                    {
                        "field_name": "mbrNo",
                        "field_type": "string",
                        "json_path": "$.payloads[*].mbrNo",
                        "location": "response",
                    }
                ],
            },
        },
    )

    report = analyze_openapi_collection([tool], context_field_names={"siteNo"})

    assert report.summary["tool_count"] == 1
    assert report.summary["operation_count"] == 1
    assert report.summary["unique_operation_count"] == 1
    assert report.coverage["consumes_field_count"] == 2
    assert report.coverage["response_schema_tool_count"] == 1
    assert report.coverage["context_field_count"] == 1
    assert "missing_response_schema" not in {issue.code for issue in report.issues}


def test_readiness_does_not_treat_contract_only_tool_as_openapi_operation() -> None:
    tool = ToolSchema(
        name="localSearch",
        description="Local non-OpenAPI tool",
        parameters=[ToolParameter(name="keyword", type="string", required=True)],
        metadata={
            "api_contract": {
                "consumes": [
                    {
                        "field_name": "keyword",
                        "field_type": "string",
                        "required": True,
                        "location": "query",
                    }
                ],
                "produces": [
                    {
                        "field_name": "result",
                        "field_type": "string",
                        "location": "response",
                    }
                ],
            }
        },
    )

    report = analyze_openapi_collection([tool])

    assert report.summary["operation_count"] == 0
    assert report.summary["unique_operation_count"] == 0


def test_readiness_reports_generic_and_missing_schema_issues() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Risky Body API", "version": "1.0.0"},
        "paths": {
            "/payload": {
                "post": {
                    "operationId": "submitPayload",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/raw": {
                "post": {
                    "operationId": "submitRaw",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {}},
                    },
                    "responses": {"204": {"description": "Accepted"}},
                }
            },
        },
    }

    report = analyze_openapi_collection(spec, detect_dependencies=False)
    issues = {issue.code: issue for issue in report.issues}

    assert report.summary["status"] == "blocked"
    assert issues["generic_request_body"].severity == "blocker"
    assert issues["missing_request_schema"].severity == "blocker"
    assert issues["missing_response_schema"].severity == "warning"


def test_readiness_reports_operation_auth_array_and_envelope_signals() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Collection Signals API", "version": "1.0.0"},
        "components": {
            "securitySchemes": {
                "apiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}
            }
        },
        "security": [{"apiKeyAuth": []}],
        "paths": {
            "/orders": {
                "post": {
                    "summary": "Create orders",
                    "parameters": [{"name": "siteNo", "in": "query", "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["sku"],
                                        "properties": {
                                            "sku": {"type": "string"},
                                            "quantity": {"type": "integer"},
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "code": {"type": "string"},
                                            "message": {"type": "string"},
                                            "data": {
                                                "type": "object",
                                                "properties": {
                                                    "items": {
                                                        "type": "array",
                                                        "items": {
                                                            "type": "object",
                                                            "properties": {
                                                                "orderNo": {"type": "string"}
                                                            },
                                                        },
                                                    }
                                                },
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/lookup-a": {
                "get": {"operationId": "findThing", "responses": {"204": {"description": "OK"}}}
            },
            "/lookup-b": {
                "get": {"operationId": "findThing", "responses": {"204": {"description": "OK"}}}
            },
        },
    }

    tg = ToolGraph()
    tg.ingest_openapi(spec, detect_dependencies=False)
    report = tg.analyze_openapi(context_field_names=["siteNo"])
    codes = {issue.code for issue in report.issues}

    assert "missing_operation_id" in codes
    assert "duplicate_operation_id" in codes
    assert "auth_required" in codes
    assert "array_leaf_alignment_required" in codes
    assert "response_envelope_detected" in codes
    assert report.coverage["auth_field_count"] >= 1
    assert report.coverage["context_field_count"] == 1
    assert report.coverage["response_envelope_tool_count"] == 1
    assert report.coverage["body_view_candidate_count"] >= 1


def test_inspect_openapi_cli_json_and_text(tmp_path: Path) -> None:
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(_ready_crud_spec()), encoding="utf-8")

    json_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "graph_tool_call",
            "inspect-openapi",
            str(spec_path),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(json_result.stdout)
    assert payload["summary"]["tool_count"] == 2
    assert "readiness_score" in payload["summary"]
    assert "coverage" in payload

    text_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "graph_tool_call",
            "inspect-openapi",
            str(spec_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "OpenAPI readiness:" in text_result.stdout
    assert "Recommendations:" in text_result.stdout
