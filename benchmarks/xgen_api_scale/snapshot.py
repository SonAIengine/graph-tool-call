"""Capture XGEN-scale OpenAPI specs as reusable snapshot files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.xgen_api_scale.run import (
    DEFAULT_X2BEE_SWAGGER_URL,
    LoadedSpec,
    load_specs,
    profile_spec,
)
from graph_tool_call import __version__


def snapshot_specs(
    *,
    out_dir: Path,
    swagger_url: str = DEFAULT_X2BEE_SWAGGER_URL,
    spec_sources: list[str | dict[str, Any]] | None = None,
    max_response_bytes: int = 5_000_000,
    allow_private_hosts: bool = False,
) -> dict[str, Any]:
    """Load OpenAPI specs and write a reproducible local snapshot manifest."""
    loaded_specs = load_specs(
        swagger_url=swagger_url,
        spec_sources=spec_sources,
        max_response_bytes=max_response_bytes,
        allow_private_hosts=allow_private_hosts,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        _write_snapshot_spec(loaded, index=index, out_dir=out_dir)
        for index, loaded in enumerate(loaded_specs, start=1)
    ]
    manifest = {
        "snapshot": "xgen_api_scale_openapi_snapshot",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "graph_tool_call_version": __version__,
        "source_url": swagger_url,
        "spec_count": len(rows),
        "operation_count": sum(int(row["operation_count"]) for row in rows),
        "path_count": sum(int(row["path_count"]) for row in rows),
        "specs_csv": ",".join(str(row["path"]) for row in rows),
        "specs": rows,
    }
    manifest_path = out_dir / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _write_snapshot_spec(loaded: LoadedSpec, *, index: int, out_dir: Path) -> dict[str, Any]:
    raw = json.dumps(loaded.spec, ensure_ascii=False, indent=2, sort_keys=True)
    encoded = raw.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    profile = profile_spec(loaded)
    filename = f"{index:02d}_{_safe_slug(loaded.label)}_{digest[:12]}.json"
    path = out_dir / filename
    path.write_bytes(encoded)
    return {
        "index": index,
        "label": loaded.label,
        "source": loaded.source,
        "path": str(path),
        "sha256": digest,
        "bytes": len(encoded),
        "title": profile.title,
        "version": profile.version,
        "openapi_version": profile.openapi_version,
        "path_count": profile.path_count,
        "operation_count": profile.operation_count,
        "operation_id_count": profile.operation_id_count,
        "missing_operation_id_count": profile.missing_operation_id_count,
        "request_body_schema_count": profile.request_body_schema_count,
        "response_schema_count": profile.response_schema_count,
    }


def _safe_slug(value: str, *, fallback: str = "spec") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return (slug or fallback)[:80]


def format_manifest(manifest: dict[str, Any]) -> str:
    """Format a compact human-readable snapshot summary."""
    return (
        "xgen-scale snapshot specs={specs} operations={ops} path={path}\nspecs_csv={csv}"
    ).format(
        specs=manifest.get("spec_count"),
        ops=manifest.get("operation_count"),
        path=manifest.get("manifest_path"),
        csv=manifest.get("specs_csv"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swagger-url", default=DEFAULT_X2BEE_SWAGGER_URL)
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        help="Direct spec URL or local spec file. May be repeated. Skips Swagger discovery.",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-response-bytes", type=int, default=5_000_000)
    parser.add_argument("--allow-private-hosts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    manifest = snapshot_specs(
        out_dir=args.out_dir,
        swagger_url=args.swagger_url,
        spec_sources=args.spec or None,
        max_response_bytes=args.max_response_bytes,
        allow_private_hosts=args.allow_private_hosts,
    )
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(format_manifest(manifest))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
