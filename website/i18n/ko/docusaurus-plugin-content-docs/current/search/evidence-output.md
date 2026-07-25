---
title: Evidence 출력
description: tool이 왜 검색, 확장, 선택됐는지 확인합니다.
---

# Evidence 출력

Evidence output은 debuggable retrieval engine과 black-box prompt를 나누는 핵심입니다.

## Product UI에 보여줄 것

candidate별로 아래를 보여주는 것이 좋습니다.

- rank
- score
- score breakdown
- matched action/resource/module
- matched contract field
- graph expansion source
- selector reason code

## 무엇을 저장하나

decision을 재현하는 데 필요한 compact, scrubbed evidence만 저장합니다. raw request
body, response body, token, cookie, user identifier는 저장하지 않습니다.

## 관련 문서

- [Tool Graph Search](./tool-graph-search.mdx)
- [Trace Learning](../concepts/trace-learning.md)
