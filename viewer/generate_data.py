"""Generate viewer data.json from a ToolGraph instance.

Usage:
    poetry run python viewer/generate_data.py [swagger_url] [--llm openai/gpt-4o-mini]

Examples:
    # From x2bee swagger
    poetry run python viewer/generate_data.py \
        https://admin-api-dev.x2bee.com/swagger-ui/index.html \
        --llm openai/gpt-4o-mini

    # From saved graph
    poetry run python viewer/generate_data.py --load graph.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graph_tool_call import ToolGraph
from graph_tool_call.ontology.schema import NodeType, RelationType


def generate_viewer_data(tg: ToolGraph) -> dict:
    """Extract viewer-compatible data from a ToolGraph."""
    graph = tg.graph
    tools_data: dict[str, dict] = {}
    categories: dict[str, list[str]] = {}

    # 1. Build category mapping from BELONGS_TO edges
    tool_category: dict[str, str] = {}
    for src, tgt, attrs in graph.edges():
        if attrs.get("relation") == RelationType.BELONGS_TO:
            src_attrs = graph.get_node_attrs(src)
            tgt_attrs = graph.get_node_attrs(tgt)
            is_tool = src_attrs.get("node_type") == NodeType.TOOL
            is_cat = tgt_attrs.get("node_type") == NodeType.CATEGORY
            if is_tool and is_cat:
                tool_category[src] = tgt

    # 2. Build tool data with real relations
    for name, tool in tg.tools.items():
        cat = tool_category.get(name, tool.domain or "uncategorized")

        # Collect relations from graph edges (both directions)
        relations = []
        seen_targets = set()
        for edge in graph.get_edges_from(name, direction="both"):
            src, tgt, attrs = edge
            other = tgt if src == name else src

            # Skip non-tool nodes
            other_attrs = graph.get_node_attrs(other)
            if other_attrs.get("node_type") != NodeType.TOOL:
                continue

            if other in seen_targets:
                continue
            seen_targets.add(other)

            rel_type = attrs.get("relation")
            if rel_type is None:
                continue

            # Skip BELONGS_TO (category edges, not tool-tool)
            if rel_type == RelationType.BELONGS_TO:
                continue

            rel_str = rel_type.value if isinstance(rel_type, RelationType) else str(rel_type)
            weight = attrs.get("weight", 1.0)
            relations.append(
                {
                    "name": other,
                    "type": rel_str,
                    "weight": round(weight, 3),
                }
            )

        # Sort by weight descending, limit to 30
        relations.sort(key=lambda r: r.get("weight", 0), reverse=True)
        relations = relations[:30]

        tools_data[name] = {
            "description": tool.description,
            "tags": list(tool.tags),
            "params": [p.name for p in tool.parameters],
            "category": cat,
            "relations": relations,
        }

        # Group into categories
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(name)

    # Sort categories by tool count descending
    categories = dict(sorted(categories.items(), key=lambda x: len(x[1]), reverse=True))

    # Count total edges (tool-tool only)
    total_edges = sum(len(t["relations"]) for t in tools_data.values())

    return {
        "stats": {
            "total_tools": len(tools_data),
            "total_categories": len(categories),
            "total_edges": total_edges,
        },
        "categories": categories,
        "tools": tools_data,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate viewer data.json")
    parser.add_argument("url", nargs="?", help="Swagger UI or OpenAPI spec URL")
    parser.add_argument("--llm", default=None, help="LLM for auto_organize")
    parser.add_argument("--load", default=None, help="Load from saved graph JSON")
    parser.add_argument("--output", default="viewer/data.json", help="Output path")
    args = parser.parse_args()

    if args.load:
        print(f"Loading graph from {args.load}...")
        tg = ToolGraph.load(args.load)
    elif args.url:
        print(f"Fetching specs from {args.url}...")
        tg = ToolGraph.from_url(args.url, detect_dependencies=True, min_confidence=0.7)
        if args.llm:
            print(f"Running auto_organize with {args.llm}...")
            tg.auto_organize(llm=args.llm)
    else:
        parser.error("Either url or --load is required")
        return

    print(f"Graph: {tg}")
    data = generate_viewer_data(tg)
    print(f"Stats: {data['stats']}")

    # Relation type distribution
    from collections import Counter

    rel_types = Counter()
    for tool in data["tools"].values():
        for rel in tool["relations"]:
            rel_types[rel["type"]] += 1
    print("Relation types:")
    for t, c in rel_types.most_common():
        print(f"  {t}: {c}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Written to {output} ({output.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
