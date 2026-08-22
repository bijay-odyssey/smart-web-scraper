"""Fetch a URL and extract its main readable text content.

Plain static fetching can't see anything that only appears after
JavaScript runs -- and a lot of the pages worth citing (docs sites,
pricing pages, product consoles) are React/Vue/Next.js apps that render
almost nothing server-side (confirmed in testing: console.groq.com
returns ~480 chars of boilerplate via a static GET, vs. ~4300 chars of
real content once rendered). When static extraction comes back too thin
to be useful, this falls back to Jina AI's free Reader API
(r.jina.ai), which renders the page server-side and returns clean text
-- no API key needed for this volume of use.
"""

from __future__ import annotations

import requests
import trafilatura
from bs4 import BeautifulSoup

from search_agent import cache
from search_agent.search import HEADERS

MAX_DOWNLOAD_BYTES = 3_000_000

# Below this many characters, a static fetch is probably boilerplate from
# a JS-rendered page rather than real article/doc content.
THIN_CONTENT_THRESHOLD = 500

JINA_READER_URL = "https://r.jina.ai/"


def _static_fetch(url: str, timeout: int) -> str | None:
    try:
        resp = requests.get(
            url, headers=HEADERS, timeout=timeout, stream=True
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type:
            return None

        raw = resp.raw.read(MAX_DOWNLOAD_BYTES, decode_content=True)
        html = raw.decode(resp.encoding or "utf-8", errors="ignore")
    except (requests.RequestException, UnicodeDecodeError):
        return None

    text = trafilatura.extract(html, include_comments=False, include_tables=False)
    if text and text.strip():
        return text.strip()

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    fallback = soup.get_text(separator="\n", strip=True)
    return fallback if fallback else None


def _jina_reader_fetch(url: str, timeout: int) -> str | None:
    try:
        resp = requests.get(JINA_READER_URL + url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    text = resp.text.strip()
    return text if text else None


def fetch_page_text(url: str, timeout: int = 10) -> str | None:
    """Download `url` and return extracted body text, or None on failure.

    Tries a fast static fetch first; if that's missing or suspiciously
    thin, falls back to a server-rendered reader that can see JS-only
    content. Cached to disk per-URL so re-fetching the same page (common
    when a query recurs, or an agent searches similar things) is instant.
    """
    cached = cache.get_fetch(url)
    if cached is not None:
        return cached

    text = _static_fetch(url, timeout)

    if not text or len(text) < THIN_CONTENT_THRESHOLD:
        rendered = _jina_reader_fetch(url, timeout=20)
        if rendered and (not text or len(rendered) > len(text)):
            text = rendered

    if text:
        cache.set_fetch(url, text)
    return text
