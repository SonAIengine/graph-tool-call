"""Unit tests for the A-P0-1 failure-recovery loop.

Covers retry (transient fault) → skip (unconsumed output) → replan (swap a
failed producer) and asserts the default ``on_error='abort'`` path stays
byte-for-byte identical (no recovery events emitted).
"""

from __future__ import annotations

from typing import Any

from graph_tool_call.plan import (
    Plan,
    PlanRepaired,
    PlanRepairer,
    PlanRunner,
    PlanStep,
    RetryPolicy,
    StepRetrying,
    StepSkipped,
)
from graph_tool_call.plan.deps import compute_step_deps, is_output_consumed
from graph_tool_call.plan.synthesizer import PathSynthesizer

# ---------------------------------------------------------------------------
# fault-injection tool caller
# ---------------------------------------------------------------------------


def make_caller(
    outputs: dict[str, Any] | None = None,
    *,
    fail_perm: set[str] | None = None,
    fail_times: dict[str, int] | None = None,
):
    """Build a ``call_tool`` that records calls and injects faults.

    ``fail_perm`` tools always raise. ``fail_times`` tools raise the given
    number of times then succeed (models a flaky/transient endpoint).
    """
    outputs = outputs or {}
    fail_perm = set(fail_perm or set())
    remaining = dict(fail_times or {})
    calls: list[tuple[str, dict]] = []

    def call(name: str, args: dict[str, Any]) -> Any:
        calls.append((name, dict(args)))
        if name in fail_perm:
            raise RuntimeError(f"{name} permanent failure")
        if remaining.get(name, 0) > 0:
            remaining[name] -= 1
            raise RuntimeError(f"{name} transient failure")
        return outputs.get(name, {"ok": name, "echoed": args})

    call.calls = calls  # type: ignore[attr-defined]
    return call


def _no_sleep(_seconds: float) -> None:
    return None


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------


def test_retry_recovers_transient_failure():
    """retry_all=True → a step that fails twice then succeeds should complete."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="flaky", args={"x": 1})],
        output_binding="${s1}",
    )
    caller = make_caller({"flaky": {"ok": True}}, fail_times={"flaky": 2})
    runner = PlanRunner(
        caller,
        on_error="retry",
        retry_policy=RetryPolicy(max_attempts=3, retry_all=True, backoff_base_ms=1),
        _sleep=_no_sleep,
    )
    trace = runner.run(plan)
    assert trace.success, trace.failed_step
    assert trace.steps[0].retries == 2, "두 번 재시도 후 성공"
    assert len(caller.calls) == 3  # type: ignore[attr-defined]


def test_retry_respects_max_attempts_then_aborts():
    """max_attempts 소진 후에도 실패하면 abort."""
    plan = Plan(id="t", goal="g", steps=[PlanStep(id="s1", tool="boom")])
    caller = make_caller(fail_perm={"boom"})
    runner = PlanRunner(
        caller,
        on_error="retry",
        retry_policy=RetryPolicy(max_attempts=2, retry_all=True, backoff_base_ms=1),
        _sleep=_no_sleep,
    )
    trace = runner.run(plan)
    assert trace.success is False
    assert trace.failed_step == "s1"
    assert trace.steps[0].retries == 1  # 1 retry (2 attempts total)
    assert len(caller.calls) == 2  # type: ignore[attr-defined]


def test_retry_only_for_opted_in_step():
    """retry_all=False → step.retryable=False 는 재시도 안 함."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="flaky", retryable=False)],
    )
    caller = make_caller(fail_times={"flaky": 1})
    runner = PlanRunner(
        caller,
        on_error="retry",
        retry_policy=RetryPolicy(max_attempts=3, retry_all=False, backoff_base_ms=1),
        _sleep=_no_sleep,
    )
    trace = runner.run(plan)
    assert trace.success is False, "retryable=False 이므로 재시도 없이 abort"
    assert len(caller.calls) == 1  # type: ignore[attr-defined]


def test_retry_opt_in_via_step_retryable():
    """retry_all=False 여도 step.retryable=True 면 재시도."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="flaky", retryable=True)],
        output_binding="${s1}",
    )
    caller = make_caller({"flaky": {"ok": True}}, fail_times={"flaky": 1})
    runner = PlanRunner(
        caller,
        on_error="retry",
        retry_policy=RetryPolicy(max_attempts=3, retry_all=False, backoff_base_ms=1),
        _sleep=_no_sleep,
    )
    trace = runner.run(plan)
    assert trace.success, "retryable=True → 재시도 후 성공"
    assert trace.steps[0].retries == 1
    assert len(caller.calls) == 2  # type: ignore[attr-defined]


def test_retry_emits_step_retrying_events_with_backoff():
    plan = Plan(id="t", goal="g", steps=[PlanStep(id="s1", tool="flaky")])
    caller = make_caller({"flaky": {"ok": 1}}, fail_times={"flaky": 2})
    slept: list[float] = []
    runner = PlanRunner(
        caller,
        on_error="retry",
        retry_policy=RetryPolicy(
            max_attempts=3, retry_all=True, backoff_base_ms=100, backoff_factor=2.0
        ),
        _sleep=slept.append,
    )
    events = list(runner.run_stream(plan))
    retrying = [e for e in events if isinstance(e, StepRetrying)]
    assert len(retrying) == 2
    assert retrying[0].delay_ms == 100
    assert retrying[1].delay_ms == 200, "지수 백오프"
    assert slept == [0.1, 0.2], "주입된 sleep 이 초 단위로 호출됨"


# ---------------------------------------------------------------------------
# skip
# ---------------------------------------------------------------------------


def test_recover_skips_step_whose_output_is_unconsumed():
    """recover 모드: 실패 step 의 출력을 아무도 안 쓰면 건너뛰고 완주."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="ok"),
            PlanStep(id="s2", tool="optional_side"),  # nobody binds s2
            PlanStep(id="s3", tool="final", args={"a": "${s1.ok}"}),
        ],
        output_binding="${s3}",
    )
    caller = make_caller(
        {"ok": {"ok": "A"}, "final": {"done": True}},
        fail_perm={"optional_side"},
    )
    runner = PlanRunner(caller, on_error="recover")
    events = list(runner.run_stream(plan))
    skipped = [e for e in events if isinstance(e, StepSkipped)]
    assert len(skipped) == 1
    assert skipped[0].step_id == "s2"
    completed = events[-1]
    assert completed.type == "plan.completed"


def test_recover_terminal_step_skipped_aborts_cleanly_without_output_binding():
    """recover 모드에서 종료 step 이 safe-skip 되고 output_binding 도 없으면
    context[last]=KeyError 로 crash 하지 말고 깔끔한 plan.aborted 로 종료해야 한다.

    (XGEN force_target 단일 step chip-click 이 도구 실패 시 KeyError 로 죽던 회귀 방지.)
    """
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="only")],  # 단일 step, output_binding 없음
    )
    caller = make_caller({}, fail_perm={"only"})
    runner = PlanRunner(caller, on_error="recover")  # repairer 없음 → skip 시도
    events = list(runner.run_stream(plan))  # KeyError 안 나야
    assert [e for e in events if isinstance(e, StepSkipped)], "종료 step 이 safe-skip 됨"
    assert events[-1].type == "plan.aborted"
    assert events[-1].failed_step == "<output_binding>"


def test_recover_does_not_skip_consumed_output_without_repairer():
    """출력이 소비되면 skip 불가 — repairer 없으면 abort."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="producer"),
            PlanStep(id="s2", tool="consumer", args={"v": "${s1.val}"}),
        ],
        output_binding="${s2}",
    )
    caller = make_caller(fail_perm={"producer"})
    runner = PlanRunner(caller, on_error="recover")  # no repairer
    trace = runner.run(plan)
    assert trace.success is False
    assert trace.failed_step == "s1"


# ---------------------------------------------------------------------------
# replan
# ---------------------------------------------------------------------------


def _two_producer_graph() -> dict:
    """target 'combine' 은 'aId' 필요. producerV1/producerV2 둘 다 aId 생산."""

    def mk_producer() -> dict:
        return {
            "metadata": {
                "method": "GET",
                "path": "/p",
                "consumes": [{"field_name": "seed", "kind": "data", "required": True}],
                "produces": [
                    {"field_name": "aId", "json_path": "$.body.aId", "semantic_tag": "a.id"}
                ],
                "ai_metadata": {"canonical_action": "search", "primary_resource": "a"},
            }
        }

    return {
        "tools": {
            "producerV1": mk_producer(),
            "producerV2": mk_producer(),
            "combine": {
                "metadata": {
                    "method": "GET",
                    "path": "/combine",
                    "consumes": [
                        {
                            "field_name": "aId",
                            "semantic_tag": "a.id",
                            "kind": "data",
                            "required": True,
                        }
                    ],
                    "produces": [{"field_name": "result", "json_path": "$.body.result"}],
                    "ai_metadata": {"canonical_action": "read", "primary_resource": "a"},
                }
            },
        }
    }


def test_replan_swaps_failed_producer():
    """producerV1 이 죽으면 repairer 가 producerV2 로 우회해 완주."""
    graph = _two_producer_graph()
    syn = PathSynthesizer(graph)
    plan = syn.synthesize(target="combine", entities={"seed": "kw"})
    # 초기 계획은 첫 producer 를 사용
    first_producer = plan.steps[0].tool
    assert first_producer in ("producerV1", "producerV2")
    alt = "producerV2" if first_producer == "producerV1" else "producerV1"

    caller = make_caller(
        {
            "producerV1": {"body": {"aId": "V1"}},
            "producerV2": {"body": {"aId": "V2"}},
            "combine": {"body": {"result": "OK"}},
        },
        fail_perm={first_producer},
    )
    repairer = PlanRepairer(syn, max_repairs=2)
    runner = PlanRunner(caller, on_error="recover", repairer=repairer)
    events = list(runner.run_stream(plan))
    repaired = [e for e in events if isinstance(e, PlanRepaired)]
    assert len(repaired) == 1
    assert first_producer in repaired[0].excluded_tools
    completed = events[-1]
    assert completed.type == "plan.completed"
    # 우회 producer 가 실제로 호출되고, combine 이 그 결과를 받았는지
    called_tools = [c[0] for c in caller.calls]  # type: ignore[attr-defined]
    assert alt in called_tools
    assert "combine" in called_tools


def test_replan_declines_when_target_itself_fails():
    """target(combine) 자체가 실패하면 repair 불가 → abort."""
    graph = _two_producer_graph()
    syn = PathSynthesizer(graph)
    plan = syn.synthesize(target="combine", entities={"aId": "given"})  # 1-step plan
    assert len(plan.steps) == 1 and plan.steps[0].tool == "combine"
    caller = make_caller(fail_perm={"combine"})
    repairer = PlanRepairer(syn)
    runner = PlanRunner(caller, on_error="recover", repairer=repairer)
    trace = runner.run(plan)
    assert trace.success is False
    assert trace.failed_step == "s1"


# ---------------------------------------------------------------------------
# backward compat — abort mode byte-identical
# ---------------------------------------------------------------------------


def test_abort_mode_emits_no_recovery_events():
    """기본 on_error='abort' 는 복구 이벤트를 전혀 안 냄 (v1 동작 보존)."""
    plan = Plan(id="t", goal="g", steps=[PlanStep(id="s1", tool="boom")])
    caller = make_caller(fail_perm={"boom"})
    events = list(PlanRunner(caller).run_stream(plan))
    types = [e.type for e in events]
    assert "step.retrying" not in types
    assert "step.skipped" not in types
    assert "plan.repaired" not in types
    assert types == ["plan.started", "step.started", "step.failed", "plan.aborted"]
    assert len(caller.calls) == 1, "abort 모드는 재시도 없음"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# deps
# ---------------------------------------------------------------------------


def test_compute_step_deps_maps_bindings_to_step_ids():
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="a", args={"k": "${input.kw}"}),
            PlanStep(id="s2", tool="b", args={"v": "${s1.body.id}"}),
            PlanStep(id="s3", tool="c", args={"x": "${s1.a}", "y": "${s2.b}"}),
        ],
    )
    deps = compute_step_deps(plan)
    assert deps["s1"] == set()  # input.* 는 스텝 의존 아님
    assert deps["s2"] == {"s1"}
    assert deps["s3"] == {"s1", "s2"}


def test_is_output_consumed_detects_downstream_and_output_binding():
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="a"),
            PlanStep(id="s2", tool="b", args={"v": "${s1.id}"}),
            PlanStep(id="s3", tool="c"),
        ],
        output_binding="${s3}",
    )
    assert is_output_consumed(plan, "s1", 0) is True  # s2 가 소비
    assert is_output_consumed(plan, "s2", 1) is False  # 아무도 s2 안 씀
    assert is_output_consumed(plan, "s3", 2) is True  # output_binding 이 가리킴


def test_synthesizer_populates_depends_on():
    """합성된 plan 의 step 이 depends_on 을 채워야 (linear 시맨틱은 불변)."""
    graph = _two_producer_graph()
    syn = PathSynthesizer(graph)
    plan = syn.synthesize(target="combine", entities={"seed": "kw"})
    assert len(plan.steps) == 2
    producer_step, combine_step = plan.steps
    assert producer_step.depends_on == []  # 첫 스텝은 의존 없음
    assert combine_step.depends_on == [producer_step.id]
