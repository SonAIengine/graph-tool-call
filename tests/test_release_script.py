"""Tests for release automation helpers."""

from __future__ import annotations

from pathlib import Path

from scripts.release import (
    prepare_changelog_release,
    unreleased_notes,
    update_init_version,
    update_pyproject_version,
)


def _sample_changelog() -> str:
    return """# Changelog

## [Unreleased]

### Added
- New thing

## [0.5.0] - 2026-03-07

### Added
- Old thing

[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.4.0...v0.5.0
"""


def test_unreleased_notes_extracts_body():
    notes = unreleased_notes(_sample_changelog())
    assert "### Added" in notes
    assert "- New thing" in notes
    assert "0.5.0" not in notes


def test_prepare_changelog_release_inserts_version_block():
    updated = prepare_changelog_release(_sample_changelog(), "0.8.0", "2026-03-12")
    assert "## [0.8.0] - 2026-03-12" in updated
    assert (
        "[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v0.8.0...HEAD"
        in updated
    )
    assert (
        "[0.8.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.5.0...v0.8.0" in updated
    )


def test_prepare_updates_version_files():
    pyproject = 'name = "graph-tool-call"\nversion = "0.7.2"\n'
    init_file = '__version__ = "0.7.2"\n'

    assert 'version = "0.8.0"' in update_pyproject_version(pyproject, "0.8.0")
    assert '__version__ = "0.8.0"' in update_init_version(init_file, "0.8.0")


def test_notes_command_output_file(tmp_path: Path):
    changelog_path = tmp_path / "CHANGELOG.md"
    output_path = tmp_path / "notes.md"
    changelog_path.write_text(_sample_changelog(), encoding="utf-8")

    from scripts.release import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "notes",
            "--version",
            "0.8.0",
            "--changelog",
            str(changelog_path),
            "--output",
            str(output_path),
            "--format",
            "plain",
        ]
    )
    result = args.func(args)
    assert result == 0
    assert output_path.read_text(encoding="utf-8").strip().startswith("### Added")
