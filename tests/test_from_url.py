"""Tests for ToolGraph.from_url() and _discover_spec_urls()."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from graph_tool_call.tool_graph import ToolGraph, _discover_spec_urls


class TestDiscoverSpecUrls:
    def test_direct_spec_url(self) -> None:
        """Non-Swagger-UI URLs are returned as-is."""
        url = "https://api.example.com/v3/api-docs"
        assert _discover_spec_urls(url) == [url]

    def test_swagger_ui_with_config(self) -> None:
        """Swagger UI URLs discover specs via swagger-config."""
        config_json = json.dumps(
            {
                "urls": [
                    {"url": "/v3/api-docs/group1", "name": "Group 1"},
                    {"url": "/v3/api-docs/group2", "name": "Group 2"},
                ]
            }
        ).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = config_json
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            urls = _discover_spec_urls("https://api.example.com/swagger-ui/index.html")

        mock_open.assert_called_once_with("https://api.example.com/swagger-config")
        assert len(urls) == 2
        assert "https://api.example.com/v3/api-docs/group1" in urls
        assert "https://api.example.com/v3/api-docs/group2" in urls

    def test_swagger_ui_config_fails_fallback(self) -> None:
        """When swagger-config fails, falls back to v3/api-docs."""
        with patch("urllib.request.urlopen", side_effect=Exception("not found")):
            urls = _discover_spec_urls("https://api.example.com/swagger-ui/index.html")

        assert urls == ["https://api.example.com/v3/api-docs"]

    def test_swagger_ui_nested_path(self) -> None:
        """Swagger UI URL with deeper path still extracts base correctly."""
        with patch("urllib.request.urlopen", side_effect=Exception("not found")):
            urls = _discover_spec_urls("https://api.example.com/app/swagger-ui/index.html")

        assert urls == ["https://api.example.com/app/v3/api-docs"]


class TestFromUrl:
    def test_from_url_direct_spec(self) -> None:
        """from_url with a direct spec URL ingests the spec."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "summary": "List items",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_json = json.dumps(spec).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = spec_json
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            tg = ToolGraph.from_url("https://api.example.com/v3/api-docs")

        assert len(tg.tools) == 1
        assert "listItems" in tg.tools

    def test_from_url_swagger_ui_multiple_specs(self) -> None:
        """from_url with Swagger UI discovers and ingests multiple specs."""
        config_json = json.dumps({"urls": [{"url": "/v3/api-docs/a", "name": "A"}]}).encode()

        spec_a = {
            "openapi": "3.0.0",
            "info": {"title": "A", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "summary": "List users",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_a_json = json.dumps(spec_a).encode()

        call_count = 0

        def mock_urlopen(url):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.__enter__ = lambda s: s
            mock.__exit__ = MagicMock(return_value=False)
            if "swagger-config" in url:
                mock.read.return_value = config_json
            else:
                mock.read.return_value = spec_a_json
            return mock

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

        assert "listUsers" in tg.tools
