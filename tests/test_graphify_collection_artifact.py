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
from graph_tool_call.plan import PathSynthesizer


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
    assert artifact["edge_stats"]["arazzo_workflows"] == {
        "added": 0,
        "merged": 0,
        "binding_aliases_added": 0,
    }
    assert artifact["semantic_summary"]["canonical_action_known_rate"] == 1.0
    assert artifact["semantic_summary"]["primary_resource_assigned_rate"] == 1.0
    assert artifact["edge_quality_summary"]["total"] == len(artifact["graph"]["edges"])
    assert artifact["metadata"]["semantic_summary"]["path_module_assigned_rate"] == 1.0
    assert artifact["metadata"]["edge_quality_summary"]["total"] == len(artifact["graph"]["edges"])
    assert artifact["metadata"]["build_options"]["derive_semantic_metadata"] is True
    assert "graph" in artifact and "tools" in artifact
    list_brands_ai = artifact["tools"]["listBrands"]["metadata"]["ai_metadata"]
    assert list_brands_ai["canonical_action"] == "search"
    assert list_brands_ai["result_shape"] == "list"
    assert artifact["tools"]["createProduct"]["metadata"]["ai_metadata"]["primary_resource"] == (
        "products"
    )
    assert artifact["tools"]["createProduct"]["metadata"]["ai_metadata"]["result_shape"] == (
        "mutation"
    )
    assert artifact["semantic_summary"]["result_shape_counts"]["list"] == 1
    assert artifact["semantic_summary"]["result_shape_counts"]["mutation"] == 1

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


def test_build_openapi_collection_artifact_applies_arazzo_order_and_binding() -> None:
    workflow = {
        "arazzo": "1.1.0",
        "info": {"title": "Product workflow", "version": "1.0.0"},
        "sourceDescriptions": [],
        "workflows": [
            {
                "workflowId": "createProductFlow",
                "steps": [
                    {
                        "stepId": "brands",
                        "operationId": "listBrands",
                        "outputs": {"brandId": "$response.body#/data/items/0/brandNo"},
                    },
                    {
                        "stepId": "create",
                        "operationId": "createProduct",
                        "parameters": [
                            {
                                "name": "brandNo",
                                "in": "body",
                                "value": "$steps.brands.outputs.brandId",
                            }
                        ],
                    },
                ],
            }
        ],
    }

    artifact = build_openapi_collection_artifact(
        _collection_spec(),
        workflow_sources=workflow,
        context_field_names={"siteNo"},
    )

    summary = artifact["workflow_summary"]
    assert summary["source_count"] == 1
    assert summary["workflow_count"] == 1
    assert summary["relation_count"] == 1
    assert summary["by_dependency_kind"] == {"runtime_reference": 1}
    assert summary["edge_stats"] == {
        "added": 1,
        "merged": 0,
        "binding_aliases_added": 1,
    }
    assert artifact["metadata"]["workflow_summary"] == summary
    assert artifact["metadata"]["build_options"]["workflow_source_count"] == 1
    assert artifact["edge_quality_summary"]["workflow"] == 1
    edge = next(
        edge
        for edge in artifact["graph"]["edges"]
        if edge["source"] == "listBrands" and edge["target"] == "createProduct"
    )
    assert edge["relation"] == "precedes"
    assert edge["evidence_sources"] == ["arazzo"]
    assert edge["data_flow"]["from_path"] == "$.data.items[0].brandNo"
    assert edge["data_flow"]["to_field"] == "brandNo"
    aliases = artifact["tools"]["listBrands"]["metadata"]["produces"]
    assert any(
        row.get("field_name") == "brandNo"
        and row.get("json_path") == "$.data.items[0].brandNo"
        and row.get("contract_source") == "arazzo"
        for row in aliases
    )

    plan = PathSynthesizer(artifact).synthesize(
        target="createProduct",
        goal="상품 등록",
        entities={"productName": "Example", "siteNo": "1"},
    )

    assert [step.tool for step in plan.steps] == ["listBrands", "createProduct"]
    assert plan.steps[-1].args["brandNo"] == "${s1.data.items[0].brandNo}"


def test_build_openapi_collection_artifact_resolves_arazzo_operation_path() -> None:
    workflow = {
        "arazzo": "1.1.0",
        "info": {"title": "Path workflow", "version": "1.0.0"},
        "sourceDescriptions": [],
        "workflows": [
            {
                "workflowId": "pathFlow",
                "steps": [
                    {
                        "stepId": "brands",
                        "operationPath": ("{$sourceDescriptions.api.url}#/paths/~1brands/get"),
                    },
                    {
                        "stepId": "create",
                        "operationPath": ("{$sourceDescriptions.api.url}#/paths/~1products/post"),
                    },
                ],
            }
        ],
    }

    artifact = build_openapi_collection_artifact(
        _collection_spec(),
        workflow_sources=workflow,
    )

    assert artifact["workflow_summary"]["relation_count"] == 1
    assert any(
        edge["source"] == "listBrands"
        and edge["target"] == "createProduct"
        and edge["evidence_sources"] == ["arazzo"]
        for edge in artifact["graph"]["edges"]
    )


def test_build_openapi_collection_cli_writes_artifact(tmp_path: Path) -> None:
    spec_path = tmp_path / "openapi.json"
    workflow_path = tmp_path / "arazzo.json"
    artifact_path = tmp_path / "collection.json"
    spec_path.write_text(json.dumps(_collection_spec()), encoding="utf-8")
    workflow_path.write_text(
        json.dumps(
            {
                "arazzo": "1.1.0",
                "info": {"title": "CLI workflow", "version": "1.0.0"},
                "sourceDescriptions": [],
                "workflows": [
                    {
                        "workflowId": "create-product",
                        "steps": [
                            {"stepId": "brands", "operationId": "listBrands"},
                            {"stepId": "create", "operationId": "createProduct"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "graph_tool_call",
            "build-openapi-collection",
            str(spec_path),
            "-o",
            str(artifact_path),
            "--workflow",
            str(workflow_path),
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
    assert payload["metadata"]["build_options"]["derive_semantic_metadata"] is True
    assert payload["semantic_summary"]["canonical_action_known_rate"] == 1.0
    assert payload["workflow_summary"]["relation_count"] == 1
