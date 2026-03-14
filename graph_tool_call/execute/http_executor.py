"""HTTP executor: build and send requests from ToolSchema metadata.

Zero external dependencies — uses only ``urllib.request``.

Usage::

    from graph_tool_call.execute.http_executor import HttpExecutor

    executor = HttpExecutor("https://api.github.com", auth_token="ghp_...")
    result = executor.execute(tool, {"owner": "octocat", "repo": "Hello-World"})
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from graph_tool_call.core.tool import ToolSchema


class HttpExecutor:
    """Execute OpenAPI-sourced tools via HTTP."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = dict(headers) if headers else {}
        if auth_token:
            self._headers.setdefault("Authorization", f"Bearer {auth_token}")
        self._timeout = timeout

    def build_request(
        self,
        tool: ToolSchema,
        arguments: dict[str, Any],
    ) -> urllib.request.Request:
        """Build a ``urllib.request.Request`` from tool metadata + arguments.

        Parameters are classified by location:
        - Path params: ``{name}`` placeholders in the URL template
        - Query params: GET/DELETE/HEAD method params
        - Body params: POST/PUT/PATCH method params (sent as JSON)
        """
        metadata = tool.metadata
        if not metadata or metadata.get("source") != "openapi":
            raise ValueError(f"Tool '{tool.name}' is not an OpenAPI tool")

        method = metadata["method"].upper()
        path_template: str = metadata["path"]

        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}

        for param in tool.parameters:
            value = arguments.get(param.name)
            if value is None:
                continue
            if f"{{{param.name}}}" in path_template:
                path_params[param.name] = value
            elif method in ("GET", "DELETE", "HEAD", "OPTIONS"):
                query_params[param.name] = value
            else:
                body_params[param.name] = value

        # Build URL
        path = path_template
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", urllib.parse.quote(str(v), safe=""))

        url = f"{self._base_url}{path}"
        if query_params:
            url += "?" + urllib.parse.urlencode(query_params, doseq=True)

        # Build request
        headers = dict(self._headers)
        data: bytes | None = None
        if body_params and method in ("POST", "PUT", "PATCH"):
            headers["Content-Type"] = "application/json"
            data = json.dumps(body_params, ensure_ascii=False).encode("utf-8")

        return urllib.request.Request(url, data=data, headers=headers, method=method)

    def execute(
        self,
        tool: ToolSchema,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool and return the response.

        Returns a dict with ``status``, ``headers``, and ``body`` keys.
        On HTTP errors, returns ``status``, ``error``, and ``body``.
        """
        req = self.build_request(tool, arguments)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    body: Any = json.loads(raw)
                except json.JSONDecodeError:
                    body = raw
                return {
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "body": body,
                }
        except urllib.error.HTTPError as e:
            raw_body = e.read().decode("utf-8", errors="replace")
            try:
                err_body: Any = json.loads(raw_body)
            except json.JSONDecodeError:
                err_body = raw_body
            return {
                "status": e.code,
                "error": e.reason,
                "body": err_body,
            }

    def dry_run(
        self,
        tool: ToolSchema,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Build request without executing — for preview/debugging.

        Returns ``method``, ``url``, ``headers``, and optional ``body``.
        """
        req = self.build_request(tool, arguments)
        result: dict[str, Any] = {
            "method": req.method,
            "url": req.full_url,
            "headers": dict(req.headers),
        }
        if req.data:
            result["body"] = json.loads(req.data.decode("utf-8"))
        return result
