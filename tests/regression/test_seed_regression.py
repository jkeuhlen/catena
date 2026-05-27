"""Lock the parsed shape of every SEED against ``seed_snapshot.json``.

If you change the parser and a seed shifts: investigate first. If the shift is
intended (a real improvement), regenerate the snapshot with::

    uv run python -m tests.regression.snapshot

and commit the diff alongside the code change so the intent is reviewable.
"""

from __future__ import annotations

import pytest

from .snapshot import _snapshot_one, load_snapshot

_SNAP = load_snapshot()
_SEEDS_BY_URL = {s["source_url"]: s for s in _SNAP["seeds"]}


@pytest.mark.parametrize("url", list(_SEEDS_BY_URL), ids=lambda u: u.rsplit("/", 1)[-1])
def test_seed_matches_snapshot(url: str) -> None:
    expected = _SEEDS_BY_URL[url]
    actual = _snapshot_one(url)
    # Compare the cheap scalars first so failure messages point at the right field.
    for field in (
        "doc_key", "title", "author", "author_key", "doc_type", "date",
        "footnote_count", "citation_count", "scripture_count",
    ):
        assert actual[field] == expected[field], (
            f"{field} drifted for {url}: {actual[field]!r} != {expected[field]!r}"
        )
    assert actual["author_histogram"] == expected["author_histogram"]
    assert actual["scripture_histogram"] == expected["scripture_histogram"]
    assert actual["citations"] == expected["citations"]
