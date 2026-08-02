---
title: Candidate Expansion
description: Expand retrieved targets with producer tools and graph neighbors when evidence supports it.
---

# Candidate Expansion

Candidate expansion adds related tools after the initial search stage. The most
important expansion is producer discovery: if a target consumes a required field,
the graph can include tools that produce that field.

This keeps the LLM catalog compact while still giving plan synthesis enough
tools to fill required inputs.

For execution-oriented planning, prefer evidence-gated dependency completion
after target selection. The legacy list helper remains useful for broad catalog
expansion.

## Minimal Example

```python
from graph_tool_call.graphify import expand_candidates_with_producers

expanded = expand_candidates_with_producers(
    candidate_names=["cancelOrder"],
    tools_by_name=tools_by_name,
    max_producers_per_field=2,
    max_hops=1,
)
```

If `cancelOrder` requires `orderNo` and another tool produces `orderNo`, the
producer can be added to the candidate list before target selection or planning.

## Target-Specific Dependency Closure

```python
from graph_tool_call.graphify import (
    assemble_tool_bundle,
    complete_target_dependencies,
)

closure = complete_target_dependencies(
    selected_target,
    tools_by_name,
    graph=tool_graph,
    query=query,
    available_fields={"tenant_id"},
    context_field_names={"workspace_id"},
    allow_mutation=False,
    max_hops=3,
)

bundle = assemble_tool_bundle(
    query,
    selected_target,
    tools_by_name,
    graph=tool_graph,
    target_alternatives=target_shortlist,
    token_budget=2048,
    token_counter=tokenizer,
    allow_mutation=False,
)
```

The closure keeps `required_dependencies`, `optional_dependencies`, and target
alternatives in separate roles. Field-level evidence explains every admitted
producer. Weak name-only evidence is reported as ambiguity instead of being
silently executed. If the target and required chain do not fit the token budget,
the bundle returns `budget_insufficient`.

Mutation is deny-by-default. A matching `create`, `update`, or `delete` tool
requires both write/delete intent in the query and `allow_mutation=True` after
the adapter's own authorization and confirmation checks. Either signal alone is
insufficient, and blocked tools stay out of model-facing alternatives.
Contract-only producers also need
a discovery-shaped query such as `find/list -> inspect/execute`; direct IDs,
body fields, and scope values remain user-input slots instead of causing extra
network calls. Inspect `closure.safety`, `closure.user_input_slots`, and
`closure.diagnostics` to explain every decision.

Callers that omit `query` retain the v1 admission behavior for backward
compatibility. Execution adapters should always pass the original query.

For OpenAPI graphs, consumer-aligned output promotion can improve producer
coverage, but it is not a blanket license to execute every matching neighbor.
API-contract edges are resolved per required field, while unscoped structural
`requires` edges remain optional hints. Validate a collection before rollout:

```bash
make paper-openapi-closure
```

The gate reports required-producer recall, complete dependency coverage,
unexpected dependencies, and sample sufficiency. OpenAPI-optional workflow
steps remain planner decisions unless query, manual, OpenAPI Link, or promoted
trace evidence makes them explicit.

## Expansion Sources

- deterministic IO contract edges
- OpenAPI links
- manual edges
- promoted run-observed trace edges
- high-confidence semantic links

## Inputs

| Parameter | Purpose |
| --- | --- |
| `candidate_names` | Initial retrieved targets |
| `tools_by_name` | Tool metadata keyed by name |
| `max_producers_per_field` | Upper bound for each missing required field |
| `max_hops` | How far to follow producer chains |
| `action_priority` | Optional generic ordering for producer-like actions |

The helper only expands required `kind=data` consume fields. Context, auth,
paging, and search filters should not explode the execution catalog.

## Output

The function returns an ordered list of tool names. Original candidates remain
first, followed by producer candidates. The output intentionally stays simple so
adapters can pass it to LLM catalog construction or `select_target_candidate()`.

```python
[
    "cancelOrder",
    "searchOrders",
    "getOrderDetail",
]
```

## Safety Policy

Expansion should improve planning without flooding the LLM catalog. Keep
low-confidence structural edges available for graph inspection, but prefer
strong evidence for execution-oriented candidates.

Recommended defaults:

| Setting | Default Guidance |
| --- | --- |
| `max_hops` | `1` for general retrieval, higher only for target-specific planning |
| `max_producers_per_field` | `1` to `3` |
| Manual edges | Use when deterministic contract evidence cannot express the relation |
| Trace edges | Use only after promotion, not from a single observed run |
| Required closure | Reserve before target alternatives and optional tools |
| Schema form | Use projected schemas for selection; hydrate full schemas before execution |

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Too many expanded tools | broad required fields or high `max_hops` | lower hop/producer limits |
| No producers added | missing `produces` metadata | inspect IO contracts |
| Wrong producer added | weak semantic tags | improve OpenAPI semantic build or aliases |
| LLM sees implementation helpers | source catalog includes non-user tools | filter at collection build time |

## Validation

Candidate expansion should be tested through plan outcomes, not only list size.
A good expansion reduces `unsatisfied_field` failures without raising average
candidate count too much.

Track:

- average candidate count
- max candidate count
- plan hit rate
- `unsatisfied_field` count
- selector ambiguity count

## Related Pages

- [IO Contracts](../build/io-contracts.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Target Selection](./target-selection.md)
