---
title: Release Gate
description: local development, release candidate, public claim에 맞는 검증 깊이를 정합니다.
---

# Release Gate

Release gate는 개발 속도를 유지하면서 package quality와 public claim을
보호하기 위한 기준입니다. 바꾼 코드가 깨뜨릴 가능성이 있는 범위를 잡을 수
있는 가장 싼 검증부터 돌리고, release 직전에는 gate를 넓힙니다.

## Gate level

| Level | 언제 | Command |
| --- | --- | --- |
| Fast loop | graphify/search/plan code 수정 중 | `make quick` |
| Focused test | 특정 기능 영역 수정 | `poetry run pytest tests/test_*.py -q` |
| Website | docs site 수정 | `cd website && npm run typecheck && npm run build` |
| Full library | merge/release candidate 전 | `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run pytest tests/ -q` |
| Release candidate | PyPI 배포 전 | `make release-check` |
| Public claim | README/docs benchmark 숫자 갱신 전 | deterministic benchmark와 저장 artifact, 필요 시 LLM run |

## Fast loop

```bash
make quick
```

구현 중에는 이 gate를 먼저 사용합니다. graphify, retrieval, selector, plan,
runner public contract가 깨지는지를 빠르게 잡는 용도입니다.

## Full library gate

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run pytest tests/ -q
```

trivial하지 않은 code change는 review 요청 전에 이 gate를 통과시키세요.

## Release candidate gate

```bash
make release-check
make pypi-smoke
```

release candidate는 public import와 package build 결과까지 확인해야 합니다.

## Public benchmark gate

public quality claim을 갱신할 때는 다음이 포함되어야 합니다.

- dataset 또는 fixture id
- graph-tool-call version
- LLM을 쓴 경우 model/provider
- run configuration
- timestamp
- raw result artifact
- summary metric

재현할 수 없는 수치는 공식 문서에 넣지 않습니다.

## 하지 말아야 할 것

- 작은 수정마다 5시간짜리 LLM benchmark를 돌리지 않습니다.
- CI가 red인 상태에서 PyPI 배포하지 않습니다.
- local ad-hoc output으로 README 수치를 바꾸지 않습니다.
- search 성공을 execute readiness의 증거로 착각하지 않습니다.

## 관련 문서

- [Benchmark](./benchmarks.md)
- [Quality Lab](./quality-lab.md)
- [XGEN Scale Gate](./xgen-scale-gates.md)
- [BFCL 스타일 평가](./bfcl-style-evaluation.md)
