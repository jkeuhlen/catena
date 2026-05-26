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
    doc_type: str    # the kind of work — overwrites any stale type a citing
                     # footnote left on the citation (see ``parse._canonicalize``).
                     # Required: omitting it would re-open the doc_type-carryover bug.


# (substring matched against the normalized title, canonical title, author, doc_type)
_WORKS_RAW: list[tuple[str, str, str, str]] = [
    # Thomas Aquinas — scholastic
    ("summa theolog",             "Summa Theologiae",            "Saint Thomas Aquinas", "Scholastic treatise"),
    ("summa contra gentiles",     "Summa contra Gentiles",       "Saint Thomas Aquinas", "Scholastic treatise"),
    ("scriptum super sententiis", "Scriptum super Sententiis",   "Saint Thomas Aquinas", "Commentary"),
    ("super boetium de trinitate", "Super Boetium de Trinitate", "Saint Thomas Aquinas", "Commentary"),
    ("contra impugnantes",        "Contra impugnantes Dei cultum et religionem", "Saint Thomas Aquinas", "Treatise"),
    ("de regimine principum",     "De Regimine Principum",       "Saint Thomas Aquinas", "Treatise"),
    ("summa th",                  "Summa Theologiae",            "Saint Thomas Aquinas", "Scholastic treatise"),  # "Summa Th." abbrev
    # Augustine
    ("de civitate dei",           "De Civitate Dei",             "Saint Augustine", "Theological treatise"),
    ("city of god",               "De Civitate Dei",             "Saint Augustine", "Theological treatise"),
    ("confession",                "Confessions",                 "Saint Augustine", "Spiritual autobiography"),
    ("enarrationes in psalmos",   "Enarrationes in Psalmos",     "Saint Augustine", "Scripture commentary"),
    ("de doctrina christiana",    "De Doctrina Christiana",      "Saint Augustine", "Theological treatise"),
    ("in iohannis evangelium tractatus", "In Iohannis Evangelium Tractatus", "Saint Augustine", "Scripture commentary"),
    ("tract in ioannem",          "In Iohannis Evangelium Tractatus", "Saint Augustine", "Scripture commentary"),
    ("tract in joannem",          "In Iohannis Evangelium Tractatus", "Saint Augustine", "Scripture commentary"),
    # Other Fathers & Doctors
    ("adversus haereses",         "Adversus Haereses",           "Saint Irenaeus of Lyons", "Theological treatise"),
    ("homiliae in matthaeum",     "Homilies on the Gospel of Matthew", "Saint John Chrysostom", "Homilies"),
    ("in io homil",               "Homilies on the Gospel of John", "Saint John Chrysostom", "Homilies"),
    ("de lazaro",                 "De Lazaro",                   "Saint John Chrysostom", "Homilies"),
    ("regula pastoralis",         "Regula Pastoralis",           "Saint Gregory the Great", "Pastoral treatise"),
    ("moralia in job",            "Moralia in Job",              "Saint Gregory the Great", "Scripture commentary"),
    ("divinae institutiones",     "Divinae Institutiones",       "Lactantius", "Apologetic treatise"),
    ("in joh",                    "Commentary on the Gospel of John", "Origen", "Scripture commentary"),
    ("in num homil",              "Homilies on Numbers",         "Origen", "Homilies"),
    ("hexaemeron",                "Hexaemeron",                  "Saint Basil the Great", "Homilies"),
    ("expositio evangelii secundum lucam", "Expositio Evangelii secundum Lucam", "Saint Ambrose", "Scripture commentary"),
    ("exameron",                  "Exameron",                    "Saint Ambrose", "Homilies"),  # CSEL 32, distinct from Basil's Greek Hexaemeron
    ("in matthaeum",              "Homilies on the Gospel of Matthew", "Saint John Chrysostom", "Homilies"),  # PG 57/58
    ("de hominis opificio",       "De Hominis Opificio",         "Saint Gregory of Nyssa", "Theological treatise"),  # PG 44
    ("apologeticum",              "Apologeticum",                "Tertullian", "Apologetic treatise"),  # PL 1
    # Franciscan sources
    ("admonitions",               "Admonitions",                 "Saint Francis of Assisi", "Spiritual writing"),
    ("regula non bullata",        "Earlier Rule (Regula non bullata)", "Saint Francis of Assisi", "Religious rule"),
    ("earlier rule",              "Earlier Rule (Regula non bullata)", "Saint Francis of Assisi", "Religious rule"),
    ("major legend of saint francis", "The Major Legend of Saint Francis", "Saint Bonaventure", "Hagiography"),
    ("in ii sent",                "Commentary on the Sentences", "Saint Bonaventure", "Commentary"),
    # Conciliar / magisterial title aliases — collapse text-only variants onto the
    # canonical Latin title (graph._title_index then merges them onto any
    # URL-backed node sharing that title; the seed's own doc_type wins there).
    ("on the condition of",       "Rerum Novarum",               "Leo XIII", "Encyclical"),
    ("pastoral constitution on the church in", "Gaudium et Spes", "Second Vatican Ecumenical Council", "Pastoral Constitution"),
    ("dei verbum",                "Dei Verbum",                  "Second Vatican Ecumenical Council", "Dogmatic Constitution"),
    ("familiaris consortio",      "Familiaris Consortio",        "John Paul II", "Apostolic Exhortation"),
    ("donum vitae",               "Donum Vitae",                 "Congregation for the Doctrine of the Faith", "Instruction"),
    ("immortale dei",             "Immortale Dei",               "Leo XIII", "Encyclical"),
    ("das ende der neuzeit",      "Das Ende der Neuzeit",        "Romano Guardini", "Philosophical work"),
    # Classical & literary
    ("aeneid",                    "Aeneid",                      "Virgil", "Epic poem"),
    ("divine comedy",             "The Divine Comedy",           "Dante Alighieri", "Epic poem"),
    ("the demons",                "The Demons",                  "Fyodor Dostoevsky", "Novel"),
    ("jenseits von gut und b",    "Jenseits von Gut und Böse",   "Friedrich Nietzsche", "Philosophical work"),
]


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_WORKS: list[tuple[str, Work]] = [
    (pat, Work(title, author, f"doc:work:{_slug(title)}", doc_type))
    for pat, title, author, doc_type in _WORKS_RAW
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
