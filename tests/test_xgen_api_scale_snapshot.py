from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmarks.xgen_api_scale import snapshot
from benchmarks.xgen_api_scale.run import run_benchmark


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
    assert saved_manifest["manifest_path"] == str(manifest_path)
    assert manifest_path.exists()
    assert manifest["snapshot"] == "xgen_api_scale_openapi_snapshot"
    assert manifest["spec_count"] == 2
    assert manifest["operation_count"] == 2
    assert manifest["specs_csv"] == ",".join(row["path"] for row in manifest["specs"])

    for row in manifest["specs"]:
        spec_path = Path(str(row["path"]))
        assert spec_path.exists()
        digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        assert row["sha256"] == digest
        assert row["operation_count"] == 1

    report = run_benchmark(
        spec_sources=[str(row["path"]) for row in manifest["specs"]],
        cases_path=None,
        min_unique_tools=2,
        max_build_seconds=10,
    )
    assert report["status"] == "pass"
    assert report["scale"]["spec_count"] == 2
    assert report["gate"]["status"] == "pass"


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
