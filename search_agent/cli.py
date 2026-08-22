"""CLI: search the web for a keyword, scrape top results, synthesize an answer.

Usage:
    python -m search_agent.cli "best free llm tools for local agents"
    python -m search_agent.cli "best free llm tools" --json > result.json
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

from search_agent import cache
from search_agent.pipeline import run_pipeline
from search_agent.synthesize import DEFAULT_MODEL

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

console = Console()


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="What to search for")
    parser.add_argument(
        "-n", "--num-results", type=int, default=6,
        help="Number of search results to fetch (default: 6)",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Groq model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--show-sources", action="store_true",
        help="Print the list of fetched sources before the answer",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print machine-readable JSON instead of formatted text "
             "(for piping into scripts or other tools)",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Force a fresh lookup instead of reusing a cached result "
             "from the last hour",
    )
    args = parser.parse_args()

    if args.no_cache:
        cache.set_enabled(False)

    if not args.json:
        console.print(f"[bold cyan]Searching:[/bold cyan] {args.query}")

    result = run_pipeline(args.query, num_results=args.num_results, model=args.model)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if not result["sources"]:
        console.print(f"[red]{result['answer']}[/red]")
        return

    if args.show_sources:
        for src in result["sources"]:
            console.print(f"[bold]{src['index']}. {src['title']}[/bold] — {src['url']}")
        console.print()

    console.print(Markdown(result["answer"]))


if __name__ == "__main__":
    main()
