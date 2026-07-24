# XGEN 통합

XGEN은 `graph-tool-call`을 product-neutral engine으로 다루는 것이 좋습니다.

## 경계

`graph-tool-call`이 담당합니다.

- OpenAPI ingest와 contract extraction
- semantic metadata
- graph edge normalization과 evidence
- retrieval과 target selection
- plan synthesis diagnostics
- scrub된 trace learning record

XGEN이 담당합니다.

- DB 저장
- auth profile과 user/session context
- API collection UX
- SSE/log forwarding
- 실제 HTTP 실행 정책
- provider/model 선택

## API Collection Build

API collection을 build할 때 XGEN은 다음을 저장하는 것이 좋습니다.

- `graph_tool_call_version`
- `collection_graph_version`
- `semantic_summary`
- `edge_quality_summary`
- `readiness_report`
- operation `metadata.openapi`
- operation `metadata.api_contract`

## Runtime

Runtime에서는 다음 순서를 권장합니다.

1. evidence와 함께 candidate를 retrieve합니다.
2. selector-ranked candidate를 LLM에 넘깁니다.
3. `select_target_candidate`로 LLM target을 guard합니다.
4. plan을 합성합니다.
5. auth readiness를 preflight합니다.
6. 실행하고 scrub된 trace evidence를 저장합니다.

