# 2026-03-03 — MCP Annotation-Aware Retrieval 구현

## 배경

논문 Tier 1 contribution 중 "MCP Annotation-Aware Retrieval" 구현 완료.
기존 retrieval의 3-source wRRF(BM25 + Graph + Embedding)에 MCP annotation을 4번째 signal로 추가.

## 핵심 설계 결정

### 1. Zero-LLM Intent Classifier
- LLM 없이 키워드 사전 매칭으로 query intent 분류
- 한/영 양쪽 지원 (조회/생성/삭제 키워드)
- 이유: core 철학 "LLM 없이 동작, 있으면 더 좋아짐" 유지

### 2. Annotation Weight = 0.2
- wRRF에서 BM25/Graph/Embedding은 weight 1.0, annotation은 0.2
- Annotation은 tiebreaker 역할 — 주 ranking을 바꾸지 않고 미세 조정
- BM25 rank 1 ≈ 0.016, annotation rank 1 ≈ 0.003 (약 20%)

### 3. OpenAPI에서 annotation 자동 추론
- HTTP method → MCP annotation 매핑 (RFC 7231 기반)
- MCP source 없이도 annotation-aware retrieval 동작
- GET → readOnly, DELETE → destructive 등

### 4. Noise 방지
- Neutral intent (키워드 미매칭) → annotation scoring 건너뜀
- Annotation 없는 도구 → neutral score → wRRF에서 제외
- Hard mismatch (write + readOnly) → 0.0 score로 명확한 penalty

## 구현 요약

| Step | 파일 | 내용 |
|------|------|------|
| 1 | `core/tool.py` | `MCPAnnotations` 모델, `ToolSchema.annotations`, `parse_mcp_tool()` |
| 2 | `ingest/openapi.py` | HTTP method → annotation 추론 (`_infer_annotations()`) |
| 3 | `ingest/mcp.py` (신규) | MCP tool list ingest |
| 4 | `retrieval/intent.py` (신규) | `QueryIntent` + `classify_intent()` |
| 5 | `retrieval/annotation_scorer.py` (신규) | `score_annotation_match()` |
| 6 | `retrieval/engine.py` | 4-source wRRF 통합 |
| 7 | builder/similarity/init | annotation 저장, 보너스, export |

## 테스트 결과

- 기존 181 → **255 테스트** (74개 신규, 6개 파일)
- 모든 기존 테스트 통과 (regression 없음)
- E2E: "삭제" query → destructive 도구 상위 랭크 확인

## 논문 관점

- **Novelty**: annotation을 retrieval signal로 사용하는 최초 연구
- **Contribution**: behavioral semantics + intent alignment이 precision 향상
- 추후 실험: Petstore/GitHub 대규모 spec에서 정량 평가 (Precision@K, NDCG 개선)
