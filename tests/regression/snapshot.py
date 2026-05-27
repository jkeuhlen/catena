"""Generate and load regression snapshots for the seed corpus.

A snapshot captures the *parsed shape* of each SEED so any future parser change
must be a deliberate update — not a silent drift. The snapshot is intentionally
detailed (every citation tuple, every distinct author, scripture book tallies)
because the parser's failure mode has historically been *quiet* mis-attribution,
not loud exceptions.

Run ``python -m tests.regression.snapshot`` to (re)generate the golden file.
The pytest in ``test_seed_regression.py`` reads the same file and diffs.

Inputs come exclusively from ``data/raw/`` — the offline cache. No network.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from pipeline import parse, paths
from pipeline.cli import SEEDS

SNAPSHOT_PATH = Path(__file__).parent / "seed_snapshot.json"


def _cache_html(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return (paths.RAW / f"{digest}.html").read_text(encoding="utf-8")


def _snapshot_one(url: str) -> dict:
    doc = parse.parse_document(_cache_html(url), url)
    # Citations as ordered tuples — order matters for ibid./idem chains, and the
    # full list catches "lost" or "extra" citations a count-only check would miss.
    citations = [
        {
            "footnote": c.footnote,
            "target_key": c.target_key,
            "title": c.title,
            "url": c.url,
            "author_key": c.author_key,
            "doc_type": c.doc_type,
        }
        for c in doc.citations
    ]
    # Author histogram: count of citations attributed to each key. Catches
    # mass-mis-attribution (apparatus showing up as an author repeatedly).
    author_hist = Counter(c["author_key"] or "<none>" for c in citations)
    # Lists, not tuples — survives the JSON round-trip cleanly.
    scripture_hist = sorted(
        [s["book"], s["cite"], s["count"]] for s in doc.scripture
    )
    return {
        "source_url": url,
        "doc_key": doc.doc_key,
        "title": doc.title,
        "author": doc.author,
        "author_key": doc.author_key,
        "doc_type": doc.doc_type,
        "date": doc.date,
        "footnote_count": doc.footnote_count,
        "citation_count": len(doc.citations),
        "scripture_count": len(doc.scripture),
        "author_histogram": dict(sorted(author_hist.items())),
        "scripture_histogram": scripture_hist,
        "citations": citations,
    }


def build_snapshot() -> dict:
    return {"seeds": [_snapshot_one(u) for u in SEEDS]}


def load_snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    snap = build_snapshot()
    SNAPSHOT_PATH.write_text(
        json.dumps(snap, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    n = len(snap["seeds"])
    cites = sum(s["citation_count"] for s in snap["seeds"])
    print(f"Wrote {SNAPSHOT_PATH} — {n} seeds, {cites} citations.")
