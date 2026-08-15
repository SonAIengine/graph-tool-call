from __future__ import annotations

from graph_tool_call import GoalExecutionRecord, ScenarioSpec, evaluate_goal_execution
from graph_tool_call.evaluation import ObservedToolCall
from graph_tool_call.plan import ExecutionTrace, Plan, PlanStep, StepTrace


def _scenario() -> ScenarioSpec:
    return ScenarioSpec.from_dict(
        {
            "id": "change_shipping_address",
            "query": "내 최근 주문을 찾아 배송지를 서울로 바꾸고 확인해줘",
            "milestones": [
                {"id": "find_order", "tools": ["findOrders", "searchOrders"]},
                {"id": "change_address", "tools": ["updateShippingAddress"]},
                {"id": "verify_order", "tools": ["getOrderDetail"], "target": True},
            ],
            "dependency_constraints": [
                {"before": "find_order", "after": "change_address"},
                {"before": "change_address", "after": "verify_order"},
            ],
            "binding_constraints": [
                {
                    "source_milestone": "find_order",
                    "source_path": "orders[0].orderId",
                    "target_milestone": "change_address",
                    "target_arg": "orderId",
                },
                {
                    "source_milestone": "find_order",
                    "source_path": "orders[0].orderId",
                    "target_milestone": "verify_order",
                    "target_arg": "orderId",
                },
            ],
            "final_state_assertions": [
                {
                    "scope": "final_state",
                    "path": "orders.O1.shippingAddress",
                    "operator": "eq",
                    "value": "서울",
                }
            ],
            "forbidden_tools": ["cancelOrder"],
            "max_calls": 4,
            "max_replans": 1,
            "timeout_sec": 5,
        }
    )


def _valid_record() -> GoalExecutionRecord:
    return GoalExecutionRecord(
        calls=(
            ObservedToolCall(
                sequence=1,
                tool="searchOrders",
                args={"q": "recent"},
                output={"orders": [{"orderId": "O1"}]},
                schema_valid=True,
            ),
            ObservedToolCall(
                sequence=2,
                tool="updateShippingAddress",
                args={"orderId": "O1", "shippingAddress": "서울"},
                output={"orderId": "O1", "updated": True},
                schema_valid=True,
            ),
            ObservedToolCall(
                sequence=3,
                tool="getOrderDetail",
                args={"orderId": "O1"},
                output={"orderId": "O1", "shippingAddress": "서울"},
                schema_valid=True,
            ),
        ),
        success=True,
        retrieved_tools=("getOrderDetail", "updateShippingAddress", "searchOrders"),
        candidate_tools=("getOrderDetail", "updateShippingAddress", "searchOrders"),
        planned_tools=("searchOrders", "updateShippingAddress", "getOrderDetail"),
        final_state={"orders": {"O1": {"shippingAddress": "서울"}}},
        latency_ms=40,
    )


def test_goal_evaluator_accepts_alternative_tools_and_valid_outcome():
    result = evaluate_goal_execution(_scenario(), _valid_record())

    assert result.goal_completed is True
    assert result.failure_reason_codes == ()
    assert result.metrics["candidate_required_tool_recall"] == 1.0
    assert result.metrics["plan_required_tool_recall"] == 1.0
    assert result.metrics["dependency_order_accuracy"] == 1.0
    assert result.metrics["binding_accuracy"] == 1.0
    assert result.metrics["final_state_accuracy"] == 1.0
    assert result.metrics["schema_valid_call_rate"] == 1.0
    assert result.metrics["goal_completion"] == 1.0


def test_goal_evaluator_separates_order_binding_and_final_state_failures():
    valid = _valid_record()
    broken = GoalExecutionRecord(
        calls=(
            ObservedToolCall(
                sequence=1,
                tool="updateShippingAddress",
                args={"orderId": "O1", "shippingAddress": "서울"},
                output={"orderId": "O1", "updated": True},
                schema_valid=True,
            ),
            ObservedToolCall(
                sequence=2,
                tool="searchOrders",
                args={"q": "recent"},
                output={"orders": [{"orderId": "O1"}]},
                schema_valid=True,
            ),
            ObservedToolCall(
                sequence=3,
                tool="getOrderDetail",
                args={"orderId": "WRONG"},
                output={"orderId": "WRONG", "shippingAddress": "부산"},
                schema_valid=True,
            ),
        ),
        success=True,
        candidate_tools=valid.candidate_tools,
        planned_tools=("updateShippingAddress", "searchOrders", "getOrderDetail"),
        final_state={"orders": {"O1": {"shippingAddress": "부산"}}},
    )

    result = evaluate_goal_execution(_scenario(), broken)

    assert result.goal_completed is False
    assert "invalid_dependency_order" in result.failure_reason_codes
    assert "binding_mismatch" in result.failure_reason_codes
    assert "goal_state_mismatch" in result.failure_reason_codes


def test_goal_evaluator_reports_missing_milestone_policy_and_budget():
    record = GoalExecutionRecord(
        calls=(
            ObservedToolCall(sequence=1, tool="findOrders", output={"orders": []}),
            ObservedToolCall(sequence=2, tool="cancelOrder"),
            ObservedToolCall(sequence=3, tool="noop"),
            ObservedToolCall(sequence=4, tool="noop"),
            ObservedToolCall(sequence=5, tool="noop"),
        ),
        success=True,
        final_state={"orders": {}},
        replans=2,
        latency_ms=6000,
    )

    result = evaluate_goal_execution(_scenario(), record)

    assert result.goal_completed is False
    assert "missing_milestone" in result.failure_reason_codes
    assert "forbidden_tool_called" in result.failure_reason_codes
    assert "max_calls_exceeded" in result.failure_reason_codes
    assert "max_replans_exceeded" in result.failure_reason_codes
    assert "timeout_exceeded" in result.failure_reason_codes
    assert result.metrics["policy_violation_count"] == 1


def test_goal_evaluation_serialization_scrubs_sensitive_values():
    scenario = ScenarioSpec.from_dict(
        {
            "id": "secret_safe",
            "query": "인증 상태 확인",
            "milestones": [{"id": "check", "tools": ["checkAuth"]}],
            "final_state_assertions": [
                {"path": "email", "operator": "eq", "value": "person@example.com"}
            ],
        }
    )
    record = GoalExecutionRecord(
        calls=(ObservedToolCall(sequence=1, tool="checkAuth"),),
        success=True,
        final_state={"email": "wrong@example.com"},
    )

    payload = evaluate_goal_execution(scenario, record).to_dict()
    state_check = next(item for item in payload["checks"] if item["category"] == "state")

    assert "person@example.com" not in str(state_check)
    assert "wrong@example.com" not in str(state_check)

    call_payload = ObservedToolCall(
        sequence=1,
        tool="checkAuth",
        args={"authorization": "Bearer secret-token"},
        output={"email": "person@example.com"},
    ).to_dict()
    assert "secret-token" not in str(call_payload)
    assert "person@example.com" not in str(call_payload)


def test_goal_execution_record_adapts_plan_runner_trace():
    plan = Plan(
        id="p1",
        goal="lookup",
        steps=[PlanStep(id="s1", tool="findOrders", args={"q": "recent"})],
    )
    trace = ExecutionTrace(
        plan_id="p1",
        success=True,
        steps=[
            StepTrace(
                id="s1",
                tool="findOrders",
                args_resolved={"q": "recent"},
                output={"orders": [{"orderId": "O1"}]},
                duration_ms=3,
            )
        ],
        output={"orders": [{"orderId": "O1"}]},
        total_duration_ms=4,
    )

    record = GoalExecutionRecord.from_execution_trace(
        trace,
        plan=plan,
        retrieved_tools=["findOrders"],
        candidate_tools=["findOrders"],
        schema_valid=True,
    )

    assert record.success is True
    assert record.planned_tools == ("findOrders",)
    assert record.calls[0].args == {"q": "recent"}
    assert record.calls[0].schema_valid is True


def test_scenario_contract_round_trips_and_validates_references():
    scenario = _scenario()

    assert ScenarioSpec.from_dict(scenario.to_dict()) == scenario

    invalid = scenario.to_dict()
    invalid["dependency_constraints"] = [{"before": "unknown", "after": "find_order"}]
    try:
        ScenarioSpec.from_dict(invalid)
    except ValueError as exc:
        assert "known milestones" in str(exc)
    else:  # pragma: no cover - contract guard
        raise AssertionError("invalid milestone reference was accepted")


def test_milestone_matching_handles_overlapping_alternatives_and_arg_filters():
    scenario = ScenarioSpec.from_dict(
        {
            "id": "overlapping",
            "query": "두 주문 상태를 확인",
            "milestones": [
                {"id": "any_order", "tools": ["getOrder", "findOrder"]},
                {
                    "id": "specific_order",
                    "tools": ["getOrder"],
                    "match_args": {"orderId": "O2"},
                },
            ],
        }
    )
    record = GoalExecutionRecord(
        calls=(
            ObservedToolCall(sequence=1, tool="getOrder", args={"orderId": "O2"}),
            ObservedToolCall(sequence=2, tool="findOrder", args={"query": "recent"}),
        ),
        success=True,
    )

    result = evaluate_goal_execution(scenario, record)

    assert result.goal_completed is True
    assert result.matched_milestones == {"specific_order": 1, "any_order": 2}
    assert result.metrics["extraneous_call_rate"] == 0.0


def test_unsupported_partial_path_is_reported_as_state_mismatch():
    scenario = ScenarioSpec.from_dict(
        {
            "id": "invalid_path",
            "query": "마지막 주문 확인",
            "milestones": [{"id": "read", "tools": ["getOrders"]}],
            "final_state_assertions": [
                {"path": "orders[-1].status", "operator": "eq", "value": "paid"}
            ],
        }
    )
    record = GoalExecutionRecord(
        calls=(ObservedToolCall(sequence=1, tool="getOrders"),),
        success=True,
        final_state={"orders": [{"status": "paid"}]},
    )

    result = evaluate_goal_execution(scenario, record)

    assert result.goal_completed is False
    assert result.failure_reason_codes == ("goal_state_mismatch",)
