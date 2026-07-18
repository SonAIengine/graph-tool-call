"""HTTP executor: build and send requests from ToolSchema metadata.

Zero external dependencies — uses only ``urllib.request``.

Usage::

    from graph_tool_call.execute.http_executor import HttpExecutor

    executor = HttpExecutor("https://api.github.com", auth_token="ghp_...")
    result = executor.execute(tool, {"owner": "octocat", "repo": "Hello-World"})
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from graph_tool_call.core.tool import ToolSchema

_RESERVED_QUERY_CHARS = ":/?#[]@!$&'()*+,;="


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

        Parameters are classified by OpenAPI metadata when available:
        ``path`` / ``query`` / ``header`` / ``cookie`` / request-body fields.
        Older tool metadata falls back to the previous method-based heuristic.
        """
        metadata = tool.metadata
        if not metadata or metadata.get("source") != "openapi":
            raise ValueError(f"Tool '{tool.name}' is not an OpenAPI tool")

        method = metadata["method"].upper()
        path_template: str = metadata["path"]
        api_metadata = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        location_by_param = _location_by_param(api_metadata)
        parameter_metadata = _parameter_metadata_by_name(api_metadata)
        body_field_paths = _body_field_paths(api_metadata)

        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        header_params: dict[str, Any] = {}
        cookie_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}

        for param_name in _iter_known_argument_names(tool, api_metadata):
            value = arguments.get(param_name)
            if value is None:
                continue
            location = location_by_param.get(param_name)
            if f"{{{param_name}}}" in path_template or location == "path":
                path_params[param_name] = value
            elif location == "query":
                query_params[param_name] = value
            elif location == "header":
                header_params[param_name] = value
            elif location == "cookie":
                cookie_params[param_name] = value
            elif location == "body":
                body_params[param_name] = value
            elif method in ("GET", "DELETE", "HEAD", "OPTIONS"):
                query_params[param_name] = value
            else:
                body_params[param_name] = value

        # Build URL
        path = path_template
        for k, v in path_params.items():
            serialized = _serialize_path_parameter(k, v, parameter_metadata.get(k, {}))
            path = path.replace(f"{{{k}}}", serialized)
        missing_path_params = re.findall(r"{([^}/]+)}", path)
        if missing_path_params:
            missing = ", ".join(sorted(set(missing_path_params)))
            raise ValueError(f"Missing path parameter(s) for tool '{tool.name}': {missing}")

        # tool 자체 base_url(spec.servers 유래)이 있으면 그쪽 우선 — 한 컬렉션에
        # 다른 호스트(common/product/member 등)의 source가 섞여 있을 때 source별
        # 호스트로 라우팅한다. 없으면 executor 기본 base_url 사용.
        tool_base = (metadata.get("base_url") or "").rstrip("/")
        base = tool_base or self._base_url
        url = f"{base}{path}"
        if query_params:
            query_string = _serialize_query_params(query_params, parameter_metadata)
            if query_string:
                url += "?" + query_string

        # Build request
        headers = dict(self._headers)
        for k, v in header_params.items():
            headers[str(k)] = _serialize_header_parameter(k, v, parameter_metadata.get(k, {}))
        if cookie_params:
            cookie_segments: list[str] = []
            for k, v in cookie_params.items():
                cookie_segments.extend(_cookie_segments(k, v, parameter_metadata.get(k, {})))
            cookie = "; ".join(cookie_segments)
            headers["Cookie"] = (
                f"{headers.get('Cookie')}; {cookie}" if headers.get("Cookie") else cookie
            )

        data: bytes | None = None
        if body_params and method in ("POST", "PUT", "PATCH"):
            content_type = _request_content_type(api_metadata, metadata)
            headers["Content-Type"] = content_type
            if _is_form_content_type(content_type):
                data = urllib.parse.urlencode(body_params, doseq=True).encode("utf-8")
            else:
                body = _build_json_body(body_params, body_field_paths)
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")

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
            content_type = req.headers.get("Content-type") or req.headers.get("Content-Type") or ""
            if _is_form_content_type(content_type):
                result["body"] = req.data.decode("utf-8")
            else:
                result["body"] = json.loads(req.data.decode("utf-8"))
        return result


def _iter_known_argument_names(tool: ToolSchema, api_metadata: dict[str, Any]) -> list[str]:
    names: list[str] = []

    def add(name: str) -> None:
        if name and name not in names:
            names.append(name)

    for param in tool.parameters:
        add(param.name)
    for param in api_metadata.get("parameters") or []:
        if isinstance(param, dict):
            add(str(param.get("name") or ""))
    request_body = api_metadata.get("request_body") or {}
    for row in (request_body.get("top_level_fields") or []) + (request_body.get("fields") or []):
        if isinstance(row, dict):
            add(str(row.get("field_name") or ""))
    return names


def _location_by_param(api_metadata: dict[str, Any]) -> dict[str, str]:
    locations: dict[str, str] = {}
    for param in api_metadata.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "")
        loc = str(param.get("in") or "")
        if name and loc:
            locations[name] = loc
    request_body = api_metadata.get("request_body") or {}
    for row in (request_body.get("top_level_fields") or []) + (request_body.get("fields") or []):
        if isinstance(row, dict) and row.get("field_name"):
            locations.setdefault(str(row["field_name"]), "body")
    return locations


def _parameter_metadata_by_name(api_metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for param in api_metadata.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "")
        if name:
            metadata[name] = param
    return metadata


def _body_field_paths(api_metadata: dict[str, Any]) -> dict[str, str]:
    request_body = api_metadata.get("request_body") or {}
    paths: dict[str, str] = {}
    for row in (request_body.get("top_level_fields") or []) + (request_body.get("fields") or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("field_name") or "")
        json_path = str(row.get("json_path") or "")
        if name and json_path and name not in paths:
            paths[name] = json_path
    return paths


def _request_content_type(api_metadata: dict[str, Any], metadata: dict[str, Any]) -> str:
    request_body = api_metadata.get("request_body") or {}
    content_type = (
        request_body.get("content_type")
        or metadata.get("request_content_type")
        or "application/json"
    )
    return "application/json" if content_type == "*/*" else str(content_type)


def _is_form_content_type(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower() == "application/x-www-form-urlencoded"


def _serialize_path_parameter(name: str, value: Any, parameter: dict[str, Any]) -> str:
    style = str(parameter.get("style") or "simple")
    explode = _explode(parameter, style)
    if style == "label":
        return _serialize_label_path_value(value, explode=explode)
    if style == "matrix":
        return _serialize_matrix_path_value(name, value, explode=explode)
    return _serialize_simple_path_value(value, explode=explode)


def _serialize_query_params(
    params: dict[str, Any],
    parameter_metadata: dict[str, dict[str, Any]],
) -> str:
    segments: list[str] = []
    for name, value in params.items():
        segments.extend(_serialize_query_parameter(name, value, parameter_metadata.get(name, {})))
    return "&".join(segments)


def _serialize_query_parameter(
    name: str,
    value: Any,
    parameter: dict[str, Any],
) -> list[str]:
    style = str(parameter.get("style") or "form")
    explode = _explode(parameter, style)
    allow_reserved = bool(parameter.get("allowReserved", False))

    if style == "deepObject" and isinstance(value, dict):
        return [
            _query_pair(
                f"{name}[{key}]",
                item,
                allow_reserved=allow_reserved,
                name_safe_extra="[]",
            )
            for key, item in value.items()
            if item is not None
        ]

    if style == "spaceDelimited" and _is_sequence(value):
        return [
            _query_pair(
                name,
                " ".join(_primitive_text(item) for item in value),
                allow_reserved=allow_reserved,
                plus=False,
            )
        ]

    if style == "pipeDelimited" and _is_sequence(value):
        return [
            _query_pair(
                name,
                "|".join(_primitive_text(item) for item in value),
                allow_reserved=allow_reserved,
                value_safe_extra="|",
            )
        ]

    if isinstance(value, dict):
        if explode:
            return [
                _query_pair(str(key), item, allow_reserved=allow_reserved)
                for key, item in value.items()
                if item is not None
            ]
        return [
            _query_pair(
                name,
                ",".join(_object_items(value)),
                allow_reserved=allow_reserved,
                value_safe_extra=",",
            )
        ]

    if _is_sequence(value):
        if explode:
            return [
                _query_pair(name, item, allow_reserved=allow_reserved)
                for item in value
                if item is not None
            ]
        return [
            _query_pair(
                name,
                ",".join(_primitive_text(item) for item in value),
                allow_reserved=allow_reserved,
                value_safe_extra=",",
            )
        ]

    return [_query_pair(name, value, allow_reserved=allow_reserved)]


def _query_pair(
    name: str,
    value: Any,
    *,
    allow_reserved: bool = False,
    name_safe_extra: str = "",
    value_safe_extra: str = "",
    plus: bool = True,
) -> str:
    safe = (_RESERVED_QUERY_CHARS if allow_reserved else "") + value_safe_extra
    quote = urllib.parse.quote_plus if plus else urllib.parse.quote
    encoded_name = urllib.parse.quote_plus(str(name), safe=name_safe_extra)
    encoded_value = quote(_primitive_text(value), safe=safe)
    return f"{encoded_name}={encoded_value}"


def _serialize_header_parameter(name: str, value: Any, parameter: dict[str, Any]) -> str:
    style = str(parameter.get("style") or "simple")
    explode = _explode(parameter, style)
    return _serialize_simple_text(name, value, explode=explode)


def _cookie_segments(name: str, value: Any, parameter: dict[str, Any]) -> list[str]:
    style = str(parameter.get("style") or "form")
    explode = _explode(parameter, style)
    if isinstance(value, dict):
        if style == "form" and explode:
            return [_cookie_pair(str(key), item) for key, item in value.items() if item is not None]
        return [_cookie_pair(name, ",".join(_object_items(value)))]
    if _is_sequence(value):
        if style == "form" and explode:
            return [_cookie_pair(name, item) for item in value if item is not None]
        return [_cookie_pair(name, ",".join(_primitive_text(item) for item in value))]
    return [_cookie_pair(name, _serialize_simple_text(name, value, explode=explode))]


def _cookie_pair(name: str, value: Any) -> str:
    encoded_name = urllib.parse.quote(str(name))
    encoded_value = urllib.parse.quote(_primitive_text(value))
    return f"{encoded_name}={encoded_value}"


def _serialize_simple_path_value(value: Any, *, explode: bool) -> str:
    if _is_sequence(value):
        return ",".join(_quote_path_value(item) for item in value)
    if isinstance(value, dict):
        if explode:
            return ",".join(
                f"{_quote_path_value(key)}={_quote_path_value(item)}" for key, item in value.items()
            )
        return ",".join(_quote_path_value(item) for item in _object_items(value))
    return _quote_path_value(value)


def _serialize_label_path_value(value: Any, *, explode: bool) -> str:
    if _is_sequence(value):
        separator = "." if explode else ","
        return "." + separator.join(_quote_path_value(item) for item in value)
    if isinstance(value, dict):
        separator = "." if explode else ","
        items = (
            (f"{key}={_primitive_text(item)}" for key, item in value.items())
            if explode
            else _object_items(value)
        )
        return "." + separator.join(_quote_path_value(item) for item in items)
    return "." + _quote_path_value(value)


def _serialize_matrix_path_value(name: str, value: Any, *, explode: bool) -> str:
    encoded_name = _quote_path_value(name)
    if _is_sequence(value):
        if explode:
            return "".join(f";{encoded_name}={_quote_path_value(item)}" for item in value)
        joined = ",".join(_quote_path_value(item) for item in value)
        return f";{encoded_name}={joined}"
    if isinstance(value, dict):
        if explode:
            return "".join(
                f";{_quote_path_value(key)}={_quote_path_value(item)}"
                for key, item in value.items()
            )
        joined = ",".join(_quote_path_value(item) for item in _object_items(value))
        return f";{encoded_name}={joined}"
    return f";{encoded_name}={_quote_path_value(value)}"


def _serialize_simple_text(name: str, value: Any, *, explode: bool) -> str:
    if _is_sequence(value):
        return ",".join(_primitive_text(item) for item in value)
    if isinstance(value, dict):
        if explode:
            return ",".join(f"{key}={_primitive_text(item)}" for key, item in value.items())
        return ",".join(_object_items(value))
    return _primitive_text(value)


def _object_items(value: dict[Any, Any]) -> list[str]:
    parts: list[str] = []
    for key, item in value.items():
        if item is None:
            continue
        parts.extend([_primitive_text(key), _primitive_text(item)])
    return parts


def _is_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes, bytearray))


def _primitive_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _quote_path_value(value: Any) -> str:
    return urllib.parse.quote(_primitive_text(value), safe="")


def _explode(parameter: dict[str, Any], style: str) -> bool:
    if "explode" in parameter:
        return bool(parameter["explode"])
    return style == "form"


def _build_json_body(
    body_params: dict[str, Any],
    body_field_paths: dict[str, str],
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for name, value in body_params.items():
        json_path = body_field_paths.get(name)
        if json_path and _can_assign_json_path(json_path):
            _assign_json_path(body, json_path, value)
        else:
            body[name] = value
    return body


def _can_assign_json_path(json_path: str) -> bool:
    return json_path.startswith("$.") and "[*]" not in json_path


def _assign_json_path(body: dict[str, Any], json_path: str, value: Any) -> None:
    parts = [part for part in json_path.removeprefix("$.").split(".") if part]
    if not parts:
        return
    cursor = body
    for part in parts[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = existing
    cursor[parts[-1]] = value
