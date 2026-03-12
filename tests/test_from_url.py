"""Tests for ToolGraph.from_url() and _discover_spec_urls()."""

from __future__ import annotations

import json
from pathlib import Path
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
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "https://api.example.com/swagger-config"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("graph_tool_call.net._open_url", return_value=mock_resp) as mock_open:
            urls = _discover_spec_urls("https://api.example.com/swagger-ui/index.html")

        assert mock_open.call_count == 1
        assert len(urls) == 2
        assert "https://api.example.com/v3/api-docs/group1" in urls
        assert "https://api.example.com/v3/api-docs/group2" in urls

    def test_swagger_ui_config_fails_fallback(self) -> None:
        """When swagger-config fails, falls back to v3/api-docs."""
        with patch("graph_tool_call.net._open_url", side_effect=Exception("not found")):
            urls = _discover_spec_urls("https://api.example.com/swagger-ui/index.html")

        assert urls == ["https://api.example.com/v3/api-docs"]

    def test_swagger_ui_nested_path(self) -> None:
        """Swagger UI URL with deeper path still extracts base correctly."""
        with patch("graph_tool_call.net._open_url", side_effect=Exception("not found")):
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

        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "https://api.example.com/v3/api-docs"

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
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

        def mock_urlopen(request, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.__enter__ = lambda s: s
            mock.__exit__ = MagicMock(return_value=False)
            target = request.full_url if hasattr(request, "full_url") else str(request)
            mock.headers = {"Content-Type": "application/json"}
            mock.geturl.return_value = target
            if "swagger-config" in target:
                mock.read.return_value = config_json
            else:
                mock.read.return_value = spec_a_json
            return mock

        with patch("graph_tool_call.net._open_url", side_effect=mock_urlopen):
            tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

        assert "listUsers" in tg.tools

    def test_from_url_cache_save_and_load(self, tmp_path: Path) -> None:
        """from_url saves cache on first call, loads on second."""
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
        cache_file = tmp_path / "cached.json"

        mock_resp = MagicMock()
        mock_resp.read.return_value = spec_json
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        # First call: builds and saves
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "https://api.example.com/v3/api-docs"

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            tg1 = ToolGraph.from_url("https://api.example.com/v3/api-docs", cache=cache_file)
        assert cache_file.exists()
        assert "listItems" in tg1.tools

        # Verify metadata in saved file
        saved = json.loads(cache_file.read_text())
        assert "metadata" in saved
        assert saved["metadata"]["source_url"] == "https://api.example.com/v3/api-docs"
        assert "built_at" in saved["metadata"]

        # Second call: loads from cache (no network)
        tg2 = ToolGraph.from_url("https://api.example.com/v3/api-docs", cache=cache_file)
        assert "listItems" in tg2.tools
        assert tg2.metadata.get("source_url") == "https://api.example.com/v3/api-docs"

    def test_from_url_force_rebuild(self, tmp_path: Path) -> None:
        """force=True ignores existing cache and rebuilds."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "getUsers",
                        "summary": "Get users",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_json = json.dumps(spec).encode()
        cache_file = tmp_path / "cached.json"

        # Write a dummy cache with different content
        cache_file.write_text(
            json.dumps(
                {
                    "format_version": "1",
                    "library_version": "0.0.0",
                    "graph": {"nodes": [], "edges": []},
                    "tools": {},
                }
            )
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = spec_json
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        # Without force: loads empty cache
        tg_cached = ToolGraph.from_url("https://api.example.com/v3/api-docs", cache=cache_file)
        assert len(tg_cached.tools) == 0

        # With force: rebuilds from source
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "https://api.example.com/v3/api-docs"

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            tg_fresh = ToolGraph.from_url(
                "https://api.example.com/v3/api-docs",
                cache=cache_file,
                force=True,
            )
        assert "getUsers" in tg_fresh.tools

    def test_from_url_progress_callback(self) -> None:
        """progress callback receives status messages."""
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
        messages: list[str] = []

        mock_resp = MagicMock()
        mock_resp.read.return_value = spec_json
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "https://api.example.com/v3/api-docs"

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            ToolGraph.from_url(
                "https://api.example.com/v3/api-docs",
                progress=messages.append,
            )

        assert len(messages) >= 3  # discovering, ingesting, done
        assert any("Discovering" in m for m in messages)
        assert any("Done" in m for m in messages)

    def test_from_url_blocks_private_host_by_default(self) -> None:
        with patch("graph_tool_call.net._open_url") as mock_open:
            try:
                ToolGraph.from_url("http://127.0.0.1/openapi.json")
            except ConnectionError as e:
                assert "private or local host" in str(e)
            else:
                raise AssertionError("expected ConnectionError")
        mock_open.assert_not_called()

    def test_from_url_allows_private_host_with_opt_in(self) -> None:
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
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.geturl.return_value = "http://127.0.0.1/openapi.json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("graph_tool_call.net._open_url", return_value=mock_resp):
            tg = ToolGraph.from_url(
                "http://127.0.0.1/openapi.json",
                allow_private_hosts=True,
            )
        assert "listItems" in tg.tools
