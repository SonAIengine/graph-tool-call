from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from graph_tool_call import ToolGraph
from graph_tool_call.graphify import (
    COLLECTION_GRAPH_VERSION,
    build_openapi_collection_artifact,
)


def _collection_spec() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Collection API", "version": "1.0.0"},
        "paths": {
            "/brands": {
                "get": {
                    "operationId": "listBrands",
                    "summary": "브랜드 목록 조회",
                    "parameters": [
                        {
                            "name": "siteNo",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "type": "object",
                                                "properties": {
                                                    "items": {
                                                        "type": "array",
                                                        "items": {
                                                            "type": "object",
                                                            "properties": {
                                                                "brandNo": {"type": "string"},
                                                                "brandName": {"type": "string"},
                                                            },
                                                        },
                                                    }
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/products": {
                "post": {
                    "operationId": "createProduct",
                    "summary": "상품 등록",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["brandNo", "productName"],
                                    "properties": {
                                        "brandNo": {"type": "string"},
                                        "productName": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"productNo": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }


def test_build_openapi_collection_artifact_is_loadable_and_preserves_build_evidence(
    tmp_path: Path,
) -> None:
    artifact = build_openapi_collection_artifact(
        _collection_spec(),
        context_field_names={"siteNo"},
        promote_contract_signals=True,
    )

    assert artifact["collection_graph_version"] == COLLECTION_GRAPH_VERSION
    assert artifact["metadata"]["collection_graph_version"] == COLLECTION_GRAPH_VERSION
    assert artifact["readiness_report"]["summary"]["tool_count"] == 2
    assert artifact["readiness_report"]["coverage"]["context_field_count"] == 1
    assert artifact["source_snapshot_manifest"]["spec_count"] == 1
    assert artifact["source_snapshot_manifest"]["operation_count"] == 2
    assert len(artifact["source_snapshot_manifest"]["specs"][0]["sha256"]) == 64
    assert artifact["ingest_summary"]["registered_tool_count"] == 2
    assert artifact["edge_stats"]["tool_count"] == 2
    assert "graph" in artifact and "tools" in artifact

    path = tmp_path / "collection.json"
    path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    loaded = ToolGraph.load(path)

    assert set(loaded.tools) == {"listBrands", "createProduct"}
    assert loaded.metadata["readiness_summary"]["tool_count"] == 2
    assert loaded.metadata["source_snapshot_manifest"]["specs"][0]["title"] == "Collection API"


def test_build_openapi_collection_artifact_dedupes_multiple_sources() -> None:
    first = _collection_spec()
    second = _collection_spec()
    second["info"] = {"title": "Duplicate Collection API", "version": "1.0.0"}

    artifact = build_openapi_collection_artifact([first, second])

    assert artifact["source_snapshot_manifest"]["spec_count"] == 2
    assert artifact["ingest_summary"]["ingested_tool_total"] == 4
    assert artifact["ingest_summary"]["registered_tool_count"] == 2
    assert artifact["ingest_summary"]["duplicate_tool_count"] == 2


def test_build_openapi_collection_cli_writes_artifact(tmp_path: Path) -> None:
    spec_path = tmp_path / "openapi.json"
    artifact_path = tmp_path / "collection.json"
    spec_path.write_text(json.dumps(_collection_spec()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "graph_tool_call",
            "build-openapi-collection",
            str(spec_path),
            "-o",
            str(artifact_path),
            "--context-field",
            "siteNo",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert "Built OpenAPI collection:" in result.stdout
    assert payload["readiness_report"]["summary"]["tool_count"] == 2
    assert payload["metadata"]["build_options"]["context_field_names"] == ["siteNo"]
