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
import uuid
from typing import Any

from graph_tool_call.core.tool import ToolSchema

_RESERVED_QUERY_CHARS = ":/?#[]@!$&'()*+,;="


class OpenAPIRequestValidationError(ValueError):
    """Raised when OpenAPI request arguments miss required inputs."""

    def __init__(self, tool_name: str, diagnostics: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.diagnostics = diagnostics
        missing = ", ".join(
            f"{item.get('location', 'input')}:{item.get('name', '')}"
            for item in diagnostics.get("missing_required") or []
        )
        message = f"Missing required argument(s) for tool '{tool_name}'"
        if missing:
            message = f"{message}: {missing}"
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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = dict(headers) if headers else {}
        if auth_token:
            self._headers.setdefault("Authorization", f"Bearer {auth_token}")
        self._timeout = timeout
        self._validate_required = validate_required

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

        if self._validate_required:
            diagnostics = self.validate_request(tool, arguments)
            if not diagnostics["valid"]:
                raise OpenAPIRequestValidationError(tool.name, diagnostics)

        method = metadata["method"].upper()
        path_template: str = metadata["path"]
        api_metadata = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}
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
            content_type = _request_content_type(api_metadata, metadata, body_params)
            body_field_paths = _body_field_paths(api_metadata, content_type=content_type)
            if _is_form_content_type(content_type):
                headers["Content-Type"] = content_type
                data = _encode_urlencoded_body(body_params)
            elif _is_multipart_content_type(content_type):
                content_type, data = _encode_multipart_body(content_type, body_params)
                headers["Content-Type"] = content_type
            else:
                headers["Content-Type"] = content_type
                body = _build_json_body(body_params, body_field_paths)
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")

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
        unused_arguments = [
            str(name)
            for name, value in arguments.items()
            if value is not None and str(name) not in known_name_set
        ]
        return {
            "valid": not missing_required,
            "missing_required": missing_required,
            "unused_arguments": unused_arguments,
            "used_arguments": used_by_location,
            "selected_content_type": selected_content_type,
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
    return names


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
        value = arguments.get(name)
        if value is None:
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
        if _argument_present(name, location, arguments, headers):
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
    has_body_argument = bool(
        _used_arguments_by_location(
            tool,
            arguments,
            api_metadata,
            method=method,
            path_template=path_template,
        )["body"]
    )
    for row in body_rows:
        if not isinstance(row, dict) or not row.get("required"):
            continue
        name = str(row.get("field_name") or "")
        if not name:
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

    request_body = api_metadata.get("request_body") or {}
    if (
        method in ("POST", "PUT", "PATCH")
        and isinstance(request_body, dict)
        and request_body.get("required")
        and not body_rows
        and not has_body_argument
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


def _header_present(headers: dict[str, str], name: str) -> bool:
    lower_name = name.lower()
    return any(
        str(key).lower() == lower_name and value not in (None, "") for key, value in headers.items()
    )


def _cookie_present(headers: dict[str, str], name: str) -> bool:
    cookie_header = ""
    for key, value in headers.items():
        if str(key).lower() == "cookie":
            cookie_header = str(value)
            break
    if not cookie_header:
        return False
    prefix = f"{name}="
    return any(segment.strip().startswith(prefix) for segment in cookie_header.split(";"))


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
        "min_length",
        "max_length",
        "min_items",
        "max_items",
    ):
        value = source.get(key)
        if value not in (None, "", []):
            target[key] = list(value) if isinstance(value, list) else value


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


def _body_field_paths(
    api_metadata: dict[str, Any],
    *,
    content_type: str | None = None,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    for row in _body_rows(api_metadata, content_type=content_type, include_content_type_rows=False):
        if not isinstance(row, dict):
            continue
        name = str(row.get("field_name") or "")
        json_path = str(row.get("json_path") or "")
        if name and json_path and name not in paths:
            paths[name] = json_path
    return paths


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


def _encode_urlencoded_body(body_params: dict[str, Any]) -> bytes:
    pairs: list[tuple[str, str]] = []
    for name, value in body_params.items():
        if value is None:
            continue
        if _is_sequence(value):
            pairs.extend((str(name), _primitive_text(item)) for item in value if item is not None)
        elif isinstance(value, dict):
            pairs.append((str(name), json.dumps(value, ensure_ascii=False)))
        else:
            pairs.append((str(name), _primitive_text(value)))
    return urllib.parse.urlencode(pairs, doseq=True).encode("utf-8")


def _encode_multipart_body(
    content_type: str,
    body_params: dict[str, Any],
) -> tuple[str, bytes]:
    boundary = _multipart_boundary(content_type) or f"----graph-tool-call-{uuid.uuid4().hex}"
    header_content_type = content_type
    if "boundary=" not in content_type.lower():
        header_content_type = f"{content_type}; boundary={boundary}"
    body = _multipart_bytes(body_params, boundary=boundary)
    return header_content_type, body


def _multipart_bytes(body_params: dict[str, Any], *, boundary: str) -> bytes:
    chunks: list[bytes] = []
    boundary_bytes = boundary.encode("ascii")
    for name, value in body_params.items():
        if value is None:
            continue
        for item in _iter_multipart_values(value):
            chunks.append(b"--" + boundary_bytes + b"\r\n")
            file_part = _file_part(item, field_name=str(name))
            if file_part:
                filename, part_content_type, payload = file_part
                chunks.append(
                    (
                        "Content-Disposition: form-data; "
                        f'name="{_quote_multipart_header_value(str(name))}"; '
                        f'filename="{_quote_multipart_header_value(filename)}"\r\n'
                    ).encode()
                )
                chunks.append(f"Content-Type: {part_content_type}\r\n\r\n".encode())
                chunks.append(payload)
                chunks.append(b"\r\n")
                continue

            chunks.append(
                (
                    "Content-Disposition: form-data; "
                    f'name="{_quote_multipart_header_value(str(name))}"\r\n\r\n'
                ).encode()
            )
            chunks.append(_multipart_text(item).encode("utf-8"))
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


def _file_part(value: Any, *, field_name: str) -> tuple[str, str, bytes] | None:
    if isinstance(value, bytes | bytearray):
        return field_name, "application/octet-stream", bytes(value)

    if isinstance(value, tuple) and len(value) in (2, 3) and isinstance(value[0], str):
        filename = value[0]
        payload = _file_payload(value[1])
        content_type = str(value[2]) if len(value) == 3 and value[2] else "application/octet-stream"
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
                value.get("content_type") or value.get("contentType") or "application/octet-stream"
            )
            return filename, content_type, _file_payload(payload_source)

    if hasattr(value, "read"):
        raw = value.read()
        filename = str(getattr(value, "name", field_name) or field_name).rsplit("/", 1)[-1]
        return filename, "application/octet-stream", _file_payload(raw)

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


def _multipart_text(value: Any) -> str:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return _primitive_text(value)


def _multipart_boundary(content_type: str) -> str | None:
    for segment in content_type.split(";")[1:]:
        name, separator, value = segment.strip().partition("=")
        if separator and name.lower() == "boundary":
            return value.strip().strip('"') or None
    return None


def _quote_multipart_header_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


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
