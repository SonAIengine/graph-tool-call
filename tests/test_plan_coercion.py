"""Unit tests for A-P0-2 parameter strengthening.

coerce_args (type cast + fuzzy enum) and the runner's opt-in
``validate_args='coerce'`` / ``binding_recovery`` hooks. All default-off, so a
plain runner stays unchanged.
"""

from __future__ import annotations

from typing import Any

from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.plan import (
    ArgsCoerced,
    BindingRepaired,
    CoercionReport,
    Plan,
    PlanRunner,
    PlanStep,
    coerce_args,
)


def _tool(name: str, params: list[ToolParameter]) -> ToolSchema:
    return ToolSchema(name=name, parameters=params)


# ---------------------------------------------------------------------------
# coerce_args
# ---------------------------------------------------------------------------


def test_coerce_casts_string_to_int_and_bool():
    tool = _tool(
        "t",
        [
            ToolParameter(name="page", type="integer"),
            ToolParameter(name="active", type="boolean"),
            ToolParameter(name="ratio", type="number"),
        ],
    )
    report = coerce_args(tool, {"page": "3", "active": "true", "ratio": "1.5"})
    assert isinstance(report, CoercionReport)
    assert report.corrected == {"page": 3, "active": True, "ratio": 1.5}
    rules = {c["field"]: c["rule"] for c in report.changes}
    assert rules == {"page": "cast", "active": "cast", "ratio": "cast"}


def test_coerce_leaves_correct_types_and_unknown_params():
    tool = _tool("t", [ToolParameter(name="n", type="integer")])
    report = coerce_args(tool, {"n": 5, "extra": "keep"})
    assert report.corrected == {"n": 5, "extra": "keep"}
    assert report.changes == []


def test_coerce_does_not_cast_real_bool_to_int():
    tool = _tool("t", [ToolParameter(name="flag", type="integer")])
    report = coerce_args(tool, {"flag": True})
    assert report.corrected == {"flag": True}, "bool 은 int 로 재캐스트하지 않음"
    assert report.changes == []


def test_coerce_fuzzy_enum_folds_case_and_separators():
    tool = _tool(
        "t",
        [ToolParameter(name="status", type="string", enum=["in_progress", "done"])],
    )
    report = coerce_args(tool, {"status": "IN PROGRESS"})
    assert report.corrected["status"] == "in_progress"
    assert report.changes[0]["rule"] == "enum"


def test_coerce_enum_unresolved_when_no_match():
    tool = _tool("t", [ToolParameter(name="status", type="string", enum=["a", "b"])])
    report = coerce_args(tool, {"status": "zzz"})
    assert report.corrected["status"] == "zzz", "매치 실패 시 원값 유지"
    assert "status" in report.unresolved


def test_coerce_bad_int_string_left_alone():
    tool = _tool("t", [ToolParameter(name="n", type="integer")])
    report = coerce_args(tool, {"n": "not-a-number"})
    assert report.corrected == {"n": "not-a-number"}
    assert report.changes == []


# ---------------------------------------------------------------------------
# runner validate_args='coerce' hook
# ---------------------------------------------------------------------------


def _record_caller():
    seen: list[tuple[str, dict]] = []

    def call(name: str, args: dict[str, Any]) -> Any:
        seen.append((name, dict(args)))
        return {"ok": True}

    call.seen = seen  # type: ignore[attr-defined]
    return call


def test_runner_coerces_args_before_call():
    tool = _tool("search", [ToolParameter(name="page", type="integer")])
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="search", args={"page": "2"})],
        output_binding="${s1}",
    )
    caller = _record_caller()
    runner = PlanRunner(caller, tools={"search": tool}, validate_args="coerce")
    events = list(runner.run_stream(plan))
    coerced = [e for e in events if isinstance(e, ArgsCoerced)]
    assert len(coerced) == 1
    assert coerced[0].changes[0]["to"] == 2
    # 실제 도구가 캐스팅된 정수를 받았는지
    assert caller.seen[0][1] == {"page": 2}  # type: ignore[attr-defined]


def test_runner_no_coercion_when_off():
    tool = _tool("search", [ToolParameter(name="page", type="integer")])
    plan = Plan(
        id="t",
        goal="g",
        steps=[PlanStep(id="s1", tool="search", args={"page": "2"})],
    )
    caller = _record_caller()
    runner = PlanRunner(caller, tools={"search": tool})  # validate_args default 'off'
    events = list(runner.run_stream(plan))
    assert not [e for e in events if isinstance(e, ArgsCoerced)]
    assert caller.seen[0][1] == {"page": "2"}, "off 면 문자열 그대로"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# runner binding_recovery hook
# ---------------------------------------------------------------------------


def test_binding_recovery_relocates_stale_path():
    """선언된 ${s1.body.goodsNo} 가 실제 응답 모양과 안 맞아도 트리 검색으로 회수."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="search"),
            PlanStep(id="s2", tool="detail", args={"goodsNo": "${s1.body.goodsNo}"}),
        ],
        output_binding="${s2}",
    )

    def caller(name: str, args: dict[str, Any]) -> Any:
        if name == "search":
            # body 래퍼 없이 다른 모양으로 응답 → 선언 경로 miss
            return {"result": {"items": [{"goodsNo": "G-42"}]}}
        return {"got": args}

    runner = PlanRunner(caller, binding_recovery=True)
    events = list(runner.run_stream(plan))
    repaired = [e for e in events if isinstance(e, BindingRepaired)]
    assert len(repaired) == 1
    assert repaired[0].field_name == "goodsNo"
    assert repaired[0].recovered_path.endswith("goodsNo")
    completed = events[-1]
    assert completed.type == "plan.completed"
    assert completed.output == {"got": {"goodsNo": "G-42"}}


def test_binding_recovery_off_aborts_as_before():
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="search"),
            PlanStep(id="s2", tool="detail", args={"goodsNo": "${s1.body.goodsNo}"}),
        ],
    )

    def caller(name: str, args: dict[str, Any]) -> Any:
        if name == "search":
            return {"result": {"items": [{"goodsNo": "G-42"}]}}
        return {"got": args}

    runner = PlanRunner(caller)  # binding_recovery default False
    trace = runner.run(plan)
    assert trace.success is False
    assert trace.failed_step == "s2"
    assert trace.steps[-1].error["kind"] == "binding"


def test_binding_recovery_gives_up_on_ambiguous():
    """동일 confidence 후보가 둘이면 회수 포기 → abort (silent 오선택 방지)."""
    plan = Plan(
        id="t",
        goal="g",
        steps=[
            PlanStep(id="s1", tool="search"),
            PlanStep(id="s2", tool="detail", args={"code": "${s1.body.code}"}),
        ],
    )

    def caller(name: str, args: dict[str, Any]) -> Any:
        if name == "search":
            # 같은 깊이에 'code' 두 개 → 동률 → 애매
            return {"a": {"code": "X"}, "b": {"code": "Y"}}
        return {"got": args}

    runner = PlanRunner(caller, binding_recovery=True)
    trace = runner.run(plan)
    assert trace.success is False
    assert trace.failed_step == "s2"


# ---------------------------------------------------------------------------
# validate_args validation
# ---------------------------------------------------------------------------


def test_invalid_validate_args_raises():
    import pytest

    with pytest.raises(ValueError):
        PlanRunner(lambda n, a: None, validate_args="bogus")
