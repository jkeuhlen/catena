"""Tests for non-pope authoring-body resolution from URL slugs."""

from __future__ import annotations

from pipeline import bodies


def test_ddf_post_rename() -> None:
    # 2024 document → Dicastery (renamed from Congregation in 2022).
    url = ("https://www.vatican.va/roman_curia/congregations/cfaith/"
           "documents/rc_ddf_doc_20240402_dignitas-infinita_en.html")
    assert bodies.lookup_by_url(url) == "Dicastery for the Doctrine of the Faith"


def test_cdf_pre_rename() -> None:
    # 2000 document → Congregation (pre-2022 entity, same path slug).
    url = ("https://www.vatican.va/roman_curia/congregations/cfaith/"
           "documents/rc_con_cfaith_doc_20000806_dominus-iesus_en.html")
    assert bodies.lookup_by_url(url) == "Congregation for the Doctrine of the Faith"


def test_pontifical_council() -> None:
    url = ("https://www.vatican.va/roman_curia/pontifical_councils/justpeace/"
           "documents/rc_pc_justpeace_doc_20060526_compendio-dott-soc_en.html")
    assert bodies.lookup_by_url(url) == "Pontifical Council for Justice and Peace"


def test_vatican_ii() -> None:
    url = ("https://www.vatican.va/archive/hist_councils/ii_vatican_council/"
           "documents/vat-ii_const_19651207_gaudium-et-spes_en.html")
    assert bodies.lookup_by_url(url) == "Second Vatican Council"


def test_unknown_slug() -> None:
    # An unmapped curia slug returns None so callers fall back to pope-slug parsing.
    url = "https://www.vatican.va/roman_curia/congregations/unknown_xyz/documents/foo.html"
    assert bodies.lookup_by_url(url) is None


def test_non_curia_url_ignored() -> None:
    # A pope-encyclical URL should not match the body table.
    url = ("https://www.vatican.va/content/francesco/en/encyclicals/documents/"
           "papa-francesco_20150524_enciclica-laudato-si.html")
    assert bodies.lookup_by_url(url) is None
