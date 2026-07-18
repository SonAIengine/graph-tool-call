.PHONY: quick lint test verify research-check research-check-unit research-check-deterministic research-check-smoke xgen-benchmark xgen-llm-benchmark bfcl-benchmark bfcl-llm-benchmark bfcl-sweep bfcl-failure-subset release-check pypi-smoke

quick:
	scripts/quick-check.sh

lint:
	poetry run ruff check .
	poetry run ruff format --check .

test:
	poetry run pytest tests/ -q

verify: lint test

research-check:
	scripts/research-check.sh deterministic

research-check-unit:
	scripts/research-check.sh unit

research-check-deterministic:
	scripts/research-check.sh deterministic

research-check-smoke:
	scripts/research-check.sh smoke

xgen-benchmark:
	poetry run python -m benchmarks.xgen_tool_graph.run

xgen-llm-benchmark:
	poetry run python -m benchmarks.xgen_tool_graph.llm_loop --model qwen3:4b

bfcl-benchmark:
	poetry run python -m benchmarks.bfcl_tool_selection.run --limit 50

bfcl-llm-benchmark:
	poetry run python -m benchmarks.bfcl_tool_selection.llm_loop --categories simple_python --limit 5 --model qwen3:4b

bfcl-sweep:
	poetry run python -m benchmarks.bfcl_tool_selection.sweep --categories simple_python --limit 5 --top-ks 3,5 --model qwen3:4b

bfcl-failure-subset:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-failure-subset REPORT=/tmp/report.json [OUT=/tmp/case_ids.txt]" && exit 2)
	poetry run python -m benchmarks.bfcl_tool_selection.failures --report "$(REPORT)" --output "$${OUT:-/tmp/gtc-bfcl-failure-case-ids.txt}"

release-check:
	scripts/release-check.sh

pypi-smoke:
	scripts/pypi-smoke.sh
