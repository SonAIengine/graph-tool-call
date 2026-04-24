"""Plan-and-Execute primitives: schemas, binding resolver, runner.

The ``plan`` package is deliberately transport-agnostic. It knows nothing
about HTTP, authentication, or xgen internals — it only defines how a
Plan looks, how string bindings are resolved against step outputs, and how
to drive execution via an injected callable.

Typical use (from an integration layer like xgen-workflow):

    from graph_tool_call.plan import Plan, PlanStep, PlanRunner

    plan = Plan(id="...", goal="...", steps=[PlanStep(...), ...])

    def call_tool(tool_name, args):
        return my_http_executor.execute(tool_name, args)

    runner = PlanRunner(call_tool)
    for event in runner.run(plan):
        # event: StepStarted | StepCompleted | StepFailed | PlanCompleted
        ...
"""

from graph_tool_call.plan.binding import (
    BindingError,
    resolve_bindings,
)
from graph_tool_call.plan.runner import (
    PlanRunner,
    PlanEvent,
    PlanStarted,
    StepStarted,
    StepCompleted,
    StepFailed,
    PlanCompleted,
    PlanAborted,
)
from graph_tool_call.plan.schema import (
    Plan,
    PlanStep,
    ExecutionTrace,
    StepTrace,
)

__all__ = [
    # schema
    "Plan",
    "PlanStep",
    "ExecutionTrace",
    "StepTrace",
    # binding
    "BindingError",
    "resolve_bindings",
    # runner + events
    "PlanRunner",
    "PlanEvent",
    "PlanStarted",
    "StepStarted",
    "StepCompleted",
    "StepFailed",
    "PlanCompleted",
    "PlanAborted",
]
