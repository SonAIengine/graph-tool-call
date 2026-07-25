---
title: Python Functions
description: 로컬 Python function을 retrieval과 planning에 사용할 ToolSchema로 변환합니다.
---

# Python Functions

Python function ingestion은 API spec이 아니라 application code에서 tool catalog를
만들 때 유용합니다.

## Use Cases

- 내부 automation function
- test fixture
- 빠른 실험
- non-HTTP system을 감싼 custom adapter

## Contract Guidance

Function tool은 signature와 docstring이 아래 내용을 설명할수록 잘 동작합니다.

- required argument
- optional argument
- return shape
- failure behavior
- side effect

이 정보가 retrieval과 planning evidence가 됩니다.

## 관련 문서

- [Mental Model](../getting-started/mental-model.md)
- [Tool Graph Search](/docs/search/tool-graph-search/)
