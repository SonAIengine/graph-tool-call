"""CLI entry point: python -m graph_tool_call."""

from __future__ import annotations

import argparse
import json
import sys

from graph_tool_call import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-tool-call",
        description="Graph-structured tool retrieval for LLM agents",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    # --- ingest ---
    p_ingest = sub.add_parser("ingest", help="Ingest OpenAPI spec and save graph")
    p_ingest.add_argument("source", help="OpenAPI spec URL or file path")
    p_ingest.add_argument("-o", "--output", default="graph.json", help="Output graph file")
    p_ingest.add_argument("--required-only", action="store_true", help="Only required params")
    p_ingest.add_argument("--include-deprecated", action="store_true", help="Include deprecated")
    p_ingest.add_argument("--min-confidence", type=float, default=0.7)

    # --- analyze ---
    p_analyze = sub.add_parser("analyze", help="Analyze a saved graph")
    p_analyze.add_argument("graph_file", help="Graph JSON file")
    p_analyze.add_argument("--duplicates", action="store_true", help="Find duplicate tools")
    p_analyze.add_argument("--threshold", type=float, default=0.85, help="Duplicate threshold")

    # --- retrieve ---
    p_retrieve = sub.add_parser("retrieve", help="Search tools by query")
    p_retrieve.add_argument("query", help="Search query")
    p_retrieve.add_argument("-g", "--graph", required=True, help="Graph JSON file")
    p_retrieve.add_argument("-k", "--top-k", type=int, default=5)
    p_retrieve.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # --- visualize ---
    p_viz = sub.add_parser("visualize", help="Export graph visualization")
    p_viz.add_argument("graph_file", help="Graph JSON file")
    p_viz.add_argument("-o", "--output", help="Output file path")
    p_viz.add_argument(
        "-f",
        "--format",
        choices=["html", "graphml", "cypher"],
        default="html",
        help="Export format (default: html)",
    )

    # --- info ---
    p_info = sub.add_parser("info", help="Show graph summary")
    p_info.add_argument("graph_file", help="Graph JSON file")

    return parser


def cmd_ingest(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    tg = ToolGraph()
    tools = tg.ingest_openapi(
        args.source,
        required_only=args.required_only,
        skip_deprecated=not args.include_deprecated,
        min_confidence=args.min_confidence,
    )
    tg.save(args.output)
    print(f"Ingested {len(tools)} tools, {tg.graph.edge_count()} relations")
    print(f"Saved to {args.output}")


def cmd_analyze(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    tg = ToolGraph.load(args.graph_file)
    print(tg)

    if args.duplicates:
        dupes = tg.find_duplicates(threshold=args.threshold)
        if dupes:
            print(f"\nDuplicates found ({len(dupes)}):")
            for d in dupes:
                print(f"  {d.tool_a} <-> {d.tool_b}  (score: {d.score:.3f})")
        else:
            print("\nNo duplicates found.")


def cmd_retrieve(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    tg = ToolGraph.load(args.graph)
    results = tg.retrieve(args.query, top_k=args.top_k)

    if args.as_json:
        out = [{"name": t.name, "description": t.description} for t in results]
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"Query: {args.query}")
        print(f"Results ({len(results)}):")
        for i, t in enumerate(results, 1):
            desc = t.description[:80] + "..." if len(t.description) > 80 else t.description
            print(f"  {i}. {t.name}: {desc}")


def cmd_visualize(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    tg = ToolGraph.load(args.graph_file)
    fmt = args.format

    # Default output filename
    if args.output:
        out = args.output
    else:
        out = {"html": "graph.html", "graphml": "graph.graphml", "cypher": "graph.cypher"}[fmt]

    if fmt == "html":
        tg.export_html(out)
    elif fmt == "graphml":
        tg.export_graphml(out)
    elif fmt == "cypher":
        tg.export_cypher(out)

    print(f"Exported {fmt} to {out}")


def cmd_info(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph
    from graph_tool_call.ontology.schema import NodeType

    tg = ToolGraph.load(args.graph_file)
    print(tg)

    # Count by node type
    type_counts: dict[str, int] = {}
    for node_id in tg.graph.nodes():
        attrs = tg.graph.get_node_attrs(node_id)
        nt = str(attrs.get("node_type", "unknown"))
        type_counts[nt] = type_counts.get(nt, 0) + 1
    print("\nNodes by type:")
    for nt, count in sorted(type_counts.items()):
        print(f"  {nt}: {count}")

    # Count by relation type
    rel_counts: dict[str, int] = {}
    for _, _, attrs in tg.graph.edges():
        rel = str(attrs.get("relation", "unknown"))
        rel_counts[rel] = rel_counts.get(rel, 0) + 1
    if rel_counts:
        print("\nEdges by relation:")
        for rel, count in sorted(rel_counts.items()):
            print(f"  {rel}: {count}")

    # List categories
    categories = [
        n
        for n in tg.graph.nodes()
        if tg.graph.get_node_attrs(n).get("node_type") == NodeType.CATEGORY
    ]
    if categories:
        print(f"\nCategories ({len(categories)}):")
        for cat in sorted(categories):
            tool_count = len(
                [
                    nb
                    for nb in tg.graph.get_neighbors(cat, direction="in")
                    if tg.graph.get_node_attrs(nb).get("node_type") == NodeType.TOOL
                ]
            )
            print(f"  {cat} ({tool_count} tools)")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "ingest": cmd_ingest,
        "analyze": cmd_analyze,
        "retrieve": cmd_retrieve,
        "visualize": cmd_visualize,
        "info": cmd_info,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
