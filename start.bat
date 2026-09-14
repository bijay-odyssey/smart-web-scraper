@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing dependencies...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt

if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo Created .env from .env.example.
    echo Add your GROQ_API_KEY ^(free at https://console.groq.com^) to .env, then run this script again.
    exit /b 0
)

set NEEDS_KEY=1
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if "%%A"=="GROQ_API_KEY" (
        if not "%%B"=="" if not "%%B"=="groq_api_key_here" set NEEDS_KEY=0
    )
)

if "%NEEDS_KEY%"=="1" (
    echo.
    echo GROQ_API_KEY is not set in .env yet.
    echo Add it ^(free at https://console.groq.com^), then run this script again.
    exit /b 0
)

echo.
echo Setup complete. Running a demo search...
echo.
.venv\Scripts\python.exe -m search_agent.cli "best free tools to use as llm for my local agent project"

echo.
echo Try your own query:
echo   .venv\Scripts\python.exe -m search_agent.cli "your query here"
