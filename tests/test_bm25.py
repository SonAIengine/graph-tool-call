"""Tests for BM25 scorer."""

from __future__ import annotations

from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.retrieval.keyword import BM25Scorer


def _make_tool(
    name: str,
    description: str = "",
    tags: list[str] | None = None,
    parameters: list[ToolParameter] | None = None,
) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=description,
        tags=tags or [],
        parameters=parameters or [],
    )


def _build_tools() -> dict[str, ToolSchema]:
    tools = [
        _make_tool("read_file", "Read contents of a file from disk"),
        _make_tool("write_file", "Write contents to a file on disk"),
        _make_tool("delete_file", "Delete a file from the filesystem"),
        _make_tool("query_database", "Execute SQL query on a database"),
        _make_tool("insert_record", "Insert a record into a database table"),
        _make_tool("send_email", "Send an email message"),
    ]
    return {t.name: t for t in tools}


def test_tokenize_camel_case():
    tokens = BM25Scorer._tokenize("getUserById")
    assert tokens == ["get", "user", "by", "id"]


def test_tokenize_snake_case():
    tokens = BM25Scorer._tokenize("list_all_pets")
    # Stemming: "pets" → "pet" (original "pets" also kept)
    assert "list" in tokens
    assert "all" in tokens
    assert "pet" in tokens
    assert "pets" in tokens


def test_tokenize_kebab_case():
    tokens = BM25Scorer._tokenize("send-email")
    assert tokens == ["send", "email"]


def test_bm25_exact_match_highest():
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    scores = scorer.score("read file")

    assert "read_file" in scores
    # read_file should have the highest score since it matches the query exactly
    top_tool = max(scores, key=scores.get)  # type: ignore[arg-type]
    assert top_tool == "read_file"


def test_bm25_description_match():
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    scores = scorer.score("execute SQL query")

    assert "query_database" in scores
    assert scores["query_database"] > 0


def test_bm25_empty_query():
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    scores = scorer.score("")

    assert scores == {}


def test_bm25_all_tools_scored():
    """Query that matches terms from multiple tools should score them all."""
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    # "file" appears in read_file, write_file, delete_file descriptions/names
    scores = scorer.score("file")

    assert len(scores) >= 3
    for name in ["read_file", "write_file", "delete_file"]:
        assert name in scores
        assert scores[name] > 0


def test_currency_denominations_expand_to_currency_conversion_terms():
    """Concrete money words should match abstract currency conversion tools."""
    target = _make_tool(
        "currency_exchange.convert",
        "Convert an amount from a base currency to a target currency.",
    )
    noisy = _make_tool("us_history.get_event_info", "Retrieve United States historical events.")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("How many Canadian dollars can I get for 500 US dollars?")

    assert scores["currency_exchange.convert"] > scores.get("us_history.get_event_info", 0)


def test_unit_measurement_words_expand_to_conversion_terms():
    """Concrete units should match generic unit/cooking conversion tools."""
    target = _make_tool(
        "cooking_conversion.convert",
        "Convert cooking measurements from one unit to another.",
    )
    noisy = _make_tool("probability.dice_roll", "Calculate probability of dice outcomes.")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("How many ounces in 2 pounds of butter?")

    assert scores["cooking_conversion.convert"] > scores.get("probability.dice_roll", 0)


def test_historical_event_wording_expands_to_event_date_terms():
    """Specific treaty/signing wording should match generic event-date APIs."""
    target = _make_tool("get_event_date", "Retrieve the date of a historical event.")
    noisy = _make_tool("lawsuit_search", "Search legal lawsuits and civil cases.")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("When was the signing of the Treaty of Lisbon?")

    assert scores["get_event_date"] > scores.get("lawsuit_search", 0)


def test_card_probability_alias_does_not_fire_for_monarch_history():
    """King can be a person/title; only card probability context should expand it."""
    target = _make_tool("historic_leader_search", "Search historic leaders and monarchs.")
    noisy = _make_tool("probabilities.calculate_single", "Calculate probability of an event.")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("Who was the King of France in 1510?")

    assert scores.get("probabilities.calculate_single", 0) == 0


def test_unit_alias_does_not_fire_for_bmi_measurements():
    """Body measurements should not imply a standalone unit-conversion tool."""
    target = _make_tool("calculate_bmi", "Calculate BMI from weight and height.")
    noisy = _make_tool("unit_conversion.convert", "Convert a value from one unit to another.")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("Calculate BMI for 85 kilograms and 180 centimeters.")

    assert scores["calculate_bmi"] > scores.get("unit_conversion.convert", 0)


def test_british_pounds_do_not_trigger_unit_conversion_alias():
    """British Pounds are currency, not physical pounds, unless other unit context appears."""
    target = _make_tool(
        "currency_converter",
        "Calculates the current cost in target currency given the amount in base currency.",
    )
    noisy = _make_tool("cooking_conversion.convert", "Convert cooking measurements.")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("Calculate the current cost in British Pounds for 200 US dollars.")

    assert scores["currency_converter"] > scores.get("cooking_conversion.convert", 0)


def test_current_cost_phrase_boosts_matching_currency_tool():
    """Exact current-cost phrase evidence should beat generic conversion siblings."""
    target = _make_tool(
        "currency_converter",
        "Calculates the current cost in target currency given the amount in base currency.",
    )
    sibling = _make_tool(
        "currency_conversion.convert", "Convert a value from one currency to another."
    )
    tools = {tool.name: tool for tool in [target, sibling]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("Calculate the current cost in British Pounds for 200 US dollars.")

    assert scores["currency_converter"] > scores["currency_conversion.convert"]


# ---------------------------------------------------------------------------
# Korean bigram tokenization tests
# ---------------------------------------------------------------------------


def test_tokenize_korean_bigrams():
    """_korean_bigrams should produce character-level bigrams from Korean text."""
    bigrams = BM25Scorer._korean_bigrams("정기주문해지")
    assert bigrams == ["정기", "기주", "주문", "문해", "해지"]


def test_korean_query_matches_tool():
    """Korean query should match a tool with Korean description via bigrams."""
    tool = _make_tool(
        "cancelSubscription",
        description="정기주문을 해지하는 API",
    )
    tools = {tool.name: tool}
    scorer = BM25Scorer(tools)
    scores = scorer.score("주문해지")
    assert "cancelSubscription" in scores
    assert scores["cancelSubscription"] > 0


def test_korean_spaced_query_prefers_compact_business_phrase():
    """Separated Korean query terms should prefer compact Swagger menu summaries."""
    target = _make_tool("getOrderQueryList", description="주문/결제 > 주문관리 > 주문조회")
    noisy = _make_tool(
        "getGoodsItmInfoList",
        description="정기주문 상품의 변경 가능한 단품 목록 조회",
    )
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("주문 목록 조회")

    assert scores["getOrderQueryList"] > scores["getGoodsItmInfoList"]


def test_korean_settlement_compare_matches_reconciliation_alias():
    """Business wording 정산 비교 should match 정산대사/AdjustCompare APIs."""
    target = _make_tool("getPgAdjustCompareSummary", description="PG정산대사 요약 조회")
    noisy = _make_tool("savePgApprovalList", description="PG정산정보 수신")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("정산 비교 조회")

    assert scores["getPgAdjustCompareSummary"] > scores["savePgApprovalList"]


def test_korean_permission_button_phrase_beats_generic_menu():
    """회원 권한 버튼 조회 should prefer button-right APIs over generic menu lookup."""
    target = _make_tool("getButtonByPageRoleList", description="권한 없는 버튼 조회")
    noisy = _make_tool("getTopMenuList", description="상단 메뉴 조회")
    tools = {tool.name: tool for tool in [target, noisy]}
    scorer = BM25Scorer(tools)

    scores = scorer.score("회원 권한 버튼 조회")

    assert scores["getButtonByPageRoleList"] > scores["getTopMenuList"]


def test_korean_permission_button_prefers_page_role_siblings():
    """권한 버튼 queries should keep page-role button APIs ahead of user variants."""
    page_role = _make_tool("getButtonByPageRoleList", description="권한 없는 버튼 조회")
    enabled_page_role = _make_tool(
        "getEnabledButtonByPageRoleList",
        description="권한 존재 버튼 조회",
    )
    user_button = _make_tool("getButtonByUserList", description="권한 없는 저장버튼 조회")
    individual_button = _make_tool(
        "getIndivRightButtonList",
        description="개별 권한 버튼 목록 조회",
    )
    tools = {
        tool.name: tool for tool in [page_role, enabled_page_role, user_button, individual_button]
    }
    scorer = BM25Scorer(tools)

    scores = scorer.score("회원 권한 버튼 조회")

    assert scores["getButtonByPageRoleList"] > scores["getButtonByUserList"]
    assert scores["getEnabledButtonByPageRoleList"] > scores["getIndivRightButtonList"]
    assert BM25Scorer._semantic_phrase_multiplier(
        "회원 권한 버튼 조회",
        "getEnabledButtonByPageRoleList",
        enabled_page_role,
    ) > BM25Scorer._semantic_phrase_multiplier(
        "회원 권한 버튼 조회",
        "getButtonByUserList",
        user_button,
    )


def test_korean_intent_phrases_skip_bridge_terms_and_repeated_actions():
    """Phrase builder should keep discriminative word+action pairs."""
    phrases = BM25Scorer._korean_intent_phrases(["상품", "목록", "조회", "주문", "조회"])

    assert "상품조회" in phrases
    assert "주문조회" in phrases
    assert "목록조회" not in phrases


def test_korean_business_phrase_multiplier_is_bounded_and_negative_safe():
    """Korean phrase boosts should not fire for unrelated or English-only queries."""
    assert BM25Scorer._korean_business_phrase_multiplier("read file", "read_file") == 1.0
    assert BM25Scorer._korean_business_phrase_multiplier("배송 조회", "주문조회") == 1.0
    assert (
        BM25Scorer._korean_business_phrase_multiplier(
            "회원 권한 버튼 조회",
            "getButtonByPageRoleList 권한 버튼 조회 pagerole button role",
        )
        <= 2.0
    )


def test_mixed_korean_english():
    """Tokenization of mixed Korean/English text produces both bigrams and English tokens."""
    tokens = BM25Scorer._tokenize("주문order 해지cancel")
    # Should contain the original Korean tokens and their bigrams
    assert "주문order" in tokens  # original token (lowered, no split since no camelCase)
    assert "해지cancel" in tokens
    # Korean bigrams from "주문order" (only Korean chars: 주문 -> one bigram "주문")
    assert "주문" in tokens
    # Korean bigrams from "해지cancel" (only Korean chars: 해지 -> one bigram "해지")
    assert "해지" in tokens
    # English parts from camelCase split — "order" and "cancel" are part of mixed tokens
    # They remain as part of their original tokens since there's no camelCase boundary
