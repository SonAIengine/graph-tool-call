---
title: Evidence Output
description: Inspect why a tool was retrieved, expanded, or selected.
---

# Evidence Output

Evidence output is the main difference between a debuggable retrieval engine and
a black-box prompt.

## What To Show In A Product UI

For each candidate, show:

- rank
- score
- score breakdown
- matched action/resource/module
- contract fields that matched
- graph expansion source
- selector reason codes

## What To Persist

Persist compact, scrubbed evidence that helps reproduce the decision. Avoid raw
request bodies, response bodies, tokens, cookies, and user identifiers.

## Related Pages

- [Tool Graph Search](./tool-graph-search.mdx)
- [Trace Learning](../concepts/trace-learning.md)
