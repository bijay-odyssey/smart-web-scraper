"""Agent-callable interface: an OpenAI-style function/tool schema plus an
executor, so any tool-calling agent (Groq, OpenAI, Ollama, LangChain, a
hand-rolled loop) can register this as a live web-search capability.
"""

from __future__ import annotations

import json

from search_agent.pipeline import run_pipeline

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the live web for a query and return a synthesized, "
            "cited answer built from current real pages (news, docs, "
            "product/pricing pages, comparisons, etc). Use this whenever "
            "you need up-to-date or factual information you don't "
            "already know."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "num_results": {
                    "type": "integer",
                    "description": "How many web pages to search and read (default 6).",
                },
            },
            "required": ["query"],
        },
    },
}


def web_search(query: str, num_results: int = 6) -> str:
    """Run the search -> fetch -> synthesize pipeline and return a JSON
    string, ready to feed back to an LLM as a tool result message.

    Never raises for a runtime failure (missing key, every backend
    blocked, fetch failure, synthesis failure) -- run_pipeline already
    turns each of those into a JSON-serializable dict with an "error"
    code (see pipeline.py's module docstring for the exact set). This
    wraps it in a final catch-all so a genuinely unanticipated exception
    still comes back as a string instead of crossing the tool boundary
    as a raised exception -- the one thing this deliberately does NOT
    catch is a bad `function_name` in execute_tool_call below, which is
    a caller bug, not a runtime condition, and should fail loudly.
    """
    try:
        result = run_pipeline(query, num_results=num_results)
    except Exception as e:
        result = {
            "query": query,
            "answer": f"Unexpected internal error: {e}. Do not answer "
                      "from memory.",
            "sources": [],
            "error": "internal_error",
        }
    return json.dumps(result)


def execute_tool_call(function_name: str, arguments: dict) -> str:
    """Dispatch a tool call by name to its implementation.

    Raises ValueError for an unrecognized function_name -- that's a
    caller/wiring bug, not something a search can fail at, so it's kept
    as a real exception rather than folded into the JSON error contract
    that web_search() uses for runtime failures.
    """
    if function_name == "web_search":
        return web_search(
            query=arguments["query"],
            num_results=arguments.get("num_results", 6),
        )
    raise ValueError(f"Unknown tool: {function_name}")
