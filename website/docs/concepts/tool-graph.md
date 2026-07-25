---
title: Tool Graph
description: Understand the graph data model that powers retrieval, candidate expansion, planning, visualization, and trace learning.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Tool Graph

A tool graph is the evidence layer between a large tool catalog and an LLM
agent. It stores tools as nodes, relationships as edges, and diagnostics as
metadata so retrieval, target selection, planning, and product UIs can explain
why a tool was found.

The graph is not a picture first. It is a contract-bearing search structure.
Visualization is one consumer of the graph, but the main purpose is to turn a
large catalog into a small, ranked, inspectable candidate set.

## What The Graph Stores

```text
OpenAPI / MCP / Python tools
        |
        v
ToolSchema nodes
api_contract
semantic metadata
        |
        v
evidence edges
readiness reports
quality summaries
        |
        v
retrieval
target selection
plan synthesis
runner events
learning
```

A useful graph artifact answers five questions:

1. What does each tool do?
2. Which request fields does it need?
3. Which response fields can it produce?
4. Which tools are related by reliable evidence?
5. Which parts are weak, missing, or unsafe to execute?

## Minimal Build

<Tabs>
  <TabItem value="cli" label="CLI" default>

```bash
graph-tool-call \
  build-openapi-collection \
  openapi.json \
  -o artifact.json
```

  </TabItem>
  <TabItem value="python" label="Python">

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
)

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
)

print(artifact["semantic_summary"])
print(artifact["edge_quality_summary"])
```

  </TabItem>
  <TabItem value="inspect-node" label="Node">

```python
tool = next(iter(artifact["tools"].values()))

print(tool["name"])
print(tool["metadata"]["openapi"])
print(tool["metadata"]["ai_metadata"])
print(tool["metadata"]["api_contract"])
```

  </TabItem>
  <TabItem value="inspect-edge" label="Edge">

```python
edge = artifact["graph"]["edges"][0]

print(edge["source"], "->", edge["target"])
print(edge["relation"])
print(edge["evidence_sources"])
print(edge.get("data_flow"))
```

  </TabItem>
</Tabs>

For product integrations, persist the full artifact rather than only the graph
payload. The summary and readiness sections are what make the build observable.

## Node Model

Each tool node starts as a `ToolSchema`. The node can hold source facts,
semantic facts, IO contracts, and execution readiness facts.

| Area | Typical Fields | Why It Matters |
| --- | --- | --- |
| Identity | `name`, `description`, `tags`, `source` | Basic catalog identity and keyword search |
| OpenAPI | `method`, `path`, `operation_id`, `parameters`, `security` | Request construction and auth diagnostics |
| Semantics | `canonical_action`, `primary_resource`, `path_module`, `result_shape` | Action/resource/shape matching for retrieval and target selection |
| Contract | `api_contract.consumes`, `api_contract.produces`, `api_contract.links` | Producer expansion and plan synthesis |
| Readiness | response/request coverage, enum/context/auth fields | Build warnings and execute preflight |
| Learning | promoted target preferences and plan paths | Low-weight ranking improvements from validated traces |

Good nodes are compact. They do not store every raw OpenAPI leaf as ranking
text. They store the fields that help the engine decide whether the tool is
the right candidate.

## Semantic Metadata

Semantic metadata is deterministic by default. The OpenAPI semantic pass derives
the most useful searchable fields without calling an LLM.

| Field | Example | Derived From |
| --- | --- | --- |
| `canonical_action` | `search`, `read`, `create`, `update`, `delete`, `action` | operation id, HTTP method, summary, description |
| `primary_resource` | `order`, `customer`, `payment` | tags, stable path segments, operation noun, schemas |
| `path_module` | `/api/v1/orders` | stable path prefix |
| `operation_group` | `orders` | tags or grouped path/module facts |
| `result_shape` | `single`, `list`, `count`, `mutation` | method, name, description, response schema |
| `semantic_confidence` | `high`, `medium`, `low` | evidence strength |

Adapters may pass aliases such as resource, action, module, context, paging, or
search field names. The library should not contain customer-specific business
dictionaries.

## IO Contract

The IO contract turns API schemas into planning evidence.

| Contract Field | Meaning |
| --- | --- |
| `consumes` | Fields the tool needs in path, query, header, cookie, or body |
| `produces` | Fields the tool can return from response body or envelope |
| `links` | Explicit or inferred producer-consumer relationships |
| `kind` | `data`, `context`, or `auth` |
| `required` | Whether the field blocks execution when missing |
| `enum` | Allowed values when the source exposes them |
| `semantic_tag` | Generic role such as paging, search filter, id, date, auth |

Contract fields are the bridge between search and execution. A query can find a
tool by text, but a plan can only run if required inputs are satisfied or can be
produced by earlier steps.

## Edge Model

Edges describe why tools should be considered together. Every graphify-style
edge is normalized through `normalize_graph_edge()` and can be merged with
`merge_graph_edges()`.

| Edge Source | Typical Relation | Strength | Used For |
| --- | --- | --- | --- |
| Structural | same source, tag, module, or path | Weak | navigation, grouping, map view |
| Name-based | similar operation names or resources | Weak to medium | candidate expansion, diagnostics |
| API contract | produced field satisfies consumed field | Strong | producer expansion, plan synthesis |
| OpenAPI link | explicit OpenAPI relationship | Strong | plan synthesis and explainability |
| Manual | operator-curated relationship | Strong | product-specific graph correction |
| Run observed | successful plan binding from traces | Suggested until promoted | trace learning and ranking hints |
| LLM curated | offline enrichment or curation | Medium unless verified | semantic grouping |

Normalized edges carry:

```json
{
  "source": "searchOrders",
  "target": "getOrderDetail",
  "relation": "requires",
  "kind": "data",
  "confidence": "INFERRED",
  "conf_score": 0.92,
  "evidence": "produces orderId consumed by getOrderDetail",
  "evidence_sources": ["api_contract"],
  "data_flow": {"from_path": "items[].orderId", "to_field": "orderId"},
  "is_manual": false
}
```

Do not treat dense structural edges as execution proof. Planning should prefer
contract, OpenAPI link, manual, and promoted trace evidence.

## Search Path

```text
query
  -> keyword and tokenizer seeds
  -> semantic/action/resource/shape scoring
  -> contract scoring
  -> graph expansion from reliable edges
  -> ranked candidates with evidence
```

<Tabs>
  <TabItem value="retrieve" label="Retrieve" default>

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
response = retrieve_graphify(
    graph,
    query="find refund-ready orders",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["name"])
print(first["score_breakdown"])
print(first["semantic_evidence"])
```

  </TabItem>
  <TabItem value="selector" label="Selector">

```python
from graph_tool_call.graphify import (
    select_target_candidate,
)

selection = select_target_candidate(
    query="find refund-ready orders",
    candidates=[
        item["name"]
        for item in response["results"]
    ],
    tools=graph.tools,
    retrieval_results=response["results"],
    llm_target=llm_intent.target,
)

print(selection["selected_target"])
print(selection["reason_codes"])
```

  </TabItem>
</Tabs>

The LLM should receive the smallest useful catalog, not the whole source file.
If the LLM names a weak target while deterministic evidence strongly favors
another candidate, the selector can record an override. If the margin is weak,
the graph should expose ambiguity instead of hiding it.

## Planning Path

Planning uses the graph after target selection. `PathSynthesizer` can inspect
producer-consumer evidence, required fields, enum requirements, context
defaults, and user input slots.

```text
selected target
  -> required consumes fields
  -> available context/defaults/user input
  -> producer expansion from data-flow edges
  -> executable Plan
  -> PlanRunner.run_stream() events
```

Failures should remain structured. A missing request field, enum choice,
ambiguous target, auth preflight failure, HTTP 4xx, and HTTP 5xx are different
conditions and should be represented as different reason codes.

## Large Graph Visualization

Large API catalogs should not render every node and edge at once. A 600-tool
catalog with thousands of structural relationships becomes unreadable when
drawn as one force-directed graph.

Use three views instead:

| View | Purpose | Render |
| --- | --- | --- |
| Map view | Understand collection structure | modules, resources, actions, orphan counts, readiness |
| Scoped graph | Inspect a chosen module/resource/target | only the selected neighborhood and high-value edges |
| Workflow path | Explain one retrieval or plan decision | target, producers, required fields, selected edges |

For visual edges, start with high-signal evidence:

- API contract data flow
- explicit OpenAPI links
- manual edges
- promoted run-observed edges
- high-confidence semantic relationships

Show structural and name-based edges as filters or summaries first. Render them
only after the user scopes down.

## Persistence And Rebuilds

Store version and provenance metadata with the artifact:

```json
{
  "graph_tool_call_version": "0.32.1",
  "collection_graph_version": 2,
  "semantic_summary": {
    "canonical_action_known_rate": 0.96,
    "primary_resource_assigned_rate": 0.88
  },
  "edge_quality_summary": {
    "total": 14569,
    "api_contract": 830,
    "manual": 12,
    "run": 4
  }
}
```

During rebuild:

1. Recompute source-derived tools, semantics, contracts, readiness, and weak
   structural edges.
2. Preserve product-owned fields such as curated `ai_metadata`,
   `context_defaults`, `enum_mappings`, manual edges, Quality Lab cases, and
   promoted learning suggestions.
3. Re-run quality gates before promoting the artifact.

## Operational Checklist

Before an adapter exposes a graph to an agent, check:

- `semantic_summary` has high action/resource/module coverage.
- `edge_quality_summary` has enough contract or curated evidence.
- `readiness_report` has no blocker issues.
- required auth/context fields are visible before execution.
- search cases have stable Top-K and Top-1 behavior.
- plan cases preserve reason codes for missing fields and auth failures.
- visualization defaults to map or scoped views for large catalogs.
- trace learning stores scrubbed evidence only and promotes suggestions
  conservatively.

## Related Pages

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Collection Artifacts](../build/collection-artifacts.md)
- [IO Contracts](../build/io-contracts.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Runner Events](../plan/runner-events.md)
- [Trace Learning](./trace-learning.md)
