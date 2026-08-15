.PHONY: quick lint test verify research-check research-check-unit research-check-deterministic research-check-smoke paper-corpus-check paper-corpus-internal-review-check paper-corpus-claim-check paper-adapter-conformance paper-baseline-run paper-graph-ablation paper-producer-coverage paper-output-promotion paper-candidate-admission paper-contract-projection paper-model-loop paper-llm-catalog-baseline paper-model-loop-analysis paper-toolinkos-parity paper-openapi-closure paper-harness-check goal-completion-benchmark xgen-benchmark xgen-llm-benchmark xgen-scale-snapshot xgen-scale-snapshot-check xgen-scale-acceptance xgen-scale-sweep xgen-scale-gate-check xgen-scale-028-gate-check xgen-scale-contract-ablation bfcl-benchmark bfcl-llm-benchmark bfcl-sweep bfcl-027-gate bfcl-027-gate-check bfcl-028-gate bfcl-028-gate-check bfcl-failure-subset bfcl-inspect-failures bfcl-hard-cases release-check pypi-smoke public-smoke launch-evidence launch-evidence-check observability-evidence observability-evidence-check

quick:
	scripts/quick-check.sh

lint:
	poetry run ruff check .
	poetry run ruff format --check .

test:
	poetry run pytest tests/ -q

verify: lint test

public-smoke:
	scripts/public-smoke.sh

launch-evidence:
	poetry run python -m benchmarks.release_evidence

launch-evidence-check:
	poetry run python -m benchmarks.release_evidence --check

observability-evidence:
	poetry run python -m benchmarks.observability_release

observability-evidence-check:
	poetry run python -m benchmarks.observability_release --check

research-check:
	scripts/research-check.sh deterministic

research-check-unit:
	scripts/research-check.sh unit

research-check-deterministic:
	scripts/research-check.sh deterministic

research-check-smoke:
	scripts/research-check.sh smoke

paper-corpus-check:
	poetry run python -m benchmarks.corpus.manifest \
		"$${MANIFEST:-benchmarks/corpus/manifest.json}" \
		--verify-ingest
	poetry run python -m benchmarks.corpus.review \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}"

paper-corpus-internal-review-check:
	poetry run python -m benchmarks.corpus.review \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}"

paper-corpus-claim-check:
	poetry run python -m benchmarks.corpus.review \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}"
	poetry run python -m benchmarks.corpus.manifest \
		"$${MANIFEST:-benchmarks/corpus/manifest.json}" \
		--verify-ingest \
		--require-paper-ready

paper-adapter-conformance:
	poetry run python -m benchmarks.adapter_conformance.run \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}" \
		--splits "$${SPLITS:-train,dev}" \
		--out "$${OUT:-/tmp/graph-tool-call-adapter-conformance.json}"

paper-baseline-run:
	poetry run python -m benchmarks.paper_baselines.run \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}" \
		--splits "$${SPLITS:-train,dev}" \
		--top-k "$${TOP_K:-5}" \
		--seed "$${SEED:-17}" \
		--dense-model "$${DENSE_MODEL:-intfloat/multilingual-e5-small}" \
		--dense-revision "$${DENSE_REVISION:-fd1525a9fd15316a2d503bf26ab031a61d056e98}" \
		--dense-device "$${DENSE_DEVICE:-cpu}" \
		--dense-batch-size "$${DENSE_BATCH_SIZE:-32}" \
		--token-budget "$${TOKEN_BUDGET:-2048}" \
		--context-tokenizer "$${CONTEXT_TOKENIZER:-Qwen/Qwen3-4B}" \
		--context-tokenizer-revision "$${CONTEXT_TOKENIZER_REVISION:-1cfa9a7208912126459214e8b04321603b3df60c}" \
		--bootstrap-resamples "$${BOOTSTRAP_RESAMPLES:-1000}" \
		--out "$${OUT:-/tmp/graph-tool-call-paper-baselines.json}"

paper-graph-ablation:
	@$(MAKE) paper-baseline-run \
		OUT="$${OUT:-/tmp/graph-tool-call-paper-graph-ablation.json}"

paper-producer-coverage:
	@$(MAKE) paper-baseline-run \
		OUT="$${OUT:-/tmp/graph-tool-call-paper-producer-coverage.json}"

paper-output-promotion:
	@$(MAKE) paper-baseline-run \
		OUT="$${OUT:-/tmp/graph-tool-call-paper-output-promotion.json}"

paper-candidate-admission:
	@$(MAKE) paper-baseline-run \
		OUT="$${OUT:-/tmp/graph-tool-call-paper-candidate-admission.json}"

paper-contract-projection:
	@$(MAKE) paper-baseline-run \
		OUT="$${OUT:-/tmp/graph-tool-call-paper-contract-projection.json}"

paper-model-loop:
	@test -n "$${BASELINE_ARTIFACT:-}" || (echo "BASELINE_ARTIFACT is required"; exit 2)
	@test -n "$${MODEL:-}" || (echo "MODEL is required"; exit 2)
	@test -n "$${MODEL_REVISION:-}" || (echo "MODEL_REVISION is required"; exit 2)
	poetry run python -m benchmarks.paper_model_loop.run \
		--baseline-artifact "$$BASELINE_ARTIFACT" \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}" \
		--model "$$MODEL" \
		--model-revision "$$MODEL_REVISION" \
		--provider "$${PROVIDER:-openai-compatible}" \
		--llm-url "$${LLM_URL:-http://localhost:8000/v1}" \
		--repeats "$${REPEATS:-1}" \
		--seed "$${SEED:-17}" \
		--timeout "$${TIMEOUT:-180}" \
		--bootstrap-resamples "$${BOOTSTRAP_RESAMPLES:-1000}" \
		--out "$${OUT:-/tmp/graph-tool-call-paper-b6c-model-loop.json}"

paper-llm-catalog-baseline:
	@test -n "$${BASELINE_ARTIFACT:-}" || (echo "BASELINE_ARTIFACT is required"; exit 2)
	@test -n "$${MODEL:-}" || (echo "MODEL is required"; exit 2)
	@test -n "$${MODEL_REVISION:-}" || (echo "MODEL_REVISION is required"; exit 2)
	poetry run python -m benchmarks.paper_model_loop.llm_catalog_run \
		--baseline-artifact "$$BASELINE_ARTIFACT" \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}" \
		--model "$$MODEL" \
		--model-revision "$$MODEL_REVISION" \
		--provider "$${PROVIDER:-openai-compatible}" \
		--llm-url "$${LLM_URL:-http://localhost:8000/v1}" \
		--repeats "$${REPEATS:-1}" \
		--seed "$${SEED:-17}" \
		--timeout "$${TIMEOUT:-180}" \
		--bootstrap-resamples "$${BOOTSTRAP_RESAMPLES:-1000}" \
		--out "$${OUT:-/tmp/graph-tool-call-paper-b0l-vs-b6c.json}"

paper-model-loop-analysis:
	@test -n "$${ARTIFACT:-}" || (echo "ARTIFACT is required"; exit 2)
	poetry run python -m benchmarks.paper_model_loop.analysis \
		--artifact "$$ARTIFACT" \
		--bootstrap-resamples "$${BOOTSTRAP_RESAMPLES:-10000}" \
		--out "$${OUT:-/tmp/graph-tool-call-paper-model-loop-analysis.json}"

paper-toolinkos-parity:
	poetry run python -m benchmarks.external_tool_retrieval.toollinkos \
		--dataset-root "$${DATASET_ROOT:-/tmp/toolinkos}" \
		--download \
		--top-k "$${TOP_K:-10,20,30}" \
		--initial-k "$${INITIAL_K:-3}" \
		--dense-device "$${DENSE_DEVICE:-cpu}" \
		--bootstrap-resamples "$${BOOTSTRAP_RESAMPLES:-2000}" \
		--out "$${OUT:-/tmp/graph-tool-call-toolinkos-parity.json}"

paper-openapi-closure:
	poetry run python -m benchmarks.openapi_dependency_closure \
		--manifest "$${MANIFEST:-benchmarks/corpus/manifest.json}" \
		--splits "$${SPLITS:-train,dev}" \
		--max-hops "$${MAX_HOPS:-3}" \
		--bootstrap-resamples "$${BOOTSTRAP_RESAMPLES:-2000}" \
		--seed "$${SEED:-17}" \
		--out "$${OUT:-/tmp/graph-tool-call-openapi-closure.json}"

paper-harness-check:
	poetry run pytest \
		tests/test_experiment_artifact.py \
		tests/test_paper_baselines.py \
		tests/test_paper_token_budget.py \
		tests/test_paper_model_loop.py \
		tests/test_paper_llm_catalog_baseline.py \
		tests/test_paper_corpus_manifest.py \
		tests/test_paper_corpus_review.py \
		tests/test_adapter_conformance.py \
		tests/test_openapi_dependency_closure_benchmark.py \
		-q

goal-completion-benchmark:
	poetry run python -m benchmarks.goal_completion.run \
		--scenarios "$${SCENARIOS:-benchmarks/goal_completion/scenarios.json}" \
		--output "$${OUT:-/tmp/graph-tool-call-goal-completion.json}"

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
		--gate-profile "$${GATE_PROFILE:-xgen-scale-0.27}" \
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
		--gate-profile "$${GATE_PROFILE:-xgen-scale-0.27}" \
		--output "$${OUT:-/tmp/gtc-xgen-scale-sweep.json}"

xgen-scale-gate-check:
	@test -n "$(REPORT)" || (echo "Usage: make xgen-scale-gate-check REPORT=/tmp/gtc-xgen-scale-sweep.json [PROFILE=xgen-scale-0.27]" && exit 2)
	poetry run python -m benchmarks.xgen_api_scale.gate "$(REPORT)" --profile "$${PROFILE:-xgen-scale-0.27}"

xgen-scale-028-gate-check:
	@test -n "$(REPORT)" || (echo "Usage: make xgen-scale-028-gate-check REPORT=/tmp/gtc-xgen-scale-snapshot-sweep.json" && exit 2)
	poetry run python -m benchmarks.xgen_api_scale.gate "$(REPORT)" --profile xgen-scale-0.28

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
