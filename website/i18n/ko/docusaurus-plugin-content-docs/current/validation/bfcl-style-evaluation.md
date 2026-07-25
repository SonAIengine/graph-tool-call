---
title: BFCL 스타일 평가
description: tool-call benchmark 방법론으로 graph-tool-call을 검증하는 방식을 설명합니다.
---

# BFCL 스타일 평가

BFCL-style evaluation은 tool-call 품질에 대한 public claim을 만들 때 사용합니다.
빠른 개발 loop보다 무겁기 때문에 release candidate나 benchmark claim 업데이트
시점에 실행하는 것이 맞습니다.

## 무엇을 측정하나

- target selection correctness
- plan validity
- argument readiness
- 안전한 경우 execution outcome
- failure classification
- latency와 token context budget

## 피해야 할 것

좁은 smoke test 결과를 benchmark number처럼 공개하지 않습니다. public claim은
dataset, model, run configuration, stored result artifact와 연결되어야 합니다.

## 관련 문서

- [Benchmarks](./benchmarks.md)
- [Release Gates](./release-gates.md)
