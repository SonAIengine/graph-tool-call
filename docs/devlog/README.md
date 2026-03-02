# Development Log

graph-tool-call 개발 과정과 의사결정을 기록하는 devlog.

## Issues (X2BEE BO API 1,077 endpoints 적용 결과)

| # | 이슈 | 원인 | 해결 방향 |
|---|------|------|-----------|
| 1 | Edge 폭발 (경로 유사도) | 스펙 품질 — /bo/ prefix 공유 | ai-api-lint (별도 프로젝트) |
| 2 | requestBody 누락 | 스펙 품질 — POST에 body 미정의 | ai-api-lint (별도 프로젝트) |
| 3 | 한글 BM25 검색 부진 | 합성어 단일 토큰화 | graph-tool-call 한글 bigram |
| 4 | Malformed parameter | name 필드 누락 | graph-tool-call 테스트 추가 |

## Entries

- [2026-03-03-annotation](./2026-03-03-annotation.md) — MCP Annotation-Aware Retrieval 구현 (Phase 2.5)
- [2026-03-03](./2026-03-03.md) — Day 1: 방향 전환, ai-api-lint 분리, graph-tool-call 범용 개선
