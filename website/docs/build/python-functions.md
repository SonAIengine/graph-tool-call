---
title: Python Functions
description: Turn local Python functions into ToolSchema objects for retrieval and planning.
---

# Python Functions

Python function ingestion is useful when the tool catalog comes from local
application code rather than an API spec.

It converts callables into `ToolSchema` objects using function names, type hints,
signatures, and the first docstring line. This path is intentionally lightweight:
use it for local tools and tests, not for rich OpenAPI-style contract discovery.

## Minimal Example

```python
from graph_tool_call import ToolGraph

def lookup_customer(customer_id: str, include_orders: bool = False) -> dict:
    """Look up a customer profile."""
    return {}

def search_orders(customer_id: str, status: str | None = None) -> list[dict]:
    """Search orders for a customer."""
    return []

graph = ToolGraph()
tools = graph.ingest_functions([lookup_customer, search_orders])

for tool in tools:
    print(tool.name, tool.description)
```

The function name becomes the tool name. The first docstring line becomes the
description. Parameters without defaults are required.

## When To Use This

- internal automation functions
- test fixtures
- quick experiments
- custom adapters around non-HTTP systems
- local evaluation datasets

For large HTTP API collections, prefer [OpenAPI Ingestion](./openapi-ingestion.md)
so request/response contracts, auth, content types, and schema evidence can be
preserved.

## Extraction Rules

| Source | Extracted As |
| --- | --- |
| `fn.__name__` | `ToolSchema.name` |
| first non-empty docstring line | `ToolSchema.description` |
| Python signature | tool parameters |
| type hints | JSON-schema-like primitive parameter types |
| missing default value | `required=True` |

`*args`, `**kwargs`, `self`, and `cls` are ignored.

## Contract Guidance

Function tools work best when their signatures and docstrings describe:

- required arguments
- optional arguments
- return shape
- failure behavior
- side effects

Those fields become retrieval and planning evidence.

Example docstring style:

```python
def cancel_order(order_id: str, reason: str) -> dict:
    """Cancel an order and return cancellation status."""
```

## Limits

Python function ingestion does not automatically know:

- response schema leaves
- HTTP method or path
- auth requirement
- paging semantics
- enum label mappings
- external side-effect safety

If those details matter, add metadata after ingestion or build the catalog from
a richer source.

## Validation

Use `retrieve_with_scores()` to confirm that function names and docstrings are
enough for your expected queries:

```python
results = graph.retrieve_with_scores("cancel an order", top_k=3)
print([(row.tool.name, row.score) for row in results])
```

For planning workflows, add IO contract metadata manually or through an adapter
so producer/consumer relationships are visible to `PathSynthesizer`.

## Related Pages

- [Mental Model](../getting-started/mental-model.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
- [IO Contracts](./io-contracts.md)
- [Direct API](../integrations/direct-api.md)
