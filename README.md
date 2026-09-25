# Smart Web Scraper

A web search tool that actually answers your question instead of handing you ten blue links to click through yourself.

You give it a query — even a full sentence like *"best free tools to use as an LLM for my local agent project"* — and it searches the web, pulls the real content off the top results, and gives you back a synthesized answer with inline citations pointing at the actual source pages.

I built this after putting together a smaller scraper (scrape one review site, run some EDA on it) and wanting to see what a general-purpose version would look like — not pulling structured data off a single site, but actually searching, reading, and synthesizing across the open web the way you would if you opened ten tabs and read them yourself.

## Why it's not just "type into a search box"

Early on I tested this exact question: if I can just Google something or ask ChatGPT, why would I run my own scraper? Turns out the honest answer depends on how you use it.

As a website you visit to ask a question, it loses to Google or ChatGPT every time, and I'm not going to pretend otherwise — I hit a DuckDuckGo rate limit mid-testing and had to build fallback handling for it, which a polished product doesn't force you to think about.

Where it actually wins is as **infrastructure you own**: a function you can call from your own code, for free, with no subscription — which a website can't be for you at any price. Every one of the OpenAI/Groq/Ollama-style tool-calling agents out there needs a "search the web" capability, and this is a free, self-hosted one you can drop straight in and inspect/modify however you want.

## What it does

- Searches across a tiered backend chain — Tavily and Brave (real search APIs, generous free tiers) if you've set up keys, falling back automatically to DuckDuckGo/Bing scraping if you haven't
- Re-ranks results against the actual query instead of trusting a backend blindly — an unauthenticated search endpoint's ranking can be surprisingly bad (I once got Best Buy and a dictionary definition of "best" back for a query about local LLM tools)
- Pulls real page content, including from JS-heavy sites a plain HTTP request can't see through (falls back to a server-rendering reader when a static fetch comes back suspiciously thin)
- Synthesizes a cited answer via Groq, with every claim traceable back to a specific source URL
- Ships three ways: a CLI, a `--json` mode for scripting, and an importable tool with a standard function-calling schema so any LLM agent can call it directly
- Caches results to disk so repeat or near-duplicate queries don't hit the same backends twice

## Quick start

```bash
git clone https://github.com/bijay-odyssey/smart-web-scraper.git
cd smart-web-scraper
./start.sh        # Windows: start.bat
```

First run creates the virtualenv, installs dependencies, and writes `.env` from the template, then stops and tells you to add a `GROQ_API_KEY`. Add it (free at [console.groq.com](https://console.groq.com)) and run the script again — it'll finish setup and run a demo search so you can see it actually working.

## Manual setup

If you'd rather do it by hand instead of using the start script:

```bash
python -m venv .venv
.venv\Scripts\activate      # on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then fill in `.env`:

- `GROQ_API_KEY` — required, free at [console.groq.com](https://console.groq.com)
- `TAVILY_API_KEY` / `BRAVE_API_KEY` — optional, both free-tier, and make search meaningfully more reliable than scraping alone

## Usage

```bash
python -m search_agent.cli "best free tools to use as llm for my local agent project"
```

Flags:

| Flag | What it does |
|---|---|
| `-n, --num-results` | How many pages to pull (default 6) |
| `--json` | Machine-readable output, for piping into other tools |
| `--show-sources` | Print the source list before the answer |
| `--no-cache` | Force a fresh lookup instead of a cached result |
| `--model` | Override the Groq model used for synthesis |

## Using it as an agent tool

The whole point of `search_agent/tool.py` is that it's not tied to the CLI — it's a plain Python function with an OpenAI-style tool schema attached, so it drops into any tool-calling agent loop:

```python
from search_agent.tool import TOOL_SCHEMA, execute_tool_call

# TOOL_SCHEMA goes straight into your `tools=[...]` list for Groq/OpenAI/Ollama
# execute_tool_call("web_search", {"query": "...", "num_results": 6}) runs it
```

`examples/agent_example.py` is a working demo: an LLM decides on its own whether it needs to search, calls the tool if so, and answers from the result — including handling a search failure without making anything up.

## Machine interface

This is the contract for anything that imports `search_agent.tool` directly instead of shelling out to the CLI — the Python surface is the stable interface; the CLI is a wrapper around the same `run_pipeline()` call underneath, so its `--json` output has the identical shape documented here.

### Tool schema

`search_agent.tool.TOOL_SCHEMA` is a standard OpenAI-style function schema:

```json
{
  "type": "function",
  "function": {
    "name": "web_search",
    "description": "Search the live web for a query and return a synthesized, cited answer...",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "The search query."},
        "num_results": {"type": "integer", "description": "How many web pages to search and read (default 6)."}
      },
      "required": ["query"]
    }
  }
}
```

Call it via `execute_tool_call("web_search", {"query": "...", "num_results": 6})`, which returns a JSON **string** (ready to drop straight into a `role: tool` message). `num_results` is optional and defaults to 6.

### Return shape

A successful call returns exactly this shape — unchanged since this project's first version, and it will stay that way; new failure modes get their own field, not a reshaped success case:

```json
{
  "query": "groq api free tier limits",
  "answer": "1. Groq's free-tier API is available without a credit card...\n\n**Sources**\n\n[1] https://...",
  "sources": [
    {"index": 1, "title": "Groq Free Tier 2026: ...", "url": "https://..."}
  ]
}
```

A failed call keeps the same three keys (so code that only ever reads `result["answer"]` still works without a KeyError) and adds a fourth: `"error"`, set to one of a fixed set of codes. **The presence of the `error` key is the discriminator** — check for it rather than pattern-matching the `answer` text, which is prose meant for a human/LLM, not a machine.

| `error` value | What actually happened | `sources` |
|---|---|---|
| *(key absent)* | Success | populated |
| `missing_api_key` | `GROQ_API_KEY` isn't set. Caught before any search is attempted, so this is fast — no wasted network calls. | `[]` |
| `no_results` | Every configured backend answered successfully but found nothing relevant. Not a block, not an error — genuinely nothing there. | `[]` |
| `search_blocked` | At least one backend actually rate-limited or challenged this client (or errored for some other transport reason), and every backend in the chain ended up failing. | `[]` |
| `fetch_failed` | Search found results, but page content couldn't be read from any of them. | `[]` |
| `synthesis_failed` | Sources were fetched successfully, but the Groq call itself failed (bad/rejected key, Groq-side outage, Groq-side rate limit). | `[]` |
| `internal_error` | Catch-all for anything genuinely unanticipated. If you see this in practice, it's worth a bug report. | `[]` |

This is a real, verified distinction, not just a label — `no_results` and `search_blocked` used to collapse into the same response before this was added, because an empty result and a rate-limited backend were handled identically internally (on purpose, for retry/fallthrough) but were indistinguishable from the outside. They're still handled identically internally; only the outward classification changed.

`execute_tool_call` never raises for a runtime condition — every case above comes back as a parseable JSON string, including cases this project can't fully anticipate (`internal_error` is the backstop). The one deliberate exception: an unrecognized `function_name` raises `ValueError`. That's a caller wiring bug, not something a search can fail at, so it's kept as a real exception instead of being folded into the error codes above.

### CLI `--json` shape

`python -m search_agent.cli "<query>" --json` prints the exact same dict as `run_pipeline()`/`execute_tool_call()` returns, `json.dumps(..., indent=2)`'d to stdout — same keys, same `error` codes, nothing added or renamed for the CLI specifically. A real captured example:

```json
{
  "query": "groq api free tier limits",
  "answer": "1. Groq's free-tier API is available without a credit card and applies rate limits...",
  "sources": [
    {"index": 1, "title": "Groq Free Tier 2026: 1,000 Requests a Day, Llama Is Gone", "url": "https://klymentiev.com/blog/groq-pricing"},
    {"index": 2, "title": "Groq Pricing 2026: Per-Model Rates, Free Tier, Batch ...", "url": "https://www.layer3labs.io/guides/groq-pricing"}
  ]
}
```

### Cache behaviour

`search_agent/cache.py` disk-caches two things, independently:

- **Search results** (the raw backend pool, pre-ranking) — 1 hour TTL, keyed by normalized query text
- **Fetched page text** — 6 hour TTL, keyed by URL

Both are genuinely fast on a hit — measured at 0.00s for a repeat query's search and fetch stages, versus several seconds cold. **What is *not* cached: synthesis.** Every call makes a fresh Groq request to write the answer text, cache hit or not — measured at 18.4s in isolation on one run. So a "repeat" query is not meaningfully faster end to end than a fresh one; only the search+fetch portion of the latency goes away.

The cache lives at `<project root>/.cache/` (a `diskcache` SQLite store). It's created — file and all — the moment `search_agent.tool` (or anything importing it) is imported, not lazily on first search. Importing the module also runs `load_dotenv()` (reads `.env` into the process environment); nothing else happens at import time — no network calls, no other file writes.

`--no-cache` on the CLI (or `search_agent.cache.set_enabled(False)` at the Python level) disables cache *reads* for that run; writes still happen so later calls benefit.

## How it's put together

```
search_agent/
  search.py       tiered backend chain (Tavily -> Brave -> DuckDuckGo -> Bing) + relevance ranking
  relevance.py     scores/reranks results against the query; rewrites queries for keyword-only backends
  fetch.py         pulls page text, with a JS-rendering fallback for content a static request can't see
  cache.py         disk cache for search results and fetched pages
  synthesize.py    turns scraped sources into a cited answer via Groq
  pipeline.py      wires search -> fetch -> synthesize together
  tool.py          agent-callable interface (schema + executor)
  cli.py           command-line entry point
examples/
  agent_example.py  a minimal tool-calling agent that actually uses search_agent.tool
```

## What I'd still improve

- DuckDuckGo and Bing scraping are inherently fragile — free search APIs (Tavily/Brave) fix this when configured, but scraping is still the fallback path if you don't set them up
- The example agent's own free-text answers don't always keep citations as cleanly as the core pipeline does
- Synthesis isn't cached (search and page fetches are) — a repeat query still pays the full Groq generation cost every time, which dominates total latency
- No test suite yet — everything's been verified by hand against live queries so far

## Skills demonstrated

Web scraping, Python, API integration, LLM tool-calling and agent design, search relevance ranking, caching and rate-limit handling, CLI design.
