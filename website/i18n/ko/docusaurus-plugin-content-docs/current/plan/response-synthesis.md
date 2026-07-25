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

## 출력 계약

Response synthesis는 마지막 사용자-facing 단계입니다. 실행 상태를 보존하는
유일한 위치가 되어서는 안 됩니다.

| Input | 보존 목적 | 메모 |
| --- | --- | --- |
| `requirement` | 사용자 요청 context | rewrite된 추측이 아니라 원 요청을 사용 |
| `result` | success summary | 큰 payload는 먼저 project/compress |
| `failed_step` | 실패 위치 | 가능하면 stable step id 사용 |
| `error.reason_code` | product diagnostic | final answer와 함께 구조화된 code 보존 |
| `partial_results` | 유용한 중간 결과 | scrub된 non-sensitive summary만 포함 |

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
- 같은 trace metadata를 log/SSE에도 전달해 final answer를 audit할 수 있게 합니다.

## Deterministic fallback

결과가 strict JSON이어야 하거나, compliance상 승인된 문구만 써야 하거나, 실패
reason만으로 이미 조치가 명확한 경우에는 LLM synthesis 대신 template을 씁니다.

```python
if response_format == "json" or error.reason_code in {"auth_failed", "auth_context_required"}:
    return deterministic_response(trace)

return synthesize_failure_response(..., llm=llm)
```

핵심 규칙은 단순합니다. synthesis는 답을 읽기 쉽게 만들 수는 있지만, 없는 total을
만들거나, 실패 stage를 숨기거나, 구조화된 reason을 모호한 사과문으로 바꾸면 안
됩니다.

## 품질 체크

실제 integration에서는 success/failure answer가 아래를 보존하는지 확인합니다.

- selected target tool
- `plan_id`와 failed step
- structured failure의 reason code
- large payload truncation limit
- raw token, cookie, phone number, internal id가 없는지

## 사용하지 않는 경우

제품이 이미 strict response format을 갖고 있거나, 결과가 machine-readable JSON이어야
하거나, compliance policy상 deterministic template이 필요한 경우에는 response
synthesis를 건너뜁니다.

## 관련 문서

- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Event Schemas](../reference/event-schemas.md)
