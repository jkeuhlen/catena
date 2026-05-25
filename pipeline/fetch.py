"""Polite, cached HTTP fetching for source documents.

Every fetched URL is cached on disk under ``data/raw`` so that re-running the
pipeline never re-hits vatican.va or papalencyclicals.net. Cache keys are a hash
of the URL; a sidecar ``.meta`` records the original URL and fetch time.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import paths

USER_AGENT = (
    "catena/0.1 (research project cataloging encyclical citations; "
    "contact via https://github.com)"
)

# Be a good citizen: minimum seconds between live network requests.
MIN_REQUEST_INTERVAL = 1.0

_last_request_at = 0.0


@dataclass(frozen=True)
class FetchResult:
    url: str
    html: str
    from_cache: bool


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return paths.RAW / f"{digest}.html"


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def fetch(url: str, *, force: bool = False, timeout: float = 30.0) -> FetchResult:
    """Return the HTML for ``url``, using the on-disk cache unless ``force``."""
    paths.RAW.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(url)

    if cache_file.exists() and not force:
        return FetchResult(url=url, html=cache_file.read_text(encoding="utf-8"), from_cache=True)

    _throttle()
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    with httpx.Client(follow_redirects=True, headers=headers, timeout=timeout) as client:
        resp = client.get(url)
        resp.raise_for_status()
        # vatican.va serves UTF-8; trust httpx's decoding but fall back gracefully.
        html = resp.text

    cache_file.write_text(html, encoding="utf-8")
    meta = {"url": url, "fetched_at": time.time(), "status": resp.status_code}
    cache_file.with_suffix(".meta").write_text(json.dumps(meta), encoding="utf-8")
    return FetchResult(url=url, html=html, from_cache=False)
