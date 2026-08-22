"""Score and filter raw search results against the query.

Search backends don't guarantee relevance -- confirmed directly in
testing: Bing's unauthenticated HTML endpoint returned "Best Buy" and
dictionary definitions of "best" for a query about free local-LLM
tools, because without full browser/session context it degraded to
naive keyword matching where a common word dominated. This module is a
backend-agnostic second pass: keep only results that actually share
substantive vocabulary with the query, ranked by how much they share.
"""

from __future__ import annotations

import re

GENERIC_TERMS = {
    "best", "good", "great", "top", "better", "ideal", "perfect",
    "free", "cheap", "easy", "simple", "fast", "new",
    "tool", "tools", "option", "options", "way", "ways",
    "thing", "things", "project", "guide", "list",
}

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "for", "with", "as", "at", "by", "from",
    "and", "or", "but", "if", "so", "than", "that", "this", "these",
    "those", "it", "its", "my", "your", "our", "their", "his", "her",
    "i", "you", "we", "they", "he", "she", "do", "does", "did",
    "can", "could", "should", "would", "will", "shall", "may", "might",
    "what", "which", "who", "whom", "how", "when", "where", "why",
    "use", "using", "used", "get", "find", "about",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(word: str) -> str:
    """Crude singular/plural folding (llm/llms, agent/agents, tool/tools)
    so exact-string matching doesn't miss otherwise-perfect matches."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokenize(text: str) -> set[str]:
    words = _WORD_RE.findall(text.lower())
    return {_normalize(w) for w in words if w not in _STOPWORDS and len(w) > 1}


def build_precise_query(query: str) -> str:
    """Rewrite a natural-language query for keyword-only backends that
    lack real query understanding without a full browser session.

    Confirmed live, and the cause isolated by direct testing: Bing's
    unauthenticated HTML endpoint weights early query terms far more
    heavily than later ones (a `+required` operator made zero measured
    difference -- moving "best" from first word to last word was what
    took results from "Best Buy"/dictionary spam to genuine on-topic
    LLM/agent content). So this moves specific/technical terms to the
    front and generic/subjective ones (best, free, tools, ...) to the
    back, instead of trying to mark anything as required.
    """
    words = _WORD_RE.findall(query.lower())
    seen = set()
    specific, generic = [], []
    for w in words:
        if w in _STOPWORDS or w in seen or len(w) <= 1:
            continue
        seen.add(w)
        (generic if w in GENERIC_TERMS else specific).append(w)
    ordered = specific + generic
    return " ".join(ordered) if ordered else query


def score_result(query_terms: set[str], result: dict) -> float:
    """Fraction of substantive query terms that appear in the result's
    title + snippet. 0.0 (no overlap) to 1.0 (every term present)."""
    if not query_terms:
        return 1.0
    haystack = _tokenize(result.get("title", "") + " " + result.get("snippet", ""))
    hits = len(query_terms & haystack)
    return hits / len(query_terms)


def filter_and_rank(query: str, results: list[dict], max_results: int, min_score: float = 0.2) -> list[dict]:
    """Keep results with meaningful term overlap with the query, sorted by
    relevance, capped to max_results. Falls back to the original order
    (still capped) if scoring would eliminate everything -- a strict
    filter can be wrong for short or unusually-phrased queries, and
    returning nothing is worse than returning the backend's raw guess."""
    query_terms = _tokenize(query)
    scored = [(score_result(query_terms, r), r) for r in results]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    kept = [r for score, r in scored if score >= min_score]
    if not kept:
        return results[:max_results]

    return kept[:max_results]
