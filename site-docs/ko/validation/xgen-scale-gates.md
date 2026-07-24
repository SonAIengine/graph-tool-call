# XGEN Scale Gates

XGEN scale gate는 대형 API collection snapshot을 replay해서 realistic catalog size에서
변경사항을 평가합니다.

## Gate 예시

- selector exact hit rate
- average candidate count
- max candidate count
- schema context reduction
- semantic action/resource/module coverage
- uncaught error count

## 실행 시점

- 일반적인 retrieval/selector 변경에는 saved snapshot replay를 사용합니다.
- OpenAPI ingest, search, semantic, plan synthesis logic이 바뀌면 live scale sweep을
  실행합니다.
- full LLM E2E는 release candidate 또는 public benchmark 갱신 때만 실행합니다.

