---
title: Release Gate
description: local development, release candidate, public claim에 맞는 validation depth를 선택합니다.
---

# Release Gate

Release gate는 개발 속도를 지키면서 public quality claim을 보호합니다.

## Fast Loop

core retrieval, graphify, plan code를 수정하는 동안 실행합니다.

```bash
make quick
```

## Release Candidate

새 package를 배포하기 전에 실행합니다.

```bash
make release-check
```

## Public Benchmark Claim

README나 documentation claim을 갱신할 때만 full benchmark configuration을
실행합니다. dataset, model, configuration, result artifact를 저장합니다.

## 관련 문서

- [Benchmarks](./benchmarks.md)
- [BFCL-Style Evaluation](./bfcl-style-evaluation.md)
