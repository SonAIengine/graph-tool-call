"""PlanRunner — deterministic executor for Plan artifacts.

The runner is transport-agnostic: it takes a ``call_tool`` callable that
actually performs each step. This decouples ``graph_tool_call`` (pure
plan/graph logic) from integration concerns (HTTP, auth, retries —
handled by the caller's adapter).

The runner emits structured events as it progresses — callers can relay
these over SSE, logs, or progress UIs.

v1 scope reminder: **linear execution, no fan-out, no conditionals, no
automatic re-planning**. Failures abort the run and return a trace.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from graph_tool_call.plan.binding import BindingError, resolve_bindings
from graph_tool_call.plan.schema import (
    ExecutionTrace,
    Plan,
    StepTrace,
)

# ---------------------------------------------------------------------------
# Event types — structured so callers can pattern-match by ``type`` field
# ---------------------------------------------------------------------------


@dataclass
class PlanStarted:
    type: str = "plan.started"
    plan_id: str = ""
    goal: str = ""
    step_count: int = 0


@dataclass
class StepStarted:
    type: str = "step.started"
    step_id: str = ""
    tool: str = ""
    args_resolved: dict[str, Any] = field(default_factory=dict)
    index: int = 0
    total: int = 0


@dataclass
class StepCompleted:
    type: str = "step.completed"
    step_id: str = ""
    tool: str = ""
    duration_ms: int = 0
    output_preview: Any = None  # truncated output for UI
    output_size: int = 0


@dataclass
class StepFailed:
    type: str = "step.failed"
    step_id: str = ""
    tool: str = ""
    error: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class PlanCompleted:
    type: str = "plan.completed"
    plan_id: str = ""
    output: Any = None
    total_duration_ms: int = 0
    # 누적 step traces — 비-스트리밍 ``run()`` 이 ExecutionTrace.steps 채울 때 사용.
    trace_steps: list[StepTrace] = field(default_factory=list)


@dataclass
class PlanAborted:
    type: str = "plan.aborted"
    plan_id: str = ""
    failed_step: str = ""
    error: dict[str, Any] = field(default_factory=dict)
    total_duration_ms: int = 0
    trace_steps: list[StepTrace] = field(default_factory=list)


PlanEvent = PlanStarted | StepStarted | StepCompleted | StepFailed | PlanCompleted | PlanAborted


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


# ToolCaller signature: (tool_name, resolved_args) -> output_dict
ToolCaller = Callable[[str, dict[str, Any]], Any]


class PlanRunner:
    """Execute a Plan step-by-step using a caller-provided tool invoker.

    Usage::

        def call_tool(name: str, args: dict) -> dict:
            return my_http_executor.execute(name, args)

        runner = PlanRunner(call_tool)
        trace = runner.run(plan)                  # run to completion, return trace
        # or — streaming:
        for event in runner.run_stream(plan):
            send_over_sse(event)
    """

    def __init__(
        self,
        call_tool: ToolCaller,
        *,
        output_preview_limit: int = 512,
        on_error: str = "abort",  # 'abort' only in v1
    ) -> None:
        self._call_tool = call_tool
        self._preview_limit = output_preview_limit
        if on_error != "abort":
            raise ValueError("v1 PlanRunner only supports on_error='abort'")

    # ----------------------------------------------------------------------
    # Streaming interface — yields PlanEvent instances
    # ----------------------------------------------------------------------

    def run_stream(
        self,
        plan: Plan,
        *,
        input_context: dict[str, Any] | None = None,
    ) -> Iterator[PlanEvent]:
        """Execute *plan* and yield events as each step progresses.

        ``input_context`` supplies values for ``${input.xxx}`` and
        ``${user_input.xxx}`` bindings (both keys resolve to the same dict,
        kept as aliases because the synthesizer emits ``user_input`` for
        F2/Cycle-policy fallbacks and historical entity-injection paths use
        ``input``). Typically the entities extracted by Stage 1 (intent
        parser) plus any operator-supplied seed values.
        """
        plan_start = time.monotonic()

        yield PlanStarted(
            plan_id=plan.id,
            goal=plan.goal,
            step_count=len(plan.steps),
        )

        # step_id -> output (runtime context for binding resolution).
        # ``input`` and ``user_input`` are aliases — same dict, both names —
        # so binding ``${input.x}`` and ``${user_input.x}`` both resolve.
        context: dict[str, Any] = {}
        if input_context:
            input_dict = dict(input_context)
            context["input"] = input_dict
            context["user_input"] = input_dict

        trace_steps: list[StepTrace] = []

        for idx, step in enumerate(plan.steps, start=1):
            step_trace = StepTrace(id=step.id, tool=step.tool)
            step_start = time.monotonic()

            # 1. Resolve bindings
            try:
                resolved = resolve_bindings(step.args, context)
            except BindingError as exc:
                err = {
                    "kind": "binding",
                    "message": str(exc),
                }
                step_trace.error = err
                step_trace.duration_ms = _ms_since(step_start)
                trace_steps.append(step_trace)
                yield StepFailed(
                    step_id=step.id,
                    tool=step.tool,
                    error=err,
                    duration_ms=step_trace.duration_ms,
                )
                yield PlanAborted(
                    plan_id=plan.id,
                    failed_step=step.id,
                    error=err,
                    total_duration_ms=_ms_since(plan_start),
                    trace_steps=list(trace_steps),
                )
                return

            step_trace.args_resolved = resolved
            yield StepStarted(
                step_id=step.id,
                tool=step.tool,
                args_resolved=resolved,
                index=idx,
                total=len(plan.steps),
            )

            # 2. Execute via caller's tool invoker
            try:
                output = self._call_tool(step.tool, resolved)
            except Exception as exc:  # noqa: BLE001 — caller-defined
                err = {
                    "kind": "tool",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                }
                step_trace.error = err
                step_trace.duration_ms = _ms_since(step_start)
                trace_steps.append(step_trace)
                yield StepFailed(
                    step_id=step.id,
                    tool=step.tool,
                    error=err,
                    duration_ms=step_trace.duration_ms,
                )
                yield PlanAborted(
                    plan_id=plan.id,
                    failed_step=step.id,
                    error=err,
                    total_duration_ms=_ms_since(plan_start),
                    trace_steps=list(trace_steps),
                )
                return

            # 2a. Unwrap a single-level envelope when the response shape
            # diverges from the schema in the canonical "{code, message,
            # <wrapper>: {...}, timestamp}" pattern. One detect per step,
            # not per binding — every binding for this step then resolves
            # against the unwrapped dict naturally.
            output = _maybe_unwrap_envelope(output, step.response_root_keys)

            step_trace.output = output
            step_trace.duration_ms = _ms_since(step_start)
            trace_steps.append(step_trace)

            # 3. Store output in context for later bindings
            context[step.id] = output

            yield StepCompleted(
                step_id=step.id,
                tool=step.tool,
                duration_ms=step_trace.duration_ms,
                output_preview=_preview(output, self._preview_limit),
                output_size=_output_size(output),
            )

        # 4. Resolve output_binding for final answer
        try:
            final = (
                resolve_bindings(plan.output_binding, context)
                if plan.output_binding
                else (context[plan.steps[-1].id] if plan.steps else None)
            )
        except BindingError as exc:
            err = {"kind": "output_binding", "message": str(exc)}
            yield PlanAborted(
                plan_id=plan.id,
                failed_step="<output_binding>",
                error=err,
                total_duration_ms=_ms_since(plan_start),
                trace_steps=list(trace_steps),
            )
            return

        yield PlanCompleted(
            plan_id=plan.id,
            output=final,
            total_duration_ms=_ms_since(plan_start),
            trace_steps=list(trace_steps),
        )

    # ----------------------------------------------------------------------
    # Non-streaming interface — returns final ExecutionTrace
    # ----------------------------------------------------------------------

    def run(
        self,
        plan: Plan,
        *,
        input_context: dict[str, Any] | None = None,
    ) -> ExecutionTrace:
        """Execute *plan* and return an ExecutionTrace aggregating events.

        ``trace_steps`` 는 종결 이벤트 (``PlanCompleted`` / ``PlanAborted``) 가
        실어 보내는 것을 그대로 사용 — run_stream 안에서 step 단위로 누적된
        StepTrace 가 그대로 ExecutionTrace.steps 에 들어간다.
        """
        started_at = _now_iso()
        started = time.monotonic()
        trace_steps: list[StepTrace] = []
        success = False
        failed_step: str | None = None
        output: Any = None

        for event in self.run_stream(plan, input_context=input_context):
            etype = event.type
            if etype == "plan.completed":
                success = True
                output = event.output  # type: ignore[union-attr]
                trace_steps = list(event.trace_steps)  # type: ignore[union-attr]
            elif etype == "plan.aborted":
                failed_step = event.failed_step  # type: ignore[union-attr]
                trace_steps = list(event.trace_steps)  # type: ignore[union-attr]

        return ExecutionTrace(
            plan_id=plan.id,
            success=success,
            steps=trace_steps,
            output=output,
            failed_step=failed_step,
            total_duration_ms=_ms_since(started),
            started_at=started_at,
            ended_at=_now_iso(),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ms_since(start_monotonic: float) -> int:
    return int((time.monotonic() - start_monotonic) * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(value: Any, limit: int) -> Any:
    """Trim large outputs for UI previews. Keep small values intact."""
    if isinstance(value, (dict, list)):
        import json as _json

        try:
            rendered = _json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return {"_preview": f"<unserializable {type(value).__name__}>"}
        if len(rendered) <= limit:
            return value
        return {"_preview": rendered[:limit] + "…", "_truncated": True}
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def _maybe_unwrap_envelope(
    output: Any,
    expected_root_keys: list[str],
) -> Any:
    """Peel one envelope layer when the response shape diverges from schema.

    Conservative — unwraps only when ALL of these hold:

      1. ``output`` is a dict with two or more root keys
         (a bare ``{"payload": ...}`` is more likely real data than envelope).
      2. Exactly one root value is itself a dict — the wrapper candidate.
      3. Every other root value is scalar / null
         (envelope siblings are status/code/message/timestamp — not
         business collections).
      4. None of ``expected_root_keys`` appears at the response root
         (otherwise the response is already in schema-shape).
      5. At least one ``expected_root_keys`` entry appears inside the
         wrapper candidate (otherwise the dict-typed sibling is unrelated
         business data — unwrapping would lose information).

    The wrapper *key name* is never inspected, so this works for
    ``payload`` / ``data`` / ``result`` / any other convention. Without
    ``expected_root_keys`` there's no schema signal to validate against,
    so the output passes through unchanged.
    """
    if not expected_root_keys or not isinstance(output, dict) or len(output) < 2:
        return output

    dict_keys = [k for k, v in output.items() if isinstance(v, dict)]
    if len(dict_keys) != 1:
        return output

    wrapper_key = dict_keys[0]
    for k, v in output.items():
        if k == wrapper_key:
            continue
        if isinstance(v, (dict, list)):
            return output

    expected = set(expected_root_keys)
    if expected & set(output.keys()):
        return output

    wrapper = output[wrapper_key]
    if not (expected & set(wrapper.keys())):
        return output

    return wrapper


def _output_size(value: Any) -> int:
    """Approximate serialized byte size (for observability)."""
    import json as _json

    try:
        return len(_json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return 0
