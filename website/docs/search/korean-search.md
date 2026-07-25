---
title: Korean Search
description: Search mixed Korean and English tool catalogs without hard-coding product-specific terms.
---

# Korean Search

Many enterprise catalogs use Korean summaries with English operation ids and
field names. graph-tool-call indexes both the human descriptions and the stable
technical metadata.

The goal is not to hard-code Korean business terms in the engine. The engine
should expose product-neutral metadata and accept optional aliases from the
adapter.

## Installation

Use the Korean extra when you want stronger tokenization for Korean-heavy
catalogs.

```bash
pip install "graph-tool-call[korean]"
```

The library still works without this extra, but mixed Korean/English queries may
lean more heavily on operation ids, path segments, and semantic metadata.

## Minimal Example

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")

ko = graph.retrieve_with_scores("회원 상세 조회", top_k=8)
en = graph.retrieve_with_scores("member detail info", top_k=8)

print([item.tool.name for item in ko[:3]])
print([item.tool.name for item in en[:3]])
```

Both queries should return the same target family when the catalog has enough
semantic and contract evidence.

## What Helps

- Korean tokenizer extra when available
- English operation ids
- path segments
- deterministic action/resource metadata
- request and response field names
- alias dictionaries passed by the adapter

## Alias Policy

Aliases should be supplied by the adapter or collection configuration:

```python
semantic_options = {
    "resource_aliases": {
        "회원": "member",
        "주문": "order",
    },
    "action_aliases": {
        "조회": "search",
        "상세": "read",
    },
}
```

Do not add XGEN, BO, or domain-specific dictionaries directly to the library.

## Query Patterns

| User Query | Expected Signal |
| --- | --- |
| `회원 상세 조회` | `primary_resource=member`, `result_shape=single` |
| `주문 목록 검색` | `primary_resource=order`, `canonical_action=search`, `result_shape=list` |
| `쿠폰 개수` | `result_shape=count` |
| `claim cancel reason` | English operation/path tokens plus resource/action metadata |

## Failure Modes

| Symptom | Likely Cause | What To Check |
| --- | --- | --- |
| Korean query only matches generic tools | summaries are noisy or missing | `one_line_summary`, `when_to_use` |
| English operation id wins over Korean intent | missing action/resource aliases | semantic options and metadata |
| detail query returns list tool | missing `result_shape` | semantic build output |
| every query matches the same module | path/module cluster too large | `path_module`, readiness report |

## Validation

Keep paired Korean/English cases for the same target family:

```json
[
  {"query": "회원 상세 조회", "expected": "getMemberDetail"},
  {"query": "member detail info", "expected": "getMemberDetail"}
]
```

Track Top-1, Top-3, Top-8, and sibling mismatch rate. For product validation,
save evidence output for every miss so the fix can target metadata, aliases, or
contract extraction rather than prompt wording.

## Related Pages

- [Semantic Build](../build/semantic-build.md)
- [Retrieval Signals](./retrieval-signals.md)
- [Search Tuning](./search-tuning.md)
