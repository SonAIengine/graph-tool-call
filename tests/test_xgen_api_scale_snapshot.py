from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from benchmarks.xgen_api_scale import manifest as snapshot_manifest
from benchmarks.xgen_api_scale import snapshot
from benchmarks.xgen_api_scale.run import main, run_benchmark


def test_xgen_api_scale_snapshot_writes_reusable_manifest(tmp_path: Path):
    out_dir = tmp_path / "snapshot"

    manifest = snapshot.snapshot_specs(
        out_dir=out_dir,
        spec_sources=[
            _spec("Snapshot Catalog", {"/brands": _operation("searchBrands", "Brand search")}),
            _spec("Snapshot Orders", {"/orders": _operation("listOrders", "Order list")}),
        ],
    )

    manifest_path = out_dir / "manifest.json"
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_path"] == str(manifest_path)
    assert saved_manifest["manifest_path"] == "manifest.json"
    assert manifest_path.exists()
    assert manifest["snapshot"] == "xgen_api_scale_openapi_snapshot"
    assert manifest["spec_count"] == 2
    assert manifest["operation_count"] == 2
    assert manifest["specs_csv"] == ",".join(row["path"] for row in manifest["specs"])
    assert all(not Path(str(row["path"])).is_absolute() for row in saved_manifest["specs"])

    for row in manifest["specs"]:
        spec_path = out_dir / str(row["path"])
        assert spec_path.exists()
        digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        assert row["sha256"] == digest
        assert row["operation_count"] == 1

    manifest_sources = snapshot_manifest.spec_sources_from_manifest(manifest_path)
    report = run_benchmark(
        spec_sources=manifest_sources,
        cases_path=None,
        min_unique_tools=2,
        max_build_seconds=10,
    )
    assert report["status"] == "pass"
    assert report["scale"]["spec_count"] == 2
    assert report["gate"]["status"] == "pass"

    assert manifest_sources == [
        str((out_dir / str(row["path"])).resolve()) for row in manifest["specs"]
    ]


def test_xgen_api_scale_snapshot_manifest_survives_directory_move(tmp_path: Path):
    out_dir = tmp_path / "snapshot"
    moved_dir = tmp_path / "moved-snapshot"
    snapshot.snapshot_specs(
        out_dir=out_dir,
        spec_sources=[
            _spec("Snapshot Catalog", {"/brands": _operation("searchBrands", "Brand search")}),
        ],
    )

    shutil.copytree(out_dir, moved_dir)
    moved_sources = snapshot_manifest.spec_sources_from_manifest(moved_dir / "manifest.json")

    assert moved_sources == [
        str(next(path for path in moved_dir.iterdir() if path.name.startswith("01_")).resolve())
    ]


def test_xgen_api_scale_snapshot_cli_accepts_local_specs(tmp_path: Path, capsys):
    spec_path = tmp_path / "catalog.json"
    out_dir = tmp_path / "snapshot"
    spec_path.write_text(
        json.dumps(
            _spec("Snapshot Catalog", {"/brands": _operation("searchBrands", "Brand search")})
        ),
        encoding="utf-8",
    )

    assert snapshot.main(["--spec", str(spec_path), "--out-dir", str(out_dir), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["spec_count"] == 1
    assert payload["specs"][0]["source"] == str(spec_path)
    assert payload["specs_csv"] == payload["specs"][0]["path"]
    assert not Path(payload["specs"][0]["path"]).is_absolute()


def test_xgen_api_scale_run_cli_accepts_verified_manifest(tmp_path: Path):
    out_dir = tmp_path / "snapshot"
    output_path = tmp_path / "report.json"
    manifest = snapshot.snapshot_specs(
        out_dir=out_dir,
        spec_sources=[
            _spec("Snapshot Catalog", {"/brands": _operation("searchBrands", "Brand search")}),
        ],
    )

    exit_code = main(
        [
            "--manifest",
            str(manifest["manifest_path"]),
            "--no-cases",
            "--min-unique-tools",
            "1",
            "--max-build-seconds",
            "10",
            "--output",
            str(output_path),
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["status"] == "pass"
    assert report["scale"]["unique_tool_count"] == 1
    assert report["specs"][0]["source"] == str((out_dir / manifest["specs"][0]["path"]).resolve())
    assert report["snapshot_manifests"][0]["manifest_path"] == str(manifest["manifest_path"])
    assert report["snapshot_manifests"][0]["spec_count"] == 1
    assert report["snapshot_manifests"][0]["specs"][0]["sha256"] == manifest["specs"][0]["sha256"]


def test_xgen_api_scale_manifest_detects_snapshot_tampering(tmp_path: Path):
    out_dir = tmp_path / "snapshot"
    manifest = snapshot.snapshot_specs(
        out_dir=out_dir,
        spec_sources=[
            _spec("Snapshot Catalog", {"/brands": _operation("searchBrands", "Brand search")}),
        ],
    )
    spec_path = out_dir / str(manifest["specs"][0]["path"])
    spec_path.write_text(
        json.dumps(_spec("Tampered Catalog", {"/orders": _operation("listOrders", "Order list")})),
        encoding="utf-8",
    )

    with pytest.raises(snapshot_manifest.SnapshotManifestError, match="sha256 mismatch"):
        snapshot_manifest.spec_sources_from_manifest(str(manifest["manifest_path"]))


def _spec(title: str, paths: dict[str, object]) -> dict[str, object]:
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": "1.0.0"},
        "paths": paths,
    }


def _operation(operation_id: str, summary: str) -> dict[str, object]:
    return {
        "get": {
            "operationId": operation_id,
            "summary": summary,
            "responses": {
                "200": {
                    "description": "OK",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}},
                            }
                        }
                    },
                }
            },
        }
    }
