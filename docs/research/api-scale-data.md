# 실제 API 규모 데이터

## 주요 API 실측

| API | File Size | Endpoints | Schemas | Tags | Deprecated |
|-----|-----------|-----------|---------|------|------------|
| GitHub REST | 11.31 MB | 1,079 | 911 | 45 | 31 (2.9%) |
| Kubernetes | 3.74 MB | 1,085 | 746 | 64 | 0 |
| Stripe | 3.80 MB | 587 | 1,335 | **0 (없음!)** | 6 |
| Slack | 1.18 MB | 174 | 48 | 0 | 0 |
| Twilio | 10.44 MB | ~1,000+ | ~800+ | 분산(54파일) | N/A |
| Petstore | 35 KB | 20 | 10 | 3 | 0 |

## APIs.guru 통계

- 총 API: 3,992개 (고유 2,529개)
- 총 endpoint: 108,837개
- **평균: ~43 endpoints/API**
- 200K 파일 분석 평균: ~51 endpoints, ~33 schemas, ~38 query params

## Context Window 초과 문제

| Spec | 추정 토큰 | Claude 200K 대비 |
|------|----------|-----------------|
| Slack (174 ep) | ~120K | 60% (겨우 들어감) |
| Kubernetes (1,085 ep) | ~740K | **370%** (불가) |
| Stripe (587 ep) | ~997K | **499%** (불가) |
| GitHub (1,079 ep) | ~1,672K | **836%** (불가) |

## 설계에 반영할 인사이트

1. **Stripe는 tag가 없음** → path prefix 기반 자동 categorization 필수
2. Stripe `anyOf` 1,910회 → polymorphic type 처리 필요
3. 가장 큰 request body: 60개 필드 → required만 노출 옵션
4. 가장 큰 schema: 105개 properties (GitHub `full-repository`)
5. Twilio 분산 전략 (54개 파일) → incremental ingest 지원
6. 27% API에 보안 전략 없음 → auth 처리 robust해야
