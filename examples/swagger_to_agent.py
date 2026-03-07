"""Example: Ingest a Swagger/OpenAPI spec and use graph-based retrieval.

This example demonstrates the full workflow:
1. Ingest a Petstore Swagger spec
2. Auto-detect dependencies and categories
3. Retrieve tools by natural language query
4. Export visualization
"""

from __future__ import annotations

from pathlib import Path

from graph_tool_call import ToolGraph


def main() -> None:
    # 1. Ingest Petstore Swagger spec
    fixture = Path(__file__).parent.parent / "tests" / "fixtures" / "petstore_swagger2.json"
    if not fixture.exists():
        print("Petstore fixture not found, using URL...")
        tg = ToolGraph.from_url("https://petstore.swagger.io/v2/swagger.json")
    else:
        tg = ToolGraph()
        tg.ingest_openapi(str(fixture))

    print(tg)

    # 2. Check detected relations
    print("\nRelations:")
    for src, tgt, attrs in tg.graph.edges():
        rel = attrs.get("relation", "?")
        if str(rel) != "belongs_to" and "belongs_to" not in str(rel):
            print(f"  {src} --[{rel}]--> {tgt}")

    # 3. Retrieve tools for a query
    queries = [
        "add a new pet and upload its photo",
        "find pets by status",
        "place an order for a pet",
    ]
    for query in queries:
        results = tg.retrieve(query, top_k=3)
        print(f"\nQuery: {query}")
        for i, t in enumerate(results, 1):
            print(f"  {i}. {t.name}: {t.description[:60]}")

    # 4. Export GraphML (always works, no extra deps)
    out = Path("petstore_graph.graphml")
    tg.export_graphml(out)
    print(f"\nGraphML exported to {out}")

    # 5. Save and reload
    tg.save("petstore_graph.json")
    tg2 = ToolGraph.load("petstore_graph.json")
    print(f"Reloaded: {tg2}")


if __name__ == "__main__":
    main()
