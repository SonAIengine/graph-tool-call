"""PlanRepairer — re-synthesize a plan around a failed step.

When a step fails and its output is needed downstream (so it can't just be
skipped), the runner asks the repairer for an alternative. The strategy is
deliberately simple and reuses the synthesizer wholesale:

  1. Recover the original ``target`` + ``entities`` from ``Plan.metadata``
     (the synthesizer records both).
  2. Fold every *completed* step's result back in as entities — each output is
     run through :func:`extract_produced_entities` against that tool's
     ``produces`` schema, keyed by both ``semantic_tag`` and ``field_name``.
     A re-synthesis then sees those values as already-available and won't
     re-chain the producers that already ran.
  3. Re-synthesize the same target with ``exclude_tools`` naming the failed
     tool (and any previously excluded ones), so the synthesizer reroutes
     through a different producer — or, if none remains, surfaces a
     ``${user_input.x}`` slot instead of the failed tool.

Repairing the *target itself* is declined (returns ``None``): the target is
what the user asked for, not a swappable prerequisite. Synthesis failures
also return ``None`` — the runner then aborts as usual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graph_tool_call.plan.extraction import extract_produced_entities
from graph_tool_call.plan.schema import Plan
from graph_tool_call.plan.synthesizer import PathSynthesizer, PlanSynthesisError

__all__ = ["RepairResult", "PlanRepairer"]


@dataclass
class RepairResult:
    """Outcome of a successful repair.

    ``plan`` is the freshly synthesized replacement. ``reused_outputs`` maps
    the *old* plan's completed step ids to their raw outputs (kept for audit /
    context re-seeding). ``excluded_tools`` is the cumulative set of tools the
    synthesis avoided (failed tool + any carried over from earlier repairs).
    """

    plan: Plan
    reused_outputs: dict[str, Any] = field(default_factory=dict)
    excluded_tools: set[str] = field(default_factory=set)


class PlanRepairer:
    """Produce an alternative :class:`Plan` when a step fails mid-run."""

    def __init__(self, synthesizer: PathSynthesizer, *, max_repairs: int = 2) -> None:
        self._syn = synthesizer
        self.max_repairs = max_repairs

    def repair(
        self,
        plan: Plan,
        failed_step_id: str,
        error: Any,
        completed_outputs: dict[str, Any],
        *,
        already_excluded: set[str] | None = None,
    ) -> RepairResult | None:
        """Attempt to re-synthesize *plan* around the failed step.

        Returns a :class:`RepairResult` on success, or ``None`` when repair is
        impossible (missing metadata, the target itself failed, or the
        synthesizer can't build an alternative). ``error`` is accepted for
        interface completeness / future error-aware routing; the current
        strategy re-synthesizes regardless of the failure kind.
        """
        failed_step = next((s for s in plan.steps if s.id == failed_step_id), None)
        if failed_step is None:
            return None
        failed_tool = failed_step.tool

        metadata = plan.metadata or {}
        target = metadata.get("target")
        if not target:
            return None
        # The target is the user's goal, not a swappable prerequisite.
        if failed_tool == target:
            return None

        # Start from the original entities, fold in completed step results.
        augmented: dict[str, Any] = dict(metadata.get("entities") or {})
        reused_outputs: dict[str, Any] = {}
        for step in plan.steps:
            out = completed_outputs.get(step.id)
            if out is None:
                continue
            reused_outputs[step.id] = out
            produced = extract_produced_entities(self._tool_meta(step.tool), out)
            for key, val in produced.items():
                # User-supplied / earlier entities win — never clobber them.
                augmented.setdefault(key, val)

        excluded: set[str] = set(already_excluded or set())
        excluded.add(failed_tool)

        try:
            new_plan = self._syn.synthesize(
                target=target,
                entities=augmented,
                goal=plan.goal,
                exclude_tools=excluded,
            )
        except PlanSynthesisError:
            return None

        return RepairResult(
            plan=new_plan,
            reused_outputs=reused_outputs,
            excluded_tools=excluded,
        )

    # ------------------------------------------------------------------

    def _tool_meta(self, tool_name: str) -> dict[str, Any]:
        """Return a tool's ``metadata`` block from the synthesizer's graph."""
        tool = (self._syn._tools or {}).get(tool_name) or {}
        return tool.get("metadata") or {}
