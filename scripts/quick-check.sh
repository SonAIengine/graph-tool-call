#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${1:-}" == "--full" ]]; then
  shift
  tests=(tests/)
else
  tests=(
    tests/test_graphify_contract_025.py
    tests/test_graphify_metadata.py
    tests/test_io_contract.py
    tests/test_bm25.py
    tests/test_retrieval.py
    tests/test_plan_binding.py
    tests/test_plan_coercion.py
    tests/test_plan_recovery.py
    tests/test_plan_runner.py
    tests/test_plan_synthesizer.py
    tests/test_tokenizer_injection.py
    tests/test_bfcl_tool_selection_benchmark.py
    tests/test_bfcl_tool_selection_failures.py
    tests/test_bfcl_tool_selection_inspect.py
    tests/test_bfcl_tool_selection_llm_loop.py
    tests/test_bfcl_tool_selection_sweep.py
    tests/test_xgen_tool_graph_benchmark.py
    tests/test_xgen_tool_graph_llm_loop.py
  )
fi

if [[ "${SKIP_LINT:-0}" != "1" ]]; then
  poetry run ruff check .
  poetry run ruff format --check .
fi

poetry run pytest -q "${tests[@]}" "$@"
