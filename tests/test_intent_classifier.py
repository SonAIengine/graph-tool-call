"""Test intent classifier with Korean and English queries."""

from graph_tool_call.retrieval.intent import QueryIntent, classify_intent


def test_read_intent_english():
    intent = classify_intent("get user list")
    assert intent.read_intent > 0
    assert intent.write_intent == 0.0
    assert intent.delete_intent == 0.0


def test_read_intent_korean():
    intent = classify_intent("사용자 목록 조회")
    assert intent.read_intent > 0
    assert intent.write_intent == 0.0


def test_write_intent_english():
    intent = classify_intent("create a new user")
    assert intent.write_intent > 0
    assert intent.delete_intent == 0.0


def test_write_intent_korean():
    intent = classify_intent("새 사용자 생성")
    assert intent.write_intent > 0


def test_delete_intent_english():
    intent = classify_intent("delete the old records")
    assert intent.delete_intent > 0
    assert intent.read_intent == 0.0


def test_delete_intent_korean():
    intent = classify_intent("오래된 레코드 삭제")
    assert intent.delete_intent > 0


def test_neutral_intent():
    intent = classify_intent("hello world")
    assert intent.is_neutral is True
    assert intent.read_intent == 0.0
    assert intent.write_intent == 0.0
    assert intent.delete_intent == 0.0


def test_mixed_intent():
    intent = classify_intent("search and update user records")
    assert intent.read_intent > 0  # search
    assert intent.write_intent > 0  # update
    assert intent.read_intent + intent.write_intent <= 2.0


def test_empty_query():
    intent = classify_intent("")
    assert intent.is_neutral is True


def test_query_intent_is_neutral_property():
    neutral = QueryIntent()
    assert neutral.is_neutral is True
    non_neutral = QueryIntent(read_intent=0.5)
    assert non_neutral.is_neutral is False


def test_intent_normalization():
    """All intent dimensions should sum to approximately 1.0 when present."""
    intent = classify_intent("find and remove items")
    total = intent.read_intent + intent.write_intent + intent.delete_intent
    assert 0.9 <= total <= 1.1


def test_multiple_read_keywords():
    intent = classify_intent("list show get all items")
    assert intent.read_intent > 0
