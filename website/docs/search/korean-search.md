---
title: Korean Search
description: Search mixed Korean and English tool catalogs without hard-coding product-specific terms.
---

# Korean Search

Many enterprise catalogs use Korean summaries with English operation ids and
field names. graph-tool-call indexes both the human descriptions and the stable
technical metadata.

## What Helps

- Korean tokenizer extra when available
- English operation ids
- path segments
- deterministic action/resource metadata
- request and response field names
- alias dictionaries passed by the adapter

## Example

```python
graph.retrieve_with_scores("회원 상세 조회", top_k=8)
graph.retrieve_with_scores("member detail info", top_k=8)
```

Both queries should return the same target family when the catalog has enough
semantic and contract evidence.

## Related Pages

- [Semantic Build](../build/semantic-build.md)
- [Retrieval Signals](./retrieval-signals.md)
