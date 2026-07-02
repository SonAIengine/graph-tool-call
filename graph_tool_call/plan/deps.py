"""Static dependency analysis for Plan artifacts.

A ``Plan`` is executed linearly (steps in listed order), but its *data*
dependencies form a DAG: each step's ``args`` may bind to earlier steps'
outputs via ``${sN.path}`` placeholders. This module reads those bindings
back out — without executing anything — so recovery logic can answer two
questions cheaply:

  * ``compute_step_deps`` — for each step, which earlier steps does it
    consume? (the reverse of the producer chain the synthesizer built)
  * ``is_output_consumed`` — if a step fails, can we safely skip it, or does
    a later step (or the plan's final output) depend on its result?

The binding grammar is shared with :mod:`graph_tool_call.plan.binding`
(``_BINDING_RE``) so this stays in lock-step with the resolver — a change to
the placeholder syntax is picked up here for free.

Non-step heads (``input`` / ``user_input``) are intentionally ignored: they
are runtime-supplied context, not inter-step edges.
"""

from __future__ import annotations

import re
from typing import Any

from graph_tool_call.plan.binding import _BINDING_RE
from graph_tool_call.plan.schema import Plan

# Split a binding expression at its first path separator (``.`` or ``[``) to
# isolate the *head* — the source name (``s1`` / ``input`` / ``user_input``).
_HEAD_SPLIT_RE = re.compile(r"[.\[]")

__all__ = ["compute_step_deps", "is_output_consumed", "binding_heads"]


def binding_heads(value: Any) -> set[str]:
    """Collect the *head* (source name) of every ``${...}`` binding in *value*.

    Walks dict / list / str the same way ``resolve_bindings`` does. Returns
    the set of source names referenced, e.g. ``{"s1", "input"}`` for
    ``{"a": "${s1.body.id}", "b": "prefix-${input.kw}"}``. Empty bindings
    (``${}``) are skipped — they surface as ``BindingError`` at resolve time,
    not as a dependency edge.
    """
    heads: set[str] = set()
    _collect_heads(value, heads)
    return heads


def _collect_heads(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _collect_heads(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_heads(v, out)
    elif isinstance(value, str):
        for m in _BINDING_RE.finditer(value):
            expr = m.group(1).strip()
            if not expr:
                continue
            head = _HEAD_SPLIT_RE.split(expr, maxsplit=1)[0].strip()
            if head:
                out.add(head)


def compute_step_deps(plan: Plan) -> dict[str, set[str]]:
    """Map each step id → the set of earlier step ids its args reference.

    Only heads that are *actual step ids in this plan* count as dependencies;
    ``input`` / ``user_input`` and any dangling reference are dropped. A step
    never depends on itself. Steps with no binding to a sibling get an empty
    set (linear-only semantics preserved).
    """
    step_ids = {s.id for s in plan.steps}
    deps: dict[str, set[str]] = {}
    for step in plan.steps:
        refs = {h for h in binding_heads(step.args) if h in step_ids and h != step.id}
        deps[step.id] = refs
    return deps


def is_output_consumed(plan: Plan, step_id: str, after_index: int) -> bool:
    """Is ``step_id``'s output referenced by anything that runs after it?

    ``after_index`` is the 0-based position of ``step_id`` in ``plan.steps``.
    Returns True if any *later* step binds to ``step_id`` **or** the plan's
    ``output_binding`` points at it — in either case dropping the step would
    lose data a downstream consumer needs. A False result means the step is a
    safe skip candidate (its result feeds nothing further).
    """
    for later in plan.steps[after_index + 1 :]:
        if step_id in binding_heads(later.args):
            return True
    if plan.output_binding and step_id in binding_heads(plan.output_binding):
        return True
    return False
