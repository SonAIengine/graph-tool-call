"""HTTP executor: build and send requests from ToolSchema metadata.

Zero external dependencies — uses only ``urllib.request``.

Usage::

    from graph_tool_call.execute.http_executor import HttpExecutor

    executor = HttpExecutor("https://api.github.com", auth_token="ghp_...")
    result = executor.execute(tool, {"owner": "octocat", "repo": "Hello-World"})
"""

from __future__ import annotations

import copy
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from graph_tool_call.core.tool import ToolSchema

_RESERVED_QUERY_CHARS = ":/?#[]@!$&'()*+,;="
_HTTP_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_NO_DEFAULT = object()
_SENSITIVE_DEFAULT_PARAMETER_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "bearer",
    "bearer_token",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "id_token",
    "jwt",
    "jwt_token",
    "password",
    "passwd",
    "proxy_authorization",
    "refresh_token",
    "secret",
    "session",
    "session_id",
    "session_key",
    "sessionid",
    "set_cookie",
    "sid",
    "token",
    "x_api_key",
    "xapikey",
}
_SENSITIVE_DEFAULT_PARAMETER_SUFFIXES = (
    "_api_key",
    "_apikey",
    "_credential",
    "_credentials",
    "_password",
    "_secret",
    "_token",
)


class OpenAPIRequestValidationError(ValueError):
    """Raised when OpenAPI request preflight fails before network I/O."""

    def __init__(self, tool_name: str, diagnostics: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.diagnostics = diagnostics
        missing_inputs = ", ".join(
            f"{item.get('location', 'input')}:{item.get('name', '')}"
            for item in diagnostics.get("missing_required") or []
        )
        missing_security = ", ".join(
            str(scheme.get("name") or "")
            for requirement in diagnostics.get("missing_security") or []
            for scheme in requirement.get("schemes") or []
            if isinstance(scheme, dict) and scheme.get("name")
        )
        invalid_arguments = ", ".join(
            f"{item.get('location', 'input')}:{item.get('name', '')}"
            f"({item.get('reason', 'invalid')})"
            for item in diagnostics.get("invalid_arguments") or []
        )
        details = []
        if missing_inputs:
            details.append(f"missing inputs: {missing_inputs}")
        if missing_security:
            details.append(f"missing security: {missing_security}")
        if invalid_arguments:
            details.append(f"invalid arguments: {invalid_arguments}")
        message = f"Invalid OpenAPI request for tool '{tool_name}'"
        if details:
            message = f"{message}: {'; '.join(details)}"
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Return structured diagnostics for UI/log forwarding."""
        return dict(self.diagnostics)


class HttpExecutor:
    """Execute OpenAPI-sourced tools via HTTP."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: int = 30,
        validate_required: bool = True,
        validate_values: bool = True,
        apply_defaults: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = dict(headers) if headers else {}
        if auth_token:
            self._headers.setdefault("Authorization", f"Bearer {auth_token}")
        self._timeout = timeout
        self._validate_required = validate_required
        self._validate_values = validate_values
        self._apply_defaults = apply_defaults

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
        original_arguments = arguments
        effective_arguments, _applied_defaults = _arguments_with_openapi_defaults(
            tool,
            arguments,
            api_metadata,
            metadata,
            method=method,
            path_template=path_template,
            enabled=self._apply_defaults,
        )

        if self._validate_required:
            diagnostics = self.validate_request(tool, original_arguments)
            if _preflight_blocks_request(
                diagnostics,
                validate_values=self._validate_values,
            ):
                raise OpenAPIRequestValidationError(tool.name, diagnostics)
        arguments = effective_arguments

        location_by_param = _location_by_param(api_metadata)
        parameter_metadata = _parameter_metadata_by_name(api_metadata)

        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        header_params: dict[str, Any] = {}
        cookie_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}

        for param_name in _iter_known_argument_names(
            tool, api_metadata, path_template=path_template
        ):
            has_argument = param_name in arguments
            value = arguments.get(param_name)
            if value is None:
                if not has_argument:
                    continue
                if location_by_param.get(param_name) == "body":
                    body_params[param_name] = value
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
            content_type = _request_content_type(api_metadata, metadata, body_params)
            body_rows = _body_rows(
                api_metadata,
                content_type=content_type,
                include_content_type_rows=False,
            )
            body_field_paths = _body_field_paths_from_rows(body_rows)
            if _is_form_content_type(content_type):
                body_field_metadata = _body_field_metadata_from_rows(body_rows)
                headers["Content-Type"] = content_type
                data = _encode_urlencoded_body(body_params, body_field_metadata)
            elif _is_multipart_content_type(content_type):
                multipart_params, multipart_metadata = _prepare_multipart_body_parts(
                    body_params,
                    body_rows,
                )
                content_type, data = _encode_multipart_body(
                    content_type,
                    multipart_params,
                    multipart_metadata,
                )
                headers["Content-Type"] = content_type
            else:
                headers["Content-Type"] = content_type
                request_body = (
                    api_metadata.get("request_body")
                    if isinstance(api_metadata.get("request_body"), dict)
                    else {}
                )
                if _is_json_content_type(content_type):
                    body = _build_json_body(
                        body_params,
                        body_field_paths,
                        request_body=request_body,
                    )
                    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                else:
                    data = _encode_raw_body(
                        body_params,
                        body_field_paths,
                        request_body=request_body,
                    )

        return urllib.request.Request(url, data=data, headers=headers, method=method)

    def validate_request(
        self,
        tool: ToolSchema,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Return request preflight diagnostics without building or sending HTTP."""
        metadata = tool.metadata
        if not metadata or metadata.get("source") != "openapi":
            raise ValueError(f"Tool '{tool.name}' is not an OpenAPI tool")

        method = str(metadata["method"]).upper()
        path_template = str(metadata["path"])
        api_metadata = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
        arguments, applied_defaults = _arguments_with_openapi_defaults(
            tool,
            arguments,
            api_metadata,
            metadata,
            method=method,
            path_template=path_template,
            enabled=self._apply_defaults,
        )
        location_by_param = _location_by_param(api_metadata)
        known_names = _iter_known_argument_names(tool, api_metadata, path_template=path_template)
        known_name_set = set(known_names)
        used_by_location = _used_arguments_by_location(
            tool,
            arguments,
            api_metadata,
            method=method,
            path_template=path_template,
        )
        body_params = {name: arguments[name] for name in used_by_location["body"]}
        selected_content_type = (
            _request_content_type(api_metadata, metadata, body_params)
            if method in ("POST", "PUT", "PATCH")
            else ""
        )
        missing_required = _missing_required_inputs(
            tool,
            arguments,
            api_metadata,
            method=method,
            path_template=path_template,
            location_by_param=location_by_param,
            headers=self._headers,
            selected_content_type=selected_content_type,
        )
        missing_security = _missing_security_requirements(
            api_metadata,
            arguments,
            headers=self._headers,
        )
        invalid_arguments = _invalid_argument_values(
            tool,
            arguments,
            api_metadata,
            method=method,
            path_template=path_template,
            location_by_param=location_by_param,
            headers=self._headers,
            selected_content_type=selected_content_type,
        )
        unused_arguments = [
            str(name)
            for name, value in arguments.items()
            if value is not None and str(name) not in known_name_set
        ]
        return {
            "valid": not missing_required and not missing_security and not invalid_arguments,
            "missing_required": missing_required,
            "missing_security": missing_security,
            "invalid_arguments": invalid_arguments,
            "unused_arguments": unused_arguments,
            "used_arguments": used_by_location,
            "selected_content_type": selected_content_type,
            "applied_defaults": applied_defaults,
        }

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
        api_metadata = (
            tool.metadata.get("openapi") if isinstance(tool.metadata.get("openapi"), dict) else {}
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                content_type = _response_content_type(dict(resp.headers))
                try:
                    body: Any = json.loads(raw)
                except json.JSONDecodeError:
                    body = raw
                response_metadata = _match_response_metadata(
                    api_metadata,
                    status=resp.status,
                    content_type=content_type,
                )
                return {
                    "status": resp.status,
                    "ok": 200 <= resp.status < 300,
                    "headers": dict(resp.headers),
                    "content_type": content_type,
                    "body": body,
                    "response_metadata": response_metadata,
                }
        except urllib.error.HTTPError as e:
            raw_body = e.read().decode("utf-8", errors="replace")
            headers = dict(e.headers or {})
            content_type = _response_content_type(headers)
            try:
                err_body: Any = json.loads(raw_body)
            except json.JSONDecodeError:
                err_body = raw_body
            response_metadata = _match_response_metadata(
                api_metadata,
                status=e.code,
                content_type=content_type,
            )
            return {
                "status": e.code,
                "ok": False,
                "headers": headers,
                "content_type": content_type,
                "error": e.reason,
                "body": err_body,
                "response_metadata": response_metadata,
                "error_response": response_metadata if not response_metadata.get("success") else {},
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
            "preflight": self.validate_request(tool, arguments),
        }
        if req.data:
            content_type = req.headers.get("Content-type") or req.headers.get("Content-Type") or ""
            if _is_form_content_type(content_type):
                result["body"] = req.data.decode("utf-8")
            elif _is_multipart_content_type(content_type):
                result["body"] = req.data.decode("utf-8", errors="replace")
            else:
                try:
                    result["body"] = json.loads(req.data.decode("utf-8"))
                except json.JSONDecodeError:
                    result["body"] = req.data.decode("utf-8", errors="replace")
        return result


def _arguments_with_openapi_defaults(
    tool: ToolSchema,
    arguments: dict[str, Any],
    api_metadata: dict[str, Any],
    metadata: dict[str, Any],
    *,
    method: str,
    path_template: str,
    enabled: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not enabled:
        return arguments, []

    effective = dict(arguments)
    applied: list[dict[str, Any]] = []
    security_api_key_locations = _security_api_key_locations(api_metadata)

    def apply_default(
        name: str,
        location: str,
        row: dict[str, Any],
        *,
        source: str,
        content_type: str = "",
    ) -> None:
        if not name or location == "path" or name in effective:
            return
        if security_api_key_locations.get(name) == location:
            return
        if _is_sensitive_default_parameter(name):
            return
        value_source, value = _openapi_static_default(row)
        if value is _NO_DEFAULT:
            return
        effective[name] = copy.deepcopy(value)
        item: dict[str, Any] = {
            "name": name,
            "location": location,
            "source": source,
            "value_source": value_source,
            "value": copy.deepcopy(value),
        }
        if content_type:
            item["content_type"] = content_type
        _copy_validation_hint(row, item)
        applied.append(item)

    for row in api_metadata.get("parameters") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        location = str(row.get("in") or "")
        if location in {"query", "header", "cookie"}:
            apply_default(name, location, row, source="openapi_parameter")

    location_by_param = _location_by_param(api_metadata)
    body_params = {
        name: effective[name]
        for name in _iter_known_argument_names(tool, api_metadata, path_template=path_template)
        if name in effective and location_by_param.get(name) == "body"
    }
    selected_content_type = (
        _request_content_type(api_metadata, metadata, body_params)
        if method in ("POST", "PUT", "PATCH")
        else ""
    )
    for row in _body_rows(
        api_metadata,
        content_type=selected_content_type,
        include_content_type_rows=False,
    ):
        if not isinstance(row, dict):
            continue
        name = str(row.get("field_name") or "")
        apply_default(
            name,
            "body",
            row,
            source="request_body",
            content_type=selected_content_type,
        )

    return effective, applied


def _openapi_static_default(row: dict[str, Any]) -> tuple[str, Any]:
    if "const" in row and row.get("const") is not None:
        return "const", row["const"]
    if "default" in row and row.get("default") is not None:
        return "default", row["default"]
    return "", _NO_DEFAULT


def _is_sensitive_default_parameter(name: str) -> bool:
    snake_name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name).strip())
    normalized = re.sub(r"[^a-z0-9]+", "_", snake_name.lower()).strip("_")
    compact = normalized.replace("_", "")
    return (
        normalized in _SENSITIVE_DEFAULT_PARAMETER_NAMES
        or compact in _SENSITIVE_DEFAULT_PARAMETER_NAMES
        or normalized.endswith(_SENSITIVE_DEFAULT_PARAMETER_SUFFIXES)
    )


def _iter_known_argument_names(
    tool: ToolSchema,
    api_metadata: dict[str, Any],
    *,
    path_template: str = "",
) -> list[str]:
    names: list[str] = []

    def add(name: str) -> None:
        if name and name not in names:
            names.append(name)

    for name in re.findall(r"{([^}/]+)}", path_template):
        add(name)
    for param in tool.parameters:
        add(param.name)
    for param in api_metadata.get("parameters") or []:
        if isinstance(param, dict):
            add(str(param.get("name") or ""))
    for row in _body_rows(api_metadata):
        if isinstance(row, dict):
            add(str(row.get("field_name") or ""))
    for name in _security_api_key_locations(api_metadata):
        add(name)
    return names


def _preflight_blocks_request(
    diagnostics: dict[str, Any],
    *,
    validate_values: bool,
) -> bool:
    if diagnostics.get("missing_required") or diagnostics.get("missing_security"):
        return True
    return validate_values and bool(diagnostics.get("invalid_arguments"))


def _used_arguments_by_location(
    tool: ToolSchema,
    arguments: dict[str, Any],
    api_metadata: dict[str, Any],
    *,
    method: str,
    path_template: str,
) -> dict[str, list[str]]:
    location_by_param = _location_by_param(api_metadata)
    used: dict[str, list[str]] = {
        "path": [],
        "query": [],
        "header": [],
        "cookie": [],
        "body": [],
    }

    def add(location: str, name: str) -> None:
        if location in used and name not in used[location]:
            used[location].append(name)

    for name in _iter_known_argument_names(tool, api_metadata, path_template=path_template):
        has_argument = name in arguments
        value = arguments.get(name)
        if value is None:
            if has_argument and location_by_param.get(name) == "body":
                add("body", name)
            continue
        location = location_by_param.get(name)
        if f"{{{name}}}" in path_template or location == "path":
            add("path", name)
        elif location in used:
            add(location, name)
        elif method in ("GET", "DELETE", "HEAD", "OPTIONS"):
            add("query", name)
        else:
            add("body", name)
    return used


def _missing_required_inputs(
    tool: ToolSchema,
    arguments: dict[str, Any],
    api_metadata: dict[str, Any],
    *,
    method: str,
    path_template: str,
    location_by_param: dict[str, str],
    headers: dict[str, str],
    selected_content_type: str,
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, Any]) -> None:
        name = str(row.get("name") or "")
        location = str(row.get("location") or "")
        if not name or not location:
            return
        key = (location, name)
        if key in seen:
            return
        if _required_argument_present(name, location, arguments, headers):
            return
        seen.add(key)
        missing.append(row)

    for name in re.findall(r"{([^}/]+)}", path_template):
        add({"name": name, "location": "path", "source": "path_template"})

    for row in api_metadata.get("parameters") or []:
        if not isinstance(row, dict) or not row.get("required"):
            continue
        name = str(row.get("name") or "")
        location = str(row.get("in") or "")
        if not name or not location:
            continue
        item: dict[str, Any] = {
            "name": name,
            "location": location,
            "source": "openapi_parameter",
        }
        _copy_validation_hint(row, item)
        add(item)

    body_rows = _body_rows(
        api_metadata,
        content_type=selected_content_type,
        include_content_type_rows=False,
    )
    satisfied_body_containers = _body_container_fields_satisfied_by_leaf_args(
        body_rows,
        arguments,
    )
    satisfied_body_container_names = {name for name, _path in satisfied_body_containers}
    has_body_argument = bool(
        _used_arguments_by_location(
            tool,
            arguments,
            api_metadata,
            method=method,
            path_template=path_template,
        )["body"]
    )
    has_raw_body_argument = _raw_body_argument_present(body_rows, arguments)
    for row in body_rows:
        if not isinstance(row, dict) or not row.get("required"):
            continue
        name = str(row.get("field_name") or "")
        if not name:
            continue
        if (name, str(row.get("json_path") or "")) in satisfied_body_containers:
            continue
        if _is_request_body_root_row(row):
            if has_body_argument:
                continue
        elif has_raw_body_argument:
            continue
        item = {
            "name": name,
            "location": "body",
            "source": "request_body",
        }
        if selected_content_type:
            item["content_type"] = selected_content_type
        _copy_validation_hint(row, item)
        add(item)

    for item in _missing_branch_required_inputs(
        body_rows,
        arguments,
        selected_content_type=selected_content_type,
    ):
        add(item)

    request_body = api_metadata.get("request_body") or {}
    if (
        method in ("POST", "PUT", "PATCH")
        and isinstance(request_body, dict)
        and request_body.get("required")
        and not has_body_argument
        and (not body_rows or not any(bool(row.get("required")) for row in body_rows))
    ):
        add(
            {
                "name": "body",
                "location": "body",
                "source": "request_body",
                **({"content_type": selected_content_type} if selected_content_type else {}),
            }
        )

    parameter_required = {
        (str(row.get("in") or ""), str(row.get("name") or ""))
        for row in api_metadata.get("parameters") or []
        if isinstance(row, dict)
    }
    for param in tool.parameters:
        if not param.required:
            continue
        location = location_by_param.get(param.name)
        if not location:
            location = "path" if f"{{{param.name}}}" in path_template else ""
        if not location:
            location = "query" if method in ("GET", "DELETE", "HEAD", "OPTIONS") else "body"
        if location == "body" and param.name in satisfied_body_container_names:
            continue
        if (
            location == "body"
            and has_body_argument
            and any(
                _is_request_body_root_row(row) and str(row.get("field_name") or "") == param.name
                for row in body_rows
                if isinstance(row, dict)
            )
        ):
            continue
        if (location, param.name) in parameter_required:
            continue
        item = {
            "name": param.name,
            "location": location,
            "source": "tool_parameter",
            "field_type": param.type,
        }
        if param.enum:
            item["enum"] = list(param.enum)
        add(item)
    return missing


def _invalid_argument_values(
    tool: ToolSchema,
    arguments: dict[str, Any],
    api_metadata: dict[str, Any],
    *,
    method: str,
    path_template: str,
    location_by_param: dict[str, str],
    headers: dict[str, str],
    selected_content_type: str,
) -> list[dict[str, Any]]:
    invalid: list[dict[str, Any]] = []
    seen_contracts: set[tuple[str, str]] = set()

    def add_contract(row: dict[str, Any]) -> None:
        name = str(row.get("name") or row.get("field_name") or "")
        location = str(row.get("location") or row.get("in") or "")
        if not name or not location:
            return
        key = (location, name)
        if key in seen_contracts:
            return
        seen_contracts.add(key)

        present, value = _contract_value_for_validation(name, location, arguments, headers)
        if not present:
            return

        contract: dict[str, Any] = {
            "name": name,
            "location": location,
            "source": str(row.get("source") or "openapi_schema"),
        }
        if row.get("json_path"):
            contract["json_path"] = row["json_path"]
        if location == "body" and selected_content_type:
            contract["content_type"] = selected_content_type
        _copy_validation_hint(row, contract)
        invalid.extend(_validation_issues(value, contract))

    for row in api_metadata.get("parameters") or []:
        if isinstance(row, dict):
            add_contract({**row, "location": row.get("in"), "source": "openapi_parameter"})

    for row in _body_rows(
        api_metadata,
        content_type=selected_content_type,
        include_content_type_rows=False,
    ):
        if isinstance(row, dict):
            add_contract({**row, "location": "body", "source": "request_body"})

    for param in tool.parameters:
        location = location_by_param.get(param.name)
        if not location:
            location = "path" if f"{{{param.name}}}" in path_template else ""
        if not location:
            location = "query" if method in ("GET", "DELETE", "HEAD", "OPTIONS") else "body"
        add_contract(
            {
                "name": param.name,
                "location": location,
                "source": "tool_parameter",
                "field_type": param.type,
                **({"enum": list(param.enum)} if param.enum else {}),
            }
        )

    return invalid


def _validation_issues(value: Any, contract: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if value is None:
        if contract.get("nullable"):
            return issues
        if str(contract.get("location") or "") == "body":
            issues.append(_invalid_argument_row(contract, "null"))
        return issues

    const_failed = "const" in contract and not _const_matches(value, contract.get("const"))
    if const_failed:
        issues.append(_invalid_argument_row(contract, "const"))

    enum = contract.get("enum")
    if not const_failed and isinstance(enum, list) and enum and not _enum_matches(value, enum):
        issues.append(_invalid_argument_row(contract, "enum"))

    expected_type = str(contract.get("field_type") or "")
    if not _field_type_matches(
        value,
        expected_type,
        location=str(contract.get("location") or ""),
        schema_format=str(contract.get("format") or ""),
    ):
        issues.append(_invalid_argument_row(contract, "type", expected_type=expected_type))
        return issues

    issues.extend(_numeric_constraint_issues(value, contract))
    issues.extend(_length_constraint_issues(value, contract))
    issues.extend(_array_constraint_issues(value, contract))
    issues.extend(_object_constraint_issues(value, contract))
    return issues


def _invalid_argument_row(
    contract: dict[str, Any],
    reason: str,
    *,
    expected_type: str = "",
) -> dict[str, Any]:
    row = {
        "name": contract["name"],
        "location": contract["location"],
        "source": contract.get("source") or "openapi_schema",
        "reason": reason,
    }
    if expected_type:
        row["expected_type"] = expected_type
    _copy_validation_hint(contract, row)
    return row


def _enum_matches(value: Any, enum: list[Any]) -> bool:
    if value in enum:
        return True
    if _is_sequence(value):
        return any(list(value) == option for option in enum)
    if isinstance(value, dict):
        return False
    value_text = str(value)
    return any(value_text == str(option) for option in enum)


def _const_matches(value: Any, expected: Any) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict | list) or isinstance(expected, dict | list):
        return False
    return str(value) == str(expected)


def _field_type_matches(
    value: Any,
    field_type: str,
    *,
    location: str,
    schema_format: str = "",
) -> bool:
    if not field_type or value is None:
        return True
    if field_type == "string":
        if schema_format.lower() == "binary" and _is_file_part_value(value):
            return True
        if isinstance(value, str):
            return True
        return location != "body" and _is_primitive(value)
    if field_type == "integer":
        return _integer_value(value) is not None
    if field_type == "number":
        return _numeric_value(value) is not None
    if field_type == "boolean":
        return isinstance(value, bool) or (
            isinstance(value, str) and value.strip().lower() in {"true", "false"}
        )
    if field_type == "array":
        return _is_sequence(value)
    if field_type == "object":
        return isinstance(value, dict)
    return True


def _numeric_constraint_issues(value: Any, contract: dict[str, Any]) -> list[dict[str, Any]]:
    number = _numeric_value(value)
    if number is None:
        return []
    issues: list[dict[str, Any]] = []
    minimum = _numeric_value(contract.get("minimum"))
    maximum = _numeric_value(contract.get("maximum"))
    exclusive_minimum = contract.get("exclusive_minimum")
    exclusive_maximum = contract.get("exclusive_maximum")

    if isinstance(exclusive_minimum, bool) and exclusive_minimum and minimum is not None:
        if number <= minimum:
            issues.append(_invalid_argument_row(contract, "exclusive_minimum"))
    elif (exclusive_minimum_value := _numeric_value(exclusive_minimum)) is not None:
        if number <= exclusive_minimum_value:
            issues.append(_invalid_argument_row(contract, "exclusive_minimum"))
    elif minimum is not None and number < minimum:
        issues.append(_invalid_argument_row(contract, "minimum"))

    if isinstance(exclusive_maximum, bool) and exclusive_maximum and maximum is not None:
        if number >= maximum:
            issues.append(_invalid_argument_row(contract, "exclusive_maximum"))
    elif (exclusive_maximum_value := _numeric_value(exclusive_maximum)) is not None:
        if number >= exclusive_maximum_value:
            issues.append(_invalid_argument_row(contract, "exclusive_maximum"))
    elif maximum is not None and number > maximum:
        issues.append(_invalid_argument_row(contract, "maximum"))

    multiple_of = _numeric_value(contract.get("multiple_of"))
    if multiple_of not in (None, 0.0):
        remainder = number / multiple_of
        if abs(remainder - round(remainder)) > 1e-9:
            issues.append(_invalid_argument_row(contract, "multiple_of"))
    return issues


def _length_constraint_issues(value: Any, contract: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(value, (dict, bytes, bytearray)) or _is_sequence(value):
        return []
    if not any(key in contract for key in ("min_length", "max_length", "pattern")):
        return []
    text = str(value)
    issues: list[dict[str, Any]] = []
    min_length = _integer_value(contract.get("min_length"))
    max_length = _integer_value(contract.get("max_length"))
    if min_length is not None and len(text) < min_length:
        issues.append(_invalid_argument_row(contract, "min_length"))
    if max_length is not None and len(text) > max_length:
        issues.append(_invalid_argument_row(contract, "max_length"))
    pattern = contract.get("pattern")
    if isinstance(pattern, str) and pattern:
        try:
            matches = re.search(pattern, text) is not None
        except re.error:
            matches = True
        if not matches:
            issues.append(_invalid_argument_row(contract, "pattern"))
    return issues


def _array_constraint_issues(value: Any, contract: dict[str, Any]) -> list[dict[str, Any]]:
    if not _is_sequence(value):
        return []
    issues: list[dict[str, Any]] = []
    min_items = _integer_value(contract.get("min_items"))
    max_items = _integer_value(contract.get("max_items"))
    if min_items is not None and len(value) < min_items:
        issues.append(_invalid_argument_row(contract, "min_items"))
    if max_items is not None and len(value) > max_items:
        issues.append(_invalid_argument_row(contract, "max_items"))
    return issues


def _object_constraint_issues(value: Any, contract: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    issues: list[dict[str, Any]] = []
    min_properties = _integer_value(contract.get("min_properties"))
    max_properties = _integer_value(contract.get("max_properties"))
    if min_properties is not None and len(value) < min_properties:
        issues.append(_invalid_argument_row(contract, "min_properties"))
    if max_properties is not None and len(value) > max_properties:
        issues.append(_invalid_argument_row(contract, "max_properties"))
    return issues


def _argument_value_for_validation(
    name: str,
    location: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
) -> tuple[bool, Any]:
    if name in arguments and arguments[name] is not None:
        return True, arguments[name]
    if location == "header":
        return _header_value(headers, name)
    if location == "cookie":
        return _cookie_value(headers, name)
    return False, None


def _contract_value_for_validation(
    name: str,
    location: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
) -> tuple[bool, Any]:
    if location == "body" and name in arguments:
        return True, arguments[name]
    return _argument_value_for_validation(name, location, arguments, headers)


def _argument_present(
    name: str,
    location: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
) -> bool:
    value = arguments.get(name)
    if value is not None:
        return True
    if location == "header":
        return _header_present(headers, name)
    if location == "cookie":
        return _cookie_present(headers, name)
    return False


def _required_argument_present(
    name: str,
    location: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
) -> bool:
    if location == "body" and name in arguments:
        return True
    return _argument_present(name, location, arguments, headers)


def _missing_security_requirements(
    api_metadata: dict[str, Any],
    arguments: dict[str, Any],
    *,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    security = _security_metadata(api_metadata)
    requirements = (
        security.get("requirements") if isinstance(security.get("requirements"), list) else []
    )
    schemes = security.get("schemes") if isinstance(security.get("schemes"), dict) else {}
    if not requirements:
        return []

    missing_alternatives: list[dict[str, Any]] = []
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            continue
        if not requirement:
            return []

        missing_schemes: list[dict[str, Any]] = []
        all_satisfied = True
        for scheme_name, scopes in requirement.items():
            name = str(scheme_name)
            scheme = schemes.get(name) if isinstance(schemes.get(name), dict) else {}
            if _security_scheme_satisfied(name, scheme, arguments, headers):
                continue
            all_satisfied = False
            row = _security_scheme_diagnostic(name, scheme)
            if isinstance(scopes, list) and scopes:
                row["scopes"] = [str(scope) for scope in scopes]
            missing_schemes.append(row)

        if all_satisfied:
            return []
        if missing_schemes:
            missing_alternatives.append(
                {
                    "requirement_index": index,
                    "source": "openapi_security",
                    "schemes": missing_schemes,
                }
            )

    return missing_alternatives


def _security_scheme_satisfied(
    name: str,
    scheme: dict[str, Any],
    arguments: dict[str, Any],
    headers: dict[str, str],
) -> bool:
    if not scheme:
        return False
    scheme_type = str(scheme.get("type") or "").lower()
    if scheme_type == "apikey":
        credential_name = str(scheme.get("name") or "")
        location = str(scheme.get("in") or "").lower()
        if not credential_name or location not in {"query", "header", "cookie"}:
            return False
        return _argument_present(credential_name, location, arguments, headers)
    if scheme_type == "http":
        auth_scheme = str(scheme.get("scheme") or "").lower()
        if auth_scheme in {"bearer", "basic"}:
            return _authorization_header_matches(headers, auth_scheme)
        return _header_present(headers, "Authorization")
    if scheme_type in {"oauth2", "openidconnect"}:
        return _header_present(headers, "Authorization")
    return _header_present(headers, name)


def _security_scheme_diagnostic(name: str, scheme: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "source": "openapi_security_scheme"}
    scheme_type = str(scheme.get("type") or "")
    if scheme_type:
        row["type"] = scheme_type

    if scheme_type.lower() == "apikey":
        location = str(scheme.get("in") or "")
        credential_name = str(scheme.get("name") or "")
        if location:
            row["location"] = location
        if credential_name:
            row["credential_name"] = credential_name
        return row

    auth_scheme = str(scheme.get("scheme") or "")
    if auth_scheme:
        row["scheme"] = auth_scheme
    if scheme_type.lower() in {"http", "oauth2", "openidconnect"}:
        row["location"] = "header"
        row["credential_name"] = "Authorization"
    return row


def _authorization_header_matches(headers: dict[str, str], scheme: str) -> bool:
    prefix = f"{scheme.lower()} "
    for key, value in headers.items():
        if str(key).lower() != "authorization" or value in (None, ""):
            continue
        return str(value).lower().startswith(prefix)
    return False


def _header_value(headers: dict[str, str], name: str) -> tuple[bool, str | None]:
    lower_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower_name and value not in (None, ""):
            return True, str(value)
    return False, None


def _header_present(headers: dict[str, str], name: str) -> bool:
    present, _value = _header_value(headers, name)
    return present


def _cookie_value(headers: dict[str, str], name: str) -> tuple[bool, str | None]:
    cookie_header = ""
    for key, value in headers.items():
        if str(key).lower() == "cookie":
            cookie_header = str(value)
            break
    if not cookie_header:
        return False, None
    prefix = f"{name}="
    for segment in cookie_header.split(";"):
        segment = segment.strip()
        if segment.startswith(prefix):
            return True, segment[len(prefix) :]
    return False, None


def _cookie_present(headers: dict[str, str], name: str) -> bool:
    present, _value = _cookie_value(headers, name)
    return present


def _copy_validation_hint(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in (
        "field_type",
        "json_path",
        "enum",
        "description",
        "format",
        "default",
        "example",
        "nullable",
        "pattern",
        "minimum",
        "maximum",
        "const",
        "exclusive_minimum",
        "exclusive_maximum",
        "min_length",
        "max_length",
        "min_items",
        "max_items",
        "min_properties",
        "max_properties",
        "multiple_of",
        "schema_combinator",
        "schema_branch",
        "schema_branch_count",
        "schema_branches",
        "required_in_branch",
        "schema_ref",
        "content_type",
        "content_types",
        "content_schema_type",
        "content_fields",
        "content_top_level_fields",
        "encoding_content_type",
        "encoding_style",
        "encoding_explode",
        "encoding_allow_reserved",
        "encoding_headers",
        "encoding_field_name",
        "discriminator_property",
        "discriminator_value",
        "discriminator_values",
        "additional_properties",
        "map_value",
        "map_key_placeholder",
    ):
        value = source.get(key)
        if value not in (None, "", []):
            target[key] = list(value) if isinstance(value, list) else value


def _missing_branch_required_inputs(
    body_rows: list[dict[str, Any]],
    arguments: dict[str, Any],
    *,
    selected_content_type: str,
) -> list[dict[str, Any]]:
    discriminator = _selected_discriminator(body_rows, arguments)
    if not discriminator:
        return []
    property_name, value = discriminator
    missing: list[dict[str, Any]] = []
    for row in body_rows:
        if not isinstance(row, dict) or not row.get("required_in_branch"):
            continue
        if not _branch_row_matches_discriminator(row, property_name, value):
            continue
        name = str(row.get("field_name") or "")
        if not name or name == property_name:
            continue
        if _argument_present(name, "body", arguments, {}):
            continue
        item = {
            "name": name,
            "location": "body",
            "source": "request_body_branch",
        }
        if selected_content_type:
            item["content_type"] = selected_content_type
        _copy_validation_hint(row, item)
        missing.append(item)
    return missing


def _selected_discriminator(
    body_rows: list[dict[str, Any]],
    arguments: dict[str, Any],
) -> tuple[str, Any] | None:
    for row in body_rows:
        if not isinstance(row, dict):
            continue
        property_name = str(row.get("discriminator_property") or "")
        if not property_name or property_name not in arguments:
            continue
        value = arguments.get(property_name)
        if value is not None:
            return property_name, value
    return None


def _branch_row_matches_discriminator(
    row: dict[str, Any],
    property_name: str,
    value: Any,
) -> bool:
    if str(row.get("discriminator_property") or "") != property_name:
        return False
    values = row.get("discriminator_values")
    if isinstance(values, list) and values:
        return _enum_matches(value, values)
    if "discriminator_value" in row:
        return _const_matches(value, row.get("discriminator_value"))
    return False


def _location_by_param(api_metadata: dict[str, Any]) -> dict[str, str]:
    locations: dict[str, str] = {}
    for param in api_metadata.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "")
        loc = str(param.get("in") or "")
        if name and loc:
            locations[name] = loc
    for row in _body_rows(api_metadata):
        if isinstance(row, dict) and row.get("field_name"):
            locations.setdefault(str(row["field_name"]), "body")
    for name, location in _security_api_key_locations(api_metadata).items():
        locations.setdefault(name, location)
    return locations


def _security_api_key_locations(api_metadata: dict[str, Any]) -> dict[str, str]:
    security = _security_metadata(api_metadata)
    schemes = security.get("schemes") if isinstance(security.get("schemes"), dict) else {}
    locations: dict[str, str] = {}
    for scheme in schemes.values():
        if not isinstance(scheme, dict):
            continue
        if str(scheme.get("type") or "").lower() != "apikey":
            continue
        name = str(scheme.get("name") or "")
        location = str(scheme.get("in") or "").lower()
        if name and location in {"query", "header", "cookie"}:
            locations[name] = location
    return locations


def _security_metadata(api_metadata: dict[str, Any]) -> dict[str, Any]:
    security = api_metadata.get("security")
    return security if isinstance(security, dict) else {}


def _parameter_metadata_by_name(api_metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for param in api_metadata.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "")
        if name:
            metadata[name] = param
    return metadata


def _body_field_paths(
    api_metadata: dict[str, Any],
    *,
    content_type: str | None = None,
) -> dict[str, str]:
    return _body_field_paths_from_rows(
        _body_rows(api_metadata, content_type=content_type, include_content_type_rows=False)
    )


def _body_field_paths_from_rows(body_rows: list[dict[str, Any]]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for row in body_rows:
        if not isinstance(row, dict):
            continue
        if row.get("map_value") and not _is_request_body_root_row(row):
            continue
        name = str(row.get("field_name") or "")
        json_path = str(row.get("json_path") or "")
        if name and json_path and name not in paths:
            paths[name] = json_path
    return paths


def _body_field_metadata_from_rows(body_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for row in body_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("field_name") or "")
        if name and name not in metadata:
            metadata[name] = row
    return metadata


def _raw_body_argument_present(
    body_rows: list[dict[str, Any]],
    arguments: dict[str, Any],
) -> bool:
    for row in body_rows:
        if not isinstance(row, dict) or not _is_request_body_root_row(row):
            continue
        name = str(row.get("field_name") or "")
        if name and name in arguments:
            return True
    return False


def _body_container_fields_satisfied_by_leaf_args(
    body_rows: list[dict[str, Any]],
    arguments: dict[str, Any],
) -> set[tuple[str, str]]:
    present_paths: list[str] = []
    for row in body_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("field_name") or "")
        json_path = str(row.get("json_path") or "")
        if name and json_path and name in arguments:
            present_paths.append(json_path)

    satisfied: set[tuple[str, str]] = set()
    for row in body_rows:
        if not isinstance(row, dict) or not row.get("required"):
            continue
        field_type = str(row.get("field_type") or "")
        if field_type not in {"array", "object"}:
            continue
        name = str(row.get("field_name") or "")
        json_path = str(row.get("json_path") or "")
        if not name or not json_path or name in arguments:
            continue
        if any(_json_path_descends_from(candidate, json_path) for candidate in present_paths):
            satisfied.add((name, json_path))
    return satisfied


def _json_path_descends_from(candidate: str, parent: str) -> bool:
    if not candidate or not parent or candidate == parent:
        return False
    return candidate.startswith(f"{parent}.") or candidate.startswith(f"{parent}[")


def _is_request_body_root_row(row: dict[str, Any]) -> bool:
    return bool(row.get("request_body_root")) and str(row.get("json_path") or "") == "$"


def _body_rows(
    api_metadata: dict[str, Any],
    *,
    content_type: str | None = None,
    include_content_type_rows: bool = True,
) -> list[dict[str, Any]]:
    request_body = api_metadata.get("request_body") or {}
    if not isinstance(request_body, dict):
        return []
    rows: list[dict[str, Any]] = []

    def extend(source: dict[str, Any]) -> None:
        for row in (source.get("top_level_fields") or []) + (source.get("fields") or []):
            if isinstance(row, dict):
                rows.append(row)

    if content_type:
        for candidate in request_body.get("content_types") or []:
            if not isinstance(candidate, dict):
                continue
            if _same_content_type(str(candidate.get("content_type") or ""), content_type):
                extend(candidate)
                break

    extend(request_body)

    if include_content_type_rows:
        for candidate in request_body.get("content_types") or []:
            if isinstance(candidate, dict):
                extend(candidate)

    return rows


def _request_content_type(
    api_metadata: dict[str, Any],
    metadata: dict[str, Any],
    body_params: dict[str, Any] | None = None,
) -> str:
    request_body = api_metadata.get("request_body") or {}
    declared = _request_content_type_candidates(request_body)
    selected = request_body.get("content_type") or metadata.get("request_content_type")
    if selected:
        selected = str(selected)
    if selected and selected not in declared:
        declared.insert(0, selected)

    if body_params and _body_has_file_value(body_params):
        multipart = next((ct for ct in declared if _is_multipart_content_type(ct)), None)
        if multipart:
            return multipart

    best = (
        _best_matching_content_type(request_body, body_params) if body_params and declared else None
    )
    if selected and selected != "*/*":
        if best and not _same_content_type(best, selected):
            selected_score = _content_type_match_score(request_body, selected, body_params or {})
            best_score = _content_type_match_score(request_body, best, body_params or {})
            if best_score > selected_score:
                return best
        return selected

    if best:
        return best

    json_candidate = next((ct for ct in declared if _is_json_content_type(ct)), None)
    if json_candidate:
        return json_candidate

    content_type = declared[0] if declared else selected or "application/json"
    return "application/json" if content_type == "*/*" else str(content_type)


def _request_content_type_candidates(request_body: Any) -> list[str]:
    if not isinstance(request_body, dict):
        return []
    candidates: list[str] = []
    for row in request_body.get("content_types") or []:
        if not isinstance(row, dict):
            continue
        content_type = str(row.get("content_type") or "")
        if content_type and content_type not in candidates:
            candidates.append(content_type)
    return candidates


def _response_content_type(headers: dict[str, Any]) -> str:
    for name, value in headers.items():
        if str(name).lower() == "content-type":
            return str(value).split(";", 1)[0].strip()
    return ""


def _match_response_metadata(
    api_metadata: dict[str, Any],
    *,
    status: int,
    content_type: str = "",
) -> dict[str, Any]:
    responses = api_metadata.get("responses") or []
    if not isinstance(responses, list):
        return {}

    status_text = str(status)
    fallback_default: dict[str, Any] | None = None
    fallback_range: dict[str, Any] | None = None
    for row in responses:
        if not isinstance(row, dict):
            continue
        declared_status = str(row.get("status") or "")
        if declared_status == "default":
            fallback_default = row
            continue
        if declared_status == status_text:
            return _response_metadata_with_content(row, content_type)
        if _status_range_matches(declared_status, status):
            fallback_range = row

    if fallback_range:
        return _response_metadata_with_content(fallback_range, content_type)
    if fallback_default:
        return _response_metadata_with_content(fallback_default, content_type)
    return {}


def _response_metadata_with_content(row: dict[str, Any], content_type: str) -> dict[str, Any]:
    metadata = dict(row)
    if content_type:
        metadata["matched_content_type"] = content_type
    for candidate in row.get("content_types") or []:
        if not isinstance(candidate, dict):
            continue
        if _same_content_type(str(candidate.get("content_type") or ""), content_type):
            metadata["content_metadata"] = dict(candidate)
            break
    return metadata


def _status_range_matches(declared_status: str, status: int) -> bool:
    text = declared_status.upper()
    return (
        len(text) == 3 and text[0].isdigit() and text[1:] == "XX" and status // 100 == int(text[0])
    )


def _best_matching_content_type(
    request_body: dict[str, Any],
    body_params: dict[str, Any],
) -> str | None:
    best: tuple[int, int, str] | None = None
    for index, row in enumerate(request_body.get("content_types") or []):
        if not isinstance(row, dict):
            continue
        content_type = str(row.get("content_type") or "")
        if not content_type or content_type == "*/*":
            continue
        matches = _content_type_match_score(request_body, content_type, body_params)
        if matches == 0:
            continue
        candidate = (matches, -index, content_type)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def _content_type_match_score(
    request_body: dict[str, Any],
    content_type: str,
    body_params: dict[str, Any],
) -> int:
    keys = {str(key) for key, value in body_params.items() if value is not None}
    for row in request_body.get("content_types") or []:
        if not isinstance(row, dict):
            continue
        if not _same_content_type(str(row.get("content_type") or ""), content_type):
            continue
        fields = {
            str(field.get("field_name") or "")
            for field in (row.get("top_level_fields") or []) + (row.get("fields") or [])
            if isinstance(field, dict)
        }
        return len(keys & fields)
    return 0


def _is_form_content_type(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower() == "application/x-www-form-urlencoded"


def _is_multipart_content_type(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower() == "multipart/form-data"


def _is_json_content_type(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json") or media == "*/*"


def _same_content_type(left: str, right: str) -> bool:
    return left.split(";", 1)[0].strip().lower() == right.split(";", 1)[0].strip().lower()


def _serialize_path_parameter(name: str, value: Any, parameter: dict[str, Any]) -> str:
    content_text = _parameter_content_text(value, parameter)
    if content_text is not None:
        return _quote_path_value(content_text)
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
    content_text = _parameter_content_text(value, parameter)
    if content_text is not None:
        return [_query_pair(name, content_text, allow_reserved=allow_reserved)]

    if style == "deepObject" and isinstance(value, dict):
        return _serialize_deep_object_query_parameter(
            name,
            value,
            allow_reserved=allow_reserved,
        )

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


def _serialize_deep_object_query_parameter(
    name: str,
    value: dict[Any, Any],
    *,
    allow_reserved: bool,
) -> list[str]:
    segments: list[str] = []
    _append_deep_object_query_segments(
        segments,
        str(name),
        value,
        allow_reserved=allow_reserved,
    )
    return segments


def _append_deep_object_query_segments(
    segments: list[str],
    prefix: str,
    value: Any,
    *,
    allow_reserved: bool,
) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None:
                continue
            _append_deep_object_query_segments(
                segments,
                f"{prefix}[{key}]",
                item,
                allow_reserved=allow_reserved,
            )
        return
    if _is_sequence(value):
        if all(not isinstance(item, dict | list | tuple) for item in value):
            for item in value:
                if item is not None:
                    segments.append(
                        _query_pair(
                            prefix,
                            item,
                            allow_reserved=allow_reserved,
                            name_safe_extra="[]",
                        )
                    )
            return
        for index, item in enumerate(value):
            if item is None:
                continue
            _append_deep_object_query_segments(
                segments,
                f"{prefix}[{index}]",
                item,
                allow_reserved=allow_reserved,
            )
        return
    segments.append(
        _query_pair(
            prefix,
            value,
            allow_reserved=allow_reserved,
            name_safe_extra="[]",
        )
    )


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
    content_text = _parameter_content_text(value, parameter)
    if content_text is not None:
        return content_text
    style = str(parameter.get("style") or "simple")
    explode = _explode(parameter, style)
    return _serialize_simple_text(name, value, explode=explode)


def _cookie_segments(name: str, value: Any, parameter: dict[str, Any]) -> list[str]:
    content_text = _parameter_content_text(value, parameter)
    if content_text is not None:
        return [_cookie_pair(name, content_text)]
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


def _is_primitive(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _integer_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and re.fullmatch(r"[-+]?\d+", value.strip()):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _primitive_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _quote_path_value(value: Any) -> str:
    return urllib.parse.quote(_primitive_text(value), safe="")


def _parameter_content_text(value: Any, parameter: dict[str, Any]) -> str | None:
    content_type = str(parameter.get("content_type") or "")
    if not content_type or not _is_json_content_type(content_type):
        return None
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return None


def _explode(parameter: dict[str, Any], style: str) -> bool:
    if "explode" in parameter:
        return bool(parameter["explode"])
    return style == "form"


def _encode_urlencoded_body(
    body_params: dict[str, Any],
    body_field_metadata: dict[str, dict[str, Any]] | None = None,
) -> bytes:
    segments: list[str] = []
    pairs: list[tuple[str, str]] = []
    for name, value in body_params.items():
        if value is None:
            continue
        field_metadata = (body_field_metadata or {}).get(str(name), {})
        if _has_form_encoding_metadata(field_metadata):
            segments.extend(_serialize_form_body_field(str(name), value, field_metadata))
            continue
        if _is_sequence(value):
            pairs.extend((str(name), _primitive_text(item)) for item in value if item is not None)
        elif isinstance(value, dict):
            pairs.append((str(name), json.dumps(value, ensure_ascii=False)))
        else:
            pairs.append((str(name), _primitive_text(value)))
    if pairs:
        segments.append(urllib.parse.urlencode(pairs, doseq=True))
    return "&".join(segment for segment in segments if segment).encode("utf-8")


def _has_form_encoding_metadata(field_metadata: dict[str, Any]) -> bool:
    return any(
        key in field_metadata
        for key in (
            "encoding_content_type",
            "encoding_style",
            "encoding_explode",
            "encoding_allow_reserved",
        )
    )


def _serialize_form_body_field(
    name: str,
    value: Any,
    field_metadata: dict[str, Any],
) -> list[str]:
    parameter = {
        "style": field_metadata.get("encoding_style") or "form",
        "content_type": field_metadata.get("encoding_content_type") or "",
    }
    if "encoding_explode" in field_metadata:
        parameter["explode"] = bool(field_metadata["encoding_explode"])
    if "encoding_allow_reserved" in field_metadata:
        parameter["allowReserved"] = bool(field_metadata["encoding_allow_reserved"])
    return _serialize_query_parameter(name, value, parameter)


def _prepare_multipart_body_parts(
    body_params: dict[str, Any],
    body_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    field_rows = _body_field_metadata_from_rows(body_rows)
    top_level_rows = _top_level_multipart_rows(body_rows)
    direct_names = {str(name) for name in body_params}
    part_values: dict[str, Any] = {}
    part_metadata: dict[str, dict[str, Any]] = {}
    grouped_values: dict[str, Any] = {}

    for name, value in body_params.items():
        field_name = str(name)
        row = field_rows.get(field_name, {})
        parent_row = _multipart_parent_part_row(row, top_level_rows)
        parent_name = str(parent_row.get("field_name") or "") if parent_row else ""
        if (
            parent_row
            and parent_name
            and parent_name != field_name
            and parent_name not in direct_names
            and not _is_file_part_value(value)
        ):
            parent_type = str(parent_row.get("field_type") or "")
            relative_path = _relative_json_path(
                str(row.get("json_path") or ""),
                str(parent_row.get("json_path") or ""),
            )
            grouped_values[parent_name] = _assign_multipart_group_value(
                grouped_values.get(parent_name),
                parent_type,
                relative_path,
                value,
            )
            part_metadata[parent_name] = parent_row
            continue

        part_values[field_name] = value
        if row:
            part_metadata[field_name] = row

    for name, value in grouped_values.items():
        if name not in part_values:
            part_values[name] = value
            if name not in part_metadata and name in field_rows:
                part_metadata[name] = field_rows[name]
    return part_values, part_metadata


def _top_level_multipart_rows(body_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in body_rows:
        if not isinstance(row, dict):
            continue
        json_path = str(row.get("json_path") or "")
        if _top_level_body_json_path(json_path):
            rows.append(row)
    return rows


def _top_level_body_json_path(json_path: str) -> bool:
    if not json_path.startswith("$."):
        return False
    rest = json_path.removeprefix("$.")
    return bool(rest) and "." not in rest and "[" not in rest


def _multipart_parent_part_row(
    row: dict[str, Any],
    top_level_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    json_path = str(row.get("json_path") or "")
    if not json_path:
        return None
    for parent in top_level_rows:
        parent_path = str(parent.get("json_path") or "")
        if parent_path == json_path:
            return None
        parent_type = str(parent.get("field_type") or "")
        if parent_type not in {"object", "array"}:
            continue
        if _json_path_descends_from(json_path, parent_path):
            return parent
    return None


def _relative_json_path(json_path: str, parent_path: str) -> str:
    if not json_path or not parent_path:
        return ""
    if json_path == parent_path:
        return "$"
    if json_path.startswith(f"{parent_path}."):
        return "$" + json_path.removeprefix(parent_path)
    if json_path.startswith(f"{parent_path}[*]"):
        return "$" + json_path.removeprefix(parent_path)
    return ""


def _assign_multipart_group_value(
    existing: Any,
    parent_type: str,
    relative_path: str,
    value: Any,
) -> Any:
    if relative_path in {"", "$"}:
        return value
    if parent_type == "array":
        return _assign_multipart_array_part(existing, relative_path, value)

    body = existing if isinstance(existing, dict) else {}
    if _assign_json_body_value(body, relative_path, value):
        return body
    body[_multipart_fallback_field_name(relative_path)] = value
    return body


def _assign_multipart_array_part(existing: Any, relative_path: str, value: Any) -> Any:
    if not relative_path.startswith("$[*]"):
        return value
    suffix = relative_path.removeprefix("$[*]")
    if not suffix:
        return list(value) if _is_sequence(value) else [value]
    if not suffix.startswith("."):
        return existing if isinstance(existing, list) else []

    items = existing if isinstance(existing, list) else []
    if items and isinstance(items[0], dict):
        item = items[0]
    else:
        item = {}
        if items:
            items[0] = item
        else:
            items.append(item)
    if not _assign_json_body_value(item, "$" + suffix, value):
        item[_multipart_fallback_field_name("$" + suffix)] = value
    return items


def _multipart_fallback_field_name(relative_path: str) -> str:
    path = relative_path.removeprefix("$.").removeprefix("$[*].")
    if not path:
        return "value"
    return path.rsplit(".", 1)[-1].removesuffix("[*]")


def _encode_multipart_body(
    content_type: str,
    body_params: dict[str, Any],
    body_field_metadata: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, bytes]:
    boundary = _multipart_boundary(content_type) or f"----graph-tool-call-{uuid.uuid4().hex}"
    header_content_type = content_type
    if "boundary=" not in content_type.lower():
        header_content_type = f"{content_type}; boundary={boundary}"
    body = _multipart_bytes(
        body_params,
        boundary=boundary,
        body_field_metadata=body_field_metadata or {},
    )
    return header_content_type, body


def _multipart_bytes(
    body_params: dict[str, Any],
    *,
    boundary: str,
    body_field_metadata: dict[str, dict[str, Any]],
) -> bytes:
    chunks: list[bytes] = []
    boundary_bytes = boundary.encode("ascii")
    for name, value in body_params.items():
        if value is None:
            continue
        field_metadata = body_field_metadata.get(str(name), {})
        for item in _iter_multipart_values(value):
            chunks.append(b"--" + boundary_bytes + b"\r\n")
            file_part = _file_part(
                item,
                field_name=str(name),
                default_content_type=_multipart_part_content_type(field_metadata),
            )
            extra_headers = _multipart_part_headers(field_metadata)
            if file_part:
                filename, part_content_type, payload = file_part
                chunks.append(
                    (
                        "Content-Disposition: form-data; "
                        f'name="{_quote_multipart_header_value(str(name))}"; '
                        f'filename="{_quote_multipart_header_value(filename)}"\r\n'
                    ).encode()
                )
                chunks.extend(_multipart_header_chunks(extra_headers))
                chunks.append(f"Content-Type: {part_content_type}\r\n\r\n".encode())
                chunks.append(payload)
                chunks.append(b"\r\n")
                continue

            chunks.append(
                (
                    "Content-Disposition: form-data; "
                    f'name="{_quote_multipart_header_value(str(name))}"\r\n'
                ).encode()
            )
            part_content_type = _multipart_part_content_type(field_metadata)
            if part_content_type:
                chunks.append(f"Content-Type: {part_content_type}\r\n".encode())
            chunks.extend(_multipart_header_chunks(extra_headers))
            chunks.append(b"\r\n")
            chunks.append(_multipart_text(item, content_type=part_content_type).encode("utf-8"))
            chunks.append(b"\r\n")
    chunks.append(b"--" + boundary_bytes + b"--\r\n")
    return b"".join(chunks)


def _iter_multipart_values(value: Any) -> list[Any]:
    if _is_file_part_value(value):
        return [value]
    if _is_sequence(value):
        return [item for item in value if item is not None]
    return [value]


def _body_has_file_value(body_params: dict[str, Any]) -> bool:
    for value in body_params.values():
        if _is_file_part_value(value):
            return True
        if _is_sequence(value) and any(_is_file_part_value(item) for item in value):
            return True
    return False


def _is_file_part_value(value: Any) -> bool:
    if isinstance(value, bytes | bytearray):
        return True
    if isinstance(value, tuple) and len(value) in (2, 3) and isinstance(value[0], str):
        return True
    if isinstance(value, dict):
        has_payload = any(key in value for key in ("content", "data", "bytes"))
        has_file_metadata = any(key in value for key in ("filename", "content_type", "contentType"))
        return has_payload and has_file_metadata
    return hasattr(value, "read")


def _file_part(
    value: Any,
    *,
    field_name: str,
    default_content_type: str = "",
) -> tuple[str, str, bytes] | None:
    fallback_content_type = default_content_type or "application/octet-stream"
    if isinstance(value, bytes | bytearray):
        return field_name, fallback_content_type, bytes(value)

    if isinstance(value, tuple) and len(value) in (2, 3) and isinstance(value[0], str):
        filename = value[0]
        payload = _file_payload(value[1])
        content_type = str(value[2]) if len(value) == 3 and value[2] else fallback_content_type
        return filename, content_type, payload

    if isinstance(value, dict):
        payload_source = None
        for key in ("content", "data", "bytes"):
            if key in value:
                payload_source = value[key]
                break
        if payload_source is not None and (
            "filename" in value or "content_type" in value or "contentType" in value
        ):
            filename = str(value.get("filename") or value.get("name") or field_name)
            content_type = str(
                value.get("content_type") or value.get("contentType") or fallback_content_type
            )
            return filename, content_type, _file_payload(payload_source)

    if hasattr(value, "read"):
        raw = value.read()
        filename = str(getattr(value, "name", field_name) or field_name).rsplit("/", 1)[-1]
        return filename, fallback_content_type, _file_payload(raw)

    return None


def _file_payload(value: Any) -> bytes:
    if hasattr(value, "read"):
        return _file_payload(value.read())
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    return str(value).encode("utf-8")


def _multipart_text(value: Any, *, content_type: str = "") -> str:
    if isinstance(value, dict | list):
        compact = _is_json_content_type(content_type)
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":") if compact else None,
        )
    if _is_json_content_type(content_type) and isinstance(value, str | int | float | bool):
        return json.dumps(value, ensure_ascii=False)
    return _primitive_text(value)


def _multipart_part_content_type(field_metadata: dict[str, Any]) -> str:
    return str(field_metadata.get("encoding_content_type") or "")


def _multipart_part_headers(field_metadata: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for row in _iter_multipart_encoding_header_rows(field_metadata.get("encoding_headers")):
        name = str(row.get("name") or row.get("field_name") or "")
        if not name or name.lower() == "content-type":
            continue
        header_value = _encoding_header_static_value(row)
        if header_value is not None:
            headers[name] = _primitive_text(header_value)
    return headers


def _iter_multipart_encoding_header_rows(headers: Any) -> list[dict[str, Any]]:
    if isinstance(headers, list):
        return [row for row in headers if isinstance(row, dict)]
    if not isinstance(headers, dict):
        return []

    rows: list[dict[str, Any]] = []
    for name, value in headers.items():
        if isinstance(value, dict):
            rows.append({"name": str(name), **value})
        elif value is not None:
            rows.append({"name": str(name), "default": value})
    return rows


def _encoding_header_static_value(row: dict[str, Any]) -> Any:
    for key in ("const", "default", "example"):
        if key in row:
            return row[key]
    examples = row.get("examples")
    if isinstance(examples, list):
        for example in examples:
            if isinstance(example, dict) and "value" in example:
                return example["value"]
    return None


def _multipart_header_chunks(headers: dict[str, str]) -> list[bytes]:
    chunks: list[bytes] = []
    for name, value in headers.items():
        header_name = _safe_multipart_header_name(name)
        if header_name:
            header_value = _safe_multipart_header_value(value)
            chunks.append(f"{header_name}: {header_value}\r\n".encode())
    return chunks


def _safe_multipart_header_name(value: str) -> str:
    name = value.strip().replace("\r", "").replace("\n", "")
    return name if _HTTP_HEADER_NAME_RE.fullmatch(name) else ""


def _safe_multipart_header_value(value: str) -> str:
    return value.replace("\r", "").replace("\n", "")


def _multipart_boundary(content_type: str) -> str | None:
    for segment in content_type.split(";")[1:]:
        name, separator, value = segment.strip().partition("=")
        if separator and name.lower() == "boundary":
            return value.strip().strip('"') or None
    return None


def _quote_multipart_header_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def _encode_raw_body(
    body_params: dict[str, Any],
    body_field_paths: dict[str, str],
    *,
    request_body: dict[str, Any] | None = None,
) -> bytes:
    raw_body = _raw_request_body_value(body_params, body_field_paths, request_body=request_body)
    return _raw_body_bytes(raw_body)


def _raw_request_body_value(
    body_params: dict[str, Any],
    body_field_paths: dict[str, str],
    *,
    request_body: dict[str, Any] | None = None,
) -> Any:
    raw_body = _raw_json_body(body_params, body_field_paths)
    if raw_body is not _NO_RAW_BODY:
        return raw_body

    if len(body_params) == 1:
        return next(iter(body_params.values()))

    return _build_json_body(body_params, body_field_paths, request_body=request_body)


def _raw_body_bytes(value: Any) -> bytes:
    if hasattr(value, "read"):
        return _raw_body_bytes(value.read())
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if value is None:
        return b""
    return _primitive_text(value).encode("utf-8")


def _build_json_body(
    body_params: dict[str, Any],
    body_field_paths: dict[str, str],
    *,
    request_body: dict[str, Any] | None = None,
) -> Any:
    raw_body = _raw_json_body(body_params, body_field_paths)
    if raw_body is not _NO_RAW_BODY:
        return raw_body

    if _request_body_schema_type(request_body) == "array":
        array_body = _build_root_array_json_body(body_params, body_field_paths)
        if array_body is not None:
            return array_body

    body: dict[str, Any] = {}
    for name, value in body_params.items():
        json_path = body_field_paths.get(name)
        if json_path and _assign_json_body_value(body, json_path, value):
            continue
        body[name] = value
    return body


def _assign_json_body_value(body: dict[str, Any], json_path: str, value: Any) -> bool:
    if _can_assign_json_path(json_path):
        _assign_json_path(body, json_path, value)
        return True
    if _can_assign_single_array_json_path(json_path):
        _assign_single_array_json_path(body, json_path, value)
        return True
    return False


def _can_assign_single_array_json_path(json_path: str) -> bool:
    return json_path.startswith("$.") and json_path.count("[*]") == 1 and ".*" not in json_path


def _assign_single_array_json_path(body: dict[str, Any], json_path: str, value: Any) -> None:
    parts = [part for part in json_path.removeprefix("$.").split(".") if part]
    if not parts:
        return

    cursor = body
    for index, part in enumerate(parts):
        if not part.endswith("[*]"):
            if index == len(parts) - 1:
                cursor[part] = value
                return
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
            continue

        array_name = part.removesuffix("[*]")
        if not array_name:
            return
        if index == len(parts) - 1:
            cursor[array_name] = list(value) if _is_sequence(value) else [value]
            return

        existing_array = cursor.get(array_name)
        if not isinstance(existing_array, list):
            existing_array = []
            cursor[array_name] = existing_array
        if existing_array and isinstance(existing_array[0], dict):
            array_item = existing_array[0]
        else:
            array_item = {}
            if existing_array:
                existing_array[0] = array_item
            else:
                existing_array.append(array_item)
        cursor = array_item


_NO_RAW_BODY = object()


def _raw_json_body(body_params: dict[str, Any], body_field_paths: dict[str, str]) -> Any:
    for name, value in body_params.items():
        if body_field_paths.get(name) == "$":
            return value
    return _NO_RAW_BODY


def _request_body_schema_type(request_body: dict[str, Any] | None) -> str:
    if not isinstance(request_body, dict):
        return ""
    root = request_body.get("root")
    if isinstance(root, dict):
        field_type = str(root.get("field_type") or "")
        if field_type:
            return field_type
    schema = request_body.get("schema")
    if isinstance(schema, dict):
        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            return str(next((item for item in schema_type if item and item != "null"), ""))
        return str(schema_type or "")
    return ""


def _build_root_array_json_body(
    body_params: dict[str, Any],
    body_field_paths: dict[str, str],
) -> list[Any] | None:
    item: dict[str, Any] = {}
    for name, value in body_params.items():
        json_path = body_field_paths.get(name)
        if not json_path or not json_path.startswith("$[*]"):
            return None
        suffix = json_path.removeprefix("$[*]")
        if not suffix:
            return list(value) if _is_sequence(value) else [value]
        if not suffix.startswith("."):
            return None
        item_path = "$" + suffix
        if not _can_assign_json_path(item_path):
            return None
        _assign_json_path(item, item_path, value)
    return [item] if item else None


def _can_assign_json_path(json_path: str) -> bool:
    return json_path.startswith("$.") and "[*]" not in json_path and ".*" not in json_path


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
