#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT_DIR"
EXPECTED_VERSION="$(poetry version -s)"
poetry build -f wheel --output "$TMP_DIR/dist"
python3 -m venv "$TMP_DIR/venv"
"$TMP_DIR/venv/bin/python" -m pip install --quiet --no-deps "$TMP_DIR"/dist/*.whl

VERSION_OUTPUT="$("$TMP_DIR/venv/bin/graph-tool-call" --version)"
DEMO_OUTPUT="$("$TMP_DIR/venv/bin/graph-tool-call" demo dependency-chain)"

if [[ "$VERSION_OUTPUT" != "graph-tool-call $EXPECTED_VERSION" ]]; then
    printf 'unexpected installed version: %s (expected %s)\n' \
        "$VERSION_OUTPUT" "$EXPECTED_VERSION" >&2
    exit 1
fi

case "$DEMO_OUTPUT" in
    *"1. findOrdersByEmail"*"2. refundOrder"*) ;;
    *)
        printf 'dependency-chain demo output did not contain the required order\n' >&2
        exit 1
        ;;
esac

"$TMP_DIR/venv/bin/python" -m compileall -q examples
"$TMP_DIR/venv/bin/python" examples/token_savings_demo.py \
    benchmarks/specs/k8s_core_v1.json "delete a pod" 5 >"$TMP_DIR/token-demo.txt"

printf '%s\n' "$VERSION_OUTPUT"
printf '%s\n' "$DEMO_OUTPUT"
printf 'Public wheel and example smoke checks passed.\n'
