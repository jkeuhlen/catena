"""Curated temporal spans for non-pope author nodes (councils & persons).

The Timeline view paints a right-edge "ribbon" gutter of historical context
alongside the encyclical swarm: each pope's *reign* (sourced from
``pontiffs.py``), each ecumenical *council* as a dated event, and the
*lifetimes* of the Fathers, Doctors, and saints the corpus draws upon.

This module is the curated source for the latter two. Popes are NOT listed here
— their span is derived from their ``Pontiff`` record in ``graph.finalize``.

Keys are the normalized author key the graph already produces (the part after
``author:`` in the node id — lowercase, honorifics stripped). A figure cited
under several keys (Vatican II appears as four distinct author nodes) gets one
``Span`` registered under every variant via ``_alias``.

Two display shapes:
  - ``kind="council"`` — an event; rendered as a short dated bar (or a point
    marker when ``start == end``).
  - ``kind="life"``    — a lifetime; rendered as a labelled vertical band.

Dates are AD years; ``~`` (circa) births for ancient figures use the
conventional scholarly year. When unsure of a patristic birth/death to within a
few years, that's fine — the band is contextual, not load-bearing. Don't guess
wildly; omit a figure rather than invent a date.

Add a line when a new dated figure surfaces in the corpus; an unmatched key is
simply skipped, so listing a few not-yet-present saints is harmless.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    kind: str          # "council" | "life"
    start: int         # AD year (birth, or council opening)
    end: int | None    # AD year (death, or council close); None = ongoing/point
    label: str         # display label for the ribbon


# Canonical entries. Variant author keys are wired up in ``_ALIASES`` below.
_SPANS: dict[str, Span] = {
    # — Ecumenical councils (dated events) —
    "council of trent":                  Span("council", 1545, 1563, "Council of Trent"),
    "first vatican ecumenical council":  Span("council", 1869, 1870, "First Vatican Council"),
    "second vatican ecumenical council": Span("council", 1962, 1965, "Second Vatican Council"),

    # — Fathers, Doctors & saints (lifetimes) —
    # Ante-Nicene / patristic
    "justin martyr":        Span("life", 100, 165, "Saint Justin Martyr"),
    "irenaeus of lyons":    Span("life", 130, 202, "Saint Irenaeus of Lyons"),
    "irenaeus":             Span("life", 130, 202, "Saint Irenaeus of Lyons"),
    "clement of alexandria":Span("life", 150, 215, "Saint Clement of Alexandria"),
    "tertullian":           Span("life", 155, 220, "Tertullian"),
    "origen":               Span("life", 185, 253, "Origen"),
    "cyprian":              Span("life", 210, 258, "Saint Cyprian"),
    "athanasius":           Span("life", 296, 373, "Saint Athanasius"),
    "hilary of poitiers":   Span("life", 310, 367, "Saint Hilary of Poitiers"),
    "basil the great":      Span("life", 330, 379, "Saint Basil the Great"),
    "gregory of nazianzus": Span("life", 329, 390, "Saint Gregory of Nazianzus"),
    "gregory of nyssa":     Span("life", 335, 395, "Saint Gregory of Nyssa"),
    "ambrose":              Span("life", 339, 397, "Saint Ambrose"),
    "john chrysostom":      Span("life", 347, 407, "Saint John Chrysostom"),
    "jerome":               Span("life", 342, 420, "Saint Jerome"),
    "augustine":            Span("life", 354, 430, "Saint Augustine"),
    "cyril of alexandria":  Span("life", 376, 444, "Saint Cyril of Alexandria"),
    # Medieval
    "maximus the confessor":Span("life", 580, 662, "Saint Maximus the Confessor"),
    "john damascene":       Span("life", 675, 749, "Saint John Damascene"),
    "anselm":               Span("life", 1033, 1109, "Saint Anselm"),
    "bernard of clairvaux": Span("life", 1090, 1153, "Saint Bernard of Clairvaux"),
    "anthony of padua":     Span("life", 1195, 1231, "Saint Anthony of Padua"),
    "bonaventure":          Span("life", 1221, 1274, "Saint Bonaventure"),
    "thomas aquinas":       Span("life", 1225, 1274, "Saint Thomas Aquinas"),
    "catherine of siena":   Span("life", 1347, 1380, "Saint Catherine of Siena"),
    # Early-modern / modern
    "teresa of avila":      Span("life", 1515, 1582, "Saint Teresa of Ávila"),
    "john of the cross":    Span("life", 1542, 1591, "Saint John of the Cross"),
    "robert bellarmine":    Span("life", 1542, 1621, "Saint Robert Bellarmine"),
    "francis de sales":     Span("life", 1567, 1622, "Saint Francis de Sales"),
    "margaret mary alacoque": Span("life", 1647, 1690, "Saint Margaret Mary Alacoque"),
    "alphonsus liguori":    Span("life", 1696, 1787, "Saint Alphonsus Liguori"),
    "john henry newman":    Span("life", 1801, 1890, "Saint John Henry Newman"),
    "charles de foucauld":  Span("life", 1858, 1916, "Saint Charles de Foucauld"),
    "therese of lisieux":   Span("life", 1873, 1897, "Saint Thérèse of Lisieux"),
    "romano guardini":      Span("life", 1885, 1968, "Romano Guardini"),
    "edith stein":          Span("life", 1891, 1942, "Saint Teresa Benedicta (Edith Stein)"),
}

# Variant author keys → canonical key in ``_SPANS``. The graph produces several
# author nodes for the same historical figure (Vatican II especially); each
# variant should light up the same ribbon.
_ALIASES: dict[str, str] = {
    "second vatican council":   "second vatican ecumenical council",
    "vatican council ii":       "second vatican ecumenical council",
    "vatican ii":               "second vatican ecumenical council",
    "first vatican council":    "first vatican ecumenical council",
    "vatican council i":        "first vatican ecumenical council",
    "trent":                    "council of trent",
}


def lookup(author_key: str | None) -> Span | None:
    """Return the curated ``Span`` for an author key, or ``None``."""
    if not author_key:
        return None
    key = author_key.strip().lower()
    key = _ALIASES.get(key, key)
    return _SPANS.get(key)
