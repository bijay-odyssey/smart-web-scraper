"""Disk-backed cache for search results and fetched page text.

The CLI runs as a fresh process per invocation, and an agent loop can
issue several similar searches in one run -- without persistence across
those, every query re-hits the same fragile free scraping backends that
already proved they rate-limit under repeated use. Caching to disk
means an identical (or near-identical, for the agent's own retries)
query is instant and puts zero additional load on DuckDuckGo/Bing.
"""

from __future__ import annotations

from pathlib import Path

from diskcache import Cache

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

SEARCH_TTL = 60 * 60        # 1 hour: rankings don't change minute to minute
FETCH_TTL = 6 * 60 * 60     # 6 hours: page content is even more stable

_cache = Cache(str(CACHE_DIR))
_enabled = True


def set_enabled(enabled: bool) -> None:
    """Toggle cache reads (writes still happen so later runs benefit).
    Used by the CLI's --no-cache flag to force a fresh lookup."""
    global _enabled
    _enabled = enabled


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def get_search(query: str) -> list[dict] | None:
    if not _enabled:
        return None
    return _cache.get(f"search:{_normalize_query(query)}")


def set_search(query: str, results: list[dict]) -> None:
    _cache.set(f"search:{_normalize_query(query)}", results, expire=SEARCH_TTL)


def get_fetch(url: str) -> str | None:
    if not _enabled:
        return None
    return _cache.get(f"fetch:{url}")


def set_fetch(url: str, text: str) -> None:
    _cache.set(f"fetch:{url}", text, expire=FETCH_TTL)
