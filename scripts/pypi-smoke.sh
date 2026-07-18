#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

version="${1:-}"
if [[ -z "$version" ]]; then
  version="$(
    "${PYTHON:-python3}" - <<'PY'
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

data = tomllib.loads(Path("pyproject.toml").read_text())
print(data["tool"]["poetry"]["version"])
PY
  )"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

"${PYTHON:-python3}" -m venv "$tmp/venv"
cd "$tmp"
"$tmp/venv/bin/pip" install --no-cache-dir -q "graph-tool-call[korean]==${version}"
"$tmp/venv/bin/python" - <<'PY'
import graph_tool_call
from graph_tool_call.graphify import (
    build_io_contract,
    expand_candidates_with_producers,
    normalize_graph_edge,
    retrieve_graphify,
)
from graph_tool_call.plan import PathSynthesizer, PlanRunner

print(graph_tool_call.__version__)
print(
    retrieve_graphify.__name__,
    build_io_contract.__name__,
    expand_candidates_with_producers.__name__,
    normalize_graph_edge.__name__,
)
print(PathSynthesizer.__name__, PlanRunner.__name__)
PY
