# 도구 그래프

도구 그래프는 핵심 데이터 구조입니다. 각 tool은 metadata를 가진 node이고,
edge는 retrieval과 planning에 필요한 관계를 설명합니다.

## Node Signal

Tool node에는 다음 정보가 들어갈 수 있습니다.

- name, description, tag, source metadata
- OpenAPI method/path/operation metadata
- canonical action, primary resource, module, result shape 같은 semantic metadata
- consumed/produced field에 대한 IO contract
- execution/auth readiness 정보

## Edge Signal

Edge는 다음 출처에서 생깁니다.

- OpenAPI 구조
- request/response data-flow contract
- semantic relation inference
- manual curation
- run-observed trace evidence

Graph edge는 시각화용 장식이 아닙니다. candidate expansion, workflow discovery,
target selection diagnostics에 직접 사용됩니다.

## Retrieval 흐름

```text
query -> keyword seeds -> semantic/contract scoring -> graph expansion -> ranked candidates
```

LLM에는 전체 tool catalog가 아니라 가장 강한 작은 후보 집합이 전달되어야 합니다.

