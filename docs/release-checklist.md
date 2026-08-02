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
- `poetry run ruff format --check .`
- `make public-smoke`
- `make launch-evidence-check`
- README 계열에 신규 공개 API 반영 확인
- optional extras 변경 확인
- `CHANGELOG.md` `Unreleased` 정리
- 버전 번호 확인: [`pyproject.toml`](../pyproject.toml), [`graph_tool_call/__init__.py`](../graph_tool_call/__init__.py)

## 릴리즈 노트 작성 흐름

1. `CHANGELOG.md`의 `Unreleased`를 기준으로 Added / Changed / Fixed를 다듬는다.
2. 새 버전 헤더를 추가한다. 예: `## [0.8.0] - 2026-03-12`
3. 비교 링크를 갱신한다.
4. GitHub Release 본문도 같은 내용을 사용한다.

## 현재 자동화

이제 아래 두 경로가 추가되었다.

- `python scripts/release.py prepare --version 0.8.0 --date 2026-03-12`
  - `CHANGELOG.md`
  - `pyproject.toml`
  - `graph_tool_call/__init__.py`
  를 함께 갱신한다.
- `.github/workflows/release-draft.yml`
  - `v*` 태그 푸시 시 `CHANGELOG.md`의 `Unreleased` 기준으로 draft release 본문을 생성한다.
- `.github/workflows/publish.yml`
  - published GitHub Release의 tag와 package version을 대조한다.
  - 일치하는 wheel/sdist를 build한 뒤 trusted publishing으로 PyPI에 올린다.
- `.github/workflows/ci.yml`
  - clean wheel에서 public demo와 예제를 실행한다.
  - 공개 benchmark artifact가 현재 engine/fixture와 같은지 검증한다.

즉, `Unreleased`와 version metadata를 정확히 유지하면 draft, package build,
public smoke, evidence check, PyPI publishing까지 같은 release chain으로 검증된다.
