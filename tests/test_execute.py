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
        assert result["body"]["path"] == "/users/42"
        assert result["body"]["method"] == "GET"

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
        assert result["body"]["received"] == {"name": "Alice"}

    def test_delete_no_body(self, mock_server):
        tool = _make_tool(name="deleteUser", method="DELETE", path="/users/{userId}")
        executor = HttpExecutor(mock_server)
        result = executor.execute(tool, {"userId": "99"})

        assert result["status"] == 204

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
