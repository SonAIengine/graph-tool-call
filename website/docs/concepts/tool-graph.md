---
title: Tool Graph
description: Understand the graph data model that powers retrieval, candidate expansion, planning, and trace learning.
---

# Tool Graph

The tool graph is the core data structure. Each tool is a node with metadata,
and edges describe relationships that are useful for retrieval and planning.

## Node Signals

Tool nodes can include:

- name, description, tags, and source metadata
- OpenAPI method/path/operation metadata
- semantic metadata such as canonical action, primary resource, module, and
  result shape
- IO contracts for consumed and produced fields
- execution and auth readiness facts

## Edge Signals

Edges can come from:

- OpenAPI structure
- request/response data-flow contracts
- semantic relation inference
- manual curation
- run-observed trace evidence

Graph edges are not just for visualization. They power candidate expansion,
workflow discovery, and target selection diagnostics.

## Edge Kinds

| Edge Kind | Meaning | Used For |
| --- | --- | --- |
| structural | same source, tag, module, or path relationship | navigation and weak grouping |
| data flow | one tool produces a field another tool consumes | plan synthesis and producer expansion |
| semantic | action/resource similarity or curated relation | retrieval and target selection |
| manual | human-provided relation | high-trust graph evidence |
| trace | observed successful or failed run relationship | learning and future ranking |

Dense structural edges should not be treated as strong execution evidence.
Prefer contract, manual, OpenAPI link, and promoted trace edges when planning.

## Retrieval Flow

```text
query -> keyword seeds -> semantic/contract scoring -> graph expansion -> ranked candidates
```

The LLM should see the strongest, smallest candidate set instead of the whole
tool catalog.

## Large Graph Visualization

Large API graphs should not render every node and every edge at once. A useful
product UI usually needs two modes:

- **map mode** for modules, resources, actions, orphan counts, and readiness
- **scoped graph mode** for a selected module, target tool, or workflow path

The graph is primarily an evidence structure. Visualization should help users
choose a scope and inspect why a candidate is connected, not draw every
relationship as a hairball.

## Persistence

Store graph artifacts with version metadata:

```json
{
  "graph_tool_call_version": "0.32.1",
  "collection_graph_version": 2,
  "nodes": 624,
  "edges": 14569
}
```

Preserve manual and promoted learning edges during rebuild. Recompute weak
structural edges from source.

## Related Pages

- [Collection Artifacts](../build/collection-artifacts.md)
- [Candidate Expansion](../search/candidate-expansion.md)
- [Trace Learning](./trace-learning.md)
