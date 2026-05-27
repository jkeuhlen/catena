"""Turn parsed documents into a deduplicated node/edge graph.

Node types:
  - ``document``  a magisterial work (encyclical, council document, a saint's text…)
  - ``author``    a person or body (a pope, a saint, a council, a dicastery)
  - ``scripture`` a biblical passage (book + locator)

Edge types:
  - ``cites``           document -> document (a footnote reference)
  - ``authored_by``     document -> author
  - ``cites_scripture`` document -> scripture passage

Documents cited both with and without a Vatican URL are collapsed onto the
URL-backed identity via normalized-title matching, so the same work is one node.
"""

from __future__ import annotations

import re

from . import pontiffs
from .parse import ParsedDocument


def _norm_title(title: str | None) -> str:
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b")
_EIGHT_DIGITS = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_FOUR_DIGITS_BOUND = re.compile(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)")


def _year_of(date: str | None, url: str | None) -> int | None:
    """Promulgation year for the chronological views.

    Tries the parsed ``date`` first (any era's title parenthetical). Falls back
    to the Vatican URL slug — modern paths embed YYYYMMDD, but Leo XIII / Pius
    XI pages use DDMMYYYY, so we try both ends of any 8-digit block.
    """
    if date:
        m = _YEAR_RE.search(date)
        if m:
            return int(m.group(1))
    if url:
        for m in _EIGHT_DIGITS.finditer(url):
            s = m.group(1)
            for cand in (s[:4], s[-4:]):
                y = int(cand)
                if 1500 < y < 2200:
                    return y
        m = _FOUR_DIGITS_BOUND.search(url)
        if m:
            return int(m.group(1))
    return None


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        # normalized title -> canonical (URL-backed) doc key, for cross-source dedup
        self._title_index: dict[str, str] = {}

    # -- node/edge helpers -------------------------------------------------
    def _node(self, node_id: str, node_type: str, **fields) -> dict:
        node = self.nodes.get(node_id)
        if node is None:
            node = {"id": node_id, "type": node_type}
            self.nodes[node_id] = node
        # Merge: only fill empty fields, but let truthy values upgrade falsy ones.
        for k, v in fields.items():
            if v and not node.get(k):
                node[k] = v
        return node

    def _edge(self, src: str, dst: str, etype: str) -> None:
        if src == dst:
            return
        key = (src, dst, etype)
        edge = self.edges.get(key)
        if edge is None:
            self.edges[key] = {"source": src, "target": dst, "type": etype, "weight": 1}
        else:
            edge["weight"] += 1

    # -- ingestion ---------------------------------------------------------
    def index_titles(self, docs: list[ParsedDocument]) -> None:
        """Register URL-backed identities so text-only citations can dedupe."""
        for doc in docs:
            self._title_index[_norm_title(doc.title)] = doc.doc_key
        for doc in docs:
            for c in doc.citations:
                if c.url:
                    self._title_index.setdefault(_norm_title(c.title), c.target_key)

    def _canonical_target(self, c) -> str:
        if c.url:
            return c.target_key
        canonical = self._title_index.get(_norm_title(c.title))
        return canonical or c.target_key

    def add_document(self, doc: ParsedDocument, *, is_source: bool = True) -> None:
        # ``is_source`` distinguishes seeds (the curated corpus the visualisation
        # is *about*) from recursively-parsed layer-2 docs. Both get
        # ``in_corpus=True`` so they receive outgoing edges from their own
        # citations; only seeds get the eyebrow/legend treatment as sources.
        node = self._node(
            doc.doc_key, "document",
            label=doc.title, title=doc.title, author=doc.author,
            author_key=doc.author_key, doc_type=doc.doc_type, url=doc.url,
            date=doc.date, in_corpus=True, is_source=is_source,
        )
        # The fill-only merge in ``_node`` is right for *citations* (a curated
        # value mustn't be clobbered by stale apparatus reaching the same node
        # via a different footnote), but wrong for the document we just parsed:
        # we have authoritative metadata for it, so overwrite the bibliographic
        # fields with parsed truth. (E.g. a footnote that mis-labels Fides et
        # Ratio as "Populorum Progressio" otherwise sticks as the node label.)
        node["label"] = doc.title
        node["title"] = doc.title
        node["author"] = doc.author
        node["author_key"] = doc.author_key
        node["doc_type"] = doc.doc_type
        node["url"] = doc.url
        node["date"] = doc.date
        if doc.author_key:
            aid = f"author:{doc.author_key}"
            self._node(aid, "author", label=doc.author, name=doc.author)
            self._edge(doc.doc_key, aid, "authored_by")

        for c in doc.citations:
            tgt = self._canonical_target(c)
            self._node(
                tgt, "document",
                label=c.title, title=c.title, author=c.author,
                author_key=c.author_key, doc_type=c.doc_type, url=c.url,
            )
            self._edge(doc.doc_key, tgt, "cites")
            if c.author_key:
                aid = f"author:{c.author_key}"
                self._node(aid, "author", label=c.author, name=c.author)
                self._edge(tgt, aid, "authored_by")

        for s in doc.scripture:
            locator = s["cite"][len(s["book"]) + 1:]
            sid = f"scripture:{s['book']}|{locator}"
            self._node(
                sid, "scripture",
                label=s["cite"], cite=s["cite"], book=s["book"],
                testament=s["testament"], order=s["order"],
            )
            for _ in range(s["count"]):
                self._edge(doc.doc_key, sid, "cites_scripture")

    # -- finalize ----------------------------------------------------------
    def finalize(self) -> dict:
        # mark non-source documents as out-of-corpus and default missing flags
        for n in self.nodes.values():
            if n["type"] == "document":
                n.setdefault("in_corpus", False)
                n.setdefault("is_source", False)
        # promulgation year on every document node (used by the Timeline /
        # Lineage views; ``None`` for works without a parseable date or URL).
        for n in self.nodes.values():
            if n["type"] == "document":
                n["year"] = _year_of(n.get("date"), n.get("url"))
        # tag author nodes that name a pope with their pontiff record so the
        # site can render the specialised card. The legend category stays
        # ``author`` — filters and counts are unaffected.
        for n in self.nodes.values():
            if n["type"] != "author":
                continue
            key = n["id"].removeprefix("author:")
            rec = pontiffs.lookup(key)
            if rec:
                n["pontiff"] = rec
        # degree (undirected) for sizing
        deg: dict[str, int] = {nid: 0 for nid in self.nodes}
        for e in self.edges.values():
            deg[e["source"]] += e["weight"]
            deg[e["target"]] += e["weight"]
        for nid, d in deg.items():
            self.nodes[nid]["degree"] = d
        return {
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
        }


def build_graph(
    docs: list[ParsedDocument],
    *,
    layer2: list[ParsedDocument] | None = None,
) -> dict:
    """Assemble the graph. ``docs`` are seeds (is_source=True); the optional
    ``layer2`` is the depth-1 crawl of works the seeds cite (is_source=False).
    """
    gb = GraphBuilder()
    all_docs = docs + (layer2 or [])
    gb.index_titles(all_docs)
    for doc in docs:
        gb.add_document(doc, is_source=True)
    for doc in (layer2 or []):
        gb.add_document(doc, is_source=False)
    graph = gb.finalize()
    graph["meta"] = {
        "documents": sum(1 for n in graph["nodes"] if n["type"] == "document"),
        "in_corpus": sum(1 for n in graph["nodes"] if n.get("in_corpus")),
        "authors": sum(1 for n in graph["nodes"] if n["type"] == "author"),
        "scripture": sum(1 for n in graph["nodes"] if n["type"] == "scripture"),
        "edges": len(graph["edges"]),
    }
    return graph
