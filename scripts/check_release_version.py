"""Fail a release when its tag and package metadata disagree."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Release tag, for example v0.36.0")
    args = parser.parse_args(argv)

    expected = args.tag.removeprefix("v")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = str(pyproject["tool"]["poetry"]["version"])
    version_line = next(
        line
        for line in (ROOT / "graph_tool_call/__init__.py").read_text(encoding="utf-8").splitlines()
        if line.startswith("__version__ =")
    )
    module_version = str(ast.literal_eval(version_line.split("=", 1)[1].strip()))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    failures = []
    if package_version != expected:
        failures.append(f"pyproject version {package_version!r} != tag {expected!r}")
    if module_version != expected:
        failures.append(f"module version {module_version!r} != tag {expected!r}")
    if f"## [{expected}]" not in changelog:
        failures.append(f"CHANGELOG has no [{expected}] release section")
    if failures:
        print("Release version check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"Release metadata matches {args.tag}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
