"""Core orchestration: search -> fetch -> synthesize.

Returns plain, JSON-serializable data so this can be used from the CLI,
imported as a library, or wired up as an agent tool.

Error contract: a successful result has no "error" key -- query/answer/
sources only, unchanged from before. A failed result keeps those same
three keys (so callers that only ever read result["answer"] still work)
and adds "error" set to one of a fixed set of machine-readable codes:

    missing_api_key   GROQ_API_KEY isn't configured; nothing was attempted.
    no_results        Every backend answered but found nothing relevant --
                       not blocked, just nothing there.
    search_blocked     At least one backend actually rate-limited or
                       challenged this client (or every backend errored
                       for some other transport reason).
    fetch_failed       Search succeeded, but content couldn't be read
                       from any of the results.
    synthesis_failed   Sources were fetched, but the Groq call itself
                       failed (bad key, Groq outage, Groq-side rate limit).

This is what lets a caller (e.g. an agent orchestrator) distinguish
"nothing to find" from "temporarily broken" from "not configured" without
parsing prose out of the answer field.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from search_agent.fetch import fetch_page_text
from search_agent.search import AllBackendsBlockedError, search
from search_agent.synthesize import DEFAULT_MODEL, synthesize_answer


def _fetch_all(results: list[dict], workers: int = 6) -> list[dict]:
    # A result can already carry full page content (Tavily's API returns
    # it directly) -- no need to re-fetch those URLs ourselves.
    sources = [r for r in results if r.get("text")]
    need_fetch = [r for r in results if not r.get("text")]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_result = {
            pool.submit(fetch_page_text, r["url"]): r for r in need_fetch
        }
        for future in as_completed(future_to_result):
            result = future_to_result[future]
            text = future.result()
            if text:
                sources.append({**result, "text": text})
    return sources


def run_pipeline(query: str, num_results: int = 6, model: str = DEFAULT_MODEL) -> dict:
    """Search the web for `query`, scrape the top results, and synthesize a
    cited answer. Returns {query, answer, sources: [{index, title, url}]}
    on success; see the module docstring for the error contract."""
    if not os.environ.get("GROQ_API_KEY"):
        # Checked up front rather than letting synthesize_answer raise
        # later -- no point spending a search round-trip on a query that
        # can never reach synthesis, and the caller gets a fast, clean
        # signal instead of a mid-pipeline crash.
        return {
            "query": query,
            "answer": "GROQ_API_KEY is not configured -- cannot synthesize "
                      "an answer. Do not answer from memory.",
            "sources": [],
            "error": "missing_api_key",
        }

    try:
        results = search(query, max_results=num_results)
    except AllBackendsBlockedError as e:
        if e.all_empty:
            return {
                "query": query,
                "answer": "No search results found for this query.",
                "sources": [],
                "error": "no_results",
            }
        return {
            "query": query,
            "answer": f"Search is temporarily unavailable ({e}). "
                      "Do not answer from memory -- tell the user the "
                      "search failed and to try again shortly.",
            "sources": [],
            "error": "search_blocked",
        }
    if not results:
        return {
            "query": query,
            "answer": "No search results found for this query.",
            "sources": [],
            "error": "no_results",
        }

    sources = _fetch_all(results)
    if not sources:
        return {
            "query": query,
            "answer": "Could not fetch content from any search result.",
            "sources": [],
            "error": "fetch_failed",
        }

    try:
        answer = synthesize_answer(query, sources, model=model)
    except Exception as e:
        # Covers a bad/rejected key, a Groq-side outage or rate limit, or
        # a network failure during the synthesis call itself -- anything
        # that gets this far has real sources in hand, so this is
        # specifically "the write-up step broke", not "nothing was found".
        return {
            "query": query,
            "answer": f"Answer synthesis failed ({e}). Do not answer from "
                      "memory -- the search itself succeeded, only the "
                      "write-up step broke.",
            "sources": [],
            "error": "synthesis_failed",
        }

    return {
        "query": query,
        "answer": answer,
        "sources": [
            {"index": i, "title": s["title"], "url": s["url"]}
            for i, s in enumerate(sources, start=1)
        ],
    }
