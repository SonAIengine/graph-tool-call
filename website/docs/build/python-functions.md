---
title: Python Functions
description: Turn local Python functions into ToolSchema objects for retrieval and planning.
---

# Python Functions

Python function ingestion is useful when the tool catalog comes from local
application code rather than an API spec.

## Use Cases

- internal automation functions
- test fixtures
- quick experiments
- custom adapters around non-HTTP systems

## Contract Guidance

Function tools work best when their signatures and docstrings describe:

- required arguments
- optional arguments
- return shape
- failure behavior
- side effects

Those fields become retrieval and planning evidence.

## Related Pages

- [Mental Model](../getting-started/mental-model.md)
- [Tool Graph Search](/docs/search/tool-graph-search/)
