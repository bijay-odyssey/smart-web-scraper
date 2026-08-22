"""Core orchestration: search -> fetch -> synthesize.

Returns plain, JSON-serializable data so this can be used from the CLI,
imported as a library, or wired up as an agent tool.
"""

from __future__ import annotations

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
    cited answer. Returns {query, answer, sources: [{index, title, url}]}."""
    try:
        results = search(query, max_results=num_results)
    except AllBackendsBlockedError as e:
        return {
            "query": query,
            "answer": f"Search is temporarily unavailable ({e}). "
                      "Do not answer from memory -- tell the user the "
                      "search failed and to try again shortly.",
            "sources": [],
            "error": "search_blocked",
        }
    if not results:
        return {"query": query, "answer": "No search results found for this query.", "sources": []}

    sources = _fetch_all(results)
    if not sources:
        return {
            "query": query,
            "answer": "Could not fetch content from any search result.",
            "sources": [],
        }

    answer = synthesize_answer(query, sources, model=model)

    return {
        "query": query,
        "answer": answer,
        "sources": [
            {"index": i, "title": s["title"], "url": s["url"]}
            for i, s in enumerate(sources, start=1)
        ],
    }
