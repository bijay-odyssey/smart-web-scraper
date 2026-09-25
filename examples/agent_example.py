"""Minimal proof that search_agent works as a callable tool, not just a
standalone script.

A small tool-calling loop: the LLM decides on its own whether it needs to
search the web, calls the `web_search` tool from search_agent.tool if so,
and then answers using the result. This is the same pattern any local
agent framework (LangChain, a hand-rolled ReAct loop, etc.) would use to
plug this project in as a live-web-search capability.

Usage:
    python examples/agent_example.py "your question here"
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from groq import Groq

from search_agent.tool import TOOL_SCHEMA, execute_tool_call

# Note: openai/gpt-oss models carry built-in "browser" tool tokens from
# their training format and can hallucinate phantom tool calls (e.g.
# "web_open") on the follow-up turn of a tool-calling loop. Qwen3 doesn't
# have that quirk, so it's used here for the agent's decision-making;
# gpt-oss-120b is still used for synthesis (search_agent/synthesize.py),
# where no tools are involved and it performs well.
MODEL = os.environ.get("AGENT_MODEL", "qwen/qwen3.8-27b")

_THINK_TAG_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Qwen3 emits its chain-of-thought inline in <think> tags; drop it
    for the user-facing answer."""
    return _THINK_TAG_RE.sub("", text).strip()


SYSTEM_PROMPT = """\
You have a web_search tool. It already returns a synthesized, cited \
answer built from real sources -- not a raw link list -- so one call is \
normally enough for a topic. Base your final answer only on what its \
"sources" actually contain, and keep citing with [n] the way they \
appear in the tool result.

Only call it again if the first call returned zero sources/an error, or \
the question has a genuinely separate follow-up the first call didn't \
cover. Do not re-run near-duplicate searches to "gather more coverage" \
on an already-answered topic -- after at most 2 calls, answer with what \
you have rather than continuing to search.

If a tool call returns zero sources or an error, do NOT fall back to \
answering from your own memory as though it were current or verified. \
Instead, tell the user the search failed (or found nothing) and that \
you can't give a grounded, up-to-date answer right now.
"""


def run_agent(question: str, max_turns: int = 6) -> str:
    load_dotenv()
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    last_tool_answer = None

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[TOOL_SCHEMA],
            temperature=0.2,
        )
        reply = response.choices[0].message
        messages.append(reply)

        if not reply.tool_calls:
            return _strip_thinking(reply.content or "")

        for call in reply.tool_calls:
            args = json.loads(call.function.arguments)
            print(
                f"  [agent called web_search(query={args.get('query')!r}, "
                f"num_results={args.get('num_results', 6)})]",
                file=sys.stderr,
            )
            result = execute_tool_call(call.function.name, args)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )
            parsed = json.loads(result)
            if parsed.get("sources"):
                last_tool_answer = parsed["answer"]

    # The model can be indecisive and keep re-searching instead of
    # answering (observed live with Qwen3 on broad comparison-style
    # questions). Rather than a dead-end error, fall back to the last
    # genuinely sourced tool result -- web_search already returns a
    # synthesized, cited answer per call, so this is still a real,
    # grounded answer, just without the outer model's final polish.
    if last_tool_answer:
        return (
            "(The agent kept re-searching instead of finalizing an answer "
            "-- showing the most recent search result directly.)\n\n"
            + last_tool_answer
        )
    return "Search did not return any usable sources after multiple attempts."


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "What are the best free LLM APIs right now?"
    print(run_agent(question))
