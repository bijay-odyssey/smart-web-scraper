"""Turn a set of scraped sources into a synthesized answer via Groq."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from groq import Groq

# Loaded here, not just in cli.py, so importing this module directly (as
# an agent framework would via search_agent.tool) works without the
# caller needing to know to call load_dotenv() first.
load_dotenv()

DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

SYSTEM_PROMPT = """\
You are a research assistant that answers a user's query using ONLY the \
provided sources. Be concrete and practical: name specific tools, \
products, or options; give key facts (pricing, free tiers, capabilities, \
limitations) when the sources mention them; and skip anything the \
sources don't support rather than guessing.

Format your answer as:
1. A short intro sentence.
2. A bullet list, one per recommendation/finding, each with a bolded \
name, a 1-3 sentence description, and an inline citation.
3. A "Sources" section at the end mapping each citation number to its URL.

Citations MUST use the exact plain format [1], [2], etc. — a bare \
number in square brackets, nothing else inside the brackets (no daggers, \
line refs, or other symbols).

If the sources don't contain enough to answer well, say so plainly \
instead of inventing details.
"""


def _build_sources_block(sources: list[dict], max_chars_per_source: int) -> str:
    blocks = []
    for i, src in enumerate(sources, start=1):
        text = src.get("text") or src.get("snippet") or ""
        text = text[:max_chars_per_source]
        blocks.append(
            f"[{i}] {src['title']}\nURL: {src['url']}\nContent:\n{text}\n"
        )
    return "\n---\n".join(blocks)


def synthesize_answer(
    query: str,
    sources: list[dict],
    model: str = DEFAULT_MODEL,
    max_chars_per_source: int = 3000,
) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to a .env file or your "
            "environment (see .env.example)."
        )

    client = Groq(api_key=api_key)
    sources_block = _build_sources_block(sources, max_chars_per_source)

    user_prompt = f"Query: {query}\n\nSources:\n{sources_block}"

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    return completion.choices[0].message.content
