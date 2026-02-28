"""Tests for graph_tool_call.ingest.functions."""

from __future__ import annotations

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ingest.functions import ingest_function, ingest_functions

# ---------------------------------------------------------------------------
# Sample functions for testing
# ---------------------------------------------------------------------------


def greet(name: str, times: int = 1) -> str:
    """Say hello to someone.

    Longer description that should be ignored.
    """
    return f"Hello, {name}! " * times


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def no_hints(x, y):
    """Function without type hints."""
    return x + y


def no_docstring(value: float) -> float:
    return value * 2


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestSimpleFunction:
    def test_ingest_simple_function(self) -> None:
        tool = ingest_function(add)
        assert isinstance(tool, ToolSchema)
        assert tool.name == "add"
        assert tool.description == "Add two numbers."
        assert len(tool.parameters) == 2
        param_names = {p.name for p in tool.parameters}
        assert param_names == {"a", "b"}
        for p in tool.parameters:
            assert p.type == "integer"
            assert p.required is True


class TestIngestFunctionWithDocstring:
    def test_ingest_function_with_docstring(self) -> None:
        tool = ingest_function(greet)
        # Only the first line of the docstring should be used
        assert tool.description == "Say hello to someone."


class TestIngestFunctionDefaultParams:
    def test_ingest_function_default_params(self) -> None:
        tool = ingest_function(greet)
        params_by_name = {p.name: p for p in tool.parameters}
        # 'name' has no default -> required
        assert params_by_name["name"].required is True
        assert params_by_name["name"].type == "string"
        # 'times' has default=1 -> not required
        assert params_by_name["times"].required is False
        assert params_by_name["times"].type == "integer"


class TestIngestFunctionsMultiple:
    def test_ingest_functions_multiple(self) -> None:
        tools = ingest_functions([greet, add, no_hints])
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"greet", "add", "no_hints"}


class TestIngestFunctionNoHints:
    def test_ingest_function_no_hints(self) -> None:
        tool = ingest_function(no_hints)
        assert tool.name == "no_hints"
        # Without type hints, params should default to "string"
        for p in tool.parameters:
            assert p.type == "string"
        assert len(tool.parameters) == 2


class TestIngestFunctionNoDocstring:
    def test_ingest_function_no_docstring(self) -> None:
        tool = ingest_function(no_docstring)
        assert tool.description == ""
        assert len(tool.parameters) == 1
        assert tool.parameters[0].type == "number"
