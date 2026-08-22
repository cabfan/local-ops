@echo off
setlocal
rem 总控台 (Console) - Windows launcher (equivalent to start.command / start.sh)
rem Double-click to run: listens on 127.0.0.1:9600 and opens the browser.
cd /d "%~dp0"

set "PY_CMD="
where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD where python3 >nul 2>nul && set "PY_CMD=python3"
if not defined PY_CMD (
    echo Error: Python 3 not found. Install Python 3.12 or newer.
    pause
    exit /b 127
)

%PY_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo Error: Console requires Python 3.12 or newer.
    pause
    exit /b 126
)

%PY_CMD% server.py
endlocal
