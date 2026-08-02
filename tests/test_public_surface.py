"""Guard the version, examples, and launch claims users see first."""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

from graph_tool_call import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent_across_package_and_changelog() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = pyproject["tool"]["poetry"]["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert package_version == __version__ == "0.36.0"
    assert f"## [{package_version}]" in changelog


def test_public_examples_do_not_pin_obsolete_package_versions() -> None:
    obsolete = re.compile(r"graph-tool-call(?:\[[^]]+\])?==0\.(?:[0-2]?\d)\.")
    offenders = []
    for path in (ROOT / "examples").glob("*.py"):
        if obsolete.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)

    assert offenders == []


def test_quickstarts_use_the_reproducible_offline_demo() -> None:
    paths = [
        ROOT / "README.md",
        ROOT / "README-ko.md",
        ROOT / "README-zh_CN.md",
        ROOT / "README-ja.md",
        ROOT / "website/docs/getting-started/quickstart.md",
        ROOT
        / "website/i18n/ko/docusaurus-plugin-content-docs/current/getting-started/quickstart.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "graph-tool-call demo dependency-chain" in text, path


def test_readme_release_claim_links_to_checked_in_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    evidence = ROOT / "benchmarks/results/releases/v0.36.0/dependency-chain-evidence.json"

    assert evidence.is_file()
    assert "Required-producer recall** | 14.3% | **100%" in readme
    assert str(evidence.relative_to(ROOT)) in readme
