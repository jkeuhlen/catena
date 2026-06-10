"""Command-line entry point: fetch -> parse -> build the citation graph.

    uv run catena build            # run the full pipeline on the seed set
    uv run catena parse <url>      # parse one document, print a summary
    uv run catena fetch <url>      # warm the cache for one URL
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse

from . import fetch, graph, layout, normalize, parse, paths, pontiffs
from .parse import ParsedDocument

# URL "kinds" (the path segment immediately before ``documents/``) whose works
# carry citation footnotes worth pulling into a second corpus layer. Speeches,
# homilies, messages, audiences and angelus are deliberately excluded — they'd
# mostly add leaf nodes with no outgoing citations, widening the graph without
# making it denser.
_LAYER2_PATH_KINDS = {"encyclicals", "apost_exhortations", "apost_letters"}

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


def _is_layer2_candidate(url: str | None) -> bool:
    """True if ``url`` names a vatican.va document worth recursively parsing.

    Accepts encyclicals / apostolic exhortations / apostolic letters from any
    pope, plus all curia-issued documents (``/roman_curia/…/documents/…``)
    and ecumenical council documents (``/archive/hist_councils/…``). The
    Catechism family (``/archive/ENG0015/__P*.HTM``) is excluded — it has no
    parseable footnote structure and is already collapsed onto a single
    metadata node via ``normalize.doc_key_from_url``.
    """
    if not url:
        return False
    p = urlparse(url)
    if "vatican.va" not in p.netloc:
        return False
    parts = [seg for seg in p.path.split("/") if seg]
    if not parts:
        return False
    if parts[0] == "archive" and "ENG0015" in parts:
        return False
    # /roman_curia/<branch>/<body>/documents/… and
    # /archive/hist_councils/<council>/documents/…
    if parts[0] in ("roman_curia", "archive") and "documents" in parts:
        return True
    # /content/<pope>/en/<kind>/documents/…
    if "documents" in parts:
        kind = parts[parts.index("documents") - 1]
        return kind in _LAYER2_PATH_KINDS
    return False


def _collect_layer2_urls(seeds: list[ParsedDocument]) -> list[str]:
    """URLs cited by ``seeds`` that pass the layer-2 filter, deduplicated and
    host-normalised (w2.vatican.va → www.vatican.va), with seed URLs excluded
    since we've already parsed them.
    """
    seed_keys = {d.doc_key for d in seeds}
    # Dedupe by canonical doc_key, not by URL. The same work is often cited with
    # different fragments ("…doc.html#23", "…doc.html#185") that point at the
    # same node — without this, popular works like *Evangelii Gaudium* would be
    # fetched once per citing fragment.
    seen: dict[str, str] = {}  # doc_key → first URL we'll use to fetch it
    for doc in seeds:
        for c in doc.citations:
            if not _is_layer2_candidate(c.url):
                continue
            url = (c.url or "").replace("https://w2.vatican.va",
                                        "https://www.vatican.va")
            # Strip any fragment — it's a footnote/paragraph anchor on the same
            # document, never part of its identity.
            url = url.split("#", 1)[0]
            key = normalize.doc_key_from_url(url)
            if key in seed_keys or key in seen:
                continue
            seen[key] = url
    return list(seen.values())


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
    print(f"Parsing {len(urls)} seed document(s)…", file=sys.stderr)
    docs = [_parse_url(u, force=args.force) for u in urls]

    layer2: list[ParsedDocument] = []
    if not args.no_recurse:
        candidates = _collect_layer2_urls(docs)
        print(f"Layer-2 crawl: parsing {len(candidates)} cited document(s)…",
              file=sys.stderr)
        for url in candidates:
            try:
                layer2.append(_parse_url(url, force=args.force))
            except Exception as exc:  # noqa: BLE001 — one bad page can't sink the build
                print(f"  [skip] {url}: {exc}", file=sys.stderr)

    print("Building graph…", file=sys.stderr)
    g = graph.build_graph(docs, layer2=layer2)
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


def cmd_validate_pontiffs(_args: argparse.Namespace) -> int:
    """Fetch the live /holy-father/ index and check our curated slugs.

    Reports any slug in ``pipeline.pontiffs`` that 404s against the index, plus
    any pope on the index whose English name suggests we should add an entry.
    Exit code is non-zero on mismatches so this can gate a build if wanted.
    """
    import re
    import urllib.request

    url = "https://www.vatican.va/content/vatican/en/holy-father.html"
    print(f"Fetching {url} …", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "catena-validator/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (trusted host)
        html = resp.read().decode("utf-8", errors="replace")

    # Each pope is a /content/vatican/en/holy-father/<slug>.html link.
    slugs = set(re.findall(r"/content/vatican/en/holy-father/([a-z0-9-]+)\.html", html))
    print(f"  found {len(slugs)} pope slugs on the index", file=sys.stderr)

    bad: list[tuple[str, str]] = []
    overrides_checked = 0
    for key, p in pontiffs.all_entries():
        if p.vatican_slug is not None:
            if p.vatican_slug not in slugs:
                bad.append((key, f"slug {p.vatican_slug!r} not on index"))
            continue
        # Override URL — verify it resolves with a HEAD.
        if not p.vatican_url_override:
            bad.append((key, "no vatican_slug and no override"))
            continue
        head = urllib.request.Request(
            p.vatican_url_override, method="HEAD",
            headers={"User-Agent": "catena-validator/1.0"},
        )
        try:
            with urllib.request.urlopen(head, timeout=15) as r:  # noqa: S310
                if r.status >= 400:
                    bad.append((key, f"{p.vatican_url_override} → HTTP {r.status}"))
        except Exception as exc:  # noqa: BLE001 — surface any error verbatim
            bad.append((key, f"{p.vatican_url_override} → {exc}"))
        overrides_checked += 1

    if bad:
        print("\nProblems found:", file=sys.stderr)
        for key, msg in bad:
            print(f"  - {key!r:24}  {msg}", file=sys.stderr)
        return 1
    print(
        f"All {len(pontiffs.all_keys())} curated pontiff entries resolve "
        f"({overrides_checked} via override URL).",
        file=sys.stderr,
    )
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
    p_build.add_argument("--no-recurse", action="store_true",
                         help="skip the depth-1 crawl of cited documents")
    p_build.set_defaults(func=cmd_build)

    p_vp = sub.add_parser(
        "validate-pontiffs",
        help="check curated vatican.va slugs in pipeline.pontiffs against the live index",
    )
    p_vp.set_defaults(func=cmd_validate_pontiffs)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
