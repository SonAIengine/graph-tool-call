---
title: 한글 검색
description: product-specific term을 하드코딩하지 않고 한국어/영어가 섞인 tool catalog를 검색합니다.
---

# 한글 검색

많은 enterprise catalog는 한국어 summary와 영어 operation id, field name이 섞여
있습니다. graph-tool-call은 human description과 stable technical metadata를 함께
index합니다.

## 도움이 되는 것

- 가능한 경우 Korean tokenizer extra
- 영어 operation id
- path segment
- deterministic action/resource metadata
- request/response field name
- adapter가 option으로 전달한 alias dictionary

## 예제

```python
graph.retrieve_with_scores("회원 상세 조회", top_k=8)
graph.retrieve_with_scores("member detail info", top_k=8)
```

catalog에 충분한 semantic/contract evidence가 있으면 두 query는 같은 target
family를 반환해야 합니다.

## 관련 문서

- [Semantic Build](../build/semantic-build.md)
- [Retrieval Signals](./retrieval-signals.md)
