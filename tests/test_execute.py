"""Tests for HTTP executor and ToolGraph.execute() integration."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

import pytest

from graph_tool_call.core.tool import ToolParameter as ToolParam
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.execute.http_executor import HttpExecutor
from graph_tool_call.ingest.openapi import ingest_openapi

# --- Fixtures ---


def _make_tool(
    name: str = "getUser",
    method: str = "GET",
    path: str = "/users/{userId}",
    params: list[dict[str, Any]] | None = None,
) -> ToolSchema:
    """Create a ToolSchema with OpenAPI metadata."""
    if params is None:
        params = [ToolParam(name="userId", type="string", description="User ID", required=True)]
    return ToolSchema(
        name=name,
        description=f"Tool {name}",
        parameters=params,
        metadata={"source": "openapi", "method": method, "path": path},
    )


# --- build_request tests ---


class TestBuildRequest:
    def test_get_with_path_param(self):
        tool = _make_tool()
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"userId": "42"})

        assert req.method == "GET"
        assert req.full_url == "https://api.example.com/users/42"
        assert req.data is None

    def test_get_with_query_params(self):
        tool = _make_tool(
            name="listUsers",
            method="GET",
            path="/users",
            params=[
                ToolParam(name="page", type="integer", description="Page", required=False),
                ToolParam(name="limit", type="integer", description="Limit", required=False),
            ],
        )
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"page": 2, "limit": 10})

        assert req.method == "GET"
        assert "page=2" in req.full_url
        assert "limit=10" in req.full_url
        assert req.data is None

    def test_post_with_body_params(self):
        tool = _make_tool(
            name="createUser",
            method="POST",
            path="/users",
            params=[
                ToolParam(name="name", type="string", description="Name", required=True),
                ToolParam(name="email", type="string", description="Email", required=True),
            ],
        )
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"name": "Alice", "email": "a@b.com"})

        assert req.method == "POST"
        assert req.full_url == "https://api.example.com/users"
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"name": "Alice", "email": "a@b.com"}
        assert req.headers["Content-type"] == "application/json"

    def test_put_with_path_and_body(self):
        tool = _make_tool(
            name="updateUser",
            method="PUT",
            path="/users/{userId}",
            params=[
                ToolParam(name="userId", type="string", description="ID", required=True),
                ToolParam(name="name", type="string", description="Name", required=True),
            ],
        )
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"userId": "42", "name": "Bob"})

        assert req.method == "PUT"
        assert req.full_url == "https://api.example.com/users/42"
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"name": "Bob"}

    def test_openapi_locations_override_method_heuristic(self):
        """POST operations can still have query/header params; metadata wins."""
        tool = _make_tool(
            name="updateOrder",
            method="POST",
            path="/orders/{orderId}",
            params=[
                ToolParam(name="orderId", type="string", required=True),
                ToolParam(name="preview", type="boolean"),
                ToolParam(name="X-Site-No", type="string", required=True),
                ToolParam(name="status", type="string", required=True),
                ToolParam(name="city", type="string"),
            ],
        )
        tool.metadata["request_content_type"] = "application/json"
        tool.metadata["openapi"] = {
            "parameters": [
                {"name": "orderId", "in": "path", "required": True},
                {"name": "preview", "in": "query", "required": False},
                {"name": "X-Site-No", "in": "header", "required": True},
            ],
            "request_body": {
                "content_type": "application/json",
                "top_level_fields": [{"field_name": "status", "json_path": "$.status"}],
                "fields": [
                    {"field_name": "status", "json_path": "$.status"},
                    {"field_name": "city", "json_path": "$.shipping.city"},
                ],
            },
        }
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(
            tool,
            {
                "orderId": "O/1",
                "preview": True,
                "X-Site-No": "10",
                "status": "paid",
                "city": "Seoul",
            },
        )

        assert req.method == "POST"
        assert req.full_url == "https://api.example.com/orders/O%2F1?preview=true"
        assert req.headers["X-site-no"] == "10"
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"status": "paid", "shipping": {"city": "Seoul"}}

    def test_ingested_openapi_contract_drives_request_building(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Runtime API", "version": "1.0.0"},
            "paths": {
                "/orders/{orderId}": {
                    "patch": {
                        "operationId": "patchOrder",
                        "parameters": [
                            {
                                "name": "orderId",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                            {"name": "dryRun", "in": "query", "schema": {"type": "boolean"}},
                            {
                                "name": "X-User-Id",
                                "in": "header",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "memo": {
                                                "type": "object",
                                                "properties": {"text": {"type": "string"}},
                                            },
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(
            tools[0],
            {
                "orderId": "A 1",
                "dryRun": False,
                "X-User-Id": "u-1",
                "status": "ready",
                "text": "ship now",
            },
        )

        assert req.method == "PATCH"
        assert req.full_url == "https://api.example.com/orders/A%201?dryRun=false"
        assert req.headers["X-user-id"] == "u-1"
        assert json.loads(req.data.decode("utf-8")) == {
            "status": "ready",
            "memo": {"text": "ship now"},
        }

    def test_ingested_openapi_parameter_styles_drive_query_serialization(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Search API", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "searchItems",
                        "parameters": [
                            {
                                "name": "ids",
                                "in": "query",
                                "style": "form",
                                "explode": False,
                                "schema": {"type": "array", "items": {"type": "string"}},
                            },
                            {
                                "name": "filter",
                                "in": "query",
                                "style": "deepObject",
                                "explode": True,
                                "schema": {
                                    "type": "object",
                                    "properties": {"status": {"type": "string"}},
                                },
                            },
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(
            tools[0],
            {"ids": ["A", "B"], "filter": {"status": "paid"}},
        )

        assert req.full_url == "https://api.example.com/items?ids=A,B&filter[status]=paid"

    def test_openapi_query_parameter_serialization_styles(self):
        tool = _make_tool(
            name="searchItems",
            method="GET",
            path="/items",
            params=[
                ToolParam(name="ids", type="array"),
                ToolParam(name="tags", type="array"),
                ToolParam(name="created", type="array"),
                ToolParam(name="filter", type="object"),
                ToolParam(name="q", type="string"),
            ],
        )
        tool.metadata["openapi"] = {
            "parameters": [
                {"name": "ids", "in": "query", "style": "form", "explode": False},
                {"name": "tags", "in": "query", "style": "pipeDelimited", "explode": False},
                {"name": "created", "in": "query", "style": "spaceDelimited", "explode": False},
                {"name": "filter", "in": "query", "style": "deepObject", "explode": True},
                {"name": "q", "in": "query", "allowReserved": True},
            ]
        }
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(
            tool,
            {
                "ids": ["A", "B"],
                "tags": ["red", "blue"],
                "created": ["2026-01-01", "2026-01-31"],
                "filter": {"status": "paid", "siteNo": 10},
                "q": "/goods?x=1",
            },
        )

        assert req.full_url == (
            "https://api.example.com/items?"
            "ids=A,B&tags=red|blue&created=2026-01-01%202026-01-31&"
            "filter[status]=paid&filter[siteNo]=10&q=/goods?x=1"
        )

    def test_openapi_path_header_and_cookie_serialization_styles(self):
        tool = _make_tool(
            name="scopedItems",
            method="GET",
            path="/items/{ids}/labels/{labels}/matrix/{scope}",
            params=[
                ToolParam(name="ids", type="array", required=True),
                ToolParam(name="labels", type="array", required=True),
                ToolParam(name="scope", type="object", required=True),
                ToolParam(name="X-Scopes", type="array"),
                ToolParam(name="prefs", type="object"),
            ],
        )
        tool.metadata["openapi"] = {
            "parameters": [
                {"name": "ids", "in": "path", "style": "simple", "explode": False},
                {"name": "labels", "in": "path", "style": "label", "explode": True},
                {"name": "scope", "in": "path", "style": "matrix", "explode": True},
                {"name": "X-Scopes", "in": "header", "style": "simple", "explode": False},
                {"name": "prefs", "in": "cookie", "style": "form", "explode": True},
            ]
        }
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(
            tool,
            {
                "ids": ["A", "B"],
                "labels": ["red", "blue"],
                "scope": {"site": 10, "lang": "ko"},
                "X-Scopes": ["read", "write"],
                "prefs": {"theme": "dark", "compact": True},
            },
        )

        assert req.full_url == (
            "https://api.example.com/items/A,B/labels/.red.blue/matrix/;site=10;lang=ko"
        )
        assert req.headers["X-scopes"] == "read,write"
        assert req.headers["Cookie"] == "theme=dark; compact=true"

    def test_form_request_body_uses_urlencoding(self):
        tool = _make_tool(
            name="submitSearch",
            method="POST",
            path="/search",
            params=[
                ToolParam(name="keyword", type="string", required=True),
                ToolParam(name="page", type="integer"),
            ],
        )
        tool.metadata["openapi"] = {
            "request_body": {
                "content_type": "application/x-www-form-urlencoded",
                "fields": [
                    {"field_name": "keyword", "json_path": "$.keyword"},
                    {"field_name": "page", "json_path": "$.page"},
                ],
            }
        }
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"keyword": "상품 검색", "page": 2})

        assert req.headers["Content-type"] == "application/x-www-form-urlencoded"
        assert req.data.decode("utf-8") == "keyword=%EC%83%81%ED%92%88+%EA%B2%80%EC%83%89&page=2"

    def test_ingested_multipart_request_body_uses_candidate_schema(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Asset API", "version": "1.0.0"},
            "paths": {
                "/assets": {
                    "post": {
                        "operationId": "uploadAsset",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {},
                                "multipart/form-data": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["file"],
                                        "properties": {
                                            "file": {
                                                "type": "string",
                                                "format": "binary",
                                                "description": "Asset file",
                                            },
                                            "title": {"type": "string"},
                                        },
                                    }
                                },
                            },
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        tool = tools[0]
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(
            tool,
            {"file": ("asset.png", b"PNGDATA", "image/png"), "title": "대표 이미지"},
        )
        body = req.data.decode("utf-8", errors="replace")

        assert {param.name for param in tool.parameters} >= {"file", "title"}
        assert tool.metadata["request_content_type"] == "multipart/form-data"
        assert req.headers["Content-type"].startswith("multipart/form-data; boundary=")
        assert 'name="file"; filename="asset.png"' in body
        assert "Content-Type: image/png" in body
        assert "PNGDATA" in body
        assert 'name="title"' in body
        assert "대표 이미지" in body

    def test_multipart_candidate_is_selected_for_binary_argument(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Asset API", "version": "1.0.0"},
            "paths": {
                "/assets": {
                    "post": {
                        "operationId": "createAsset",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"title": {"type": "string"}},
                                    }
                                },
                                "multipart/form-data": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "title": {"type": "string"},
                                            "file": {"type": "string", "format": "binary"},
                                        },
                                    }
                                },
                            },
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(tools[0], {"title": "banner", "file": b"abc"})
        body = req.data.decode("utf-8", errors="replace")

        assert tools[0].metadata["request_content_type"] == "application/json"
        assert req.headers["Content-type"].startswith("multipart/form-data; boundary=")
        assert 'name="file"; filename="file"' in body
        assert "abc" in body

    def test_form_candidate_is_selected_when_arguments_match_that_schema(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Search API", "version": "1.0.0"},
            "paths": {
                "/search": {
                    "post": {
                        "operationId": "submitSearch",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"payload": {"type": "object"}},
                                    }
                                },
                                "application/x-www-form-urlencoded": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "keyword": {"type": "string"},
                                            "page": {"type": "integer"},
                                        },
                                    }
                                },
                            },
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        tools, _ = ingest_openapi(spec)
        executor = HttpExecutor("https://api.example.com")

        req = executor.build_request(tools[0], {"keyword": "상품", "page": 1})

        assert tools[0].metadata["request_content_type"] == "application/json"
        assert req.headers["Content-type"] == "application/x-www-form-urlencoded"
        assert req.data.decode("utf-8") == "keyword=%EC%83%81%ED%92%88&page=1"

    def test_missing_path_parameter_raises(self):
        tool = _make_tool(path="/users/{userId}/orders/{orderId}")
        executor = HttpExecutor("https://api.example.com")

        with pytest.raises(ValueError, match="orderId"):
            executor.build_request(tool, {"userId": "u1"})

    def test_delete_with_path_param(self):
        tool = _make_tool(name="deleteUser", method="DELETE", path="/users/{userId}")
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"userId": "99"})

        assert req.method == "DELETE"
        assert req.full_url == "https://api.example.com/users/99"
        assert req.data is None

    def test_patch_with_body(self):
        tool = _make_tool(
            name="patchUser",
            method="PATCH",
            path="/users/{userId}",
            params=[
                ToolParam(name="userId", type="string", description="ID", required=True),
                ToolParam(name="email", type="string", description="Email", required=False),
            ],
        )
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"userId": "1", "email": "new@x.com"})

        assert req.method == "PATCH"
        body = json.loads(req.data.decode("utf-8"))
        assert body == {"email": "new@x.com"}

    def test_path_param_url_encoding(self):
        """Path params with special chars should be URL-encoded."""
        tool = _make_tool(path="/users/{userId}")
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"userId": "user/name with spaces"})

        assert "user%2Fname%20with%20spaces" in req.full_url

    def test_skip_none_params(self):
        tool = _make_tool(
            name="listUsers",
            method="GET",
            path="/users",
            params=[
                ToolParam(name="page", type="integer", description="Page", required=False),
                ToolParam(name="limit", type="integer", description="Limit", required=False),
            ],
        )
        executor = HttpExecutor("https://api.example.com")
        req = executor.build_request(tool, {"page": 1, "limit": None})

        assert "page=1" in req.full_url
        assert "limit" not in req.full_url

    def test_non_openapi_tool_raises(self):
        tool = ToolSchema(name="mcp_tool", description="MCP tool")
        executor = HttpExecutor("https://api.example.com")
        with pytest.raises(ValueError, match="not an OpenAPI tool"):
            executor.build_request(tool, {})

    def test_base_url_trailing_slash_stripped(self):
        tool = _make_tool(path="/users/{userId}")
        executor = HttpExecutor("https://api.example.com/")
        req = executor.build_request(tool, {"userId": "1"})

        assert req.full_url == "https://api.example.com/users/1"


# --- Auth tests ---


class TestAuth:
    def test_bearer_token(self):
        executor = HttpExecutor("https://api.example.com", auth_token="tok_123")
        tool = _make_tool()
        req = executor.build_request(tool, {"userId": "1"})

        assert req.headers["Authorization"] == "Bearer tok_123"

    def test_custom_headers(self):
        executor = HttpExecutor(
            "https://api.example.com",
            headers={"X-Custom": "value", "Authorization": "Basic abc"},
        )
        tool = _make_tool()
        req = executor.build_request(tool, {"userId": "1"})

        assert req.headers["X-custom"] == "value"
        assert req.headers["Authorization"] == "Basic abc"

    def test_auth_token_does_not_override_custom_auth(self):
        """If Authorization is in headers, auth_token should not override it."""
        executor = HttpExecutor(
            "https://api.example.com",
            headers={"Authorization": "Basic xyz"},
            auth_token="tok_ignored",
        )
        tool = _make_tool()
        req = executor.build_request(tool, {"userId": "1"})

        # setdefault should keep existing Authorization
        assert req.headers["Authorization"] == "Basic xyz"


# --- dry_run tests ---


class TestDryRun:
    def test_dry_run_get(self):
        tool = _make_tool()
        executor = HttpExecutor("https://api.example.com")
        result = executor.dry_run(tool, {"userId": "42"})

        assert result["method"] == "GET"
        assert result["url"] == "https://api.example.com/users/42"
        assert "body" not in result

    def test_dry_run_post_includes_body(self):
        tool = _make_tool(
            name="createUser",
            method="POST",
            path="/users",
            params=[ToolParam(name="name", type="string", description="N", required=True)],
        )
        executor = HttpExecutor("https://api.example.com")
        result = executor.dry_run(tool, {"name": "Alice"})

        assert result["method"] == "POST"
        assert result["body"] == {"name": "Alice"}


# --- execute with mock HTTP server ---


class _MockHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for testing."""

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"code": "NOT_FOUND", "message": "Missing"}).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"path": self.path, "method": "GET"}).encode())

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else ""
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"received": json.loads(body) if body else {}}).encode())

    def do_DELETE(self):  # noqa: N802
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass  # suppress logging


@pytest.fixture()
def mock_server():
    """Start a local HTTP server for testing."""
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestExecuteReal:
    def test_get_success(self, mock_server):
        tool = _make_tool(path="/users/{userId}")
        executor = HttpExecutor(mock_server)
        result = executor.execute(tool, {"userId": "42"})

        assert result["status"] == 200
        assert result["ok"] is True
        assert result["content_type"] == "application/json"
        assert result["body"]["path"] == "/users/42"
        assert result["body"]["method"] == "GET"

    def test_success_response_metadata_matches_openapi_catalog(self, mock_server):
        tool = _make_tool(path="/users/{userId}")
        tool.metadata["openapi"] = {
            "responses": [
                {
                    "status": "200",
                    "success": True,
                    "description": "User details",
                    "content_type": "application/json",
                    "content_types": [
                        {
                            "content_type": "application/json",
                            "is_json": True,
                            "has_schema": True,
                        }
                    ],
                }
            ]
        }
        executor = HttpExecutor(mock_server)

        result = executor.execute(tool, {"userId": "42"})

        assert result["ok"] is True
        assert result["response_metadata"]["status"] == "200"
        assert result["response_metadata"]["description"] == "User details"
        assert result["response_metadata"]["matched_content_type"] == "application/json"
        assert result["response_metadata"]["content_metadata"]["is_json"] is True

    def test_post_success(self, mock_server):
        tool = _make_tool(
            name="createUser",
            method="POST",
            path="/users",
            params=[ToolParam(name="name", type="string", description="N", required=True)],
        )
        executor = HttpExecutor(mock_server)
        result = executor.execute(tool, {"name": "Alice"})

        assert result["status"] == 201
        assert result["ok"] is True
        assert result["body"]["received"] == {"name": "Alice"}

    def test_success_response_metadata_matches_range_status(self, mock_server):
        tool = _make_tool(
            name="createUser",
            method="POST",
            path="/users",
            params=[ToolParam(name="name", type="string", description="N", required=True)],
        )
        tool.metadata["openapi"] = {
            "responses": [{"status": "2XX", "success": True, "description": "Any success"}]
        }
        executor = HttpExecutor(mock_server)

        result = executor.execute(tool, {"name": "Alice"})

        assert result["status"] == 201
        assert result["response_metadata"]["status"] == "2XX"
        assert result["response_metadata"]["description"] == "Any success"

    def test_delete_no_body(self, mock_server):
        tool = _make_tool(name="deleteUser", method="DELETE", path="/users/{userId}")
        executor = HttpExecutor(mock_server)
        result = executor.execute(tool, {"userId": "99"})

        assert result["status"] == 204
        assert result["ok"] is True

    def test_http_error_response_metadata_matches_error_catalog(self, mock_server):
        tool = _make_tool(name="getMissing", path="/missing/{userId}")
        tool.metadata["openapi"] = {
            "responses": [
                {"status": "200", "success": True, "description": "OK"},
                {
                    "status": "404",
                    "success": False,
                    "description": "User was not found",
                    "content_type": "application/json",
                    "content_types": [
                        {
                            "content_type": "application/json",
                            "is_json": True,
                            "has_schema": True,
                        }
                    ],
                },
                {"status": "default", "success": False, "description": "Unexpected error"},
            ]
        }
        executor = HttpExecutor(mock_server)

        result = executor.execute(tool, {"userId": "404"})

        assert result["status"] == 404
        assert result["ok"] is False
        assert result["content_type"] == "application/json"
        assert result["body"]["code"] == "NOT_FOUND"
        assert result["response_metadata"]["status"] == "404"
        assert result["error_response"]["description"] == "User was not found"

    def test_http_error_returns_error_dict(self):
        """HTTP errors should return status + error, not raise."""
        tool = _make_tool(path="/users/{userId}")
        executor = HttpExecutor("http://127.0.0.1:1")  # connection refused
        # urllib will raise URLError, not HTTPError
        with pytest.raises(Exception):
            executor.execute(tool, {"userId": "1"})


# --- ToolGraph.execute integration ---


class TestToolGraphExecute:
    def test_execute_tool_not_found(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        with pytest.raises(ValueError, match="not found"):
            tg.execute("nonexistent", {})

    def test_execute_missing_base_url(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tool = _make_tool()
        tg.add_tool(tool)
        with pytest.raises(ValueError, match="base_url required"):
            tg.execute("getUser", {"userId": "1"})

    def test_execute_with_explicit_base_url(self, mock_server):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tool = _make_tool(path="/users/{userId}")
        tg.add_tool(tool)
        result = tg.execute("getUser", {"userId": "42"}, base_url=mock_server)

        assert result["status"] == 200
        assert result["body"]["path"] == "/users/42"
