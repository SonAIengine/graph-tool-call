.PHONY: quick lint test verify release-check pypi-smoke

quick:
	scripts/quick-check.sh

lint:
	poetry run ruff check .
	poetry run ruff format --check .

test:
	poetry run pytest tests/ -q

verify: lint test

release-check:
	scripts/release-check.sh

pypi-smoke:
	scripts/pypi-smoke.sh
