"""Tests for graph_tool_call.compressor module."""

from __future__ import annotations

import json

from graph_tool_call.compressor import CompressConfig, compress_tool_result
from graph_tool_call.compressor.error_comp import (
    compress_error_dict,
    compress_error_text,
    is_error_dict,
    is_error_text,
)
from graph_tool_call.compressor.html_comp import (
    compress_html,
    is_html,
)
from graph_tool_call.compressor.json_comp import compress_json_dict, compress_json_list
from graph_tool_call.compressor.text_comp import compress_text

# ---------------------------------------------------------------------------
# TextCompressor
# ---------------------------------------------------------------------------


class TestTextCompressor:
    def test_short_text_unchanged(self):
        text = "Hello, world!"
        assert compress_text(text, CompressConfig()) == text

    def test_long_text_head_tail(self):
        text = "A" * 10000
        result = compress_text(text, CompressConfig(max_chars=1000))
        assert len(result) < 10000
        assert "chars omitted" in result
        assert result.startswith("A")
        assert result.endswith("A")

    def test_exact_boundary(self):
        text = "x" * 4000
        assert compress_text(text, CompressConfig(max_chars=4000)) == text

    def test_one_over_boundary(self):
        text = "x" * 4001
        result = compress_text(text, CompressConfig(max_chars=4000))
        assert "chars omitted" in result


# ---------------------------------------------------------------------------
# ErrorCompressor
# ---------------------------------------------------------------------------


class TestErrorCompressor:
    def test_http_error_dict(self):
        data = {"status": 401, "error": "Unauthorized", "body": {"detail": "인증이 필요합니다"}}
        result = compress_error_dict(data, CompressConfig())
        assert "401" in result
        assert "인증이 필요합니다" in result

    def test_error_with_status_code_key(self):
        data = {"status_code": 500, "message": "Internal Server Error"}
        assert is_error_dict(data)
        result = compress_error_dict(data, CompressConfig())
        assert "500" in result

    def test_error_without_status(self):
        data = {"error": "Something went wrong", "traceback": "..."}
        assert is_error_dict(data)

    def test_non_error_dict(self):
        data = {"name": "test", "value": 42}
        assert not is_error_dict(data)

    def test_traceback_text(self):
        text = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 10, in <module>\n'
            "    raise ValueError('bad value')\n"
            "ValueError: bad value"
        )
        assert is_error_text(text)
        result = compress_error_text(text, CompressConfig())
        assert "ValueError" in result

    def test_non_error_text(self):
        assert not is_error_text("Hello, world!")


# ---------------------------------------------------------------------------
# JsonCompressor
# ---------------------------------------------------------------------------


class TestJsonCompressor:
    def test_small_dict_unchanged(self):
        data = {"id": "1", "name": "test"}
        result = compress_json_dict(data, CompressConfig())
        parsed = json.loads(result)
        assert parsed["id"] == "1"
        assert parsed["name"] == "test"

    def test_large_list_compressed(self):
        data = [{"id": str(i), "name": f"item_{i}", "description": "x" * 300} for i in range(50)]
        result = compress_json_list(data, CompressConfig(max_list_items=3))
        parsed = json.loads(result)
        assert parsed["_compressed"] is True
        assert parsed["total"] == 50
        assert len(parsed["samples"]) == 3
        assert parsed["omitted"] == 47
        assert "schema" in parsed

    def test_list_schema_extraction(self):
        data = [{"id": 1, "name": "a", "active": True}, {"id": 2, "name": "b", "active": False}]
        result = compress_json_list(data, CompressConfig(max_list_items=2))
        parsed = json.loads(result)
        schema = parsed["schema"]
        assert schema["id"] == "int"
        assert schema["name"] == "str"
        assert schema["active"] == "bool"

    def test_nested_dict_flattened(self):
        data = {
            "id": "1",
            "metadata": {
                "created": "2024-01-01",
                "nested": {
                    "deep": {"very_deep": "value"},
                },
            },
        }
        result = compress_json_dict(data, CompressConfig(max_depth=2))
        parsed = json.loads(result)
        assert parsed["id"] == "1"
        # Deep nesting should be summarised.
        assert isinstance(parsed["metadata"]["nested"], (str, dict))

    def test_preserve_keys(self):
        data = {"id": "1", "secret_data": "x" * 1000, "keep_this": "important"}
        config = CompressConfig(max_value_len=50, preserve_keys=["keep_this"])
        result = compress_json_dict(data, config)
        parsed = json.loads(result)
        assert parsed["keep_this"] == "important"

    def test_error_dict_delegated(self):
        data = {"status": 404, "error": "Not Found", "body": {"detail": "Resource not found"}}
        result = compress_json_dict(data, CompressConfig())
        assert "404" in result
        assert "not found" in result.lower()

    def test_long_string_value_trimmed(self):
        data = {"id": "1", "content": "A" * 500}
        result = compress_json_dict(data, CompressConfig(max_value_len=100))
        parsed = json.loads(result)
        assert len(parsed["content"]) < 500
        assert "chars" in parsed["content"]

    def test_small_list_no_omitted(self):
        data = [{"id": 1}, {"id": 2}]
        result = compress_json_list(data, CompressConfig(max_list_items=5))
        parsed = json.loads(result)
        assert parsed["total"] == 2
        assert "omitted" not in parsed


# ---------------------------------------------------------------------------
# HtmlCompressor
# ---------------------------------------------------------------------------


class TestHtmlCompressor:
    def test_simple_html_to_text(self):
        html = "<html><body><p>Hello World</p></body></html>"
        result = compress_html(html, CompressConfig())
        assert "Hello World" in result

    def test_script_style_removed(self):
        html = (
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert('hi')</script><p>Content</p></body></html>"
        )
        result = compress_html(html, CompressConfig())
        assert "alert" not in result
        assert "color:red" not in result
        assert "Content" in result

    def test_error_page_detected(self):
        html = (
            "<html><head><title>404 Not Found</title></head>"
            "<body><h1>Page not found</h1></body></html>"
        )
        result = compress_html(html, CompressConfig())
        assert "404" in result

    def test_large_html_truncated(self):
        html = "<html><body>" + "<p>Content</p>" * 1000 + "</body></html>"
        result = compress_html(html, CompressConfig(max_chars=500))
        assert len(result) <= 500

    def test_empty_html(self):
        result = compress_html("", CompressConfig())
        assert "empty" in result.lower() or result == ""

    def test_is_html_detection(self):
        assert is_html("<!DOCTYPE html><html><body>Hi</body></html>")
        assert is_html("<html><body>Hi</body></html>")
        assert is_html("<div>content</div>")
        assert not is_html("Hello, world!")
        assert not is_html('{"key": "value"}')


# ---------------------------------------------------------------------------
# Auto-detect (compress_tool_result)
# ---------------------------------------------------------------------------


class TestCompressToolResult:
    def test_dict_input(self):
        data = [{"id": i, "name": f"item_{i}"} for i in range(100)]
        result = compress_tool_result(data, max_chars=2000)
        parsed = json.loads(result)
        assert parsed["_compressed"] is True
        assert parsed["total"] == 100

    def test_json_string_input(self):
        data = json.dumps([{"id": i, "payload": "x" * 100} for i in range(50)])
        result = compress_tool_result(data, max_chars=1000)
        parsed = json.loads(result)
        assert parsed["_compressed"] is True

    def test_html_string_input(self):
        html = "<!DOCTYPE html><html><body>" + "<p>text</p>" * 500 + "</body></html>"
        result = compress_tool_result(html, max_chars=500)
        assert len(result) <= 500
        assert "<p>" not in result

    def test_error_dict_input(self):
        data = {"status": 500, "error": "Internal Server Error"}
        result = compress_tool_result(data)
        assert "500" in result

    def test_short_content_unchanged(self):
        text = "Short result"
        assert compress_tool_result(text) == "Short result"

    def test_short_dict_serialized(self):
        data = {"ok": True}
        result = compress_tool_result(data)
        assert "ok" in result

    def test_content_type_override(self):
        data = '{"items": [1, 2, 3]}'
        result = compress_tool_result(data, content_type="text", max_chars=10)
        assert "chars omitted" in result or len(result) <= 10

    def test_config_object(self):
        data = [{"id": i} for i in range(100)]
        cfg = CompressConfig(max_chars=1000, max_list_items=5)
        result = compress_tool_result(data, config=cfg)
        parsed = json.loads(result)
        assert len(parsed["samples"]) == 5

    def test_non_string_non_dict(self):
        result = compress_tool_result(12345)
        assert "12345" in result

    def test_traceback_string(self):
        text = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 10, in <module>\n'
            "    x = 1/0\n"
            "ZeroDivisionError: division by zero\n"
        ) * 20  # Make it long enough to trigger compression
        result = compress_tool_result(text, max_chars=200)
        assert "ZeroDivisionError" in result


# ---------------------------------------------------------------------------
# Top-level import
# ---------------------------------------------------------------------------


class TestTopLevelImport:
    def test_lazy_import(self):
        from graph_tool_call import CompressConfig as CompressConfigAlias
        from graph_tool_call import compress_tool_result as compress_alias

        assert CompressConfigAlias is CompressConfig
        assert compress_alias is compress_tool_result
