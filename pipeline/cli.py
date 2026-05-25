"""Command-line entry point: fetch -> parse -> build the citation graph.

    uv run catena build            # run the full pipeline on the seed set
    uv run catena parse <url>      # parse one document, print a summary
    uv run catena fetch <url>      # warm the cache for one URL
"""

from __future__ import annotations

import argparse
import json
import sys

from . import fetch, graph, layout, parse, paths
from .parse import ParsedDocument

# The corpus seed set. Add more encyclical URLs here to grow the graph.
SEEDS: list[str] = [
    "https://www.vatican.va/content/leo-xiv/en/encyclicals/documents/20260515-magnifica-humanitas.html",
    "https://www.vatican.va/content/francesco/en/encyclicals/documents/papa-francesco_20201003_enciclica-fratelli-tutti.html",
]


def _parse_url(url: str, *, force: bool = False) -> ParsedDocument:
    result = fetch.fetch(url, force=force)
    doc = parse.parse_document(result.html, url)
    out = paths.PARSED / f"{doc.doc_key.removeprefix('doc:')}.json"
    out.write_text(json.dumps(doc.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    cached = "cache" if result.from_cache else "fetched"
    print(f"  [{cached}] {doc.title} — {len(doc.citations)} citations, "
          f"{len(doc.scripture)} scripture refs", file=sys.stderr)
    return doc


def cmd_fetch(args: argparse.Namespace) -> int:
    res = fetch.fetch(args.url, force=args.force)
    print(f"{'cache' if res.from_cache else 'fetched'}: {len(res.html):,} bytes")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    doc = _parse_url(args.url, force=args.force)
    print(json.dumps(doc.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    urls = args.urls or SEEDS
    print(f"Parsing {len(urls)} document(s)…", file=sys.stderr)
    docs = [_parse_url(u, force=args.force) for u in urls]

    print("Building graph…", file=sys.stderr)
    g = graph.build_graph(docs)
    print("Computing layout…", file=sys.stderr)
    g = layout.compute_layout(g)

    payload = json.dumps(g, ensure_ascii=False, separators=(",", ":"))
    for target in (paths.GRAPH / "graph.json", paths.SITE_DATA / "graph.json"):
        target.write_text(payload, encoding="utf-8")

    m = g["meta"]
    print(
        f"Graph: {len(g['nodes'])} nodes, {m['edges']} edges "
        f"({m['documents']} documents [{m['in_corpus']} in-corpus], "
        f"{m['authors']} authors, {m['scripture']} scripture)",
        file=sys.stderr,
    )
    print(f"Wrote {paths.GRAPH / 'graph.json'} and {paths.SITE_DATA / 'graph.json'}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catena", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="fetch and cache a URL")
    p_fetch.add_argument("url")
    p_fetch.add_argument("--force", action="store_true", help="bypass the cache")
    p_fetch.set_defaults(func=cmd_fetch)

    p_parse = sub.add_parser("parse", help="parse one document and print JSON")
    p_parse.add_argument("url")
    p_parse.add_argument("--force", action="store_true", help="bypass the cache")
    p_parse.set_defaults(func=cmd_parse)

    p_build = sub.add_parser("build", help="build the full graph from the seed set")
    p_build.add_argument("urls", nargs="*", help="override the seed URLs")
    p_build.add_argument("--force", action="store_true", help="bypass the cache")
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
