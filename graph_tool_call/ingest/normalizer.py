"""Normalize Swagger 2.0 / OpenAPI 3.0 / 3.1 specs into a common internal format."""

from __future__ import annotations

import copy
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SpecVersion(str, Enum):
    """Supported OpenAPI specification versions."""

    SWAGGER_2_0 = "swagger_2.0"
    OPENAPI_3_0 = "openapi_3.0"
    OPENAPI_3_1 = "openapi_3.1"


class NormalizedSpec(BaseModel):
    """Unified internal representation of an API specification."""

    version: SpecVersion
    info: dict[str, Any] = Field(default_factory=dict)
    servers: list[dict[str, Any]] = Field(default_factory=list)
    paths: dict[str, Any] = Field(default_factory=dict)
    schemas: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


def detect_version(spec: dict[str, Any]) -> SpecVersion:
    """Detect the OpenAPI/Swagger version from the spec dict."""
    if "swagger" in spec:
        version_str = str(spec["swagger"])
        if version_str.startswith("2"):
            return SpecVersion.SWAGGER_2_0
    if "openapi" in spec:
        version_str = str(spec["openapi"])
        if version_str.startswith("3.1"):
            return SpecVersion.OPENAPI_3_1
        if version_str.startswith("3"):
            return SpecVersion.OPENAPI_3_0
    msg = f"Cannot detect spec version from keys: {list(spec.keys())}"
    raise ValueError(msg)


def _slugify_path(path: str) -> str:
    """Convert a URL path to a snake_case slug for operationId generation.

    Examples:
        /users/{userId} -> users_by_userId
        /pets           -> pets
    """
    # Strip leading/trailing slashes
    stripped = path.strip("/")
    # Replace path params {foo} with by_foo
    stripped = re.sub(r"\{(\w+)\}", r"by_\1", stripped)
    # Replace remaining slashes and non-word chars with underscores
    slug = re.sub(r"[/\-]+", "_", stripped)
    # Collapse multiple underscores
    slug = re.sub(r"_+", "_", slug)
    return slug


def _ensure_operation_ids(paths: dict[str, Any]) -> dict[str, Any]:
    """Auto-generate operationId for operations that lack one."""
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in methods:
            operation = path_item.get(method)
            if isinstance(operation, dict) and not operation.get("operationId"):
                slug = _slugify_path(path)
                operation["operationId"] = f"{method}_{slug}"
    return paths


def _normalize_swagger20(spec: dict[str, Any]) -> NormalizedSpec:
    """Normalize a Swagger 2.0 spec to the common format."""
    raw = copy.deepcopy(spec)

    # Convert host + basePath + schemes -> servers
    servers: list[dict[str, Any]] = []
    host = spec.get("host", "")
    base_path = spec.get("basePath", "")
    schemes = spec.get("schemes", ["https"])
    if host:
        for scheme in schemes:
            servers.append({"url": f"{scheme}://{host}{base_path}"})

    # Convert definitions -> schemas
    schemas = spec.get("definitions", {})

    # Build info with consumes/produces metadata
    info = dict(spec.get("info", {}))
    if "consumes" in spec:
        info["consumes"] = spec["consumes"]
    if "produces" in spec:
        info["produces"] = spec["produces"]

    paths = copy.deepcopy(spec.get("paths", {}))
    paths = _ensure_operation_ids(paths)

    return NormalizedSpec(
        version=SpecVersion.SWAGGER_2_0,
        info=info,
        servers=servers,
        paths=paths,
        schemas=schemas,
        raw=raw,
    )


def _convert_nullable_anyof(schema: Any) -> Any:
    """Recursively convert OpenAPI 3.1 anyOf-with-null to 3.0 nullable pattern."""
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if key == "anyOf" and isinstance(value, list):
            non_null = [s for s in value if not (isinstance(s, dict) and s.get("type") == "null")]
            has_null = len(non_null) < len(value)
            if has_null and len(non_null) == 1:
                # Flatten: merge the non-null schema and add nullable
                merged = _convert_nullable_anyof(non_null[0])
                if isinstance(merged, dict):
                    result.update(merged)
                result["nullable"] = True
                continue
            # Keep anyOf but recurse into each element
            result[key] = [_convert_nullable_anyof(s) for s in value]
        elif isinstance(value, dict):
            result[key] = _convert_nullable_anyof(value)
        elif isinstance(value, list):
            result[key] = [_convert_nullable_anyof(item) for item in value]
        else:
            result[key] = value

    return result


def _normalize_openapi31(spec: dict[str, Any]) -> NormalizedSpec:
    """Normalize an OpenAPI 3.1 spec — mainly unify nullable patterns."""
    raw = copy.deepcopy(spec)

    schemas = copy.deepcopy(spec.get("components", {}).get("schemas", {}))
    schemas = {k: _convert_nullable_anyof(v) for k, v in schemas.items()}

    paths = copy.deepcopy(spec.get("paths", {}))
    paths = _convert_nullable_anyof(paths)
    paths = _ensure_operation_ids(paths)

    return NormalizedSpec(
        version=SpecVersion.OPENAPI_3_1,
        info=dict(spec.get("info", {})),
        servers=list(spec.get("servers", [])),
        paths=paths,
        schemas=schemas,
        raw=raw,
    )


def _normalize_openapi30(spec: dict[str, Any]) -> NormalizedSpec:
    """Normalize an OpenAPI 3.0 spec (already close to target format)."""
    raw = copy.deepcopy(spec)

    paths = copy.deepcopy(spec.get("paths", {}))
    paths = _ensure_operation_ids(paths)

    return NormalizedSpec(
        version=SpecVersion.OPENAPI_3_0,
        info=dict(spec.get("info", {})),
        servers=list(spec.get("servers", [])),
        paths=paths,
        schemas=copy.deepcopy(spec.get("components", {}).get("schemas", {})),
        raw=raw,
    )


def normalize(spec: dict[str, Any]) -> NormalizedSpec:
    """Detect spec version and normalize to common internal format."""
    version = detect_version(spec)
    if version == SpecVersion.SWAGGER_2_0:
        return _normalize_swagger20(spec)
    if version == SpecVersion.OPENAPI_3_1:
        return _normalize_openapi31(spec)
    return _normalize_openapi30(spec)
