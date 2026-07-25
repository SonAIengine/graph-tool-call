---
title: Quality Lab
description: production 사용 전에 collection 단위 search, plan, execute case를 실행합니다.
---

# Quality Lab

Quality Lab은 API collection을 위한 product-facing validation layer입니다. 반복
가능한 case를 search, target selection, plan synthesis, optional execution으로
실행합니다.

## Case Modes

| Mode | Purpose |
| --- | --- |
| `search` | retrieval과 Top-K behavior 확인 |
| `plan` | target selection과 plan synthesis 확인 |
| `execute` | 안전한 경우 adapter를 통해 plan 실행 |

## Execute Safety

Mutating execute case는 아래 조건을 요구해야 합니다.

- explicit mutation allowance
- dev host allowlist
- cleanup steps
- assertions
- structured failure recording

## 관련 문서

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [XGEN Quality Lab](../integrations/xgen-quality-lab.md)
