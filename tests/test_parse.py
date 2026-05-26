from pipeline import graph, parse, scripture

# A minimal stand-in for the Vatican Word-export structure: a canonical link,
# a title, an inline scripture ref, and three footnotes including an "ibid.".
FIXTURE = """
<html><head>
  <title>Encyclical Letter of His Holiness Leo XIV Test Lumen (15 May 2026)</title>
  <link rel="canonical" href="http://www.vatican.va/content/leo-xiv/en/encyclicals/documents/20260515-test-lumen.html"/>
</head><body>
  <p>The truth is clear (cf. <i>Jn</i> 1:5) to all.</p>
  <p class="MsoFootnoteText"><a name="_ftn1" href="#_ftnref1">[1]</a>&nbsp;Second Vatican Ecumenical Council, Pastoral Constitution
     <a href="https://www.vatican.va/archive/hist_councils/ii_vatican_council/documents/vat-ii_const_19651207_gaudium-et-spes_en.html"><i>Gaudium et Spes</i></a>, 22.</p>
  <p class="MsoFootnoteText"><a name="_ftn2" href="#_ftnref2">[2]</a>&nbsp;Ibid., 24.</p>
  <p class="MsoFootnoteText"><a name="_ftn3" href="#_ftnref3">[3]</a>&nbsp;Saint Augustine, <i>Confessions</i>, X, 27.</p>
</body></html>
"""

URL = "https://www.vatican.va/content/leo-xiv/en/encyclicals/documents/20260515-test-lumen.html"


def test_metadata():
    doc = parse.parse_document(FIXTURE, URL)
    assert doc.title == "Test Lumen"
    assert doc.author == "Leo XIV"
    assert doc.doc_type == "Encyclical"
    assert doc.date == "15 May 2026"
    assert doc.doc_key == "doc:20260515-test-lumen"


def test_footnotes_and_ibid():
    doc = parse.parse_document(FIXTURE, URL)
    assert doc.footnote_count == 3

    by_fn = {c.footnote: c for c in doc.citations}
    # fn1: linked council document
    assert by_fn[1].author == "Second Vatican Ecumenical Council"
    assert by_fn[1].doc_type == "Pastoral Constitution"
    assert by_fn[1].url.endswith("gaudium-et-spes_en.html")
    # fn2: "Ibid." inherits the previous work entirely
    assert by_fn[2].target_key == by_fn[1].target_key
    assert by_fn[2].author == "Second Vatican Ecumenical Council"
    # fn3: a text-only work (no online edition)
    assert by_fn[3].author == "Saint Augustine"
    assert by_fn[3].title == "Confessions"
    assert by_fn[3].url is None


def test_scripture_collected():
    doc = parse.parse_document(FIXTURE, URL)
    cites = {s["cite"] for s in doc.scripture}
    assert "John 1:5" in cites


# Resilience to real-world formatting quirks seen in Francis-era encyclicals:
# a malformed footnote marker (missing "["), a type-leading title with no named
# author, and a bare <p> footnote (no MsoFootnoteText class).
MESSY = """
<html><head>
  <title>Fratelli tutti (3 October 2020)</title>
  <meta name="description" content="ENCYCLICAL LETTER FRATELLI TUTTI OF THE HOLY FATHER FRANCIS"/>
  <link rel="canonical" href="http://www.vatican.va/content/francesco/en/encyclicals/documents/papa-francesco_20201003_enciclica-fratelli-tutti.html"/>
</head><body>
  <p><a name="_ftn1" href="#_ftnref1">[1]</a> Encyclical Letter
     <a href="https://www.vatican.va/content/francesco/en/encyclicals/documents/papa-francesco_20150524_enciclica-laudato-si.html"><i>Laudato Si'</i></a> (24 May 2015), 49.</p>
  <p><a name="_ftn2" href="#_ftnref2">2]</a>
     <a href="https://www.vatican.va/content/francesco/en/speeches/2014/documents/papa-francesco_20141125_strasburgo-parlamento-europeo.html"><i>Address to the European Parliament</i></a>, Strasbourg.</p>
</body></html>
"""
MESSY_URL = "https://www.vatican.va/content/francesco/en/encyclicals/documents/papa-francesco_20201003_enciclica-fratelli-tutti.html"


def test_type_from_description_when_title_is_terse():
    doc = parse.parse_document(MESSY, MESSY_URL)
    assert doc.title == "Fratelli tutti"
    assert doc.author == "Francis"
    assert doc.doc_type == "Encyclical"   # read from the meta description


def test_resilient_to_formatting_quirks():
    doc = parse.parse_document(MESSY, MESSY_URL)
    by_fn = {c.footnote: c for c in doc.citations}
    # type-leading title → no spurious author, type inferred, deduped onto the URL
    assert by_fn[1].author is None
    assert by_fn[1].doc_type == "Encyclical"
    assert by_fn[1].target_key == "doc:papa-francesco_20150524_enciclica-laudato-si"
    # malformed marker "2]" must not leak into the author; type from the title
    assert by_fn[2].footnote == 2
    assert by_fn[2].author is None
    assert by_fn[2].doc_type == "Address"
    # the only author node is the source's own pope — the messy citations add none
    g = graph.build_graph([doc])
    author_labels = {n["label"] for n in g["nodes"] if n["type"] == "author"}
    assert author_labels == {"Francis"}


# Older / JP2 / Benedict encyclicals use *endnotes* (_edn/_ednref anchors) rather
# than footnotes (_ftn/_ftnref) — same structure, different prefix, and the inline
# anchors carry their attributes in a different order (BeautifulSoup is order-agnostic).
ENDNOTES = """
<html><head>
  <title>Caritas in Veritate (29 June 2009)</title>
  <meta name="description" content="ENCYCLICAL LETTER CARITAS IN VERITATE OF THE SUPREME PONTIFF BENEDICT XVI"/>
  <link rel="canonical" href="http://www.vatican.va/content/benedict-xvi/en/encyclicals/documents/hf_ben-xvi_enc_20090629_caritas-in-veritate.html"/>
</head><body>
  <p>Charity in truth<a title="" href="#_edn1" name="_ednref1">[1]</a> is the way.</p>
  <p><a title="" href="#_ednref1" name="_edn1">[1]</a> Paul VI, Encyclical Letter
     <a href="https://www.vatican.va/content/paul-vi/en/encyclicals/documents/hf_p-vi_enc_26031967_populorum.html"><i>Populorum Progressio</i></a>, 22.</p>
  <p><a title="" href="#_ednref2" name="_edn2">[2]</a> Saint Augustine, <i>Confessions</i>, X, 27.</p>
</body></html>
"""
ENDNOTES_URL = "https://www.vatican.va/content/benedict-xvi/en/encyclicals/documents/hf_ben-xvi_enc_20090629_caritas-in-veritate.html"


def test_endnotes_parsed_like_footnotes():
    doc = parse.parse_document(ENDNOTES, ENDNOTES_URL)
    assert doc.footnote_count == 2
    by_fn = {c.footnote: c for c in doc.citations}
    # edn1: linked encyclical, author before the link
    assert by_fn[1].author == "Paul VI"
    assert by_fn[1].target_key == "doc:hf_p-vi_enc_26031967_populorum"
    # edn2: a text-only work (no online edition)
    assert by_fn[2].author == "Saint Augustine"
    assert by_fn[2].title == "Confessions"


# Pre-2000 encyclicals carry no note anchors at all: notes are plain <p> blocks
# after an <hr>, numbered with "(N)" / "N)." / a bare "N." marker, and the bare
# note number is often a separate element from its trailing punctuation. The
# parser splits the post-<hr> region on the ascending note numbers.
LEGACY = """
<html><head>
  <title>Rerum Novarum (May 15, 1891)</title>
  <meta name="description" content="ENCYCLICAL LETTER RERUM NOVARUM OF THE SUPREME PONTIFF LEO XIII"/>
  <link rel="canonical" href="http://www.vatican.va/content/leo-xiii/en/encyclicals/documents/hf_l-xiii_enc_15051891_rerum-novarum.html"/>
</head><body>
  <p>On the condition of labour (cf. <i>Deut</i> 5:21).</p>
  <hr/>
  <p>NOTES</p>
  <p>(1) Cf. <i>Deut</i> 5:21.</p>
  <p>(2) Saint Thomas Aquinas, <i>Summa Theologiae</i>, IIa-IIae, q. 10, art. 12.</p>
  <p>(3) <b>3</b>. Leo XIII's encyclical letter <i>Immortale Dei</i>: Acta Leonis XIII, 5.</p>
  <p>Copyright &copy; Dicastery for Communication</p>
</body></html>
"""
LEGACY_URL = "https://www.vatican.va/content/leo-xiii/en/encyclicals/documents/hf_l-xiii_enc_15051891_rerum-novarum.html"


def test_legacy_plaintext_notes():
    doc = parse.parse_document(LEGACY, LEGACY_URL)
    assert doc.title == "Rerum Novarum"
    assert doc.doc_type == "Encyclical"
    assert doc.footnote_count == 3            # split on the ascending markers
    by_fn = {c.footnote: c for c in doc.citations}
    # note 1 is a bare scripture reference — must not become a spurious "Deut" work
    assert 1 not in by_fn
    assert "Deuteronomy 5:21" in {s["cite"] for s in doc.scripture}
    # note 2: a curated work, attributed via works.py despite no online edition
    assert by_fn[2].author == "Saint Thomas Aquinas"
    assert by_fn[2].title == "Summa Theologiae"
    # note 3: possessive "Leo XIII's encyclical letter <Title>" → pope is the author,
    # and a clean lead (no orphaned "3." marker leaking into the author)
    assert by_fn[3].author == "Leo XIII"
    assert by_fn[3].title == "Immortale Dei"
    assert by_fn[3].doc_type == "Encyclical"


# Italics inside footnotes regularly carry things that *look* like work titles
# but aren't: a stray punctuation italic, a bare scripture-book suffix when the
# "1 "/"2 " is left outside the <i>, and the Latin work-form abbreviations
# "Ep."/"Hom." used to identify patristic letters by number rather than name.
JUNK_TITLES = """
<html><head>
  <title>Test (1 January 2026)</title>
  <link rel="canonical" href="http://www.vatican.va/test.html"/>
</head><body>
  <p class="MsoFootnoteText"><a name="_ftn1" href="#_ftnref1">[1]</a> Cf. Benedict XVI<i>,</i> Encyclical Letter Deus Caritas Est, 18.</p>
  <p class="MsoFootnoteText"><a name="_ftn2" href="#_ftnref2">[2]</a> Cf. 2 <i>Pt</i> 3:13.</p>
  <p class="MsoFootnoteText"><a name="_ftn3" href="#_ftnref3">[3]</a> Saint Augustine, <i>Ep</i>. 204, 5: CSEL 57, 320.</p>
</body></html>
"""

def test_no_spurious_titles_from_stray_italics():
    doc = parse.parse_document(JUNK_TITLES, "https://www.vatican.va/test.html")
    titles = {c.title for c in doc.citations}
    # the italicized comma is not a work
    assert "," not in titles
    # bare "<i>Pt</i>" is the scripture sigil for 1 / 2 Peter, not a work title
    assert "Pt" not in titles
    # "<i>Ep</i>." is the Latin abbreviation for Epistula, not a title
    assert "Ep" not in titles
    # is_book recognizes the bare suffix of a numbered book directly
    assert scripture.is_book("Pt")
    assert scripture.is_book("Cor")
    assert not scripture.is_book("Foo")


# Legacy notes leak scholarly-source locators (AAS, PG, CSEL…) and multi-citation
# semicolon tails into the author field; titles arrive with stray punctuation and
# lost CamelCase spaces from the source HTML.
APPARATUS = """
<html><head>
  <title>Test (1 January 2026)</title>
  <link rel="canonical" href="http://www.vatican.va/test.html"/>
</head><body>
  <p class="MsoFootnoteText"><a name="_ftn1" href="#_ftnref1">[1]</a> Pius XI's encyclical <i>Mit brennender Sorge</i>, AAS 29 (1937) 159, and his others.</p>
  <p class="MsoFootnoteText"><a name="_ftn2" href="#_ftnref2">[2]</a> Saint Augustine, <i>De Trinitate</i>, X, 27: PL 42, 994; cf. Saint Thomas Aquinas, <i>Summa Theologiae</i>.</p>
  <p class="MsoFootnoteText"><a name="_ftn3" href="#_ftnref3">[3]</a> Pius XII, Address, <i>Iura et Bona,</i> 5.</p>
  <p class="MsoFootnoteText"><a name="_ftn4" href="#_ftnref4">[4]</a> Cf. <i>QuadragesimoAnno</i> 14.</p>
</body></html>
"""

def test_author_apparatus_and_title_cleanup():
    doc = parse.parse_document(APPARATUS, "https://www.vatican.va/test.html")
    by_fn = {c.footnote: c for c in doc.citations}
    # fn1: AAS apparatus stripped; possessive "Pius XI's" → "Pius XI"
    assert by_fn[1].author == "Pius XI"
    # fn2: the semicolon tail is dropped — fn2 attributes only the first work
    assert by_fn[2].author == "Saint Augustine"
    assert by_fn[2].title == "De Trinitate"
    # fn3: trailing comma stripped from the italicized title
    assert by_fn[3].title == "Iura et Bona"
    # fn4: a lost CamelCase space is restored, and the title-index then dedupes
    # it onto the existing "Quadragesimo Anno" seed
    assert by_fn[4].title == "Quadragesimo Anno"


def test_curated_work_canonicalization():
    # the Summa is cited three ways — by Aquinas, by part number, and buried in
    # prose — yet must collapse to one node attributed to Aquinas.
    html = """
    <html><head><title>X (1 January 2020)</title>
      <link rel="canonical" href="http://www.vatican.va/content/francesco/en/encyclicals/documents/x.html"/>
    </head><body>
      <p><a name="_ftn1" href="#_ftnref1">[1]</a> Saint Thomas Aquinas, <i>Summa Theologiae</i>, I-II, q. 1.</p>
      <p><a name="_ftn2" href="#_ftnref2">[2]</a> <i>Summa Theologiae</i> II-II, q. 23.</p>
      <p><a name="_ftn3" href="#_ftnref3">[3]</a> Catholic moral doctrine; cf. <i>Summa Theologiae</i>, I-II, q. 8.</p>
    </body></html>
    """
    doc = parse.parse_document(html, "https://www.vatican.va/content/francesco/en/encyclicals/documents/x.html")
    keys = {c.target_key for c in doc.citations}
    assert keys == {"doc:work:summa-theologiae"}
    assert {c.author for c in doc.citations} == {"Saint Thomas Aquinas"}

    g = graph.build_graph([doc])
    summa = [n for n in g["nodes"] if n["id"] == "doc:work:summa-theologiae"]
    assert len(summa) == 1 and summa[0]["type"] == "document"
    author_labels = {n["label"] for n in g["nodes"] if n["type"] == "author"}
    assert author_labels == {"Francis", "Saint Thomas Aquinas"}


def test_apparatus_does_not_leak_into_authors():
    # "cf." (incl. no-space "Cf.Name"), a leading quote, and "id." must never be
    # parsed as authors.
    html = """
    <html><head><title>X (1 January 2020)</title>
      <link rel="canonical" href="http://www.vatican.va/content/francesco/en/encyclicals/documents/x.html"/>
    </head><body>
      <p><a name="_ftn1" href="#_ftnref1">[1]</a> Cf.Pontifical Council for Justice and Peace,
         <a href="https://www.vatican.va/roman_curia/pontifical_councils/justpeace/documents/rc_pc_justpeace_doc_20060526_compendio-dott-soc_en.html"><i>Compendium</i></a>, 1.</p>
      <p><a name="_ftn2" href="#_ftnref2">[2]</a> &#8220;Man is a political animal&#8221;, Aristotle, <i>Politics</i>, 1253a.</p>
      <p><a name="_ftn3" href="#_ftnref3">[3]</a> Cf.</p>
    </body></html>
    """
    doc = parse.parse_document(html, "https://www.vatican.va/content/francesco/en/encyclicals/documents/x.html")
    by_fn = {c.footnote: c for c in doc.citations}
    assert by_fn[1].author == "Pontifical Council for Justice and Peace"
    assert by_fn[2].author == "Aristotle"        # leading quote stripped
    assert by_fn[2].title == "Politics"
    # no author is a bare apparatus token
    assert not [c for c in doc.citations if (c.author or "").lower() in {"cf", "id", "idem", "ibid"}]


def test_graph_build_and_dedup():
    doc = parse.parse_document(FIXTURE, URL)
    g = graph.build_graph([doc])
    ids = {n["id"] for n in g["nodes"]}
    # the source, the council doc, Augustine's text, two authors, one scripture
    assert "doc:20260515-test-lumen" in ids
    assert "doc:vat-ii_const_19651207_gaudium-et-spes" in ids
    assert "author:second vatican ecumenical council" in ids
    # ibid. collapsed onto the same target → exactly one cites edge to it
    cites_edges = [
        e for e in g["edges"]
        if e["type"] == "cites" and e["target"] == "doc:vat-ii_const_19651207_gaudium-et-spes"
    ]
    assert len(cites_edges) == 1 and cites_edges[0]["weight"] == 2
    # every node carries layout-free graph data; coords added by layout step only
    assert g["meta"]["scripture"] == 1
