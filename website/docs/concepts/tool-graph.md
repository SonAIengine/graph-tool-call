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

## Retrieval Flow

```text
query -> keyword seeds -> semantic/contract scoring -> graph expansion -> ranked candidates
```

The LLM should see the strongest, smallest candidate set instead of the whole
tool catalog.

