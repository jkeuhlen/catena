"""Parse a Vatican encyclical HTML page into a structured document.

Extracts the document's own metadata (pope, title, type, date, canonical URL)
and walks its footnotes into structured citations, plus all inline scripture
references. The Vatican HTML is a Word export: footnotes are
``<p class="MsoFootnoteText">`` blocks, each led by ``<a name="_ftnN">`` (older
texts use *endnotes* with the ``_edn`` prefix instead — handled identically).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace

from bs4 import BeautifulSoup, NavigableString, Tag

from . import normalize, scripture, works

# Italic tokens that are never a work title (citation apparatus, not works).
# "Ep" / "Hom" are the Latin work-form abbreviations (Epistula, Homilia) that
# show up italicized in patristic citations like "Ep. 204, 5: CSEL 57, 320" —
# the work is identified by author + number, not a real title.
_NOT_A_TITLE = re.compile(r"^(ibid|op\.?\s*cit|loc\.?\s*cit|AAS|cf|ep|hom)\b", re.IGNORECASE)
_IBID = re.compile(r"\bibid\b", re.IGNORECASE)
# "ibid." → the *same work* as the previous footnote; "idem"/"id." → the *same
# author* but (usually) a new work. Both are apparatus, never a person's name.
_IBID_LEAD = re.compile(r"^\s*(cf\.?\s*)?ibid\b", re.IGNORECASE)
_IDEM_LEAD = re.compile(r"^\s*(cf\.?\s*)?(idem|id)\b\.?", re.IGNORECASE)
_APPARATUS_KEYS = {"ibid", "idem", "id"}
# A quoted phrase opening a footnote ("…", AUTHOR, Work) — apparatus, not a name.
_LEAD_QUOTE = re.compile(r'^\s*[“"«][^”"»]{0,120}[”"»][\s,;:.()]*')

_ROMAN = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
# Vatican URL slugs that are Italian-only for popes whose English name differs.
_POPE_SLUG_OVERRIDES = {"francesco": "Francis", "benedict-xvi": "Benedict XVI"}


@dataclass(frozen=True)
class Citation:
    footnote: int
    target_key: str          # canonical node id of the cited work
    title: str | None
    url: str | None
    author: str | None       # display form, e.g. "Saint John Paul II"
    author_key: str | None   # normalized key for dedup
    doc_type: str | None


@dataclass
class ParsedDocument:
    source_url: str
    url: str                 # canonical URL
    doc_key: str             # canonical node id of this document
    title: str
    raw_title: str
    author: str
    author_key: str
    doc_type: str | None
    date: str | None
    footnote_count: int
    citations: list[Citation] = field(default_factory=list)
    scripture: list[dict] = field(default_factory=list)  # {cite, book, testament, order, count}

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _pope_from_slug(slug: str) -> str:
    if slug in _POPE_SLUG_OVERRIDES:
        return _POPE_SLUG_OVERRIDES[slug]
    words = []
    for part in slug.split("-"):
        words.append(part.upper() if _ROMAN.match(part) else part.capitalize())
    return " ".join(words)


def _meta_content(soup: BeautifulSoup, **attrs) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    if isinstance(tag, Tag):
        c = tag.get("content")
        if isinstance(c, str):
            return c.strip()
    return None


def _canonical_url(soup: BeautifulSoup, source_url: str) -> str:
    link = soup.find("link", rel="canonical")
    if isinstance(link, Tag):
        href = link.get("href")
        if isinstance(href, str) and href:
            return href.replace("http://", "https://")
    og = _meta_content(soup, property="og:url")
    if og:
        return og.replace("http://", "https://")
    return source_url


def _document_links(p: Tag) -> list[tuple[str, str]]:
    """(url, link_text) for each magisterial-document link in a footnote."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in p.find_all("a", href=True):
        href = a["href"]
        if not isinstance(href, str) or href.startswith("#"):
            continue
        if not normalize.is_document_url(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append((href, a.get_text(" ", strip=True)))
    return out


def _clean_lead(text: str) -> str:
    """Strip leading reference apparatus: "cf.", then a quoted phrase, then "cf." again."""
    text = normalize.strip_cf(text)
    text = _LEAD_QUOTE.sub("", text).lstrip(" (")
    return normalize.strip_cf(text).strip()


def _author_type(prefix: str) -> tuple[str | None, str | None, str | None]:
    """From the text that precedes a work's title, guess (author, key, type).

    The convention is "[cf.] AUTHOR, TYPE", so the author is whatever comes
    before the first type keyword. If the prefix *starts* with a type keyword
    (e.g. "Encyclical Letter …"), there is no named author.
    """
    prefix = _clean_lead(prefix)
    # Conciliar-session apparatus ("Sess. IV", "Session VI") is location, not author.
    prefix = re.sub(r"^\s*Sess(?:\.|ion)?\s+[IVXLCDM\d]+[,.\s]*", "", prefix, flags=re.IGNORECASE)
    # A semicolon in a citation tail almost always introduces a second cited work
    # ("Work1; Author2, Work2") or apparatus ("can. 394; Code of Canons of the
    # Eastern Churches"); keep only what precedes it so the second author / title
    # doesn't leak into the first citation. Real personal names never contain ";".
    prefix = prefix.split(";", 1)[0].strip()
    # Strip a trailing scholarly-source locator ("…AAS 23 (1931) 221 et seq",
    # "…PG 32, 972", "CSEL 57"); these are reference apparatus, not author names.
    prefix = re.sub(
        r"[,;\s]+(?:AAS|PG|PL|CSEL|CCL|CCSL|DS|SC|LCC)\s+\d.*$", "", prefix
    ).strip()
    canonical_type, type_idx = normalize.detect_type(prefix)
    if type_idx > 0:
        author_raw = prefix[:type_idx]
    elif type_idx == 0:
        author_raw = ""            # starts with the type → no leading author
    else:
        author_raw = prefix        # no type keyword → the whole prefix is the author
    author_raw = author_raw.strip().strip(",").strip()
    # a title fragment ("…, A Pastoral Letter") can leave a dangling article
    author_raw = re.sub(r",\s*(?:[a-z]|an|the)$", "", author_raw, flags=re.IGNORECASE).strip()
    # legacy "<Pope>'s encyclical letter <Title>" leaves a trailing possessive
    author_raw = re.sub(r"['’]s$", "", author_raw).strip()
    if not author_raw or len(author_raw) > 80:
        return None, None, canonical_type
    key, display = normalize.normalize_author(author_raw)
    return display, key, canonical_type


def _first_title(p: Tag) -> str | None:
    for i in p.find_all("i"):
        t = i.get_text(" ", strip=True)
        # Source markup sometimes italicizes the trailing comma/period along with
        # the title ("<i>Iura et Bona,</i>"); also CamelCase artifacts from lost
        # spaces ("Gaudium etSpes", "QuadragesimoAnno") — split before further use.
        t = re.sub(r"([a-zà-ÿ])([A-ZÀ-Ý])", r"\1 \2", t).rstrip(",.;:")
        # A real title has at least one letter (rejects stray italicized commas).
        # An italicized scripture sigil ("Ps", "Gen") is a reference, not a title —
        # crucial for legacy notes, which are largely bare scripture citations.
        if (t and re.search(r"[A-Za-zÀ-ÿ]", t)
                and not _NOT_A_TITLE.match(t)
                and not scripture.is_book(t)):
            return t
    return None


def _footnote_number(p: Tag) -> int | None:
    back = p.find("a", href=re.compile(r"^#_(?:ftn|edn)ref\d+"))
    if not isinstance(back, Tag):
        return None
    href = back.get("href", "")
    m = re.search(r"\d+", href if isinstance(href, str) else "")
    return int(m.group()) if m else None


def _strip_marker(text: str, number: int) -> str:
    """Remove a leading note marker, tolerating the many styles across eras.

    Modern footnotes use "[N]" (and occasionally the malformed "185]" with a
    dropped bracket); legacy notes use "(N)", "N)." or a bare "N." instead. We
    strip the known number with optional surrounding bracket/parenthesis.
    """
    return re.sub(rf"^\s*[\[(]?\s*{number}\s*[\])]?[.\s]*", "", text)


def _prefix_before_first_doclink(p: Tag) -> str | None:
    """Text appearing before the first document link, or None if there is none."""
    first = None
    for a in p.find_all("a", href=True):
        href = a.get("href", "")
        if isinstance(href, str) and normalize.is_document_url(href):
            first = a
            break
    if first is None:
        return None
    parts: list[str] = []
    for node in p.descendants:
        if node is first:
            break
        if isinstance(node, NavigableString):
            parts.append(str(node))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _parse_note(number: int, p: Tag, prev: Citation | None) -> tuple[list[Citation], Citation | None]:
    """Parse one note (foot- or endnote) given its number and the previous primary
    citation for ibid. resolution.

    Returns ``(citations, new_prev)`` where ``new_prev`` is the primary citation
    to carry forward (the work a following ``ibid.`` would refer to). The number is
    passed in because the various note formats locate it differently (an anchor's
    name, a back-link href, or a leading "(N)"/"N)." text marker).
    """
    text = _strip_marker(p.get_text(" ", strip=True), number)
    # Legacy splitting consumes the bare note number but can leave its orphan
    # punctuation ("N." → ". Leo XIII…"); drop it so "cf." stripping and author
    # detection see a clean lead.
    text = re.sub(r"^[\s.)\]]+", "", text)
    is_ibid = bool(_IBID_LEAD.match(text))    # same work
    is_idem = bool(_IDEM_LEAD.match(text))    # same author, new work
    links = _document_links(p)

    # Author/type. When the footnote links to a work, the link text is the
    # title, so the author is whatever precedes that link (often nothing). For
    # link-less footnotes we fall back to scanning the whole text.
    if links:
        prefix = _prefix_before_first_doclink(p) or ""
        author, author_key, doc_type = _author_type(_strip_marker(prefix, number))
    else:
        # link-less "[cf.] AUTHOR, TITLE, locator": the author runs up to the
        # first type keyword, else the first comma or colon ("Aquinas: Summa…").
        head = _clean_lead(text)
        _, idx = normalize.detect_type(head)
        candidate = head if idx >= 0 else re.split(r"\s*[,:]\s*", head, maxsplit=1)[0]
        author, author_key, doc_type = _author_type(candidate)

    # "ibid."/"idem"/"id." never name a new author — inherit from the previous
    # work. "ibid." also carries the previous type (it's the same work).
    if is_ibid or is_idem or author_key in _APPARATUS_KEYS:
        if prev is not None:
            author, author_key = prev.author, prev.author_key
            if is_ibid:
                doc_type = prev.doc_type
        else:
            author, author_key = None, None

    citations: list[Citation] = []
    if links:
        for url, link_text in links:
            doc_key = normalize.doc_key_from_url(url)
            title = link_text.strip()
            if not title or _IBID.search(title):
                title = (prev.title if prev else None) or normalize.title_from_slug(doc_key)
            citations.append(
                Citation(
                    footnote=number,
                    target_key=doc_key,
                    title=title,
                    url=url.replace("http://", "https://"),
                    author=author,
                    author_key=author_key,
                    # infer a type from the title when the prefix gave none
                    doc_type=doc_type or normalize.detect_type(title)[0],
                )
            )
        return citations, citations[0]

    # No link. A bare "ibid." inherits the entire previous target.
    if is_ibid and prev is not None:
        cite = Citation(
            footnote=number,
            target_key=prev.target_key,
            title=prev.title,
            url=prev.url,
            author=prev.author,
            author_key=prev.author_key,
            doc_type=prev.doc_type,
        )
        return [cite], prev

    # A work without an online edition (a saint, a council, an old text).
    title = _first_title(p)
    # If the candidate "author" is just the same text we picked as the title,
    # the footnote really named only a work ("Cf. <i>Title</i>, …") — there is
    # no author, not the title-as-author. works.py can still supply one later.
    if author and title and author.strip().lower() == title.strip().lower():
        author, author_key = None, None
    # Emit any real title even without an author or type — bare "Cf. <i>Title</i>"
    # is common, and works.py / the title-index will attach the right identity if
    # the work is known.
    if title:
        slug = re.sub(r"[^a-z0-9]+", "-", f"{author_key or ''} {title}".lower()).strip("-")
        cite = Citation(
            footnote=number,
            target_key=f"doc:{slug}",
            title=title,
            url=None,
            author=author,
            author_key=author_key,
            doc_type=doc_type,
        )
        return [cite], cite
    return [], prev


def _canonicalize(c: Citation) -> Citation:
    """Map a citation of a famous work onto its curated canonical identity.

    Fixes authorship (e.g. attributes every form of the *Summa* to Aquinas) and,
    for works without an online edition, unifies the node key so the variants
    collapse to one node.
    """
    work = works.lookup(c.title)
    if work is None:
        return c
    key, _ = normalize.normalize_author(work.author)
    return replace(
        c,
        author=work.author,
        author_key=key,
        title=work.title,
        target_key=work.key if c.url is None else c.target_key,
    )


def _parse_metadata(soup: BeautifulSoup, source_url: str) -> dict:
    url = _canonical_url(soup, source_url)
    # pope slug: /content/<pope>/... ; fall back to a generic author.
    slug_m = re.search(r"/content/([^/]+)/", url) or re.search(r"/([a-z-]+)/[a-z_]+/documents/", url)
    pope_slug = slug_m.group(1) if slug_m else "unknown"
    author = _pope_from_slug(pope_slug)
    author_key, author = normalize.normalize_author(author)

    raw_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    # The meta description carries the formal heading ("ENCYCLICAL LETTER … OF …"),
    # which is uniform across eras even when the <title> tag is terse.
    desc = (_meta_content(soup, name="description")
            or _meta_content(soup, property="og:description") or "")
    doc_type, _ = normalize.detect_type(raw_title)
    if not doc_type:
        # descriptions are sometimes ALL-CAPS; title-case so type words match
        doc_type, _ = normalize.detect_type(desc.title())

    date = None
    dm = re.search(r"\(([^)]*\b\d{4})\)\s*$", raw_title)
    if dm:
        date = dm.group(1).strip()

    # title (work name): drop a trailing "(date)", then the "of His Holiness <Pope>"
    # preamble if present (older format); otherwise the remainder is the title.
    base = re.sub(r"\s*\([^)]*\b\d{4}\)\s*$", "", raw_title).strip()
    tm = re.search(r"of His Holiness\s+(.*)$", base)
    title = (tm.group(1) if tm else base).strip()
    title = re.sub(rf"^{re.escape(author)}\s+", "", title).strip()   # leading pope name
    ct, ci = normalize.detect_type(title)
    if ci == 0 and ct:                                                # leading type phrase
        for phrase, _canon in normalize._TYPE_PATTERNS:
            if title.startswith(phrase):
                title = title[len(phrase):].strip()
                break
    title = re.sub(r"\s+", " ", title or base or raw_title).strip()

    return {
        "source_url": source_url,
        "url": url,
        "doc_key": normalize.doc_key_from_url(url),
        "title": title,
        "raw_title": raw_title,
        "author": author,
        "author_key": author_key,
        "doc_type": doc_type,
        "date": date,
    }


# --- note collection across the eras of Vatican HTML ---------------------------
# A "note block" is a (number, <p>) pair the shared parser can read. Modern pages
# anchor each note (_ftn/_edn); pre-2000 pages don't, so we fall back to splitting
# the post-<hr> notes region on its ascending note numbers (see _legacy_notes).


def _anchor_notes(soup: BeautifulSoup) -> list[tuple[int, Tag]]:
    """Modern foot-/endnotes: bodies marked by a back-link anchor (name="_ftnN" /
    "_ednN", href="#_ftnrefN" / "#_ednrefN"). Older pages wrap each in
    <p class="MsoFootnoteText">; newer ones use a bare <p>. Most JP2 / Benedict
    pages use *endnotes* (_edn) — same structure, different prefix. Select by the
    anchor, not the class."""
    out: list[tuple[int, Tag]] = []
    seen: set[int] = set()
    for a in soup.find_all("a", attrs={"name": re.compile(r"^_(?:ftn|edn)\d+$")}):
        href = a.get("href", "")
        if not (isinstance(href, str) and href.startswith(("#_ftnref", "#_ednref"))):
            continue
        block = a.find_parent("p") or a.parent
        if not isinstance(block, Tag) or id(block) in seen:
            continue
        seen.add(id(block))
        number = _footnote_number(block)
        if number is not None:
            out.append((number, block))
    return out


# A note-number bookmark anchor in legacy pages: <a name="$N">/<a href="#-N">…</a>
# (the "$" is URL-encoded as %24). Its visible text is the note number — collapse
# it to bare text so the number joins the marker stream below.
_NOTE_ANCHOR = re.compile(r'<a\b[^>]*(?:name="[^"]*"|href="#[^"]*")[^>]*>\s*(\d*)\s*</a>')
# Where the notes region gives way to page chrome.
_REGION_END = re.compile(r"<footer\b|<!--\s*END:\s*body|Copyright\s*(?:©|&copy;|&#169;)", re.I)
# Tags after which a number at the start of the next text is a note marker.
_BLOCK_TAG = re.compile(r"^<\s*/?\s*(?:p|br|div|hr|td|tr|table|li|font)\b", re.I)


def _notes_region_html(html: str) -> str:
    """Raw HTML of the notes section: everything after the last <hr>, before the
    page footer. Every pre-2000 encyclical separates its notes with a single <hr>."""
    i = html.rfind("<hr")
    if i == -1:
        return ""
    region = html[html.find(">", i) + 1:]
    return _REGION_END.split(region, maxsplit=1)[0]


def _match_marker(text: str, want: int, at_boundary: bool):
    """Match the marker for note ``want`` in ``text``: either a number at a block
    boundary (start of a <p>/after a <br> — covers "(N)", "N).", "N." and the bare
    bookmark number) or a "N ." / "N )" with a space before the punctuation (covers
    notes crammed into one <p>). The space rule keeps locators like "22." — no
    space — from being mistaken for a marker. A boundary marker tolerates a stray
    leading section number ("14. (6)…" seen in Populorum Progressio)."""
    if at_boundary:
        m = re.match(rf"\s*(?:\d{{1,3}}[.)]\s+)?\(?\s*{want}\s*\)?\s*\.?(?!\d)", text)
        if m and re.search(rf"(?<!\d){want}(?!\d)", m.group()):
            return m
    return re.search(rf"(?<![\d.]){want}\s+[).]", text)


def _legacy_notes(html: str) -> list[tuple[int, Tag]]:
    """Pre-2000 encyclicals carry no note anchors. Slice the post-<hr> notes region
    and split it on the ascending note numbers — the one signal common to every
    era's marker zoo — re-parsing each span into a <p> the shared parser can read."""
    region = _NOTE_ANCHOR.sub(r" \1 ", _notes_region_html(html))
    if not region.strip():
        return []
    notes: list[tuple[int, Tag]] = []
    cur: list[str] = []
    cur_num: int | None = None
    boundary = True

    def emit() -> None:
        if cur_num is None:
            return
        block = BeautifulSoup(f"<p>{''.join(cur)}</p>", "lxml").find("p")
        if isinstance(block, Tag):
            notes.append((cur_num, block))

    for tok in re.split(r"(<[^>]+>)", region):
        if not tok:
            continue
        if tok.startswith("<"):
            if cur_num is not None:
                cur.append(tok)
            if _BLOCK_TAG.match(tok):
                boundary = True
            continue
        if not tok.strip():
            # whitespace between a <br>/<b> and the note number must not consume
            # the boundary (else the number is read as body text, not a marker).
            if cur_num is not None:
                cur.append(tok)
            continue
        text, first = tok, True
        while text:
            want = cur_num + 1 if cur_num is not None else 1
            m = _match_marker(text, want, boundary and first)
            if not m:
                if cur_num is not None:
                    cur.append(text)
                break
            before = text[:m.start()]
            if cur_num is not None and before.strip():
                cur.append(before)
            emit()
            cur, cur_num = [], want
            text, first = text[m.end():], False
        boundary = False
    emit()
    return notes


def _collect_notes(soup: BeautifulSoup, html: str) -> list[tuple[int, Tag]]:
    """All notes as (number, block) pairs: modern anchors, else the legacy split."""
    return _anchor_notes(soup) or _legacy_notes(html)


def parse_document(html: str, source_url: str) -> ParsedDocument:
    soup = BeautifulSoup(html, "lxml")
    meta = _parse_metadata(soup, source_url)

    notes = _collect_notes(soup, html)
    citations: list[Citation] = []
    prev: Citation | None = None
    for number, block in notes:
        cites, prev = _parse_note(number, block, prev)
        citations.extend(cites)
    # map famous works onto their curated canonical identity (author + key)
    citations = [_canonicalize(c) for c in citations]

    # Scripture references across the whole document (body + footnotes).
    refs = scripture.parse_refs(soup.get_text(" "))
    counts: dict[str, dict] = {}
    for r in refs:
        entry = counts.setdefault(
            r.node_id,
            {"cite": r.cite, "book": r.book, "testament": r.testament, "order": r.order, "count": 0},
        )
        entry["count"] += 1

    return ParsedDocument(
        **meta,
        footnote_count=len(notes),
        citations=citations,
        scripture=list(counts.values()),
    )
