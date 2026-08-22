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

## Setup

```bash
git clone https://github.com/bijay-odyssey/smart-web-scraper.git
cd smart-web-scraper
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
- No test suite yet — everything's been verified by hand against live queries so far

## Skills demonstrated

Web scraping, Python, API integration, LLM tool-calling and agent design, search relevance ranking, caching and rate-limit handling, CLI design.
