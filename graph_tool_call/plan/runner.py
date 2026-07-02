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
from graph_tool_call.plan.deps import is_output_consumed
from graph_tool_call.plan.repair import PlanRepairer
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


# --- recovery events (additive; only emitted in retry/recover modes) --------


@dataclass
class StepRetrying:
    """A step's tool call failed and is about to be retried after a backoff."""

    type: str = "step.retrying"
    step_id: str = ""
    tool: str = ""
    attempt: int = 0  # 1-based index of the retry about to run
    max_attempts: int = 0
    delay_ms: int = 0
    error: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepSkipped:
    """A failed step whose output nothing downstream consumes — safely skipped."""

    type: str = "step.skipped"
    step_id: str = ""
    tool: str = ""
    reason: str = ""
    error: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanRepaired:
    """The plan was re-synthesized around a failed step (execution continues)."""

    type: str = "plan.repaired"
    old_plan_id: str = ""
    new_plan_id: str = ""
    failed_step: str = ""
    excluded_tools: list[str] = field(default_factory=list)
    step_count: int = 0


PlanEvent = (
    PlanStarted
    | StepStarted
    | StepCompleted
    | StepFailed
    | PlanCompleted
    | PlanAborted
    | StepRetrying
    | StepSkipped
    | PlanRepaired
)


@dataclass
class RetryPolicy:
    """Retry configuration consumed by :class:`PlanRunner`.

    A step is retried only when the runner's ``on_error`` is ``retry`` /
    ``recover`` **and** the step opts in (``PlanStep.retryable``) or
    ``retry_all`` is set. Only ``kind='tool'`` failures retry — binding
    errors are deterministic and never retried. Backoff for the *n*-th retry
    (1-based) is ``backoff_base_ms * backoff_factor**(n-1)`` milliseconds.
    """

    max_attempts: int = 2  # total tries incl. the first (so 2 ⇒ 1 retry)
    backoff_base_ms: int = 200
    backoff_factor: float = 2.0
    retry_all: bool = False


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
        on_error: str = "abort",
        retry_policy: RetryPolicy | None = None,
        repairer: PlanRepairer | None = None,
        _sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._call_tool = call_tool
        self._preview_limit = output_preview_limit
        if on_error not in ("abort", "retry", "recover"):
            raise ValueError("PlanRunner on_error must be 'abort', 'retry', or 'recover'")
        # Recovery config. All default to the v1 behaviour: ``on_error='abort'``
        # with no policy/repairer means the executor is byte-for-byte identical
        # to the pre-recovery runner — failures abort immediately.
        self._on_error = on_error
        self._retry_policy = retry_policy
        self._repairer = repairer
        # Injectable sleep so tests can run backoff logic without wall-clock
        # delay; production uses ``time.sleep``.
        self._sleep = _sleep

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
        base_input: dict[str, Any] = dict(input_context) if input_context else {}
        context: dict[str, Any] = {}
        if base_input:
            input_dict = dict(base_input)
            context["input"] = input_dict
            context["user_input"] = input_dict

        trace_steps: list[StepTrace] = []
        repairs_done = 0
        excluded_tools: set[str] = set()

        # While-loop (not for-each) because ``recover`` mode can swap ``plan``
        # for a repaired one mid-run and restart the index. In ``abort`` mode
        # the flow degenerates to the original linear pass.
        idx = 0
        while idx < len(plan.steps):
            step = plan.steps[idx]
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
                index=idx + 1,
                total=len(plan.steps),
            )

            # 2. Execute via caller's tool invoker, with optional retry.
            output: Any = None
            err: dict[str, Any] | None = None
            attempts = 0
            max_attempts = self._max_attempts_for(step)
            while True:
                attempts += 1
                try:
                    output = self._call_tool(step.tool, resolved)
                    err = None
                    break
                except Exception as exc:  # noqa: BLE001 — caller-defined
                    err = {
                        "kind": "tool",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    }
                    if attempts < max_attempts:
                        delay_ms = self._backoff_ms(attempts)
                        yield StepRetrying(
                            step_id=step.id,
                            tool=step.tool,
                            attempt=attempts,
                            max_attempts=max_attempts,
                            delay_ms=delay_ms,
                            error=err,
                        )
                        if delay_ms > 0:
                            self._sleep(delay_ms / 1000.0)
                        continue
                    break
            step_trace.retries = attempts - 1

            if err is not None:
                step_trace.error = err
                step_trace.duration_ms = _ms_since(step_start)

                # ---- recovery cascade (only in 'recover' mode) ----
                if self._on_error == "recover":
                    # (a) Safe skip — nothing downstream (nor the final output
                    #     binding) consumes this step's result.
                    if not is_output_consumed(plan, step.id, idx):
                        trace_steps.append(step_trace)
                        yield StepSkipped(
                            step_id=step.id,
                            tool=step.tool,
                            reason="output not consumed by later steps",
                            error=err,
                        )
                        idx += 1
                        continue

                    # (b) Replan — swap the failed producer, reuse completed
                    #     outputs as entities, continue on the new plan.
                    if self._repairer is not None and repairs_done < self._repairer.max_repairs:
                        completed_outputs = {
                            s.id: context[s.id] for s in plan.steps[:idx] if s.id in context
                        }
                        repair_result = self._repairer.repair(
                            plan,
                            step.id,
                            err,
                            completed_outputs,
                            already_excluded=excluded_tools,
                        )
                        if repair_result is not None:
                            trace_steps.append(step_trace)  # record the trigger
                            repairs_done += 1
                            excluded_tools = set(repair_result.excluded_tools)
                            new_plan = repair_result.plan
                            yield PlanRepaired(
                                old_plan_id=plan.id,
                                new_plan_id=new_plan.id,
                                failed_step=step.id,
                                excluded_tools=sorted(excluded_tools),
                                step_count=len(new_plan.steps),
                            )
                            # Re-seed context for the new plan. Its already-
                            # satisfied producers are baked in as entities;
                            # expose them (plus the original operator input) so
                            # ${input.x}/${user_input.x} bindings still resolve.
                            merged_input = dict(base_input)
                            merged_input.update(new_plan.metadata.get("entities") or {})
                            context = {}
                            input_dict = dict(merged_input)
                            context["input"] = input_dict
                            context["user_input"] = input_dict
                            plan = new_plan
                            idx = 0
                            continue

                # abort (abort/retry modes, or recover exhausted)
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
            idx += 1

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
    # retry helpers
    # ----------------------------------------------------------------------

    def _max_attempts_for(self, step: Any) -> int:
        """Total attempts (incl. first) allowed for *step*.

        Returns 1 (no retry) unless the runner is in ``retry`` / ``recover``
        mode, a ``RetryPolicy`` is configured, and the step opts in
        (``retryable`` or the policy's ``retry_all``).
        """
        if self._on_error not in ("retry", "recover") or self._retry_policy is None:
            return 1
        if not (getattr(step, "retryable", False) or self._retry_policy.retry_all):
            return 1
        return max(1, self._retry_policy.max_attempts)

    def _backoff_ms(self, attempt: int) -> int:
        """Backoff before the *attempt*-th retry (1-based)."""
        policy = self._retry_policy
        if policy is None:
            return 0
        return int(policy.backoff_base_ms * (policy.backoff_factor ** (attempt - 1)))

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
