.PHONY: quick lint test verify research-check research-check-unit research-check-deterministic research-check-smoke xgen-benchmark xgen-llm-benchmark xgen-scale-snapshot xgen-scale-snapshot-check xgen-scale-acceptance xgen-scale-sweep xgen-scale-gate-check xgen-scale-contract-ablation bfcl-benchmark bfcl-llm-benchmark bfcl-sweep bfcl-027-gate bfcl-027-gate-check bfcl-028-gate bfcl-028-gate-check bfcl-failure-subset bfcl-inspect-failures bfcl-hard-cases release-check pypi-smoke

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
	poetry run python -m benchmarks.xgen_tool_graph.run --suite all

xgen-llm-benchmark:
	poetry run python -m benchmarks.xgen_tool_graph.llm_loop --model qwen3:4b

xgen-scale-snapshot:
	@source_args="--swagger-url $${SWAGGER_URL:-https://api-bo.x2bee.com/api/bo/swagger-ui/index.html}"; \
	selected_specs="$${SPECS:-$${SPEC:-}}"; \
	if [ -n "$$selected_specs" ]; then \
		source_args=""; \
		for spec in $$(printf "%s" "$$selected_specs" | tr ',' ' '); do source_args="$$source_args --spec $$spec"; done; \
	fi; \
	private_args=""; \
	if [ "$${ALLOW_PRIVATE_HOSTS:-0}" != "0" ]; then private_args="--allow-private-hosts"; fi; \
	poetry run python -m benchmarks.xgen_api_scale.snapshot \
		$$source_args \
		$$private_args \
		--max-response-bytes "$${MAX_RESPONSE_BYTES:-5000000}" \
		--out-dir "$${OUT_DIR:-/tmp/gtc-xgen-scale-snapshot}"

xgen-scale-snapshot-check:
	@test -n "$(MANIFEST)" || (echo "Usage: make xgen-scale-snapshot-check MANIFEST=/tmp/gtc-xgen-scale-snapshot/manifest.json" && exit 2)
	poetry run python -m benchmarks.xgen_api_scale.manifest "$(MANIFEST)"

xgen-scale-acceptance:
	@source_args="--swagger-url $${SWAGGER_URL:-https://api-bo.x2bee.com/api/bo/swagger-ui/index.html}"; \
	selected_specs="$${SPECS:-$${SPEC:-}}"; \
	selected_manifests="$${SNAPSHOT_MANIFESTS:-$${MANIFESTS:-$${SNAPSHOT_MANIFEST:-$${MANIFEST:-}}}}"; \
	if [ -n "$$selected_manifests$$selected_specs" ]; then \
		source_args=""; \
		for manifest in $$(printf "%s" "$$selected_manifests" | tr ',' ' '); do source_args="$$source_args --manifest $$manifest"; done; \
	fi; \
	if [ -n "$$selected_specs" ]; then \
		for spec in $$(printf "%s" "$$selected_specs" | tr ',' ' '); do source_args="$$source_args --spec $$spec"; done; \
	fi; \
	case_args=""; \
	if [ "$${NO_CASES:-0}" != "0" ]; then case_args="--no-cases"; fi; \
	poetry run python -m benchmarks.xgen_api_scale.run \
		$$source_args \
		$$case_args \
		--min-unique-tools "$${MIN_UNIQUE_TOOLS:-1000}" \
		--max-build-seconds "$${MAX_BUILD_SECONDS:-30}" \
		--output "$${OUT:-/tmp/gtc-xgen-scale-acceptance.json}"

xgen-scale-sweep:
	@source_args="--swagger-url $${SWAGGER_URL:-https://api-bo.x2bee.com/api/bo/swagger-ui/index.html}"; \
	selected_specs="$${SPECS:-$${SPEC:-}}"; \
	selected_manifests="$${SNAPSHOT_MANIFESTS:-$${MANIFESTS:-$${SNAPSHOT_MANIFEST:-$${MANIFEST:-}}}}"; \
	if [ -n "$$selected_manifests$$selected_specs" ]; then \
		source_args=""; \
		for manifest in $$(printf "%s" "$$selected_manifests" | tr ',' ' '); do source_args="$$source_args --manifest $$manifest"; done; \
	fi; \
	if [ -n "$$selected_specs" ]; then \
		for spec in $$(printf "%s" "$$selected_specs" | tr ',' ' '); do source_args="$$source_args --spec $$spec"; done; \
	fi; \
	case_args=""; \
	if [ "$${NO_CASES:-0}" != "0" ]; then case_args="--no-cases"; fi; \
	poetry run python -m benchmarks.xgen_api_scale.run \
		$$source_args \
		$$case_args \
		--top-ks "$${TOP_KS:-3,5,10}" \
		--acceptance-top-k "$${ACCEPTANCE_TOP_K:-10}" \
		--min-unique-tools "$${MIN_UNIQUE_TOOLS:-1000}" \
		--max-build-seconds "$${MAX_BUILD_SECONDS:-30}" \
		--output "$${OUT:-/tmp/gtc-xgen-scale-sweep.json}"

xgen-scale-gate-check:
	@test -n "$(REPORT)" || (echo "Usage: make xgen-scale-gate-check REPORT=/tmp/gtc-xgen-scale-sweep.json [PROFILE=xgen-scale-0.27]" && exit 2)
	poetry run python -m benchmarks.xgen_api_scale.gate "$(REPORT)" --profile "$${PROFILE:-xgen-scale-0.27}"

xgen-scale-contract-ablation:
	@source_args="--swagger-url $${SWAGGER_URL:-https://api-bo.x2bee.com/api/bo/swagger-ui/index.html}"; \
	selected_specs="$${SPECS:-$${SPEC:-}}"; \
	selected_manifests="$${SNAPSHOT_MANIFESTS:-$${MANIFESTS:-$${SNAPSHOT_MANIFEST:-$${MANIFEST:-}}}}"; \
	if [ -n "$$selected_manifests$$selected_specs" ]; then \
		source_args=""; \
		for manifest in $$(printf "%s" "$$selected_manifests" | tr ',' ' '); do source_args="$$source_args --manifest $$manifest"; done; \
	fi; \
	if [ -n "$$selected_specs" ]; then \
		for spec in $$(printf "%s" "$$selected_specs" | tr ',' ' '); do source_args="$$source_args --spec $$spec"; done; \
	fi; \
	case_args=""; \
	if [ "$${NO_CASES:-0}" != "0" ]; then case_args="--no-cases"; fi; \
	poetry run python -m benchmarks.xgen_api_scale.run \
		$$source_args \
		$$case_args \
		--compare-contract-signals \
		--context-fields "$${CONTEXT_FIELDS:-siteNo,langCd,sysGbCd}" \
		--min-unique-tools "$${MIN_UNIQUE_TOOLS:-1000}" \
		--max-build-seconds "$${MAX_BUILD_SECONDS:-30}" \
		--output "$${OUT:-/tmp/gtc-xgen-scale-contract-ablation.json}"

bfcl-benchmark:
	poetry run python -m benchmarks.bfcl_tool_selection.run --limit 50

bfcl-llm-benchmark:
	poetry run python -m benchmarks.bfcl_tool_selection.llm_loop --categories simple_python --limit 5 --model qwen3:4b

bfcl-sweep:
	poetry run python -m benchmarks.bfcl_tool_selection.sweep --categories simple_python --limit 5 --top-ks 3,5 --model qwen3:4b

bfcl-027-gate:
	@fail_args=""; \
	if [ "$${FAIL_ON_GATE:-1}" != "0" ]; then fail_args="--fail-on-milestone-gate"; fi; \
	poetry run python -m benchmarks.bfcl_tool_selection.sweep \
		--categories "$${CATEGORIES:-simple_python,multiple,parallel,parallel_multiple}" \
		--limit "$${LIMIT:-25}" \
		--top-ks "$${TOP_KS:-5}" \
		--tool-sources "$${TOOL_SOURCES:-row,retrieved}" \
		--repeats "$${REPEATS:-3}" \
		--model "$${MODEL:-qwen3.6-27b}" \
		--llm-url "$${LLM_URL:-http://127.0.0.1:18000/v1}" \
		--disable-thinking \
		--candidate-selection-guidance \
		--cohesive-namespace-candidates \
		--cache-dir "$${CACHE_DIR:-/tmp/gtc-bfcl-027-gate-cache}" \
		--concurrency "$${CONCURRENCY:-6}" \
		--progress \
		--progress-every "$${PROGRESS_EVERY:-10}" \
		--output "$${OUT:-/tmp/gtc-bfcl-027-gate.json}" \
		$$fail_args

bfcl-027-gate-check:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-027-gate-check REPORT=/tmp/gtc-bfcl-027-gate.json [PROFILE=xgen-0.27]" && exit 2)
	poetry run python -m benchmarks.bfcl_tool_selection.gate "$(REPORT)" --profile "$${PROFILE:-xgen-0.27}"

bfcl-028-gate:
	@fail_args=""; \
	if [ "$${FAIL_ON_GATE:-1}" != "0" ]; then fail_args="--fail-on-milestone-gate"; fi; \
	limit_args=""; \
	if [ -n "$${LIMIT:-}" ]; then limit_args="--limit $${LIMIT}"; fi; \
	poetry run python -m benchmarks.bfcl_tool_selection.sweep \
		--categories "$${CATEGORIES:-simple_python,multiple,parallel,parallel_multiple}" \
		$$limit_args \
		--top-ks "$${TOP_KS:-5}" \
		--tool-sources "$${TOOL_SOURCES:-row,retrieved}" \
		--repeats "$${REPEATS:-3}" \
		--model "$${MODEL:-qwen3.6-27b}" \
		--llm-url "$${LLM_URL:-http://127.0.0.1:18000/v1}" \
		--disable-thinking \
		--candidate-selection-guidance \
		--cohesive-namespace-candidates \
		--cache-dir "$${CACHE_DIR:-/tmp/gtc-bfcl-028-gate-cache}" \
		--concurrency "$${CONCURRENCY:-6}" \
		--progress \
		--progress-every "$${PROGRESS_EVERY:-10}" \
		--milestone-profile xgen-0.28 \
		--output "$${OUT:-/tmp/gtc-bfcl-028-gate.json}" \
		$$fail_args

bfcl-028-gate-check:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-028-gate-check REPORT=/tmp/gtc-bfcl-028-gate.json" && exit 2)
	poetry run python -m benchmarks.bfcl_tool_selection.gate "$(REPORT)" --profile xgen-0.28

bfcl-failure-subset:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-failure-subset REPORT=/tmp/report.json [OUT=/tmp/case_ids.txt]" && exit 2)
	poetry run python -m benchmarks.bfcl_tool_selection.failures --report "$(REPORT)" --output "$${OUT:-/tmp/gtc-bfcl-failure-case-ids.txt}"

bfcl-inspect-failures:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-inspect-failures REPORT=/tmp/report.json [OUT=/tmp/inspect.json] [TOP_K=5] [INSPECT_DEPTH=20]" && exit 2)
	poetry run python -m benchmarks.bfcl_tool_selection.inspect --report "$(REPORT)" --top-k "$${TOP_K:-5}" --inspect-depth "$${INSPECT_DEPTH:-20}" --tool-sources "$${TOOL_SOURCES:-retrieved}" --top-ks "$${REPORT_TOP_KS:-5}" --output "$${OUT:-/tmp/gtc-bfcl-failure-inspect.json}"

bfcl-hard-cases:
	@test -n "$(REPORT)" || (echo "Usage: make bfcl-hard-cases REPORT=/tmp/report.json [OUT_DIR=/tmp/gtc-bfcl-hard-cases] [DATA_ROOT=/tmp/bfcl-data] [TOP_K=5] [INSPECT_DEPTH=20]" && exit 2)
	@data_root_args=""; \
	if [ -n "$${DATA_ROOT:-}" ]; then data_root_args="--data-root $${DATA_ROOT}"; fi; \
	poetry run python -m benchmarks.bfcl_tool_selection.hard_cases \
		--report "$(REPORT)" \
		--out-dir "$${OUT_DIR:-/tmp/gtc-bfcl-hard-cases}" \
		$$data_root_args \
		--categories "$${CATEGORIES:-}" \
		--failure-categories "$${FAILURE_CATEGORIES:-retrieval_miss,candidate_ambiguity}" \
		--tool-sources "$${TOOL_SOURCES:-}" \
		--top-ks "$${REPORT_TOP_KS:-5}" \
		--top-k "$${TOP_K:-5}" \
		--inspect-depth "$${INSPECT_DEPTH:-20}"

release-check:
	scripts/release-check.sh

pypi-smoke:
	scripts/pypi-smoke.sh
