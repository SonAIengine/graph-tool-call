# Release Checklist

릴리즈는 현재 `자동 생성`이 아니라 `체계적으로 수동 관리`하는 방식이다.
기준 문서는 [`CHANGELOG.md`](../CHANGELOG.md)와 이 체크리스트다.

## 원칙

1. 기능 개발이 끝나면 먼저 `CHANGELOG.md`의 `Unreleased`에 추가한다.
2. 문서 반영이 끝나면 README/API 예시와 실제 공개 API를 다시 대조한다.
3. 릴리즈 직전 테스트를 한 번에 실행하고 결과를 기록한다.
4. 버전 태그를 만들 때 `Unreleased` 내용을 새 버전 섹션으로 내린다.

## 릴리즈 전 체크

- `poetry run pytest -q`
- `poetry run ruff check .`
- README 계열에 신규 공개 API 반영 확인
- optional extras 변경 확인
- `CHANGELOG.md` `Unreleased` 정리
- 버전 번호 확인: [`pyproject.toml`](../pyproject.toml), [`graph_tool_call/__init__.py`](../graph_tool_call/__init__.py)

## 릴리즈 노트 작성 흐름

1. `CHANGELOG.md`의 `Unreleased`를 기준으로 Added / Changed / Fixed를 다듬는다.
2. 새 버전 헤더를 추가한다. 예: `## [0.8.0] - 2026-03-12`
3. 비교 링크를 갱신한다.
4. GitHub Release 본문도 같은 내용을 사용한다.

## 자동화 범위

현재 저장소에는 `CHANGELOG.md`를 자동 생성하거나 Git 태그로 자동 릴리즈 노트를 만드는 CI는 없다.
즉, 지금 구조는 `알아서 관리된다`기보다 `놓치기 어렵게 관리된다`에 가깝다.

원하면 다음 단계로는 아래 둘 중 하나를 추가할 수 있다.

- `scripts/release.py`로 `Unreleased -> version section` 자동 정리
- GitHub Actions로 태그 시 릴리즈 초안 생성

## 현재 자동화

이제 아래 두 경로가 추가되었다.

- `python scripts/release.py prepare --version 0.8.0 --date 2026-03-12`
  - `CHANGELOG.md`
  - `pyproject.toml`
  - `graph_tool_call/__init__.py`
  를 함께 갱신한다.
- `.github/workflows/release-draft.yml`
  - `v*` 태그 푸시 시 `CHANGELOG.md`의 `Unreleased` 기준으로 draft release 본문을 생성한다.

즉, 릴리즈 노트는 이제 `완전 자동 생성`은 아니지만,
`Unreleased`만 제대로 유지하면 draft 생성과 버전 반영은 자동화할 수 있다.
