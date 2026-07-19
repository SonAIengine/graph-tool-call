"""Utilities for reading XGEN-scale OpenAPI snapshot manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class SnapshotManifestError(ValueError):
    """Raised when an XGEN scale snapshot manifest is invalid."""


def load_snapshot_manifest(
    manifest_path: str | Path,
    *,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    """Load a snapshot manifest and optionally verify every spec sha256."""
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    specs = manifest.get("specs")
    if not isinstance(specs, list):
        msg = f"snapshot manifest missing specs list: {path}"
        raise SnapshotManifestError(msg)

    normalized_specs = [
        _normalize_spec_row(row, manifest_path=path, verify_hashes=verify_hashes) for row in specs
    ]
    normalized = dict(manifest)
    normalized["manifest_path"] = str(path)
    normalized["specs"] = normalized_specs
    normalized["specs_csv"] = ",".join(str(row["path"]) for row in normalized_specs)
    return normalized


def spec_sources_from_manifest(
    manifest_path: str | Path,
    *,
    verify_hashes: bool = True,
) -> list[str]:
    """Return local spec paths from a verified snapshot manifest."""
    manifest = load_snapshot_manifest(manifest_path, verify_hashes=verify_hashes)
    return [str(row["path"]) for row in manifest["specs"]]


def _normalize_spec_row(
    row: Any,
    *,
    manifest_path: Path,
    verify_hashes: bool,
) -> dict[str, Any]:
    if not isinstance(row, dict):
        msg = f"snapshot manifest spec row must be an object: {manifest_path}"
        raise SnapshotManifestError(msg)
    if not row.get("path"):
        msg = f"snapshot manifest spec row missing path: {manifest_path}"
        raise SnapshotManifestError(msg)

    normalized = dict(row)
    spec_path = _resolve_spec_path(str(normalized["path"]), manifest_path=manifest_path)
    if not spec_path.exists():
        msg = f"snapshot spec file not found: {spec_path}"
        raise SnapshotManifestError(msg)

    if verify_hashes and normalized.get("sha256"):
        digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        if digest != normalized["sha256"]:
            msg = f"snapshot spec sha256 mismatch: {spec_path}"
            raise SnapshotManifestError(msg)

    normalized["path"] = str(spec_path)
    return normalized


def _resolve_spec_path(value: str, *, manifest_path: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def format_manifest_check(manifest: dict[str, Any]) -> str:
    """Format a compact successful manifest check."""
    return "xgen-scale snapshot manifest ok specs={specs} operations={ops} path={path}".format(
        specs=manifest.get("spec_count", len(manifest.get("specs") or [])),
        ops=manifest.get("operation_count"),
        path=manifest.get("manifest_path"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--no-verify-hashes",
        action="store_true",
        help="Skip sha256 verification and only check manifest structure/paths.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    manifest = load_snapshot_manifest(args.manifest, verify_hashes=not args.no_verify_hashes)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(format_manifest_check(manifest))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
