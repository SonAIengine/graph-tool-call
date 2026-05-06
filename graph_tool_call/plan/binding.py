"""Binding resolver for Plan args.

Substitutes ``${source.dotted.path}`` placeholders in step arguments with
actual values drawn from the runtime context. The context is a dict mapping
source names (``"s1"``, ``"s2"``, ``"input"``, ...) to arbitrary JSON-like
objects.

v1 path syntax (kept deliberately small):

  - dotted keys          : ``s1.body.goods`` → ``ctx["s1"]["body"]["goods"]``
  - array index          : ``s1.body.goods[0].goodsNo``
  - whole-source         : ``s1`` → entire result dict of step s1
  - input alias          : ``input.keyword`` — caller injects a special
                           ``"input"`` entry at runtime for user-provided
                           entities extracted by Stage 1.

Explicitly NOT supported in v1:

  - wildcard ``[*]`` (fan-out) — see §11.1 of the design doc
  - filter expressions (JSONPath ``[?(...)]``)
  - functions / casts (``int(...)``, ``default(...)``)

Behavior rules:

  1. If a string argument is **entirely** one binding (``"${s1.id}"``) the
     resolved value keeps its native type (int, dict, list, ...). This is
     important so integer IDs aren't accidentally stringified.
  2. If a string contains bindings mixed with literal text
     (``"prefix-${s1.id}"``) each binding is ``str()``-cast during
     interpolation. The result is always a string.
  3. Unresolved bindings raise ``BindingError`` — callers should treat
     this as a plan validation failure, not a tool execution error.
  4. ``dict`` and ``list`` values are walked recursively.
"""

from __future__ import annotations

import re
from typing import Any


class BindingError(ValueError):
    """Raised when a ``${...}`` expression cannot be resolved."""


# Matches one ``${...}`` placeholder. Accepts empty body so ``${}`` triggers
# a clear BindingError downstream instead of passing through as a literal.
# ``{`` and ``}`` inside a binding are not supported in v1.
_BINDING_RE = re.compile(r"\$\{([^${}]*)\}")


def resolve_bindings(value: Any, context: dict[str, Any]) -> Any:
    """Recursively resolve bindings in *value* against *context*.

    Dict/list values are walked; strings are interpolated. Non-string
    scalars pass through unchanged.
    """
    if isinstance(value, dict):
        return {k: resolve_bindings(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_bindings(v, context) for v in value]
    if isinstance(value, str):
        return _resolve_string(value, context)
    return value


def _resolve_string(s: str, context: dict[str, Any]) -> Any:
    """Resolve a string value.

    If the string is exactly one binding (``${path}``), returns the native
    value. Otherwise substitutes each match with its stringified form.
    """
    # Whole-string binding → native type
    m = _BINDING_RE.fullmatch(s.strip())
    if m:
        return _lookup(m.group(1).strip(), context)

    # Mixed / multi-binding → string interpolation
    def _sub(match: re.Match[str]) -> str:
        val = _lookup(match.group(1).strip(), context)
        return "" if val is None else str(val)

    return _BINDING_RE.sub(_sub, s)


def _lookup(expr: str, context: dict[str, Any]) -> Any:
    """Walk a dotted path with optional ``[N]`` indices against *context*."""
    tokens = _tokenize(expr)
    if not tokens:
        raise BindingError(f"empty binding expression: {expr!r}")

    head = tokens[0]
    if head not in context:
        raise BindingError(
            f"unknown source {head!r} in binding ${{...}}: context has {sorted(context)!r}"
        )
    node: Any = context[head]

    for tok in tokens[1:]:
        if tok.startswith("[") and tok.endswith("]"):
            # array index — allow negative too
            try:
                idx = int(tok[1:-1])
            except ValueError as exc:
                raise BindingError(f"non-numeric array index {tok!r} in binding {expr!r}") from exc
            if not isinstance(node, (list, tuple)):
                raise BindingError(
                    f"indexing {tok} on non-list type {type(node).__name__} (expr={expr!r})"
                )
            try:
                node = node[idx]
            except IndexError as exc:
                raise BindingError(f"index {idx} out of range in binding {expr!r}") from exc
        else:
            if not isinstance(node, dict):
                raise BindingError(
                    f"cannot descend into .{tok} on non-dict type {type(node).__name__} "
                    f"(expr={expr!r})"
                )
            if tok not in node:
                raise BindingError(
                    f"key {tok!r} not found in binding {expr!r} "
                    f"(available: {sorted(node)[:8]!r}...)"
                )
            node = node[tok]

    return node


def _tokenize(expr: str) -> list[str]:
    """Tokenize a dotted path with ``[N]`` indices.

    ``s1.body.goods[0].goodsNo`` → ``["s1", "body", "goods", "[0]", "goodsNo"]``
    """
    tokens: list[str] = []
    buf = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == ".":
            if buf:
                tokens.append("".join(buf))
                buf = []
        elif ch == "[":
            if buf:
                tokens.append("".join(buf))
                buf = []
            end = expr.find("]", i)
            if end == -1:
                raise BindingError(f"unclosed '[' in binding {expr!r}")
            tokens.append(expr[i : end + 1])
            i = end
        else:
            buf.append(ch)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


__all__ = ["BindingError", "resolve_bindings"]
