"""Unit tests for ``graph_tool_call.plan.runner``.

리뷰 CRITICAL #1, #2 회귀 방지 + 핵심 동작 cover.
"""
from __future__ import annotations

from typing import Any

import pytest

from graph_tool_call.plan import (
    Plan,
    PlanRunner,
    PlanStep,
)
from graph_tool_call.plan.runner import (
    PlanAborted,
    PlanCompleted,
)


def _echo(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"echoed": args, "tool": name}


# ─── CRITICAL #1: input_context 가 ${user_input.x} / ${input.x} 둘 다 resolve ──


def test_user_input_alias_resolves():
    """``${user_input.foo}`` 가 input_context["foo"] 로 resolve 되어야 한다.

    이전엔 synthesizer 가 ${user_input.x} 만들고 runner 가 context["input"] 에만
    심어서 첫 step 부터 BindingError 로 abort 됐던 케이스.
    """
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="echo", args={"foo": "${user_input.foo}"}),
        ],
        output_binding="${s1}",
    )
    trace = PlanRunner(_echo).run(plan, input_context={"foo": "BAR"})
    assert trace.success, f"plan should succeed, got: {trace.failed_step}"
    assert trace.steps[0].args_resolved == {"foo": "BAR"}


def test_input_alias_resolves_too():
    """``${input.foo}`` 도 동일 dict 가리켜야 한다 (backward compat)."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="echo", args={"foo": "${input.foo}"}),
        ],
        output_binding="${s1}",
    )
    trace = PlanRunner(_echo).run(plan, input_context={"foo": "BAR"})
    assert trace.success
    assert trace.steps[0].args_resolved == {"foo": "BAR"}


def test_mixed_input_user_input_in_same_step():
    """한 step 에 ${input.x} 와 ${user_input.y} 가 섞여 있어도 둘 다 resolve."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(
                id="s1",
                tool="echo",
                args={"a": "${input.x}", "b": "${user_input.y}"},
            ),
        ],
    )
    trace = PlanRunner(_echo).run(plan, input_context={"x": "X", "y": "Y"})
    assert trace.success
    assert trace.steps[0].args_resolved == {"a": "X", "b": "Y"}


# ─── CRITICAL #2: ExecutionTrace.steps 가 누적 ──


def test_execution_trace_accumulates_steps():
    """run() 의 ExecutionTrace.steps 가 빈 리스트가 아니어야 한다.

    이전엔 runner.py:289 의 pass 때문에 항상 [] 였던 케이스.
    """
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="echo", args={"x": "hello"}),
            PlanStep(id="s2", tool="echo", args={"y": "${s1.echoed.x}"}),
        ],
        output_binding="${s2}",
    )
    trace = PlanRunner(_echo).run(plan)
    assert trace.success
    assert len(trace.steps) == 2, "두 step 모두 trace 에 누적돼야 함"
    assert trace.steps[0].id == "s1"
    assert trace.steps[1].id == "s2"
    assert trace.steps[0].output == {"echoed": {"x": "hello"}, "tool": "echo"}
    assert trace.steps[1].args_resolved == {"y": "hello"}, "이전 step 출력 binding"


def test_execution_trace_includes_failed_step():
    """실패해도 실패한 step + 그 이전 step 이 trace 에 포함."""
    def flaky(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "boom":
            raise RuntimeError("simulated")
        return {"ok": True}

    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="ok"),
            PlanStep(id="s2", tool="boom"),
            PlanStep(id="s3", tool="never_called"),
        ],
    )
    trace = PlanRunner(flaky).run(plan)
    assert trace.success is False
    assert trace.failed_step == "s2"
    assert len(trace.steps) == 2, "실패까지의 step 만 누적 (s3 는 도달 안 함)"
    assert trace.steps[0].id == "s1"
    assert trace.steps[0].error is None
    assert trace.steps[1].id == "s2"
    assert trace.steps[1].error is not None
    assert "simulated" in trace.steps[1].error["message"]


# ─── 일반 동작 ──


def test_run_stream_yields_expected_events_in_order():
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="echo", args={"x": "hi"})],
    )
    events = list(PlanRunner(_echo).run_stream(plan))
    types = [e.type for e in events]
    assert types[0] == "plan.started"
    assert types[-1] == "plan.completed"
    assert "step.started" in types
    assert "step.completed" in types


def test_plan_completed_carries_trace_steps():
    """run_stream 의 PlanCompleted 가 trace_steps 를 실어 보내야 run() 이 읽을 수 있음."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="echo", args={"x": "hi"})],
    )
    completed = next(
        e for e in PlanRunner(_echo).run_stream(plan)
        if isinstance(e, PlanCompleted)
    )
    assert len(completed.trace_steps) == 1
    assert completed.trace_steps[0].id == "s1"


def test_plan_aborted_carries_trace_steps():
    """abort 시에도 PlanAborted 가 그때까지의 trace_steps 를 실어 보내야 함."""
    def fail(name: str, args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")

    plan = Plan(id="t", goal="g", steps=[PlanStep(id="s1", tool="x")])
    aborted = next(
        e for e in PlanRunner(fail).run_stream(plan)
        if isinstance(e, PlanAborted)
    )
    assert len(aborted.trace_steps) == 1
    assert aborted.trace_steps[0].error is not None


def test_binding_to_unknown_source_aborts():
    """존재하지 않는 step id 참조 → BindingError → abort."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="echo", args={"x": "${ghost.foo}"})],
    )
    trace = PlanRunner(_echo).run(plan)
    assert trace.success is False
    assert trace.failed_step == "s1"
    assert trace.steps[0].error["kind"] == "binding"


def test_output_binding_resolves_nested_path():
    """output_binding 이 step 응답 안의 nested path 를 가리킬 수 있어야."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="echo", args={"v": 42})],
        output_binding="${s1.echoed.v}",
    )
    trace = PlanRunner(_echo).run(plan)
    assert trace.success
    assert trace.output == 42


def test_no_input_context_works_when_plan_has_no_input_binding():
    """input_context 안 줘도 ${input.x} 안 쓰면 동작."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="echo", args={"x": "literal"})],
    )
    trace = PlanRunner(_echo).run(plan)
    assert trace.success


def test_v1_only_supports_abort_on_error():
    """v1 PlanRunner 는 on_error='abort' 만 허용 — 다른 값은 ValueError."""
    with pytest.raises(ValueError):
        PlanRunner(_echo, on_error="continue")
