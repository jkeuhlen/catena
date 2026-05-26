"""Normalization of authors, document types, and document identities.

Citations name the same work and the same person in many surface forms
("Saint John Paul II" / "John Paul II"; ``_en`` vs ``_sp`` URLs). These helpers
collapse those variants onto stable keys so the graph dedupes correctly, while
preserving a human-friendly display string.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Honorifics stripped when keying a person, kept in the display name.
_HONORIFICS = [
    "his holiness",
    "pope",
    "saint",
    "st.",
    "st",
    "blessed",
    "bl.",
    "servant of god",
    "venerable",
]

# Canonical document/work types and the surface phrases that map to them.
# Order matters: longer/more-specific phrases first.
_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("Dogmatic Constitution", "Dogmatic Constitution"),
    ("Pastoral Constitution", "Pastoral Constitution"),
    ("Apostolic Constitution", "Apostolic Constitution"),
    ("Post-Synodal Apostolic Exhortation", "Apostolic Exhortation"),
    ("Apostolic Exhortation", "Apostolic Exhortation"),
    ("Apostolic Exaltation", "Apostolic Exhortation"),    # recurring source typo
    ("Aposotolic Exhortation", "Apostolic Exhortation"),  # …and another
    ("Apostolic Letter", "Apostolic Letter"),
    ("Pastoral Letter", "Pastoral Letter"),
    ("Encyclical Letter", "Encyclical"),
    ("Encyclical Epistle", "Encyclical"),    # older curial phrasing
    ("Encyc. Letter", "Encyclical"),         # abbreviation in pre-2000 notes
    ("Encyc.letter", "Encyclical"),          # …sometimes without the space
    ("Encyclical", "Encyclical"),
    ("Motu Proprio", "Motu Proprio"),
    ("Radio Message", "Message"),
    ("Message", "Message"),
    ("Homily", "Homily"),
    ("Address", "Address"),
    ("Declaration", "Declaration"),
    ("Decree", "Decree"),
    ("Constitution", "Constitution"),
    ("Bull", "Bull"),
    ("Catechism", "Catechism"),
    ("Letter", "Letter"),
]

# Leading reference markers ("cf.", "cfr.", "see"). The trailing separator is
# optional so we also catch "Cf." at the very end and "Cf.Pontifical" (no space).
_LEADING_CF = re.compile(r"^\s*(?:cfr|cf|see)\b\.?\s*", re.IGNORECASE)


def strip_cf(text: str) -> str:
    return _LEADING_CF.sub("", text).strip()


# Lowercased nobiliary/grammatical particles that stay lowercase mid-name.
_PARTICLES = {
    "de", "del", "della", "dei", "di", "da", "du", "des", "von", "van", "der",
    "den", "la", "le", "les", "el", "y", "of", "for", "and", "the", "in", "on", "à",
}
_INITIALS = re.compile(r"(?:[A-Za-zÀ-ÿ]\.){1,}$")          # "J.R.R." / "O.F.M."
_ROMAN = re.compile(r"^(?=[MDCLXVI])M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def _recase_word(w: str) -> str:
    if _INITIALS.fullmatch(w) or _ROMAN.match(w):     # acronyms, initials, "XVI"
        return w.upper()
    # capitalize each hyphenated segment, preserving accents ("Hoyos-Vásquez")
    return "-".join(s[:1].upper() + s[1:].lower() if s else s for s in w.split("-"))


def recase_name(name: str) -> str:
    """Title-case a SHOUTING name; leave already-mixed-case names untouched.

    Footnotes often cite modern authors and bishops' conferences in all caps
    ("PAUL RICOEUR", "CONGREGATION FOR THE DOCTRINE OF THE FAITH"). Only names
    with no lowercase letters are re-cased, so "Saint Augustine" and
    "J.R.R. Tolkien" are preserved.
    """
    if any(c.islower() for c in name):
        return name
    words = name.split()
    out = []
    for i, w in enumerate(words):
        out.append(w.lower() if i and w.lower() in _PARTICLES else _recase_word(w))
    return " ".join(out)


def normalize_author(raw: str) -> tuple[str, str]:
    """Return ``(key, display)`` for a person/body named in a citation."""
    display = re.sub(r"\s+", " ", raw).strip().strip(",.").strip()
    key = display.lower()
    for h in _HONORIFICS:
        # remove honorific tokens wherever they lead the name
        key = re.sub(rf"^{re.escape(h)}\s+", "", key)
    key = re.sub(r"[^a-z0-9 ]", "", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key or display.lower(), recase_name(display)


def detect_type(text: str) -> tuple[str | None, int]:
    """Find the first document-type phrase in ``text``.

    Returns ``(canonical_type, index)`` where ``index`` is the character offset
    of the match (``-1`` if none found), useful for splitting author from title.

    Multi-word phrases ("Encyclical Letter", "Pastoral Constitution") match
    case-insensitively — legacy notes lowercase them — while short single words
    ("Letter", "Message", "Bull") stay case-sensitive so the English words
    "letter"/"message" in prose don't false-match. "Encyclical" is long and
    unambiguous enough to also be case-insensitive — that catches the recurring
    legacy pattern "<Pope>'s encyclical <Title>".
    """
    best: tuple[str | None, int] = (None, -1)
    for phrase, canonical in _TYPE_PATTERNS:
        flags = re.IGNORECASE if (" " in phrase or "." in phrase or phrase == "Encyclical") else 0
        m = re.search(rf"\b{re.escape(phrase)}\b", text, flags)
        if m and (best[1] == -1 or m.start() < best[1]):
            best = (canonical, m.start())
    return best


def is_document_url(url: str) -> bool:
    """True for vatican.va links that point at an actual magisterial document."""
    if not url:
        return False
    p = urlparse(url)
    if "vatican.va" not in p.netloc:
        return False
    path = p.path.lower()
    # Document pages end in .html/.htm and live under a documents/ or archive path.
    return path.endswith((".html", ".htm")) and (
        "/documents/" in path or "/archive/" in path or "_enc_" in path
    )


_LANG_SUFFIX = re.compile(r"_(en|sp|it|la|fr|ge|po|pt|de)$", re.IGNORECASE)


def doc_key_from_url(url: str) -> str:
    """Stable, language-independent key for a document URL.

    Uses the final path segment's stem with any trailing language suffix
    removed, e.g. ``vat-ii_const_19651207_gaudium-et-spes`` for any language
    edition of Gaudium et Spes. Also collapses the ``_cons_`` typo (seen on
    one Gaudium et Spes URL) onto the standard ``_const_`` form.
    """
    path = urlparse(url).path
    stem = path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(html?|HTML?)$", "", stem)
    stem = _LANG_SUFFIX.sub("", stem)
    stem = re.sub(r"(?<=vat-ii)_cons_", "_const_", stem, flags=re.IGNORECASE)
    return f"doc:{stem.lower()}"


# date-like token inside a slug, e.g. _30121987_ or _19651207_
_SLUG_DATE = re.compile(r"\d{6,8}")


def title_from_slug(doc_key: str) -> str:
    """Best-effort display title from a doc key when no link text is available."""
    stem = doc_key.removeprefix("doc:")
    parts = stem.split("_")
    # keep the segment(s) after the last date-like token
    tail: list[str] = []
    for part in parts:
        if _SLUG_DATE.fullmatch(part):
            tail = []
        else:
            tail.append(part)
    words = "-".join(tail).replace("-", " ").split()
    return " ".join(w.capitalize() for w in words) or stem
