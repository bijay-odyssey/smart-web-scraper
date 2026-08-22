"""Search the web via a tiered chain of backends, then rank results by
actual relevance to the query.

Backend order: Tavily (if TAVILY_API_KEY is set) -> Brave (if
BRAVE_API_KEY is set) -> DuckDuckGo scraping -> Bing scraping. Real APIs
go first because they're what actually fixes the reliability problems
found in testing; scraping is the free zero-signup fallback, not the
primary path.

Problems found and fixed here through live testing, not guesswork:

1. DuckDuckGo's HTML endpoint rate-limits under repeated use (a burst of
   requests gets a 202 challenge page instead of results) -- so `search()`
   falls through to the next backend when one is blocked, and
   throttles+retries each backend to avoid tripping the limit in the
   first place.
2. A scraping backend's own ranking isn't trustworthy: Bing's
   unauthenticated HTML page returned "Best Buy" and dictionary
   definitions for a query about free local-LLM tools, because without
   full browser/session context it fell back to naive keyword matching
   where a common word dominated. So `search()` pulls a larger raw pool
   per backend and re-ranks it against the query itself
   (search_agent.relevance) instead of trusting whichever result the
   backend put first.
3. Repeated/near-identical queries (normal for an agent that searches a
   few times per question) shouldn't re-hit these backends at all --
   results are cached to disk.
"""

from __future__ import annotations

import base64
import os
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from search_agent import cache
from search_agent.relevance import build_precise_query, filter_and_rank

load_dotenv()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# How many raw results to pull from a backend before re-ranking, regardless
# of how many the caller ultimately wants -- the ranker needs a real pool
# to choose from, not just the backend's top few.
RAW_POOL_SIZE = 20

# Minimum seconds between consecutive requests to the same backend, so a
# single process making several searches in a row (an agent loop, e.g.)
# doesn't itself trigger the kind of burst that gets rate-limited.
MIN_REQUEST_INTERVAL = 2.0


class SearchBlockedError(RuntimeError):
    """Raised by a single backend when it appears to be rate-limiting or
    challenging this client instead of returning real results."""


class AllBackendsBlockedError(RuntimeError):
    """Raised by search() when every backend failed."""


_last_request_time: dict[str, float] = {}


def _throttle(backend_name: str) -> None:
    last = _last_request_time.get(backend_name)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time[backend_name] = time.monotonic()


# ---------------------------------------------------------------------
# Tavily backend (real API, free tier -- optional, used first if configured)
# ---------------------------------------------------------------------

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _search_tavily(query: str, raw_limit: int) -> list[dict]:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise SearchBlockedError("TAVILY_API_KEY not set")

    resp = requests.post(
        TAVILY_SEARCH_URL,
        json={
            "api_key": api_key,
            "query": query,
            "max_results": raw_limit,
            "include_raw_content": True,
        },
        timeout=20,
    )
    if resp.status_code == 429:
        raise SearchBlockedError("Tavily rate-limited (429)")
    resp.raise_for_status()

    results = []
    for item in resp.json().get("results", []):
        url = item.get("url", "")
        if not url.startswith("http"):
            continue
        # Tavily already returns extracted page content -- carrying it as
        # "text" lets the pipeline skip re-fetching this URL entirely.
        results.append(
            {
                "title": item.get("title", ""),
                "url": url,
                "snippet": (item.get("content") or "")[:300],
                "text": item.get("raw_content") or item.get("content") or "",
            }
        )
    return results


# ---------------------------------------------------------------------
# Brave Search backend (real API, free tier -- optional)
# ---------------------------------------------------------------------

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def _search_brave(query: str, raw_limit: int) -> list[dict]:
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        raise SearchBlockedError("BRAVE_API_KEY not set")

    resp = requests.get(
        BRAVE_SEARCH_URL,
        params={"q": query, "count": min(raw_limit, 20)},
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        timeout=10,
    )
    if resp.status_code == 429:
        raise SearchBlockedError("Brave rate-limited (429)")
    resp.raise_for_status()

    results = []
    for item in resp.json().get("web", {}).get("results", []):
        url = item.get("url", "")
        if not url.startswith("http"):
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("description", ""),
            }
        )
    return results


# ---------------------------------------------------------------------
# DuckDuckGo backend
# ---------------------------------------------------------------------

DDG_HTML_URL = "https://html.duckduckgo.com/html/"


def _resolve_ddg_redirect(href: str) -> str:
    """DuckDuckGo's html endpoint wraps result links in a redirect;
    pull the real target out of the `uddg` query param when present."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path == "/l/":
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def _search_duckduckgo(query: str, raw_limit: int) -> list[dict]:
    resp = requests.post(
        DDG_HTML_URL, data={"q": query}, headers=HEADERS, timeout=10
    )
    resp.raise_for_status()
    if resp.status_code != 200:
        raise SearchBlockedError(
            f"DuckDuckGo returned status {resp.status_code} instead of a "
            "results page -- likely rate-limited."
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        snippet_el = result.select_one(".result__snippet")
        if not link or not link.get("href"):
            continue
        url = _resolve_ddg_redirect(link["href"])
        if not url.startswith("http"):
            continue
        results.append(
            {
                "title": link.get_text(strip=True),
                "url": url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
        if len(results) >= raw_limit:
            break
    return results


# ---------------------------------------------------------------------
# Bing backend
# ---------------------------------------------------------------------

BING_SEARCH_URL = "https://www.bing.com/search"


def _decode_bing_redirect(href: str) -> str:
    """Bing wraps results in /ck/a?...&u=a1<base64url-no-padding>; decode
    the real target out of it. Falls back to the raw href if decoding
    fails or the link isn't a redirect."""
    parsed = urlparse(href)
    if "bing.com" in parsed.netloc and parsed.path == "/ck/a":
        u = parse_qs(parsed.query).get("u", [None])[0]
        if u and u.startswith("a1"):
            b64 = u[2:]
            padded = b64 + "=" * (-len(b64) % 4)
            try:
                return base64.urlsafe_b64decode(padded).decode(
                    "utf-8", errors="ignore"
                )
            except (ValueError, UnicodeDecodeError):
                pass
    return href


def _search_bing(query: str, raw_limit: int) -> list[dict]:
    # Bing's unauthenticated HTML page has no real query understanding
    # without a full browser session -- rewriting to require the query's
    # specific/technical terms (see relevance.build_precise_query) is
    # what fixes it, confirmed live: raw natural-language queries pulled
    # in "Best Buy" and dictionary spam, the rewritten form didn't.
    bing_query = build_precise_query(query)
    resp = requests.get(
        BING_SEARCH_URL,
        params={"q": bing_query, "mkt": "en-US"},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    if resp.status_code != 200:
        raise SearchBlockedError(
            f"Bing returned status {resp.status_code} instead of a "
            "results page -- likely rate-limited."
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for item in soup.select("li.b_algo"):
        h2 = item.select_one("h2")
        link = h2.select_one("a") if h2 else None
        snippet_el = item.select_one(".b_caption p") or item.select_one("p")
        if not link or not link.get("href"):
            continue
        url = _decode_bing_redirect(link["href"])
        if not url.startswith("http"):
            continue
        results.append(
            {
                "title": link.get_text(strip=True),
                "url": url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
        if len(results) >= raw_limit:
            break
    return results


# ---------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------

# Real APIs (when a key is configured) are tried before the free scraping
# backends -- they're far more reliable, and scraping is a fallback for
# when no key is set up, not the primary path.
SCRAPING_BACKENDS = [
    ("duckduckgo", _search_duckduckgo),
    ("bing", _search_bing),
]


def _get_backends() -> list[tuple[str, callable]]:
    backends = []
    if os.environ.get("TAVILY_API_KEY"):
        backends.append(("tavily", _search_tavily))
    if os.environ.get("BRAVE_API_KEY"):
        backends.append(("brave", _search_brave))
    backends.extend(SCRAPING_BACKENDS)
    return backends


def _fetch_raw_pool(query: str, retries_per_backend: int) -> list[dict]:
    cached = cache.get_search(query)
    if cached is not None:
        return cached

    errors = []
    for name, backend_fn in _get_backends():
        delay = 3.0
        for attempt in range(retries_per_backend + 1):
            _throttle(name)
            try:
                results = backend_fn(query, RAW_POOL_SIZE)
                cache.set_search(query, results)
                return results
            except (SearchBlockedError, requests.RequestException) as e:
                errors.append(f"{name}: {e}")
                if attempt < retries_per_backend:
                    time.sleep(delay)
                    delay *= 2

    raise AllBackendsBlockedError(
        "All search backends failed: " + "; ".join(errors)
    )


def search(query: str, max_results: int = 8, retries_per_backend: int = 1) -> list[dict]:
    """Return up to `max_results` results as [{title, url, snippet}, ...],
    ranked by relevance to `query` (not just whichever backend's raw
    order).

    Tries each backend in BACKENDS in order (with throttling + backoff
    per backend), falling through to the next one if a backend is
    blocked. Raises AllBackendsBlockedError only if every backend fails.
    Results are cached to disk per-query for cache.SEARCH_TTL.
    """
    raw_pool = _fetch_raw_pool(query, retries_per_backend)
    return filter_and_rank(query, raw_pool, max_results)
