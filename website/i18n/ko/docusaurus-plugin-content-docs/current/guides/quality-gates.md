# 품질 게이트

품질 게이트는 search와 planning 개선을 감이 아니라 수치로 보게 해줍니다.

## 개발 루프

구현 중에는 빠른 deterministic check를 먼저 사용합니다.

```bash
make quick
poetry run pytest tests/test_graphify_metadata.py tests/test_openapi_readiness.py -q
```

OpenAPI ingest, retrieval, selector, plan logic이 크게 바뀔 때만 더 큰 OpenAPI와
LLM 검증을 돌립니다.

## 권장 Gate

대형 OpenAPI collection에서는 다음을 봅니다.

- semantic action known rate
- primary resource assigned rate
- path/module assigned rate
- search Hit@K
- plan target hit rate
- execute read success rate
- structured failure classification rate
- uncaught server error count

목표는 모든 API call을 CI에서 성공시키는 것이 아닙니다. 모든 성공과 실패가 설명
가능하게 남는 것이 목표입니다.

