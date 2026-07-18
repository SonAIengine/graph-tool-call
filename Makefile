.PHONY: quick lint test verify research-check research-check-unit research-check-deterministic research-check-smoke xgen-benchmark xgen-llm-benchmark xgen-scale-acceptance xgen-scale-sweep xgen-scale-contract-ablation bfcl-benchmark bfcl-llm-benchmark bfcl-sweep bfcl-failure-subset bfcl-inspect-failures release-check pypi-smoke

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

xgen-scale-acceptance:
	poetry run python -m benchmarks.xgen_api_scale.run \
		--swagger-url "$${SWAGGER_URL:-https://api-bo.x2bee.com/api/bo/swagger-ui/index.html}" \
		--output "$${OUT:-/tmp/gtc-xgen-scale-acceptance.json}"

xgen-scale-sweep:
	poetry run python -m benchmarks.xgen_api_scale.run \
		--swagger-url "$${SWAGGER_URL:-https://api-bo.x2bee.com/api/bo/swagger-ui/index.html}" \
		--top-ks "$${TOP_KS:-3,5,10}" \
		--acceptance-top-k "$${ACCEPTANCE_TOP_K:-10}" \
		--output "$${OUT:-/tmp/gtc-xgen-scale-sweep.json}"

xgen-scale-contract-ablation:
	poetry run python -m benchmarks.xgen_api_scale.run \
		--swagger-url "$${SWAGGER_URL:-https://api-bo.x2bee.com/api/bo/swagger-ui/index.html}" \
		--compare-contract-signals \
		--context-fields "$${CONTEXT_FIELDS:-siteNo,langCd,sysGbCd}" \
		--output "$${OUT:-/tmp/gtc-xgen-scale-contract-ablation.json}"

bfcl-benchmark:
	poetry run python -m benchmarks.bfcl_tool_selection.run --limit 50

bfcl-llm-benchmark:
	poetry run python -m benchmarks.bfcl_tool_selection.llm_loop --categories simple_python --limit 5 --model qwen3:4b

bfcl-sweep:
	poetry run python -m benchmarks.bfcl_tool_selection.sweep --categories simple_python --limit 5 --top-ks 3,5 --model qwen3:4b

bfcl-failure-subset:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-failure-subset REPORT=/tmp/report.json [OUT=/tmp/case_ids.txt]" && exit 2)
	poetry run python -m benchmarks.bfcl_tool_selection.failures --report "$(REPORT)" --output "$${OUT:-/tmp/gtc-bfcl-failure-case-ids.txt}"

bfcl-inspect-failures:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-inspect-failures REPORT=/tmp/report.json [OUT=/tmp/inspect.json] [TOP_K=5] [INSPECT_DEPTH=20]" && exit 2)
	poetry run python -m benchmarks.bfcl_tool_selection.inspect --report "$(REPORT)" --top-k "$${TOP_K:-5}" --inspect-depth "$${INSPECT_DEPTH:-20}" --tool-sources "$${TOOL_SOURCES:-retrieved}" --top-ks "$${REPORT_TOP_KS:-5}" --output "$${OUT:-/tmp/gtc-bfcl-failure-inspect.json}"

release-check:
	scripts/release-check.sh

pypi-smoke:
	scripts/pypi-smoke.sh
