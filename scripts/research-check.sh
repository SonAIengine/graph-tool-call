#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mode="${1:-deterministic}"
artifact_dir="${ARTIFACT_DIR:-/tmp/gtc-research-check}"
mkdir -p "$artifact_dir"

bfcl_categories="${BFCL_CATEGORIES:-simple_python,multiple,parallel,parallel_multiple}"
bfcl_top_k="${BFCL_TOP_K:-5}"
bfcl_min_recall="${BFCL_MIN_RECALL_AT_5:-0.90}"
case_ids_file="${CASE_IDS_FILE:-}"
smoke_limit="${SMOKE_LIMIT:-5}"
model="${MODEL:-qwen3:4b}"
llm_url="${LLM_URL:-http://localhost:11434/api/chat}"

case_filter_args=()
if [[ -n "$case_ids_file" ]]; then
  case_filter_args=(--case-ids-file "$case_ids_file")
fi

thinking_args=()
if [[ "${DISABLE_THINKING:-0}" == "1" ]]; then
  thinking_args=(--disable-thinking)
fi

run() {
  printf '\n==> %s\n' "$*"
  "$@"
}

run_json() {
  local output="$1"
  shift
  printf '\n==> %s > %s\n' "$*" "$output"
  "$@" > "$output"
}

run_unit() {
  run scripts/quick-check.sh
}

run_deterministic() {
  run_unit
  run_json "$artifact_dir/xgen-deterministic.json" \
    poetry run python -m benchmarks.xgen_tool_graph.run \
    --json
  run_json "$artifact_dir/bfcl-deterministic.json" \
    poetry run python -m benchmarks.bfcl_tool_selection.run \
    --categories "$bfcl_categories" \
    --top-k "$bfcl_top_k" \
    --min-recall-at-5 "$bfcl_min_recall" \
    "${case_filter_args[@]}" \
    --json
  printf '\nArtifacts written to %s\n' "$artifact_dir"
}

run_smoke() {
  run_deterministic
  run_json "$artifact_dir/xgen-llm-smoke.json" \
    poetry run python -m benchmarks.xgen_tool_graph.llm_loop \
    --model "$model" \
    --llm-url "$llm_url" \
    --limit "$smoke_limit" \
    "${thinking_args[@]}" \
    --json
  run poetry run python -m benchmarks.bfcl_tool_selection.llm_loop \
    --categories "${BFCL_SMOKE_CATEGORIES:-simple_python}" \
    --limit "$smoke_limit" \
    --top-k "$bfcl_top_k" \
    --model "$model" \
    --llm-url "$llm_url" \
    --cache-dir "$artifact_dir/bfcl-cache" \
    "${case_filter_args[@]}" \
    "${thinking_args[@]}" \
    --output "$artifact_dir/bfcl-llm-smoke.json"
}

usage() {
  cat <<'USAGE'
Usage: scripts/research-check.sh [unit|deterministic|smoke|release]

Environment:
  ARTIFACT_DIR=/tmp/gtc-research-check
  BFCL_CATEGORIES=simple_python,multiple,parallel,parallel_multiple
  BFCL_TOP_K=5
  BFCL_MIN_RECALL_AT_5=0.90
  CASE_IDS_FILE=/tmp/failed-case-ids.txt
  MODEL=qwen3:4b
  LLM_URL=http://localhost:11434/api/chat
  SMOKE_LIMIT=5
  DISABLE_THINKING=1

Tiers:
  unit           lint/format plus fast contract tests
  deterministic unit plus no-LLM XGEN and BFCL retrieval gates
  smoke          deterministic plus small model-in-the-loop checks
  release        full release-check only; expensive model benchmarks stay manual
USAGE
}

case "$mode" in
  unit)
    run_unit
    ;;
  deterministic)
    run_deterministic
    ;;
  smoke)
    run_smoke
    ;;
  release)
    run scripts/release-check.sh
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
