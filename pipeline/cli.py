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
#
# Three eras of Vatican HTML, all handled by pipeline.parse:
#   - modern (Leo XIV, Francis, Benedict): footnote/endnote anchors (_ftn/_edn);
#   - pre-2000 (Leo XIII → John Paul II): anchorless plain-text notes after an
#     <hr>, in a zoo of marker styles ((N), N)., N., "N ."), split on their
#     ascending note numbers.
SEEDS: list[str] = [
    # modern (anchor-based)
    "https://www.vatican.va/content/leo-xiv/en/encyclicals/documents/20260515-magnifica-humanitas.html",
    "https://www.vatican.va/content/francesco/en/encyclicals/documents/papa-francesco_20201003_enciclica-fratelli-tutti.html",
    "https://www.vatican.va/content/benedict-xvi/en/encyclicals/documents/hf_ben-xvi_enc_20051225_deus-caritas-est.html",
    "https://www.vatican.va/content/benedict-xvi/en/encyclicals/documents/hf_ben-xvi_enc_20090629_caritas-in-veritate.html",
    "https://www.vatican.va/content/francesco/en/encyclicals/documents/papa-francesco_20150524_enciclica-laudato-si.html",
    "https://www.vatican.va/content/francesco/en/encyclicals/documents/20241024-enciclica-dilexit-nos.html",
    # pre-2000 (anchorless plain-text notes)
    "https://www.vatican.va/content/leo-xiii/en/encyclicals/documents/hf_l-xiii_enc_15051891_rerum-novarum.html",
    "https://www.vatican.va/content/pius-xi/en/encyclicals/documents/hf_p-xi_enc_19310515_quadragesimo-anno.html",
    "https://www.vatican.va/content/john-xxiii/en/encyclicals/documents/hf_j-xxiii_enc_15051961_mater.html",
    "https://www.vatican.va/content/john-xxiii/en/encyclicals/documents/hf_j-xxiii_enc_11041963_pacem.html",
    "https://www.vatican.va/content/paul-vi/en/encyclicals/documents/hf_p-vi_enc_26031967_populorum.html",
    "https://www.vatican.va/content/john-paul-ii/en/encyclicals/documents/hf_jp-ii_enc_14091981_laborem-exercens.html",
    "https://www.vatican.va/content/john-paul-ii/en/encyclicals/documents/hf_jp-ii_enc_30121987_sollicitudo-rei-socialis.html",
    "https://www.vatican.va/content/john-paul-ii/en/encyclicals/documents/hf_jp-ii_enc_01051991_centesimus-annus.html",
    "https://www.vatican.va/content/john-paul-ii/en/encyclicals/documents/hf_jp-ii_enc_06081993_veritatis-splendor.html",
    "https://www.vatican.va/content/john-paul-ii/en/encyclicals/documents/hf_jp-ii_enc_25031995_evangelium-vitae.html",
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
