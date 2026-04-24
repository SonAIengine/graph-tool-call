"""PathSynthesizer — Stage 2 of Plan-and-Execute.

Given a target tool and user-provided entities, walk the ToolGraph's
produces/consumes metadata backwards to construct a Plan (ordered steps +
bindings) that, when executed by PlanRunner, satisfies the target.

This module is transport-agnostic. It consumes a plain ``graph`` dict (the
shape persisted as ``api_tool_collections.graph.graph``) — no DB, no HTTP.

v1 scope (per design §16.6):
  - Linear chain only — no fan-out, no parallel, no branching.
  - If multiple producers exist for a required field, the first one is
    picked (simple, predictable). Ambiguity handling is Phase D+.
  - Max recursion depth = 5 (guard against cyclic or pathological graphs).

Matching order for each required consume field:
  1. User ``entities`` (Stage 1 output) — preferred, no extra step.
  2. Another tool's ``produces`` with the same ``semantic_tag``
     (Pass 2 LLM enrichment quality).
  3. Another tool's ``produces`` with the same ``field_name``
     (Pass 1 deterministic extraction, fallback).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from graph_tool_call.plan.schema import Plan, PlanStep


class PlanSynthesisError(Exception):
    """Base class for synthesis failures."""


class UnsatisfiableFieldError(PlanSynthesisError):
    """A required field cannot be supplied by entities or any producer."""


class CyclicDependencyError(PlanSynthesisError):
    """The synthesis trace revisits a tool already in progress."""


class MaxDepthExceededError(PlanSynthesisError):
    """Recursion depth exceeded — likely a misshapen graph."""


@dataclass
class _PartialStep:
    """In-progress step being built during bottom-up synthesis."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    step_id: str = ""                          # assigned at topological sort


class PathSynthesizer:
    """Deterministic plan builder driven by graph ``produces``/``consumes``.

    Usage::

        syn = PathSynthesizer(graph_dict)
        plan = syn.synthesize(
            target="seltProductDetailInfo",
            entities={"search_keyword": "quarzen 티셔츠"},
        )
    """

    def __init__(
        self,
        graph: dict[str, Any],
        *,
        max_depth: int = 5,
    ) -> None:
        self._tools: dict[str, dict[str, Any]] = dict(graph.get("tools") or {})
        self._max_depth = max_depth
        # semantic_tag -> [tool_name], insertion order preserved
        self._producers_by_semantic: dict[str, list[str]] = {}
        self._producers_by_field: dict[str, list[str]] = {}
        self._build_producer_indexes()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def synthesize(
        self,
        *,
        target: str,
        entities: dict[str, Any] | None = None,
        goal: str = "",
    ) -> Plan:
        """Build a Plan whose final step is ``target`` with required args
        filled by entities + prerequisite steps.

        Raises ``UnsatisfiableFieldError`` if a required field has no
        producer or entity mapping.
        """
        if target not in self._tools:
            raise PlanSynthesisError(f"target tool not in graph: {target!r}")

        entities = entities or {}
        steps_by_tool: dict[str, _PartialStep] = {}
        visiting: set[str] = set()

        # Resolve recursively; populates steps_by_tool with target at the end
        self._resolve(
            tool_name=target,
            entities=entities,
            steps_by_tool=steps_by_tool,
            visiting=visiting,
            depth=0,
        )

        # Assign topological ids s1..sN by insertion order
        ordered_tools = list(steps_by_tool.keys())
        for idx, tool_name in enumerate(ordered_tools, start=1):
            steps_by_tool[tool_name].step_id = f"s{idx}"

        # Replace tool-name bindings with step-id bindings
        final_steps: list[PlanStep] = []
        for tool_name in ordered_tools:
            partial = steps_by_tool[tool_name]
            args = {
                k: self._rewrite_tool_refs(v, steps_by_tool)
                for k, v in partial.args.items()
            }
            final_steps.append(PlanStep(
                id=partial.step_id,
                tool=partial.tool,
                args=args,
                rationale=partial.rationale,
            ))

        target_step_id = steps_by_tool[target].step_id
        return Plan(
            id=str(uuid.uuid4()),
            goal=goal or f"Execute {target}",
            steps=final_steps,
            output_binding=f"${{{target_step_id}.body}}",
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "target": target,
                "entities": dict(entities),
                "synthesized_by": "PathSynthesizer/v1",
            },
        )

    # ------------------------------------------------------------------
    # core recursion
    # ------------------------------------------------------------------

    def _resolve(
        self,
        *,
        tool_name: str,
        entities: dict[str, Any],
        steps_by_tool: dict[str, _PartialStep],
        visiting: set[str],
        depth: int,
    ) -> str:
        """Ensure ``tool_name`` has a PartialStep with resolved args.

        Returns the tool name itself (used as a placeholder in args until
        step_ids are assigned by the caller).
        """
        if depth > self._max_depth:
            raise MaxDepthExceededError(
                f"synthesis exceeded max_depth={self._max_depth} at {tool_name!r}"
            )
        if tool_name in steps_by_tool:
            return tool_name
        if tool_name in visiting:
            raise CyclicDependencyError(
                f"cycle detected at {tool_name!r} (chain: {sorted(visiting)!r})"
            )
        visiting.add(tool_name)

        tool = self._tools.get(tool_name) or {}
        metadata = tool.get("metadata") or {}
        consumes = metadata.get("consumes") or []

        args: dict[str, Any] = {}
        rationales: list[str] = []

        for consume in consumes:
            if not consume.get("required"):
                continue

            field_name = consume.get("field_name") or ""
            semantic = consume.get("semantic_tag") or ""

            # 1. Entity match (user-supplied)
            entity_val = self._match_entity(entities, semantic, field_name)
            if entity_val is not None:
                args[field_name] = entity_val
                continue

            # 2/3. Find a producer (semantic first, then field_name)
            producer = self._find_producer(
                semantic=semantic, field_name=field_name,
                exclude=tool_name,
            )
            if producer is None:
                raise UnsatisfiableFieldError(
                    f"tool {tool_name!r} requires {field_name!r} "
                    f"(semantic={semantic!r}) but no entity or producer found"
                )

            # Recurse into the producer first so step_id ordering is correct
            self._resolve(
                tool_name=producer,
                entities=entities,
                steps_by_tool=steps_by_tool,
                visiting=visiting,
                depth=depth + 1,
            )

            # Build a placeholder binding — will be rewritten after step_ids
            # are assigned. Format: ${<tool_name>.<jsonpath-sans-root>}
            prod_path = self._producer_jsonpath(producer, semantic, field_name)
            args[field_name] = f"${{{producer}.{prod_path}}}"
            rationales.append(f"{field_name} ← {producer} ({prod_path})")

        steps_by_tool[tool_name] = _PartialStep(
            tool=tool_name,
            args=args,
            rationale="; ".join(rationales) if rationales else "",
        )
        visiting.discard(tool_name)
        return tool_name

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _build_producer_indexes(self) -> None:
        """Index which tools produce which semantic / field across graph."""
        for name, tool in self._tools.items():
            meta = tool.get("metadata") or {}
            for produce in meta.get("produces") or []:
                sem = produce.get("semantic_tag") or ""
                fname = produce.get("field_name") or ""
                if sem:
                    self._producers_by_semantic.setdefault(sem, []).append(name)
                if fname:
                    self._producers_by_field.setdefault(fname, []).append(name)

    def _find_producer(
        self,
        *,
        semantic: str,
        field_name: str,
        exclude: str,
    ) -> str | None:
        """Pick the first producer matching semantic, falling back to field name."""
        if semantic:
            for name in self._producers_by_semantic.get(semantic, []):
                if name != exclude:
                    return name
        if field_name:
            for name in self._producers_by_field.get(field_name, []):
                if name != exclude:
                    return name
        return None

    def _producer_jsonpath(
        self,
        producer: str,
        semantic: str,
        field_name: str,
    ) -> str:
        """Return a dotted path under the producer's response that yields
        the desired field. Converts ``$.a.b[*].c`` → ``a.b[0].c`` (v1 picks
        the first array element when a wildcard is present).

        Falls back to ``body`` + field_name if we can't locate the produces.
        """
        tool = self._tools.get(producer) or {}
        produces = (tool.get("metadata") or {}).get("produces") or []
        match = None
        if semantic:
            match = next(
                (p for p in produces if p.get("semantic_tag") == semantic),
                None,
            )
        if match is None and field_name:
            match = next(
                (p for p in produces if p.get("field_name") == field_name),
                None,
            )
        if match is None:
            return f"body.{field_name}" if field_name else "body"

        raw = match.get("json_path") or ""
        return _normalize_jsonpath_for_binding(raw)

    def _match_entity(
        self,
        entities: dict[str, Any],
        semantic: str,
        field_name: str,
    ) -> Any | None:
        """Look up user-supplied entity by semantic tag or field name."""
        if semantic and semantic in entities:
            return entities[semantic]
        if field_name and field_name in entities:
            return entities[field_name]
        return None

    def _rewrite_tool_refs(
        self,
        value: Any,
        steps_by_tool: dict[str, _PartialStep],
    ) -> Any:
        """Recursively rewrite ``${<tool_name>.<path>}`` → ``${sN.<path>}``."""
        if isinstance(value, dict):
            return {k: self._rewrite_tool_refs(v, steps_by_tool) for k, v in value.items()}
        if isinstance(value, list):
            return [self._rewrite_tool_refs(v, steps_by_tool) for v in value]
        if not isinstance(value, str):
            return value
        # Only rewrite full-string bindings that we inserted. Entities
        # supplied by the caller are left alone (no ${...} wrapping).
        if not (value.startswith("${") and value.endswith("}")):
            return value
        inner = value[2:-1]
        head, _, tail = inner.partition(".")
        if head in steps_by_tool:
            step_id = steps_by_tool[head].step_id
            rest = f".{tail}" if tail else ""
            return f"${{{step_id}{rest}}}"
        return value


def _normalize_jsonpath_for_binding(raw: str) -> str:
    """``$.body.goods[*].goodsNo`` → ``body.goods[0].goodsNo``.

    v1 always picks index 0 for arrays. Fan-out is v2 (design §11.1).
    """
    if not raw:
        return ""
    path = raw
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    return path.replace("[*]", "[0]")


__all__ = [
    "PathSynthesizer",
    "PlanSynthesisError",
    "UnsatisfiableFieldError",
    "CyclicDependencyError",
    "MaxDepthExceededError",
]
