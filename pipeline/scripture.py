"""Parse and normalize biblical citations such as ``Prov 8:22-31``.

Encyclicals cite scripture inline (``cf. Prov 8:22-31``) using abbreviated book
names, italicized in the source HTML. This module maps the abbreviations the
Vatican uses onto canonical book names (Catholic 73-book canon) and extracts
structured references from arbitrary text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (canonical name, testament, [accepted abbreviations]).
# Order is canonical scripture order; the list index doubles as a sort key.
_BOOKS: list[tuple[str, str, list[str]]] = [
    # --- Old Testament ---
    ("Genesis", "OT", ["Gen", "Gn"]),
    ("Exodus", "OT", ["Ex", "Exod"]),
    ("Leviticus", "OT", ["Lev", "Lv"]),
    ("Numbers", "OT", ["Num", "Nm", "Nb"]),
    ("Deuteronomy", "OT", ["Deut", "Dt"]),
    ("Joshua", "OT", ["Josh", "Jos"]),
    ("Judges", "OT", ["Judg", "Jdg", "Jgs"]),
    ("Ruth", "OT", ["Ruth", "Ru"]),
    ("1 Samuel", "OT", ["1 Sam", "1 Sm", "1Sam"]),
    ("2 Samuel", "OT", ["2 Sam", "2 Sm", "2Sam"]),
    ("1 Kings", "OT", ["1 Kings", "1 Kgs", "1 Kg"]),
    ("2 Kings", "OT", ["2 Kings", "2 Kgs", "2 Kg"]),
    ("1 Chronicles", "OT", ["1 Chron", "1 Chr"]),
    ("2 Chronicles", "OT", ["2 Chron", "2 Chr"]),
    ("Ezra", "OT", ["Ezra", "Ezr"]),
    ("Nehemiah", "OT", ["Neh", "Ne"]),
    ("Tobit", "OT", ["Tob", "Tb"]),
    ("Judith", "OT", ["Jdt", "Jth"]),
    ("Esther", "OT", ["Esth", "Est"]),
    ("1 Maccabees", "OT", ["1 Macc", "1 Mac", "1 Mc"]),
    ("2 Maccabees", "OT", ["2 Macc", "2 Mac", "2 Mc"]),
    ("Job", "OT", ["Job", "Jb"]),
    ("Psalms", "OT", ["Ps", "Pss", "Psalm"]),
    ("Proverbs", "OT", ["Prov", "Prv", "Pr"]),
    ("Ecclesiastes", "OT", ["Eccl", "Eccles", "Qoh"]),
    ("Song of Songs", "OT", ["Song", "Sg", "Cant"]),
    ("Wisdom", "OT", ["Wis", "Ws"]),
    ("Sirach", "OT", ["Sir", "Ecclus"]),
    ("Isaiah", "OT", ["Isa", "Is"]),
    ("Jeremiah", "OT", ["Jer", "Jr"]),
    ("Lamentations", "OT", ["Lam", "Lm"]),
    ("Baruch", "OT", ["Bar"]),
    ("Ezekiel", "OT", ["Ezek", "Ez"]),
    ("Daniel", "OT", ["Dan", "Dn"]),
    ("Hosea", "OT", ["Hos", "Ho"]),
    ("Joel", "OT", ["Joel", "Jl"]),
    ("Amos", "OT", ["Amos", "Am"]),
    ("Obadiah", "OT", ["Obad", "Ob"]),
    ("Jonah", "OT", ["Jonah", "Jon"]),
    ("Micah", "OT", ["Mic", "Mi"]),
    ("Nahum", "OT", ["Nah", "Na"]),
    ("Habakkuk", "OT", ["Hab", "Hb"]),
    ("Zephaniah", "OT", ["Zeph", "Zep"]),
    ("Haggai", "OT", ["Hag", "Hg"]),
    ("Zechariah", "OT", ["Zech", "Zec"]),
    ("Malachi", "OT", ["Mal", "Ml"]),
    # --- New Testament ---
    ("Matthew", "NT", ["Matt", "Mt"]),
    ("Mark", "NT", ["Mark", "Mk", "Mc"]),
    ("Luke", "NT", ["Luke", "Lk", "Lc"]),
    ("John", "NT", ["John", "Jn"]),
    ("Acts", "NT", ["Acts", "Ac"]),
    ("Romans", "NT", ["Rom", "Rm"]),
    ("1 Corinthians", "NT", ["1 Cor", "1Cor"]),
    ("2 Corinthians", "NT", ["2 Cor", "2Cor"]),
    ("Galatians", "NT", ["Gal", "Ga"]),
    ("Ephesians", "NT", ["Eph", "Ephes"]),
    ("Philippians", "NT", ["Phil", "Php"]),
    ("Colossians", "NT", ["Col", "Cl"]),
    ("1 Thessalonians", "NT", ["1 Thess", "1 Thes", "1 Th"]),
    ("2 Thessalonians", "NT", ["2 Thess", "2 Thes", "2 Th"]),
    ("1 Timothy", "NT", ["1 Tim", "1 Tm"]),
    ("2 Timothy", "NT", ["2 Tim", "2 Tm"]),
    ("Titus", "NT", ["Titus", "Ti", "Tit"]),
    ("Philemon", "NT", ["Philem", "Phlm", "Phm"]),
    ("Hebrews", "NT", ["Heb", "Hebr"]),
    ("James", "NT", ["Jas", "Jm"]),
    ("1 Peter", "NT", ["1 Pet", "1 Pt", "1 Pe"]),
    ("2 Peter", "NT", ["2 Pet", "2 Pt", "2 Pe"]),
    ("1 John", "NT", ["1 John", "1 Jn"]),
    ("2 John", "NT", ["2 John", "2 Jn"]),
    ("3 John", "NT", ["3 John", "3 Jn"]),
    ("Jude", "NT", ["Jude", "Jud"]),
    ("Revelation", "NT", ["Rev", "Rv", "Apoc"]),
]

# exact-case abbreviation -> (canonical, testament, order). Matching is
# case-sensitive on purpose: scripture abbreviations are always capitalized,
# so "Is"/"Am"/"Job" won't collide with the English words "is"/"am"/"job".
_ABBREV: dict[str, tuple[str, str, int]] = {}
for _order, (_name, _testament, _abbrevs) in enumerate(_BOOKS):
    for _abbr in [_name, *_abbrevs]:
        _ABBREV[_abbr] = (_name, _testament, _order)

# Longest abbreviations first so e.g. "1 Cor" wins over a hypothetical "1".
_ALT = "|".join(
    re.escape(a) for a in sorted(_ABBREV, key=len, reverse=True)
)
# A book token followed by a chapter:verse locator. The locator is a run of
# digits, colons, commas, dashes (incl. en-dash) and spaces, e.g. "8:22-31"
# or "4:4; 1:5". We capture greedily then trim trailing punctuation.
_REF_RE = re.compile(
    rf"\b(?P<book>{_ALT})\b\.?\s*(?P<locator>\d+(?::\d+)?(?:\s*[-–,;]\s*\d+(?::\d+)?)*)",
)


@dataclass(frozen=True)
class ScriptureRef:
    book: str          # canonical name, e.g. "Proverbs"
    testament: str     # "OT" | "NT"
    order: int         # canonical book index (for sorting/coloring)
    locator: str       # normalized chapter:verse string, e.g. "8:22-31"

    @property
    def cite(self) -> str:
        return f"{self.book} {self.locator}"

    @property
    def node_id(self) -> str:
        return f"scripture:{self.book}|{self.locator}"


def _normalize_locator(raw: str) -> str:
    s = raw.replace("–", "-")                 # en-dash -> hyphen
    s = re.sub(r"\s*([:,;-])\s*", r"\1", s)         # tighten around punctuation
    return s.strip(" .,;")


def is_book(token: str | None) -> bool:
    """True if ``token`` is a scripture book name or abbreviation (case-sensitive).

    Lets the citation parser reject an italicized scripture sigil ("Ps", "Gen")
    that would otherwise be mistaken for a work title. Case-sensitive for the same
    reason ``_ABBREV`` is — so the words "is"/"am"/"job" never match.

    Also accepts a *bare suffix* of a numbered book ("Pt", "Cor", "Tim") — the
    source often italicizes only the book name and leaves the "1 " / "2 " in
    plain text ("2 <i>Pt</i> 3:13"), so ``<i>Pt</i>`` on its own must still be
    recognized as scripture rather than treated as a one-letter work title.
    """
    if not token:
        return False
    t = token.strip().rstrip(".")
    if t in _ABBREV:
        return True
    return any(f"{n} {t}" in _ABBREV for n in ("1", "2", "3"))


def parse_refs(text: str) -> list[ScriptureRef]:
    """Extract all biblical references from ``text``, in order of appearance."""
    refs: list[ScriptureRef] = []
    for m in _REF_RE.finditer(text):
        name, testament, order = _ABBREV[m.group("book").rstrip(".")]
        locator = _normalize_locator(m.group("locator"))
        if not locator:
            continue
        refs.append(ScriptureRef(name, testament, order, locator))
    return refs
