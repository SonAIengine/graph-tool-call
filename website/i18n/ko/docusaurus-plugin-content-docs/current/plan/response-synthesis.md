---
title: 응답 합성
description: tool execution 이후 structured success/failure response를 생성합니다.
---

# 응답 합성

Response synthesis는 plan과 runner output을 최종 assistant-facing answer로
변환합니다. failure reason과 evidence를 숨기지 않고 보존해야 합니다.

## Public Helpers

```python
from graph_tool_call.plan import (
    synthesize_failure_response,
    synthesize_success_response,
)
```

## Guidance

- raw API payload handling은 adapter에 둡니다.
- final response generation은 stage, failed step, reason code를 알아야 합니다.
- debugging을 위해 `plan_id`와 trace metadata를 보존합니다.

## 관련 문서

- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
