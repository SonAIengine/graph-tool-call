---
title: 응답 합성
description: tool execution 이후 structured success/failure response를 생성합니다.
---

# 응답 합성

Response synthesis는 plan과 runner output을 최종 assistant-facing answer로
변환합니다. 사용자가 요청한 내용, 실행한 단계, 실패 지점, reason-code evidence를
숨기지 않고 요약해야 합니다.

Helper는 `OntologyLLM` interface를 사용합니다. 어떤 provider와 model을 쓸지는
adapter가 결정합니다.

## Public Helpers

```python
from graph_tool_call.plan import (
    synthesize_failure_response,
    synthesize_success_response,
)
```

## Success Response

```python
answer = synthesize_success_response(
    requirement="회원 배송지를 조회해줘",
    result=trace.output,
    llm=llm,
    result_char_limit=4000,
)
```

Success prompt는 count 표현을 조심합니다. API result가 truncate되어 있고 명시적인
total field가 없다면 모델이 절대 개수를 단정하지 않아야 합니다.

## Failure Response

```python
answer = synthesize_failure_response(
    requirement="회원 배송지를 조회해줘",
    failed_step=trace.failed_step or "unknown",
    error={"reason_code": "auth_failed", "message": "HTTP 403"},
    partial_results=[step.output for step in trace.steps if step.error is None],
    llm=llm,
)
```

Failure response는 아래를 설명해야 합니다.

- 사용자가 요청한 것
- 시도한 것
- 실패한 위치
- plain-language reason
- 명확한 다음 조치가 있다면 그 조치

## Adapter Guidance

- raw API payload handling은 adapter에 둡니다.
- final response generation은 stage, failed step, reason code를 알아야 합니다.
- debugging을 위해 `plan_id`와 trace metadata를 보존합니다.
- 큰 API payload는 project/compress합니다.
- sensitive value는 scrub합니다.

## 사용하지 않는 경우

제품이 이미 strict response format을 갖고 있거나, 결과가 machine-readable JSON이어야
하거나, compliance policy상 deterministic template이 필요한 경우에는 response
synthesis를 건너뜁니다.

## 관련 문서

- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Event Schemas](../reference/event-schemas.md)
