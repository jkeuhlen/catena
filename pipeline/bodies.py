"""Authoring bodies that are not popes: dicasteries, congregations, councils.

The original parser assumed every document on vatican.va was signed by a pope —
extracting the author from the ``/content/<pope-slug>/`` segment of the URL.
That breaks for curia-issued documents (``/roman_curia/congregations/cfaith/…``)
and council documents (``/archive/hist_councils/ii_vatican_council/…``), which
have either no pope segment or one that names the wrong actor.

This module is the curated extension point: a small table mapping the body's
URL-slug (and, where the same slug spans a rename, the date of issue) to the
canonical English display name. Add a row when a new authoring body surfaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Body:
    display: str
    # When a body is renamed (CDF → DDF in 2022), the same path slug spans two
    # entities. ``since`` is the YYYYMMDD threshold at which this entry applies;
    # both old/new entries share the slug and parsers pick the right one by date.
    since: str | None = None


# Keyed by the slug appearing in the URL. For ``/roman_curia/<branch>/<slug>/``
# the lookup key is ``<slug>``; for councils it is the council slug under
# ``/archive/hist_councils/``.
_BODIES: dict[str, list[Body]] = {
    # — Dicastery / Congregation for the Doctrine of the Faith —
    # The CDF was reorganised into the DDF by Praedicate Evangelium (2022-06-05).
    # Pre-rename docs sit at the same ``cfaith`` slug as post-rename ones, so we
    # disambiguate by date encoded in the filename (``rc_con_cfaith_doc_*`` vs.
    # the newer ``rc_ddf_doc_*``).
    "cfaith": [
        Body("Dicastery for the Doctrine of the Faith", since="20220605"),
        Body("Congregation for the Doctrine of the Faith"),
    ],
    # — Pontifical councils that authored cited documents —
    "justpeace": [Body("Pontifical Council for Justice and Peace")],
    "migrants":  [Body("Pontifical Council for the Pastoral Care of Migrants and Itinerant People")],
    # — Ecumenical councils (under /archive/hist_councils/) —
    "ii_vatican_council": [Body("Second Vatican Council")],
}


_RC_PATH = re.compile(r"/roman_curia/[^/]+/([^/]+)/", re.IGNORECASE)
_COUNCIL_PATH = re.compile(r"/archive/hist_councils/([^/]+)/", re.IGNORECASE)
_FILENAME_DATE = re.compile(r"_(\d{8})_")


def lookup_by_url(url: str) -> str | None:
    """Return the display name of the body authoring the document at ``url``.

    Picks the right rename-era entry by matching the YYYYMMDD encoded in the
    Vatican filename against each entry's ``since`` threshold. None means we
    don't recognise the slug; callers should fall back to the existing
    pope-slug path.
    """
    m = _RC_PATH.search(url) or _COUNCIL_PATH.search(url)
    if not m:
        return None
    entries = _BODIES.get(m.group(1).lower())
    if not entries:
        return None
    date_m = _FILENAME_DATE.search(url)
    date = date_m.group(1) if date_m else None
    for entry in entries:
        if entry.since is None or (date is not None and date >= entry.since):
            return entry.display
    return entries[-1].display
