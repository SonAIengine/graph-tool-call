"""Tests for Arazzo 1.0.0 workflow ingestion (Phase 2)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from graph_tool_call.ingest.arazzo import ingest_arazzo
from graph_tool_call.ontology.schema import RelationType

# ---------- helpers ----------


def _simple_arazzo() -> dict:
    return {
        "arazzo": "1.0.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "sourceDescriptions": [],
        "workflows": [
            {
                "workflowId": "flow1",
                "steps": [
                    {"stepId": "step1", "operationId": "createItem"},
                    {"stepId": "step2", "operationId": "getItem", "dependsOn": ["step1"]},
                    {"stepId": "step3", "operationId": "deleteItem", "dependsOn": ["step2"]},
                ],
            }
        ],
    }


# ---------- Tests ----------


class TestIngestArazzoDict:
    def test_simple_workflow(self):
        relations = ingest_arazzo(_simple_arazzo())
        assert len(relations) >= 2
        # createItem → getItem (dependsOn)
        assert any(r.source == "createItem" and r.target == "getItem" for r in relations)
        # getItem → deleteItem (dependsOn)
        assert any(r.source == "getItem" and r.target == "deleteItem" for r in relations)
        # All should be PRECEDES
        assert all(r.relation_type == RelationType.PRECEDES for r in relations)

    def test_multiple_depends_on(self):
        spec = {
            "arazzo": "1.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "sourceDescriptions": [],
            "workflows": [
                {
                    "workflowId": "flow1",
                    "steps": [
                        {"stepId": "auth", "operationId": "authenticate"},
                        {"stepId": "load", "operationId": "loadData"},
                        {
                            "stepId": "process",
                            "operationId": "processData",
                            "dependsOn": ["auth", "load"],
                        },
                    ],
                }
            ],
        }
        relations = ingest_arazzo(spec)
        # Both auth → processData and loadData → processData should exist
        sources_to_process = {r.source for r in relations if r.target == "processData"}
        assert "authenticate" in sources_to_process
        assert "loadData" in sources_to_process

    def test_missing_operation_id_skipped(self):
        spec = {
            "arazzo": "1.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "sourceDescriptions": [],
            "workflows": [
                {
                    "workflowId": "flow1",
                    "steps": [
                        {"stepId": "step1", "operationId": "createItem"},
                        {
                            "stepId": "step2",
                            "operationPath": "petstore#/paths/~1pets/get",  # not an operationId
                            "dependsOn": ["step1"],
                        },
                    ],
                }
            ],
        }
        relations = ingest_arazzo(spec)
        # step2 has no extractable operationId (it uses operationPath with #)
        # So no dependsOn relation should be created for step2
        assert all(r.target != "step2" for r in relations)

    def test_registered_tools_filter(self):
        """Only emit relations for registered tools."""
        relations = ingest_arazzo(_simple_arazzo(), registered_tools={"createItem", "getItem"})
        # createItem → getItem should exist
        assert any(r.source == "createItem" and r.target == "getItem" for r in relations)
        # deleteItem is not registered, so no relation involving it
        assert all(r.source != "deleteItem" and r.target != "deleteItem" for r in relations)

    def test_sequential_ordering(self):
        """Steps without dependsOn still get sequential PRECEDES."""
        spec = {
            "arazzo": "1.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "sourceDescriptions": [],
            "workflows": [
                {
                    "workflowId": "flow1",
                    "steps": [
                        {"stepId": "s1", "operationId": "op1"},
                        {"stepId": "s2", "operationId": "op2"},
                        {"stepId": "s3", "operationId": "op3"},
                    ],
                }
            ],
        }
        relations = ingest_arazzo(spec)
        # op1 → op2, op2 → op3 from sequential ordering
        assert any(r.source == "op1" and r.target == "op2" for r in relations)
        assert any(r.source == "op2" and r.target == "op3" for r in relations)

    def test_runtime_output_reference_is_implicit_dependency_with_binding(self):
        spec = {
            "arazzo": "1.1.0",
            "info": {"title": "Runtime binding", "version": "1.0.0"},
            "sourceDescriptions": [],
            "workflows": [
                {
                    "workflowId": "profileFlow",
                    "steps": [
                        {
                            "stepId": "createStep",
                            "operationId": "createProfile",
                            "outputs": {"profileId": "$response.body#/id"},
                        },
                        {
                            "stepId": "readStep",
                            "operationId": "getProfile",
                            "parameters": [
                                {
                                    "name": "userId",
                                    "in": "path",
                                    "value": "$steps.createStep.outputs.profileId",
                                }
                            ],
                        },
                    ],
                }
            ],
        }

        relations = ingest_arazzo(spec)

        assert len(relations) == 1
        relation = relations[0]
        assert relation.source == "createProfile"
        assert relation.target == "getProfile"
        assert relation.dependency_kind == "runtime_reference"
        assert relation.bindings == (
            {
                "source_step_id": "createStep",
                "source_output": "profileId",
                "source_path": "$.id",
                "target_field": "userId",
                "target_location": "path",
                "expression": "$steps.createStep.outputs.profileId",
            },
        )

    def test_qualified_operation_id_uses_registered_operation_tail(self):
        spec = {
            "arazzo": "1.1.0",
            "info": {"title": "Qualified operations", "version": "1.0.0"},
            "sourceDescriptions": [],
            "workflows": [
                {
                    "workflowId": "flow",
                    "steps": [
                        {
                            "stepId": "first",
                            "operationId": "$sourceDescriptions.store.createItem",
                        },
                        {
                            "stepId": "second",
                            "operationId": "$sourceDescriptions.store.getItem",
                        },
                    ],
                }
            ],
        }

        relations = ingest_arazzo(spec, registered_tools={"createItem", "getItem"})

        assert [(row.source, row.target) for row in relations] == [("createItem", "getItem")]

    def test_nested_request_body_binding_preserves_leaf_and_target_path(self):
        spec = {
            "arazzo": "1.1.0",
            "info": {"title": "Body binding", "version": "1.0.0"},
            "sourceDescriptions": [],
            "workflows": [
                {
                    "workflowId": "bodyFlow",
                    "steps": [
                        {
                            "stepId": "lookup",
                            "operationId": "lookupOrder",
                            "outputs": {"orderId": "$response.body#/items/0/id"},
                        },
                        {
                            "stepId": "submit",
                            "operationId": "submitOrder",
                            "requestBody": {
                                "contentType": "application/json",
                                "payload": {
                                    "order": {
                                        "orderId": "$steps.lookup.outputs.orderId",
                                    }
                                },
                            },
                        },
                    ],
                }
            ],
        }

        relations = ingest_arazzo(spec)

        assert relations[0].bindings[0]["target_field"] == "orderId"
        assert relations[0].bindings[0]["target_location"] == "request_body"
        assert relations[0].bindings[0]["target_path"] == "requestBody.payload.order.orderId"

    def test_runtime_binding_does_not_persist_surrounding_literal_text(self):
        spec = {
            "arazzo": "1.1.0",
            "info": {"title": "Safe binding", "version": "1.0.0"},
            "sourceDescriptions": [],
            "workflows": [
                {
                    "workflowId": "safeFlow",
                    "steps": [
                        {
                            "stepId": "lookup",
                            "operationId": "lookupOrder",
                            "outputs": {"orderId": "$response.body#/id"},
                        },
                        {
                            "stepId": "read",
                            "operationId": "readOrder",
                            "parameters": [
                                {
                                    "name": "orderId",
                                    "in": "path",
                                    "value": "Bearer $steps.lookup.outputs.orderId trailing-secret",
                                }
                            ],
                        },
                    ],
                }
            ],
        }

        relation = ingest_arazzo(spec)[0]

        assert relation.bindings[0]["expression"] == "$steps.lookup.outputs.orderId"
        assert "Bearer" not in str(relation.bindings)
        assert "trailing-secret" not in str(relation.bindings)


class TestIngestArazzoFile:
    def test_yaml_file(self):
        pytest.importorskip("yaml")
        relations = ingest_arazzo("tests/fixtures/petstore_arazzo.yaml")
        assert len(relations) >= 2
        # adoptPet workflow: listPets → getPetById → updatePet
        assert any(r.source == "listPets" and r.target == "getPetById" for r in relations)
        assert any(r.source == "getPetById" and r.target == "updatePet" for r in relations)


class TestRemoteSafety:
    def test_private_host_blocked_by_default(self):
        with pytest.raises(ConnectionError, match="private or local host"):
            ingest_arazzo("http://127.0.0.1/workflow.json")

    def test_private_host_allowed_with_opt_in(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(_simple_arazzo()).encode()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "http://127.0.0.1/workflow.json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            relations = ingest_arazzo(
                "http://127.0.0.1/workflow.json",
                allow_private_hosts=True,
            )
        assert len(relations) >= 2

    def test_remote_yaml_is_supported(self):
        pytest.importorskip("yaml")
        yaml_text = """
arazzo: 1.1.0
info: {title: Remote, version: 1.0.0}
sourceDescriptions: []
workflows:
  - workflowId: remote
    steps:
      - {stepId: first, operationId: firstOperation}
      - {stepId: second, operationId: secondOperation}
"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = yaml_text.encode()
        mock_resp.headers = {"Content-Type": "application/yaml"}
        mock_resp.geturl.return_value = "https://example.com/arazzo.yaml"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            relations = ingest_arazzo("https://example.com/arazzo.yaml")

        assert [(row.source, row.target) for row in relations] == [
            ("firstOperation", "secondOperation")
        ]


class TestToolGraphIntegration:
    def test_ingest_arazzo(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        # First register the tools
        for name in ["createItem", "getItem", "deleteItem"]:
            tg.add_tool(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"{name} operation",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            )

        relations = tg.ingest_arazzo(_simple_arazzo())
        assert len(relations) >= 2

        # Check graph has PRECEDES edges
        graph = tg.graph
        edges = graph.edges()
        precedes_edges = [(s, t) for s, t, d in edges if d.get("relation") == RelationType.PRECEDES]
        assert len(precedes_edges) >= 2

    def test_ingest_arazzo_unregistered_tools_ignored(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        # Only register createItem, not getItem/deleteItem
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "createItem",
                    "description": "Create",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )

        relations = tg.ingest_arazzo(_simple_arazzo())
        # No relations because getItem/deleteItem are not registered
        assert len(relations) == 0
