from __future__ import annotations

from graph_tool_call import ToolGraph


def _graph(tools: list[dict]) -> ToolGraph:
    tg = ToolGraph()
    tg.add_tools(tools, detect_dependencies=False)
    return tg


def _tool(name: str, description: str) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }


def test_bfcl_us_history_event_alias_lifts_american_civil_war_query():
    tg = _graph(
        [
            _tool("law.civil.get_case_details", "Retrieve details about civil law cases."),
            _tool("european_history.get_event_date", "Get dates for European historical events."),
            _tool("civil_cases.retrieve", "Retrieve civil lawsuit cases."),
            _tool(
                "us_history.get_event_info",
                "Get information about historical events in the United States.",
            ),
        ]
    )

    retrieved = [tool.name for tool in tg.retrieve("Get start date on the American Civil War.", 3)]

    assert retrieved[0] == "us_history.get_event_info"


def test_bfcl_religion_history_alias_lifts_christianity_queries():
    tg = _graph(
        [
            _tool("historic_leader_search", "Search historic leaders by time period."),
            _tool("us_history.get_event_info", "Get information about historical US events."),
            _tool("religion.history_info", "Get high-level information about a religion."),
            _tool("get_religion_history", "Retrieve historical dates and facts for a religion."),
            _tool(
                "religion_history.track",
                "Track the rise and fall of a religion across regions and years.",
            ),
        ]
    )

    christianity_dates = [
        tool.name
        for tool in tg.retrieve(
            "Retrieve the historic dates and facts related to Christianity between "
            "year 300 and 400.",
            3,
        )
    ]
    rise_and_fall = [
        tool.name
        for tool in tg.retrieve(
            "I want to know the rise and fall of Christianity in Egypt and Turkey from "
            "100 A.D to 1500 A.D.",
            3,
        )
    ]

    assert "get_religion_history" in christianity_dates
    assert "religion_history.track" in rise_and_fall


def test_bfcl_grocery_nutrition_alias_lifts_food_macro_query():
    tg = _graph(
        [
            _tool("walmart.check_price", "Check a Walmart product price."),
            _tool("recipe_info.get_calories", "Get calories for a recipe."),
            _tool("get_protein_sequence", "Return protein sequence data for a gene."),
            _tool(
                "grocery_info.nutritional_info",
                "Return nutritional information for grocery food items.",
            ),
        ]
    )

    retrieved = [
        tool.name
        for tool in tg.retrieve(
            "Check the amount of protein, calories and carbs in an avocado from Walmart.",
            3,
        )
    ]

    assert retrieved[0] == "grocery_info.nutritional_info"


def test_bfcl_music_and_instrument_aliases_lift_multi_intent_subtasks():
    tg = _graph(
        [
            _tool("poker_game_winner", "Determine the winner of a poker hand."),
            _tool("restaurant.find_nearby", "Locate nearby restaurants."),
            _tool("find_instrument", "Find an available musical instrument within a budget."),
            _tool("musical_scale", "Return the notes in a musical scale for a key."),
        ]
    )

    instrument_hits = [
        tool.name for tool in tg.retrieve("Find me a Fender guitar within my budget of $500.", 3)
    ]
    scale_hits = [
        tool.name
        for tool in tg.retrieve("I forgot the notes in the C major scale while playing guitar.", 3)
    ]

    assert instrument_hits[0] == "find_instrument"
    assert scale_hits[0] == "musical_scale"


def test_bfcl_displacement_restaurant_and_recipe_aliases_lift_subtasks():
    tg = _graph(
        [
            _tool("kinematics.final_velocity", "Calculate final velocity from acceleration."),
            _tool("calculate_displacement", "Calculate displacement from velocity and time."),
            _tool("vegan_restaurant.find_nearby", "Locate nearby vegan restaurants."),
            _tool("find_restaurants", "Find restaurant options by cuisine, city, and diet."),
            _tool("recipe_info.get_calories", "Get calories for a recipe."),
            _tool("find_recipe", "Find recipe ideas by course, diet, and preparation time."),
            _tool("soccer.get_last_match", "Get the last soccer match."),
            _tool("sports.match_schedule", "Get upcoming NBA match schedules for a team."),
            _tool("get_stock_price", "Get a stock price quote."),
            _tool("get_stock_info", "Get detailed stock information for a market symbol."),
            _tool("hospital.locate", "Locate nearby hospitals with emergency departments."),
            _tool("locate_tallest_mountains", "Locate tall mountains near a region."),
        ]
    )

    displacement_hits = [
        tool.name
        for tool in tg.retrieve(
            "A small object has initial velocity 10 m/s and travels for 5 seconds. "
            "How far did the object travel during this time?",
            3,
        )
    ]
    restaurant_hits = [
        tool.name
        for tool in tg.retrieve(
            "Find 5 restaurant options in San Francisco that serve Italian food for a vegan.",
            3,
        )
    ]
    recipe_hits = [
        tool.name
        for tool in tg.retrieve(
            "Find a vegan main course recipe that can be prepared within 45 minutes.",
            3,
        )
    ]
    sports_hits = [
        tool.name
        for tool in tg.retrieve(
            "Tell me the next 3 match schedules for the Warriors in the NBA.",
            3,
        )
    ]
    stock_hits = [
        tool.name
        for tool in tg.retrieve("Provide detailed information about Apple Inc stocks in NASDAQ.", 3)
    ]
    hospital_hits = [
        tool.name
        for tool in tg.retrieve(
            "Find nearby hospitals in Denver within 10 kms with an Emergency department.",
            3,
        )
    ]

    assert displacement_hits[0] == "calculate_displacement"
    assert restaurant_hits[0] == "find_restaurants"
    assert recipe_hits[0] == "find_recipe"
    assert sports_hits[0] == "sports.match_schedule"
    assert stock_hits[0] == "get_stock_info"
    assert hospital_hits[0] == "hospital.locate"


def test_bfcl_distance_aliases_lift_location_and_coordinate_queries():
    tg = _graph(
        [
            _tool(
                "geo_distance.calculate",
                "Calculate the geographic distance between two given locations.",
            ),
            _tool(
                "get_shortest_driving_distance",
                "Calculate the shortest driving distance between two locations.",
            ),
            _tool("calculate_distance", "Calculate the distance between two GPS coordinates."),
            _tool(
                "distance_calculator.calculate",
                "Calculate the distance between two locations considering terrain.",
            ),
            _tool(
                "calculate_electrostatic_potential",
                "Calculate electrostatic potential between charged bodies using distance.",
            ),
            _tool(
                "EuclideanDistance.calculate",
                "Calculate the Euclidean distance between two points in 2D space.",
            ),
            _tool("calculate_velocity", "Calculate velocity for a distance travelled in time."),
        ]
    )

    location_distance = [
        tool.name
        for tool in tg.retrieve(
            "What's the approximate distance between Boston, MA and Washington, D.C. in mile?",
            5,
        )
    ]
    coordinate_distance = [
        tool.name
        for tool in tg.retrieve(
            "What is the total distance in kilometers from Paris (48.8584 N, 2.2945 E) "
            "to Rome (41.8902 N, 12.4922 E) and Athens (37.9715 N, 23.7257 E)?",
            5,
        )
    ]
    driving_distance = [
        tool.name
        for tool in tg.retrieve(
            "Calculate the shortest driving distance between Boston and Washington.",
            3,
        )
    ]
    euclidean_distance = [
        tool.name
        for tool in tg.retrieve(
            "Compute the Euclidean distance between two points A(3,4) and B(1,2).",
            5,
        )
    ]
    terrain_distance = [
        tool.name
        for tool in tg.retrieve(
            "Find the distance between New York and Boston, accounting for terrain.",
            5,
        )
    ]
    electrostatic_distance = [
        tool.name
        for tool in tg.retrieve(
            "Calculate the electrostatic potential between two charged bodies using distance.",
            5,
        )
    ]

    assert location_distance[0] == "geo_distance.calculate"
    assert coordinate_distance[0] == "calculate_distance"
    assert driving_distance[0] == "get_shortest_driving_distance"
    assert euclidean_distance[0] == "EuclideanDistance.calculate"
    assert terrain_distance[0] == "distance_calculator.calculate"
    assert electrostatic_distance[0] == "calculate_electrostatic_potential"


def test_bfcl_distance_alias_keeps_explicit_geodistance_tool_name():
    tg = _graph(
        [
            _tool(
                "geo_distance.calculate",
                "Calculate the geographic distance between two given locations.",
            ),
            _tool("geodistance.find", "Find the distance between two locations."),
            _tool("flights.search", "Search available flights for travel planning."),
        ]
    )

    names = [
        tool.name
        for tool in tg.retrieve(
            "Plan a trip: use the 'geodistance.find' function for New York to London.",
            5,
        )
    ]

    assert names[0] == "geodistance.find"


def test_bfcl_sports_schedule_alias_does_not_swallow_ranking_query():
    tg = _graph(
        [
            _tool("sports.match_schedule", "Get upcoming NBA match schedules for a team."),
            _tool("sports.player_ranking", "Get current top player rankings for NBA athletes."),
            _tool("team_roster.lookup", "Look up a team roster."),
        ]
    )

    retrieved = [
        tool.name for tool in tg.retrieve("Who are the top ranked NBA players right now?", 3)
    ]

    assert retrieved[0] == "sports.player_ranking"
