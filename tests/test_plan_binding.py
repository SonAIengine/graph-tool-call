"""Unit tests for ``graph_tool_call.plan.binding``.

binding placeholder resolution + error 동작.
"""

from __future__ import annotations

import pytest

from graph_tool_call.plan.binding import BindingError, resolve_bindings


def test_literal_passes_through():
    assert resolve_bindings("hello", {}) == "hello"
    assert resolve_bindings(42, {}) == 42
    assert resolve_bindings(None, {}) is None


def test_simple_lookup():
    ctx = {"s1": {"foo": "BAR"}}
    assert resolve_bindings("${s1.foo}", ctx) == "BAR"


def test_full_step_object():
    ctx = {"s1": {"a": 1, "b": 2}}
    assert resolve_bindings("${s1}", ctx) == {"a": 1, "b": 2}


def test_array_index():
    ctx = {"s1": {"items": [{"id": "A"}, {"id": "B"}]}}
    assert resolve_bindings("${s1.items[0].id}", ctx) == "A"
    assert resolve_bindings("${s1.items[1].id}", ctx) == "B"


def test_array_negative_index():
    ctx = {"s1": [10, 20, 30]}
    assert resolve_bindings("${s1[-1]}", ctx) == 30


def test_unknown_source_raises():
    with pytest.raises(BindingError, match="unknown source"):
        resolve_bindings("${ghost.x}", {"s1": {}})


def test_dict_walks_recursively():
    ctx = {"s1": {"v": 9}}
    out = resolve_bindings(
        {"a": "${s1.v}", "b": "literal", "nested": {"c": "${s1.v}"}},
        ctx,
    )
    assert out == {"a": 9, "b": "literal", "nested": {"c": 9}}


def test_list_walks_recursively():
    ctx = {"s1": {"v": "X"}}
    out = resolve_bindings(["${s1.v}", "lit", {"k": "${s1.v}"}], ctx)
    assert out == ["X", "lit", {"k": "X"}]


def test_oob_index_raises():
    ctx = {"s1": [1, 2]}
    with pytest.raises(BindingError, match="out of range"):
        resolve_bindings("${s1[5]}", ctx)


def test_input_alias_lookup():
    """input / user_input 둘 다 같은 값 가리키도록 caller 가 등록한 케이스."""
    shared = {"keyword": "shoes"}
    ctx = {"input": shared, "user_input": shared}
    assert resolve_bindings("${input.keyword}", ctx) == "shoes"
    assert resolve_bindings("${user_input.keyword}", ctx) == "shoes"
