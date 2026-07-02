"""Argument coercion against a tool's parameter schema.

Deterministic, no-LLM cleanup of resolved step arguments right before a tool
call:

  * **Type casting** — a value that arrived as a string but the parameter
    declares ``integer`` / ``number`` / ``boolean`` is cast (``"3"`` → ``3``,
    ``"true"`` → ``True``). Bindings and user input routinely stringify
    numbers; the backend then 400s on a type mismatch.
  * **Fuzzy enum** — a value that isn't an exact enum member is matched
    case-insensitively with separators folded (``"IN PROGRESS"`` →
    ``"in_progress"``), reusing the synthesizer's ``_normalize_field_name``.

The rules mirror :mod:`graph_tool_call.assist.validator` (which corrects
*LLM-authored* calls) but run on *resolved* plan args and never mutate the
input — a :class:`CoercionReport` carries the corrected copy plus an audit of
what changed and which enum fields stayed unresolved. Both flags default on;
turn either off to narrow the behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.plan.synthesizer import _normalize_field_name

__all__ = ["CoercionReport", "coerce_args"]

_INT_TYPES = frozenset({"int", "integer"})
_FLOAT_TYPES = frozenset({"number", "float", "double"})
_BOOL_TYPES = frozenset({"bool", "boolean"})
_TRUE_STRINGS = frozenset({"true", "1", "yes", "y"})
_FALSE_STRINGS = frozenset({"false", "0", "no", "n"})


@dataclass
class CoercionReport:
    """Outcome of :func:`coerce_args`.

    ``corrected`` is a fresh dict (input untouched). ``changes`` lists each
    applied correction as ``{"field", "from", "to", "rule"}`` (rule ∈
    ``cast`` / ``enum``). ``unresolved`` names enum fields whose value matched
    no member even after folding — left as-is for the backend to reject.
    """

    corrected: dict[str, Any]
    changes: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def coerce_args(
    tool: ToolSchema,
    args: dict[str, Any],
    *,
    fuzzy_enum: bool = True,
    cast_types: bool = True,
) -> CoercionReport:
    """Coerce *args* to fit *tool*'s parameter schema (non-mutating).

    Only known parameters are touched; unknown args pass through untouched
    (name validation is the validator's job, not coercion's). Casting is
    conservative — it only ever upgrades a *string* to a scalar and never
    reinterprets an already-correct type (a real ``bool`` is left alone even
    though ``bool`` is an ``int`` subclass).
    """
    param_map = {p.name: p for p in tool.parameters}
    corrected: dict[str, Any] = dict(args)
    changes: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for name, val in list(corrected.items()):
        param = param_map.get(name)
        if param is None:
            continue

        if cast_types:
            new_val = _cast(val, param.type)
            if new_val is not _UNCHANGED:
                changes.append({"field": name, "from": val, "to": new_val, "rule": "cast"})
                corrected[name] = new_val
                val = new_val

        if fuzzy_enum and param.enum and isinstance(val, str) and val not in param.enum:
            match = _fuzzy_enum(val, param.enum)
            if match is not None:
                changes.append({"field": name, "from": val, "to": match, "rule": "enum"})
                corrected[name] = match
            else:
                unresolved.append(name)

    return CoercionReport(corrected=corrected, changes=changes, unresolved=unresolved)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# Sentinel: "no cast applied" — distinct from a legitimately cast ``None``.
_UNCHANGED: Any = object()


def _cast(val: Any, declared_type: str) -> Any:
    """Return a cast value, or ``_UNCHANGED`` when nothing applies.

    Casts a ``str`` to the parameter's declared scalar type. Non-strings pass
    through unchanged (already the right shape, or too ambiguous to touch).
    """
    t = (declared_type or "").strip().lower()

    # bool → int is a Python footgun (True == 1); never re-cast a real bool.
    if isinstance(val, bool):
        return _UNCHANGED
    if not isinstance(val, str):
        return _UNCHANGED

    s = val.strip()
    if not s:
        return _UNCHANGED

    if t in _INT_TYPES:
        try:
            return int(s)
        except ValueError:
            return _UNCHANGED
    if t in _FLOAT_TYPES:
        try:
            return float(s)
        except ValueError:
            return _UNCHANGED
    if t in _BOOL_TYPES:
        low = s.lower()
        if low in _TRUE_STRINGS:
            return True
        if low in _FALSE_STRINGS:
            return False
        return _UNCHANGED
    return _UNCHANGED


def _fuzzy_enum(val: str, allowed: list[str]) -> str | None:
    """Match *val* against *allowed* by case + separator folding.

    Returns the canonical member on a unique fold-match, else ``None``.
    ``_normalize_field_name`` lowercases and drops non-alphanumerics, so
    ``"IN-PROGRESS"`` / ``"in progress"`` / ``"inProgress"`` all fold to
    ``"inprogress"``.
    """
    target = _normalize_field_name(val)
    if not target:
        return None
    matches = [a for a in allowed if _normalize_field_name(a) == target]
    if len(matches) == 1:
        return matches[0]
    return None
