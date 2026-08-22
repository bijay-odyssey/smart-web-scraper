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
    string, ready to feed back to an LLM as a tool result message."""
    result = run_pipeline(query, num_results=num_results)
    return json.dumps(result)


def execute_tool_call(function_name: str, arguments: dict) -> str:
    """Dispatch a tool call by name to its implementation."""
    if function_name == "web_search":
        return web_search(
            query=arguments["query"],
            num_results=arguments.get("num_results", 6),
        )
    raise ValueError(f"Unknown tool: {function_name}")
