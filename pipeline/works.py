"""Curated canonicalization of famous works cited inconsistently across encyclicals.

Classical and patristic works — the *Summa*, the *Confessions*, the *City of God* —
are cited by many titles and in several languages, frequently without naming their
author. The generic parser therefore scatters them across several mis-attributed
nodes (e.g. "Summa Theologiae II-II" and "Catholic moral doctrine" both standing in
as the "author" of the Summa). This table maps such works onto one canonical
identity — a title, an author, and a stable node key — so every citation collapses
to a single, correctly-attributed node.

Matching is a substring test against a normalized title. Order entries
most-specific first, and extend ``_WORKS_RAW`` as new works surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Work:
    title: str       # canonical display title
    author: str      # canonical author (display form)
    key: str         # stable node id, independent of how the work was cited


# (substring matched against the normalized title, canonical title, author)
_WORKS_RAW: list[tuple[str, str, str]] = [
    # Thomas Aquinas
    ("summa theolog",             "Summa Theologiae",            "Saint Thomas Aquinas"),
    ("summa contra gentiles",     "Summa contra Gentiles",       "Saint Thomas Aquinas"),
    ("scriptum super sententiis", "Scriptum super Sententiis",   "Saint Thomas Aquinas"),
    ("super boetium de trinitate", "Super Boetium de Trinitate", "Saint Thomas Aquinas"),
    # Augustine
    ("de civitate dei",           "De Civitate Dei",             "Saint Augustine"),
    ("city of god",               "De Civitate Dei",             "Saint Augustine"),
    ("confession",                "Confessions",                 "Saint Augustine"),
    ("enarrationes in psalmos",   "Enarrationes in Psalmos",     "Saint Augustine"),
    ("de doctrina christiana",    "De Doctrina Christiana",      "Saint Augustine"),
    # Other Fathers & Doctors
    ("adversus haereses",         "Adversus Haereses",           "Saint Irenaeus of Lyons"),
    ("homiliae in matthaeum",     "Homilies on the Gospel of Matthew", "Saint John Chrysostom"),
    ("de lazaro",                 "De Lazaro",                   "Saint John Chrysostom"),
    ("regula pastoralis",         "Regula Pastoralis",           "Saint Gregory the Great"),
    ("divinae institutiones",     "Divinae Institutiones",       "Lactantius"),
    # Franciscan sources
    ("admonitions",               "Admonitions",                 "Saint Francis of Assisi"),
    ("regula non bullata",        "Earlier Rule (Regula non bullata)", "Saint Francis of Assisi"),
    ("earlier rule",              "Earlier Rule (Regula non bullata)", "Saint Francis of Assisi"),
    # Classical
    ("aeneid",                    "Aeneid",                      "Virgil"),
]


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_WORKS: list[tuple[str, Work]] = [
    (pat, Work(title, author, f"doc:work:{_slug(title)}"))
    for pat, title, author in _WORKS_RAW
]


def lookup(title: str | None) -> Work | None:
    """Return the canonical Work whose pattern matches ``title``, or None."""
    n = _norm(title or "")
    if not n:
        return None
    for pat, work in _WORKS:
        if pat in n:
            return work
    return None
