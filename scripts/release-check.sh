#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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

poetry run ruff check .
poetry run ruff format --check .
poetry run pytest tests/ -q
poetry build
uvx twine check "dist/graph_tool_call-${version}"*
