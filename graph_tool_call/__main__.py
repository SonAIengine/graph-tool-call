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
    p_ingest.add_argument(
        "-f", "--force", action="store_true", help="Force rebuild (ignore existing cache)"
    )
    p_ingest.add_argument("--embedding", nargs="?", const="auto", help="Enable embedding index")
    p_ingest.add_argument("--llm", help="LLM for ontology (e.g. ollama/qwen2.5:7b)")
    p_ingest.add_argument("--organize", action="store_true", help="Run auto_organize()")
    p_ingest.add_argument("--lint", action="store_true", help="Run ai-api-lint auto-fix")
    p_ingest.add_argument("--lint-level", type=int, default=2, help="Lint level (1 or 2)")
    p_ingest.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="Allow localhost/private IP URLs for remote spec loading",
    )
    p_ingest.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output")

    # --- analyze ---
    p_analyze = sub.add_parser("analyze", help="Analyze a saved graph")
    p_analyze.add_argument("graph_file", help="Graph JSON file")
    p_analyze.add_argument("--duplicates", action="store_true", help="Find duplicate tools")
    p_analyze.add_argument("--conflicts", action="store_true", help="Show detected conflicts")
    p_analyze.add_argument("--orphans", action="store_true", help="Show orphan tools")
    p_analyze.add_argument("--categories", action="store_true", help="Show category coverage")
    p_analyze.add_argument("--threshold", type=float, default=0.85, help="Duplicate threshold")
    p_analyze.add_argument(
        "--conflict-threshold", type=float, default=0.6, help="Conflict confidence threshold"
    )
    p_analyze.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # --- search (one-liner: ingest + retrieve) ---
    p_search = sub.add_parser("search", help="Search tools from source (no pre-build needed)")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument(
        "-s",
        "--source",
        required=True,
        help="OpenAPI spec URL, file path, or pre-built graph JSON",
    )
    p_search.add_argument("-k", "--top-k", type=int, default=5)
    p_search.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    p_search.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="Allow localhost/private IP URLs",
    )
    p_search.add_argument(
        "--scores",
        action="store_true",
        help="Show detailed relevance scores",
    )

    # --- retrieve ---
    p_retrieve = sub.add_parser("retrieve", help="Search tools from pre-built graph")
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

    # --- dashboard ---
    p_dash = sub.add_parser("dashboard", help="Launch interactive dashboard")
    p_dash.add_argument("graph_file", help="Graph JSON file")
    p_dash.add_argument("--host", default="127.0.0.1", help="Host to bind")
    p_dash.add_argument("--port", type=int, default=8050, help="Port to bind")
    p_dash.add_argument("--debug", action="store_true", help="Enable Dash debug mode")

    # --- proxy (MCP proxy) ---
    p_proxy = sub.add_parser(
        "proxy",
        help="Run as MCP proxy (aggregate + filter backend servers)",
    )
    p_proxy.add_argument(
        "-c",
        "--config",
        required=True,
        help="Proxy config JSON or .mcp.json file",
    )
    p_proxy.add_argument("--top-k", type=int, default=10, help="Default top-K for search")
    p_proxy.add_argument(
        "--embedding",
        nargs="?",
        const=True,
        default=False,
        help="Enable embedding (optionally specify provider, e.g. ollama/qwen3-embedding:0.6b)",
    )
    p_proxy.add_argument(
        "--passthrough-threshold",
        type=int,
        default=30,
        help="Max tools for passthrough mode (default: 30)",
    )
    p_proxy.add_argument(
        "--cache",
        dest="cache_path",
        help="Cache path for ToolGraph (skip embedding rebuild on restart)",
    )

    # --- serve (MCP server) ---
    p_serve = sub.add_parser("serve", help="Run as MCP server (stdio transport)")
    p_serve.add_argument(
        "-s",
        "--source",
        action="append",
        dest="sources",
        help="OpenAPI spec URL or file (repeatable)",
    )
    p_serve.add_argument(
        "-g",
        "--graph",
        dest="graph_file",
        help="Pre-built graph JSON file",
    )
    p_serve.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="Allow localhost/private IP URLs",
    )
    p_serve.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="MCP transport (default: stdio)",
    )

    return parser


def cmd_ingest(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    progress = None if args.quiet else (lambda msg: print(f"  {msg}"))
    source = args.source

    # URL source: use from_url() with full feature set
    if source.startswith(("http://", "https://")):
        llm = None
        if args.llm:
            from graph_tool_call.ontology.llm_provider import wrap_llm

            llm = wrap_llm(args.llm)
        elif args.organize:
            pass  # auto_organize(llm=None) runs auto-mode only

        tg = ToolGraph.from_url(
            source,
            required_only=args.required_only,
            skip_deprecated=not args.include_deprecated,
            min_confidence=args.min_confidence,
            lint=args.lint,
            lint_level=args.lint_level,
            llm=llm,
            cache=args.output,
            force=args.force,
            progress=progress,
            allow_private_hosts=args.allow_private_hosts,
        )

        # Post-build: organize without LLM if --organize but no --llm
        if args.organize and not args.llm:
            if progress:
                progress("Running auto_organize()")
            tg.auto_organize()
            tg.save(args.output)
    else:
        # Local file: direct ingest
        tg = ToolGraph()
        if progress:
            progress(f"Ingesting {source}")
        tg.ingest_openapi(
            source,
            required_only=args.required_only,
            skip_deprecated=not args.include_deprecated,
            min_confidence=args.min_confidence,
            allow_private_hosts=args.allow_private_hosts,
        )

        if args.organize or args.llm:
            llm = None
            if args.llm:
                from graph_tool_call.ontology.llm_provider import wrap_llm

                llm = wrap_llm(args.llm)
            if progress:
                progress("Running auto_organize()")
            tg.auto_organize(llm=llm)

        tg.save(args.output)

    # Post-build: embedding
    if args.embedding:
        if progress:
            progress("Building embedding index")
        model = None if args.embedding == "auto" else args.embedding
        if model:
            tg.enable_embedding(model)
        else:
            tg.enable_embedding()
        # Re-save with embedding-ready state
        tg.save(args.output)

    print(f"Ingested {len(tg.tools)} tools, {tg.graph.edge_count()} relations")
    print(f"Saved to {args.output}")


def cmd_analyze(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    tg = ToolGraph.load(args.graph_file)
    report = tg.analyze(
        duplicate_threshold=args.threshold,
        conflict_min_confidence=args.conflict_threshold,
    )

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return

    print(tg)
    print("\nSummary:")
    print(f"  tools: {report.tool_count}")
    print(f"  nodes: {report.node_count}")
    print(f"  edges: {report.edge_count}")
    print(f"  categories: {report.category_count}")
    print(f"  orphan tools: {report.orphan_tool_count}")
    print(f"  duplicates: {report.duplicate_count}")
    print(f"  conflicts: {report.conflict_count}")

    if report.relation_counts:
        print("\nRelations:")
        for rel, count in report.relation_counts.items():
            print(f"  {rel}: {count}")

    if args.duplicates:
        if report.duplicates:
            print(f"\nDuplicates found ({len(report.duplicates)}):")
            for d in report.duplicates:
                print(f"  {d.tool_a} <-> {d.tool_b}  (score: {d.score:.3f})")
        else:
            print("\nNo duplicates found.")

    if args.conflicts:
        if report.conflicts:
            print(f"\nConflicts found ({len(report.conflicts)}):")
            for conflict in report.conflicts:
                print(
                    f"  {conflict.source} <-> {conflict.target}  "
                    f"(confidence: {conflict.confidence:.2f})"
                )
        else:
            print("\nNo conflicts found.")

    if args.orphans and report.orphan_tools:
        print(f"\nOrphan tools ({len(report.orphan_tools)}):")
        for tool_name in report.orphan_tools:
            print(f"  {tool_name}")
    elif args.orphans:
        print("\nNo orphan tools.")

    if args.categories and report.categories:
        print(f"\nCategories ({len(report.categories)}):")
        for category in report.categories:
            domain = f" [{category.domain}]" if category.domain else ""
            print(f"  {category.name}{domain}: {category.tool_count} tools")


def cmd_search(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    source = args.source

    # Detect source type: pre-built graph JSON or OpenAPI spec
    if source.endswith(".json") and not source.startswith(("http://", "https://")):
        # Could be a pre-built graph or a local OpenAPI spec
        try:
            tg = ToolGraph.load(source)
        except (KeyError, ValueError):
            # Not a graph file — treat as OpenAPI spec
            tg = ToolGraph()
            tg.ingest_openapi(source, allow_private_hosts=args.allow_private_hosts)
    elif source.startswith(("http://", "https://")):
        tg = ToolGraph.from_url(
            source,
            progress=lambda msg: print(f"  {msg}", file=sys.stderr),
            allow_private_hosts=args.allow_private_hosts,
        )
    else:
        tg = ToolGraph()
        tg.ingest_openapi(source, allow_private_hosts=args.allow_private_hosts)

    if args.scores:
        results = tg.retrieve_with_scores(args.query, top_k=args.top_k)
        if args.as_json:
            out = [
                {
                    "name": r.tool.name,
                    "description": r.tool.description,
                    "score": round(r.score, 4),
                    "confidence": r.confidence,
                }
                for r in results
            ]
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            total = len(tg.tools)
            print(f'Query: "{args.query}"')
            print(f"Source: {source} ({total} tools)")
            print(f"Results ({len(results)}):\n")
            for i, r in enumerate(results, 1):
                desc = r.tool.description
                if len(desc) > 70:
                    desc = desc[:70] + "..."
                print(f"  {i}. {r.tool.name}  [{r.score:.4f} {r.confidence}]")
                print(f"     {desc}")
    else:
        results = tg.retrieve(args.query, top_k=args.top_k)
        if args.as_json:
            out = [{"name": t.name, "description": t.description} for t in results]
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            total = len(tg.tools)
            print(f'Query: "{args.query}"')
            print(f"Source: {source} ({total} tools)")
            print(f"Results ({len(results)}):\n")
            for i, t in enumerate(results, 1):
                desc = t.description
                if len(desc) > 70:
                    desc = desc[:70] + "..."
                print(f"  {i}. {t.name}")
                print(f"     {desc}")


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


def cmd_dashboard(args: argparse.Namespace) -> None:
    from graph_tool_call import ToolGraph

    tg = ToolGraph.load(args.graph_file)
    tg.dashboard(host=args.host, port=args.port, debug=args.debug)


def cmd_proxy(args: argparse.Namespace) -> None:
    from graph_tool_call.mcp_proxy import load_proxy_config, run_proxy

    backends, options = load_proxy_config(args.config)
    run_proxy(
        backends,
        top_k=args.top_k or options.get("top_k", 10),
        embedding=args.embedding or options.get("embedding", False),
        passthrough_threshold=(
            args.passthrough_threshold or options.get("passthrough_threshold", 30)
        ),
        cache_path=args.cache_path or options.get("cache_path"),
    )


def cmd_serve(args: argparse.Namespace) -> None:
    from graph_tool_call.mcp_server import run_server

    run_server(
        sources=args.sources,
        graph_file=args.graph_file,
        allow_private_hosts=args.allow_private_hosts,
        transport=args.transport,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "ingest": cmd_ingest,
        "analyze": cmd_analyze,
        "search": cmd_search,
        "retrieve": cmd_retrieve,
        "visualize": cmd_visualize,
        "info": cmd_info,
        "dashboard": cmd_dashboard,
        "proxy": cmd_proxy,
        "serve": cmd_serve,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
