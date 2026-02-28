"""Tests for tool schema parsing (OpenAI, Anthropic, LangChain formats)."""

from graph_tool_call.core.tool import ToolSchema, parse_tool


def test_parse_openai_function_format():
    tool = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                    },
                },
                "required": ["location"],
            },
        },
    }

    schema = parse_tool(tool)
    assert schema.name == "get_weather"
    assert schema.description == "Get current weather for a location"
    assert len(schema.parameters) == 2
    assert schema.parameters[0].name == "location"
    assert schema.parameters[0].required is True
    assert schema.parameters[1].enum == ["celsius", "fahrenheit"]


def test_parse_openai_legacy_format():
    tool = {
        "name": "search",
        "description": "Search the web",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    }

    schema = parse_tool(tool)
    assert schema.name == "search"
    assert len(schema.parameters) == 1


def test_parse_anthropic_format():
    tool = {
        "name": "read_file",
        "description": "Read contents of a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "encoding": {"type": "string", "description": "File encoding"},
            },
            "required": ["path"],
        },
    }

    schema = parse_tool(tool)
    assert schema.name == "read_file"
    assert len(schema.parameters) == 2
    assert schema.parameters[0].required is True
    assert schema.parameters[1].required is False


def test_parse_langchain_style():
    class MockTool:
        name = "calculator"
        description = "Perform math calculations"
        args_schema = None

    schema = parse_tool(MockTool())
    assert schema.name == "calculator"
    assert schema.description == "Perform math calculations"


def test_parse_tool_schema_passthrough():
    original = ToolSchema(name="my_tool", description="A tool")
    result = parse_tool(original)
    assert result is original


def test_tool_schema_tags_and_domain():
    schema = ToolSchema(
        name="db_query",
        description="Query a database",
        tags=["database", "sql"],
        domain="data",
    )
    assert schema.tags == ["database", "sql"]
    assert schema.domain == "data"
