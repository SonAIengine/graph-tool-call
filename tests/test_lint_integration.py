"""Tests for ai-api-lint integration."""

from __future__ import annotations

import pytest

ai_api_lint = pytest.importorskip("ai_api_lint")

from graph_tool_call.ingest.lint import lint_and_fix_spec  # noqa: E402


def _minimal_spec() -> dict:
    """OpenAPI spec with intentionally poor quality for testing fixes."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "responses": {
                        "200": {
                            "description": "OK",
                        }
                    },
                },
                "post": {
                    "operationId": "createUser",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "email": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                        }
                    },
                },
            },
            "/users/{userId}": {
                "get": {
                    "operationId": "getUser",
                    "parameters": [{"name": "userId", "in": "path", "required": True}],
                    "responses": {
                        "200": {
                            "description": "OK",
                        }
                    },
                },
            },
        },
    }


def test_lint_and_fix_returns_fixed_spec():
    spec = _minimal_spec()
    fixed, result = lint_and_fix_spec(spec)

    assert fixed is not spec, "Should return a deep copy"
    assert result is not None
    assert len(result.applied) > 0, "Should have applied at least one fix"


def test_lint_and_fix_preserves_original():
    spec = _minimal_spec()
    original_paths = set(spec["paths"].keys())
    lint_and_fix_spec(spec)

    assert set(spec["paths"].keys()) == original_paths, "Original spec should be unchanged"


def test_lint_level_1_is_safe():
    spec = _minimal_spec()
    _, result = lint_and_fix_spec(spec, max_level=1)

    assert result is not None
    # Level 1 should only apply safe fixes (no guessing)


def test_lint_adds_error_responses():
    """AI042 fixer should add 400 Bad Request to POST without 4xx."""
    spec = _minimal_spec()
    fixed, _ = lint_and_fix_spec(spec)

    post_op = fixed["paths"]["/users"]["post"]
    responses = post_op.get("responses", {})
    has_4xx = any(str(code).startswith("4") for code in responses)
    assert has_4xx, "Should have added a 4xx error response"
