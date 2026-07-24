# Trace 학습 루프

Trace learning loop는 LLM을 fine-tuning하지 않고 실행 이력으로 retrieval과 planning을
개선합니다.

## 정책

기본 정책은 다음입니다.

```text
observe -> shadow -> promote
```

성공 1회는 evidence로 저장할 뿐 운영 ranking truth로 즉시 믿지 않습니다. 반복 성공
또는 Quality Lab 검증을 거치면 승격할 수 있습니다.

## 저장하는 것

Learning record는 scrub된 compact fact만 저장합니다.

- normalized query와 attempt chain
- selected target과 LLM target
- plan path
- 성공 또는 실패 reason
- latency와 selector signal
- 파생 trace edge

raw request/response body, token, cookie, API key, 명백한 개인정보는 저장하지 않습니다.

## 어떻게 좋아지는가

승격된 suggestion은 낮은 가중치의 evidence로 반영됩니다.

- target preference
- 성공한 plan path
- field mapping
- data-flow edge
- context/enum mapping candidate

