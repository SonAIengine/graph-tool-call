# Long-horizon tool-use goal evaluation

## Question

The benchmark answers one product question:

> Given only a natural-language request and a large tool catalog, did the
> system find every necessary capability, execute a valid dependency order,
> pass the right values between calls, recover safely, and reach the requested
> final state?

An exact tool array is not the primary ground truth. Real APIs can expose
equivalent tools and independent branches can run in different valid orders.

## Stable scenario contract

`graph_tool_call.evaluation.ScenarioSpec` contains:

- `milestones`: semantic steps with one or more allowed tools
- `dependency_constraints`: partial-order requirements between milestones
- `binding_constraints`: source response path to target argument equality
- `final_state_assertions`: deterministic checks on state or final output
- `forbidden_tools`: policy and mutation safety boundaries
- `max_calls`, `max_replans`, `timeout_sec`: bounded execution budgets

The evaluator accepts a transport-neutral `GoalExecutionRecord`. XGEN can
adapt Quality Lab traces to this record without moving DB, auth, HTTP, or SSE
logic into graph-tool-call.

## Metrics

The report keeps stages separate so a high retrieval score cannot hide an
execution failure:

1. candidate required-tool recall
2. plan required-tool recall
3. execution required-tool recall and milestone completion
4. dependency-order accuracy
5. binding accuracy
6. schema-valid call rate
7. final-state accuracy
8. extraneous-call and policy-violation rates
9. recovery attempt/success, calls, replans, latency
10. strict final goal completion

`goal_completion=1` requires runner success and every hard scenario check to
pass. Partial metrics remain diagnostic only.

## Evaluation tiers

| Tier | Required calls | Purpose | Routine |
|---|---:|---|---|
| L1 | 2-4 | target, basic order, binding | every PR |
| L2 | 5-8 | multiple producers and branches | every PR/nightly |
| L3 | 9-15 | pagination, retries, re-planning | nightly |
| L4 | 16-30 | long context and sustained execution | release candidate |

The deterministic sandbox remains resettable and safe for every commit. Real
XGEN dev APIs are a separate release-candidate gate with read-only assertions
or explicit mutation cleanup.

## Baseline and next bottleneck

The initial six-case L1 fixture completes 3/6 goals. Product detail, checkout,
and review pass. Inventory, add-to-cart, and shipment tracking fail because the
intended target is retrieved but an upstream tool is selected as the final
target. The runner then executes a valid but incomplete one-step plan.

The next engine change therefore targets final-target inference for compound
requests. It must improve this sealed baseline without reading milestone gold
data and without adding fixture-specific operation names or domain aliases.

After the L1 selector gate passes, work proceeds in this order:

1. add L2 scenarios with alternative tools and independent dependency branches
2. add explicit retry/re-plan trajectories and recovery metrics
3. add state-reset and cleanup adapters for XGEN Quality Lab
4. run the same sealed cases with the XGEN default model at three repeats
5. add L3/L4 datasets and compare full catalog, Top-K, graph closure, and the
   complete graph-tool-call pipeline under the same model and prompt

README or paper claims may use only versioned scenario files and saved reports
that can be reproduced by the documented command.
