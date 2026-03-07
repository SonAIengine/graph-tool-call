"""Tests for visualization and export modules."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolSchema


def _make_graph() -> ToolGraph:
    """Create a small test graph with tools, categories, and relations."""
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="get_user", description="Get a user by ID", parameters=[]))
    tg.add_tool(ToolSchema(name="create_user", description="Create a new user", parameters=[]))
    tg.add_tool(ToolSchema(name="delete_user", description="Delete a user", parameters=[]))
    tg.add_category("user_management")
    tg.assign_category("get_user", "user_management")
    tg.assign_category("create_user", "user_management")
    tg.assign_category("delete_user", "user_management")
    tg.add_relation("create_user", "get_user", "requires")
    tg.add_relation("create_user", "delete_user", "complementary")
    return tg


# --- GraphML ---


class TestGraphMLExport:
    def test_export_creates_file(self):
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.graphml"
            tg.export_graphml(out)
            assert out.exists()
            content = out.read_text()
            assert "graphml" in content
            assert "get_user" in content
            assert "create_user" in content

    def test_export_contains_node_types(self):
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.graphml"
            tg.export_graphml(out)
            content = out.read_text()
            assert "tool" in content.lower()
            assert "category" in content.lower()

    def test_export_contains_edges(self):
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.graphml"
            tg.export_graphml(out)
            content = out.read_text()
            assert "requires" in content.lower() or "relation" in content.lower()


# --- Cypher ---


class TestCypherExport:
    def test_export_creates_file(self):
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.cypher"
            tg.export_cypher(out)
            assert out.exists()
            content = out.read_text()
            assert "CREATE" in content

    def test_export_contains_nodes(self):
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.cypher"
            tg.export_cypher(out)
            content = out.read_text()
            assert "get_user" in content
            assert "create_user" in content
            assert ":Tool" in content
            assert ":Category" in content

    def test_export_contains_relations(self):
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.cypher"
            tg.export_cypher(out)
            content = out.read_text()
            assert "REQUIRES" in content
            assert "COMPLEMENTARY" in content

    def test_escapes_special_chars(self):
        tg = ToolGraph()
        tg.add_tool(ToolSchema(name="test_tool", description='It\'s a "test" tool', parameters=[]))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.cypher"
            tg.export_cypher(out)
            content = out.read_text()
            # Should not break Cypher syntax
            assert "CREATE" in content


# --- HTML (Pyvis) ---


class TestHTMLExport:
    def test_export_creates_file(self):
        pytest.importorskip("pyvis")
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.html"
            tg.export_html(out)
            assert out.exists()
            content = out.read_text()
            assert "<html" in content.lower() or "<!doctype" in content.lower()
            assert "get_user" in content

    def test_export_without_physics(self):
        pytest.importorskip("pyvis")
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.html"
            tg.export_html(out, physics=False)
            assert out.exists()

    def test_import_error_without_pyvis(self, monkeypatch):
        import graph_tool_call.visualization.html_export as mod

        monkeypatch.setattr(mod, "Network", None)
        tg = _make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.html"
            with pytest.raises(ImportError, match="pyvis"):
                tg.export_html(out)


# --- CLI ---


class TestCLI:
    def test_version(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "graph_tool_call", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "graph-tool-call" in result.stdout

    def test_help(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "graph_tool_call", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "ingest" in result.stdout
        assert "retrieve" in result.stdout

    def test_ingest_and_info(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(__file__).parent / "fixtures" / "petstore_swagger2.json"
            if not fixture.exists():
                pytest.skip("petstore fixture not found")
            out = Path(tmpdir) / "graph.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graph_tool_call",
                    "ingest",
                    str(fixture),
                    "-o",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert out.exists()

            # info
            result2 = subprocess.run(
                [sys.executable, "-m", "graph_tool_call", "info", str(out)],
                capture_output=True,
                text=True,
            )
            assert result2.returncode == 0
            assert "ToolGraph" in result2.stdout

    def test_retrieve(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(__file__).parent / "fixtures" / "petstore_swagger2.json"
            if not fixture.exists():
                pytest.skip("petstore fixture not found")
            graph_path = Path(tmpdir) / "graph.json"
            # Ingest first
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graph_tool_call",
                    "ingest",
                    str(fixture),
                    "-o",
                    str(graph_path),
                ],
                capture_output=True,
                text=True,
            )
            # Retrieve
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graph_tool_call",
                    "retrieve",
                    "add a pet",
                    "-g",
                    str(graph_path),
                    "-k",
                    "3",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "Results" in result.stdout
