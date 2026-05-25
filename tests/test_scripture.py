from pipeline import scripture


def test_basic_reference():
    (ref,) = scripture.parse_refs("invoking the Spirit (cf. Prov 8:22-31).")
    assert ref.book == "Proverbs"
    assert ref.testament == "OT"
    assert ref.locator == "8:22-31"
    assert ref.cite == "Proverbs 8:22-31"
    assert ref.node_id == "scripture:Proverbs|8:22-31"


def test_numbered_book():
    (ref,) = scripture.parse_refs("as Paul writes (1 Cor 13:4).")
    assert ref.book == "1 Corinthians"
    assert ref.locator == "13:4"


def test_new_testament_classification():
    refs = scripture.parse_refs("Mt 25:14-30 and Jn 10:10")
    assert [r.book for r in refs] == ["Matthew", "John"]
    assert all(r.testament == "NT" for r in refs)


def test_case_sensitivity_avoids_false_positives():
    # lower-case "is"/"am"/"job" must not be read as Isaiah/Amos/Job
    assert scripture.parse_refs("this is 1 of the great am 2 job 3 examples") == []


def test_chapter_only_and_range():
    (ref,) = scripture.parse_refs("see Neh 2-6 for the rebuilding")
    assert ref.book == "Nehemiah"
    assert ref.locator == "2-6"
