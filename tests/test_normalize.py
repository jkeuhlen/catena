from pipeline import normalize


def test_author_honorific_collapses():
    k1, d1 = normalize.normalize_author("Saint John Paul II")
    k2, d2 = normalize.normalize_author("John Paul II")
    assert k1 == k2 == "john paul ii"
    assert d1 == "Saint John Paul II"  # display preserves the honorific


def test_pope_vs_plain():
    assert normalize.normalize_author("Pope Francis")[0] == "francis"
    assert normalize.normalize_author("Francis")[0] == "francis"


def test_detect_type_prefers_specific():
    canon, idx = normalize.detect_type("Pastoral Constitution Gaudium et Spes")
    assert canon == "Pastoral Constitution"
    assert idx == 0
    assert normalize.detect_type("Encyclical Letter Rerum Novarum")[0] == "Encyclical"


def test_doc_key_language_independent():
    en = "https://www.vatican.va/archive/.../vat-ii_const_19651207_gaudium-et-spes_en.html"
    it = "https://www.vatican.va/archive/.../vat-ii_const_19651207_gaudium-et-spes_it.html"
    assert normalize.doc_key_from_url(en) == normalize.doc_key_from_url(it)
    assert normalize.doc_key_from_url(en) == "doc:vat-ii_const_19651207_gaudium-et-spes"


def test_is_document_url():
    assert normalize.is_document_url("https://www.vatican.va/content/x/documents/y.html")
    assert not normalize.is_document_url("https://example.com/foo.html")
    assert not normalize.is_document_url("https://www.vatican.va/content/x/")


def test_recase_shouting_names():
    assert normalize.recase_name("PAUL RICOEUR") == "Paul Ricoeur"
    assert normalize.recase_name("CHARLES DE FOUCAULD") == "Charles de Foucauld"  # particle
    assert normalize.recase_name("SAINT JOHN PAUL II") == "Saint John Paul II"     # roman numeral
    assert normalize.recase_name("JAIME HOYOS-VÁSQUEZ") == "Jaime Hoyos-Vásquez"   # hyphen + accent
    # already-mixed-case names are left untouched
    assert normalize.recase_name("Saint Augustine") == "Saint Augustine"
    assert normalize.recase_name("J.R.R. Tolkien") == "J.R.R. Tolkien"


def test_normalize_author_recases_display_but_not_key():
    key, display = normalize.normalize_author("PONTIFICAL COUNCIL FOR JUSTICE AND PEACE")
    assert display == "Pontifical Council for Justice and Peace"
    assert key == "pontifical council for justice and peace"


def test_title_from_slug():
    assert normalize.title_from_slug("doc:hf_p-vi_enc_26031967_populorum") == "Populorum"
    assert normalize.title_from_slug("doc:vat-ii_const_19651207_gaudium-et-spes") == "Gaudium Et Spes"
