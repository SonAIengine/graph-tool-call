---
title: Plan Synthesis
description: Build executable tool paths from a selected target, entities, context defaults, and contract evidence.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Plan Synthesis

Plan synthesis turns a selected target tool into an executable path. It decides
which arguments are already known, which fields can be supplied by collection
context, which upstream producer tools can satisfy missing values, and which
values must be requested from the user.

The synthesizer is deterministic and transport-agnostic. It consumes graph and
tool metadata. It does not call HTTP APIs, read product databases, resolve
runtime auth, or talk to a UI. Those responsibilities belong to the adapter.

Use this page when a tool was selected correctly but the system still needs to
explain how to call it safely.

## Where It Runs

Plan synthesis starts after target selection and ends before execution.

| Stage | Input | Output | Owned By |
| --- | --- | --- | --- |
| Intent parsing | user query | target hint, entities | LLM or adapter |
| Target selection | candidates and evidence | final selected target | graph-tool-call |
| Plan synthesis | target, entities, graph contracts | `Plan` or structured error | graph-tool-call |
| User input | missing slots and enum mappings | resumed input context | product adapter |
| Execution | plan and runtime auth | runner events | product adapter + `PlanRunner` |

If plan synthesis fails, the error should say whether the missing piece is an
unknown target, an unsatisfied required field, an enum mapping, a dynamic option,
a cycle, or a depth limit.

## Public API

<Tabs>
  <TabItem value="basic" label="Basic" default>

```python
from graph_tool_call.plan import PathSynthesizer

synthesizer = PathSynthesizer(
    graph_payload,
    context_defaults={"locale": "ko_KR"},
    enum_field_names={"statusCode"},
)

plan = synthesizer.synthesize(
    target="getOrderDetail",
    entities={"orderNo": "A-100"},
    goal="Find order detail",
)
```

  </TabItem>
  <TabItem value="with-selector" label="With selector">

```python
from graph_tool_call.graphify import select_target_candidate
from graph_tool_call.plan import PathSynthesizer

selection = select_target_candidate(
    query=query,
    candidates=retrieval_rows,
    tools=graph_json["tools"],
    retrieval_results=retrieval_rows,
    llm_target=intent.target,
)

synthesizer = PathSynthesizer(
    graph_json,
    context_defaults=collection_context_defaults,
    enum_field_names=collection_enum_field_names,
)

plan = synthesizer.synthesize(
    target=selection["selected_target"],
    entities=intent.entities,
    goal=query,
)
plan.metadata.setdefault("synthesis", {})["target_selector"] = selection
```

  </TabItem>
  <TabItem value="run-stream" label="Run stream">

```python
from dataclasses import asdict

from graph_tool_call.plan import PlanRunner

runner = PlanRunner(call_tool)

for event in runner.run_stream(
    plan,
    input_context={"orderNo": "A-100"},
    trace_metadata={"collection_id": "bo-dev"},
):
    forward_to_sse(asdict(event))
```

  </TabItem>
</Tabs>

## Input Contract

`PathSynthesizer` is initialized with a graph artifact and optional collection
settings.

| Constructor Argument | Type | Purpose |
| --- | --- | --- |
| `graph` | `dict` | Graph artifact containing tools, metadata, and edges |
| `max_depth` | `int` | Maximum producer-chain depth. Default is `5` |
| `context_defaults` | `dict` | Ambient collection values such as locale, tenant, site, or channel |
| `enum_field_names` | `set[str]` | Fields that should use adapter/user enum mapping instead of producer chaining |

`synthesize()` accepts the selected target and runtime entities.

| Method Argument | Type | Purpose |
| --- | --- | --- |
| `target` | `str` | Final selected tool name |
| `entities` | `dict` | Values extracted from the user request or supplied by the adapter |
| `goal` | `str` | Human-readable goal stored on the plan |
| `exclude_tools` | `set[str]` | Optional producer tools to avoid during repair or retry |

The synthesizer expects tools to include `metadata.api_contract.consumes` and
`metadata.api_contract.produces` when available. It can still operate with weak
metadata, but the plan will be less explainable and more likely to ask for user
input.

## Input Priority

For each required consume field, the synthesizer checks sources in a stable
order.

| Priority | Source | Example |
| --- | --- | --- |
| 1 | user or LLM-extracted `entities` | `{"orderNo": "A-100"}` |
| 2 | `context_defaults` for context fields | `siteNo`, `locale`, `channel` |
| 3 | producer tool with matching semantic tag | `member_id` produced by a search step |
| 4 | producer tool with matching field name | `ordNo` -> `ordNo` |
| 5 | graph edge or workflow fallback | curated producer relation |
| 6 | user input fallback when allowed | `${user_input.statusCode}` |

This order keeps explicit user facts ahead of inferred graph paths and keeps
collection context outside library-specific code.

## Plan Shape

A synthesized plan is a serializable artifact composed of `Plan` and `PlanStep`.

```python
from graph_tool_call.plan import Plan, PlanStep

plan = Plan(
    id="plan-001",
    goal="Find order detail",
    steps=[
        PlanStep(
            id="s1",
            tool="searchOrders",
            args={"keyword": "A-100"},
        ),
        PlanStep(
            id="s2",
            tool="getOrderDetail",
            args={"orderNo": "${s1.items.0.orderNo}"},
            depends_on=["s1"],
        ),
    ],
    output_binding="${s2}",
    metadata={
        "target": "getOrderDetail",
        "synthesis": {
            "target": "getOrderDetail"
        }
    },
)
```

`PlanStep.args` may contain binding expressions:

| Binding | Meaning |
| --- | --- |
| `${input.orderNo}` | value from `input_context` |
| `${user_input.statusCode}` | value collected from a user slot |
| `${s1.items.0.orderNo}` | value from a previous step output |
| `${s2}` | whole output of step `s2` |

`PlanRunner` resolves bindings at execution time. The synthesizer only declares
the dependency.

## Metadata To Preserve

Adapters should persist `Plan.metadata.synthesis`. This is the main debugging
contract for plan construction.

| Field | Purpose |
| --- | --- |
| `target` | Final selected target |
| `selected_producers` | Producer tools used to satisfy required fields |
| `candidate_signals` | Why producer candidates were ranked |
| `fallbacks` | Fields that fell back to user input |
| `user_input_slots` | Flattened UI-ready missing input list |
| `context_defaults` | Context keys used. Do not persist secret values |
| `enum_field_names` | Fields requiring enum mapping |
| `target_selector` | LLM target, final target, override diagnostics |

For product logs, store field names, kinds, semantic tags, and reason codes. Do
not store raw auth headers, cookies, or user identifiers.

## User Input Slots

When a required value cannot be filled automatically but user input is allowed,
the plan records `user_input_slots`.

```json
{
  "step_id": "s2",
  "tool": "getOrderDetail",
  "field_name": "statusCode",
  "required": true,
  "kind": "data",
  "location": "query",
  "semantic_tag": "order_status",
  "reason": "enum_required"
}
```

Adapters can render one popup, collect values, and resume the same plan with:

```python
for event in runner.run_stream(
    plan,
    input_context={"statusCode": "COMPLETE"},
):
    handle(event)
```

The library does not prescribe UI behavior. It only exposes stable slot
metadata.

## Failure Reasons

`PlanSynthesisError` exposes `to_dict()` so adapters can store structured
diagnostics instead of parsing exception messages.

```python
from graph_tool_call.plan import PlanSynthesisError

try:
    plan = synthesizer.synthesize(target="getOrderDetail", entities={})
except PlanSynthesisError as exc:
    result = exc.to_dict()
    print(result["reason"])
```

Common reason codes:

| Reason | Meaning | Adapter Response |
| --- | --- | --- |
| `unknown_target` | Target tool is not present in the graph | rerun retrieval or inspect selector |
| `unsatisfied_field` | Required field cannot be filled | ask user, add context default, or improve producer contract |
| `enum_required` | Required enum needs user or adapter mapping | show enum mapping UI |
| `dynamic_option_required` | A dynamic option list should be fetched first | call option producer and ask user to choose |
| `cycle` | Producer search revisited a tool already in progress | inspect graph edges |
| `max_depth` | Producer chain exceeded configured depth | reduce graph noise or increase depth carefully |
| `user_input_fallback` | Plan can continue only after user input | render user slot and resume |

Structured failure reasons are part of the public contract. Use them in Quality
Lab, SSE/log events, and operator diagnostics.

## Dynamic Option Flow

Some fields cannot be guessed from text and should not be filled through long
producer chains. Common examples are enum-like codes, product options, or UI
selection values.

When a single-hop producer can fetch a useful option list, synthesis can raise a
dynamic option diagnostic with:

| Field | Meaning |
| --- | --- |
| `field_name` | field that needs a value |
| `semantic_tag` | semantic category of the field |
| `producer_name` | tool that can fetch options |
| `options_path` | response path containing options |
| `label_field_hints` | candidate fields for display labels |

The adapter should call the producer, show choices, and resume plan execution
with the selected value.

## Runner Handoff

Plan synthesis produces the plan. `PlanRunner` executes it through an adapter
callback.

```python
def call_tool(tool_name: str, args: dict) -> dict:
    # Adapter responsibility:
    # - resolve base URL
    # - attach auth/session headers
    # - execute HTTP/MCP/function call
    # - normalize response shape
    return execute_collection_tool(tool_name, args)

runner = PlanRunner(call_tool, validate_args="coerce")

events = list(
    runner.run_stream(
        plan,
        input_context=entities,
        trace_metadata={
            "collection_id": collection_id,
            "graph_tool_call_version": graph_tool_call.__version__,
        },
    )
)
```

Runner events should preserve `plan_id`, `step_id`, `tool`, stage, error kind,
duration, and trace metadata. See [Runner Events](./runner-events.md) for the
event schema.

## Adapter Boundary

graph-tool-call owns deterministic plan construction. Product adapters own
runtime systems.

| Responsibility | Owner |
| --- | --- |
| field dependency analysis | graph-tool-call |
| producer search | graph-tool-call |
| plan artifact and synthesis metadata | graph-tool-call |
| auth profile lookup | adapter |
| session/header resolution | adapter |
| HTTP execution | adapter |
| user popup and resume UX | adapter |
| persistence and audit retention | adapter |

Keep product-specific DB, auth, cookies, user IDs, and SSE UI code outside the
library. Pass only product-neutral graph metadata into the engine.

## Quality Checks

Plan synthesis quality should be tested separately from execution. A downstream
API 401 should not be counted as a plan synthesis failure.

| Check | Expected Result |
| --- | --- |
| known target | plan final step equals selected target |
| entity fill | explicit entity values are used before producers |
| context default | context fields are filled without user prompts |
| producer path | missing data field creates upstream producer step |
| enum field | enum mapping creates a user slot or structured error |
| cycle guard | cyclic graph fails with `cycle` |
| max depth | long chain fails with `max_depth` |
| metadata | `Plan.metadata.synthesis` contains target, producers, and slots |

Useful commands:

```bash
poetry run pytest tests/test_plan_synthesizer.py -q
poetry run pytest tests/test_runner.py -q
poetry run pytest tests/test_graphify_contract_025.py -q
```

Product validation should also run Quality Lab plan cases and compare:

- selected target
- plan tools
- user input slots
- failure reason
- synthesis latency
- execution status only after auth readiness passes

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| `unknown_target` | selector chose a name not present in the graph | target selector output and graph artifact |
| required field missing | entity extraction or contract coverage is weak | `api_contract.consumes`, `user_input_slots` |
| too many producer steps | graph has broad structural edges | edge quality and producer candidate signals |
| enum values guessed incorrectly | enum field was treated as ordinary data | `enum_field_names`, user input slots |
| runner binding failure | response shape differs from contract | producer output, response envelope, binding path |
| plan passes but API fails | auth or downstream request issue | runner events and auth readiness |

## Operational Guidance

A production-ready collection should have:

- stable target selection before synthesis
- request and response contract coverage for important operations
- context defaults for ambient runtime fields
- enum mappings for fields that require operator choice
- Quality Lab plan fixtures for high-frequency workflows
- runner traces that preserve stage and failure reason
- no raw secrets in plan metadata or trace records

When improving a large API collection, debug in this order:

1. confirm the expected tool appears in retrieval Top-K
2. inspect target selector evidence
3. run plan synthesis with explicit entities
4. inspect missing fields and producer candidates
5. add context defaults or enum mappings
6. run execution only after auth readiness passes

## Related Pages

- [Target Selection](../search/target-selection.md)
- [User Input Slots](./user-input-slots.md)
- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
