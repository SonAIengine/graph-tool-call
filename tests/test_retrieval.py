"""Tests for retrieval engine."""

from graph_tool_call.retrieval.engine import RetrievalEngine
from graph_tool_call.tool_graph import ToolGraph


def _build_file_tools_graph() -> ToolGraph:
    """Build a sample ToolGraph with file operation tools."""
    tg = ToolGraph()

    tools = [
        {"name": "read_file", "description": "Read contents of a file from disk"},
        {"name": "write_file", "description": "Write contents to a file on disk"},
        {"name": "delete_file", "description": "Delete a file from the filesystem"},
        {"name": "list_directory", "description": "List files in a directory"},
        {"name": "query_database", "description": "Execute SQL query on a database"},
        {"name": "insert_record", "description": "Insert a record into a database table"},
        {"name": "send_email", "description": "Send an email message"},
        {"name": "search_web", "description": "Search the web for information"},
    ]
    tg.add_tools(tools)

    # Set up categories
    tg.add_category("file_operations", domain="io")
    tg.add_category("database", domain="data")
    tg.add_category("communication")

    tg.assign_category("read_file", "file_operations")
    tg.assign_category("write_file", "file_operations")
    tg.assign_category("delete_file", "file_operations")
    tg.assign_category("list_directory", "file_operations")
    tg.assign_category("query_database", "database")
    tg.assign_category("insert_record", "database")
    tg.assign_category("send_email", "communication")

    # Set up relations
    tg.add_relation("read_file", "write_file", "complementary")
    tg.add_relation("query_database", "insert_record", "complementary")
    tg.add_relation("write_file", "delete_file", "similar_to")

    return tg


def test_retrieve_file_tools():
    tg = _build_file_tools_graph()
    results = tg.retrieve("read a file from disk", top_k=3)
    names = [t.name for t in results]
    assert "read_file" in names


def test_retrieve_returns_related_tools():
    tg = _build_file_tools_graph()
    results = tg.retrieve("write file", top_k=5)
    names = [t.name for t in results]
    # write_file should be top, and related tools like read_file, delete_file should appear
    assert "write_file" in names


def test_retrieve_database_tools():
    tg = _build_file_tools_graph()
    results = tg.retrieve("query database", top_k=3)
    names = [t.name for t in results]
    assert "query_database" in names


def test_retrieve_respects_top_k():
    tg = _build_file_tools_graph()
    results = tg.retrieve("file operations", top_k=2)
    assert len(results) <= 2


def test_retrieve_empty_query():
    tg = _build_file_tools_graph()
    results = tg.retrieve("", top_k=5)
    # Empty query may return no results or all tools depending on implementation
    assert isinstance(results, list)


def test_retrieve_math_synonym_hypotenuse_matches_hypot_operation():
    tg = ToolGraph()
    tg.add_tools(
        [
            {
                "name": "math.hypot",
                "description": "Compute the Euclidean norm from two or more numeric components.",
            },
            {
                "name": "calculate_triangle_area",
                "description": "Calculate triangle area from base and height.",
            },
            {
                "name": "geometry.area_triangle",
                "description": "Return area of a triangle.",
            },
        ],
        detect_dependencies=False,
    )

    names = [
        tool.name
        for tool in tg.retrieve(
            "Calculate the hypotenuse of a right triangle with sides 4 and 5.",
            top_k=3,
        )
    ]

    assert "math.hypot" in names


def test_retrieve_geographic_distance_prefers_geo_distance_operation():
    tg = ToolGraph()
    tg.add_tools(
        [
            {
                "name": "geo_distance.calculate",
                "description": "Calculate the geographic distance between two locations.",
            },
            {
                "name": "get_shortest_driving_distance",
                "description": "Calculate the shortest driving distance between two locations.",
            },
            {
                "name": "distance_calculator.calculate",
                "description": "Calculate the distance between two locations considering terrain.",
            },
        ],
        detect_dependencies=False,
    )

    names = [
        tool.name
        for tool in tg.retrieve(
            "Calculate the geographic distance from Los Angeles to New York.",
            top_k=2,
        )
    ]

    assert names[0] == "geo_distance.calculate"


def test_retrieve_boosts_explicit_dotted_tool_name_inside_long_query():
    tg = ToolGraph()
    tg.add_tools(
        [
            {
                "name": "geodistance.find",
                "description": "Find distance between two locations.",
            },
            {
                "name": "cell_biology.function_lookup",
                "description": "Lookup biological cell functions and related concepts.",
            },
            {
                "name": "flights.search",
                "description": "Search available flights for travel planning.",
            },
            {
                "name": "calculate_area_under_curve",
                "description": "Calculate an integral for a mathematical function.",
            },
        ],
        detect_dependencies=False,
    )

    names = [
        tool.name
        for tool in tg.retrieve(
            "Plan a trip: use the 'geodistance.find' function for New York to London, "
            "then search flights and calculate the total itinerary.",
            top_k=3,
        )
    ]

    assert names[0] == "geodistance.find"


def test_retrieve_keeps_clause_level_tools_for_multi_intent_query():
    tg = ToolGraph()
    tg.add_tools(
        [
            {
                "name": "traffic_estimate",
                "description": "Estimate weekday traffic between two addresses.",
            },
            {
                "name": "calculate_distance",
                "description": "Calculate distance between two locations.",
            },
            {
                "name": "weather_forecast",
                "description": "Get weather forecast for a city.",
            },
            {
                "name": "weather_forecast_humidity",
                "description": "Get humidity forecast for a city.",
            },
            {
                "name": "weather_forecast_temperature",
                "description": "Get temperature forecast for a city.",
            },
            {
                "name": "event_finder.find_upcoming",
                "description": "Find upcoming events in a city.",
            },
        ],
        detect_dependencies=False,
    )

    names = [
        tool.name
        for tool in tg.retrieve(
            "I need to know the estimated traffic from San Francisco to Palo Alto. "
            "Also, I am curious about the distance between these two locations. "
            "Furthermore, I need the weather forecast for the weekend.",
            top_k=3,
        )
    ]

    assert {"traffic_estimate", "calculate_distance", "weather_forecast"}.issubset(names)


def test_split_query_clauses_handles_and_before_new_action():
    clauses = RetrievalEngine._split_query_clauses(
        "I need to convert 10 dollars to Euros and make a 10 dollar deposit "
        "in my local bank account."
    )

    assert clauses == [
        "I need to convert 10 dollars to Euros",
        "make a 10 dollar deposit in my local bank account",
    ]


def test_retrieve_keeps_and_joined_clause_tool_in_top_k():
    tg = ToolGraph()
    tg.add_tools(
        [
            {
                "name": "currency_conversion",
                "description": "Convert an amount of money from one currency to another.",
            },
            {
                "name": "banking_service",
                "description": "Make a deposit into a local bank account.",
            },
            {
                "name": "bank_account.transfer",
                "description": "Transfer money between bank accounts.",
            },
            {
                "name": "bank.calculate_balance",
                "description": "Calculate the balance of a bank account.",
            },
            {
                "name": "latest_exchange_rate",
                "description": "Retrieve the latest exchange rate for a currency pair.",
            },
        ],
        detect_dependencies=False,
    )

    names = [
        tool.name
        for tool in tg.retrieve(
            "I need to convert 10 dollars to Euros and make a 10 dollar deposit "
            "in my local bank account.",
            top_k=5,
        )
    ]

    assert {"currency_conversion", "banking_service"}.issubset(names)
