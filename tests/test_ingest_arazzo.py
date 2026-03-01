"""Tests for Arazzo 1.0.0 workflow ingestion (Phase 2)."""

from __future__ import annotations

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


class TestIngestArazzoFile:
    def test_yaml_file(self):
        pytest.importorskip("yaml")
        relations = ingest_arazzo("tests/fixtures/petstore_arazzo.yaml")
        assert len(relations) >= 2
        # adoptPet workflow: listPets → getPetById → updatePet
        assert any(r.source == "listPets" and r.target == "getPetById" for r in relations)
        assert any(r.source == "getPetById" and r.target == "updatePet" for r in relations)


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
