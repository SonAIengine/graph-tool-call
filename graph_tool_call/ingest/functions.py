"""Ingest plain Python functions into ToolSchema instances."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any, get_type_hints

from graph_tool_call.core.tool import ToolParameter, ToolSchema, normalize_tool

# ---------------------------------------------------------------------------
# Python type -> JSON Schema type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_type_to_str(tp: Any) -> str:
    """Map a Python type annotation to a JSON Schema type string."""
    return _TYPE_MAP.get(tp, "string")


# ---------------------------------------------------------------------------
# Docstring helpers
# ---------------------------------------------------------------------------


def _first_line(docstring: str | None) -> str:
    """Return the first non-empty line of *docstring*, or empty string."""
    if not docstring:
        return ""
    for line in docstring.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_function(fn: Callable[..., Any]) -> ToolSchema:
    """Convert a Python function into a ToolSchema.

    - ``name`` is taken from ``fn.__name__``.
    - ``description`` is the first line of the docstring.
    - Parameters are extracted from ``inspect.signature`` and type hints.
    - A parameter is ``required`` when it has no default value.
    """
    sig = inspect.signature(fn)

    # Try to get type hints; fall back to empty dict on failure
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}

    params: list[ToolParameter] = []
    for name, param in sig.parameters.items():
        # Skip *args, **kwargs, and 'self'/'cls'
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if name in ("self", "cls"):
            continue

        tp = hints.get(name)
        type_str = _python_type_to_str(tp) if tp is not None else "string"
        has_default = param.default is not inspect.Parameter.empty
        params.append(
            ToolParameter(
                name=name,
                type=type_str,
                required=not has_default,
            )
        )

    schema = ToolSchema(
        name=fn.__name__,
        description=_first_line(fn.__doc__),
        parameters=params,
        metadata={"source": "function"},
    )
    return normalize_tool(schema)


def ingest_functions(fns: Iterable[Callable[..., Any]]) -> list[ToolSchema]:
    """Convert multiple Python functions into ToolSchema instances."""
    return [ingest_function(fn) for fn in fns]
