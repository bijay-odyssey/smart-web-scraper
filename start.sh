#!/usr/bin/env bash
# One-shot setup + smoke test: creates the venv if needed, installs
# dependencies, checks for a configured GROQ_API_KEY, and runs a demo
# search so you can see it actually working end to end.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python -m venv .venv
fi

if [ -f ".venv/bin/activate" ]; then
    VENV_PY=".venv/bin/python"
else
    VENV_PY=".venv/Scripts/python.exe"
fi

echo "Installing dependencies..."
"$VENV_PY" -m pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example."
    echo "Add your GROQ_API_KEY (free at https://console.groq.com) to .env, then run this script again."
    exit 0
fi

if grep -qE "^GROQ_API_KEY=(groq_api_key_here)?$" .env; then
    echo ""
    echo "GROQ_API_KEY is not set in .env yet."
    echo "Add it (free at https://console.groq.com), then run this script again."
    exit 0
fi

echo ""
echo "Setup complete. Running a demo search..."
echo ""
"$VENV_PY" -m search_agent.cli "best free tools to use as llm for my local agent project"

echo ""
echo "Try your own query:"
echo "  $VENV_PY -m search_agent.cli \"your query here\""
