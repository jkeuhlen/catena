"""Curated table of popes appearing (or likely to appear) as author nodes.

Any author whose normalized key (lowercase, honorifics stripped — see
``normalize.normalize_author``) matches an entry here is rendered as a pontiff
in the site's detail card: the eyebrow becomes "PONTIFF", a subtitle gives the
ordinal and reign, and outbound buttons link to the Vatican profile and
Wikipedia. The legend category remains ``author`` so filters are unaffected.

This is the intended extension point — when a new pope surfaces as an author
node, add a line below. ``make validate-pontiffs`` checks every ``vatican_slug``
against ``vatican.va/content/vatican/en/holy-father.html``.

Vatican slugs are *Italianate* (``leone-xiv``, ``francesco``, ``giovanni-paolo-ii``)
even on the English path — that's how the Holy See organizes the URL space.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pontiff:
    ordinal: int               # nth Bishop of Rome (Peter = 1; Leo XIV = 267)
    display_name: str          # canonical English regnal name
    reign_start: int           # AD year of election
    reign_end: int | None      # AD year reign ended; None = ongoing
    vatican_slug: str | None   # /content/vatican/en/holy-father/<slug>.html ;
                               # None means use ``vatican_url_override`` instead
    wikipedia_slug: str        # /wiki/<slug>
    vatican_url_override: str | None = None  # rare popes whose profile sits
                               # outside /holy-father/ (e.g. Pius IX)


# Keyed by the normalized author key the graph already produces.
# Add modern popes as encyclicals are added; older popes only as they appear.
_PONTIFFS: dict[str, Pontiff] = {
    # — Modern (encyclical-era) —
    "leo xiv":      Pontiff(267, "Leo XIV",            2025, None, "leone-xiv",        "Pope_Leo_XIV"),
    "francis":      Pontiff(266, "Francis",            2013, 2025, "francesco",        "Pope_Francis"),
    "benedict xvi": Pontiff(265, "Benedict XVI",       2005, 2013, "benedetto-xvi",    "Pope_Benedict_XVI"),
    "john paul ii": Pontiff(264, "Saint John Paul II", 1978, 2005, "giovanni-paolo-ii","Pope_John_Paul_II"),
    "john paul i":  Pontiff(263, "John Paul I",        1978, 1978, "giovanni-paolo-i", "Pope_John_Paul_I"),
    "paul vi":      Pontiff(262, "Saint Paul VI",      1963, 1978, "paolo-vi",         "Pope_Paul_VI"),
    "john xxiii":   Pontiff(261, "Saint John XXIII",   1958, 1963, "giovanni-xxiii",   "Pope_John_XXIII"),
    "pius xii":     Pontiff(260, "Venerable Pius XII", 1939, 1958, "pio-xii",          "Pope_Pius_XII"),
    "pius xi":      Pontiff(259, "Pius XI",            1922, 1939, "pio-xi",           "Pope_Pius_XI"),
    "benedict xv":  Pontiff(258, "Benedict XV",        1914, 1922, "benedetto-xv",     "Pope_Benedict_XV"),
    "pius x":       Pontiff(257, "Saint Pius X",       1903, 1914, "pio-x",            "Pope_Pius_X"),
    "leo xiii":     Pontiff(256, "Leo XIII",           1878, 1903, "leone-xiii",       "Pope_Leo_XIII"),
    "pius ix":      Pontiff(255, "Blessed Pius IX",    1846, 1878, None,               "Pope_Pius_IX",
                            vatican_url_override="https://www.vatican.va/content/pius-ix/en.html"),
    # — Earlier popes that surface in the citation apparatus —
    "gregory the great": Pontiff(64, "Saint Gregory the Great", 590, 604, "gregorio-i--magno", "Pope_Gregory_I"),
    "gregory i":         Pontiff(64, "Saint Gregory the Great", 590, 604, "gregorio-i--magno", "Pope_Gregory_I"),
    "leo the great":     Pontiff(45, "Saint Leo the Great",     440, 461, "leone-i--magno",    "Pope_Leo_I"),
    "leo i":             Pontiff(45, "Saint Leo the Great",     440, 461, "leone-i--magno",    "Pope_Leo_I"),
}


def _ordinal_label(n: int) -> str:
    # 1st, 2nd, 3rd, 4th… with the standard 11/12/13 exception.
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _reign_label(start: int, end: int | None) -> str:
    return f"{start}–{end if end is not None else 'present'}"


def lookup(author_key: str | None) -> dict | None:
    """Return a JSON-serializable pontiff record, or None."""
    if not author_key:
        return None
    p = _PONTIFFS.get(author_key.lower())
    if p is None:
        return None
    if p.vatican_url_override:
        vatican_url = p.vatican_url_override
    elif p.vatican_slug:
        vatican_url = f"https://www.vatican.va/content/vatican/en/holy-father/{p.vatican_slug}.html"
    else:
        vatican_url = None
    return {
        "ordinal": p.ordinal,
        "ordinal_label": f"{_ordinal_label(p.ordinal)} Pontiff",
        "display_name": p.display_name,
        "reign_label": _reign_label(p.reign_start, p.reign_end),
        "reign_start": p.reign_start,
        "reign_end": p.reign_end,
        "vatican_url": vatican_url,
        "wikipedia_url": f"https://en.wikipedia.org/wiki/{p.wikipedia_slug}",
    }


def all_keys() -> list[str]:
    return list(_PONTIFFS)


def all_entries() -> list[tuple[str, Pontiff]]:
    return list(_PONTIFFS.items())
