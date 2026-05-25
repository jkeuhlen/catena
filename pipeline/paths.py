"""Canonical filesystem locations for pipeline inputs and artifacts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
RAW = DATA / "raw"           # cached fetched HTML (gitignored)
PARSED = DATA / "parsed"     # per-document parsed JSON (gitignored)
GRAPH = DATA / "graph"       # nodes/edges/layout JSON (committed; the build output)

SITE = ROOT / "site"
SITE_DATA = SITE / "data"    # graph JSON copied here for the static site to serve


def ensure_dirs() -> None:
    """Create all artifact directories if they do not yet exist."""
    for d in (RAW, PARSED, GRAPH, SITE_DATA):
        d.mkdir(parents=True, exist_ok=True)
