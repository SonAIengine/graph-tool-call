---
title: 실패 분류
description: search, target, plan, auth, request, API, cleanup failure를 분류합니다.
---

# 실패 분류

실패는 구조화되어야 합니다. product는 모든 실패를 "agent 실패" 하나로 뭉개면
안 됩니다.

## Common Classes

| Class | Examples |
| --- | --- |
| Search failure | no candidates, low confidence, target not in Top-K |
| Target failure | LLM target mismatch, ambiguous target |
| Plan failure | unsatisfied field, enum required, cycle |
| Auth readiness | auth context required, auth profile missing |
| API auth | downstream API의 401 또는 403 |
| HTTP failure | auth 준비 이후 4xx 또는 5xx |
| Cleanup failure | mutating test cleanup 실패 |

## 왜 중요한가

각 class는 수정 방법이 다릅니다. Search failure는 catalog evidence를 고쳐야 하고,
auth readiness failure는 adapter 설정을 봐야 하며, HTTP failure는 API나 request를
조사해야 합니다.

## 관련 문서

- [Auth Readiness](../build/auth-readiness.md)
- [Quality Lab](../validation/quality-lab.md)
