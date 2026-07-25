---
title: 학습 제안
description: scrub된 execution trace를 collection-scoped learning suggestion으로 변환합니다.
---

# 학습 제안

Learning suggestion은 검증된 trace에서 도출한 graph/search 개선 후보입니다.

## Suggestion Types

- `target_preference`
- `plan_path`
- `data_flow_edge`
- `field_mapping`
- `context_default_candidate`
- `enum_mapping_candidate`

## Public API

```python
from graph_tool_call.learning import (
    build_trace_learning_record,
    derive_learning_suggestions,
)

record = build_trace_learning_record(...)
suggestions = derive_learning_suggestions([record])
```

## 관련 문서

- [Scrubbing](./scrubbing.md)
- [Shadow And Promotion](./shadow-promotion.md)
