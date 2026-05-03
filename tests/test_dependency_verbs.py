"""Unit tests for ``graph_tool_call.analyze.dependency`` verb mapping.

특히 'reg' 약어가 'write' intent 로 분류되는지 확인 (리뷰 🟢 항목).
"""
from __future__ import annotations

from graph_tool_call.analyze.dependency import _VERB_TO_INTENT


def test_reg_abbrev_maps_to_write():
    """``regGoodsApprove`` 같은 camelCase 약어를 위해 'reg' 도 write 로 잡아야."""
    assert _VERB_TO_INTENT.get("reg") == "write"


def test_register_full_form_still_maps_to_write():
    assert _VERB_TO_INTENT.get("register") == "write"
    assert _VERB_TO_INTENT.get("regist") == "write"


def test_basic_verbs_unchanged():
    """기존 verb mapping 회귀 방지."""
    assert _VERB_TO_INTENT.get("get") == "read"
    assert _VERB_TO_INTENT.get("create") == "write"
    assert _VERB_TO_INTENT.get("update") == "update"
    assert _VERB_TO_INTENT.get("delete") == "delete"


# ─── _ANNOTATION_BY_VERB sibling 일관성 (잠복 결함) ──


def test_annotation_by_verb_covers_register_family():
    """``_ANNOTATION_BY_VERB`` 도 register 계열 커버해야 — _VERB_TO_INTENT 와 sibling.

    ``registerUser`` / ``insertOrder`` / ``regGoodsApprove`` 같은 도구가 MCP
    annotation 을 받을 수 있어야 한다 (read_only_hint=False, ...).
    """
    from graph_tool_call.core.tool import _ANNOTATION_BY_VERB
    for verb in ("register", "regist", "reg", "insert"):
        assert verb in _ANNOTATION_BY_VERB, (
            f"verb {verb!r} 누락 — _VERB_TO_INTENT 와 sibling vocabulary 불일치"
        )
        assert _ANNOTATION_BY_VERB[verb].read_only_hint is False
        assert _ANNOTATION_BY_VERB[verb].destructive_hint is False
