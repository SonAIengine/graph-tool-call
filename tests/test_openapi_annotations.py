"""Test HTTP method → MCP annotation inference from OpenAPI ingest."""

from graph_tool_call.ingest.openapi import _infer_annotations, ingest_openapi


def test_infer_get():
    ann = _infer_annotations("get")
    assert ann is not None
    assert ann.read_only_hint is True
    assert ann.destructive_hint is False
    assert ann.idempotent_hint is True


def test_infer_post():
    ann = _infer_annotations("post")
    assert ann is not None
    assert ann.read_only_hint is False
    assert ann.destructive_hint is False
    assert ann.idempotent_hint is False


def test_infer_put():
    ann = _infer_annotations("put")
    assert ann is not None
    assert ann.read_only_hint is False
    assert ann.destructive_hint is False
    assert ann.idempotent_hint is True


def test_infer_patch():
    ann = _infer_annotations("patch")
    assert ann is not None
    assert ann.read_only_hint is False
    assert ann.idempotent_hint is False


def test_infer_delete():
    ann = _infer_annotations("delete")
    assert ann is not None
    assert ann.read_only_hint is False
    assert ann.destructive_hint is True
    assert ann.idempotent_hint is True


def test_infer_head():
    ann = _infer_annotations("head")
    assert ann is not None
    assert ann.read_only_hint is True


def test_infer_options():
    ann = _infer_annotations("options")
    assert ann is not None
    assert ann.read_only_hint is True


def test_infer_unknown_method():
    ann = _infer_annotations("trace")
    assert ann is None


def test_infer_case_insensitive():
    ann = _infer_annotations("GET")
    assert ann is not None
    assert ann.read_only_hint is True


def _minimal_openapi_spec(method="get", path="/items"):
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0"},
        "paths": {
            path: {
                method: {
                    "operationId": f"{method}_{path.strip('/').replace('/', '_')}",
                    "summary": f"{method.upper()} {path}",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }


def test_openapi_ingest_get_has_readonly_annotation():
    spec = _minimal_openapi_spec("get", "/users")
    tools, _ = ingest_openapi(spec)
    assert len(tools) == 1
    tool = tools[0]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False


def test_openapi_ingest_delete_has_destructive_annotation():
    spec = _minimal_openapi_spec("delete", "/users/{id}")
    tools, _ = ingest_openapi(spec)
    assert len(tools) == 1
    tool = tools[0]
    assert tool.annotations is not None
    assert tool.annotations.destructive_hint is True
    assert tool.annotations.read_only_hint is False


def test_openapi_ingest_post_annotation():
    spec = _minimal_openapi_spec("post", "/users")
    tools, _ = ingest_openapi(spec)
    tool = tools[0]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is False


def test_openapi_ingest_multiple_methods():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0"},
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "summary": "List items",
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "operationId": "createItem",
                    "summary": "Create item",
                    "responses": {"201": {"description": "Created"}},
                },
                "delete": {
                    "operationId": "deleteItem",
                    "summary": "Delete item",
                    "responses": {"200": {"description": "OK"}},
                },
            }
        },
    }
    tools, _ = ingest_openapi(spec)
    by_name = {t.name: t for t in tools}

    assert by_name["listItems"].annotations.read_only_hint is True
    assert by_name["createItem"].annotations.read_only_hint is False
    assert by_name["deleteItem"].annotations.destructive_hint is True
