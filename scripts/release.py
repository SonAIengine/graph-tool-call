#!/usr/bin/env python3
"""Release helper for changelog/version management."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = ROOT / "CHANGELOG.md"
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"
DEFAULT_INIT = ROOT / "graph_tool_call" / "__init__.py"


@dataclass
class ChangelogSections:
    """Split changelog into reusable sections."""

    before_unreleased: str
    unreleased_body: str
    after_unreleased: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def parse_changelog_sections(text: str) -> ChangelogSections:
    """Extract the Unreleased section and surrounding content."""
    pattern = (
        r"(?ms)^(?P<head>.*?^## \[Unreleased\]\n)"
        r"(?P<body>.*?)"
        r"(?=^## \[.+?\] - \d{4}-\d{2}-\d{2}\n|^\[Unreleased\]:)"
    )
    match = re.search(
        pattern,
        text,
    )
    if not match:
        raise ValueError("Could not locate [Unreleased] section in CHANGELOG.md")

    body_end = match.end("body")
    return ChangelogSections(
        before_unreleased=match.group("head"),
        unreleased_body=match.group("body").strip("\n"),
        after_unreleased=text[body_end:],
    )


def unreleased_notes(text: str) -> str:
    """Return the current unreleased notes body."""
    return parse_changelog_sections(text).unreleased_body.strip()


def prepare_changelog_release(text: str, version: str, date: str) -> str:
    """Move the Unreleased section into a versioned release block."""
    sections = parse_changelog_sections(text)
    notes = sections.unreleased_body.strip()
    if not notes:
        raise ValueError("Unreleased section is empty")

    release_block = f"## [{version}] - {date}\n\n{notes}\n\n"
    new_text = (
        sections.before_unreleased + "\n" + release_block + sections.after_unreleased.lstrip("\n")
    )

    compare_pattern = re.compile(r"(?m)^\[Unreleased\]:\s+.+$")
    compare_line = (
        f"[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v{version}...HEAD"
    )
    if compare_pattern.search(new_text):
        new_text = compare_pattern.sub(compare_line, new_text, count=1)
    else:
        new_text = new_text.rstrip() + "\n\n" + compare_line + "\n"

    anchor_pattern = re.compile(rf"(?m)^\[{re.escape(version)}\]:\s+.+$")
    release_line = (
        f"[{version}]: https://github.com/SonAIengine/graph-tool-call/compare/"
        f"v{previous_version(text)}...v{version}"
    )
    if not anchor_pattern.search(new_text):
        new_text = new_text.rstrip() + "\n" + release_line + "\n"

    return new_text


def previous_version(text: str) -> str:
    """Find the most recent released version in the changelog."""
    versions = re.findall(r"(?m)^## \[([^\]]+)\] - \d{4}-\d{2}-\d{2}$", text)
    if not versions:
        raise ValueError("Could not find previous version in CHANGELOG.md")
    return versions[0]


def update_pyproject_version(text: str, version: str) -> str:
    """Update Poetry version in pyproject.toml."""
    updated, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("Could not update version in pyproject.toml")
    return updated


def update_init_version(text: str, version: str) -> str:
    """Update __version__ in graph_tool_call.__init__."""
    updated, count = re.subn(
        r'(?m)^__version__ = "[^"]+"$',
        f'__version__ = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("Could not update __version__ in graph_tool_call/__init__.py")
    return updated


def cmd_notes(args: argparse.Namespace) -> int:
    notes = unreleased_notes(_read(Path(args.changelog)))
    content = notes if args.format == "plain" else f"# Release {args.version}\n\n{notes}\n"
    if args.output:
        _write(Path(args.output), content)
    else:
        print(content)
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    changelog_path = Path(args.changelog)
    pyproject_path = Path(args.pyproject)
    init_path = Path(args.init_file)

    changelog_text = _read(changelog_path)
    new_changelog = prepare_changelog_release(changelog_text, args.version, args.date)
    new_pyproject = update_pyproject_version(_read(pyproject_path), args.version)
    new_init = update_init_version(_read(init_path), args.version)

    if args.dry_run:
        print(f"Would prepare release {args.version} ({args.date})")
        print("Updated files:")
        print(f"  {changelog_path}")
        print(f"  {pyproject_path}")
        print(f"  {init_path}")
        return 0

    _write(changelog_path, new_changelog)
    _write(pyproject_path, new_pyproject)
    _write(init_path, new_init)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Release helper for graph-tool-call")
    sub = parser.add_subparsers(dest="command", required=True)

    p_notes = sub.add_parser("notes", help="Print or write current unreleased release notes")
    p_notes.add_argument("--version", required=True, help="Target version, e.g. 0.8.0")
    p_notes.add_argument("--changelog", default=str(DEFAULT_CHANGELOG))
    p_notes.add_argument("--output", help="Write notes to a file instead of stdout")
    p_notes.add_argument(
        "--format",
        choices=["plain", "github"],
        default="github",
        help="Output formatting",
    )
    p_notes.set_defaults(func=cmd_notes)

    p_prepare = sub.add_parser("prepare", help="Freeze Unreleased into a release section")
    p_prepare.add_argument("--version", required=True, help="Release version, e.g. 0.8.0")
    p_prepare.add_argument("--date", required=True, help="Release date, e.g. 2026-03-12")
    p_prepare.add_argument("--changelog", default=str(DEFAULT_CHANGELOG))
    p_prepare.add_argument("--pyproject", default=str(DEFAULT_PYPROJECT))
    p_prepare.add_argument("--init-file", default=str(DEFAULT_INIT))
    p_prepare.add_argument("--dry-run", action="store_true")
    p_prepare.set_defaults(func=cmd_prepare)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
